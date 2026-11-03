from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest
from rich.console import Console

from evalgate.config import load_config
from evalgate.gate import GateResult, evaluate_gate
from evalgate.reports import render, render_terminal
from evalgate.reports.common import delta, pct, pretty, truncate
from evalgate.reports.html import heat
from evalgate.reports.markdown import fence
from evalgate.results import RunResult
from evalgate.runner import run_sync
from tests.conftest import MOCK_CONFIG

SNAPSHOT = Path(__file__).parent / "snapshots" / "report.md"
FIXED = datetime(2026, 11, 3, 6, 0, 0, tzinfo=UTC)
# Baseline config: the negative rule is checked first, so the tricky case s5 passes.
BASELINE_CONFIG = MOCK_CONFIG.replace(
    """        - match: "(?i)love|great|excellent"
          respond: '{"label": "positive"}'
        - match: "(?i)hate|awful|terrible"
          respond: '{"label": "negative"}'""",
    """        - match: "(?i)hate|awful|terrible"
          respond: '{"label": "negative"}'
        - match: "(?i)love|great|excellent"
          respond: '{"label": "positive"}'""",
)


@pytest.fixture
def failing(make_project: Callable[..., Path]) -> tuple[RunResult, GateResult]:
    base_cfg = load_config(make_project(config=BASELINE_CONFIG))
    baseline = run_sync(base_cfg, base_cfg.suites, "replay", now=datetime(2026, 11, 1, tzinfo=UTC))
    cfg = load_config(
        make_project(config=MOCK_CONFIG.replace("max_regression: 10", "max_regression: 5"))
    )
    run = run_sync(cfg, cfg.suites, "replay", now=FIXED)
    return run, evaluate_gate(cfg, run, baseline)


def test_helpers() -> None:
    assert pct(None) == "—" and pct(0.8125) == "81.2%"
    assert delta(None) == "—" and delta(0.01) == "±0.0 pp" and delta(-18.75) == "-18.8 pp"
    assert pretty('{"a": 1}') == '{\n  "a": 1\n}'
    assert pretty("plain") == "plain"
    assert pretty("42") == "42"
    assert pretty({"k": "पैसा"}) == '{\n  "k": "पैसा"\n}'
    assert truncate("abcdef", 3).startswith("abc\n… (3 more chars)")
    assert fence("x") == "```\nx\n```"
    assert fence("has ``` inside").startswith("````")
    assert heat(0, 5) == "0" and heat(5, 5) == "0.72" and heat(1, 0) == "0"


def test_markdown_snapshot(failing: tuple[RunResult, GateResult]) -> None:
    run, gate = failing
    assert gate.verdict == "FAIL"
    text = render("md", run, gate)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(text, "utf-8")
    assert text == SNAPSHOT.read_text("utf-8")


