# 0008. NO_BASELINE passes with a warning but still enforces absolute rules

- Status: Accepted
- Date: 2026-11-03

## Context

The first run of a new suite, or a newly added suite, has nothing to compare against.
Failing would block adoption; silently passing would hide a broken suite.

## Decision

Without a baseline, relative rules (`max_regression`, `max_new_failures`) are reported as
skipped, absolute rules (`min_pass_rate`, `critical_tags`) are still enforced, and the suite
verdict is NO_BASELINE (exit 0) with a warning that names the fix
(`evalgate baseline update`). If an absolute rule fails, the verdict is FAIL.

## Consequences

- Adding a suite in a PR never blocks merging by itself, but an obviously broken suite still fails.
- The overall verdict is FAIL if any suite fails, else NO_BASELINE if any suite lacks a
  baseline, else PASS.
