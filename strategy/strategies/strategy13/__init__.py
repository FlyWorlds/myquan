"""策略十三：纯因子1 ETF walk-forward 选票（研究）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy13.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy13.decision import (
    Strategy13Decision,
    create_decision_engine,
)

_ETF_WF = Path(__file__).resolve().parent / "etf_wf"
_TOP10_PATH = _ETF_WF / "top10_pool.json"


def load_top10_pool() -> list[dict[str, Any]]:
    if not _TOP10_PATH.exists():
        return []
    return json.loads(_TOP10_PATH.read_text(encoding="utf-8"))


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    pool = load_top10_pool()
    codes = "、".join(f"{p['code']} {p['name']}" for p in pool[:10]) or "（尚未运行 run_etf_wf.py）"
    extra = f"""
----- ETF 规则 -----
1. 仅因子1：开盘突破买入 / 开盘止损卖出；强制 T+1
2. 宇宙：walk-forward OOS 综合分 Top10（见 etf_wf/top10_pool.json）
3. 选参协议：2023前上市 IS=2023-2025 / OOS=2025-今；2025上市 IS=2025 / OOS=2026-今
4. 当前 Top10：{codes}
研究用途，非投资建议。
"""
    return head + "\n" + extra.strip()


def run_strategy13(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
) -> tuple[Any, Any]:
    del cfg, show_report, force_daily_refresh
    from strategy.strategies.strategy13.run_etf_wf import main as run_wf

    run_wf()
    summary_path = _ETF_WF / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if verbose:
            print(json.dumps(summary.get("top10", []), ensure_ascii=False, indent=2))
        return summary, load_top10_pool()
    return None, []


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="纯因子1 做 ETF；walk-forward 选参后 OOS 综合分取 Top10",
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy13,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s13", "etf_f1", "因子1ETF", "策略十三"),
        implemented=True,
        meta={
            "default": False,
            "mode": "etf_factor1_wf",
            "research_only": True,
            "factors": ("factor1",),
            "backtest_cli": "strategy/strategies/strategy13/run_etf_wf.py",
            "pool_path": str(_TOP10_PATH),
        },
    )


register_strategy(_bind(), replace=True)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy13Decision",
    "create_decision_engine",
    "run_strategy13",
    "load_top10_pool",
]
