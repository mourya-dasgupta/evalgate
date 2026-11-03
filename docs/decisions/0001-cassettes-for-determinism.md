# 0001. Record model responses once as cassettes; replay them in CI

- Status: Accepted
- Date: 2026-11-03

## Context

A CI gate must give the same answer for the same code. LLM calls are non-deterministic
(even at temperature 0, providers change models and batching), slow, cost money, and need
API keys that should not live in every CI job, especially on fork PRs.

## Decision

Model responses are recorded once (`--mode record`) into JSONL "cassettes"
(`cassettes/<suite>.jsonl`) and replayed in CI (`--mode replay`, the default). `live`
mode exists for exploratory runs and always calls the provider.

## Consequences

- CI is deterministic, fast (replaying the 66-case demo suite takes under a second) and needs no secrets.
- A PR that changes a prompt *must* re-record, which makes the cost of a prompt change
  visible in review (the cassette diff shows exactly which answers changed).
- The gate measures the recorded behaviour, not today's live behaviour. Provider-side
  drift is not caught unless someone re-records; a scheduled `live` run is the
  recommended complement (see the roadmap).
- Cassettes add repository weight (the demo's is ~350 KB for 206 entries).
