# Modernization Plan

This plan covers the modernization of `src/general_conference_reference/gcon.py`, the package CLI, and the project dependencies/tooling around it.

## Phase 0: Baseline and Guardrails

- [x] Review the current code path, package entrypoint, and dependency setup.
- [x] Confirm that the current code still uses `chat.completions` and that the installed SDK exposes `responses`.
- [ ] Capture a representative baseline run for one conference so output regressions are easier to spot.
- [ ] Decide what behavior must remain stable in the generated `reference.md` and `reference.docx`.
- [ ] Add a small fixture set for one talk and one conference index page so parser changes can be tested locally.

## Phase 1: Dependency and Packaging Cleanup

- [x] Upgrade core runtime dependencies, especially `openai`.
- [x] Upgrade dev tooling such as `pytest` and `black`.
- [x] Audit direct dependencies and remove packages that are no longer used.
- [x] Regenerate `uv.lock`.
- [x] Regenerate `requirements.txt` from `uv`.
- [x] Update `README.md` to match the actual `uv` workflow.
- [x] Remove stale Poetry-specific setup from `Dockerfile`.

## Phase 2: Configuration and CLI Cleanup

- [x] Stop loading `openai.key` at import time.
- [x] Prefer `OPENAI_API_KEY` from the environment, with an explicit optional fallback if we still want a local key file.
- [x] Move model names, output paths, and pipeline settings into a config object instead of module globals.
- [x] Inject the OpenAI client into the pipeline instead of constructing it globally.
- [x] Add CLI options for `--until-step`, `--concurrency`, `--force`, and model overrides.
- [x] Add `--until-step`.
- [x] Replace ad hoc `print` and `pprint` calls with structured logging.
- [x] Convert filesystem code to `pathlib.Path`.

## Phase 3: Responses API Migration

- [x] Replace each `client.chat.completions.create(...)` call with `client.responses.create(...)`.
- [x] Introduce a small helper for text generation so the three generation sites share one code path.
- [x] Use `instructions=` plus `input=` instead of manually constructing chat message arrays.
- [x] Standardize output extraction on `response.output_text`.
- [x] Revisit retry behavior and error handling around rate limits after the migration.
- [ ] Add explicit request settings where useful, such as reasoning effort or output limits.

## Phase 4: Structured Outputs

- [x] Define Pydantic models for outline, themes, and key-principles outputs.
- [x] Use `client.responses.parse(...)` where typed output is better than free-form markdown.
- [x] Render markdown from typed objects instead of parsing markdown back into data.
- [x] Remove brittle parsing logic for `### Summary` extraction and `key_principles.md` line parsing.
- [x] Keep the external markdown output stable enough that existing generated references still look familiar.

## Phase 5: Pipeline and Runtime Improvements

- [x] Replace the current all-at-once OpenAI fanout with bounded concurrency.
- [x] Make concurrency configurable from the CLI.
- [x] Make cache behavior explicit so reruns can skip, refresh, or rebuild outputs intentionally.
- [x] Replace the current `RUN_UNTIL_STEP` global with a clearer pipeline configuration mechanism.
- [x] Add better subprocess failure handling where external tools remain in use.
- [ ] Evaluate whether Batch API is worth using for offline conference-wide summarization.

## Phase 6: HTML and Markdown Processing Cleanup

- [ ] Decide whether to keep `curl`, `htmlq`, `gsed`, and `pandoc` as external dependencies.
- [ ] Replace `curl` and `htmlq` with Python HTTP and HTML parsing if that keeps the pipeline simpler and more portable.
- [ ] Parse each talk HTML document once instead of shelling out repeatedly for each field.
- [ ] Move markdown cleanup rules out of shell `sed` expressions and into Python.
- [ ] Keep `pandoc` only if DOCX generation still justifies it.

## Phase 7: Tests and Verification

- [ ] Add unit tests for talk parsing and output assembly.
- [ ] Add tests for structured-output parsing and markdown rendering.
- [ ] Add a smoke test for the CLI on fixture data.
- [ ] Run the formatter and test suite after each major phase.
- [ ] Perform one end-to-end verification run against a recent conference.

## Phase 8: Optional Enhancements

- [ ] Pin model snapshots explicitly if output stability matters more than always using aliases.
- [ ] Record request metadata or token usage for cost visibility.
- [ ] Add a dry-run or plan mode for inspecting pipeline steps without calling the API.
- [ ] Consider splitting the monolithic pipeline into smaller modules once behavior is stable.

## Suggested Execution Order

- [ ] Phase 1 first, with `openai` as the priority dependency update.
- [ ] Phase 2 next, so config and CLI are in place before deeper refactors.
- [ ] Phase 3 after that, to complete the Responses API migration.
- [ ] Phase 4 once the new API path is stable.
- [ ] Phase 5 and Phase 6 after behavior is covered by fixtures/tests.
- [ ] Phase 7 continuously, but finish it before calling the modernization complete.
