from __future__ import annotations

from typing import Any

import pytest

from evalgate.compare import compare_runs, compare_suite
from evalgate.config import EvalGateConfig, GateConfig
from evalgate.errors import ExitCode
from evalgate.gate import evaluate_gate, evaluate_suite
from evalgate.results import CaseResult, Metrics, RunResult, SuiteResult, TargetInfo


def suite(
    outcomes: dict[str, bool],
    tags: dict[str, list[str]] | None = None,
    name: str = "s",
    sha: str = "a",
) -> SuiteResult:
    tags = tags or {}
    cases = [
        CaseResult(
            id=cid,
            tags=tags.get(cid, []),
            passed=ok,
            score=1.0 if ok else 0.0,
            output=f"out-{cid}-{ok}",
            expected="exp",
        )
        for cid, ok in outcomes.items()
    ]
    tag_cases: dict[str, list[CaseResult]] = {}
    for c in cases:
        for t in c.tags:
            tag_cases.setdefault(t, []).append(c)
    return SuiteResult(
        name=name,
        target=TargetInfo(provider="mock", model="m", prompt="p", prompt_sha256=sha),
        golden="g",
        metrics=Metrics.from_cases(cases),
        tags={t: Metrics.from_cases(cs) for t, cs in tag_cases.items()},
        cases=cases,
    )


def run_of(*suites: SuiteResult, run_id: str = "r") -> RunResult:
    return RunResult(
        evalgate_version="0",
        run_id=run_id,
        created_at="now",
        mode="replay",
        config_path="c",
        suites=list(suites),
    )


def ten(passing: int, **kw: Any) -> SuiteResult:
    return suite({f"c{i}": i < passing for i in range(10)}, **kw)


# -- compare ------------------------------------------------------------------------------


def test_compare_flips_fixed_added_removed() -> None:
    base = suite({"a": True, "b": False, "c": True, "d": False, "gone": True}, {"a": ["x"]})
    cur = suite({"a": False, "b": True, "c": True, "d": False, "new": False}, {"a": ["x"]}, sha="b")
    comp = compare_suite(cur, base)
    assert [f.id for f in comp.new_failures] == ["a"]
    flip = comp.new_failures[0]
    assert flip.output == "out-a-False" and flip.baseline_output == "out-a-True"
    assert flip.tags == ["x"]
    assert comp.fixed == ["b"]
    assert comp.still_failing == ["d"]
    assert comp.added == ["new"]
    assert comp.removed == ["gone"]
    assert comp.prompt_changed is True
    assert comp.delta_pp == pytest.approx(40.0 - 60.0)
    assert comp.tags["x"].delta_pp == -100.0


def test_compare_without_baseline() -> None:
    comp = compare_suite(suite({"a": True}, {"a": ["t"]}), None)
    assert not comp.has_baseline and comp.delta_pp is None
    assert comp.tags["t"].baseline_pass_rate is None
    comps = compare_runs(run_of(suite({"a": True}, name="x")), run_of(suite({"a": True})))
    assert comps[0].has_baseline is False  # suite 'x' not in baseline


def test_compare_new_tag_has_no_delta() -> None:
    comp = compare_suite(suite({"a": True}, {"a": ["fresh"]}), suite({"a": True}))
    assert comp.tags["fresh"].delta_pp is None


# -- gate rules (boundaries) --------------------------------------------------------------


@pytest.mark.parametrize(("passing", "status"), [(8, "pass"), (7, "fail"), (10, "pass")])
def test_min_pass_rate_boundary(passing: int, status: str) -> None:
    cur = ten(passing)
    v = evaluate_suite(GateConfig(min_pass_rate=0.8), cur, compare_suite(cur, ten(10)))
    assert v.rules[0].status == status
    assert v.verdict == ("PASS" if status == "pass" else "FAIL")


@pytest.mark.parametrize(
    ("base", "cur", "status"), [(9, 8, "pass"), (9, 7, "fail"), (5, 9, "pass"), (9, 9, "pass")]
)
def test_max_regression_boundary(base: int, cur: int, status: str) -> None:
    current = ten(cur)
    v = evaluate_suite(GateConfig(max_regression=10), current, compare_suite(current, ten(base)))
    assert v.rules[0].status == status


