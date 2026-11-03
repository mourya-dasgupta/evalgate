"""Custom scorers loaded from a Python dotted path.

``path`` may point to:

* a :class:`~evalgate.scorers.base.Scorer` subclass, or
* a function ``fn(output, case)`` or ``fn(output, case, options)`` (sync or async)
  returning a :class:`ScoreResult`, a float, a bool, or a ``(score, reason)`` tuple.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from evalgate.errors import ConfigError
from evalgate.golden import GoldenCase
from evalgate.loader import load_object
from evalgate.scorers.base import Scorer, ScoreResult, ScorerOptions, register_scorer


class CustomOptions(ScorerOptions):
    path: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)
    base_dir: str | None = None


def coerce_result(value: Any, source: str) -> ScoreResult:
    if isinstance(value, ScoreResult):
        return value
    if isinstance(value, bool):
        return ScoreResult(1.0 if value else 0.0, "passed" if value else "failed")
    if isinstance(value, int | float):
        return ScoreResult(float(value), f"score {float(value):.2f}")
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], int | float)
        and isinstance(value[1], str)
    ):
        return ScoreResult(float(value[0]), value[1])
    raise ConfigError(
        f"custom scorer {source!r} returned {type(value).__name__}",
        hint="return a ScoreResult, a float, a bool, or a (score, reason) tuple",
    )


@register_scorer("custom")
class CustomScorer(Scorer):
    Options = CustomOptions
    options: CustomOptions

    def __init__(self, options: ScorerOptions, deps: Any = None) -> None:
        super().__init__(options, deps)
        base = Path(self.options.base_dir) if self.options.base_dir else None
        target = load_object(self.options.path, base, what="custom scorer")
        self.delegate: Scorer | None = None
        self.fn: Callable[..., Any] | None = None
        if inspect.isclass(target) and issubclass(target, Scorer):
            opts = target.Options.model_validate(self.options.options)
            self.delegate = target(opts, deps)
        elif callable(target):
            self.fn = target
            self.arity = len(inspect.signature(target).parameters)
        else:
            raise ConfigError(f"custom scorer {self.options.path!r} is not callable")

    async def score(self, output: str, case: GoldenCase) -> ScoreResult:
        if self.delegate is not None:
            return await self.delegate.score(output, case)
        assert self.fn is not None
        args: tuple[Any, ...] = (output, case)
        if self.arity >= 3:
            args = (output, case, self.options.options)
        result = self.fn(*args)
        if inspect.isawaitable(result):
            result = await result
        return coerce_result(result, self.options.path)
