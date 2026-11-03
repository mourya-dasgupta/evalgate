from __future__ import annotations

import json
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from evalgate import cli
from evalgate.cli import app
from tests.conftest import MOCK_CONFIG, write_jsonl

runner = CliRunner()


def invoke(*args: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=env)
    return result.exit_code, result.stdout, result.stderr


@pytest.fixture
def project(make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = make_project()
    monkeypatch.chdir(cfg.parent)
    return cfg


# -- basics -------------------------------------------------------------------------------


def test_version_and_help() -> None:
    code, out, _ = invoke("--version")
    assert code == 0 and out.strip() == "evalgate 0.1.0"
    code, out, _ = invoke("--help")
    assert code == 0
    for command in ("init", "run", "gate", "baseline", "report", "validate"):
        assert command in out


def test_invalid_mode_is_usage_error(project: Path) -> None:
    code, _, errout = invoke("--mode", "turbo", "run")
    assert code == 2 and "must be one of" in errout


def test_missing_config_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, out, errout = invoke("gate")
    assert code == 2
    assert "config file not found: evalgate.yaml" in errout
    assert "Traceback" not in out + errout


# -- init ---------------------------------------------------------------------------------


def test_init_then_quickstart_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, out, _ = invoke("init")
    assert code == 0
    for rel in ("evalgate.yaml", "prompts/sentiment.txt", "golden/sentiment.jsonl"):
        assert (tmp_path / rel).exists()
    assert (tmp_path / ".github/workflows/evalgate.yml").exists()
    assert "Next steps" in out

    code, out, _ = invoke("validate")
    assert code == 0 and "Configuration is valid" in out

    code, out, _ = invoke("gate")
    assert code == 0 and "NO BASELINE" in out

    code, out, _ = invoke("baseline", "update")
    assert code == 0 and "Baseline updated" in out
    assert (tmp_path / ".evalgate/baseline.json").exists()

    code, out, _ = invoke("gate")
    assert code == 0 and "Verdict: PASS" in out

    code, out, _ = invoke("init")
    assert code == 0 and "skipped" in out and "created" not in out
    code, out, _ = invoke("init", "--force")
    assert "created evalgate.yaml" in out


def test_init_into_directory(tmp_path: Path) -> None:
    code, _, _ = invoke("init", "--dir", str(tmp_path / "proj"))
    assert code == 0
    assert (tmp_path / "proj" / "evalgate.yaml").exists()


# -- validate -----------------------------------------------------------------------------


def test_validate_reports_errors_exit_2(project: Path) -> None:
    write_jsonl(project.parent / "golden" / "echo.jsonl", [{"id": "x", "input": {}}])
    code, out, _ = invoke("validate", "--suite", "echo")
    assert code == 2
    assert "invalid suite echo" in out
    assert "missing required field 'expected'" in out


def test_validate_bad_yaml(project: Path) -> None:
    project.write_text("suites: [\n", "utf-8")
    code, _, errout = invoke("validate")
    assert code == 2 and "not valid YAML" in errout


# -- run / gate ---------------------------------------------------------------------------


def test_run_and_suite_filter(project: Path) -> None:
    code, out, errout = invoke("run", "--suite", "echo")
    assert code == 0
    assert "echo" in out and "sentiment" not in out
    assert "Saved run to .evalgate/runs/" in errout
    runs = list((project.parent / ".evalgate" / "runs").glob("*.json"))
    assert len(runs) == 1
    data = json.loads(runs[0].read_text("utf-8"))
    assert [s["name"] for s in data["suites"]] == ["echo"]


def test_unknown_suite_exit_2(project: Path) -> None:
    code, _, errout = invoke("gate", "--suite", "nope")
    assert code == 2 and "unknown suite(s): nope" in errout


def test_gate_pass_then_fail_with_reports(project: Path) -> None:
    assert invoke("run")[0] == 0
    assert invoke("baseline", "update")[0] == 0
    code, out, _ = invoke(
        "gate",
        "--report-md",
        "out/r.md",
        "--report-html",
        "out/r.html",
        "--report-json",
        "out/r.json",
    )
    assert code == 0 and "Verdict: PASS" in out
    assert (project.parent / "out/r.md").read_text("utf-8").startswith("## EvalGate: ✅ PASS")
    assert "<!doctype html>" in (project.parent / "out/r.html").read_text("utf-8")
    assert json.loads((project.parent / "out/r.json").read_text("utf-8"))["verdict"] == "PASS"

    # A "prompt change" that breaks the positive rule -> regression -> exit 1
    project.write_text(
        MOCK_CONFIG.replace('respond: \'{"label": "positive"}\'', "respond: 'oops'"), "utf-8"
    )
    code, out, _ = invoke("gate", "--report-md", "out/fail.md")
    assert code == 1
    assert "Verdict: FAIL" in out
    md = (project.parent / "out/fail.md").read_text("utf-8")
    assert "flipped case(s) in sentiment" in md


def test_gate_suite_filter_only_gates_that_suite(project: Path) -> None:
    invoke("run")
    invoke("baseline", "update")
    project.write_text(
        MOCK_CONFIG.replace('respond: \'{"label": "positive"}\'', "respond: 'x'"), "utf-8"
    )
    code, out, _ = invoke("gate", "--suite", "echo")
    assert code == 0 and "sentiment" not in out


def test_global_options_before_command(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    code, out, _ = invoke("--config", str(project), "--verbose", "run", "--suite", "echo")
    assert code == 0 and "echo" in out


def test_corrupted_baseline_exit_2(project: Path) -> None:
    baseline = project.parent / ".evalgate" / "baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("{broken", "utf-8")
    code, _, errout = invoke("gate")
    assert code == 2
    assert "baseline" in errout and "corrupted" in errout


SIM = """
class Model:
    def complete(self, request):
        if "boom" in request.user_text:
            raise RuntimeError("upstream exploded")
        return "hello " + request.user_text
"""

PY_CONFIG = """\
version: 1
settings: {max_retries: 0, backoff_base_s: 0}
suites:
  - name: py
    target: {provider: python, entrypoint: "cli_sim_mod:Model", model: sim, prompt: p.txt}
    golden: g.jsonl
    scorers: [{type: contains, values: [hello]}]
    gate: {min_pass_rate: 1.0}
"""


@pytest.fixture
def py_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "cli_sim_mod.py").write_text(SIM, "utf-8")
    (tmp_path / "p.txt").write_text("{{ name }}", "utf-8")
    write_jsonl(tmp_path / "g.jsonl", [{"id": "a", "input": {"name": "asha"}, "expected": "x"}])
    (tmp_path / "evalgate.yaml").write_text(textwrap.dedent(PY_CONFIG), "utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cassette_miss_exit_3_then_record_then_replay(py_project: Path) -> None:
    code, _, errout = invoke("gate")
    assert code == 3
    assert "Provider error" in errout and "py/a" in errout
    assert "evalgate --mode record run --suite py" in errout

    code, _, errout = invoke("--mode", "record", "run")
    assert code == 0 and "Mode record" in errout
    assert (py_project / "cassettes" / "py.jsonl").exists()

    code, out, _ = invoke("gate")
    assert code == 0 and "NO BASELINE" in out

    code, _, errout = invoke("run", "--mode", "live")
    assert code == 0 and "Mode live" in errout


def test_env_var_selects_mode(py_project: Path) -> None:
    code, _, _ = invoke("run", env={"EVALGATE_MODE": "record"})
    assert code == 0
    assert (py_project / "cassettes" / "py.jsonl").exists()


def test_provider_error_exit_3_and_baseline_refuses_errored_run(py_project: Path) -> None:
    write_jsonl(
        py_project / "g.jsonl",
        [{"id": f"b{i}", "input": {"name": "boom"}, "expected": "x"} for i in range(7)],
    )
    code, _, errout = invoke("--mode", "live", "gate")
    assert code == 3
    assert "upstream exploded" in errout
    assert "... and 2 more" in errout
    assert "check API keys" in errout
    code, _, errout = invoke("baseline", "update")
    assert code == 2 and "errored case(s)" in errout


# -- baseline -----------------------------------------------------------------------------


def test_baseline_update_without_runs(project: Path) -> None:
    code, _, errout = invoke("baseline", "update")
    assert code == 2 and "no runs found" in errout


def test_baseline_show(project: Path) -> None:
    code, _, errout = invoke("baseline", "show")
    assert code == 2 and "no baseline" in errout
    invoke("run")
    invoke("baseline", "update", "--suite", "echo")
    code, out, _ = invoke("baseline", "show")
    assert code == 0 and "echo" in out and "sentiment" not in out


def test_baseline_update_from_specific_run(project: Path) -> None:
    invoke("run", "--suite", "echo")
    invoke("run")
    runs = sorted((project.parent / ".evalgate" / "runs").glob("*.json"))
    code, out, _ = invoke("baseline", "update", "--run", str(runs[0]))
    assert code == 0
    assert "echo: 1/1" in out and "sentiment" not in out


# -- report -------------------------------------------------------------------------------


def test_report_formats(project: Path) -> None:
    code, _, errout = invoke("report")
    assert code == 2 and "no runs found" in errout
    invoke("run")
    code, out, _ = invoke("report", "--format", "md")
    assert code == 0 and out.startswith("## EvalGate: ⚠️ NO BASELINE")
    code, out, _ = invoke("report", "-f", "json")
    assert json.loads(out)["verdict"] == "NO_BASELINE"
    code, _, errout = invoke("report", "--format", "html", "--output", "rep/r.html")
    assert code == 0 and (project.parent / "rep/r.html").exists()
    invoke("baseline", "update")
    code, _, errout = invoke("report")
    assert "this run is the baseline itself" in errout
    code, _, errout = invoke("report", "--format", "pdf")
    assert code == 2 and "must be md, html or json" in errout
    runs = sorted((project.parent / ".evalgate" / "runs").glob("*.json"))
    code, out, _ = invoke("report", "--run", str(runs[0]))
    assert code == 0 and "PASS" in out


# -- unexpected errors --------------------------------------------------------------------


def test_unexpected_error_is_friendly(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "run_sync", boom)
    code, _, errout = invoke("run")
    assert code == 2
    assert "Unexpected error: RuntimeError: kaboom" in errout
    assert "Traceback" not in errout
    code, _, errout = invoke("--verbose", "run")
    assert "Traceback" in errout


def test_keyboard_interrupt(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_sync", interrupt)
    code, _, errout = invoke("run")
    assert code == 130 and "Interrupted" in errout


def test_python_dash_m_entrypoint() -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "evalgate", "--version"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0 and proc.stdout.strip() == "evalgate 0.1.0"
