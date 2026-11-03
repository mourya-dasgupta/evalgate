from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from evalgate.config import EvalGateConfig, ProviderConfig, ScorerConfig, load_config, parse_config
from evalgate.errors import ConfigError
from evalgate.golden import GoldenCase
from evalgate.providers.base import ChatRequest, ChatResponse, Provider
from evalgate.scorers import SCORERS, ScorerDeps, ScoreResult, build_scorers
from evalgate.scorers.base import extract_output, get_path, parse_json, strip_code_fences
from evalgate.scorers.builtin import to_number
from evalgate.scorers.custom import coerce_result
from evalgate.scorers.llm_judge import parse_judge_reply


def case(expected: Any = None, **input_: Any) -> GoldenCase:
    return GoldenCase(id="c", input=input_ or {"m": "x"}, expected=expected)


def make(type_: str, root: Path | None = None, deps: ScorerDeps | None = None, **opts: Any) -> Any:
    data = {
        "suites": [
            {
                "name": "s",
                "target": {"provider": "mock", "model": "m", "prompt": "p"},
                "golden": "g",
                "scorers": [{"type": type_, **opts}],
            }
        ]
    }
    cfg = parse_config(data, (root or Path.cwd()) / "evalgate.yaml")
    return build_scorers(cfg.suites[0], cfg, deps)[0].impl


async def run(scorer: Any, output: str, c: GoldenCase) -> ScoreResult:
    result: ScoreResult = await scorer.score(output, c)
    return result


def test_registry_has_all_builtins() -> None:
    assert {
        "exact_match",
        "contains",
        "not_contains",
        "regex",
        "json_valid",
        "json_schema",
        "numeric_tolerance",
        "label_match",
        "llm_judge",
        "custom",
    } <= set(SCORERS)


def test_score_result_is_clamped() -> None:
    assert ScoreResult(1.7).score == 1.0
    assert ScoreResult(-2).score == 0.0


# -- helpers ------------------------------------------------------------------------------


def test_parse_json_and_fences() -> None:
    assert parse_json('```json\n{"a": 1}\n```') == (True, {"a": 1}, "")
    assert parse_json("```\n[1]\n```")[1] == [1]
    assert parse_json("")[2] == "output is empty"
    ok, _, err = parse_json("{oops}")
    assert not ok and err.startswith("invalid JSON")
    assert parse_json('```json\n{"a": 1}\n```', allow_fences=False)[0] is False
    assert strip_code_fences("plain") == "plain"


def test_get_path() -> None:
    data = {"a": {"b": [10, {"c": "x"}]}}
    assert get_path(data, "a.b.0") == 10
    assert get_path(data, "a.b.1.c") == "x"
    assert get_path(data, "a.b.-1.c") == "x"
    assert extract_output(json.dumps(data), "a.b.5")[0] is False
    assert extract_output(json.dumps(data), "a.zz")[2] == "field 'a.zz' is missing from the output"
    assert extract_output("nope", "a")[2].startswith("cannot read field 'a'")


# -- exact_match --------------------------------------------------------------------------


async def test_exact_match_normalisation() -> None:
    s = make("exact_match")
    assert (await run(s, "  Hello   world \n", case("Hello world"))).score == 1.0
    assert (await run(s, "hello world", case("Hello world"))).score == 0.0
    ci = make("exact_match", case_sensitive=False)
    assert (await run(ci, "HELLO WORLD", case("hello world"))).score == 1.0
    strict = make("exact_match", normalize_whitespace=False, strip=False)
    assert (await run(strict, "a  b", case("a b"))).score == 0.0
    r = await run(s, "", case("x"))
    assert r.score == 0.0 and "expected 'x', got ''" in r.reason


async def test_exact_match_on_field_and_unicode() -> None:
    s = make("exact_match", field="language")
    c = case({"language": "hinglish"})
    assert (await run(s, '{"language": "hinglish"}', c)).score == 1.0
    assert (await run(s, "not json", c)).score == 0.0
    nested = make("exact_match", field="a", expected_field="deep.value")
    assert (await run(nested, '{"a": "पैसा"}', case({"deep": {"value": "पैसा"}}))).score == 1.0
    r = await run(nested, '{"a": 1}', case({"deep": {}}))
    assert "golden case has no expected 'deep.value'" in r.reason


# -- contains / not_contains --------------------------------------------------------------


