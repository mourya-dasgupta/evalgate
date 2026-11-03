"""A single self-contained HTML report (inline CSS/JS, no external assets)."""

from __future__ import annotations

from importlib import resources
from typing import Any

import jinja2

from evalgate import __version__
from evalgate.gate import GateResult
from evalgate.reports.common import VERDICT_LABEL, delta, pct, pretty
from evalgate.results import RunResult


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FunctionLoader(_load_template),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["pct"] = pct
    env.filters["delta"] = delta
    env.filters["pretty"] = pretty
    return env


def _load_template(name: str) -> str:
    return resources.files("evalgate.reports").joinpath("templates", name).read_text("utf-8")


def heat(count: int, row_total: int) -> str:
    """Background alpha for a confusion-matrix cell."""
    if not row_total or not count:
        return "0"
    return f"{0.12 + 0.6 * count / row_total:.2f}"


def render_html(run: RunResult, gate: GateResult) -> str:
    flips: dict[str, set[str]] = {
        sv.suite: {f.id for f in sv.comparison.new_failures} for sv in gate.suites
    }
    suites: list[dict[str, Any]] = []
    for sv in gate.suites:
        result = run.suite(sv.suite)
        assert result is not None
        suites.append({"verdict": sv, "result": result, "flips": flips[sv.suite]})
    template = _environment().get_template("report.html.j2")
    return template.render(
        run=run,
        gate=gate,
        suites=suites,
        verdict_label=VERDICT_LABEL,
        heat=heat,
        version=__version__,
    )
