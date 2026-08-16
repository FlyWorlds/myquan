#!/usr/bin/env python3
"""Validate an A-share institutional-research-tracker Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(机构调研|调研|investor|research)", "一级标题需要标明机构调研监控报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("overview", r"^##\s*(?:\d+[.、]\s*)?调研活动总览", "缺少调研活动总览章节"),
    ("heat", r"^##\s*(?:\d+[.、]\s*)?调研热度", "缺少调研热度榜章节"),
    ("type", r"^##\s*(?:\d+[.、]\s*)?机构类型", "缺少机构类型分布章节"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整机构调研监控报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|get_investor_activity|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(窗口|快照日|活动区间|数据日|截止)", text):
        issues.append("缺少查询窗口/快照日/活动区间说明")

    # Frequency vs breadth must be distinguished.
    if not (re.search(r"(次数|频次|事件数|调研次数)", text)
            and re.search(r"(广度|家机构|distinct|参与机构数|机构数)", text)):
        issues.append("缺少频次与广度的区分（被调研次数≠参与机构家数，须分别列示）")

    # Institution type classification presence.
    if not re.search(r"(公募|券商|保险|私募|外资|未披露|机构类型)", text):
        issues.append("缺少机构类型分布（公募/券商/保险/私募/外资/未披露）")

    # Attention-not-endorsement framing.
    if not re.search(r"(关注|关注度|非背书|不构成背书|注意|attention)", text):
        issues.append("缺少『被调研=关注非背书』的定性框定")

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
