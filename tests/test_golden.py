from __future__ import annotations

from pathlib import Path

import pytest

from evalgate.errors import GoldenSetError
from evalgate.golden import load_golden, parse_golden_lines


def test_parses_cases_with_unicode_and_blank_lines() -> None:
    lines = [
        '{"id": "a", "input": {"m": "Mera refund kab aayega?"}, "expected": "refund",'
        ' "tags": ["hinglish"], "notes": "n"}',
        "",
        '{"id": "b", "input": {"m": "আমার টাকা ফেরত দিন"}, "expected": {"x": 1}}',
    ]
    cases = parse_golden_lines(lines, "g.jsonl")
    assert [c.id for c in cases] == ["a", "b"]
    assert cases[0].tags == ["hinglish"]
    assert cases[0].line == 1
    assert cases[1].line == 3
    assert cases[1].input["m"] == "আমার টাকা ফেরত দিন"
    assert "line" not in cases[0].model_dump()


def test_reports_every_error_with_line_numbers() -> None:
    lines = [
        '{"id": "a", "input": {}, "expected": 1}',
        "{not json",
        "[1, 2]",
        '{"id": "b", "expected": 1}',
        '{"id": "a", "input": {}, "expected": 2}',
        '{"id": "c", "input": {}, "expected": 1, "tagz": []}',
        '{"id": "d", "input": "text", "expected": 1}',
        '{"id": "e", "input": {}, "expected": 1, "tags": [" "]}',
    ]
    with pytest.raises(GoldenSetError) as exc:
        parse_golden_lines(lines, "g.jsonl")
    msg = exc.value.message
    assert "g.jsonl has 7 invalid line(s)" in msg
    assert "line 2: invalid JSON" in msg
    assert "line 3: expected a JSON object, got list" in msg
    assert "line 4: missing required field 'input'" in msg
    assert "line 5: duplicate id 'a' (first used on line 1)" in msg
    assert "line 6: unknown field 'tagz'" in msg
    assert "line 7: field 'input'" in msg
    assert "line 8: field 'tags'" in msg


def test_error_list_is_truncated() -> None:
    with pytest.raises(GoldenSetError, match=r"and 5 more"):
        parse_golden_lines(["{bad"] * 25, "g.jsonl")


def test_empty_file() -> None:
    with pytest.raises(GoldenSetError, match="contains no cases"):
        parse_golden_lines(["", "  "], "g.jsonl")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GoldenSetError, match="not found"):
        load_golden(tmp_path / "missing.jsonl")


def test_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(GoldenSetError, match="UTF-8"):
        load_golden(path)


def test_load_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text('{"id": "x", "input": {"a": 1}, "expected": null}\n', "utf-8")
    [case] = load_golden(path)
    assert case.expected is None