def test_markdown_pass_and_no_baseline(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    run = run_sync(cfg, cfg.suites, "replay", now=FIXED)
    no_base = render("md", run, evaluate_gate(cfg, run, None))
    assert no_base.startswith("## EvalGate: ⚠️ NO BASELINE")
    assert "vs no baseline" in no_base
    assert "has no baseline yet" in no_base
    passed = render("md", run, evaluate_gate(cfg, run, run))
    assert "**Verdict: ✅ PASS** — all suites passed the gate." in passed
    assert "flipped case(s)" not in passed


def test_markdown_truncates_many_flips(make_project: Callable[..., Path]) -> None:
    cases = [
        {"id": f"c{i}", "input": {"text": "love"}, "expected": {"label": "positive"}}
        for i in range(30)
    ]
    cfg = load_config(make_project(cases=cases))
    good = run_sync(cfg, cfg.select_suites(["sentiment"]), "replay")
    bad_cfg = load_config(
        make_project(
            config=MOCK_CONFIG.replace('respond: \'{"label": "positive"}\'', "respond: nope"),
            cases=cases,
        )
    )
    bad = run_sync(bad_cfg, bad_cfg.select_suites(["sentiment"]), "replay")
    md = render("md", bad, evaluate_gate(bad_cfg, bad, good))
    assert "30 flipped case(s)" in md
    assert "… and 5 more; see the HTML report." in md


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.urls: list[str] = []
        self.void = {"meta", "br", "img", "link", "input", "hr"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"src", "href"} and value:
                self.urls.append(value)
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
        else:
            self.stack.pop()


def test_html_is_valid_and_self_contained(failing: tuple[RunResult, GateResult]) -> None:
    run, gate = failing
    html = render("html", run, gate)
    assert html.startswith("<!doctype html>")
    parser = _Collector()
    parser.feed(html)
    assert parser.errors == []
    assert parser.stack == []
    assert all(u.startswith("#") for u in parser.urls), parser.urls
    assert not re.search(r"""(src|href)\s*=\s*["']?https?:""", html)
    assert "@import" not in html and "url(" not in html
    assert "Confusion matrix" in html
    assert 'data-flipped="yes"' in html
    assert "critical" in html


def test_html_escapes_model_output(make_project: Callable[..., Path]) -> None:
    cfg = load_config(
        make_project(
            config=MOCK_CONFIG.replace(
                'mock_default: \'{"label": "neutral"}\'',
                "mock_default: '<script>alert(1)</script>'",
            )
        )
    )
    run = run_sync(cfg, cfg.suites, "replay")
    html = render("html", run, evaluate_gate(cfg, run, None))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_json_report(failing: tuple[RunResult, GateResult]) -> None:
    run, gate = failing
    data = json.loads(render("json", run, gate))
    assert data["verdict"] == "FAIL"
    assert data["exit_code"] == 1
    assert data["run"]["run_id"] == run.run_id
    flips = data["gate"]["suites"][0]["comparison"]["new_failures"]
    assert [f["id"] for f in flips] == ["s5"]


def test_terminal(failing: tuple[RunResult, GateResult]) -> None:
    run, gate = failing
    console = Console(record=True, width=120, color_system=None)
    render_terminal(console, run, gate)
    out = console.export_text()
    assert "sentiment" in out and "FAIL" in out
    assert "✗ max_regression" in out
    assert "s5 (tricky): label_match:label: expected 'negative'" in out
    assert "Verdict: FAIL — 1 of 2 suite(s) failed the gate" in out


def test_terminal_many_flips_and_fixed(make_project: Callable[..., Path]) -> None:
    cases = [
        {"id": f"c{i}", "input": {"text": "love"}, "expected": {"label": "positive"}}
        for i in range(12)
    ]
    cfg = load_config(make_project(cases=cases))
    good = run_sync(cfg, cfg.select_suites(["sentiment"]), "replay")
    bad_cfg = load_config(
        make_project(
            config=MOCK_CONFIG.replace('respond: \'{"label": "positive"}\'', "respond: nope"),
            cases=cases,
        )
    )
    bad = run_sync(bad_cfg, bad_cfg.select_suites(["sentiment"]), "replay")
    console = Console(record=True, width=120, color_system=None)
    render_terminal(console, bad, evaluate_gate(bad_cfg, bad, good))
    assert "… and 2 more" in console.export_text()
    console = Console(record=True, width=120, color_system=None)
    render_terminal(console, bad, evaluate_gate(bad_cfg, bad, good), verbose=True)
    assert "… and" not in console.export_text()
    console = Console(record=True, width=120, color_system=None)
    render_terminal(console, good, evaluate_gate(cfg, good, bad))
    text = console.export_text()
    assert "Fixed since baseline: c0" in text
    assert "Verdict: PASS" in text
    console = Console(record=True, width=120, color_system=None)
    render_terminal(console, good, evaluate_gate(cfg, good, None))
    assert "NO BASELINE" in console.export_text()
