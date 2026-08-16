#!/usr/bin/env python3
"""validate_report.py — deterministic structural checker for a Global Macro Trend
Strategy results explainer (``results_explainer.md``).

Stdlib only. Verifies the produced report has the required sections, the strategy
contract fields, the performance metrics, a look-ahead / cost caveat, a data-source +
window label, and the mandatory non-investment-advice disclaimer. Exits non-zero on a
bad report so it can gate a workflow.

Usage:
    python validate_report.py results_explainer.md

Exit codes: 0 = OK, 1 = report has issues, 2 = file not found.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# (key, regex, human message) — searched case-insensitively, multiline.
REQUIRED_SECTIONS = [
    ("title", r"^#\s+.*(strategy|策略|trend|macro|回测)", "一级标题需标明策略/回测报告"),
    ("contract", r"(策略契约|strategy\s*contract|universe|标的池|信号)", "缺少策略契约/信号说明"),
    ("rules", r"(进出场|entry|exit|再平衡|rebalance|阈值)", "缺少进出场/再平衡规则说明"),
    ("sizing", r"(仓位|position\s*sizing|vol[-_ ]?target|波动率目标|fixed[-_ ]?fraction|固定比例)",
     "缺少仓位管理说明（vol-target / fixed-fraction）"),
    ("risk", r"(风控|风险上限|risk\s*limit|止损|stop|回撤守门|max[-_ ]?weight)", "缺少风控上限说明"),
    ("results", r"(结果|绩效|performance|指标)", "缺少结果/绩效章节"),
]

# Performance metrics that must be reported.
REQUIRED_METRICS = [
    ("cagr", r"(CAGR|年化收益)", "缺少 CAGR / 年化收益"),
    ("sharpe", r"Sharpe", "缺少 Sharpe"),
    ("maxdd", r"(max\s*draw\s*down|最大回撤|maxDD|max_drawdown)", "缺少最大回撤 maxDD"),
    ("turnover", r"(turnover|换手)", "缺少换手 turnover"),
]


def validate(text: str) -> list[str]:
    issues: list[str] = []

    if len(text.strip()) < 300:
        issues.append("报告内容过短，可能不是完整的策略结果说明")

    for _key, pattern, message in REQUIRED_SECTIONS:
        if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(message)

    for _key, pattern, message in REQUIRED_METRICS:
        if not re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(message)

    # Look-ahead avoidance must be stated (signal at t, trade at t+1).
    if not re.search(r"(t\+1|t\s*\+\s*1|次日|下一根|前视|look[-_ ]?ahead|执行滞后)", text, re.IGNORECASE):
        issues.append("缺少前视规避说明：信号 t 生成、t+1 成交")

    # Costs / slippage caveat.
    if not re.search(r"(手续费|滑点|成本|cost|slippage|bps)", text, re.IGNORECASE):
        issues.append("缺少成本/滑点说明（bps）")

    # Data source + window label.
    if not re.search(r"(数据来源|来源|Yahoo|stooq|Pandadata|data\s*source)", text, re.IGNORECASE):
        issues.append("缺少数据来源说明（Yahoo / stooq / Pandadata / 用户信号）")
    if not re.search(r"(窗口|区间|样本|start|end|日期|\d{4})", text, re.IGNORECASE):
        issues.append("缺少样本窗口/区间标注")

    # Overfit / out-of-sample note.
    if not re.search(r"(过拟合|样本外|hold[-_ ]?out|out[-_ ]?of[-_ ]?sample|示意)", text, re.IGNORECASE):
        issues.append("缺少过拟合/样本外提醒：结果为示意性历史统计")

    # Research-only, no live trading.
    if not re.search(r"(仅研究|仅供研究|不下单|research\s*only|不接券商|no\s*live)", text, re.IGNORECASE):
        issues.append("缺少‘仅研究、不下单’边界声明")

    # Mandatory disclaimer.
    if not re.search(r"不构成任何投资建议", text) and not re.search(
        r"not\s+(?:constitute\s+)?investment\s+advice", text, re.IGNORECASE
    ):
        issues.append("缺少免责声明：不构成任何投资建议 / does not constitute investment advice")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to the Markdown results explainer")
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
