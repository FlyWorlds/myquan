#!/usr/bin/env python3
"""Validate a cross-listing parity Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(A\/H|A股|ADR|跨市场|Parity)", "标题需含 A/H 或 ADR 或 跨市场"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("ah", r"^##\s*(?:\d+[.、]\s*)?A\/H.*溢价", "缺少 A/H 溢价章节"),
    ("adr", r"^##\s*(?:\d+[.、]\s*)?ADR", "缺少 ADR 章节"),
    ("anomaly", r"^##\s*(?:\d+[.、]\s*)?(异常|极值|收敛)", "缺少异常/极值章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整跨市场折溢价报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(数据日|数据截止|生成时间|截止时间)", text):
        issues.append("缺少数据日或数据截止时间说明")

    if not re.search(r"(汇率来源|USD|HKD|CNY|美元|港元|人民币)", text):
        issues.append("缺少汇率来源、币种或汇率日期说明")

    if not re.search(r"(T\+1|snapshot|Snapshot|快照|财报滞后|一致预期)", text):
        issues.append("缺少 T+1、snapshot、财报滞后或一致预期说明")

    if not re.search(r"(ratio|股数比|存托比例|映射表版本)", text):
        issues.append("缺少股数比、存托比例或映射表版本说明")

    if not re.search(r"(不构成投资建议|不提供操作建议|仅作.*事实|仅用于研究)", text):
        issues.append("缺少非投资建议/事实归纳声明")

    if re.search(r"(建仓|减仓|加仓|止盈|止损|目标价\s*\d)", text):
        issues.append("报告包含操作性表达")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to the Markdown report")
    args = parser.parse_args()

    try:
        text = args.report.read_text(encoding='utf-8-sig')
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
