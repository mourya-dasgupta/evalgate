# 0011. Ship the demo with a clearly labelled simulated model

- Status: Accepted
- Date: 2026-11-03

## Context

The demo must run offline in CI and on a reviewer's laptop without API keys, and it must
tell a believable story: a good prompt, a realistic regression, a gate that catches it.
No real model calls were allowed while building it.

## Decision

`examples/support-triage/sim_model.py` is a deterministic, rule-based stand-in (keyword
classifier + priority rules + tone heuristics) that reads the rendered prompt like a model
would. Its behaviour depends on the prompt: with v1 it follows the priority rules and
ignores injected instructions; with v2 it lets tone drive priority and obeys injections.
It also has deliberate, generic weaknesses (sarcasm read as praise, anchoring on the first
issue mentioned). Its responses are recorded with `--mode record`, exactly as a real model's
would be. A `SimulatedJudge` grades summaries the same way.

## Consequences

- The demo is honest about *mechanics* (record, replay, compare, gate, report) and makes
  no claims about any real model. Every doc that shows its numbers says it is simulated.
- `evalgate.real.yaml` and the guide show how to re-record the same suite against a real
  model to get genuine numbers.
- Because the author wrote both the golden set and the simulator, its accuracy says
  nothing about task difficulty. Only real-model recordings do.
