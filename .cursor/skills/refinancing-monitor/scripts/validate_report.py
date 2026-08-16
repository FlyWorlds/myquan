#!/usr/bin/env python3
"""Validate an A-share refinancing-monitor Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(再融资|定增|定向增发|配股|refinancing|placement)", "一级标题需要标明再融资监控报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("overview", r"^##\s*(?:\d+[.、]\s*)?再融资事件总览", "缺少再融资事件总览章节"),
    ("funnel", r"^##\s*(?:\d+[.、]\s*)?进程漏斗", "缺少进程漏斗章节"),
    ("discount", r"^##\s*(?:\d+[.、]\s*)?折价", "缺少折价与破发章节"),
    ("dilution", r"^##\s*(?:\d+[.、]\s*)?稀释", "缺少稀释强度榜章节"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整再融资监控报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|get_stock_private_placement|get_stock_allotment|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(窗口|快照日|公告区间|announcement_date|数据日|截止)", text):
        issues.append("缺少查询窗口/快照日/公告区间说明")

    # Stage discipline: 预案 vs executed must be distinguished.
    if not re.search(r"(预案|进程|issue_status|核准|实施完成)", text):
        issues.append("缺少事件进程标注（预案/核准/实施完成），募资金额须区分预案与已募资")

    # 定增/配股 split must be present.
    if not (re.search(r"(定增|定向增发|private placement)", text, flags=re.IGNORECASE)
            and re.search(r"配股", text)):
        issues.append("缺少定增与配股的拆分（两者稀释方式不同，须分别列示）")

    if not re.search(r"不构成任何投资建议", text):
        issues.append("缺少免责声明：本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。")

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