def test_max_regression_float_boundary() -> None:
    # 2/3 -> 1/3 is reported as a 33.3334 pp drop (deltas are rounded to 4 decimals);
    # an allowance equal to the reported drop passes despite float noise
    base = suite({"a": True, "b": True, "c": False})
    cur = suite({"a": True, "b": False, "c": False})
    v = evaluate_suite(GateConfig(max_regression=33.3334), cur, compare_suite(cur, base))
    assert v.rules[0].status == "pass"
    v = evaluate_suite(GateConfig(max_regression=33.3), cur, compare_suite(cur, base))
    assert v.rules[0].status == "fail"


@pytest.mark.parametrize(("flips", "status"), [(0, "pass"), (2, "pass"), (3, "fail")])
def test_max_new_failures_boundary(flips: int, status: str) -> None:
    current = ten(10 - flips)
    v = evaluate_suite(GateConfig(max_new_failures=2), current, compare_suite(current, ten(10)))
    assert v.rules[0].status == status
    assert v.rules[0].actual == str(flips)


def test_critical_tags() -> None:
    tags = {"c1": ["critical"], "c2": ["vip", "other"]}
    ok = suite({"c1": True, "c2": True, "c3": False}, tags)
    v = evaluate_suite(GateConfig(critical_tags=["critical", "vip"]), ok, compare_suite(ok, ok))
    assert v.rules[0].status == "pass" and v.verdict == "PASS"
    bad = suite({"c1": True, "c2": False, "c3": False}, tags)
    v = evaluate_suite(GateConfig(critical_tags=["critical", "vip"]), bad, compare_suite(bad, ok))
    assert v.rules[0].status == "fail" and "c2" in v.rules[0].message
    assert v.verdict == "FAIL"
    assert [r.rule for r in v.failed_rules] == ["critical_tags"]


def test_no_baseline_checks_absolute_rules_only() -> None:
    rules = GateConfig(min_pass_rate=0.5, max_regression=1, max_new_failures=0)
    cur = ten(6)
    v = evaluate_suite(rules, cur, compare_suite(cur, None))
    assert v.verdict == "NO_BASELINE"
    assert [r.status for r in v.rules] == ["pass", "skipped", "skipped"]
    assert any("no baseline" in w for w in v.warnings)
    low = ten(4)
    assert evaluate_suite(rules, low, compare_suite(low, None)).verdict == "FAIL"
    crit = suite({"a": False}, {"a": ["critical"]})
    v = evaluate_suite(GateConfig(critical_tags=["critical"]), crit, compare_suite(crit, None))
    assert v.verdict == "FAIL"


def test_warnings_for_no_rules_changed_set_and_errors() -> None:
    cur = suite({"a": True, "new": True})
    cur.metrics.errored = 1
    v = evaluate_suite(GateConfig(), cur, compare_suite(cur, suite({"a": True, "old": True})))
    assert v.verdict == "PASS"
    joined = " ".join(v.warnings)
    assert "no gate rules configured" in joined
    assert "1 added, 1 removed" in joined
    assert "1 case(s) errored" in joined


def _config(**gate: Any) -> EvalGateConfig:
    return EvalGateConfig.model_validate(
        {
            "suites": [
                {
                    "name": n,
                    "target": {"provider": "mock", "model": "m", "prompt": "p"},
                    "golden": "g",
                    "scorers": [{"type": "exact_match"}],
                    "gate": gate,
                }
                for n in ("s", "t")
            ]
        }
    )


def test_overall_verdicts_and_exit_codes() -> None:
    cfg = _config(min_pass_rate=0.8, max_regression=5)
    base = run_of(ten(9), ten(9, name="t"), run_id="base")
    good = evaluate_gate(cfg, run_of(ten(9), ten(9, name="t")), base)
    assert good.verdict == "PASS" and good.exit_code == ExitCode.OK
    assert good.baseline_run_id == "base"
    bad = evaluate_gate(cfg, run_of(ten(9), ten(7, name="t")), base)
    assert bad.verdict == "FAIL" and bad.exit_code == ExitCode.GATE_FAILED
    assert [v.verdict for v in bad.suites] == ["PASS", "FAIL"]
    partial = evaluate_gate(cfg, run_of(ten(9), ten(9, name="t")), run_of(ten(9)))
    assert partial.verdict == "NO_BASELINE" and partial.exit_code == ExitCode.OK
    none = evaluate_gate(cfg, run_of(ten(9)), None)
    assert none.verdict == "NO_BASELINE" and none.baseline_run_id is None
    unknown = evaluate_gate(cfg, run_of(ten(1, name="zzz")), None)
    assert unknown.suites[0].rules == []
