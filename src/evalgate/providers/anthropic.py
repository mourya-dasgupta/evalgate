"""Anthropic Messages API (``POST /v1/messages``) over plain httpx."""

from __future__ import annotations

from typing import Any

from evalgate.providers.base import ChatRequest, ChatResponse
from evalgate.providers.http import HTTPProvider

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024


class AnthropicProvider(HTTPProvider):
    name = "anthropic"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        key = self.api_key()
        if key:
            headers["x-api-key"] = key
        params = dict(request.params)
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": params.pop("max_tokens", DEFAULT_MAX_TOKENS),
            "messages": [dict(m) for m in request.messages if m["role"] != "system"],
            **params,
        }
        if request.system_text:
            payload["system"] = request.system_text
        body, latency = await self.post_json(f"{self.base_url}/v1/messages", payload, headers)
        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise self.malformed("expected a 'content' list")
        texts = [
            b["text"]
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        if not texts and blocks:
            raise self.malformed("no text blocks in 'content'")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return ChatResponse(text="".join(texts), latency_ms=latency, usage=usage or {})
