from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from evalgate.config import ProviderConfig, Settings
from evalgate.errors import ConfigError, ProviderError
from evalgate.providers import (
    AnthropicProvider,
    ChatRequest,
    ChatResponse,
    MockProvider,
    OpenAICompatibleProvider,
    PythonProvider,
    create_provider,
)
from evalgate.providers.http import parse_retry_after

SETTINGS = Settings(max_retries=2, backoff_base_s=0, timeout_s=5)
ENV = {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "ak-test"}
REQ = ChatRequest(
    model="m",
    messages=({"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}),
    params={"temperature": 0},
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def openai_ok(text: str = "hello") -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 3}}
    )


def oai(settings: Settings = SETTINGS, **kw: object) -> OpenAICompatibleProvider:
    cfg = ProviderConfig(provider="openai_compatible", model="m", **kw)  # type: ignore[arg-type]
    return OpenAICompatibleProvider(cfg, settings, environ=ENV)


# -- request hashing -----------------------------------------------------------------------


def test_cache_key_is_stable_and_sensitive() -> None:
    same = ChatRequest(model="m", messages=REQ.messages, params={"temperature": 0})
    assert REQ.cache_key() == same.cache_key()
    assert len(REQ.cache_key()) == 64
    changed_prompt = ChatRequest(
        model="m", messages=({"role": "user", "content": "hi!"},), params=REQ.params
    )
    assert REQ.cache_key() != changed_prompt.cache_key()
    assert REQ.cache_key() != ChatRequest("m2", REQ.messages, REQ.params).cache_key()
    assert REQ.cache_key() != ChatRequest("m", REQ.messages, {"temperature": 1}).cache_key()
    # param ordering does not matter
    a = ChatRequest("m", REQ.messages, {"a": 1, "b": 2})
    b = ChatRequest("m", REQ.messages, {"b": 2, "a": 1})
    assert a.cache_key() == b.cache_key()


def test_request_text_helpers() -> None:
    assert REQ.user_text == "hi"
    assert REQ.system_text == "be terse"
    assert REQ.prompt_text == "be terse\n\nhi"
    assert ChatRequest("m", ({"role": "system", "content": "x"},)).user_text == ""


# -- openai_compatible ---------------------------------------------------------------------


@respx.mock
async def test_openai_success_sends_auth_and_params() -> None:
    route = respx.post(OPENAI_URL).mock(return_value=openai_ok("bonjour"))
    provider = oai()
    resp = await provider.complete(REQ)
    await provider.aclose()
    assert resp.text == "bonjour"
    assert resp.usage == {"total_tokens": 3}
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-test"
    body = __import__("json").loads(sent.content)
    assert body["model"] == "m"
    assert body["temperature"] == 0
    assert body["messages"][1] == {"role": "user", "content": "hi"}


@respx.mock
async def test_openai_retries_on_429_then_succeeds() -> None:
    route = respx.post(OPENAI_URL).mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "0"}), openai_ok()]
    )
    assert (await oai().complete(REQ)).text == "hello"
    assert route.call_count == 2


@respx.mock
async def test_openai_retries_on_500_then_succeeds() -> None:
    route = respx.post(OPENAI_URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(503), openai_ok("ok")]
    )
    assert (await oai().complete(REQ)).text == "ok"
    assert route.call_count == 3


@respx.mock
async def test_openai_gives_up_after_max_retries() -> None:
    route = respx.post(OPENAI_URL).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(ProviderError) as exc:
        await oai().complete(REQ)
    assert route.call_count == 3
    assert "giving up after 3 attempt(s): HTTP 500: boom" in exc.value.message
    assert exc.value.exit_code == 3


@respx.mock
async def test_openai_timeout_is_retried_then_reported() -> None:
    route = respx.post(OPENAI_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError, match="timed out after 5s"):
        await oai().complete(REQ)
    assert route.call_count == 3


@respx.mock
async def test_openai_network_error_then_success() -> None:
    respx.post(OPENAI_URL).mock(side_effect=[httpx.ConnectError("refused"), openai_ok()])
    assert (await oai().complete(REQ)).text == "hello"


@respx.mock
async def test_openai_timeout_then_success() -> None:
    respx.post(OPENAI_URL).mock(side_effect=[httpx.ConnectTimeout("t"), openai_ok("late")])
    assert (await oai().complete(REQ)).text == "late"


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"nope": 1}),
        httpx.Response(200, json={"choices": [{"message": {"content": 42}}]}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=[1, 2, 3]),
    ],
)
async def test_openai_malformed_responses(response: httpx.Response) -> None:
    respx.post(OPENAI_URL).mock(return_value=response)
    with pytest.raises(ProviderError):
        await oai().complete(REQ)


@respx.mock
async def test_openai_null_content_is_empty_string() -> None:
    respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
    )
    assert (await oai().complete(REQ)).text == ""


@respx.mock
@pytest.mark.parametrize(("status", "hint"), [(401, "valid key"), (404, "base_url"), (400, None)])
async def test_openai_client_errors_are_not_retried(status: int, hint: str | None) -> None:
    route = respx.post(OPENAI_URL).mock(return_value=httpx.Response(status, text="bad"))
    with pytest.raises(ProviderError) as exc:
        await oai().complete(REQ)
    assert route.call_count == 1
    assert f"HTTP {status}" in exc.value.message
    if hint:
        assert hint in (exc.value.hint or "")


async def test_missing_api_key_is_friendly() -> None:
    cfg = ProviderConfig(provider="openai_compatible", model="m")
    provider = OpenAICompatibleProvider(cfg, SETTINGS, environ={})
    with pytest.raises(ProviderError) as exc:
        await provider.complete(REQ)
    assert "OPENAI_API_KEY is not set" in exc.value.message
    assert "--mode replay" in (exc.value.hint or "")


