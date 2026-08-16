#!/usr/bin/env python3
"""validate_report.py — deterministic checker for a term-structure report.

Stdlib-only. Verifies that a report produced by the
skill-global-commodity-term-structure workflow carries the required sections, a
source label, a date label, and the mandatory investment-advice disclaimer.

Usage:
    python scripts/validate_report.py <report.md>

Exit codes:
    0 — report has every required section and label
    1 — one or more checks failed (details printed to stderr)
    2 — usage error (missing/unreadable file)

This is a structural check only. It does not verify that the numbers are correct or
that the data is fresh — that is the analyst's and the reader's responsibility.
"""
from __future__ import annotations

import re
import sys

# Each requirement: a human label -> list of accepted regex markers (any one matches).
REQUIRED_SECTIONS = [
    ("Data Sources / 数据来源", [r"数据来源", r"data\s+source"]),
    ("Term Structure / 期限结构", [r"期限结构", r"term\s+structure"]),
    ("Contango/Backwardation classification", [r"contango", r"backwardation", r"升水|贴水|正向|反向"]),
    ("Roll Yield / 展期收益", [r"展期收益", r"roll\s+yield"]),
    ("Spreads / 价差", [r"价差", r"spread"]),
    ("Inventory context / 库存背景", [r"库存", r"inventory"]),
    ("Boundaries / 边界", [r"边界", r"boundar"]),
]

# A source/venue label must appear somewhere in the report.
SOURCE_MARKERS = [
    r"yahoo", r"stooq", r"\bcme\b", r"\bnymex\b", r"\bcomex\b", r"\bice\b",
    r"\blme\b", r"\beia\b", r"settlement", r"last[\s-]?trade", r"结算", r"来源",
]

# A date / as-of label must appear (ISO date, or an as-of / 日期 marker).
DATE_MARKERS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"as[\s-]?of",
    r"日期",
    r"截至",
]

DISCLAIMER_MARKERS = [r"不构成任何投资建议", r"not\s+(?:constitute\s+)?investment\s+advice"]


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def check(text: str) -> list[str]:
    failures: list[str] = []
    for label, markers in REQUIRED_SECTIONS:
        if not _any(markers, text):
            failures.append(f"missing required section: {label}")
    if not _any(SOURCE_MARKERS, text):
        failures.append("missing a data-source / venue label (e.g. Yahoo, CME, settlement)")
    if not _any(DATE_MARKERS, text):
        failures.append("missing a date / as-of label (e.g. 2026-07-14 or 'as-of')")
    if not _any(DISCLAIMER_MARKERS, text):
        failures.append("missing disclaimer: 不构成任何投资建议 / does not constitute investment advice")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: python validate_report.py <report.md>\n")
        return 2
    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        sys.stderr.write(f"cannot read {path}: {exc}\n")
        return 2

    failures = check(text)
    if failures:
        sys.stderr.write(f"FAIL: {path} is not a valid term-structure report:\n")
        for f in failures:
            sys.stderr.write(f"  - {f}\n")
        return 1
    sys.stdout.write(f"OK: {path} has all required sections and source/date/disclaimer labels\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
