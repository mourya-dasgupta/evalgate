"""Configuration models (``evalgate.yaml``) and loading.

The file is YAML, validated with Pydantic v2. Relative paths inside the config are
resolved against the directory that contains the config file, so a project can be run
from anywhere. String values may reference environment variables with ``${VAR}`` or
``${VAR:-default}``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from evalgate.errors import ConfigError

DEFAULT_CONFIG_NAME = "evalgate.yaml"

Mode = Literal["replay", "record", "live"]
ProviderKind = Literal["mock", "openai_compatible", "anthropic", "python"]

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

DEFAULT_BASE_URLS: dict[str, str] = {
    "openai_compatible": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}
DEFAULT_API_KEY_ENVS: dict[str, str] = {
    "openai_compatible": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MockRule(_Strict):
    """A rule for the ``mock`` provider: if ``match`` (a regex) matches the prompt,
    respond with ``respond``."""

    match: str
    respond: str

    @field_validator("match")
    @classmethod
    def _valid_regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {value!r}: {exc}") from exc
        return value


class ProviderConfig(_Strict):
    """Which model to call and how. Used for suite targets and for LLM judges."""

    provider: ProviderKind
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    entrypoint: str | None = Field(
        default=None, description="For provider 'python': 'module:ClassName'."
    )
    mock_responses: list[MockRule] = Field(default_factory=list)
    mock_default: str = ""
    timeout_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_provider_fields(self) -> ProviderConfig:
        if self.provider == "python" and not self.entrypoint:
            raise ValueError("provider 'python' needs 'entrypoint: module:ClassName'")
        if self.entrypoint and self.provider != "python":
            raise ValueError("'entrypoint' is only used with provider 'python'")
        if self.mock_responses and self.provider != "mock":
            raise ValueError("'mock_responses' is only used with provider 'mock'")
        return self

    @property
    def resolved_base_url(self) -> str | None:
        return self.base_url or DEFAULT_BASE_URLS.get(self.provider)

    @property
    def resolved_api_key_env(self) -> str | None:
        return self.api_key_env or DEFAULT_API_KEY_ENVS.get(self.provider)


class TargetConfig(ProviderConfig):
    """The model + prompt under test."""

    prompt: str = Field(min_length=1, description="Path to the prompt template file.")
    system_prompt: str | None = Field(
        default=None, description="Optional path to a system prompt template file."
    )


class ScorerConfig(BaseModel):
    """One scorer. Scorer-specific options are extra keys, validated by the scorer."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1)
    name: str | None = None
    weight: float = Field(default=1.0, ge=0)
    required: bool = True
    threshold: float = Field(default=1.0, ge=0, le=1)

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        field = self.options.get("field")
        return f"{self.type}:{field}" if isinstance(field, str) else self.type


class GateConfig(_Strict):
    """Rules that decide whether a suite passes."""

    min_pass_rate: float | None = Field(default=None, ge=0, le=1)
    max_regression: float | None = Field(
        default=None, ge=0, le=100, description="Allowed pass-rate drop, in percentage points."
    )
    max_new_failures: int | None = Field(default=None, ge=0)
    critical_tags: list[str] = Field(default_factory=list)


class SuiteConfig(_Strict):
    name: str
    description: str | None = None
    target: TargetConfig
    golden: str = Field(min_length=1, description="Path to the JSONL golden set.")
    scorers: list[ScorerConfig] = Field(min_length=1)
    gate: GateConfig = Field(default_factory=GateConfig)
    concurrency: int | None = Field(default=None, ge=1, le=256)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_PATTERN.match(value):
            raise ValueError(
                f"suite names may only contain letters, digits, '.', '_' and '-' (got {value!r})"
            )
        return value

    @model_validator(mode="after")
    def _unique_scorer_names(self) -> SuiteConfig:
        seen: set[str] = set()
        for scorer in self.scorers:
            name = scorer.display_name
            if name in seen:
                raise ValueError(
                    f"two scorers are both named {name!r}; give one of them a unique 'name:'"
                )
            seen.add(name)
        return self


class Settings(_Strict):
    concurrency: int = Field(default=8, ge=1, le=256)
    timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    backoff_base_s: float = Field(default=1.0, ge=0)
    cassette_dir: str = "cassettes"
    runs_dir: str = ".evalgate/runs"
    baseline_path: str = ".evalgate/baseline.json"


