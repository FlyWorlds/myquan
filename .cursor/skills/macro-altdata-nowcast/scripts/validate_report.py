#!/usr/bin/env python3
"""Validate a macro alt-data nowcast Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(特色|另类|nowcast|景气)", "一级标题需要标明宏观特色/另类数据行业景气 Nowcast"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("dictionary", r"^##\s*(?:\d+[.、]\s*)?指标字典", "缺少指标字典章节（get_macro_detail 代码解析）"),
    ("snapshot", r"^##\s*(?:\d+[.、]\s*)?行业景气快照", "缺少行业景气快照章节"),
    ("trend", r"^##\s*(?:\d+[.、]\s*)?趋势与拐点", "缺少趋势与拐点章节"),
    ("cross", r"^##\s*(?:\d+[.、]\s*)?跨行业对比", "缺少跨行业对比章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整特色数据 nowcast 报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|get_macro_|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    # Mandatory code-resolution note.
    if not re.search(r"(get_macro_detail|指标字典|代码.*名称|指标代码)", text):
        issues.append("缺少指标代码解析说明：不透明代码须先经 get_macro_detail 解析为名称/单位/频率")

    # Alt-data / sample caveat.
    if not re.search(r"(另类|特色|样本|抽样|非官方|nowcast|领先.*官方)", text):
        issues.append("缺少另类/样本口径说明：特色数据是及时样本，用于 nowcast，非官方统计")

    # Frequency / window.
    if not re.search(r"(频率|frequency|日频|周频|月频|窗口|数据期|period_date)", text):
        issues.append("缺少频率/窗口/数据期说明")

    # stat_type awareness.
    if not re.search(r"(stat_type|同比|环比|已为同比|口径)", text):
        issues.append("缺少同比/环比口径说明（stat_type：已为同比的序列不重复求同比）")

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
