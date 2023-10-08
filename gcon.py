#!/usr/bin/env python3.10

import asyncio
from dataclasses import dataclass, field
import os
import openai
import pprint
import subprocess

YEAR: str = "2023"
MONTH: str = "10"
LANGUAGE: str = "eng"
ROOT_DIR: str = f"{YEAR}{MONTH}"

with open("openai.key", "r") as f:
    openai.api_key = f.read().strip()

# Pricing as of 2023-10-07 (see https://openai.com/pricing#language-models)
#
# gpt-3.5-turbo (4K tokens): costs $0.0035 per 1K tokens (in: $0.0015, out: $0.002)
# gpt-3.5-turbo-16k (16K tokens): costs $0.007 per 1K tokens (in: $0.003, out: $0.004)
# gpt-4 (8K tokens): costs $0.09 per 1K tokens (in: $0.03, out: $0.06)
# gpt-4-32k (32K tokens), costs $0.18 per 1K tokens (in: $0.06, out: $0.12)

# OUTLINE_MODEL: str = "gpt-3.5-turbo-16k"
OUTLINE_MODEL: str = "gpt-4"
OUTLINE_PROMPT: str = """\
Help members of the Church of Jesus Christ of Latter-day Saints \
understand the key principles and doctrines from the most recent \
General Authorities from their talks at General Conference. \
The user will provide a recent talk. \
All input and output should be in Markdown format. \
Write output in the following Markdown format with each section filled in:
### Summary

Write brief summary of the talk in one sentence.

### Haiku

Write a haiku that expresses the key principles or theme of the talk.

### Key Points

Write a numbered 3 point list with a brief description of each of the major points in the talk.

### Scriptures and Gospel Principles

Write a bulleted list of a few scriptures, other referenced talks, \
or important Gospel Principles from the main talk that are worth studying.

### Questions to Ponder

Write a bulleted list of questions that the class can ponder the week leading up to the lesson \
and that the instructor might use during the lesson to help others learn.
\
"""

THEMES_MODEL: str = "gpt-4"
THEMES_PROMPT: str = """\
Help members of the Church of Jesus Christ of Latter-day Saints \
understand the key principles and doctrines from the most recent \
General Authorities from their talks at General Conference. \
The user will provide a full listing of summaries of all talks from the conference. \
All input and output should be in Markdown format. \
Write output in the following Markdown format with each section filled in:
### Summary

Summarize the overall theme from the conference. \
Emphasize any key doctrines that were repeated or that represented the main theme of the conference.

### Haiku

Write a haiku that expresses the key principles or theme of the conference.

### Questions to Ponder

Write a bulleted list of a few scriptures, other referenced talks, \
or important Gospel Principles from the conference that are worth studying.
\
"""

