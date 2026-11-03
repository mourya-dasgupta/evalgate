from __future__ import annotations

from pathlib import Path

import pytest

from evalgate.errors import TemplateError
from evalgate.templating import PromptTemplate


def test_render_and_variables() -> None:
    t = PromptTemplate("Hi {{ name }}, about {{ topic | upper }}")
    assert t.variables == frozenset({"name", "topic"})
    assert t.render({"name": "Asha", "topic": "refund"}) == "Hi Asha, about REFUND"


def test_missing_variable_is_friendly() -> None:
    t = PromptTemplate("Hi {{ name }}", name="p.txt")
    with pytest.raises(TemplateError) as exc:
        t.render({}, case_id="c1")
    assert "p.txt: could not render for case 'c1'" in exc.value.message
    assert "'name' is undefined" in exc.value.message
    assert "['name']" in (exc.value.hint or "")


def test_syntax_error() -> None:
    with pytest.raises(TemplateError, match="syntax error on line 1"):
        PromptTemplate("{{ oops ")


def test_from_file(tmp_path: Path) -> None:
    path = tmp_path / "p.txt"
    path.write_text("Message: {{ message }}\n", "utf-8")
    assert PromptTemplate.from_file(path).render({"message": "hello"}) == "Message: hello"
    with pytest.raises(TemplateError, match="not found"):
        PromptTemplate.from_file(tmp_path / "missing.txt")
