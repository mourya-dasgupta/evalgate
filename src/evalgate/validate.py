"""Static validation of a project: config, golden sets, templates and scorers."""

from __future__ import annotations

from dataclasses import dataclass, field

from evalgate.config import EvalGateConfig, SuiteConfig
from evalgate.errors import ConfigError, EvalGateError, TemplateError
from evalgate.golden import GoldenCase, load_golden
from evalgate.templating import PromptTemplate


@dataclass
class SuiteCheck:
    suite: str
    cases: int = 0
    tags: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    suites: list[SuiteCheck]

    @property
    def ok(self) -> bool:
        return all(not s.errors for s in self.suites)


def load_templates(
    config: EvalGateConfig, suite: SuiteConfig
) -> tuple[PromptTemplate, PromptTemplate | None]:
    prompt = PromptTemplate.from_file(config.resolve(suite.target.prompt))
    system = (
        PromptTemplate.from_file(config.resolve(suite.target.system_prompt))
        if suite.target.system_prompt
        else None
    )
    return prompt, system


def check_render(
    cases: list[GoldenCase], prompt: PromptTemplate, system: PromptTemplate | None
) -> list[str]:
    """Render every case so missing template variables are caught before any model call."""
    problems: list[str] = []
    for case in cases:
        for template in (prompt, system):
            if template is None:
                continue
            try:
                template.render(case.input, case_id=case.id)
            except TemplateError as exc:
                problems.append(f"line {case.line}: {exc.message}")
    return problems


def validate_suite(config: EvalGateConfig, suite: SuiteConfig) -> SuiteCheck:
    from evalgate.scorers import build_scorers  # local import: scorers import config

    check = SuiteCheck(suite=suite.name)
    cases: list[GoldenCase] = []
    try:
        cases = load_golden(config.resolve(suite.golden))
        check.cases = len(cases)
        for case in cases:
            for tag in case.tags:
                check.tags[tag] = check.tags.get(tag, 0) + 1
    except EvalGateError as exc:
        check.errors.append(exc.message)
    try:
        prompt, system = load_templates(config, suite)
        if cases:
            check.errors.extend(check_render(cases, prompt, system))
        unused = sorted(
            {k for c in cases for k in c.input}
            - prompt.variables
            - (system.variables if system else frozenset())
        )
        if unused:
            check.warnings.append(
                f"input keys not used by the prompt template: {', '.join(unused)}"
            )
    except EvalGateError as exc:
        check.errors.append(exc.message)
    try:
        build_scorers(suite, config)
    except EvalGateError as exc:
        check.errors.append(exc.message)
    for tag in suite.gate.critical_tags:
        if cases and tag not in check.tags:
            check.warnings.append(f"critical tag {tag!r} is not used by any case")
    if check.cases and check.cases < 20:
        check.warnings.append(
            f"only {check.cases} case(s); 30+ cases give a much more stable pass rate"
        )
    return check


def validate_project(
    config: EvalGateConfig, suite_names: list[str] | None = None
) -> ValidationReport:
    suites = config.select_suites(suite_names)
    return ValidationReport(suites=[validate_suite(config, s) for s in suites])


def ensure_valid(config: EvalGateConfig, suite_names: list[str] | None = None) -> None:
    report = validate_project(config, suite_names)
    if not report.ok:
        lines = [f"[{s.suite}] {e}" for s in report.suites for e in s.errors]
        raise ConfigError("validation failed:\n" + "\n".join(f"  - {line}" for line in lines))
