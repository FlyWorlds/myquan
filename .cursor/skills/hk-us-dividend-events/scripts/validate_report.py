#!/usr/bin/env python3
"""Validate an HK/U.S. dividend events Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(港美股|港股|美股).*(分红|Dividend).*(事件|Calendar)", "标题需含 港/美股 + 分红/Dividend + 事件/Calendar"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("upcoming", r"^##\s*(?:\d+[.、]\s*)?即将除息", "缺少即将除息章节"),
    ("recent", r"^##\s*(?:\d+[.、]\s*)?近期.*派息", "缺少近期派息章节"),
    ("yield", r"^##\s*(?:\d+[.、]\s*)?(高股息|Yield)", "缺少高股息/Yield 榜章节"),
    ("drip", r"^##\s*(?:\d+[.、]\s*)?DRIP", "缺少 DRIP 章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整分红事件报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(数据日|数据截止|生成时间|截止时间|snapshot|Snapshot)", text):
        issues.append("缺少数据日、数据截止或 snapshot 说明")

    if not re.search(r"(T\+1|snapshot|Snapshot|延迟披露)", text):
        issues.append("缺少 T+1、snapshot 或延迟披露说明")

    if not re.search(r"不构成投资建议", text):
        issues.append("缺少“不构成投资建议”免责")

    if re.search(r"((?<!最小)买入|卖出|建仓|减仓|加仓|止盈|止损|目标价\s*\d)", text):
        issues.append("报告包含操作性字样，请改为事实归纳")

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
