# 0009. The mock provider bypasses cassettes

- Status: Accepted
- Date: 2026-11-03

## Context

`evalgate init` must produce a project that runs immediately, offline, with no recording step.

## Decision

Providers declare `requires_recording`. The rule-based `mock` provider sets it to false and
is never wrapped by the cassette layer, so `--mode` has no effect on it. Every other
provider (`openai_compatible`, `anthropic`, `python`) is recorded and replayed.

## Consequences

- The quickstart is install → `init` → `gate` with no keys and no cassettes.
- `python` providers are cassetted on purpose: they usually wrap a real model or pipeline,
  and the demo's simulated model shows the full record/replay flow.
