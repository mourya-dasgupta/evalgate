# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-03

First release.

### Added

- `evalgate` CLI (Typer): `init`, `validate`, `run`, `gate`, `baseline update`,
  `baseline show`, `report --format md|html|json`; global `--config`, `--mode`, `--verbose`;
  `EVALGATE_MODE` environment variable.
- Configuration (`evalgate.yaml`) validated with Pydantic v2, with `${VAR:-default}`
  interpolation and error messages that name the exact field.
- JSONL golden sets with line-numbered validation errors.
- Providers behind one async interface: `mock`, `openai_compatible`, `anthropic` (httpx),
  and `python` (dotted-path entrypoint). Retries with exponential backoff and `Retry-After`,
  timeouts, and a configurable concurrency limit.
- Cassette layer with `record`, `replay` and `live` modes; requests keyed by SHA-256 of model +
  rendered messages + params.
- Scorers: `exact_match`, `contains`, `not_contains`, `regex`, `json_valid`, `json_schema`,
  `numeric_tolerance`, `label_match` (with confusion matrices), `llm_judge` (replayable), and
  custom dotted-path scorers.
- Gate rules: `min_pass_rate`, `max_regression`, `max_new_failures`, `critical_tags`; verdicts
  PASS / FAIL / NO_BASELINE; exit codes 0/1/2/3.
- Reports: rich terminal table, Markdown for PR comments, self-contained HTML with per-case
  drill-down and confusion matrices, JSON.
- Composite GitHub Action (`action.yml`), CI workflow, example PR workflow with sticky
  comments, and a Dockerfile.
- `examples/support-triage`: 66-case multilingual golden set, two prompt versions, a clearly
  labelled simulated model and judge, recorded cassettes, a committed baseline, a real-model
  config, and `make demo`.
- Documentation: README, user guide, architecture, runbook, roadmap, ADRs.
