# 0007. A case passes when all required scorers pass; weights only shape the score

- Status: Accepted
- Date: 2026-11-03

## Context

Scorers have weights. One option is "a case passes if its weighted score is above X".
That lets a strong score on an easy check hide a failure on the important one.

## Decision

Each scorer has `threshold` (default 1.0) and `required` (default true). A scorer passes
when `score >= threshold`. A case passes when every required scorer passes. The case
score is the weighted mean of all scorer scores and is reported, but the gate uses pass
rate.

## Consequences

- "Valid JSON but wrong priority" is a failure, which matches how a product owner reads it.
- Optional scorers (language detection, judge-rated summary quality) are tracked in reports
  without making the gate flaky.
- Weights matter for the score column and for trend reading, not for pass/fail.
