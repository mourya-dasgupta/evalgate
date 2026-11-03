"""The provider interface: one async ``complete`` call per chat request."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

HASH_VERSION = 1


@dataclass(frozen=True)
class ChatRequest:
    """A provider-agnostic chat request.

    ``messages`` is a list of ``{"role": ..., "content": ...}`` dicts. The cassette key
    is derived from ``model``, ``messages`` (i.e. the *rendered* prompt) and ``params``.
    """

    model: str
    messages: tuple[dict[str, str], ...]
    params: dict[str, Any] = field(default_factory=dict)

    def canonical(self) -> dict[str, Any]:
        return {
            "v": HASH_VERSION,
            "model": self.model,
            "messages": [dict(m) for m in self.messages],
            "params": self.params,
        }

    def cache_key(self) -> str:
        """SHA-256 of the canonical JSON form (sorted keys, no whitespace, UTF-8)."""
        blob = json.dumps(
            self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def prompt_text(self) -> str:
        """All message contents joined; handy for rule-based providers."""
        return "\n\n".join(m["content"] for m in self.messages)

    @property
    def user_text(self) -> str:
        users = [m["content"] for m in self.messages if m["role"] == "user"]
        return users[-1] if users else ""

    @property
    def system_text(self) -> str:
        return "\n\n".join(m["content"] for m in self.messages if m["role"] == "system")


@dataclass
class ChatResponse:
    text: str
    latency_ms: float = 0.0
    cached: bool = False
    usage: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    """Base class for model providers."""

    #: Whether the cassette layer should wrap this provider. Deterministic in-process
    #: providers (``mock``) do not need recordings.
    requires_recording: bool = True
    name: str = "provider"

    @abstractmethod
    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Send one chat request and return the model's text."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release resources (HTTP clients)."""
