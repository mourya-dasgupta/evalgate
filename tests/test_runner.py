from __future__ import annotations

import json
import textwrap
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evalgate.config import load_config
from evalgate.errors import ConfigError, TemplateError
from evalgate.results import ConfusionMatrix, ScorerOutcome
from evalgate.runner import make_run_id, run_all, run_sync, weighted_score
from tests.conftest import MOCK_CONFIG, SENTIMENT_CASES, write_jsonl


def test_run_id_is_sortable() -> None:
    a = make_run_id(datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=UTC))
    assert a == "2026-01-02T03-04-05-000006Z"
    assert make_run_id(datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)) > a


def test_weighted_score() -> None:
    def o(score: float, weight: float) -> ScorerOutcome:
        return ScorerOutcome(name="x", type="t", score=score, passed=True, weight=weight)

    assert weighted_score([]) == 0.0
    assert weighted_score([o(1, 1), o(0, 3)]) == 0.25
    assert weighted_score([o(1, 0), o(0, 0)]) == 0.5


def test_mock_run_metrics_tags_and_confusion(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    run = run_sync(cfg, cfg.suites, "replay")
    assert run.mode == "replay"
    assert run.config_path == "evalgate.yaml"
    sentiment = run.suite("sentiment")
    assert sentiment is not None
    m = sentiment.metrics
    # s5 "Not great, honestly awful" matches the positive rule first -> wrong
    assert (m.total, m.passed, m.failed, m.errored) == (5, 4, 1, 0)
    assert m.pass_rate == 0.8
    s5 = sentiment.case("s5")
    assert s5 is not None and not s5.passed
    assert s5.score == pytest.approx(1 / 3)
    assert s5.failure_reasons == ["label_match:label: expected 'negative', predicted 'positive'"]
    assert sentiment.tags["tricky"].pass_rate == 0.0
    assert sentiment.tags["critical"].pass_rate == 1.0
    [cm] = sentiment.confusion
    assert cm.scorer == "label_match:label"
    assert cm.counts["negative"]["positive"] == 1
    assert cm.accuracy() == 0.8
    assert sentiment.target.model == "mock-1"
    assert len(sentiment.target.prompt_sha256) == 64
    assert sentiment.cache_hits == 0
    echo = run.suite("echo")
    assert echo is not None and echo.metrics.pass_rate == 1.0
    assert run.suite("nope") is None
    assert run.errored_cases == []


def test_confusion_matrix_empty() -> None:
    assert ConfusionMatrix.from_pairs("x", []).accuracy() == 0.0


def test_template_errors_fail_fast(make_project: Callable[..., Path]) -> None:
    cfg_path = make_project()
    write_jsonl(
        cfg_path.parent / "golden" / "sentiment.jsonl",
        [{"id": "bad", "input": {"wrong": "x"}, "expected": {"label": "neutral"}}],
    )
    cfg = load_config(cfg_path)
    with pytest.raises(TemplateError, match="1 case\\(s\\) could not be rendered"):
        run_sync(cfg, cfg.select_suites(["sentiment"]), "replay")


def test_bad_scorer_config_raises(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project(config=MOCK_CONFIG.replace("json_valid", "nope_scorer")))
    with pytest.raises(ConfigError, match="unknown scorer type"):
        run_sync(cfg, cfg.select_suites(["sentiment"]), "replay")


SIM = """
import json

class Model:
    calls = 0
    def complete(self, request):
        Model.calls += 1
        text = request.user_text
        if "explode" in text:
            raise RuntimeError("model crashed")
        label = "positive" if "love" in text else "negative"
        return json.dumps({"label": label})

class Judge:
    calls = 0
    def complete(self, request):
        Judge.calls += 1
        return '{"score": 4, "reason": "fine"}'

def crashy(output, case):
    raise ValueError("bug in scorer")
"""

RECORDED = """\
version: 1
settings: {max_retries: 0, backoff_base_s: 0}
suites:
  - name: sim
    target:
      provider: python
      entrypoint: sim_mod_rt:Model
      model: sim-1
      prompt: p.txt
      system_prompt: sys.txt
      params: {temperature: 0}
    golden: g.jsonl
    concurrency: 2
    scorers:
      - type: label_match
        field: label
      - type: llm_judge
        required: false
        threshold: 0.5
        rubric: Is the label sensible?
        judge: {provider: python, entrypoint: "sim_mod_rt:Judge", model: judge-1}
      - type: custom
        path: sim_mod_rt:crashy
        required: false
"""


def _recorded_project(tmp_path: Path, cases: list[dict[str, object]]) -> Path:
    (tmp_path / "sim_mod_rt.py").write_text(SIM, "utf-8")
    (tmp_path / "p.txt").write_text("{{ text }}", "utf-8")
    (tmp_path / "sys.txt").write_text("Classify. Reply JSON.", "utf-8")
    write_jsonl(tmp_path / "g.jsonl", cases)
    cfg = tmp_path / "evalgate.yaml"
    cfg.write_text(textwrap.dedent(RECORDED), "utf-8")
    return cfg


CASES = [
    {"id": "a", "input": {"text": "I love it"}, "expected": {"label": "positive"}},
    {"id": "b", "input": {"text": "meh"}, "expected": {"label": "negative"}},
]


async def test_record_then_replay_includes_judge(tmp_path: Path) -> None:
    cfg = load_config(_recorded_project(tmp_path, CASES))
    recorded = await run_all(cfg, cfg.suites, "record")
    import sim_mod_rt  # type: ignore[import-not-found]

    assert sim_mod_rt.Model.calls == 2
    assert sim_mod_rt.Judge.calls == 2
    lines = (tmp_path / "cassettes" / "sim.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 4  # 2 target + 2 judge entries
    suite = recorded.suites[0]
    assert suite.metrics.pass_rate == 1.0
    case_a = suite.case("a")
    assert case_a is not None
    judge = next(s for s in case_a.scores if s.type == "llm_judge")
    assert judge.score == 0.75 and judge.passed
    crash = next(s for s in case_a.scores if s.type == "custom")
    assert crash.score == 0 and "scorer raised ValueError: bug in scorer" in crash.reason

    replayed = await run_all(cfg, cfg.suites, "replay")
    assert sim_mod_rt.Model.calls == 2 and sim_mod_rt.Judge.calls == 2  # nothing called
    rs = replayed.suites[0]
    assert rs.cache_hits == 4
    assert all(c.cached for c in rs.cases)
    assert [c.output for c in rs.cases] == [c.output for c in suite.cases]
    first = json.loads(lines[0])
    assert first["request"]["messages"][0]["role"] == "system"


async def test_replay_miss_and_provider_errors_mark_cases(tmp_path: Path) -> None:
    cases = [*CASES, {"id": "x", "input": {"text": "explode"}, "expected": {"label": "x"}}]
    cfg = load_config(_recorded_project(tmp_path, cases))
    run = await run_all(cfg, cfg.suites, "replay")
    suite = run.suites[0]
    assert suite.metrics.errored == 3
    assert all("no recording" in (c.error or "") for c in suite.cases)
    assert len(run.errored_cases) == 3
    assert suite.cases[0].failure_reasons[0].startswith("error: no recording")

    live = await run_all(cfg, cfg.suites, "live")
    crashed = live.suites[0].case("x")
    assert crashed is not None and "model crashed" in (crashed.error or "")
    assert not (tmp_path / "cassettes" / "sim.jsonl").exists()


def test_progress_callback(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    seen: list[tuple[str, int, int]] = []
    run_sync(cfg, cfg.select_suites(["sentiment"]), "replay", progress=lambda *a: seen.append(a))
    assert seen[-1] == ("sentiment", 5, 5)
    assert len(seen) == len(SENTIMENT_CASES)
