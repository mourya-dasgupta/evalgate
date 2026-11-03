"""Shared HTTP plumbing: API keys, timeouts, retries with exponential backoff."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from typing import Any

import httpx

from evalgate.config import ProviderConfig, Settings
from evalgate.errors import ProviderError
from evalgate.providers.base import ChatRequest, ChatResponse, Provider

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
MAX_RETRY_AFTER_S = 60.0
NO_AUTH = frozenset({"none", "NONE", ""})


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, min(float(value), MAX_RETRY_AFTER_S))
    except ValueError:
        return None


class HTTPProvider(Provider):
    """A provider that talks JSON over HTTP, with retries and timeouts."""

    def __init__(
        self,
        config: ProviderConfig,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self.base_url = (config.resolved_base_url or "").rstrip("/")
        self.timeout_s = config.timeout_s or settings.timeout_s
        self.max_retries = settings.max_retries
        self.backoff_base_s = settings.backoff_base_s
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        self._client = client
        self._owns_client = client is None

    # -- helpers -----------------------------------------------------------------------

    def api_key(self) -> str | None:
        env_name = self.config.resolved_api_key_env
        if env_name is None or env_name in NO_AUTH:
            return None
        key = self._environ.get(env_name)
        if not key:
            raise ProviderError(
                f"{self.name}: environment variable {env_name} is not set",
                hint=f"export {env_name}=... before using --mode record/live, "
                "or use --mode replay with recorded cassettes "
                "(set 'api_key_env: none' for endpoints that need no key)",
            )
        return key

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        return float(self.backoff_base_s * (2**attempt))

    async def post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> tuple[dict[str, Any], float]:
        """POST with retries. Returns ``(json_body, latency_ms)``."""
        attempts = self.max_retries + 1
        last_problem = "unknown error"
        for attempt in range(attempts):
            retry_after: float | None = None
            started = time.perf_counter()
            try:
                resp = await self.client.post(
                    url, json=payload, headers=headers, timeout=self.timeout_s
                )
            except httpx.TimeoutException:
                last_problem = f"request timed out after {self.timeout_s:g}s"
            except httpx.TransportError as exc:
                last_problem = f"network error: {exc.__class__.__name__}: {exc}"
            else:
                latency_ms = (time.perf_counter() - started) * 1000
                if resp.status_code in RETRYABLE_STATUS:
                    last_problem = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    retry_after = parse_retry_after(resp.headers.get("retry-after"))
                elif resp.status_code >= 400:
                    hint = None
                    if resp.status_code in (401, 403):
                        hint = f"check that {self.config.resolved_api_key_env} holds a valid key"
                    elif resp.status_code == 404:
                        hint = f"check base_url ({self.base_url}) and model ({self.config.model})"
                    raise ProviderError(
                        f"{self.name}: HTTP {resp.status_code} from {url}: {resp.text[:300]}",
                        hint=hint,
                    )
                else:
                    try:
                        body = resp.json()
                    except ValueError:
                        raise ProviderError(
                            f"{self.name}: response from {url} is not JSON: {resp.text[:200]!r}"
                        ) from None
                    if not isinstance(body, dict):
                        raise ProviderError(f"{self.name}: expected a JSON object from {url}")
                    return body, latency_ms
            if attempt < attempts - 1:
                await asyncio.sleep(self.backoff(attempt, retry_after))
        raise ProviderError(
            f"{self.name}: giving up after {attempts} attempt(s): {last_problem}",
            hint="the provider may be rate-limiting or down; lower settings.concurrency, "
            "raise settings.max_retries, or try again later",
        )

    def malformed(self, detail: str) -> ProviderError:
        return ProviderError(f"{self.name}: malformed response: {detail}")

    async def complete(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError
