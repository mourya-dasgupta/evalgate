from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from evalgate.config import load_config
from evalgate.errors import ConfigError
from evalgate.validate import ensure_valid, validate_project
from tests.conftest import MOCK_CONFIG, SENTIMENT_CASES, write_jsonl


def test_valid_project(make_project: Callable[..., Path]) -> None:
    report = validate_project(load_config(make_project()))
    assert report.ok
    sentiment = report.suites[0]
    assert sentiment.cases == 5
    assert sentiment.tags == {"critical": 1, "tricky": 1}
    assert any("only 5 case(s)" in w for w in sentiment.warnings)
    ensure_valid(load_config(make_project()))


def test_collects_all_problems(make_project: Callable[..., Path]) -> None:
    cfg_path = make_project(
        config=MOCK_CONFIG.replace("type: json_valid", "type: jsn_valid").replace(
            "critical_tags: [critical]", "critical_tags: [critical, vip]"
        )
    )
    write_jsonl(
        cfg_path.parent / "golden" / "sentiment.jsonl",
        [*SENTIMENT_CASES, {"id": "x", "input": {"txt": "typo key"}, "expected": "neutral"}],
    )
    report = validate_project(load_config(cfg_path), ["sentiment"])
    assert not report.ok
    [check] = report.suites
    joined = "\n".join(check.errors)
    assert "line 6:" in joined and "'text' is undefined" in joined
    assert "unknown scorer type 'jsn_valid'" in joined
    assert any("not used by the prompt template: txt" in w for w in check.warnings)
    assert any("critical tag 'vip'" in w for w in check.warnings)
    with pytest.raises(ConfigError, match="validation failed"):
        ensure_valid(load_config(cfg_path))


def test_missing_files(make_project: Callable[..., Path]) -> None:
    cfg_path = make_project()
    (cfg_path.parent / "golden" / "echo.jsonl").unlink()
    (cfg_path.parent / "prompts" / "echo.txt").unlink()
    report = validate_project(load_config(cfg_path), ["echo"])
    errors = report.suites[0].errors
    assert any("golden set not found" in e for e in errors)
    assert any("prompt template not found" in e for e in errors)


def test_system_prompt_is_checked(make_project: Callable[..., Path]) -> None:
    cfg_path = make_project(
        config=MOCK_CONFIG.replace(
            "prompt: prompts/echo.txt", "prompt: prompts/echo.txt\n      system_prompt: sys.txt"
        )
    )
    (cfg_path.parent / "sys.txt").write_text("You greet {{ who }}", "utf-8")
    report = validate_project(load_config(cfg_path), ["echo"])
    assert any("'who' is undefined" in e for e in report.suites[0].errors)
