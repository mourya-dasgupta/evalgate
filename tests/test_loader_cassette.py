from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalgate.cassette import Cassette, CassetteProvider
from evalgate.errors import CassetteMissError, ConfigError, ProviderError
from evalgate.loader import load_object
from evalgate.providers.base import ChatRequest, ChatResponse, Provider


class CountingProvider(Provider):
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        return ChatResponse(text=f"answer-{self.calls}", latency_ms=12.34, usage={"t": 1})


def req(text: str = "hello") -> ChatRequest:
    return ChatRequest("m", ({"role": "user", "content": text},), {"temperature": 0})


async def test_record_then_replay_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cassettes" / "suite.jsonl"
    inner = CountingProvider()
    recorder = CassetteProvider(inner, Cassette.load(path), "record", "suite")
    first = await recorder.complete(req("a"))
    await recorder.complete(req("b"))
    recorder.cassette.save()
    assert inner.calls == 2
    assert first.cached is False
    lines = path.read_text("utf-8").splitlines()
    assert len(lines) == 2
    keys = [json.loads(line)["key"] for line in lines]
    assert keys == sorted(keys)
    entry = json.loads(lines[0])
    assert entry["provider"] == "counting"
    assert entry["request"]["model"] == "m"

    replay_inner = CountingProvider()
    replayer = CassetteProvider(replay_inner, Cassette.load(path), "replay", "suite")
    hit = await replayer.complete(req("a"))
    assert hit.text == "answer-1"
    assert hit.cached is True
    assert hit.latency_ms == 12.3
    assert hit.usage == {"t": 1}
    assert replay_inner.calls == 0
    assert replayer.hits == 1


async def test_replay_miss_is_clear(tmp_path: Path) -> None:
    replayer = CassetteProvider(
        CountingProvider(), Cassette.load(tmp_path / "x.jsonl"), "replay", "triage"
    )
    with pytest.raises(CassetteMissError) as exc:
        await replayer.complete(req("changed prompt"))
    assert "no recording for this request" in exc.value.message
    assert "--mode record run --suite triage" in (exc.value.hint or "")
    assert exc.value.exit_code == 3
    assert replayer.misses == 1


async def test_record_upserts_existing_entries(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    rec = CassetteProvider(CountingProvider(), Cassette.load(path), "record", "s")
    await rec.complete(req("a"))
    rec.cassette.save()
    rec2 = CassetteProvider(CountingProvider(), Cassette.load(path), "record", "s")
    await rec2.complete(req("a"))  # re-record same key
    await rec2.complete(req("b"))
    rec2.cassette.save()
    cas = Cassette.load(path)
    assert len(cas.entries) == 2
    assert cas.get(req("a").cache_key())["response"]["text"] == "answer-1"  # type: ignore[index]


async def test_live_mode_bypasses_cassette(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    inner = CountingProvider()
    live = CassetteProvider(inner, Cassette.load(path), "live", "s")
    await live.complete(req())
    await live.complete(req())
    live.cassette.save()
    assert inner.calls == 2
    assert not path.exists()
    await live.aclose()


def test_corrupted_cassette_reports_line(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text('\n{"key": "a", "response": {"text": "x"}}\n{"key": "b"}\n', "utf-8")
    with pytest.raises(ProviderError, match="corrupted at line 3"):
        Cassette.load(path)


def test_save_is_noop_when_clean(tmp_path: Path) -> None:
    cas = Cassette(tmp_path / "c.jsonl")
    cas.save()
    assert not cas.path.exists()


def test_load_object_variants(tmp_path: Path) -> None:
    (tmp_path / "plugin_mod_x.py").write_text("VALUE = 7\n", "utf-8")
    assert load_object("plugin_mod_x:VALUE", tmp_path) == 7
    assert load_object("plugin_mod_x.VALUE", tmp_path) == 7
    assert load_object("json:dumps") is json.dumps
    with pytest.raises(ConfigError, match="invalid"):
        load_object("nodots")
    with pytest.raises(ConfigError, match="could not import"):
        load_object("no_such_module_zz:x")
    with pytest.raises(ConfigError, match="has no attribute"):
        load_object("json:nope")
