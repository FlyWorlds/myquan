#!/usr/bin/env python3
"""Validate an HK/US quote-scan Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(港美股|港股|美股|hk|us).*(行情|估值|扫描|quote|scan)", "一级标题需要标明港美股行情/估值扫描报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("identity", r"^##\s*(?:\d+[.、]\s*)?标的与分类", "缺少标的与分类章节"),
    ("quote", r"^##\s*(?:\d+[.、]\s*)?行情与流动性", "缺少行情与流动性章节"),
    ("return", r"^##\s*(?:\d+[.、]\s*)?复权", "缺少复权收益与波动章节"),
    ("valuation", r"^##\s*(?:\d+[.、]\s*)?价量估值", "缺少价量估值指标章节"),
    ("relative", r"^##\s*(?:\d+[.、]\s*)?行业相对", "缺少行业相对位置章节"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整港美股扫描")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(数据日|数据截止|快照日|交易日|end_date|窗口)", text):
        issues.append("缺少数据日/快照日/查询窗口说明")

    # HK/US reports must disclose market and currency to avoid mixing.
    if not re.search(r"(HKD|港元|港币|HK\$)", text) and not re.search(r"(USD|美元|US\$|\$)", text):
        issues.append("缺少货币标注（港元 HKD / 美元 USD），港美股金额必须标明货币")

    if not re.search(r"(市场|港股|美股|HK|US)", text):
        issues.append("缺少市场标注（港股 HK / 美股 US）")

    # Adjusted-price discipline: if a multi-day return is claimed, adjustment should be noted.
    if re.search(r"(区间收益|复权收益|涨跌幅)", text) and not re.search(r"(复权|adj_factor|get_adj_factor|已调整|除权)", text):
        issues.append("涉及区间/多日收益时需要说明是否复权（get_adj_factor）")

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
