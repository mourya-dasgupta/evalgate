"""Machine-readable report: the gate result plus the full run."""

from __future__ import annotations

import json

from evalgate.gate import GateResult
from evalgate.results import RunResult


def render_json(run: RunResult, gate: GateResult) -> str:
    payload = {
        "verdict": gate.verdict,
        "exit_code": int(gate.exit_code),
        "gate": gate.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
