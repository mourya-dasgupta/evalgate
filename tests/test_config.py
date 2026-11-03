from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from evalgate.config import (
    EvalGateConfig,
    format_location,
    interpolate_env,
    load_config,
    parse_config,
)
from evalgate.errors import ConfigError, ExitCode

MINIMAL = {
    "suites": [
        {
            "name": "s",
            "target": {"provider": "mock", "model": "m", "prompt": "p.txt"},
            "golden": "g.jsonl",
            "scorers": [{"type": "exact_match"}],
        }
    ]
}


def _with(**changes: object) -> dict[str, object]:
    import copy

    data = copy.deepcopy(MINIMAL)
    suite = data["suites"][0]  # type: ignore[index]
    for key, value in changes.items():
        suite[key] = value
    return data


def test_load_valid_config(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    assert [s.name for s in cfg.suites] == ["sentiment", "echo"]
    assert cfg.settings.concurrency == 4
    assert cfg.suites[0].gate.critical_tags == ["critical"]
    assert cfg.resolve("golden/x.jsonl") == cfg.root / "golden/x.jsonl"
    assert cfg.runs_dir == cfg.root / ".evalgate/runs"
    assert cfg.baseline_path.name == "baseline.json"
    assert cfg.cassette_dir.name == "cassettes"
    scorer = cfg.suites[0].scorers[1]
    assert scorer.options == {"field": "label"}
    assert scorer.display_name == "label_match:label"


def test_resolve_absolute_path_is_kept(tmp_path: Path) -> None:
    cfg = parse_config(MINIMAL, tmp_path / "evalgate.yaml")
    assert cfg.resolve(tmp_path / "abs") == tmp_path / "abs"


def test_missing_file_has_hint(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "nope.yaml")
    assert "not found" in exc.value.message
    assert "evalgate init" in (exc.value.hint or "")
    assert exc.value.exit_code == ExitCode.USAGE_ERROR


def test_directory_instead_of_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="is a directory"):
        load_config(tmp_path)


def test_invalid_yaml_reports_line(tmp_path: Path) -> None:
    path = tmp_path / "evalgate.yaml"
    path.write_text("suites:\n  - name: x\n   bad: [\n", "utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "not valid YAML at line" in exc.value.message


def test_empty_and_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "evalgate.yaml"
    path.write_text("", "utf-8")
    with pytest.raises(ConfigError, match="is empty"):
        load_config(path)
    path.write_text("- a\n- b\n", "utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)


def test_validation_errors_are_located_and_friendly(tmp_path: Path) -> None:
    data = _with(gate={"min_pass_rate": 1.5, "typo_rule": 1})
    with pytest.raises(ConfigError) as exc:
        parse_config(data, tmp_path / "evalgate.yaml")
    msg = exc.value.message
    assert "suites[0](s).gate.min_pass_rate" in msg
    assert "less than or equal to 1" in msg
    assert "suites[0](s).gate.typo_rule: unknown field" in msg


def test_missing_required_fields(tmp_path: Path) -> None:
    data = _with()
    del data["suites"][0]["golden"]  # type: ignore[index]
    with pytest.raises(ConfigError, match=r"golden: required field is missing"):
        parse_config(data, tmp_path / "c.yaml")


def test_no_suites(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="suites"):
        parse_config({"suites": []}, tmp_path / "c.yaml")


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"name": "bad name!"}, "suite names may only contain"),
        (
            {"target": {"provider": "python", "model": "m", "prompt": "p"}},
            "needs 'entrypoint",
        ),
        (
            {"target": {"provider": "mock", "model": "m", "prompt": "p", "entrypoint": "a:b"}},
            "only used with provider 'python'",
        ),
        (
            {
                "target": {
                    "provider": "anthropic",
                    "model": "m",
                    "prompt": "p",
                    "mock_responses": [{"match": "a", "respond": "b"}],
                }
            },
            "only used with provider 'mock'",
        ),
        (
            {
                "target": {
                    "provider": "mock",
                    "model": "m",
                    "prompt": "p",
                    "mock_responses": [{"match": "(", "respond": "b"}],
                }
            },
            "invalid regular expression",
        ),
        ({"target": {"provider": "gpt", "model": "m", "prompt": "p"}}, "provider"),
        ({"scorers": [{"type": "regex"}, {"type": "regex"}]}, "both named 'regex'"),
        ({"scorers": []}, "scorers"),
        ({"gate": {"max_regression": -1}}, "max_regression"),
    ],
)
def test_invalid_suite_fields(changes: dict[str, object], fragment: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        parse_config(_with(**changes), tmp_path / "c.yaml")
    assert fragment in exc.value.message


def test_duplicate_suite_names(tmp_path: Path) -> None:
    data = {"suites": MINIMAL["suites"] * 2}
    with pytest.raises(ConfigError, match="duplicate suite name"):
        parse_config(data, tmp_path / "c.yaml")


def test_provider_defaults() -> None:
    cfg = EvalGateConfig.model_validate(
        _with(target={"provider": "anthropic", "model": "claude", "prompt": "p"})
    )
    target = cfg.suites[0].target
    assert target.resolved_base_url == "https://api.anthropic.com"
    assert target.resolved_api_key_env == "ANTHROPIC_API_KEY"
    custom = target.model_copy(update={"base_url": "http://x", "api_key_env": "K"})
    assert custom.resolved_base_url == "http://x"
    assert custom.resolved_api_key_env == "K"


def test_select_suites(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    assert [s.name for s in cfg.select_suites(None)] == ["sentiment", "echo"]
    assert [s.name for s in cfg.select_suites(["echo"])] == ["echo"]
    with pytest.raises(ConfigError) as exc:
        cfg.select_suites(["nope"])
    assert "available suites: sentiment, echo" in (exc.value.hint or "")


def test_env_interpolation() -> None:
    env = {"MODEL": "gpt-x"}
    data = {"a": "${MODEL}", "b": ["prompts/${V:-v1}.txt", 3], "c": {"d": "x-${MODEL}-y"}}
    assert interpolate_env(data, env) == {
        "a": "gpt-x",
        "b": ["prompts/v1.txt", 3],
        "c": {"d": "x-gpt-x-y"},
    }
    with pytest.raises(ConfigError, match="'MISSING'"):
        interpolate_env("${MISSING}", env)


def test_env_interpolation_in_config(tmp_path: Path) -> None:
    data = _with(target={"provider": "mock", "model": "m", "prompt": "prompts/${PV:-v1}.txt"})
    cfg = parse_config(data, tmp_path / "c.yaml", environ={"PV": "v2"})
    assert cfg.suites[0].target.prompt == "prompts/v2.txt"


def test_format_location_handles_odd_shapes() -> None:
    assert format_location((), {}) == "(top level)"
    assert format_location(("suites", 5, "x"), {"suites": []}) == "suites[5].x"
