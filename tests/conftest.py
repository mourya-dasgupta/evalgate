"""Shared fixtures: build small throwaway EvalGate projects on disk."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SENTIMENT_PROMPT = "Classify the sentiment of this review as JSON.\nReview: {{ text }}\n"

MOCK_CONFIG = """\
version: 1
settings:
  concurrency: 4
  max_retries: 0
  backoff_base_s: 0
suites:
  - name: sentiment
    target:
      provider: mock
      model: mock-1
      prompt: prompts/sentiment.txt
      mock_responses:
        - match: "(?i)love|great|excellent"
          respond: '{"label": "positive"}'
        - match: "(?i)hate|awful|terrible"
          respond: '{"label": "negative"}'
      mock_default: '{"label": "neutral"}'
    golden: golden/sentiment.jsonl
    scorers:
      - type: json_valid
      - type: label_match
        field: label
        weight: 2
    gate:
      min_pass_rate: 0.6
      max_regression: 10
      max_new_failures: 1
      critical_tags: [critical]
  - name: echo
    target:
      provider: mock
      model: mock-1
      prompt: prompts/echo.txt
      mock_default: "hello world"
    golden: golden/echo.jsonl
    scorers:
      - type: contains
        values: ["hello"]
"""

SENTIMENT_CASES: list[dict[str, Any]] = [
    {"id": "s1", "input": {"text": "I love it"}, "expected": {"label": "positive"}},
    {"id": "s2", "input": {"text": "Great value"}, "expected": {"label": "positive"}},
    {
        "id": "s3",
        "input": {"text": "I hate this"},
        "expected": {"label": "negative"},
        "tags": ["critical"],
    },
    {"id": "s4", "input": {"text": "It arrived"}, "expected": {"label": "neutral"}},
    {
        "id": "s5",
        "input": {"text": "Not great, honestly awful"},
        "expected": {"label": "negative"},
        "tags": ["tricky"],
    },
]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


@pytest.fixture
def make_project(tmp_path: Path) -> Callable[..., Path]:
    """Create a mock-provider project; returns the config path."""

    def _make(
        config: str = MOCK_CONFIG,
        cases: list[dict[str, Any]] | None = None,
        echo_cases: list[dict[str, Any]] | None = None,
    ) -> Path:
        (tmp_path / "prompts").mkdir(exist_ok=True)
        (tmp_path / "prompts" / "sentiment.txt").write_text(SENTIMENT_PROMPT, "utf-8")
        (tmp_path / "prompts" / "echo.txt").write_text("Say hello to {{ name }}", "utf-8")
        write_jsonl(tmp_path / "golden" / "sentiment.jsonl", cases or SENTIMENT_CASES)
        write_jsonl(
            tmp_path / "golden" / "echo.jsonl",
            echo_cases or [{"id": "e1", "input": {"name": "Asha"}, "expected": "hello"}],
        )
        cfg = tmp_path / "evalgate.yaml"
        cfg.write_text(textwrap.dedent(config), "utf-8")
        return cfg

    return _make