@respx.mock
async def test_no_auth_endpoint_and_custom_base_url() -> None:
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=openai_ok("local")
    )
    provider = oai(base_url="http://localhost:11434/v1/", api_key_env="none")
    assert (await provider.complete(REQ)).text == "local"
    assert "authorization" not in route.calls.last.request.headers


def test_backoff_and_retry_after() -> None:
    p = oai(Settings(backoff_base_s=0.5))
    assert [p.backoff(i, None) for i in range(3)] == [0.5, 1.0, 2.0]
    assert p.backoff(2, 7.0) == 7.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("abc") is None
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after("9999") == 60.0


@respx.mock
async def test_backoff_actually_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post(OPENAI_URL).mock(side_effect=[httpx.Response(500), httpx.Response(429), openai_ok()])
    await oai(Settings(max_retries=3, backoff_base_s=1.0)).complete(REQ)
    assert sleeps == [1.0, 2.0]


# -- anthropic -----------------------------------------------------------------------------


def anthropic(environ: dict[str, str] = ENV) -> AnthropicProvider:
    cfg = ProviderConfig(provider="anthropic", model="claude-x", params={"max_tokens": 50})
    return AnthropicProvider(cfg, SETTINGS, environ=environ)


@respx.mock
async def test_anthropic_success_payload_shape() -> None:
    route = respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}],
                "usage": {"input_tokens": 3},
            },
        )
    )
    req = ChatRequest("claude-x", REQ.messages, {"max_tokens": 50, "temperature": 0})
    resp = await anthropic().complete(req)
    assert resp.text == "Hello"
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "ak-test"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    body = __import__("json").loads(sent.content)
    assert body["system"] == "be terse"
    assert body["max_tokens"] == 50
    assert body["temperature"] == 0
    assert body["messages"] == [{"role": "user", "content": "hi"}]


@respx.mock
async def test_anthropic_default_max_tokens_and_overloaded_retry() -> None:
    route = respx.post(ANTHROPIC_URL).mock(
        side_effect=[
            httpx.Response(529, text="overloaded"),
            httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]}),
        ]
    )
    req = ChatRequest("claude-x", ({"role": "user", "content": "hi"},))
    assert (await anthropic().complete(req)).text == "ok"
    body = __import__("json").loads(route.calls.last.request.content)
    assert body["max_tokens"] == 1024
    assert "system" not in body


@respx.mock
@pytest.mark.parametrize(
    "payload", [{"content": "nope"}, {"content": [{"type": "tool_use", "id": "x"}]}]
)
async def test_anthropic_malformed(payload: dict[str, object]) -> None:
    respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ProviderError, match="malformed"):
        await anthropic().complete(REQ)


async def test_anthropic_missing_key() -> None:
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        await anthropic(environ={}).complete(REQ)


# -- mock + python + factory ---------------------------------------------------------------


async def test_mock_provider_rules() -> None:
    cfg = ProviderConfig.model_validate(
        {
            "provider": "mock",
            "model": "m",
            "mock_responses": [{"match": "(?i)refund", "respond": "R"}],
            "mock_default": "D",
        }
    )
    provider = MockProvider(cfg)
    assert provider.requires_recording is False
    msg = ({"role": "user", "content": "Refund please"},)
    assert (await provider.complete(ChatRequest("m", msg))).text == "R"
    assert (
        await provider.complete(ChatRequest("m", ({"role": "user", "content": "x"},)))
    ).text == "D"
    assert provider.calls == 2


PY_PROVIDER = """
from evalgate.providers.base import ChatResponse

class Upper:
    def __init__(self, config):
        self.model = config.model
    def complete(self, request):
        return request.user_text.upper()

class AsyncResp:
    async def complete(self, request):
        return ChatResponse(text="async:" + request.user_text)

class Bad:
    def complete(self, request):
        return 42

class Boom:
    def complete(self, request):
        raise RuntimeError("kaput")

class NoComplete:
    pass
"""


async def test_python_provider_variants(tmp_path: Path) -> None:
    (tmp_path / "my_provider_mod.py").write_text(PY_PROVIDER, "utf-8")

    def make(name: str) -> PythonProvider:
        cfg = ProviderConfig(provider="python", model="m", entrypoint=f"my_provider_mod:{name}")
        return PythonProvider(cfg, tmp_path)

    req = ChatRequest("m", ({"role": "user", "content": "hi"},))
    assert (await make("Upper").complete(req)).text == "HI"
    assert (await make("AsyncResp").complete(req)).text == "async:hi"
    with pytest.raises(ProviderError, match="returned int"):
        await make("Bad").complete(req)
    with pytest.raises(ProviderError, match="raised RuntimeError: kaput"):
        await make("Boom").complete(req)
    with pytest.raises(ProviderError, match="no complete"):
        make("NoComplete")
    with pytest.raises(ConfigError, match="has no attribute"):
        make("Missing")


def test_factory(tmp_path: Path) -> None:
    def build(**kw: object) -> object:
        cfg = ProviderConfig.model_validate({"model": "m", **kw})
        return create_provider(cfg, SETTINGS, tmp_path, environ=ENV)

    assert isinstance(build(provider="mock"), MockProvider)
    assert isinstance(build(provider="anthropic"), AnthropicProvider)
    assert isinstance(build(provider="openai_compatible"), OpenAICompatibleProvider)
    (tmp_path / "fac_mod.py").write_text(PY_PROVIDER, "utf-8")
    assert isinstance(build(provider="python", entrypoint="fac_mod:Upper"), PythonProvider)


async def test_chat_response_defaults() -> None:
    r = ChatResponse(text="x")
    assert r.cached is False and r.usage == {} and r.latency_ms == 0.0
