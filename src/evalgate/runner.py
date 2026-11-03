"""Run golden-set evaluations: render prompts, call the provider (through the
cassette layer), score every output, aggregate metrics."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from evalgate import __version__
from evalgate.cassette import Cassette, CassetteProvider
from evalgate.config import EvalGateConfig, Mode, ProviderConfig, SuiteConfig
from evalgate.errors import EvalGateError, ProviderError, TemplateError
from evalgate.golden import GoldenCase, load_golden
from evalgate.providers import create_provider
from evalgate.providers.base import ChatRequest, Provider
from evalgate.results import (
    CaseResult,
    ConfusionMatrix,
    Metrics,
    RunResult,
    ScorerOutcome,
    SuiteResult,
    TargetInfo,
)
from evalgate.scorers import BoundScorer, ScorerDeps, build_scorers
from evalgate.validate import load_templates

ProgressCallback = Callable[[str, int, int], None]


def make_run_id(now: datetime | None = None) -> str:
    """A sortable, filename-safe UTC timestamp, e.g. ``2026-11-03T06-15-00-123456Z``."""
    moment = now or datetime.now(UTC)
    return moment.strftime("%Y-%m-%dT%H-%M-%S-%fZ")


class ProviderPool:
    """Creates providers for a suite (target and judges), wrapping each in the suite's
    cassette when it needs recording, and closes them all at the end."""

    def __init__(
        self,
        config: EvalGateConfig,
        suite: SuiteConfig,
        mode: Mode,
        environ: Mapping[str, str] | None,
    ) -> None:
        self.config = config
        self.suite = suite
        self.mode = mode
        self.environ = environ
        self.cassette = Cassette.load(config.cassette_dir / f"{suite.name}.jsonl")
        self.providers: list[Provider] = []

    def create(self, provider_config: ProviderConfig) -> Provider:
        inner = create_provider(
            provider_config, self.config.settings, self.config.root, self.environ
        )
        provider: Provider = inner
        if inner.requires_recording:
            provider = CassetteProvider(inner, self.cassette, self.mode, self.suite.name)
        self.providers.append(provider)
        return provider

    @property
    def cache_hits(self) -> int:
        return sum(p.hits for p in self.providers if isinstance(p, CassetteProvider))

    async def close(self) -> None:
        if self.mode == "record":
            self.cassette.save()
        for provider in self.providers:
            await provider.aclose()


def weighted_score(outcomes: list[ScorerOutcome]) -> float:
    if not outcomes:
        return 0.0
    total_weight = sum(o.weight for o in outcomes)
    if total_weight <= 0:
        return sum(o.score for o in outcomes) / len(outcomes)
    return sum(o.score * o.weight for o in outcomes) / total_weight


async def score_case(
    scorers: list[BoundScorer], output: str, case: GoldenCase
) -> list[ScorerOutcome]:
    outcomes: list[ScorerOutcome] = []
    for bound in scorers:
        cfg = bound.config
        try:
            result = await bound.impl.score(output, case)
            score, reason, details = result.score, result.reason, result.details
        except EvalGateError:
            raise
        except Exception as exc:  # a buggy custom scorer must not kill the whole run
            score, reason, details = 0.0, f"scorer raised {exc.__class__.__name__}: {exc}", {}
        outcomes.append(
            ScorerOutcome(
                name=bound.name,
                type=cfg.type,
                score=round(score, 6),
                passed=score >= cfg.threshold,
                reason=reason,
                weight=cfg.weight,
                required=cfg.required,
                details=details,
            )
        )
    return outcomes


def build_request(
    suite: SuiteConfig, case: GoldenCase, prompt: str, system: str | None
) -> ChatRequest:
    messages: list[dict[str, str]] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return ChatRequest(
        model=suite.target.model, messages=tuple(messages), params=suite.target.params
    )


def aggregate(
    suite: SuiteConfig, cases: list[CaseResult]
) -> tuple[dict[str, Metrics], list[ConfusionMatrix]]:
    tags: dict[str, list[CaseResult]] = {}
    for c in cases:
        for tag in c.tags:
            tags.setdefault(tag, []).append(c)
    tag_metrics = {t: Metrics.from_cases(cs) for t, cs in sorted(tags.items())}
    confusion: list[ConfusionMatrix] = []
    for sc in suite.scorers:
        if sc.type != "label_match":
            continue
        pairs: list[tuple[str, str]] = []
        for c in cases:
            for o in c.scores:
                if o.name == sc.display_name and "expected" in o.details:
                    pairs.append((str(o.details["expected"]), str(o.details["predicted"])))
        if pairs:
            confusion.append(ConfusionMatrix.from_pairs(sc.display_name, pairs))
    return tag_metrics, confusion


async def run_suite(
    config: EvalGateConfig,
    suite: SuiteConfig,
    mode: Mode,
    *,
    environ: Mapping[str, str] | None = None,
    progress: ProgressCallback | None = None,
) -> SuiteResult:
    cases = load_golden(config.resolve(suite.golden))
    prompt_tpl, system_tpl = load_templates(config, suite)

    # Render everything up-front so template mistakes fail fast, before any API call.
    rendered: list[tuple[GoldenCase, ChatRequest]] = []
    problems: list[str] = []
    for case in cases:
        try:
            prompt = prompt_tpl.render(case.input, case_id=case.id)
            system = system_tpl.render(case.input, case_id=case.id) if system_tpl else None
        except TemplateError as exc:
            problems.append(exc.message)
            continue
        rendered.append((case, build_request(suite, case, prompt, system)))
    if problems:
        raise TemplateError(
            f"suite {suite.name!r}: {len(problems)} case(s) could not be rendered:\n"
            + "\n".join(f"  - {p}" for p in problems[:10]),
            hint="run 'evalgate validate' for the full list",
        )

    pool = ProviderPool(config, suite, mode, environ)
    try:
        scorers = build_scorers(suite, config, ScorerDeps(provider_factory=pool.create))
        target = pool.create(suite.target)
        semaphore = asyncio.Semaphore(suite.concurrency or config.settings.concurrency)
        done = 0

        async def one(case: GoldenCase, request: ChatRequest) -> CaseResult:
            nonlocal done
            async with semaphore:
                result = CaseResult(
                    id=case.id,
                    tags=case.tags,
                    input=case.input,
                    expected=case.expected,
                    notes=case.notes,
                )
                try:
                    response = await target.complete(request)
                    result.output = response.text
                    result.latency_ms = round(response.latency_ms, 1)
                    result.cached = response.cached
                    result.scores = await score_case(scorers, response.text, case)
                except ProviderError as exc:
                    result.error = exc.message
                    result.passed = False
                else:
                    result.score = round(weighted_score(result.scores), 6)
                    result.passed = all(o.passed for o in result.scores if o.required)
            done += 1
            if progress:
                progress(suite.name, done, len(rendered))
            return result

        results = list(await asyncio.gather(*(one(c, r) for c, r in rendered)))
    finally:
        await pool.close()

    tag_metrics, confusion = aggregate(suite, results)
    template_text = prompt_tpl.source + ("\n" + system_tpl.source if system_tpl else "")
    return SuiteResult(
        name=suite.name,
        description=suite.description,
        target=TargetInfo(
            provider=suite.target.provider,
            model=suite.target.model,
            prompt=suite.target.prompt,
            prompt_sha256=hashlib.sha256(template_text.encode("utf-8")).hexdigest(),
            params=suite.target.params,
        ),
        golden=suite.golden,
        metrics=Metrics.from_cases(results),
        tags=tag_metrics,
        confusion=confusion,
        cache_hits=pool.cache_hits,
        cases=results,
    )


async def run_all(
    config: EvalGateConfig,
    suites: list[SuiteConfig],
    mode: Mode,
    *,
    environ: Mapping[str, str] | None = None,
    progress: ProgressCallback | None = None,
    now: datetime | None = None,
) -> RunResult:
    moment = now or datetime.now(UTC)
    suite_results = [
        await run_suite(config, s, mode, environ=environ, progress=progress) for s in suites
    ]
    try:
        config_path = str(config.path.relative_to(config.root))
    except ValueError:  # pragma: no cover - path is always under root
        config_path = str(config.path)
    return RunResult(
        evalgate_version=__version__,
        run_id=make_run_id(moment),
        created_at=moment.isoformat(timespec="seconds"),
        mode=mode,
        config_path=config_path,
        suites=suite_results,
    )


def run_sync(
    config: EvalGateConfig, suites: list[SuiteConfig], mode: Mode, **kwargs: Any
) -> RunResult:
    return asyncio.run(run_all(config, suites, mode, **kwargs))
