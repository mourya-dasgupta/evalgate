"""Scorer base class, registry, and helpers shared by built-in scorers."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from evalgate.config import ProviderConfig, ScorerConfig
from evalgate.golden import GoldenCase
from evalgate.providers.base import Provider


@dataclass
class ScoreResult:
    """What a scorer returns: a score in [0, 1], a human-readable reason, and optional
    structured details (e.g. ``expected`` / ``predicted`` labels)."""

    score: float
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = max(0.0, min(1.0, float(self.score)))


@dataclass
class ScorerDeps:
    """Things a scorer may need from the runner (e.g. a provider for LLM judges)."""

    provider_factory: Callable[[ProviderConfig], Provider] | None = None


class ScorerOptions(BaseModel):
    """Base for scorer options; unknown options are errors."""

    model_config = ConfigDict(extra="forbid")


class FieldOptions(ScorerOptions):
    """``field``: dotted path into the JSON-parsed output (e.g. ``category`` or
    ``items.0.name``). ``expected_field``: dotted path into ``expected``; defaults to
    ``field`` when ``expected`` is an object."""

    field: str | None = None
    expected_field: str | None = None


class Scorer:
    """Base class for scorers. Override :meth:`score_sync` (or :meth:`score` for async)."""

    type_name: ClassVar[str] = ""
    Options: ClassVar[type[ScorerOptions]] = ScorerOptions

    def __init__(self, options: ScorerOptions, deps: ScorerDeps | None = None) -> None:
        self.options = options
        self.deps = deps or ScorerDeps()

    async def score(self, output: str, case: GoldenCase) -> ScoreResult:
        return self.score_sync(output, case)

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release resources held by the scorer."""


SCORERS: dict[str, type[Scorer]] = {}


def register_scorer(name: str) -> Callable[[type[Scorer]], type[Scorer]]:
    """Class decorator that adds a scorer to the registry under ``name``."""

    def _register(cls: type[Scorer]) -> type[Scorer]:
        cls.type_name = name
        SCORERS[name] = cls
        return cls

    return _register


@dataclass
class BoundScorer:
    """A scorer instance together with its suite-level settings."""

    config: ScorerConfig
    impl: Scorer

    @property
    def name(self) -> str:
        return self.config.display_name


# -- helpers -----------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)
_MISSING = object()


def strip_code_fences(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1) if match else text


def parse_json(text: str, *, allow_fences: bool = True) -> tuple[bool, Any, str]:
    """Parse model output as JSON. Returns ``(ok, value, error)``."""
    candidate = strip_code_fences(text) if allow_fences else text
    if not candidate.strip():
        return False, None, "output is empty"
    try:
        return True, json.loads(candidate), ""
    except json.JSONDecodeError as exc:
        return False, None, f"invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"


def get_path(obj: Any, path: str) -> Any:
    """Follow a dotted path through dicts and lists; returns a sentinel if missing."""
    node = obj
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.lstrip("-").isdigit():
            idx = int(part)
            if -len(node) <= idx < len(node):
                node = node[idx]
            else:
                return _MISSING
        else:
            return _MISSING
    return node


def is_missing(value: Any) -> bool:
    return value is _MISSING


def extract_output(output: str, field_path: str | None) -> tuple[bool, Any, str]:
    """The thing to score: the raw text, or a field of the JSON-parsed output."""
    if field_path is None:
        return True, output, ""
    ok, value, error = parse_json(output)
    if not ok:
        return False, None, f"cannot read field '{field_path}': {error}"
    found = get_path(value, field_path)
    if is_missing(found):
        return False, None, f"field '{field_path}' is missing from the output"
    return True, found, ""


def extract_expected(case: GoldenCase, opts: FieldOptions) -> tuple[bool, Any, str]:
    path = opts.expected_field or (opts.field if isinstance(case.expected, dict) else None)
    if path is None:
        return True, case.expected, ""
    found = get_path(case.expected, path)
    if is_missing(found):
        return False, None, f"golden case has no expected '{path}'"
    return True, found, ""


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def short(value: Any, limit: int = 80) -> str:
    text = as_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
