import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from html import escape
import logging
import os
from pathlib import Path
import random
import re
import shlex
from typing import Literal, TypeVar
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError
from pydantic import BaseModel, Field

# Pricing as of 2025-10-10 (see https://platform.openai.com/docs/pricing?latest-pricing=standard)
#
# gpt-3.5-turbo (4K tokens): costs $0.0035 per 1K tokens (in: $0.0015, out: $0.002)
# gpt-3.5-turbo-16k (16K tokens): costs $0.007 per 1K tokens (in: $0.003, out: $0.004)
# gpt-4 (8K tokens): costs $0.09 per 1K tokens (in: $0.03, out: $0.06)
# gpt-4-32k (32K tokens), costs $0.18 per 1K tokens (in: $0.06, out: $0.12)
# gpt-5 (32K tokens), costs $11.25 per 1M tokens (in: $1.25, out: $10.00))
# gpt-5.4 (272K tokens), costs $17.50 per 1M tokens (in: $2.50, out: $15.00)

logger = logging.getLogger(__name__)

CHURCH_BASE_URL = "https://www.churchofjesuschrist.org"
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0

ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
ResponseVerbosity = Literal["low", "medium", "high"]

OUTLINE_PROMPT: str = """\
Help members of the Church of Jesus Christ of Latter-day Saints understand the key principles and doctrines from General Conference talks.

The user will provide one talk in Markdown format.

Return structured data with:
- summary: one sentence summarizing the talk.
- haiku: a three-line haiku expressing the talk theme.
- key_points: exactly 3 brief major points from the talk, without numbering.
- scriptures_and_gospel_principles: several scriptures, referenced talks, or gospel principles worth studying, without bullet markers.
- questions_to_ponder: several discussion or reflection questions, without bullet markers.
"""

THEMES_PROMPT: str = """\
Help members of the Church of Jesus Christ of Latter-day Saints understand the key principles and doctrines from General Conference.

The user will provide a full listing of summaries of all talks from the conference.

Return structured data with:
- summary: a concise conference-wide summary paragraph or two.
- repeated_doctrines: the repeated doctrines or major themes that should appear as bullet points, without bullet markers.
- haiku: a three-line haiku expressing the conference theme.
- questions_to_ponder: several study or discussion questions rooted in the conference themes, without bullet markers.
"""

KEY_PRINCIPLES_PROMPT: str = """\
Help members of the Church of Jesus Christ of Latter-day Saints understand the key principles and doctrines from General Conference.

The user will provide numbered talk summaries for a full conference.

Return one structured item for every talk in the same order as the input numbering.
Each item must include:
- index: the 1-based talk number from the input.
- title: the talk title as it appears in the input.
- speaker: the speaker as it appears in the input.
- principle: one short sentence describing the talk's key principle as it relates to the conference themes.
"""

STEP0_FETCH_TALK_LIST: int = 0
STEP1_FETCH_TALK_HTML: int = 1
STEP2_WRITE_TALK_STAGE: int = 2
STEP3_WRITE_TALK_MARKDOWN: int = 3
STEP4_WRITE_TALK_OUTLINE: int = 4
STEP5_WRITE_OUTLINES: int = 5
STEP6_WRITE_SUMMARIES: int = 6
STEP7_WRITE_THEMES: int = 7
STEP8_WRITE_REFERENCE_MARKDOWN: int = 8
STEP9_WRITE_REFERENCE_DOCX: int = 9


class OutlineResponse(BaseModel):
    summary: str = Field(description="A one-sentence summary of the talk.")
    haiku: str = Field(description="A three-line haiku expressing the talk theme.")
    key_points: list[str] = Field(description="Exactly three key points from the talk.", min_length=3, max_length=3)
    scriptures_and_gospel_principles: list[str] = Field(
        default_factory=list,
        description="Relevant scriptures, referenced talks, or gospel principles worth studying.",
    )
    questions_to_ponder: list[str] = Field(
        default_factory=list,
        description="Questions a class or individual could ponder before or during a lesson.",
    )


class ThemesResponse(BaseModel):
    summary: str = Field(description="A concise conference-wide summary.")
    repeated_doctrines: list[str] = Field(
        default_factory=list,
        description="Repeated doctrines or major themes from the conference, without bullet markers.",
    )
    haiku: str = Field(description="A three-line haiku expressing the conference theme.")
    questions_to_ponder: list[str] = Field(
        default_factory=list,
        description="Questions for study or discussion rooted in the conference themes.",
    )


