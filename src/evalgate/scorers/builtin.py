"""Built-in deterministic scorers."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Literal

import jsonschema
from pydantic import Field, field_validator, model_validator

from evalgate.golden import GoldenCase
from evalgate.scorers.base import (
    FieldOptions,
    Scorer,
    ScoreResult,
    ScorerOptions,
    as_text,
    extract_expected,
    extract_output,
    parse_json,
    register_scorer,
    short,
)

_WS = re.compile(r"\s+")


def normalise(text: str, *, case_sensitive: bool, whitespace: bool, strip: bool) -> str:
    if strip:
        text = text.strip()
    if whitespace:
        text = _WS.sub(" ", text)
    if not case_sensitive:
        text = text.casefold()
    return text


class FieldScorer(Scorer):
    """Shared plumbing: pull the output value and the expected value."""

    options: FieldOptions

    def values(self, output: str, case: GoldenCase) -> tuple[Any, Any, ScoreResult | None]:
        ok, actual, err = extract_output(output, self.options.field)
        if not ok:
            return None, None, ScoreResult(0.0, err)
        ok, expected, err = extract_expected(case, self.options)
        if not ok:
            return None, None, ScoreResult(0.0, err)
        return actual, expected, None


# -- exact_match ---------------------------------------------------------------------------


class ExactMatchOptions(FieldOptions):
    case_sensitive: bool = True
    normalize_whitespace: bool = True
    strip: bool = True


@register_scorer("exact_match")
class ExactMatch(FieldScorer):
    """Output (or a field of it) equals ``expected`` after normalisation."""

    Options = ExactMatchOptions
    options: ExactMatchOptions

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        actual, expected, failure = self.values(output, case)
        if failure:
            return failure
        o = self.options

        def norm(v: Any) -> str:
            return normalise(
                as_text(v),
                case_sensitive=o.case_sensitive,
                whitespace=o.normalize_whitespace,
                strip=o.strip,
            )

        if norm(actual) == norm(expected):
            return ScoreResult(1.0, "exact match")
        return ScoreResult(0.0, f"expected {short(expected)!r}, got {short(actual)!r}")


# -- contains / not_contains ----------------------------------------------------------------


class ContainsOptions(FieldOptions):
    values: list[str] | None = None
    case_sensitive: bool = False
    mode: Literal["all", "any"] = "all"

    @field_validator("values", mode="before")
    @classmethod
    def _one_or_many(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v


def _needles(opts: ContainsOptions, case: GoldenCase) -> list[str] | ScoreResult:
    if opts.values is not None:
        return opts.values
    ok, expected, err = extract_expected(case, opts)
    if not ok:
        return ScoreResult(0.0, err)
    if isinstance(expected, str):
        return [expected]
    if isinstance(expected, list) and all(isinstance(x, str) for x in expected):
        return list(expected)
    return ScoreResult(0.0, "no 'values' configured and 'expected' is not a string or list")


def _found(haystack: str, needles: list[str], case_sensitive: bool) -> list[str]:
    hay = haystack if case_sensitive else haystack.casefold()
    return [n for n in needles if (n if case_sensitive else n.casefold()) in hay]


@register_scorer("contains")
class Contains(Scorer):
    """Output contains the configured ``values`` (or ``expected``). Score is the
    fraction found (``mode: all``) or 1/0 (``mode: any``)."""

    Options = ContainsOptions
    options: ContainsOptions

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        ok, actual, err = extract_output(output, self.options.field)
        if not ok:
            return ScoreResult(0.0, err)
        needles = _needles(self.options, case)
        if isinstance(needles, ScoreResult):
            return needles
        if not needles:
            return ScoreResult(1.0, "nothing to look for")
        found = _found(as_text(actual), needles, self.options.case_sensitive)
        missing = [n for n in needles if n not in found]
        if self.options.mode == "any":
            if found:
                return ScoreResult(1.0, f"found {found[0]!r}")
            return ScoreResult(0.0, f"none of {needles} found")
        score = len(found) / len(needles)
        reason = "all values found" if not missing else f"missing {missing}"
        return ScoreResult(score, reason)


@register_scorer("not_contains")
class NotContains(Scorer):
    """Output must not contain any of ``values``."""

    Options = ContainsOptions
    options: ContainsOptions

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        ok, actual, err = extract_output(output, self.options.field)
        if not ok:
            return ScoreResult(0.0, err)
        needles = _needles(self.options, case)
        if isinstance(needles, ScoreResult):
            return needles
        found = _found(as_text(actual), needles, self.options.case_sensitive)
        if found:
            return ScoreResult(0.0, f"forbidden text found: {found}")
        return ScoreResult(1.0, "no forbidden text")


# -- regex -----------------------------------------------------------------------------------


class RegexOptions(FieldOptions):
    pattern: str
    ignore_case: bool = False
    full_match: bool = False

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {v!r}: {exc}") from exc
        return v


@register_scorer("regex")
class Regex(Scorer):
    """Output (or a field) matches ``pattern``."""

    Options = RegexOptions
    options: RegexOptions

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        ok, actual, err = extract_output(output, self.options.field)
        if not ok:
            return ScoreResult(0.0, err)
        flags = re.IGNORECASE if self.options.ignore_case else 0
        rx = re.compile(self.options.pattern, flags)
        text = as_text(actual)
        matched = rx.fullmatch(text) if self.options.full_match else rx.search(text)
        if matched:
            return ScoreResult(1.0, f"matched /{self.options.pattern}/")
        return ScoreResult(0.0, f"no match for /{self.options.pattern}/ in {short(text)!r}")


# -- json_valid / json_schema ------------------------------------------------------------------


class JsonValidOptions(ScorerOptions):
    allow_code_fences: bool = True
    require_object: bool = False


@register_scorer("json_valid")
class JsonValid(Scorer):
    """Output parses as JSON (optionally inside a Markdown code fence)."""

    Options = JsonValidOptions
    options: JsonValidOptions

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        ok, value, err = parse_json(output, allow_fences=self.options.allow_code_fences)
        if not ok:
            return ScoreResult(0.0, err)
        if self.options.require_object and not isinstance(value, dict):
            return ScoreResult(0.0, f"expected a JSON object, got {type(value).__name__}")
        return ScoreResult(1.0, "valid JSON")


class JsonSchemaOptions(ScorerOptions):
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    schema_path: str | None = None
    field: str | None = None
    #: Directory used to resolve ``schema_path``; injected by the scorer factory.
    base_dir: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> JsonSchemaOptions:
        if (self.schema_ is None) == (self.schema_path is None):
            raise ValueError("set exactly one of 'schema' (inline) or 'schema_path'")
        return self


@register_scorer("json_schema")
class JsonSchema(Scorer):
    """Output is JSON that validates against a JSON Schema."""

    Options = JsonSchemaOptions
    options: JsonSchemaOptions

    def __init__(self, options: ScorerOptions, deps: Any = None) -> None:
        super().__init__(options, deps)
        opts = self.options
        schema = opts.schema_
        if schema is None:
            assert opts.schema_path is not None
            path = Path(opts.schema_path)
            if not path.is_absolute() and opts.base_dir:
                path = Path(opts.base_dir) / path
            try:
                schema = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise ValueError(f"schema file not found: {path}") from None
            except json.JSONDecodeError as exc:
                raise ValueError(f"schema file {path} is not valid JSON: {exc.msg}") from None
        if not isinstance(schema, dict):
            raise ValueError("the JSON Schema must be an object")
        try:
            validator_cls = jsonschema.validators.validator_for(schema)
            validator_cls.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise ValueError(f"invalid JSON Schema: {exc.message}") from None
        self.validator = validator_cls(schema)

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        if self.options.field:
            ok, value, err = extract_output(output, self.options.field)
        else:
            ok, value, err = parse_json(output)
        if not ok:
            return ScoreResult(0.0, err)
        errors = sorted(self.validator.iter_errors(value), key=lambda e: list(e.path))
        if not errors:
            return ScoreResult(1.0, "matches schema")
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
        return ScoreResult(0.0, f"schema violation at {where}: {first.message}{more}")


# -- numeric_tolerance -------------------------------------------------------------------------

_NUMBER = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?")


def to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        match = _NUMBER.search(value)
        if match:
            try:
                return float(match.group(0).replace(",", ""))
            except ValueError:  # pragma: no cover - regex guarantees a number
                return None
    return None


class NumericOptions(FieldOptions):
    tolerance: float = Field(default=0.0, ge=0)
    relative: float = Field(default=0.0, ge=0, description="Relative tolerance, e.g. 0.05 = 5%")


@register_scorer("numeric_tolerance")
class NumericTolerance(FieldScorer):
    """A number in the output is within ``tolerance`` (absolute) or ``relative`` of
    the expected number."""

    Options = NumericOptions
    options: NumericOptions

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        actual, expected, failure = self.values(output, case)
        if failure:
            return failure
        a, e = to_number(actual), to_number(expected)
        if e is None:
            return ScoreResult(0.0, f"expected value {short(expected)!r} is not a number")
        if a is None:
            return ScoreResult(0.0, f"no number found in output {short(actual)!r}")
        allowed = max(self.options.tolerance, self.options.relative * abs(e))
        diff = abs(a - e)
        if diff <= allowed + 1e-12:
            return ScoreResult(1.0, f"{a:g} is within {allowed:g} of {e:g}")
        return ScoreResult(0.0, f"{a:g} differs from {e:g} by {diff:g} (allowed {allowed:g})")


# -- label_match -------------------------------------------------------------------------------


class LabelOptions(FieldOptions):
    case_sensitive: bool = False
    labels: list[str] | None = None


@register_scorer("label_match")
class LabelMatch(FieldScorer):
    """Classification: the predicted label equals the expected label. Suite results
    include a confusion matrix for every ``label_match`` scorer."""

    Options = LabelOptions
    options: LabelOptions

    def _norm(self, value: Any) -> str:
        text = as_text(value).strip()
        return text if self.options.case_sensitive else text.casefold()

    def score_sync(self, output: str, case: GoldenCase) -> ScoreResult:
        ok, expected, err = extract_expected(case, self.options)
        if not ok:
            return ScoreResult(0.0, err)
        exp = self._norm(expected)
        ok, actual, err = extract_output(output, self.options.field)
        if not ok:
            return ScoreResult(0.0, err, {"expected": exp, "predicted": "<missing>"})
        pred = self._norm(actual)
        details = {"expected": exp, "predicted": pred}
        allowed = self.options.labels
        if allowed is not None and pred not in {self._norm(x) for x in allowed}:
            return ScoreResult(0.0, f"predicted {pred!r} is not an allowed label", details)
        if pred == exp:
            return ScoreResult(1.0, f"label {pred!r}", details)
        return ScoreResult(0.0, f"expected {exp!r}, predicted {pred!r}", details)
