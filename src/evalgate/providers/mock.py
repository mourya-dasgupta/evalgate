"""A deterministic, rule-based provider for tests, demos and ``evalgate init``."""

from __future__ import annotations

import re

from evalgate.config import ProviderConfig
from evalgate.providers.base import ChatRequest, ChatResponse, Provider


class MockProvider(Provider):
    """Returns the ``respond`` of the first rule whose regex matches the user message
    (or the whole prompt if there is no user message), else ``mock_default``."""

    name = "mock"
    requires_recording = False

    def __init__(self, config: ProviderConfig) -> None:
        self.rules = [(re.compile(r.match), r.respond) for r in config.mock_responses]
        self.default = config.mock_default
        self.calls = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        text = request.user_text or request.prompt_text
        for pattern, respond in self.rules:
            if pattern.search(text):
                return ChatResponse(text=respond)
        return ChatResponse(text=self.default)
