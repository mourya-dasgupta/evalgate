from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from evalgate.config import load_config
from evalgate.errors import UsageError
from evalgate.runner import run_sync
from evalgate.store import (
    atomic_write,
    latest_run_path,
    list_runs,
    load_baseline,
    load_run,
    save_run,
    update_baseline,
)


def test_save_list_latest_load(make_project: Callable[..., Path], tmp_path: Path) -> None:
    cfg = load_config(make_project())
    runs_dir = tmp_path / "runs"
    assert list_runs(runs_dir) == []
    with pytest.raises(UsageError, match="no runs found"):
        latest_run_path(runs_dir)
    first = run_sync(cfg, cfg.suites, "replay")
    p1 = save_run(first, runs_dir)
    second = first.model_copy(update={"run_id": first.run_id + "z"})
    p2 = save_run(second, runs_dir)
    assert list_runs(runs_dir) == [p1, p2]
    assert latest_run_path(runs_dir) == p2
    loaded = load_run(p1)
    assert loaded == first


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="not found"):
        load_run(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", "utf-8")
    with pytest.raises(UsageError) as exc:
        load_baseline(bad)
    assert "baseline" in exc.value.message and "corrupted" in exc.value.message
    assert "runbook" in (exc.value.hint or "")
    bad.write_text('{"run_id": 1}', "utf-8")
    with pytest.raises(UsageError, match="ValidationError"):
        load_run(bad)
    assert load_baseline(tmp_path / "none.json") is None


def test_update_baseline_full_and_partial(
    make_project: Callable[..., Path], tmp_path: Path
) -> None:
    cfg = load_config(make_project())
    run = run_sync(cfg, cfg.suites, "replay")
    path = tmp_path / "b" / "baseline.json"

    # partial update with no existing baseline keeps only the chosen suite
    only = update_baseline(run, path, ["echo"])
    assert [s.name for s in only.suites] == ["echo"]
    # partial update merges into the existing baseline
    merged = update_baseline(run, path, ["sentiment"])
    assert [s.name for s in merged.suites] == ["echo", "sentiment"]
    full = update_baseline(run, path)
    assert [s.name for s in full.suites] == ["sentiment", "echo"]
    assert load_baseline(path) == run
    with pytest.raises(UsageError, match="not in the selected run"):
        update_baseline(run, path, ["ghost"])


def test_atomic_write_cleans_up_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Path, target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write(tmp_path / "x.json", "data")
    assert list(tmp_path.iterdir()) == []