class KeyPrincipleEntry(BaseModel):
    index: int = Field(description="The 1-based talk number from the input list.")
    title: str = Field(description="The talk title as it appears in the input.")
    speaker: str = Field(description="The talk speaker as it appears in the input.")
    principle: str = Field(description="A short sentence describing the talk's key principle.")


class KeyPrinciplesResponse(BaseModel):
    key_principles: list[KeyPrincipleEntry] = Field(
        description="One key principle entry for each talk in the conference input.",
    )


@dataclass(frozen=True)
class ResponseRequestSettings:
    max_output_tokens: int | None = None
    reasoning_effort: ReasoningEffort | None = None
    verbosity: ResponseVerbosity | None = None


@dataclass(frozen=True)
class PipelineConfig:
    outline_model: str = "gpt-5.4"
    themes_model: str = "gpt-5"
    key_principles_model: str = "gpt-5"
    outline_request: ResponseRequestSettings = field(
        default_factory=lambda: ResponseRequestSettings(
            max_output_tokens=900,
            reasoning_effort="low",
            verbosity="low",
        )
    )
    themes_request: ResponseRequestSettings = field(
        default_factory=lambda: ResponseRequestSettings(
            max_output_tokens=1400,
            reasoning_effort="low",
            verbosity="low",
        )
    )
    key_principles_request: ResponseRequestSettings = field(
        default_factory=lambda: ResponseRequestSettings(
            max_output_tokens=2200,
            reasoning_effort="low",
            verbosity="low",
        )
    )
    run_until_step: int = STEP9_WRITE_REFERENCE_DOCX
    concurrency: int = 4
    force: bool = False
    retry_max_attempts: int = 10
    retry_max_wait_seconds: float = 60.0
    retry_jitter_ratio: float = 0.25


Command = Sequence[str | Path]
ModelT = TypeVar("ModelT", bound=BaseModel)
ResponseT = TypeVar("ResponseT")
WorkItemT = TypeVar("WorkItemT")


@dataclass(frozen=True)
class ParsedTalkPage:
    title: str
    subtitle: str
    author: str
    role: str
    summary: str
    body_html: str


def load_openai_api_key(key_file: str | Path = "openai.key") -> str:
    env_api_key = os.environ.get("OPENAI_API_KEY")
    if env_api_key:
        return env_api_key
    api_key = Path(key_file).read_text(encoding="utf-8").strip() if Path(key_file).is_file() else None
    if api_key:
        return api_key
    raise RuntimeError("OpenAI API key not found. Set OPENAI_API_KEY or create an openai.key file in the working directory.")


def create_openai_client(api_key: str | None = None, key_file: str | Path = "openai.key") -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key or load_openai_api_key(key_file))


def should_refresh(path: Path, *, force: bool) -> bool:
    return force or not path.exists()


def format_command(command: Command) -> str:
    return shlex.join(str(part) for part in command)


