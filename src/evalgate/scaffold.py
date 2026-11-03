"""Files written by ``evalgate init``."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG = """\
# EvalGate configuration. Full reference: https://github.com/mourya-dasgupta/evalgate/blob/main/docs/guide.md
version: 1

settings:
  concurrency: 8          # parallel model calls per suite
  timeout_s: 60
  max_retries: 3          # retries on 429 / 5xx / timeouts, with exponential backoff
  cassette_dir: cassettes # recorded responses, replayed in CI (commit this directory)

suites:
  - name: sentiment
    description: Classify product reviews as positive / negative / neutral.
    target:
      # 'mock' is a deterministic, rule-based stand-in so this example runs offline.
      # Swap in a real model, then record once with:  evalgate --mode record run
      #   provider: openai_compatible      # or: anthropic
      #   model: gpt-4o-mini
      #   api_key_env: OPENAI_API_KEY
      provider: mock
      model: mock-sentiment
      prompt: prompts/sentiment.txt
      params: {temperature: 0}
      mock_responses:
        - match: "(?i)love|great|excellent|perfect|amazing"
          respond: '{"label": "positive"}'
        - match: "(?i)broke|terrible|awful|refund|worst|disappointed"
          respond: '{"label": "negative"}'
      mock_default: '{"label": "neutral"}'
    golden: golden/sentiment.jsonl
    scorers:
      - type: json_valid
      - type: label_match
        field: label
        labels: [positive, negative, neutral]
        weight: 2
    gate:
      min_pass_rate: 0.8      # absolute floor
      max_regression: 5       # max drop vs baseline, in percentage points
      max_new_failures: 1     # cases that passed in the baseline and fail now
      critical_tags: [critical]
"""

PROMPT = """\
You are a sentiment classifier for product reviews.
Reply with JSON only, exactly like {"label": "positive"}.
Allowed labels: positive, negative, neutral.

Review: {{ review }}
"""

CASES = [
    ("r01", "Absolutely love this kettle, boils in two minutes.", "positive", []),
    ("r02", "Great battery life, would buy again.", "positive", []),
    ("r03", "Arrived broken and support never replied.", "negative", ["critical"]),
    ("r04", "Worst purchase this year. I want a refund.", "negative", ["critical"]),
    ("r05", "It is a phone case. It fits the phone.", "neutral", []),
    ("r06", "Delivered on Tuesday as promised.", "neutral", []),
    ("r07", "Perfect fit and the colour is exactly as shown.", "positive", []),
    ("r08", "The strap feels flimsy and I'm disappointed.", "negative", []),
    ("r09", "Packaging was plain, product does the job.", "neutral", []),
    (
        "r10",
        "Oh great, another charger that stopped working after a week.",
        "negative",
        ["sarcasm"],
    ),
]

WORKFLOW = """\
name: EvalGate

on:
  pull_request:

permissions:
  contents: read

jobs:
  evalgate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Runs `evalgate gate` in replay mode (no API keys needed), writes the Markdown
      # report to the job summary and uploads the HTML report as an artifact.
      # Pin to a release tag (e.g. @v0.1.0) once one is published.
      - uses: mourya-dasgupta/evalgate@main
        with:
          config: evalgate.yaml
"""


def golden_jsonl() -> str:
    lines = []
    for case_id, review, label, tags in CASES:
        row: dict[str, object] = {
            "id": case_id,
            "input": {"review": review},
            "expected": {"label": label},
        }
        if tags:
            row["tags"] = tags
        lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def scaffold_files() -> dict[str, str]:
    return {
        "evalgate.yaml": CONFIG,
        "prompts/sentiment.txt": PROMPT,
        "golden/sentiment.jsonl": golden_jsonl(),
        ".github/workflows/evalgate.yml": WORKFLOW,
    }


def write_scaffold(root: Path, *, force: bool = False) -> tuple[list[Path], list[Path]]:
    """Write the starter project. Returns ``(written, skipped)``."""
    written: list[Path] = []
    skipped: list[Path] = []
    for rel, content in scaffold_files().items():
        path = root / rel
        if path.exists() and not force:
            skipped.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written, skipped
