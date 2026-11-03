"""Compare a run against the baseline: pass-rate deltas and per-case flips."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from evalgate.results import RunResult, SuiteResult


class FlipCase(BaseModel):
    """A case that passed in the baseline and fails now."""

    id: str
    tags: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    expected: Any = None
    output: str | None = None
    baseline_output: str | None = None
    reasons: list[str] = Field(default_factory=list)


class TagDelta(BaseModel):
    total: int
    pass_rate: float
    baseline_pass_rate: float | None = None
    delta_pp: float | None = None


class SuiteComparison(BaseModel):
    suite: str
    has_baseline: bool
    pass_rate: float
    score: float
    baseline_pass_rate: float | None = None
    baseline_score: float | None = None
    delta_pp: float | None = None
    score_delta: float | None = None
    new_failures: list[FlipCase] = Field(default_factory=list)
    fixed: list[str] = Field(default_factory=list)
    still_failing: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    prompt_changed: bool = False
    tags: dict[str, TagDelta] = Field(default_factory=dict)


def pp(rate: float) -> float:
    """Fraction → percentage points, rounded to avoid float noise in reports."""
    return round(rate * 100, 4)


def compare_suite(current: SuiteResult, baseline: SuiteResult | None) -> SuiteComparison:
    comp = SuiteComparison(
        suite=current.name,
        has_baseline=baseline is not None,
        pass_rate=current.metrics.pass_rate,
        score=current.metrics.score,
    )
    if baseline is None:
        comp.tags = {
            t: TagDelta(total=m.total, pass_rate=m.pass_rate) for t, m in current.tags.items()
        }
        return comp
    comp.baseline_pass_rate = baseline.metrics.pass_rate
    comp.baseline_score = baseline.metrics.score
    comp.delta_pp = round(pp(current.metrics.pass_rate) - pp(baseline.metrics.pass_rate), 4)
    comp.score_delta = round(current.metrics.score - baseline.metrics.score, 6)
    comp.prompt_changed = current.target.prompt_sha256 != baseline.target.prompt_sha256
    base_cases = {c.id: c for c in baseline.cases}
    current_ids = {c.id for c in current.cases}
    for case in current.cases:
        before = base_cases.get(case.id)
        if before is None:
            comp.added.append(case.id)
        elif before.passed and not case.passed:
            comp.new_failures.append(
                FlipCase(
                    id=case.id,
                    tags=case.tags,
                    input=case.input,
                    expected=case.expected,
                    output=case.output,
                    baseline_output=before.output,
                    reasons=case.failure_reasons,
                )
            )
        elif not before.passed and case.passed:
            comp.fixed.append(case.id)
        elif not before.passed and not case.passed:
            comp.still_failing.append(case.id)
    comp.removed = [cid for cid in base_cases if cid not in current_ids]
    for tag, metrics in current.tags.items():
        base_tag = baseline.tags.get(tag)
        comp.tags[tag] = TagDelta(
            total=metrics.total,
            pass_rate=metrics.pass_rate,
            baseline_pass_rate=base_tag.pass_rate if base_tag else None,
            delta_pp=round(pp(metrics.pass_rate) - pp(base_tag.pass_rate), 4) if base_tag else None,
        )
    return comp


def compare_runs(current: RunResult, baseline: RunResult | None) -> list[SuiteComparison]:
    return [
        compare_suite(suite, baseline.suite(suite.name) if baseline else None)
        for suite in current.suites
    ]
