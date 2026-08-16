#!/usr/bin/env python3
"""Validate an A-share dividend-yield-scan Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(股息|分红|红利|dividend|yield)", "一级标题需要标明高股息/分红报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("overview", r"^##\s*(?:\d+[.、]\s*)?分红事件总览", "缺少分红事件总览章节"),
    ("yield_rank", r"^##\s*(?:\d+[.、]\s*)?股息率榜", "缺少股息率榜章节"),
    ("continuity", r"^##\s*(?:\d+[.、]\s*)?连续分红", "缺少连续分红与稳定性章节"),
    ("cash_vs_share", r"^##\s*(?:\d+[.、]\s*)?现金分红\s*vs", "缺少现金分红 vs 送转章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整高股息/分红报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|get_stock_cash_dividend|get_stock_dividend|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    # Yield method disclosure: round_lot divisor must be stated.
    if not re.search(r"round_lot", text):
        issues.append("缺少股息率口径：每股现金分红 = div_cash_gross / round_lot（须注明基准单位，避免 10 倍错误）")

    # Trailing window + price date.
    if not re.search(r"(滚动|滚动窗口|近12|近 12|trailing|价格日|收盘价日|截止)", text):
        issues.append("缺少股息率滚动窗口/价格日说明")

    # Cash vs 送转 separation.
    if not re.search(r"送转", text):
        issues.append("缺少现金分红与送转的区分（送转非现金回报，不得计入现金股息率）")

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
