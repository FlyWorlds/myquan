"""策略二研究报告落盘。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def write_research_report(
    output_dir: Path,
    *,
    journal: pd.DataFrame,
    accepted: list[str],
    diagnostics: dict[str, Any],
    data_label: str,
    point_in_time_universe: bool,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = diagnostics.get("test_stats", {})
    bootstrap = diagnostics.get("bootstrap", {})
    accepted_text = "、".join(accepted) if accepted else "无（使用未排序基线）"
    status_counts = (
        journal["status"].value_counts().to_dict() if "status" in journal else {}
    )
    p05 = float(bootstrap.get("sharpe_p05", 0) or 0)
    p95 = float(bootstrap.get("sharpe_p95", 0) or 0)
    lines = [
        "# 策略二·缠论因子研究报告",
        "",
        f"- 数据：{data_label}",
        f"- 历史时点成分：{'是' if point_in_time_universe else '否'}",
        "- 规则：日线交易；30分钟只判断小转大一买/二买；日线二卖或三卖退出",
        "- 成交：日线收盘信号，下一交易日开盘；A股T+1",
        f"- 搜索试验：{diagnostics.get('search_trials', len(journal))}",
        f"- 接受因子：{accepted_text}",
        f"- 试验状态：{json.dumps(status_counts, ensure_ascii=False)}",
        "",
        "## 候选日志",
        "",
        "| 因子 | 状态 | 原因 | 验证Sharpe | 验证主分 | 相关 |",
        "|---|---|---|---|---|---|",
    ]
    if not journal.empty:
        for _, row in journal.iterrows():
            factor = row.get("factor", "")
            status = row.get("status", "")
            reason = row.get("reason", "")
            sharpe = float(row.get("validation_sharpe", 0) or 0)
            score = float(row.get("validation_score", 0) or 0)
            corr = float(row.get("max_abs_correlation", 0) or 0)
            lines.append(
                f"| {factor} | {status} | {reason} | {sharpe:.3f} | {score:.3f} | {corr:.2f} |"
            )
    lines += [
        "",
        "## 冻结样本外结果",
        "",
        f"- 年化收益：{_percent(stats.get('annual_return'))}",
        f"- 成本后 Sharpe：{float(stats.get('sharpe', 0) or 0):.3f}",
        f"- 最大回撤：{_percent(stats.get('max_drawdown'))}",
        f"- 年化换手：{float(stats.get('annual_turnover', 0) or 0):.2f}",
        f"- Bootstrap Sharpe 90%区间：[{p05:.3f}, {p95:.3f}]",
        f"- Deflated Sharpe 概率：{float(diagnostics.get('deflated_sharpe_probability', 0) or 0):.3f}",
        f"- PBO估计：{float(diagnostics.get('pbo_estimate', 1) or 1):.3f}",
        f"- 研究等级：{diagnostics.get('decision', 'reject')}",
        "",
        "## 限制",
        "",
    ]
    extra_limits: list[str] = []
    if "合成" in data_label:
        extra_limits.append(
            "本结果来自 CZSC 合成随机路径，只验证流水线；不能当成 A 股缠论选股绩效"
        )
        extra_limits.append(
            "demo 跳过结构特征，bi_snr / bi_slope 记为 CRASH/missing_column"
        )
    extra_limits.extend(str(item) for item in diagnostics.get("limitations", []))
    seen: set[str] = set()
    for item in extra_limits:
        if item and item not in seen:
            seen.add(item)
            lines.append(f"- {item}")
    lines += [
        "",
        "本报告仅供量化研究与教育用途，不构成投资建议、自动交易指令或收益保证。",
    ]
    target = output_dir / "research_report.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


__all__ = ["write_research_report"]
