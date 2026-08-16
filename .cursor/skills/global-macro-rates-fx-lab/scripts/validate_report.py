#!/usr/bin/env python3
"""Deterministic, stdlib-only checker for a Global Macro Rates FX Lab regime brief.

Verifies that a produced report contains the required sections defined by the SKILL.md
Output Contract, cites at least one public series id, carries a date/vintage label, and
ends with the mandatory research-only disclaimer.

Usage:
    python validate_report.py path/to/report.md

Exit codes:
    0  report has every required element
    1  report is missing one or more required elements
    2  usage / file error
"""
import re
import sys

# (label, regex) pairs. Each must match somewhere in the report text.
REQUIRED_SECTIONS = [
    ("regime summary", r"(概览|Regime summary)"),
    ("rate complex", r"(利率综合体|Rate complex)"),
    ("USD & major pairs", r"(美元与主要货币对|USD & major pairs|major pairs)"),
    ("international macro (get_macro_gb)", r"(国际宏观|International macro|get_macro_gb)"),
    ("consistency / divergences", r"(一致性与背离|Consistency|divergenc)"),
    ("sources & vintage", r"(数据来源|Sources|vintage|时效)"),
]

# At least one recognised public series id must appear (source labelling).
SERIES_IDS = ["DGS2", "DGS10", "T10Y2Y", "DFII10", "DTWEXBGS"]

# A date/as-of label must appear: ISO date, YYYYMMDD, or a Chinese/English as-of marker.
DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{8}\b",
    r"(截至|as[- ]of|as of|vintage|period_date)",
]

DISCLAIMER = "不构成任何投资建议"


def check(text):
    problems = []

    for label, pattern in REQUIRED_SECTIONS:
        if not re.search(pattern, text, re.IGNORECASE):
            problems.append("missing required section: %s" % label)

    if not any(sid in text for sid in SERIES_IDS):
        problems.append(
            "missing any public series id (expected one of: %s)" % ", ".join(SERIES_IDS)
        )

    if not any(re.search(p, text, re.IGNORECASE) for p in DATE_PATTERNS):
        problems.append("missing a date / as-of / vintage label")

    if DISCLAIMER not in text:
        problems.append("missing mandatory disclaimer: %s" % DISCLAIMER)

    return problems


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: python validate_report.py <report.md>\n")
        return 2
    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        sys.stderr.write("cannot read %s: %s\n" % (path, exc))
        return 2

    problems = check(text)
    if problems:
        sys.stderr.write("FAIL: report %s is missing required elements:\n" % path)
        for p in problems:
            sys.stderr.write("  - %s\n" % p)
        return 1

    sys.stdout.write("OK: %s has all required sections, a series id, a date label, "
                     "and the disclaimer.\n" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
