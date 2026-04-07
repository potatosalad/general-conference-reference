# General Conference Reference

Fetches latest General Conference talks, converts them to markdown, and uses OpenAI to produce a summarized reference document as a study guide for the conference.

See https://tinyurl.com/f7gc102023 for an example output.

## Usage

Dependencies:

```bash
brew install pandoc
uv sync
```

Formatting:

```bash
just format
```

Running:

```bash
uv run general_conference_reference .
```

Examples:

```bash
# Stop after talk outlines
uv run general_conference_reference . --year 2025 --month 10 --until-step 4

# Regenerate outputs with bounded AI concurrency and explicit models
uv run general_conference_reference . \
  --concurrency 4 \
  --force \
  --outline-model gpt-5.4 \
  --themes-model gpt-5 \
  --key-principles-model gpt-5
```
