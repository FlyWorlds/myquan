#!/usr/bin/env python3
"""Validate an A-share holder-structure-scan Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(股东结构|股东户数|筹码集中|holder[ -]?structure)", "一级标题需要标明股东结构/筹码集中度报告"),
    ("summary", r"^##\s*(?:\d+[.、]\s*)?摘要", "缺少摘要"),
    ("count", r"^##\s*(?:\d+[.、]\s*)?股东户数", "缺少股东户数趋势章节"),
    ("concentration", r"^##\s*(?:\d+[.、]\s*)?前十大", "缺少前十大集中度章节"),
    ("float", r"^##\s*(?:\d+[.、]\s*)?自由流通", "缺少自由流通占比章节"),
    ("direction", r"^##\s*(?:\d+[.、]\s*)?筹码集中方向", "缺少筹码集中方向章节"),
    ("pledge", r"^##\s*(?:\d+[.、]\s*)?大股东(质押|质押/冻结)", "缺少大股东质押/冻结章节"),
    ("risk", r"^##\s*(?:\d+[.、]\s*)?风险提示", "缺少风险提示章节"),
    ("data_notes", r"^##\s*(?:\d+[.、]\s*)?数据说明", "缺少数据说明章节"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 500:
        issues.append("报告内容过短，可能不是完整股东结构报告")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    if not re.search(r"(数据来源|来源接口|使用接口|get_holder_count|get_top_holders|get_share_float|Pandadata)", text):
        issues.append("缺少数据来源或来源接口说明")

    # Caliber label: flow vs total must be declared for top-holder ratios.
    if not re.search(r"(流通口径|总股本口径|hold_percent_float|hold_percent_total|口径)", text):
        issues.append("缺少集中度口径说明：前十大占比须注明流通口径/总股本口径")

    # Disclosure frequency / lag caveat.
    if not re.search(r"(披露|季度|滞后|截止日|end_date|定期报告)", text):
        issues.append("缺少披露频率/滞后说明：户数与占比为定期披露且滞后于期末")

    # Period labeling.
    if not re.search(r"(回溯|期数|披露期|截止日|环比|趋势)", text):
        issues.append("缺少披露期/回溯期/环比说明")

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
