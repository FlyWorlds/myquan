#!/usr/bin/env python3
"""Validate a US sector rotation Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(美股|US).*(轮动|Rotation|行业)", "标题需含 美股/US + 轮动/行业"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("sector", r"^##\s*(?:\d+[.、]\s*)?(行业|板块).*表现", "缺少行业/板块表现章节"),
    ("valuation", r"^##\s*(?:\d+[.、]\s*)?估值", "缺少估值章节"),
    ("rotation", r"^##\s*(?:\d+[.、]\s*)?轮动", "缺少轮动章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整轮动报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(数据日|数据截止|生成时间|截止时间|as-of|snapshot)", text, flags=re.IGNORECASE):
        issues.append("缺少数据日、数据截止时间或 snapshot 说明")

    if not re.search(r"(T\+1|snapshot|as-of|财报.*滞后|估值.*截至)", text, flags=re.IGNORECASE):
        issues.append("缺少 T+1、snapshot 或财报滞后说明")

    if not re.search(r"不构成投资建议", text):
        issues.append("缺少“不构成投资建议”免责声明")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to the Markdown report")
    args = parser.parse_args()

    try:
        text = args.report.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"ERROR: report not found: {args.report}", file=sys.stderr)
        return 2

    issues = validate(text)
    if issues:
        print("FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
