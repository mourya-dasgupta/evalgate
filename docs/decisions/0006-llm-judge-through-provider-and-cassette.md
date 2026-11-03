# 0006. The LLM judge goes through the same provider + cassette layer

- Status: Accepted
- Date: 2026-11-03

## Context

Rubric grading by a model is the only practical way to score open-ended text (summaries,
tone), but a judge is itself an LLM call, non-deterministic and keyed.

## Decision

`llm_judge` builds a chat request (fixed system prompt + rubric + input + optional
reference + output) and sends it through the same provider factory as the target, wrapped
in the suite's cassette. Judge replies are recorded and replayed like any other call.
Defaults to `temperature: 0`; asks for `{"score": 1-5, "reason": ...}` and normalises to 0-1.

## Consequences

- Judge-based scores are as deterministic in CI as exact-match scores.
- Changing the rubric or the judge model is a cache miss, so judge changes are reviewed too.
- Judge reliability is not solved by replay; it is solved by calibrating the judge against
  human labels (see the guide and the roadmap). In the demo the judge score is tracked but
  `required: false`, so it informs rather than gates.
