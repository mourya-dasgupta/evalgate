"""Error types and process exit codes.

Every error a user can cause is an :class:`EvalGateError`. The CLI catches these and
prints a friendly message (what is wrong, where, how to fix it) instead of a traceback.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes. They are part of the public contract with CI systems."""

    OK = 0
    GATE_FAILED = 1
    USAGE_ERROR = 2
    PROVIDER_ERROR = 3


class EvalGateError(Exception):
    """Base class for user-facing errors."""

    exit_code: ExitCode = ExitCode.USAGE_ERROR
    title: str = "Error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\nHint: {self.hint}"
        return self.message


class ConfigError(EvalGateError):
    """The configuration file is missing, malformed or invalid."""

    title = "Configuration error"


class GoldenSetError(ConfigError):
    """A golden set file is missing or contains invalid cases."""

    title = "Golden set error"


class TemplateError(ConfigError):
    """A prompt template could not be loaded or rendered."""

    title = "Prompt template error"


class UsageError(EvalGateError):
    """The command was used incorrectly (e.g. no runs exist yet)."""

    title = "Usage error"


class ProviderError(EvalGateError):
    """A model provider call failed (network, auth, rate limit, bad response)."""

    exit_code = ExitCode.PROVIDER_ERROR
    title = "Provider error"


class CassetteMissError(ProviderError):
    """Replay mode found no recorded response for a request."""

    title = "Cassette miss"
