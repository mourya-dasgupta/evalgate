"""Run storage and the baseline file."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from evalgate.errors import UsageError
from evalgate.results import RunResult


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def dump_run(run: RunResult) -> str:
    return json.dumps(run.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def save_run(run: RunResult, runs_dir: Path) -> Path:
    path = runs_dir / f"{run.run_id}.json"
    atomic_write(path, dump_run(run))
    return path


def list_runs(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    return sorted(runs_dir.glob("*.json"))


def latest_run_path(runs_dir: Path) -> Path:
    runs = list_runs(runs_dir)
    if not runs:
        raise UsageError(
            f"no runs found in {runs_dir}",
            hint="run 'evalgate run' (or 'evalgate gate') first",
        )
    return runs[-1]


def load_run(path: Path, *, what: str = "run file") -> RunResult:
    if not path.exists():
        raise UsageError(f"{what} not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunResult.model_validate(data)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        detail = exc.msg if isinstance(exc, json.JSONDecodeError) else exc.__class__.__name__
        raise UsageError(
            f"{what} {path} is corrupted or not an EvalGate run ({detail})",
            hint="restore it from git (git checkout -- <file>), or rebuild it with "
            "'evalgate run' + 'evalgate baseline update'. See docs/runbook.md",
        ) from None


def load_baseline(path: Path) -> RunResult | None:
    if not path.exists():
        return None
    return load_run(path, what="baseline")


def update_baseline(
    run: RunResult, baseline_path: Path, suites: list[str] | None = None
) -> RunResult:
    """Promote ``run`` to the baseline. With ``suites``, only those suites are replaced
    and the rest of the existing baseline is kept."""
    if suites:
        missing = [s for s in suites if run.suite(s) is None]
        if missing:
            raise UsageError(
                f"suite(s) not in the selected run: {', '.join(missing)}",
                hint="run those suites first: evalgate run --suite NAME",
            )
        existing = load_baseline(baseline_path)
        if existing is not None:
            kept = [s for s in existing.suites if s.name not in suites]
            chosen = [s for s in run.suites if s.name in suites]
            run = run.model_copy(update={"suites": kept + chosen})
        else:
            run = run.model_copy(update={"suites": [s for s in run.suites if s.name in suites]})
    atomic_write(baseline_path, dump_run(run))
    return run
