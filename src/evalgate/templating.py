"""Prompt templates (Jinja2 with strict undefined variables)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
from jinja2 import meta

from evalgate.errors import TemplateError

_ENV = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=False,
    keep_trailing_newline=False,
)


class PromptTemplate:
    """A Jinja2 prompt template. Case ``input`` keys are the template variables."""

    def __init__(self, source: str, name: str = "<prompt>") -> None:
        self.source = source
        self.name = name
        try:
            self._template = _ENV.from_string(source)
            self.variables: frozenset[str] = frozenset(
                meta.find_undeclared_variables(_ENV.parse(source))
            )
        except jinja2.TemplateSyntaxError as exc:
            raise TemplateError(
                f"{name}: template syntax error on line {exc.lineno}: {exc.message}"
            ) from None

    @classmethod
    def from_file(cls, path: Path) -> PromptTemplate:
        if not path.exists():
            raise TemplateError(
                f"prompt template not found: {path}",
                hint="check the 'prompt:' path in your config (relative to the config file)",
            )
        return cls(path.read_text(encoding="utf-8"), name=str(path))

    def render(self, variables: dict[str, Any], *, case_id: str | None = None) -> str:
        try:
            return self._template.render(**variables)
        except jinja2.UndefinedError as exc:
            where = f" for case {case_id!r}" if case_id else ""
            raise TemplateError(
                f"{self.name}: could not render{where}: {exc.message}",
                hint=f"the template uses {{{{ ... }}}} variables {sorted(self.variables)}; "
                "every golden case 'input' must provide them",
            ) from None
