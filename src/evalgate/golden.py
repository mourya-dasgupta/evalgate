"""Golden sets: JSONL files of test cases.

Each non-blank line is a JSON object with ``id``, ``input`` (template variables),
``expected``, and optional ``tags`` and ``notes``. Errors are reported with line
numbers, and all problems in a file are reported at once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from evalgate.errors import GoldenSetError

MAX_REPORTED_ERRORS = 20


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    input: dict[str, Any]
    expected: Any
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    line: int = Field(default=0, exclude=True)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str]) -> list[str]:
        cleaned = [t.strip() for t in tags]
        if any(not t for t in cleaned):
            raise ValueError("tags must be non-empty strings")
        return cleaned


def _describe(err: Any) -> str:
    loc = ".".join(str(p) for p in err["loc"]) or "(line)"
    if err["type"] == "missing":
        return f"missing required field '{loc}'"
    if err["type"] == "extra_forbidden":
        return f"unknown field '{loc}' (allowed: id, input, expected, tags, notes)"
    return f"field '{loc}': {err['msg']}"


def parse_golden_lines(lines: list[str], source: str) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    errors: list[str] = []
    seen: dict[str, int] = {}
    for lineno, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSON ({exc.msg} at column {exc.colno})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"line {lineno}: expected a JSON object, got {type(obj).__name__}")
            continue
        try:
            case = GoldenCase.model_validate({**obj, "line": lineno})
        except ValidationError as exc:
            errors.extend(f"line {lineno}: {_describe(e)}" for e in exc.errors())
            continue
        if case.id in seen:
            errors.append(
                f"line {lineno}: duplicate id {case.id!r} (first used on line {seen[case.id]})"
            )
            continue
        seen[case.id] = lineno
        cases.append(case)
    if errors:
        shown = errors[:MAX_REPORTED_ERRORS]
        more = len(errors) - len(shown)
        body = "\n".join(f"  - {e}" for e in shown)
        if more:
            body += f"\n  ... and {more} more"
        raise GoldenSetError(
            f"{source} has {len(errors)} invalid line(s):\n{body}",
            hint='each line must look like {"id": "...", "input": {...}, "expected": ...}',
        )
    if not cases:
        raise GoldenSetError(f"{source} contains no cases", hint="add at least one JSONL line")
    return cases


def load_golden(path: Path) -> list[GoldenCase]:
    if not path.exists():
        raise GoldenSetError(
            f"golden set not found: {path}",
            hint="check the 'golden:' path in your config (relative to the config file)",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise GoldenSetError(f"{path} is not valid UTF-8 text") from None
    return parse_golden_lines(text.splitlines(), str(path))
