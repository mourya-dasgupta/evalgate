"""Any OpenAI-style ``/chat/completions`` endpoint (OpenAI, Azure-compatible gateways,
Groq, Together, vLLM, Ollama, LiteLLM, ...)."""

from __future__ import annotations

from typing import Any

from evalgate.providers.base import ChatRequest, ChatResponse
from evalgate.providers.http import HTTPProvider


class OpenAICompatibleProvider(HTTPProvider):
    name = "openai_compatible"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        headers = {"Content-Type": "application/json"}
        key = self.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [dict(m) for m in request.messages],
            **request.params,
        }
        body, latency = await self.post_json(f"{self.base_url}/chat/completions", payload, headers)
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise self.malformed("expected choices[0].message.content") from None
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise self.malformed("choices[0].message.content is not a string")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return ChatResponse(text=content, latency_ms=latency, usage=usage or {})
