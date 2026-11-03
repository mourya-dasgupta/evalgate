"""Model providers and the factory that builds them from config."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from evalgate.config import ProviderConfig, Settings
from evalgate.providers.anthropic import AnthropicProvider
from evalgate.providers.base import ChatRequest, ChatResponse, Provider
from evalgate.providers.mock import MockProvider
from evalgate.providers.openai_compatible import OpenAICompatibleProvider
from evalgate.providers.python import PythonProvider

__all__ = [
    "AnthropicProvider",
    "ChatRequest",
    "ChatResponse",
    "MockProvider",
    "OpenAICompatibleProvider",
    "Provider",
    "PythonProvider",
    "create_provider",
]


def create_provider(
    config: ProviderConfig,
    settings: Settings,
    root: Path,
    environ: Mapping[str, str] | None = None,
) -> Provider:
    """Build the provider described by ``config``."""
    if config.provider == "mock":
        return MockProvider(config)
    if config.provider == "python":
        return PythonProvider(config, root)
    if config.provider == "anthropic":
        return AnthropicProvider(config, settings, environ=environ)
    return OpenAICompatibleProvider(config, settings, environ=environ)
