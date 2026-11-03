"""Result models. A run is serialised to ``.evalgate/runs/<timestamp>.json``; the
baseline is simply a promoted run."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class ScorerOutcome(BaseModel):
    name: str
    type: str
    score: float
    passed: bool
    reason: str = ""
    weight: float = 1.0
    required: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    id: str
    tags: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    expected: Any = None
    notes: str | None = None
    output: str | None = None
    error: str | None = None
    scores: list[ScorerOutcome] = Field(default_factory=list)
    score: float = 0.0
    passed: bool = False
    latency_ms: float = 0.0
    cached: bool = False

    @property
    def failure_reasons(self) -> list[str]:
        if self.error:
            return [f"error: {self.error}"]
        return [f"{s.name}: {s.reason}" for s in self.scores if s.required and not s.passed]


class Metrics(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    pass_rate: float = 0.0
    score: float = 0.0

    @classmethod
    def from_cases(cls, cases: list[CaseResult]) -> Metrics:
        total = len(cases)
        passed = sum(1 for c in cases if c.passed)
        return cls(
            total=total,
            passed=passed,
            failed=total - passed,
            errored=sum(1 for c in cases if c.error),
            pass_rate=passed / total if total else 0.0,
            score=sum(c.score for c in cases) / total if total else 0.0,
        )


class ConfusionMatrix(BaseModel):
    """Rows are expected labels, columns are predicted labels."""

    scorer: str
    labels: list[str]
    counts: dict[str, dict[str, int]]

    @classmethod
    def from_pairs(cls, scorer: str, pairs: list[tuple[str, str]]) -> ConfusionMatrix:
        labels = sorted({e for e, _ in pairs} | {p for _, p in pairs})
        counts = {e: dict.fromkeys(labels, 0) for e in labels}
        for expected, predicted in pairs:
            counts[expected][predicted] += 1
        return cls(scorer=scorer, labels=labels, counts=counts)

    def accuracy(self) -> float:
        total = sum(sum(row.values()) for row in self.counts.values())
        right = sum(self.counts[label][label] for label in self.labels)
        return right / total if total else 0.0


class TargetInfo(BaseModel):
    provider: str
    model: str
    prompt: str
    prompt_sha256: str
    params: dict[str, Any] = Field(default_factory=dict)


class SuiteResult(BaseModel):
    name: str
    description: str | None = None
    target: TargetInfo
    golden: str
    metrics: Metrics
    tags: dict[str, Metrics] = Field(default_factory=dict)
    confusion: list[ConfusionMatrix] = Field(default_factory=list)
    cache_hits: int = 0
    cases: list[CaseResult] = Field(default_factory=list)

    def case(self, case_id: str) -> CaseResult | None:
        return next((c for c in self.cases if c.id == case_id), None)

    @property
    def errored_cases(self) -> list[CaseResult]:
        return [c for c in self.cases if c.error]


class RunResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    evalgate_version: str
    run_id: str
    created_at: str
    mode: str
    config_path: str
    suites: list[SuiteResult]

    def suite(self, name: str) -> SuiteResult | None:
        return next((s for s in self.suites if s.name == name), None)

    @property
    def errored_cases(self) -> list[tuple[str, CaseResult]]:
        return [(s.name, c) for s in self.suites for c in s.errored_cases]