class EvalGateConfig(_Strict):
    version: Literal[1] = 1
    settings: Settings = Field(default_factory=Settings)
    suites: list[SuiteConfig] = Field(min_length=1)

    _path: Path = PrivateAttr(default=Path(DEFAULT_CONFIG_NAME))

    @model_validator(mode="after")
    def _unique_suite_names(self) -> EvalGateConfig:
        names = [s.name for s in self.suites]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate suite name(s): {', '.join(dupes)}")
        return self

    @property
    def path(self) -> Path:
        return self._path

    @property
    def root(self) -> Path:
        return self._path.parent

    def resolve(self, relative: str | Path) -> Path:
        """Resolve a path from the config against the config file's directory."""
        p = Path(relative)
        return p if p.is_absolute() else self.root / p

    @property
    def runs_dir(self) -> Path:
        return self.resolve(self.settings.runs_dir)

    @property
    def baseline_path(self) -> Path:
        return self.resolve(self.settings.baseline_path)

    @property
    def cassette_dir(self) -> Path:
        return self.resolve(self.settings.cassette_dir)

    def select_suites(self, names: list[str] | None) -> list[SuiteConfig]:
        """Return the suites to run, honouring ``--suite`` filters."""
        if not names:
            return list(self.suites)
        known = {s.name: s for s in self.suites}
        unknown = [n for n in names if n not in known]
        if unknown:
            raise ConfigError(
                f"unknown suite(s): {', '.join(unknown)}",
                hint=f"available suites: {', '.join(known)}",
            )
        return [known[n] for n in names]


def interpolate_env(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """Recursively replace ``${VAR}`` / ``${VAR:-default}`` in string values."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if name in env:
                return env[name]
            if default is not None:
                return default
            raise ConfigError(
                f"environment variable {name!r} is referenced in the config but not set",
                hint=f"export {name}=... or use '${{{name}:-default}}' in the config",
            )

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: interpolate_env(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate_env(v, env) for v in value]
    return value


def format_location(loc: tuple[int | str, ...], data: Any) -> str:
    """Turn a Pydantic error location into ``suites[0](triage).gate.min_pass_rate``."""
    parts: list[str] = []
    node: Any = data
    for item in loc:
        if isinstance(item, int):
            label = f"[{item}]"
            if isinstance(node, list) and 0 <= item < len(node):
                node = node[item]
                if isinstance(node, dict) and isinstance(node.get("name"), str):
                    label += f"({node['name']})"
            else:
                node = None
            parts.append(label)
        else:
            parts.append(("." if parts else "") + str(item))
            node = node.get(item) if isinstance(node, dict) else None
    return "".join(parts) or "(top level)"


def format_validation_error(exc: ValidationError, data: Any, source: str) -> str:
    lines = [f"{source} has {exc.error_count()} problem(s):"]
    for err in exc.errors():
        loc = tuple(err["loc"])
        where = format_location(loc, data)
        msg = err["msg"]
        if err["type"] == "extra_forbidden":
            msg = "unknown field (check the spelling, or see docs/guide.md for valid fields)"
        elif err["type"] == "missing":
            msg = "required field is missing"
        elif msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        lines.append(f"  - {where}: {msg}")
    return "\n".join(lines)


def parse_config(data: Any, path: Path, environ: Mapping[str, str] | None = None) -> EvalGateConfig:
    if data is None:
        raise ConfigError(f"{path} is empty", hint="run 'evalgate init' to create a starter config")
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    data = interpolate_env(data, environ)
    try:
        config = EvalGateConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            format_validation_error(exc, data, str(path)),
            hint="see docs/guide.md#configuration-reference",
        ) from None
    config._path = path
    return config


def load_config(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> EvalGateConfig:
    """Load and validate ``evalgate.yaml``."""
    cfg_path = Path(path) if path else Path(DEFAULT_CONFIG_NAME)
    if not cfg_path.exists():
        raise ConfigError(
            f"config file not found: {cfg_path}",
            hint="run 'evalgate init' to scaffold one, or pass --config PATH",
        )
    if cfg_path.is_dir():
        raise ConfigError(f"{cfg_path} is a directory, expected a YAML file")
    text = cfg_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise ConfigError(
            f"{cfg_path} is not valid YAML{where}: {problem}",
            hint="check indentation and quoting around that line",
        ) from None
    return parse_config(data, cfg_path.resolve(), environ)
