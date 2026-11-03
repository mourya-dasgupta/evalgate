"""Cassettes: record model responses once, replay them deterministically in CI.

A cassette is a JSONL file (``cassettes/<suite>.jsonl``). Each line maps a request
hash to the recorded response. The hash covers the model name, the fully rendered
messages and the request params, so *any* prompt change is a cache miss in replay
mode and must be re-recorded. That is intentional: a replayed answer to a different
prompt would be a lie.

Modes:

* ``replay`` (default): serve from the cassette; a miss raises :class:`CassetteMissError`.
* ``record``: call the real provider and upsert the response into the cassette.
* ``live``: call the real provider; the cassette is neither read nor written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalgate.config import Mode
from evalgate.errors import CassetteMissError, ProviderError
from evalgate.providers.base import ChatRequest, ChatResponse, Provider


class Cassette:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = {}
        self.dirty = False

    @classmethod
    def load(cls, path: Path) -> Cassette:
        cassette = cls(path)
        if not path.exists():
            return cassette
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                key = entry["key"]
                entry["response"]["text"]
            except (json.JSONDecodeError, KeyError, TypeError):
                raise ProviderError(
                    f"cassette {path} is corrupted at line {lineno}",
                    hint="re-record it with --mode record, or restore it from git",
                ) from None
            cassette.entries[key] = entry
        return cassette

    def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    def put(self, request: ChatRequest, response: ChatResponse, provider: str) -> None:
        key = request.cache_key()
        self.entries[key] = {
            "key": key,
            "provider": provider,
            "request": request.canonical(),
            "response": {"text": response.text, "usage": response.usage},
            "latency_ms": round(response.latency_ms, 1),
        }
        self.dirty = True

    def save(self) -> None:
        """Write entries sorted by key so re-recording produces minimal git diffs."""
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(self.entries[k], ensure_ascii=False, sort_keys=True)
            for k in sorted(self.entries)
        ]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.dirty = False


class CassetteProvider(Provider):
    """Wraps any provider with record / replay / live behaviour."""

    def __init__(self, inner: Provider, cassette: Cassette, mode: Mode, suite: str) -> None:
        self.inner = inner
        self.cassette = cassette
        self.mode = mode
        self.suite = suite
        self.name = inner.name
        self.hits = 0
        self.misses = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if self.mode == "live":
            return await self.inner.complete(request)
        key = request.cache_key()
        if self.mode == "replay":
            entry = self.cassette.get(key)
            if entry is None:
                self.misses += 1
                raise CassetteMissError(
                    f"no recording for this request in {self.cassette.path} "
                    f"(suite {self.suite!r}, model {request.model!r}, key {key[:12]})",
                    hint="the prompt, model or params changed since the cassette was recorded. "
                    "Re-record with: evalgate --mode record run "
                    f"--suite {self.suite} (needs the provider API key)",
                )
            self.hits += 1
            return ChatResponse(
                text=entry["response"]["text"],
                latency_ms=float(entry.get("latency_ms", 0.0)),
                cached=True,
                usage=dict(entry["response"].get("usage") or {}),
            )
        response = await self.inner.complete(request)
        self.cassette.put(request, response, self.inner.name)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
