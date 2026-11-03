"""Formatting helpers shared by the report renderers."""

from __future__ import annotations

import json
from typing import Any

from evalgate.gate import Verdict

VERDICT_ICON: dict[str, str] = {"PASS": "✅", "FAIL": "❌", "NO_BASELINE": "⚠️"}
VERDICT_LABEL: dict[str, str] = {"PASS": "PASS", "FAIL": "FAIL", "NO_BASELINE": "NO BASELINE"}
RULE_ICON: dict[str, str] = {"pass": "✅", "fail": "❌", "skipped": "➖"}


def pct(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def delta(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) < 0.05:
        return "±0.0 pp"
    return f"{value:+.1f} pp"


def verdict_text(verdict: Verdict) -> str:
    return f"{VERDICT_ICON[verdict]} {VERDICT_LABEL[verdict]}"


def pretty(value: Any) -> str:
    """Render expected/actual values readably: JSON-looking strings are re-indented."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
        if isinstance(parsed, dict | list):
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        return value
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more chars)"
