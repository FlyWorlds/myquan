#!/usr/bin/env python3
"""策略十二·情绪门控开盘突破：因子18 恐慌日 vs 策略一基线（研究，非投资建议）。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.backtest import metric  # noqa: E402
from strategy.config import KAICHENG, TIANTONG  # noqa: E402
from strategy.runner import run_open_break  # noqa: E402
from strategy.strategies.strategy12.emotion_gate import panic_halt_by_date  # noqa: E402

OUT = _ROOT / "backtest" / "strategy12_emotion_gate"


def _row(result: Any, *, label: str, gated: bool) -> dict[str, Any]:
    m = result.metrics_df
    n_trades = metric(m, "closed_trade_count")
    return {
        "label": label,
        "gated": gated,
        "total_return_pct": float(metric(m, "total_return_pct")),
        "max_drawdown_pct": float(metric(m, "max_drawdown_pct")),
        "sharpe_ratio": float(metric(m, "sharpe_ratio")),
        "win_rate": float(metric(m, "win_rate")),
        "n_trades": None if n_trades != n_trades else int(n_trades),
        "entry_pct": 0.025,
    }


def run_compare(*, verbose: bool = True) -> dict[str, Any]:
    halt = panic_halt_by_date()
    panic_n = sum(1 for v in halt.values() if v)
    cfgs = (("kaicheng", KAICHENG), ("tiantong", TIANTONG))
    detail: list[dict[str, Any]] = []
    for key, cfg in cfgs:
        base_res, _ = run_open_break(cfg, show_report=False, verbose=False)
        gated_cfg = replace(cfg, emotion_halt_by_date=halt)
        gated_res, _ = run_open_break(gated_cfg, show_report=False, verbose=False)
        b = _row(base_res, label=key, gated=False)
        g = _row(gated_res, label=key, gated=True)
        detail.extend([b, g])
        if verbose:
            print(
                f"{cfg.symbol_name}: 基线 {b['total_return_pct']:.1f}% / "
                f"门控 {g['total_return_pct']:.1f}%  "
                f"回撤 {b['max_drawdown_pct']:.1f}% → {g['max_drawdown_pct']:.1f}%  "
                f"笔数 {b['n_trades']} → {g['n_trades']}"
            )
    gated_kaicheng = next(r for r in detail if r["label"] == "kaicheng" and r.get("gated"))
    web_row = {
        "entry_pct": 0.025,
        "total_return_pct": gated_kaicheng["total_return_pct"],
        "max_drawdown_pct": gated_kaicheng["max_drawdown_pct"],
        "sharpe_ratio": gated_kaicheng["sharpe_ratio"],
        "win_rate": gated_kaicheng["win_rate"],
        "n_trades": gated_kaicheng["n_trades"],
    }
    summary = {
        "strategy": "strategy12",
        "panic_days": panic_n,
        "universe": "单票对照：凯盛 / 天通",
        "interval": "各 BacktestConfig.start_date → 今",
        "note": "研究用途，非投资建议。门控=因子18 恐慌日禁止新开仓。",
        "detail": detail,
        "web": [web_row],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary["web"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "summary_detail.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(summary)
    if verbose:
        print(f"恐慌日 {panic_n}  · 产物 {OUT}")
    return summary


def _write_report(summary: dict[str, Any]) -> None:
    lines = [
        "# 策略十二·情绪门控开盘突破",
        "",
        "> 研究用途，非投资建议。因子18 恐慌日（中证1000 低开开盘跌停≥4）禁止新开仓；",
        "> 执行仍用因子1 ±2.5%、仅止损、T+1；因子2 只预警。",
        "",
        f"- 恐慌日样本：{summary.get('panic_days')} 天（情绪缓存 `backtest/strategy9_limit_down_emotion/`）",
        f"- 对照标的：{summary.get('universe')}",
        "",
        "## 单票对照（费用后）",
        "",
        "| 标的 | 模式 | 总收益 | 最大回撤 | 夏普 | 笔数 |",
        "|------|------|--------|----------|------|------|",
    ]
    name = {"kaicheng": "凯盛", "tiantong": "天通"}
    for r in summary.get("detail") or []:
        mode = "门控" if r.get("gated") else "基线(策略一)"
        n = r.get("n_trades")
        n_txt = "—" if n is None else str(n)
        lines.append(
            f"| {name.get(r['label'], r['label'])} | {mode} | "
            f"{r['total_return_pct']:.1f}% | {r['max_drawdown_pct']:.1f}% | "
            f"{r['sharpe_ratio']:.2f} | {n_txt} |"
        )
    lines += [
        "",
        "数字为单票独立回测，不是组合净值。基线=无情绪门控的因子1；门控=同一规则叠加因子18。",
        "",
        "**局限**：凯盛/天通 2020→2026 样本内，门控降低了累计收益（恐慌日仅约 10 天，"
        "跳过的开仓可能落在反弹段）。本组合是可挂载的风险开关，**不替换**策略一默认。",
        "",
        "## 复现",
        "",
        "```bash",
        "python backtest/strategy12_emotion_gate/run.py",
        "python -c \"from strategy import run_strategy12; run_strategy12()\"",
        "```",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="策略十二：因子18 恐慌门控 vs 策略一基线")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    run_compare(verbose=not args.quiet)


if __name__ == "__main__":
    main()