async def test_contains_modes() -> None:
    s = make("contains", values=["refund", "order"])
    assert (await run(s, "Your REFUND for order 12", case())).score == 1.0
    half = await run(s, "refund only", case())
    assert half.score == 0.5 and "missing ['order']" in half.reason
    anyof = make("contains", values=["x", "refund"], mode="any")
    assert (await run(anyof, "refund", case())).score == 1.0
    assert (await run(anyof, "nothing", case())).score == 0.0
    cs = make("contains", values="Refund", case_sensitive=True)
    assert (await run(cs, "refund", case())).score == 0.0
    empty = make("contains", values=[])
    assert (await run(empty, "x", case())).score == 1.0


async def test_contains_uses_expected_when_no_values() -> None:
    s = make("contains")
    assert (await run(s, "Paisa wapas karo", case("paisa"))).score == 1.0
    assert (await run(s, "a b", case(["a", "b"]))).score == 1.0
    bad = await run(s, "a", case({"k": 1}))
    assert bad.score == 0.0 and "not a string or list" in bad.reason
    field = make("contains", field="summary", expected_field="must")
    out = '{"summary": "double charge on UPI"}'
    assert (await run(field, out, case({"must": "UPI"}))).score == 1.0
    assert (await run(field, out, case({"other": 1}))).score == 0.0
    assert (await run(field, "{bad", case({"must": "x"}))).score == 0.0


async def test_not_contains() -> None:
    s = make("not_contains", values=["ignore previous", "URGENT"])
    assert (await run(s, "all good", case())).score == 1.0
    r = await run(s, "Marked urgent as asked", case())
    assert r.score == 0.0 and "URGENT" in r.reason
    assert (await run(make("not_contains", field="x", values=["a"]), "nope", case())).score == 0
    assert (await run(make("not_contains"), "x", case({"k": 1}))).score == 0.0


# -- regex --------------------------------------------------------------------------------


async def test_regex() -> None:
    s = make("regex", pattern=r"ORD-\d{5}")
    assert (await run(s, "your order ORD-12345 ships", case())).score == 1.0
    assert (await run(s, "", case())).score == 0.0
    full = make("regex", pattern=r"(low|high)", full_match=True, ignore_case=True)
    assert (await run(full, "HIGH", case())).score == 1.0
    assert (await run(full, "very high", case())).score == 0.0
    f = make("regex", pattern="^h", field="p")
    assert (await run(f, '{"p": "high"}', case())).score == 1.0
    assert (await run(f, "{}", case())).score == 0.0
    with pytest.raises(ConfigError, match="invalid regular expression"):
        make("regex", pattern="(")


# -- json_valid / json_schema -------------------------------------------------------------


async def test_json_valid() -> None:
    s = make("json_valid")
    assert (await run(s, '{"a": 1}', case())).score == 1.0
    assert (await run(s, '```json\n{"a": 1}\n```', case())).score == 1.0
    assert (await run(s, "", case())).score == 0.0
    assert (await run(s, '{"a": 1,}', case())).score == 0.0
    strict = make("json_valid", allow_code_fences=False, require_object=True)
    assert (await run(strict, '```json\n{"a": 1}\n```', case())).score == 0.0
    r = await run(strict, "[1]", case())
    assert r.score == 0.0 and "expected a JSON object" in r.reason


SCHEMA = {
    "type": "object",
    "required": ["category", "priority"],
    "properties": {
        "category": {"enum": ["billing", "refund"]},
        "priority": {"enum": ["low", "high"]},
    },
}


async def test_json_schema_inline_and_file(tmp_path: Path) -> None:
    s = make("json_schema", schema=SCHEMA)
    assert (await run(s, '{"category": "refund", "priority": "low"}', case())).score == 1.0
    r = await run(s, '{"category": "spam"}', case())
    assert r.score == 0.0
    assert "schema violation" in r.reason and "(+1 more)" in r.reason
    assert (await run(s, "not json", case())).score == 0.0
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA), "utf-8")
    f = make("json_schema", root=tmp_path, schema_path="schema.json")
    assert (await run(f, '{"category": "billing", "priority": "high"}', case())).score == 1.0
    sub = make("json_schema", schema={"type": "string"}, field="category")
    assert (await run(sub, '{"category": "x"}', case())).score == 1.0
    assert (await run(sub, '{"category": 3}', case())).score == 0.0


