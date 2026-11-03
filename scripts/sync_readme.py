"""Copy an excerpt of the real demo gate-failure report into README.md.

Run after `make demo` (the Makefile does this) so the README always shows output that
was actually produced, never hand-written numbers.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "assets" / "demo-gate-fail.md"
README = ROOT / "README.md"
START = "<!-- demo-excerpt:start -->"
END = "<!-- demo-excerpt:end -->"


def excerpt(report: str) -> str:
    lines = report.splitlines()
    details = lines.index("<details>")
    head = lines[:details]
    flip_starts = [i for i, line in enumerate(lines) if line.startswith("#### ")]
    first_flip = lines[flip_starts[0] : flip_starts[1]] if len(flip_starts) > 1 else []
    total = re.search(r"<b>(\d+) flipped case", report)
    n_flips = int(total.group(1)) if total else len(flip_starts)
    tag_rows = [line for line in lines if line.startswith("| `")]
    verdict = next(line for line in reversed(lines) if line.startswith("**Verdict:"))
    out = [*head]
    if first_flip:
        out += [f"▼ {n_flips} flipped case(s) (collapsed in the PR comment); the first one:", ""]
        out += [*first_flip]
        if n_flips > 1:
            out += [f"… {n_flips - 1} more flipped case(s) …", ""]
    out += ["▼ Pass rate by tag", "", "| Tag | Cases | Pass rate | Δ vs baseline |"]
    out += ["|---|---:|---:|---:|"]
    out += [*tag_rows, "", verdict]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print("README.md has no demo-excerpt markers", file=sys.stderr)
        return 1
    block = f"{START}\n````markdown\n{excerpt(REPORT.read_text(encoding='utf-8'))}````\n{END}"
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.DOTALL)
    if new != text:
        README.write_text(new, encoding="utf-8")
        print("README.md demo excerpt updated")
    else:
        print("README.md demo excerpt already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
