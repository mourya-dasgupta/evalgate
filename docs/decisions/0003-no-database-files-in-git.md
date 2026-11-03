# 0003. No database: runs, baselines and cassettes are files in git

- Status: Accepted
- Date: 2026-11-03

## Context

Eval platforms usually store results in a hosted database with a dashboard. The target
user is one engineer at a small company who wants a gate, not a platform.

## Decision

Everything is a file: `evalgate.yaml`, JSONL golden sets, JSONL cassettes, run JSON in
`.evalgate/runs/` (git-ignored) and the baseline in `.evalgate/baseline.json` (committed).

## Consequences

- Zero infrastructure; works offline; reviewable in PRs; the baseline is versioned
  alongside the prompt it describes, and rolling back is `git checkout`.
- Baseline updates show up in code review, so "we accepted a lower score" is an explicit,
  reviewed decision.
- No cross-run trend view; history lives in git. A trend dashboard is on the roadmap as an
  optional add-on that reads these files.