def test_json_schema_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="exactly one"):
        make("json_schema")
    with pytest.raises(ConfigError, match="schema file not found"):
        make("json_schema", root=tmp_path, schema_path="missing.json")
    (tmp_path / "bad.json").write_text("{nope", "utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        make("json_schema", root=tmp_path, schema_path="bad.json")
    with pytest.raises(ConfigError, match="invalid JSON Schema"):
        make("json_schema", schema={"type": 12})
    (tmp_path / "list.json").write_text("[1]", "utf-8")
    with pytest.raises(ConfigError, match="must be an object"):
        make("json_schema", root=tmp_path, schema_path="list.json")


# -- numeric_tolerance --------------------------------------------------------------------


def test_to_number() -> None:
    assert to_number(3) == 3.0
    assert to_number("Total: ₹1,299.50 only") == 1299.5
    assert to_number("-4e2") == -400.0
    assert to_number(True) is None
    assert to_number(float("nan")) is None
    assert to_number("no digits") is None
    assert to_number(None) is None


async def test_numeric_tolerance() -> None:
    s = make("numeric_tolerance", tolerance=0.5)
    assert (await run(s, "about 10.4", case(10))).score == 1.0
    r = await run(s, "11", case(10))
    assert r.score == 0.0 and "allowed 0.5" in r.reason
    rel = make("numeric_tolerance", relative=0.1, field="amount")
    assert (await run(rel, '{"amount": 1080}', case({"amount": 1000}))).score == 1.0
    assert (await run(rel, '{"amount": "n/a"}', case({"amount": 1000}))).score == 0.0
    assert (await run(rel, '{"amount": 5}', case({"amount": "x"}))).score == 0.0
    exact = make("numeric_tolerance")
    assert (await run(exact, "42", case(42))).score == 1.0
    assert (await run(make("numeric_tolerance", field="z"), "{}", case({"z": 1}))).score == 0


# -- label_match --------------------------------------------------------------------------


async def test_label_match() -> None:
    s = make("label_match", field="category")
    c = case({"category": "Refund"})
    r = await run(s, '{"category": "refund"}', c)
    assert r.score == 1.0 and r.details == {"expected": "refund", "predicted": "refund"}
    r = await run(s, '{"category": "billing"}', c)
    assert r.score == 0.0 and r.details["predicted"] == "billing"
    r = await run(s, "garbage", c)
    assert r.score == 0.0 and r.details["predicted"] == "<missing>"
    restricted = make("label_match", field="category", labels=["billing", "refund"])
    r = await run(restricted, '{"category": "spam"}', case({"category": "spam"}))
    assert r.score == 0.0 and "not an allowed label" in r.reason
    cs = make("label_match", case_sensitive=True)
    assert (await run(cs, "Refund", case("refund"))).score == 0.0
    missing = await run(s, '{"category": "x"}', case({"priority": "low"}))
    assert "no expected 'category'" in missing.reason


# -- llm_judge ----------------------------------------------------------------------------


class FakeJudge(Provider):
    name = "fake-judge"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(text=self.reply)

    async def aclose(self) -> None:
        self.closed = True


JUDGE_CFG = {"provider": "openai_compatible", "model": "judge-1", "params": {"max_tokens": 50}}


def judge_with(reply: str, **opts: Any) -> tuple[Any, FakeJudge]:
    fake = FakeJudge(reply)
    created: list[ProviderConfig] = []

    def factory(cfg: ProviderConfig) -> Provider:
        created.append(cfg)
        return fake

    scorer = make(
        "llm_judge",
        deps=ScorerDeps(provider_factory=factory),
        rubric="Summary must mention the order issue.",
        judge=JUDGE_CFG,
        **opts,
    )
    return scorer, fake


@pytest.mark.parametrize(
    ("reply", "score"),
    [
        ('{"score": 5, "reason": "great"}', 1.0),
        ('Sure! {"score": 3, "reason": "ok"}', 0.5),
        ("score: 1", 0.0),
        ('{"score": 9}', 1.0),
    ],
)
async def test_llm_judge_scores(reply: str, score: float) -> None:
    scorer, fake = judge_with(reply)
    c = GoldenCase(id="c", input={"message": "order late"}, expected={"category": "delivery"})
    result = await run(scorer, '{"summary": "late order"}', c)
    assert result.score == score
    req = fake.requests[0]
    assert req.model == "judge-1"
    assert req.params == {"temperature": 0, "max_tokens": 50}
    assert "Reference answer" in req.messages[1]["content"]
    assert '"message": "order late"' in req.messages[1]["content"]
    await scorer.aclose()
    assert fake.closed


async def test_llm_judge_unparseable_and_field() -> None:
    scorer, _ = judge_with("I refuse to grade")
    r = await run(scorer, "x", case())
    assert r.score == 0.0 and "could not parse judge reply" in r.reason
    fscorer, fake = judge_with('{"score": 4}', field="summary", include_expected=False)
    r = await run(fscorer, '{"summary": "hello"}', case({"a": 1}))
    assert r.score == 0.75 and r.reason == "judge gave no reason"
    content = fake.requests[0].messages[1]["content"]
    assert "Reference answer" not in content and "hello" in content
    assert (await run(fscorer, "nope", case())).score == 0.0


def test_parse_judge_reply_edge_cases() -> None:
    assert parse_judge_reply('{"score": "x"}', 1, 5) == (None, "")
    assert parse_judge_reply('{"score": true}', 1, 5)[0] is None
    assert parse_judge_reply("{not json} score=2", 1, 5)[0] == 0.25
    assert parse_judge_reply("nothing", 0, 10) == (None, "")


async def test_llm_judge_without_factory_errors() -> None:
    scorer = make("llm_judge", rubric="r", judge=JUDGE_CFG)
    with pytest.raises(ConfigError, match="no provider factory"):
        await run(scorer, "x", case())
    await scorer.aclose()


def test_llm_judge_option_errors() -> None:
    with pytest.raises(ConfigError, match="max_score must be greater"):
        make("llm_judge", rubric="r", judge=JUDGE_CFG, min_score=5, max_score=1)
    with pytest.raises(ConfigError, match="judge"):
        make("llm_judge", rubric="r")


# -- custom -------------------------------------------------------------------------------

CUSTOM = """
from evalgate.scorers import Scorer, ScoreResult, ScorerOptions

def two_args(output, case):
    return len(output) < 10

def three_args(output, case, options):
    return (1.0 if options["word"] in output else 0.0, "checked word")

async def async_fn(output, case):
    return ScoreResult(0.25, "async")

def as_float(output, case):
    return 0.6

def bad_type(output, case):
    return "nope"

class WordOptions(ScorerOptions):
    word: str

class WordScorer(Scorer):
    Options = WordOptions
    def score_sync(self, output, case):
        return ScoreResult(float(self.options.word in output), "class")

NOT_CALLABLE = 3
"""


async def test_custom_scorers(tmp_path: Path) -> None:
    (tmp_path / "my_custom_scorers.py").write_text(CUSTOM, "utf-8")

    def custom(name: str, **options: Any) -> Any:
        return make("custom", root=tmp_path, path=f"my_custom_scorers:{name}", options=options)

    assert (await run(custom("two_args"), "short", case())).score == 1.0
    r = await run(custom("three_args", word="UPI"), "paid by UPI", case())
    assert r.score == 1.0 and r.reason == "checked word"
    assert (await run(custom("async_fn"), "x", case())).score == 0.25
    assert (await run(custom("as_float"), "x", case())).score == 0.6
    assert (await run(custom("WordScorer", word="hi"), "hi there", case())).reason == "class"
    with pytest.raises(ConfigError, match="returned str"):
        await run(custom("bad_type"), "x", case())
    with pytest.raises(ConfigError, match="not callable"):
        custom("NOT_CALLABLE")
    with pytest.raises(ConfigError, match="could not import"):
        make("custom", root=tmp_path, path="nope_module_q:f")


def test_coerce_result() -> None:
    assert coerce_result(False, "x").score == 0.0
    assert coerce_result((0.5, "half"), "x").reason == "half"


# -- build_scorers ------------------------------------------------------------------------


def test_build_scorers_errors() -> None:
    with pytest.raises(ConfigError) as exc:
        make("does_not_exist")
    assert "unknown scorer type 'does_not_exist'" in exc.value.message
    assert "exact_match" in (exc.value.hint or "")
    with pytest.raises(ConfigError, match="unknown option"):
        make("exact_match", bogus=1)
    with pytest.raises(ConfigError, match="pattern"):
        make("regex")


def test_build_scorers_from_project(make_project: Callable[..., Path]) -> None:
    cfg: EvalGateConfig = load_config(make_project())
    bound = build_scorers(cfg.suites[0], cfg)
    assert [b.name for b in bound] == ["json_valid", "label_match:label"]
    assert bound[1].config.weight == 2
    assert isinstance(cfg.suites[0].scorers[0], ScorerConfig)
