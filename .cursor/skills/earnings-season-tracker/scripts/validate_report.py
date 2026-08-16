#!/usr/bin/env python3
"""Validate an earnings-season tracker Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(财报季|业绩|earnings)", "一级标题需要标明财报季或业绩扫描报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("progress", r"^##\s*(?:\d+[.、]\s*)?披露进度", "缺少披露进度概览章节"),
    ("forecast", r"^##\s*(?:\d+[.、]\s*)?业绩预告", "缺少业绩预告类型分布章节"),
    ("leaders", r"^##\s*(?:\d+[.、]\s*)?(超预期|暴雷|个股榜)", "缺少超预期/暴雷个股榜章节"),
    ("industry", r"^##\s*(?:\d+[.、]\s*)?行业业绩", "缺少行业业绩景气分布章节"),
    ("audit", r"^##\s*(?:\d+[.、]\s*)?审计", "缺少审计非标清单章节（年报季必备，非年报季标注本期不适用）"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整财报季扫描")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(报告期|end_date|数据日|快照日|截止|生成时间)", text):
        issues.append("缺少报告期/快照日/数据截止时间说明")

    # Financial-statement caliber must be disclosed when single-quarter or cumulative
    # figures are discussed.
    if re.search(r"(单季|累计)", text) and not re.search(r"(口径|caliber)", text):
        issues.append("涉及单季/累计数据时需要标注口径")

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
