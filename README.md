# General Conference Reference

Fetches latest General Conference talks, converts them to markdown, and uses OpenAI to produce a summarized reference document as a study guide for the conference.

See https://tinyurl.com/f7gc102023 for an example output.

## Usage

Dependencies:

```bash
brew install curl gsed htmlq pandoc
uv install
```

Formatting:

```bash
just format
```

Running:

```bash
uv venv
source .venv/bin/activate
general_conference_reference .
```
