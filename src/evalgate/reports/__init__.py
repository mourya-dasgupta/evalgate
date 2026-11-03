"""Report renderers: terminal (rich), Markdown, HTML and JSON."""

from __future__ import annotations

from typing import Literal

from evalgate.gate import GateResult
from evalgate.reports.html import render_html
from evalgate.reports.json_report import render_json
from evalgate.reports.markdown import render_markdown
from evalgate.reports.terminal import render_terminal
from evalgate.results import RunResult

ReportFormat = Literal["md", "html", "json"]

__all__ = [
    "ReportFormat",
    "render",
    "render_html",
    "render_json",
    "render_markdown",
    "render_terminal",
]


def render(fmt: ReportFormat, run: RunResult, gate: GateResult) -> str:
    if fmt == "md":
        return render_markdown(run, gate)
    if fmt == "html":
        return render_html(run, gate)
    return render_json(run, gate)
