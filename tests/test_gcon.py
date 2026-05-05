from pathlib import Path

from openai import AsyncOpenAI

from general_conference_reference.gcon import (
    CHURCH_BASE_URL,
    GeneralConference,
    KeyPrincipleEntry,
    KeyPrinciplesResponse,
    OutlineResponse,
    ResponseRequestSettings,
    Talk,
    ThemesResponse,
    build_structured_response_request,
    cleanup_markdown,
    extract_talk_urls_from_html,
    load_openai_api_key,
    parse_talk_html,
    render_key_principles_markdown,
    render_outline_markdown,
    render_reference_markdown,
    render_stage_html,
    render_themes_markdown,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_openai_api_key_prefers_environment(monkeypatch, tmp_path: Path) -> None:
    key_file = tmp_path / "openai.key"
    key_file.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    assert load_openai_api_key(key_file) == "env-key"


def test_render_outline_markdown_preserves_expected_sections() -> None:
    outline = OutlineResponse(
        summary="One sentence.",
        haiku="Line one\nLine two\nLine three",
        key_points=["Point one", "Point two", "Point three"],
        scriptures_and_gospel_principles=["Mosiah 3:19", "Charity"],
        questions_to_ponder=["What changed?", "What comes next?"],
    )

    assert render_outline_markdown(outline) == """### Summary

One sentence.

### Haiku

Line one
Line two
Line three

### Key Points

1. Point one
2. Point two
3. Point three

### Scriptures and Gospel Principles

- Mosiah 3:19
- Charity

### Questions to Ponder

- What changed?
- What comes next?
"""


def test_render_themes_markdown_preserves_expected_sections() -> None:
    themes = ThemesResponse(
        summary="Conference summary.",
        repeated_doctrines=["Theme one", "Theme two"],
        haiku="First\nSecond\nThird",
        questions_to_ponder=["How should we respond?"],
    )

    assert render_themes_markdown(themes) == """### Summary

Conference summary.

- Theme one
- Theme two

### Haiku

First
Second
Third

### Questions to Ponder

- How should we respond?
"""


def test_render_key_principles_markdown_sorts_by_index() -> None:
    key_principles = KeyPrinciplesResponse(
        key_principles=[
            KeyPrincipleEntry(index=2, title="Second", speaker="Speaker Two", principle="Second principle."),
            KeyPrincipleEntry(index=1, title="First", speaker="Speaker One", principle="First principle."),
        ]
    )

    assert render_key_principles_markdown(key_principles) == """### Key Principles

1. *First - Speaker One:* First principle.
2. *Second - Speaker Two:* Second principle.
"""


def test_apply_key_principles_assigns_entries_by_index(tmp_path: Path) -> None:
    conference = GeneralConference(
        output_path=tmp_path,
        year="2025",
        month="04",
        language="eng",
        client=AsyncOpenAI(api_key="test"),
    )
    first_talk = Talk(parent=conference, url="https://example.com/first")
    second_talk = Talk(parent=conference, url="https://example.com/second")
    conference.talks = [first_talk, second_talk]

    conference.apply_key_principles(
        KeyPrinciplesResponse(
            key_principles=[
                KeyPrincipleEntry(index=2, title="Second", speaker="Speaker Two", principle="Second principle."),
                KeyPrincipleEntry(index=1, title="First", speaker="Speaker One", principle="First principle."),
            ]
        )
    )

    assert conference.talks[0].aiprinciple == "First principle."
    assert conference.talks[1].aiprinciple == "Second principle."


def test_build_structured_response_request_includes_explicit_limits() -> None:
    request = build_structured_response_request(
        model="gpt-5",
        instructions="Summarize the talk.",
        input_text="Talk body",
        text_format=OutlineResponse,
        request_settings=ResponseRequestSettings(
            max_output_tokens=1234,
            reasoning_effort="low",
            verbosity="medium",
        ),
    )

    assert request == {
        "model": "gpt-5",
        "instructions": "Summarize the talk.",
        "input": "Talk body",
        "text_format": OutlineResponse,
        "max_output_tokens": 1234,
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "medium"},
    }


def test_extract_talk_urls_from_html_uses_fixture() -> None:
    html = (FIXTURES_DIR / "conference_index.html").read_text(encoding="utf-8")

    assert extract_talk_urls_from_html(html) == [
        f"{CHURCH_BASE_URL}/study/general-conference/2025/04/11sample?lang=eng",
        f"{CHURCH_BASE_URL}/study/general-conference/2025/04/12sample?lang=eng",
    ]


def test_parse_talk_html_and_render_stage_uses_fixture() -> None:
    html = (FIXTURES_DIR / "talk.html").read_text(encoding="utf-8")

    talk_page = parse_talk_html(html)

    assert talk_page.title == "Finding Christ in Covenants"
    assert talk_page.subtitle == "A Better Way to Live"
    assert talk_page.author == "Elder Sample Speaker"
    assert talk_page.role == "Of the Quorum of the Twelve Apostles"
    assert talk_page.summary == "Christ makes weak things become strong."
    assert 'href="https://www.churchofjesuschrist.org/study/scriptures/bofm/mosiah/3?lang=eng#p19"' in talk_page.body_html
    assert "note-ref" not in talk_page.body_html

    expected_stage = (FIXTURES_DIR / "talk_stage.html").read_text(encoding="utf-8")
    assert render_stage_html(talk_page) == expected_stage


def test_cleanup_markdown_uses_fixture() -> None:
    raw_markdown = (FIXTURES_DIR / "raw_markdown.md").read_text(encoding="utf-8")
    expected_markdown = (FIXTURES_DIR / "clean_markdown.md").read_text(encoding="utf-8")

    assert cleanup_markdown(raw_markdown) == expected_markdown


def test_render_reference_markdown_matches_baseline_fixture() -> None:
    actual = render_reference_markdown(
        year="2025",
        month="04",
        themes_markdown="""### Summary

Conference summary.

- Theme one

### Haiku

Seek the Savior
Keep the covenants
Walk with His light

### Questions to Ponder

- What promise needs attention?
""",
        key_principles_list_markdown="""### Key Principles

1. Remember Christ in every covenant ([&ldquo;Finding Christ in Covenants&rdquo; - Elder Sample Speaker](https://example.com/talk))
""",
        outlines_markdown="""## 1. Finding Christ in Covenants - Elder Sample Speaker

[https://example.com/talk](https://example.com/talk)

### Summary

Talk summary.
""",
    )

    expected = (FIXTURES_DIR / "reference_baseline.md").read_text(encoding="utf-8")
    assert actual == expected
