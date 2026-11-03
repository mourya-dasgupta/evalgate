"""Gate rules and verdicts.

Per suite:

* ``min_pass_rate``   absolute floor on the pass rate (checked with or without a baseline)
* ``max_regression``  allowed pass-rate drop vs the baseline, in percentage points
* ``max_new_failures`` allowed number of flips (passed in baseline, failing now)
* ``critical_tags``   any failing case carrying one of these tags fails the gate

Boundaries are inclusive: a pass rate exactly equal to ``min_pass_rate`` passes, and a
drop exactly equal to ``max_regression`` passes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from evalgate.compare import SuiteComparison, compare_runs, pp
from evalgate.config import EvalGateConfig, GateConfig
from evalgate.errors import ExitCode
from evalgate.results import Metrics, RunResult, SuiteResult

Verdict = Literal["PASS", "FAIL", "NO_BASELINE"]
RuleStatus = Literal["pass", "fail", "skipped"]
EPSILON = 1e-9


class RuleResult(BaseModel):
    rule: str
    status: RuleStatus
    actual: str
    threshold: str
    message: str


class SuiteVerdict(BaseModel):
    suite: str
    verdict: Verdict
    metrics: Metrics
    rules: list[RuleResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    comparison: SuiteComparison

    @property
    def failed_rules(self) -> list[RuleResult]:
        return [r for r in self.rules if r.status == "fail"]


class GateResult(BaseModel):
    verdict: Verdict
    run_id: str
    baseline_run_id: str | None = None
    suites: list[SuiteVerdict]

    @property
    def exit_code(self) -> ExitCode:
        return ExitCode.GATE_FAILED if self.verdict == "FAIL" else ExitCode.OK


def _pct(rate: float) -> str:
    return f"{pp(rate):.1f}%"


def evaluate_suite(rules: GateConfig, result: SuiteResult, comp: SuiteComparison) -> SuiteVerdict:
    checks: list[RuleResult] = []
    warnings: list[str] = []
    rate = result.metrics.pass_rate

    if rules.min_pass_rate is not None:
        ok = rate + EPSILON >= rules.min_pass_rate
        checks.append(
            RuleResult(
                rule="min_pass_rate",
                status="pass" if ok else "fail",
                actual=_pct(rate),
                threshold=f">= {_pct(rules.min_pass_rate)}",
                message=f"pass rate {_pct(rate)} "
                + ("meets" if ok else "is below")
                + f" the floor of {_pct(rules.min_pass_rate)}",
            )
        )

    if rules.max_regression is not None:
        if comp.delta_pp is None:
            checks.append(
                RuleResult(
                    rule="max_regression",
                    status="skipped",
                    actual="n/a",
                    threshold=f"<= {rules.max_regression:g} pp",
                    message="no baseline to compare against",
                )
            )
        else:
            drop = -comp.delta_pp
            ok = drop <= rules.max_regression + EPSILON
            checks.append(
                RuleResult(
                    rule="max_regression",
                    status="pass" if ok else "fail",
                    actual=f"{comp.delta_pp:+.1f} pp",
                    threshold=f"drop <= {rules.max_regression:g} pp",
                    message=f"pass rate moved {comp.delta_pp:+.1f} pp vs baseline "
                    f"(allowed drop: {rules.max_regression:g} pp)",
                )
            )

    if rules.max_new_failures is not None:
        if not comp.has_baseline:
            checks.append(
                RuleResult(
                    rule="max_new_failures",
                    status="skipped",
                    actual="n/a",
                    threshold=f"<= {rules.max_new_failures}",
                    message="no baseline to compare against",
                )
            )
        else:
            flips = len(comp.new_failures)
            ok = flips <= rules.max_new_failures
            checks.append(
                RuleResult(
                    rule="max_new_failures",
                    status="pass" if ok else "fail",
                    actual=str(flips),
                    threshold=f"<= {rules.max_new_failures}",
                    message=f"{flips} case(s) flipped from pass to fail "
                    f"(allowed: {rules.max_new_failures})",
                )
            )

    if rules.critical_tags:
        critical = set(rules.critical_tags)
        failing = [c.id for c in result.cases if not c.passed and critical & set(c.tags)]
        checks.append(
            RuleResult(
                rule="critical_tags",
                status="fail" if failing else "pass",
                actual=f"{len(failing)} failing",
                threshold="0 failing",
                message=(
                    f"critical case(s) failing: {', '.join(failing)}"
                    if failing
                    else f"all cases tagged {sorted(critical)} pass"
                ),
            )
        )

    if not checks:
        warnings.append("no gate rules configured; this suite always passes")
    if not comp.has_baseline:
        warnings.append(
            "no baseline for this suite; only absolute rules were checked. "
            "Run 'evalgate baseline update' to set one"
        )
    if comp.added or comp.removed:
        warnings.append(
            f"golden set changed since the baseline ({len(comp.added)} added, "
            f"{len(comp.removed)} removed); the pass-rate delta compares different case sets"
        )
    if result.metrics.errored:
        warnings.append(f"{result.metrics.errored} case(s) errored and were counted as failures")

    if any(c.status == "fail" for c in checks):
        verdict: Verdict = "FAIL"
    elif not comp.has_baseline:
        verdict = "NO_BASELINE"
    else:
        verdict = "PASS"
    return SuiteVerdict(
        suite=result.name,
        verdict=verdict,
        metrics=result.metrics,
        rules=checks,
        warnings=warnings,
        comparison=comp,
    )


def evaluate_gate(config: EvalGateConfig, run: RunResult, baseline: RunResult | None) -> GateResult:
    comparisons = {c.suite: c for c in compare_runs(run, baseline)}
    rules_by_suite = {s.name: s.gate for s in config.suites}
    verdicts = [
        evaluate_suite(rules_by_suite.get(s.name, GateConfig()), s, comparisons[s.name])
        for s in run.suites
    ]
    overall: Verdict
    if any(v.verdict == "FAIL" for v in verdicts):
        overall = "FAIL"
    elif any(v.verdict == "NO_BASELINE" for v in verdicts):
        overall = "NO_BASELINE"
    else:
        overall = "PASS"
    return GateResult(
        verdict=overall,
        run_id=run.run_id,
        baseline_run_id=baseline.run_id if baseline else None,
        suites=verdicts,
    )
