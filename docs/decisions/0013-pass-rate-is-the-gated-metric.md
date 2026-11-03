# 0013. Gate on pass rate in percentage points, not mean score

- Status: Accepted
- Date: 2026-11-03

## Context

Two natural metrics exist: pass rate (share of cases that pass) and mean weighted score.

## Decision

Gate rules use pass rate. `max_regression` is expressed in percentage points of pass rate
(5 means 90.0% → 85.0% is the largest allowed drop). Boundaries are inclusive: equal to
the limit passes. Deltas are rounded to 4 decimals so float noise cannot flip a verdict.
The mean score is reported alongside for context.

## Consequences

- Rules read like product requirements ("at least 80% of tickets triaged correctly").
- Pass rate is coarse on small golden sets (one case in 66 is 1.5 pp). The guide recommends
  30+ cases per suite and setting `max_regression` above one case's worth.
- When the golden set changes between baseline and run, the delta compares different case
  sets; the gate warns about this explicitly.
