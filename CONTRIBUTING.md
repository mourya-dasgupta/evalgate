# Contributing to EvalGate

Thanks for your interest. EvalGate is small on purpose; contributions that keep it small,
typed and well-tested are very welcome.

## Development setup

```bash
git clone https://github.com/mourya-dasgupta/evalgate.git
cd evalgate
python -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[dev]"
```

## Checks (all must pass before a PR is merged)

```bash
make lint           # ruff check + ruff format --check
make typecheck      # mypy --strict on src/
make test           # pytest
make cov            # pytest with coverage; fails under 90%
make demo           # the end-to-end demo story
```

`make format` fixes formatting and auto-fixable lint issues.

## Guidelines

- **Tests first for behaviour changes.** Every scorer, gate rule and CLI exit path has tests;
  keep it that way. Never weaken or delete a test to make it pass.
- **Friendly errors.** User mistakes raise an `EvalGateError` subclass with a message that says
  what is wrong, where, and a `hint` that says how to fix it. No raw tracebacks.
- **Exit codes are a contract** (0 pass, 1 gate failed, 2 config/usage, 3 provider/cassette).
  Don't change them.
- **No network in tests.** Use `respx` for HTTP and the `mock`/`python` providers elsewhere.
- **Keep dependencies small.** Discuss new runtime dependencies in an issue first.
- **Record decisions.** Significant design choices get a short ADR in `docs/decisions/`.
- **Snapshot tests.** If you intentionally change the Markdown report, regenerate the snapshot
  with `UPDATE_SNAPSHOTS=1 pytest tests/test_reports.py` and review the diff.
- **Demo cassettes.** If you change `examples/support-triage/sim_model.py`, the prompts or the
  golden set, run `make demo-record` and commit the cassette and baseline, then `make demo`.

## Commit messages

Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `ci:`, `refactor:`, `chore:`.

## Adding a scorer

1. Add a class in `src/evalgate/scorers/builtin.py` (or a new module imported by
   `scorers/__init__.py`) with an `Options` model and `@register_scorer("name")`.
2. Return `ScoreResult(score, reason, details)` with a reason a human can act on.
3. Add tests for normal, empty, invalid-JSON and unicode inputs.
4. Document it in the scorer table in `docs/guide.md`.