def load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def save_model(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def normalize_text(text: str) -> str:
    return text.replace("\xa0", " ").strip()


def fetch_url_text_sync(url: str, *, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> str:
    request = Request(url, headers={"User-Agent": "general-conference-reference/0.1"})
    with urlopen(request, timeout=timeout) as response:
        encoding = response.headers.get_content_charset("utf-8")
        return response.read().decode(encoding, errors="replace")


async def fetch_url_text(url: str, *, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> str:
    logger.debug("Fetching URL: %s", url)
    return await asyncio.to_thread(fetch_url_text_sync, url, timeout=timeout)


def select_required_text(soup: BeautifulSoup, selector: str, *, context: str) -> str:
    element = soup.select_one(selector)
    if element is None:
        raise ValueError(f"Missing {context} using selector {selector!r}")
    return normalize_text(element.get_text(" ", strip=True))


def select_optional_text(soup: BeautifulSoup, selector: str) -> str:
    element = soup.select_one(selector)
    if element is None:
        return ""
    return normalize_text(element.get_text(" ", strip=True))


def normalize_body_html(body_html: str) -> str:
    soup = BeautifulSoup(body_html, "html.parser")
    container = soup.select_one(".body-block")
    if container is None:
        raise ValueError("Missing talk body block")

    for note_ref in container.select("a.note-ref"):
        note_ref.decompose()

    for link in container.select("a[href]"):
        href = link.get("href", "").strip()
        if href.startswith("/"):
            link["href"] = urljoin(CHURCH_BASE_URL, href)

    return str(container)


def extract_talk_urls_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    talk_urls: list[str] = []
    for link in soup.select(".body nav a[href]"):
        href = link.get("href", "").strip()
        if not href or "-session?" in href:
            continue
        absolute_url = urljoin(CHURCH_BASE_URL, href)
        if absolute_url not in talk_urls:
            talk_urls.append(absolute_url)
    return talk_urls


def parse_talk_html(html: str) -> ParsedTalkPage:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article#main")
    if article is None:
        raise ValueError("Missing talk article content")

    body_block = article.select_one(".body .body-block")
    if body_block is None:
        raise ValueError("Missing talk body block")

    return ParsedTalkPage(
        title=select_required_text(article, ".body h1", context="talk title"),
        subtitle=select_optional_text(article, ".body .subtitle"),
        author=select_required_text(article, ".body .byline .author-name", context="talk author").removeprefix("By "),
        role=select_optional_text(article, ".body .byline .author-role").removeprefix("By "),
        summary=select_optional_text(article, ".body .kicker"),
        body_html=normalize_body_html(str(body_block)),
    )


def render_stage_html(talk_page: ParsedTalkPage) -> str:
    title = talk_page.title if not talk_page.subtitle else f"{talk_page.title} {talk_page.subtitle}"
    role_line = " ".join(part for part in [talk_page.author, talk_page.role] if part).strip()

    lines = [
        f"<h1>{escape(title)}</h1>",
        f"<p><em>{escape(role_line)}</em></p>",
    ]
    if talk_page.summary:
        lines.append(f"<p><em>{escape(talk_page.summary)}</em></p>")
    lines.append(talk_page.body_html)
    return "\n".join(lines).strip() + "\n"


def cleanup_markdown(markdown: str) -> str:
    cleaned = re.sub(r"\[<sup>\s*\d*\s*</sup>\]\([^)]*\)", "", markdown)
    cleaned = re.sub(r"<a\b[^>]*>\s*<sup\b[^>]*>.*?</sup>\s*</a>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = cleaned.replace("](/", f"]({CHURCH_BASE_URL}/")
    cleaned = cleaned.replace('href="/', f'href="{CHURCH_BASE_URL}/')
    return cleaned


def extract_wait_time_seconds(error: BaseException) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        retry_after_ms = headers.get("retry-after-ms")
        if retry_after_ms:
            try:
                return float(retry_after_ms) / 1000.0
            except ValueError:
                pass
        retry_after = headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

    match = re.search(r"try again in (\d+)ms", str(error))
    if match:
        return int(match.group(1)) / 1000.0
    return None


def compute_retry_wait_seconds(*, error: BaseException, attempt: int, config: PipelineConfig) -> float:
    wait_time = extract_wait_time_seconds(error)
    if wait_time is None:
        wait_time = min((2 ** (attempt - 1)) * 0.5, config.retry_max_wait_seconds)
    wait_time += 0.1
    wait_time *= 1 + random.uniform(0, config.retry_jitter_ratio)
    return min(wait_time, config.retry_max_wait_seconds)


async def run_command(command: Command) -> bytes:
    rendered_command = [str(part) for part in command]
    logger.debug("Running command: %s", format_command(command))
    process = await asyncio.create_subprocess_exec(
        *rendered_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {process.returncode}: {format_command(command)}"
            + (f"\n{stderr_text}" if stderr_text else "")
        )
    if stderr_text:
        logger.debug("Command stderr for %s: %s", format_command(command), stderr_text)
    return stdout


def build_structured_response_request(
    *,
    model: str,
    instructions: str,
    input_text: str,
    text_format: type[ModelT],
    request_settings: ResponseRequestSettings,
) -> dict[str, object]:
    request: dict[str, object] = {
        "model": model,
        "instructions": instructions,
        "input": input_text,
        "text_format": text_format,
    }
    if request_settings.max_output_tokens is not None:
        request["max_output_tokens"] = request_settings.max_output_tokens
    if request_settings.reasoning_effort is not None:
        request["reasoning"] = {"effort": request_settings.reasoning_effort}
    if request_settings.verbosity is not None:
        request["verbosity"] = request_settings.verbosity
    return request


async def retry_openai_request(
    func: Callable[..., Awaitable[ResponseT]],
    *args,
    operation: str,
    config: PipelineConfig,
    **kwargs,
) -> ResponseT:
    for attempt in range(1, config.retry_max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError) as error:
            if attempt >= config.retry_max_attempts:
                logger.error("OpenAI request failed for %s after %s attempts: %s", operation, attempt, error)
                raise
            wait_time = compute_retry_wait_seconds(error=error, attempt=attempt, config=config)
            logger.warning(
                "Transient OpenAI error for %s on attempt %s/%s (%s). Retrying in %.2fs.",
                operation,
                attempt,
                config.retry_max_attempts,
                error.__class__.__name__,
                wait_time,
            )
            await asyncio.sleep(wait_time)

    raise AssertionError("retry_openai_request should always return or raise")


async def generate_structured_response(
    client: AsyncOpenAI,
    *,
    model: str,
    instructions: str,
    input_text: str,
    text_format: type[ModelT],
    request_settings: ResponseRequestSettings,
    operation: str,
    config: PipelineConfig,
) -> ModelT:
    response = await retry_openai_request(
        client.responses.parse,
        **build_structured_response_request(
            model=model,
            instructions=instructions,
            input_text=input_text,
            text_format=text_format,
            request_settings=request_settings,
        ),
        operation=operation,
        config=config,
    )
    output = response.output_parsed
    if output is None:
        raise ValueError(f"Empty structured response for {operation} using model={model}")
    return output


async def load_or_generate_structured_output(
    *,
    client: AsyncOpenAI,
    config: PipelineConfig,
    data_file: Path,
    markdown_file: Path,
    model: str,
    instructions: str,
    input_text: str,
    text_format: type[ModelT],
    request_settings: ResponseRequestSettings,
    render_markdown: Callable[[ModelT], str],
    operation: str,
) -> ModelT:
    if data_file.exists() and not config.force:
        logger.debug("Using cached structured data for %s from %s", operation, data_file)
        structured_output = load_model(data_file, text_format)
        if not markdown_file.exists():
            logger.info("Rebuilding missing markdown artifact for %s at %s", operation, markdown_file)
            write_text(markdown_file, render_markdown(structured_output))
        return structured_output

    if markdown_file.exists() and not data_file.exists() and not config.force:
        logger.info("Generating structured cache for %s without overwriting existing markdown at %s", operation, markdown_file)

    structured_output = await generate_structured_response(
        client,
        model=model,
        instructions=instructions,
        input_text=input_text,
        text_format=text_format,
        request_settings=request_settings,
        operation=operation,
        config=config,
    )
    save_model(data_file, structured_output)
    if should_refresh(markdown_file, force=config.force):
        write_text(markdown_file, render_markdown(structured_output))
    return structured_output


async def run_with_concurrency(
    items: Sequence[WorkItemT],
    *,
    limit: int,
    worker: Callable[[WorkItemT], Awaitable[None]],
) -> None:
    semaphore = asyncio.Semaphore(max(1, limit))

    async def bounded_worker(item: WorkItemT) -> None:
        async with semaphore:
            await worker(item)

    await asyncio.gather(*(bounded_worker(item) for item in items))


def render_outline_markdown(outline: OutlineResponse) -> str:
    lines: list[str] = [
        "### Summary",
        "",
        outline.summary.strip(),
        "",
        "### Haiku",
        "",
        outline.haiku.strip(),
        "",
        "### Key Points",
        "",
    ]
    lines.extend(f"{index}. {point.strip()}" for index, point in enumerate(outline.key_points, start=1))
    lines.extend(
        [
            "",
            "### Scriptures and Gospel Principles",
            "",
        ]
    )
    lines.extend(f"- {item.strip()}" for item in outline.scriptures_and_gospel_principles)
    lines.extend(
        [
            "",
            "### Questions to Ponder",
            "",
        ]
    )
    lines.extend(f"- {question.strip()}" for question in outline.questions_to_ponder)
    return "\n".join(lines).strip() + "\n"


def render_themes_markdown(themes: ThemesResponse) -> str:
    lines: list[str] = [
        "### Summary",
        "",
        themes.summary.strip(),
    ]
    if themes.repeated_doctrines:
        lines.append("")
        lines.extend(f"- {item.strip()}" for item in themes.repeated_doctrines)
    lines.extend(
        [
            "",
            "### Haiku",
            "",
            themes.haiku.strip(),
            "",
            "### Questions to Ponder",
            "",
        ]
    )
    lines.extend(f"- {question.strip()}" for question in themes.questions_to_ponder)
    return "\n".join(lines).strip() + "\n"


def ordered_key_principles(key_principles: KeyPrinciplesResponse) -> list[KeyPrincipleEntry]:
    return sorted(key_principles.key_principles, key=lambda entry: entry.index)


def render_key_principles_markdown(key_principles: KeyPrinciplesResponse) -> str:
    lines: list[str] = ["### Key Principles", ""]
    lines.extend(
        f"{entry.index}. *{entry.title} - {entry.speaker}:* {entry.principle.strip()}"
        for entry in ordered_key_principles(key_principles)
    )
    return "\n".join(lines).strip() + "\n"


def render_key_principles_list_markdown(talks: Sequence["Talk"]) -> str:
    lines: list[str] = ["### Key Principles", ""]
    lines.extend(
        f"{talk_index}. {talk.aiprinciple.strip()} ([&ldquo;{talk.title}&rdquo; - {talk.author}]({talk.url}))"
        for talk_index, talk in enumerate(talks, start=1)
    )
    return "\n".join(lines).strip() + "\n"


def render_outlines_markdown(talks: Sequence["Talk"]) -> str:
    lines: list[str] = []
    for talk_index, talk in enumerate(talks, start=1):
        lines.extend(
            [
                f"## {talk_index}. {talk.title} - {talk.author}",
                "",
                f"[{talk.url}]({talk.url})",
                "",
                talk.outline().rstrip(),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_summaries_markdown(talks: Sequence["Talk"]) -> str:
    lines: list[str] = []
    for talk_index, talk in enumerate(talks, start=1):
        lines.extend(
            [
                f"{talk_index}. {talk.title} - {talk.author}",
                "",
                talk.summary,
                "",
                talk.aisummary,
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_reference_markdown(
    *,
    year: str,
    month: str,
    themes_markdown: str,
    key_principles_list_markdown: str,
    outlines_markdown: str,
) -> str:
    lines = [
        f"# General Conference {year}-{month}",
        "",
        "## Themes",
        "",
        themes_markdown.rstrip(),
        "",
        key_principles_list_markdown.rstrip(),
        "",
        "## Talks",
        "",
        outlines_markdown.rstrip(),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


@dataclass
class Talk:
    parent: "GeneralConference" = field(repr=False)
    url: str
    key: str = field(init=False)
    title: str = field(init=False)
    subtitle: str = field(init=False)
    author: str = field(init=False)
    role: str = field(init=False)
    summary: str = field(init=False)
    body: str = field(init=False, repr=False)
    aisummary: str = field(init=False)
    aiprinciple: str = field(init=False)

    def __post_init__(self) -> None:
        self.key = self.url.split("/")[-1].split("?")[0]
        self.title = ""
        self.subtitle = ""
        self.author = ""
        self.role = ""
        self.summary = ""
        self.body = ""
        self.aisummary = ""
        self.aiprinciple = ""

    async def execute(self) -> None:
        if self.parent.config.run_until_step < STEP1_FETCH_TALK_HTML:
            return

        if should_refresh(self.html_file, force=self.parent.config.force):
            logger.debug("Fetching HTML for talk %s from %s", self.key, self.url)
            write_text(self.html_file, await fetch_url_text(self.url))

        talk_page = parse_talk_html(self.html_file.read_text(encoding="utf-8"))
        self.title = talk_page.title
        self.subtitle = talk_page.subtitle
        self.author = talk_page.author
        self.role = talk_page.role
        self.summary = talk_page.summary
        self.body = talk_page.body_html

        if self.parent.config.run_until_step < STEP2_WRITE_TALK_STAGE:
            return

        if should_refresh(self.stage_file, force=self.parent.config.force):
            write_text(self.stage_file, render_stage_html(talk_page))

        if self.parent.config.run_until_step < STEP3_WRITE_TALK_MARKDOWN:
            return

        if should_refresh(self.markdown_file, force=self.parent.config.force):
            markdown_text = (
                await run_command(["pandoc", "-f", "html", "-t", "commonmark", "--wrap", "none", "-o", "-", self.stage_file])
            ).decode("utf-8")
            write_text(self.markdown_file, cleanup_markdown(markdown_text))

    async def generate_ai_outputs(self) -> None:
        if self.parent.config.run_until_step < STEP4_WRITE_TALK_OUTLINE:
            return

        outline = await load_or_generate_structured_output(
            client=self.parent.client,
            config=self.parent.config,
            data_file=self.outline_data_file,
            markdown_file=self.outline_file,
            model=self.parent.config.outline_model,
            instructions=OUTLINE_PROMPT,
            input_text=self.markdown_file.read_text(encoding="utf-8"),
            text_format=OutlineResponse,
            request_settings=self.parent.config.outline_request,
            render_markdown=render_outline_markdown,
            operation=f"outline for talk {self.key}",
        )
        self.aisummary = outline.summary.strip()

    def outline(self) -> str:
        return self.outline_file.read_text(encoding="utf-8")

    @property
    def html_dir(self) -> Path:
        return self.parent.talk_dir("html")

    @property
    def html_file(self) -> Path:
        return self.html_dir / f"{self.key}.html"

    @property
    def markdown_dir(self) -> Path:
        return self.parent.talk_dir("markdown")

    @property
    def markdown_file(self) -> Path:
        return self.markdown_dir / f"{self.key}.md"

    @property
    def outline_dir(self) -> Path:
        return self.parent.talk_dir("outline")

    @property
    def outline_file(self) -> Path:
        return self.outline_dir / f"{self.key}-outline.md"

    @property
    def outline_data_file(self) -> Path:
        return self.outline_dir / f"{self.key}-outline.json"

    @property
    def talk_file(self) -> Path:
        return self.parent.talk_file(self.key)

    @property
    def stage_dir(self) -> Path:
        return self.parent.talk_dir("stage")

    @property
    def stage_file(self) -> Path:
        return self.stage_dir / f"{self.key}-stage.html"

    @property
    def yaml_file(self) -> Path:
        return self.talk_file / f"{self.key}.yaml"


@dataclass
class GeneralConference:
    output_path: Path
    year: str
    month: str
    language: str
    client: AsyncOpenAI = field(default_factory=create_openai_client, repr=False)
    config: PipelineConfig = field(default_factory=PipelineConfig, repr=False)
    talks: list["Talk"] = field(init=False)

    def __post_init__(self) -> None:
        self.output_path = Path(self.output_path)
        self.talks = []

    async def execute(self) -> None:
        talk_urls = await self.fetch()
        self.talks = [Talk(parent=self, url=talk_url) for talk_url in talk_urls]
        logger.info("Processing %s talks for %s-%s", len(self.talks), self.year, self.month)
        await asyncio.gather(*(talk.execute() for talk in self.talks))

        if self.config.run_until_step >= STEP4_WRITE_TALK_OUTLINE:
            logger.info(
                "Generating talk outlines with bounded concurrency=%s using model=%s",
                self.config.concurrency,
                self.config.outline_model,
            )
        await run_with_concurrency(self.talks, limit=self.config.concurrency, worker=lambda talk: talk.generate_ai_outputs())

        await self.dump()

    async def fetch(self) -> list[str]:
        if self.config.run_until_step < STEP0_FETCH_TALK_LIST:
            return []

        if should_refresh(self.talk_list_file, force=self.config.force):
            logger.info("Fetching talk list from %s", self.url)
            conference_html = await fetch_url_text(self.url)
            lines = extract_talk_urls_from_html(conference_html)
            write_text(self.talk_list_file, "\n".join(lines) + "\n")

        talk_urls: list[str] = []
        for talk_url in self.talk_list_file.read_text(encoding="utf-8").splitlines():
            talk_url = talk_url.strip()
            if talk_url:
                talk_urls.append(talk_url)
        return talk_urls

    async def dump(self) -> None:
        if self.config.run_until_step < STEP5_WRITE_OUTLINES:
            return

        outlines_file = self.root_file("outlines.md")
        if should_refresh(outlines_file, force=self.config.force):
            write_text(outlines_file, render_outlines_markdown(self.talks))

        if self.config.run_until_step < STEP6_WRITE_SUMMARIES:
            return

        summaries_file = self.root_file("summaries.md")
        if should_refresh(summaries_file, force=self.config.force):
            write_text(summaries_file, render_summaries_markdown(self.talks))

        if self.config.run_until_step < STEP7_WRITE_THEMES:
            return

        summaries_text = summaries_file.read_text(encoding="utf-8")
        await load_or_generate_structured_output(
            client=self.client,
            config=self.config,
            data_file=self.themes_data_file,
            markdown_file=self.themes_file,
            model=self.config.themes_model,
            instructions=THEMES_PROMPT,
            input_text=summaries_text,
            text_format=ThemesResponse,
            request_settings=self.config.themes_request,
            render_markdown=render_themes_markdown,
            operation=f"conference themes for {self.year}-{self.month}",
        )

        key_principles = await load_or_generate_structured_output(
            client=self.client,
            config=self.config,
            data_file=self.key_principles_data_file,
            markdown_file=self.key_principles_file,
            model=self.config.key_principles_model,
            instructions=KEY_PRINCIPLES_PROMPT,
            input_text=summaries_text,
            text_format=KeyPrinciplesResponse,
            request_settings=self.config.key_principles_request,
            render_markdown=render_key_principles_markdown,
            operation=f"key principles for {self.year}-{self.month}",
        )
        self.apply_key_principles(key_principles)

        key_principles_list_file = self.root_file("key_principles_list.md")
        if should_refresh(key_principles_list_file, force=self.config.force):
            write_text(key_principles_list_file, render_key_principles_list_markdown(self.talks))

        if self.config.run_until_step < STEP8_WRITE_REFERENCE_MARKDOWN:
            return

        reference_markdown_file = self.root_file("reference.md")
        if should_refresh(reference_markdown_file, force=self.config.force):
            write_text(
                reference_markdown_file,
                render_reference_markdown(
                    year=self.year,
                    month=self.month,
                    themes_markdown=self.themes_file.read_text(encoding="utf-8"),
                    key_principles_list_markdown=key_principles_list_file.read_text(encoding="utf-8"),
                    outlines_markdown=outlines_file.read_text(encoding="utf-8"),
                ),
            )

        if self.config.run_until_step < STEP9_WRITE_REFERENCE_DOCX:
            return

        reference_docx_file = self.root_file("reference.docx")
        if should_refresh(reference_docx_file, force=self.config.force):
            logger.info("Writing DOCX output to %s", reference_docx_file)
            await run_command(
                ["pandoc", "-f", "commonmark", "-t", "docx", "-s", "-o", reference_docx_file, reference_markdown_file]
            )

    def apply_key_principles(self, key_principles: KeyPrinciplesResponse) -> None:
        ordered_entries = ordered_key_principles(key_principles)
        indices = [entry.index for entry in ordered_entries]
        expected_indices = list(range(1, len(self.talks) + 1))
        if indices != expected_indices:
            raise ValueError(
                f"Expected key principle indices {expected_indices}, but received {indices} for conference {self.year}-{self.month}"
            )
        for talk, entry in zip(self.talks, ordered_entries, strict=True):
            talk.aiprinciple = entry.principle.strip()

    @property
    def root_dir(self) -> Path:
        root_dir = self.output_path / f"{self.year}{self.month}"
        root_dir.mkdir(parents=True, exist_ok=True)
        return root_dir

    def root_file(self, key: str) -> Path:
        return self.root_dir / key

    @property
    def talks_dir(self) -> Path:
        talks_dir = self.root_dir / "talks"
        talks_dir.mkdir(parents=True, exist_ok=True)
        return talks_dir

    def talk_dir(self, key: str) -> Path:
        directory = self.talks_dir / key
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def talk_file(self, key: str) -> Path:
        directory = self.talks_dir / key
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def talk_list_file(self) -> Path:
        return self.root_file("talk_list.txt")

    @property
    def themes_file(self) -> Path:
        return self.root_file("themes.md")

    @property
    def themes_data_file(self) -> Path:
        return self.root_file("themes.json")

    @property
    def key_principles_file(self) -> Path:
        return self.root_file("key_principles.md")

    @property
    def key_principles_data_file(self) -> Path:
        return self.root_file("key_principles.json")

    @property
    def url(self) -> str:
        return f"https://www.churchofjesuschrist.org/study/general-conference/{self.year}/{self.month}?lang={self.language}"
