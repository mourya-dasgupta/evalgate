"""Load a provider from a Python dotted path (``module:ClassName``).

The class is instantiated with the :class:`ProviderConfig` if its constructor accepts
one argument, otherwise with no arguments. Its ``complete(request)`` may be sync or
async and may return a :class:`ChatResponse` or a plain string.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any

from evalgate.config import ProviderConfig
from evalgate.errors import ProviderError
from evalgate.loader import load_object
from evalgate.providers.base import ChatRequest, ChatResponse, Provider


class PythonProvider(Provider):
    name = "python"

    def __init__(self, config: ProviderConfig, root: Path) -> None:
        assert config.entrypoint is not None
        factory = load_object(config.entrypoint, root, what="provider entrypoint")
        try:
            params = inspect.signature(factory).parameters
            self.impl: Any = factory(config) if len(params) >= 1 else factory()
        except (TypeError, ValueError):
            self.impl = factory()
        if not callable(getattr(self.impl, "complete", None)):
            raise ProviderError(
                f"provider entrypoint {config.entrypoint!r} has no complete(request) method"
            )
        self.name = f"python:{config.entrypoint}"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        try:
            result = self.impl.complete(request)
            if inspect.isawaitable(result):
                result = await result
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.name} raised {exc.__class__.__name__}: {exc}") from exc
        latency = (time.perf_counter() - started) * 1000
        if isinstance(result, ChatResponse):
            return result
        if isinstance(result, str):
            return ChatResponse(text=result, latency_ms=latency)
        raise ProviderError(
            f"{self.name}.complete() returned {type(result).__name__}; expected str or ChatResponse"
        )
