# 0005. Scorers are a registry with per-scorer option validation

- Status: Accepted
- Date: 2026-11-03

## Context

Every LLM feature needs different checks. A fixed set of metrics would not fit, and a
free-form "write Python" approach makes configs unreviewable.

## Decision

Scorers are classes registered by name (`@register_scorer("regex")`). Each declares a
Pydantic `Options` model; the suite config passes scorer options as extra keys, which are
validated at load time (`evalgate validate`) with friendly errors. Custom scorers load
from a dotted path (`type: custom`, `path: my_scorers:fn`) and may be a function or a
`Scorer` subclass. Every scorer returns a score in [0, 1] plus a human-readable reason.

## Consequences

- Built-in scorers cover most product checks without code; custom logic is one function away.
- Typos in scorer options fail validation instead of being silently ignored.
- Reasons flow into every report, so a failure explains itself ("expected 'urgent',
  predicted 'high'").
- A crashing custom scorer scores 0 with the exception as the reason instead of killing the run.
