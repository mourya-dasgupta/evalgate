# EvalGate build plan

This file is the source of truth for progress. A new session should read it,
find the first unchecked milestone, and continue from there. Every milestone
ends with `make lint && make typecheck && make test` passing, a tick here,
and a conventional-commit push to `claude/gallant-wright-qi9oa1`.

## Milestones

- [x] **M0 — Skeleton + tooling + CI**: `pyproject.toml` (hatchling, `src/` layout,
      console script), Makefile, ruff/mypy/pytest config, `.gitignore`,
      `.editorconfig`, LICENSE, CI workflow, smoke test.
- [x] **M1 — Config + golden sets + validate**: Pydantic v2 config models, env-var
      interpolation, friendly validation errors with locations, JSONL golden sets
      with line-numbered errors, prompt template rendering.
- [x] **M2 — Providers + cassette layer**: `Provider` interface, `mock`,
      `openai_compatible`, `anthropic`, `python` (dotted-path) providers; retries with
      exponential backoff, timeouts; cassette record/replay/live with request hashing.
- [x] **M3 — Scorers**: registry + `exact_match`, `contains`, `not_contains`, `regex`,
      `json_valid`, `json_schema`, `numeric_tolerance`, `label_match`, `llm_judge`,
      custom dotted-path scorers.
- [x] **M4 — Runner + compare + gate + exit codes**: async runner with concurrency
      limit, run storage, baseline, comparison/flip logic, gate rules, verdicts.
- [x] **M5 — Reports**: terminal (rich), Markdown (PR comment), HTML (self-contained),
      JSON.
- [ ] **M6 — CLI polish + init**: all commands, global flags, `init` scaffolding,
      friendly error handling, exit codes 0/1/2/3.
- [ ] **M7 — Demo project**: `examples/support-triage` (60+ golden cases, two prompt
      versions, simulated model, cassettes, committed baseline), `make demo`,
      reports saved to `docs/assets/`.
- [ ] **M8 — GitHub integration**: composite `action.yml`, example workflow, CI runs
      the example gate, Dockerfile.
- [ ] **M9 — Docs**: README, guide, architecture, runbook, roadmap, portfolio, ADRs,
      issues-to-create, CHANGELOG, CONTRIBUTING.
- [x] **M10 — Final verification**: clean install, lint/typecheck/tests/coverage,
      `make demo`, run every documented command, numbers cross-checked, PR opened.

## Notes / environment

- Python 3.13 is available in the build container; the package targets 3.11+.
- Package installs from PyPI work in this environment (no network workaround needed).
