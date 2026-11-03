# 0004. Distinct exit codes for pass, gate failure, config error, provider error

- Status: Accepted
- Date: 2026-11-03

## Context

CI systems only see an exit code. "The model got worse" and "the API key is missing"
need different responses from a human.

## Decision

`0` pass (including NO_BASELINE), `1` gate failed, `2` configuration/usage error,
`3` provider or cassette error. User mistakes never print a traceback; they print what
is wrong, where, and a hint. Unexpected exceptions print a one-line message (traceback
with `--verbose`) and exit 2.

## Consequences

- Workflows can branch on the code (for example, only post a "quality dropped" comment on 1).
- When any case errors (exit 3) the gate is not evaluated at all. A pass rate computed
  with missing answers would be misleading in both directions.