KEY_PRINCIPLES_MODEL: str = "gpt-4"
KEY_PRINCIPLES_PROMPT: str = """\
Help members of the Church of Jesus Christ of Latter-day Saints \
understand the key principles and doctrines from the most recent \
General Authorities from their talks at General Conference. \
The user will provide a full listing of summaries of all talks from the conference. \
All input and output should be in Markdown format. \
Write output in the following Markdown format with each section filled in:
### Key Principles

Write a numbered list for each talk with a short sentence describing the key principles \
of the talk as it relates to the themes from all of the talks in the conference.
\
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

RUN_UNTIL_STEP: int = STEP9_WRITE_REFERENCE_DOCX


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
        if RUN_UNTIL_STEP < STEP1_FETCH_TALK_HTML:
            return
        html_file: str = self.html_file
        if not os.path.isfile(html_file):
            cmd1 = ["curl", "--silent", "--location", self.url]
            process1 = await asyncio.create_subprocess_exec(*cmd1, stdout=asyncio.subprocess.PIPE)
            output, _ = await process1.communicate()
            with open(html_file, "wb") as f:
                f.write(output)
                f.close()
        await asyncio.gather(
            self.load_title(),
            self.load_subtitle(),
            self.load_author(),
            self.load_role(),
            self.load_summary(),
            self.load_body(),
        )
        if RUN_UNTIL_STEP < STEP2_WRITE_TALK_STAGE:
            return
        stage_file: str = self.stage_file
        if not os.path.isfile(stage_file):
            title: str = self.title
            if self.subtitle:
                title += f" {self.subtitle}"
            with open(stage_file, "wb") as f:
                f.write(f"<h1>{title}</h1>\n".encode("utf-8"))
                if self.role:
                    f.write(f"<p><em>{self.author} {self.role}</em></p>\n".encode("utf-8"))
                else:
                    f.write(f"<p><em>{self.author}</em></p>\n".encode("utf-8"))
                if self.summary:
                    f.write(f"<p><em>{self.summary}</em></p>\n".encode("utf-8"))
                f.write(self.body.encode("utf-8"))
        if RUN_UNTIL_STEP < STEP3_WRITE_TALK_MARKDOWN:
            return
        markdown_file: str = self.markdown_file
        if not os.path.isfile(markdown_file):
            cmd1 = ["pandoc", "-f", "html", "-t", "commonmark", "--wrap", "none", "-o", "-", stage_file]
            cmd2 = [
                "gsed",
                "-e",
                "s#\[<sup>[0-9]\+</sup>\]([^)]*)##g",
                "-e",
                "s#<a [^>]*><sup>[0-9]\+</sup></a>##g",
                "-e",
                "s#\](/#](https://www.churchofjesuschrist.org/#g",
                "-e",
                's#href="/#href="https://www.churchofjesuschrist.org/#g',
            ]
            read, write = os.pipe()
            process1 = await asyncio.create_subprocess_exec(*cmd1, stdout=write)
            os.close(write)
            process2 = await asyncio.create_subprocess_exec(*cmd2, stdin=read, stdout=asyncio.subprocess.PIPE)
            os.close(read)
            output, _ = await process2.communicate()
            with open(markdown_file, "wb") as f:
                f.write(output)

    async def give_openai_more_money(self) -> None:
        if RUN_UNTIL_STEP < STEP4_WRITE_TALK_OUTLINE:
            return
        outline_file: str = self.outline_file
        if not os.path.isfile(outline_file):
            text: str = ""
            with open(self.markdown_file, "r") as f:
                text = f.read()
            chat_completion = await openai.ChatCompletion.acreate(
                model=OUTLINE_MODEL,
                messages=[
                    {"role": "system", "content": OUTLINE_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            with open(outline_file, "w") as f:
                f.write(chat_completion.choices[0].message.content)
        aisummary: list[str] = []
        with open(outline_file, "r") as f:
            capture: bool = False
            for line in f.readlines():
                line = line.strip()
                if capture:
                    if line.startswith("###"):
                        break
                    elif line:
                        aisummary.append(line)
                else:
                    if line.startswith("### Summary"):
                        capture = True
        self.aisummary = "\n".join(aisummary)

    async def load_title(self) -> None:
        text: str = await self.htmlq(".body h1")
        self.title = text

    async def load_subtitle(self) -> None:
        text: str = await self.htmlq(".body .subtitle")
        self.subtitle = text

    async def load_author(self) -> None:
        text: str = await self.htmlq(".body .byline .author-name")
        self.author = text.replace("By ", "").replace("\xa0", " ")

    async def load_role(self) -> None:
        text: str = await self.htmlq(".body .byline .author-role")
        self.role = text.replace("By ", "").replace("\xa0", " ")

    async def load_summary(self) -> None:
        text: str = await self.htmlq(".body .kicker")
        self.summary = text

    async def load_body(self) -> None:
        text: str = await self.htmlq(".body .body-block", text=False)
        self.body = text

    async def htmlq(self, selector: str, text: bool = True) -> str:
        cmd1 = ["htmlq", "--filename", self.html_file]
        if text:
            cmd1.append("--text")
        cmd1.append(selector)
        process1 = await asyncio.create_subprocess_exec(*cmd1, stdout=asyncio.subprocess.PIPE)
        output, _ = await process1.communicate()
        return output.decode("utf-8").strip()

    def outline(self) -> str:
        with open(self.outline_file) as f:
            return f.read()

    @property
    def html_dir(self) -> str:
        return self.parent.talk_dir("html")

    @property
    def html_file(self) -> str:
        return f"{self.html_dir}/{self.key}.html"

    @property
    def markdown_dir(self) -> str:
        return self.parent.talk_dir("markdown")

    @property
    def markdown_file(self) -> str:
        return f"{self.markdown_dir}/{self.key}.md"

    @property
    def outline_dir(self) -> str:
        return self.parent.talk_dir("outline")

    @property
    def outline_file(self) -> str:
        return f"{self.outline_dir}/{self.key}-outline.md"

    @property
    def talk_file(self) -> str:
        return self.parent.talk_file(self.key)

    @property
    def stage_dir(self) -> str:
        return self.parent.talk_dir("stage")

    @property
    def stage_file(self) -> str:
        return f"{self.stage_dir}/{self.key}-stage.html"

    @property
    def yaml_file(self) -> str:
        return f"{self.talk_file}.yaml"


@dataclass
class GeneralConference:
    year: str
    month: str
    language: str
    talks: list["Talk"] = field(init=False)

    def __post_init__(self) -> None:
        self.talks = []

    async def execute(self) -> None:
        for talk_url in await self.fetch():
            self.talks.append(Talk(parent=self, url=talk_url))
        await asyncio.gather(*[talk.execute() for talk in self.talks])
        for talk in self.talks:
            await talk.give_openai_more_money()
        await self.dump()

    async def fetch(self) -> list[str]:
        talk_urls: list[str] = []
        if RUN_UNTIL_STEP >= STEP0_FETCH_TALK_LIST:
            if not os.path.isfile(self.talk_list_file):
                cmd1 = ["curl", "--silent", "--location", self.url]
                cmd2 = ["htmlq", "--attribute", "href", ".body nav a"]
                read, write = os.pipe()
                process1 = await asyncio.create_subprocess_exec(*cmd1, stdout=write)
                os.close(write)
                process2 = await asyncio.create_subprocess_exec(*cmd2, stdin=read, stdout=asyncio.subprocess.PIPE)
                os.close(read)
                output, _ = await process2.communicate()
                with open(self.talk_list_file, "wb") as f:
                    for line in output.decode("utf-8").split("\n"):
                        line = line.strip()
                        if line and "-session?" not in line:
                            f.write(f"https://www.churchofjesuschrist.org/{line}\n".encode("utf-8"))
            with open(self.talk_list_file, "r") as f:
                for talk_url in f.readlines():
                    talk_url = talk_url.strip()
                    if talk_url:
                        talk_urls.append(talk_url)
        return talk_urls

    async def dump(self) -> None:
        if RUN_UNTIL_STEP < STEP5_WRITE_OUTLINES:
            return
        outlines_file: str = self.root_file("outlines.md")
        if not os.path.isfile(outlines_file):
            i: int = 1
            with open(outlines_file, "wb") as f:
                for talk in self.talks:
                    f.write(f"## {str(i)}. {talk.title} - {talk.author}\n\n".encode("utf-8"))
                    f.write(f"[{talk.url}]({talk.url})\n\n".encode("utf-8"))
                    f.write(talk.outline().encode("utf-8"))
                    f.write("\n\n".encode("utf-8"))
                    i += 1
        if RUN_UNTIL_STEP < STEP6_WRITE_SUMMARIES:
            return
        summaries_file: str = self.root_file("summaries.md")
        if not os.path.isfile(summaries_file):
            i: int = 1
            with open(summaries_file, "wb") as f:
                for talk in self.talks:
                    f.write(f"{str(i)}. {talk.title} - {talk.author}\n\n".encode("utf-8"))
                    # f.write(f"{talk.url}\n\n".encode("utf-8"))
                    f.write(talk.summary.encode("utf-8"))
                    f.write("\n\n".encode("utf-8"))
                    f.write(talk.aisummary.encode("utf-8"))
                    f.write("\n\n".encode("utf-8"))
                    i += 1
        if RUN_UNTIL_STEP < STEP7_WRITE_THEMES:
            return
        themes_file: str = self.root_file("themes.md")
        if not os.path.isfile(themes_file):
            text: str = ""
            with open(summaries_file, "r") as f:
                text = f.read()
            chat_completion = await openai.ChatCompletion.acreate(
                model=THEMES_MODEL,
                messages=[
                    {"role": "system", "content": THEMES_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            with open(themes_file, "w") as f:
                f.write(chat_completion.choices[0].message.content)
        key_principles_file: str = self.root_file("key_principles.md")
        if not os.path.isfile(key_principles_file):
            text: str = ""
            with open(summaries_file, "r") as f:
                text = f.read()
            chat_completion = await openai.ChatCompletion.acreate(
                model=KEY_PRINCIPLES_MODEL,
                messages=[
                    {"role": "system", "content": KEY_PRINCIPLES_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            with open(key_principles_file, "w") as f:
                f.write(chat_completion.choices[0].message.content)
        with open(key_principles_file, "r") as f:
            for line in f.readlines():
                line = line.strip()
                if line and line[0].isdigit():
                    i: int = 0
                    j: int = i + 1
                    while j < len(line) and line[j].isdigit():
                        j += 1
                    talk_index: int = int(line[i:j]) - 1
                    parts: list[str] = line[j + 2 :].split("*")
                    if len(parts) != 3 or len(parts[0]) != 0 or len(parts[2]) == 0:
                        raise ValueError(f"bad parts on talk_index={talk_index}, parts={repr(parts)}")
                    self.talks[talk_index].aiprinciple = parts[2].strip()
        key_principles_list_file: str = self.root_file("key_principles_list.md")
        if not os.path.isfile(key_principles_list_file):
            with open(key_principles_list_file, "wb") as f:
                f.write(f"### Key Principles\n\n".encode("utf-8"))
                for talk_index, talk in enumerate(self.talks):
                    f.write(
                        f"{talk_index + 1}. {talk.aiprinciple} ([&ldquo;{talk.title}&rdquo; - {talk.author}]({talk.url}))\n".encode(
                            "utf-8"
                        )
                    )
                f.write(f"\n".encode("utf-8"))
        if RUN_UNTIL_STEP < STEP8_WRITE_REFERENCE_MARKDOWN:
            return
        reference_markdown_file: str = self.root_file("reference.md")
        with open(reference_markdown_file, "wb") as f:
            f.write(f"# General Conference {self.year}-{self.month}\n\n".encode("utf-8"))
            f.write("## Themes\n\n".encode("utf-8"))
            with open(themes_file, "rb") as sf:
                f.write(sf.read())
            f.write("\n\n".encode("utf-8"))
            with open(key_principles_list_file, "rb") as sf:
                f.write(sf.read())
            f.write("\n\n".encode("utf-8"))
            f.write("## Talks\n\n".encode("utf-8"))
            with open(outlines_file, "rb") as sf:
                f.write(sf.read())
            f.write("\n\n".encode("utf-8"))
        if RUN_UNTIL_STEP < STEP9_WRITE_REFERENCE_DOCX:
            return
        reference_docx_file: str = self.root_file("reference.docx")
        cmd1 = ["pandoc", "-f", "commonmark", "-t", "docx", "-s", "-o", reference_docx_file, reference_markdown_file]
        process1 = await asyncio.create_subprocess_exec(*cmd1, stdout=asyncio.subprocess.PIPE)
        output, _ = await process1.communicate()
        print(output.decode("utf-8").strip())
        return

    @property
    def root_dir(self) -> str:
        if not os.path.isdir(ROOT_DIR):
            os.mkdir(ROOT_DIR)
        return ROOT_DIR

    def root_file(self, key: str) -> str:
        return f"{self.root_dir}/{key}"

    @property
    def talks_dir(self) -> str:
        talks_dir: str = f"{self.root_dir}/talks"
        if not os.path.isdir(talks_dir):
            os.mkdir(talks_dir)
        return talks_dir

    def talk_dir(self, key: str) -> str:
        dir: str = self.talk_file(key)
        if not os.path.isdir(dir):
            os.mkdir(dir)
        return dir

    def talk_file(self, key: str) -> str:
        return f"{self.talks_dir}/{key}"

    @property
    def talk_list_file(self) -> str:
        return f"{self.root_dir}/talk_list.txt"

    @property
    def themes_file(self) -> str:
        return self.root_file("themes.md")

    @property
    def url(self) -> str:
        return f"https://www.churchofjesuschrist.org/study/general-conference/{self.year}/{self.month}?lang={self.language}"


general_conference = GeneralConference(YEAR, MONTH, LANGUAGE)
asyncio.run(general_conference.execute())
pprint.pprint(general_conference)
