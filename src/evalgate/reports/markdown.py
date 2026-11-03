"""Markdown report, designed to be posted as a pull-request comment or written to
``$GITHUB_STEP_SUMMARY``."""

from __future__ import annotations

import re

from evalgate.compare import FlipCase
from evalgate.gate import GateResult, SuiteVerdict
from evalgate.reports.common import RULE_ICON, delta, pct, pretty, truncate, verdict_text
from evalgate.results import RunResult

MAX_FLIPS = 25
MAX_VALUE_CHARS = 1200


def fence(text: str, lang: str = "") -> str:
    """A code fence long enough that the content cannot close it early."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{text}\n{ticks}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _flip(flip: FlipCase) -> list[str]:
    tags = f" · tags: {', '.join(flip.tags)}" if flip.tags else ""
    lines = [f"#### `{flip.id}`{tags}", ""]
    if flip.input:
        lines += ["**Input**", "", fence(truncate(pretty(flip.input), MAX_VALUE_CHARS), "json"), ""]
    lines += [
        "**Expected**",
        "",
        fence(truncate(pretty(flip.expected), MAX_VALUE_CHARS), "json"),
        "",
    ]
    actual = flip.output if flip.output is not None else "(no output)"
    lines += ["**Actual**", "", fence(truncate(pretty(actual), MAX_VALUE_CHARS)), ""]
    if flip.reasons:
        lines.append("**Why it fails:** " + "; ".join(f"`{r}`" for r in flip.reasons))
        lines.append("")
    return lines


def _suite_details(sv: SuiteVerdict) -> list[str]:
    lines: list[str] = []
    if sv.rules or sv.warnings:
        lines += [f"**{sv.suite}** — gate rules", ""]
        lines += [f"- {RULE_ICON[r.status]} `{r.rule}`: {r.message}" for r in sv.rules]
        lines += [f"- ⚠️ {w}" for w in sv.warnings]
        lines.append("")
    flips = sv.comparison.new_failures
    if flips:
        lines += [
            "<details>",
            f"<summary><b>{len(flips)} flipped case(s) in {sv.suite}</b> "
            "(passed in the baseline, failing now)</summary>",
            "",
        ]
        for flip in flips[:MAX_FLIPS]:
            lines += _flip(flip)
        if len(flips) > MAX_FLIPS:
            lines += [f"_… and {len(flips) - MAX_FLIPS} more; see the HTML report._", ""]
        lines += ["</details>", ""]
    tags = sv.comparison.tags
    if tags:
        lines += [
            "<details>",
            f"<summary>Pass rate by tag — {sv.suite}</summary>",
            "",
            "| Tag | Cases | Pass rate | Δ vs baseline |",
            "|---|---:|---:|---:|",
        ]
        lines += [
            f"| `{_cell(t)}` | {d.total} | {pct(d.pass_rate)} | {delta(d.delta_pp)} |"
            for t, d in tags.items()
        ]
        lines += ["", "</details>", ""]
    return lines


def render_markdown(run: RunResult, gate: GateResult) -> str:
    lines = [f"## EvalGate: {verdict_text(gate.verdict)}", ""]
    baseline = f"baseline `{gate.baseline_run_id}`" if gate.baseline_run_id else "no baseline"
    lines += [f"Run `{run.run_id}` vs {baseline} · mode `{run.mode}`", ""]
    lines += [
        "| Suite | Cases | Pass rate | Δ vs baseline | Score | Flips | Verdict |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for sv in gate.suites:
        comp = sv.comparison
        flips = str(len(comp.new_failures)) if comp.has_baseline else "—"
        lines.append(
            f"| {_cell(sv.suite)} | {sv.metrics.total} | {pct(sv.metrics.pass_rate)} "
            f"| {delta(comp.delta_pp)} | {sv.metrics.score:.3f} | {flips} "
            f"| {verdict_text(sv.verdict)} |"
        )
    lines.append("")
    for sv in gate.suites:
        lines += _suite_details(sv)
    failed = [s.suite for s in gate.suites if s.verdict == "FAIL"]
    if gate.verdict == "FAIL":
        tail = f"{len(failed)} of {len(gate.suites)} suite(s) failed the gate: {', '.join(failed)}."
    elif gate.verdict == "NO_BASELINE":
        tail = "passing, but at least one suite has no baseline yet."
    else:
        tail = "all suites passed the gate."
    lines.append(f"**Verdict: {verdict_text(gate.verdict)}** — {tail}")
    return "\n".join(lines) + "\n"
