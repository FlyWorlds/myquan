#!/usr/bin/env python3
"""Validate an HK/US analyst-consensus radar Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(一致预期|consensus|评级|analyst)", "一级标题需要标明港美股一致预期/评级雷达报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("rating", r"^##\s*(?:\d+[.、]\s*)?评级分布", "缺少评级分布章节"),
    ("target", r"^##\s*(?:\d+[.、]\s*)?目标价", "缺少目标价与上行空间章节"),
    ("growth", r"^##\s*(?:\d+[.、]\s*)?长期成长", "缺少长期成长预期章节"),
    ("coverage", r"^##\s*(?:\d+[.、]\s*)?覆盖", "缺少覆盖广度与分歧章节"),
    ("revision", r"^##\s*(?:\d+[.、]\s*)?一致预期变化", "缺少一致预期变化章节"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整一致预期雷达")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    if not re.search(r"(数据日|数据截止|快照日|end_date)", text):
        issues.append("缺少数据日/快照日说明")

    # Market & currency must be disclosed for target prices.
    if not re.search(r"(市场|港股|美股|HK|US)", text):
        issues.append("缺少市场标注（港股 HK / 美股 US）")
    if not re.search(r"(HKD|港元|USD|美元|货币|currency)", text):
        issues.append("缺少货币标注，目标价必须标明货币")

    # Upside must state its baseline (target-price source + current-price anchor).
    if re.search(r"(上行空间|上涨空间|上行幅度|upside)", text) and not re.search(r"(现价|收盘价|基准|口径|目标价均值|目标价中位|mean|median)", text):
        issues.append("涉及上行空间时需要写明目标价口径与现价基准/日期")

    # Coverage depth should be present so thin consensus is not over-read.
    if not re.search(r"(覆盖|分析师数|recommendations_num|estimates_num|覆盖广度)", text):
        issues.append("缺少覆盖广度（分析师数量）说明，避免高估薄覆盖一致预期")

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
