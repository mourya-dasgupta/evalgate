"""Rich terminal output."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from evalgate.gate import GateResult
from evalgate.reports.common import delta, pct
from evalgate.results import RunResult

STYLE = {"PASS": "bold green", "FAIL": "bold red", "NO_BASELINE": "bold yellow"}
RULE_MARK = {"pass": ("✓", "green"), "fail": ("✗", "red"), "skipped": ("–", "dim")}
MAX_FLIPS_SHOWN = 10


def _say(console: Console, text: str) -> None:
    console.print(text, emoji=False, highlight=False)


def render_terminal(
    console: Console, run: RunResult, gate: GateResult, *, verbose: bool = False
) -> None:
    table = Table(title=f"EvalGate · run {run.run_id} · mode {run.mode}", title_justify="left")
    for col, justify in [
        ("Suite", "left"),
        ("Cases", "right"),
        ("Pass rate", "right"),
        ("Δ vs baseline", "right"),
        ("Score", "right"),
        ("Flips", "right"),
        ("Verdict", "center"),
    ]:
        table.add_column(col, justify=justify)  # type: ignore[arg-type]
    for sv in gate.suites:
        comp = sv.comparison
        d = comp.delta_pp
        d_style = "red" if d is not None and d < 0 else "green" if d and d > 0 else ""
        table.add_row(
            sv.suite,
            str(sv.metrics.total),
            pct(sv.metrics.pass_rate),
            Text(delta(d), style=d_style),
            f"{sv.metrics.score:.3f}",
            str(len(comp.new_failures)) if comp.has_baseline else "—",
            Text(sv.verdict.replace("_", " "), style=STYLE[sv.verdict]),
        )
    console.print(table)

    for sv in gate.suites:
        _say(console, f"[bold]{escape(sv.suite)}[/bold]")
        for rule in sv.rules:
            mark, style = RULE_MARK[rule.status]
            _say(console, f"  [{style}]{mark}[/{style}] {rule.rule}: {escape(rule.message)}")
        for warning in sv.warnings:
            _say(console, f"  [yellow]![/yellow] {escape(warning)}")
        flips = sv.comparison.new_failures
        if flips:
            _say(console, f"  [red]Flipped to failing ({len(flips)}):[/red]")
            for flip in flips[: MAX_FLIPS_SHOWN if not verbose else len(flips)]:
                tags = f" [dim]({escape(', '.join(flip.tags))})[/dim]" if flip.tags else ""
                reason = escape(flip.reasons[0]) if flip.reasons else ""
                _say(console, f"    • {escape(flip.id)}{tags}: {reason}")
            hidden = len(flips) - MAX_FLIPS_SHOWN
            if hidden > 0 and not verbose:
                _say(console, f"    … and {hidden} more (use --verbose or the HTML report)")
        if sv.comparison.fixed:
            fixed = escape(", ".join(sv.comparison.fixed))
            _say(console, f"  [green]Fixed since baseline:[/green] {fixed}")

    style = STYLE[gate.verdict]
    label = gate.verdict.replace("_", " ")
    failed = sum(1 for s in gate.suites if s.verdict == "FAIL")
    summary = {
        "PASS": "all suites passed the gate",
        "FAIL": f"{failed} of {len(gate.suites)} suite(s) failed the gate",
        "NO_BASELINE": "passing, but some suites have no baseline yet",
    }[gate.verdict]
    console.print(Text.assemble(("Verdict: ", "bold"), (label, style), f" — {summary}"))
