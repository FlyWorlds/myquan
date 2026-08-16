#!/usr/bin/env python3
"""Validate an HK/US insider-radar Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(内部人|insider)", "一级标题需要标明港股/美股内部人交易雷达报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("overview", r"^##\s*(?:\d+[.、]\s*)?内部人交易总览", "缺少内部人交易总览章节"),
    ("direction", r"^##\s*(?:\d+[.、]\s*)?(方向与类型|方向|类型分解)", "缺少方向与类型分解章节"),
    ("role", r"^##\s*(?:\d+[.、]\s*)?身份加权", "缺少身份加权章节"),
    ("cluster", r"^##\s*(?:\d+[.、]\s*)?聚集", "缺少聚集买入/卖出章节"),
    ("holding", r"^##\s*(?:\d+[.、]\s*)?持股变化", "缺少持股变化章节"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整内部人交易雷达报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(
        r"(数据来源|来源接口|使用接口|get_stock_insider_trade|get_stock_insider_transaction|Pandadata)",
        text,
    ):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(窗口|快照日|申报日|info_date|截止|区间)", text):
        issues.append("缺少查询窗口/申报日区间说明")

    # Type taxonomy: open-market must be separated from option/gift/plan.
    if not re.search(r"(公开市场|open[ -]?market|开放市场)", text):
        issues.append("缺少公开市场买卖与其他类型的分解（公开市场净额须为头条）")
    if not re.search(r"(期权|行权|赠与|计划减持|option|grant|gift)", text):
        issues.append("缺少交易类型分类说明：期权行权/赠与/计划减持须与公开市场买卖分开")

    # Filing lag caveat.
    if not re.search(r"(申报滞后|滞后|info_date|transaction_date|申报日.*交易日|交易日.*申报日)", text):
        issues.append("缺少申报滞后说明：info_date(申报) 与 transaction_date(交易) 不同")

    # Currency labelling.
    if not re.search(r"(币种|货币|currency|HKD|USD|港元|美元)", text):
        issues.append("缺少币种说明：交易额须标货币，不跨币种相加")

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
