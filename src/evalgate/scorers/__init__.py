"""Scorers: pluggable functions that grade one output, returning a 0-1 score + reason."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from evalgate.config import EvalGateConfig, SuiteConfig
from evalgate.errors import ConfigError, EvalGateError
from evalgate.scorers import builtin, custom, llm_judge  # noqa: F401 - registers scorers
from evalgate.scorers.base import (
    SCORERS,
    BoundScorer,
    Scorer,
    ScorerDeps,
    ScoreResult,
    ScorerOptions,
    register_scorer,
)

__all__ = [
    "SCORERS",
    "BoundScorer",
    "ScoreResult",
    "Scorer",
    "ScorerDeps",
    "ScorerOptions",
    "build_scorers",
    "register_scorer",
]

_PATH_AWARE = {"json_schema", "custom"}


def build_scorers(
    suite: SuiteConfig, config: EvalGateConfig, deps: ScorerDeps | None = None
) -> list[BoundScorer]:
    """Instantiate and validate every scorer of a suite."""
    bound: list[BoundScorer] = []
    for index, sc in enumerate(suite.scorers):
        where = f"suite {suite.name!r}, scorers[{index}] ({sc.display_name})"
        cls = SCORERS.get(sc.type)
        if cls is None:
            raise ConfigError(
                f"{where}: unknown scorer type {sc.type!r}",
                hint=f"built-in types: {', '.join(sorted(SCORERS))}; "
                "or use type 'custom' with 'path: module:function'",
            )
        raw: dict[str, Any] = sc.options
        if sc.type in _PATH_AWARE:
            raw.setdefault("base_dir", str(config.root))
        try:
            options = cls.Options.model_validate(raw)
            impl = cls(options, deps)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'options'}: "
                + (
                    "unknown option"
                    if e["type"] == "extra_forbidden"
                    else e["msg"].removeprefix("Value error, ")
                )
                for e in exc.errors()
            )
            raise ConfigError(f"{where}: {problems}") from None
        except EvalGateError as exc:
            raise ConfigError(f"{where}: {exc.message}", hint=exc.hint) from None
        except ValueError as exc:
            raise ConfigError(f"{where}: {exc}") from None
        bound.append(BoundScorer(config=sc, impl=impl))
    return bound
