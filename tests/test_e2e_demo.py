"""End-to-end: the full demo story on the shipped support-triage example, offline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from evalgate.cli import app

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "support-triage"
runner = CliRunner()


@pytest.fixture
def demo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("evalgate.yaml", "sim_model.py"):
        shutil.copy(EXAMPLE / name, tmp_path / name)
    for name in ("prompts", "golden", "schemas", "cassettes"):
        shutil.copytree(EXAMPLE / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRIAGE_PROMPT", raising=False)
    return tmp_path


def test_demo_story_v1_baseline_v2_fails_v1_passes(demo_dir: Path) -> None:
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(app, ["baseline", "update"]).exit_code == 0

    result = runner.invoke(
        app,
        ["gate", "--report-md", "fail.md", "--report-html", "fail.html", "--report-json", "f.json"],
        env={"TRIAGE_PROMPT": "v2_regressed"},
    )
    assert result.exit_code == 1, result.output
    assert "Verdict: FAIL" in result.stdout
    report = json.loads((demo_dir / "f.json").read_text("utf-8"))
    suite = report["gate"]["suites"][0]
    failed_rules = {r["rule"] for r in suite["rules"] if r["status"] == "fail"}
    assert {"max_regression", "max_new_failures", "critical_tags"} <= failed_rules
    flipped_tags = {t for f in suite["comparison"]["new_failures"] for t in f["tags"]}
    assert {"injection", "polite-urgent", "angry-low"} <= flipped_tags
    md = (demo_dir / "fail.md").read_text("utf-8")
    assert md.startswith("## EvalGate: ❌ FAIL")
    assert "flipped case(s) in triage" in md

    result = runner.invoke(app, ["gate"])
    assert result.exit_code == 0, result.output
    assert "Verdict: PASS" in result.stdout


def test_v1_quality_band_and_v2_regression(demo_dir: Path) -> None:
    """Guards the demo's realism: v1 good-but-imperfect, v2 clearly worse."""
    runner.invoke(app, ["run"])
    v1 = json.loads(sorted((demo_dir / ".evalgate/runs").glob("*.json"))[-1].read_text("utf-8"))
    runner.invoke(app, ["run"], env={"TRIAGE_PROMPT": "v2_regressed"})
    v2 = json.loads(sorted((demo_dir / ".evalgate/runs").glob("*.json"))[-1].read_text("utf-8"))
    r1, r2 = v1["suites"][0], v2["suites"][0]
    assert 0.85 <= r1["metrics"]["pass_rate"] <= 0.92
    assert r1["tags"]["critical"]["pass_rate"] == 1.0
    assert r1["metrics"]["total"] >= 60
    assert r2["metrics"]["pass_rate"] <= r1["metrics"]["pass_rate"] - 0.15
    assert r2["tags"]["injection"]["pass_rate"] < r1["tags"]["injection"]["pass_rate"]
    assert r2["tags"]["polite-urgent"]["pass_rate"] < r1["tags"]["polite-urgent"]["pass_rate"]
    assert r1["cache_hits"] > 0 and all(c["cached"] for c in r1["cases"])


def test_committed_baseline_matches_v1_replay(demo_dir: Path) -> None:
    shutil.copytree(
        EXAMPLE / ".evalgate", demo_dir / ".evalgate", ignore=shutil.ignore_patterns("runs*")
    )
    result = runner.invoke(app, ["gate"])
    assert result.exit_code == 0, result.output
    assert "±0.0 pp" in result.stdout
