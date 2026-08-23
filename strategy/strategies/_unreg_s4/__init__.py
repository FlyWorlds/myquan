"""策略四：因子1 滚动12月 Top3 池 × 池内反转。"""

from __future__ import annotations

from typing import Any

from strategy.strategies._common import compose_rules
from strategy.strategies._unreg_s4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies._unreg_s4.decision import Strategy4Decision, create_decision_engine
from strategy.strategies._unreg_s4.portfolio import (
    PORTFOLIO_DEFAULTS,
    current_picks,
    run_strategy4_portfolio,
)


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    extra = f"""
【策略四】
  · 建池：因子1 开盘突破 · 滚动12月评分 → Top{PORTFOLIO_DEFAULTS['pool_n']}（次月生效）
  · 交易：仅池内 {PORTFOLIO_DEFAULTS['kind']}(n={PORTFOLIO_DEFAULTS['n']})
          日选 Top{PORTFOLIO_DEFAULTS['top_k']}，持有 {PORTFOLIO_DEFAULTS['hold_days']} 日
  · 执行：收盘信号 → 次日开盘；袖套轮动
  · 股票池：中证1000主板（与挖参口径一致）
""".strip()
    return f"{head}\n\n{extra}\n"


def _run(cfg: Any = None, **kwargs: Any):
    overrides: dict[str, Any] = dict(PORTFOLIO_DEFAULTS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    if bool(overrides.pop("picks_only", False)):
        return current_picks(**overrides)
    return run_strategy4_portfolio(**overrides)


__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "PORTFOLIO_DEFAULTS",
    "Strategy4Decision",
    "create_decision_engine",
    "run_strategy4_portfolio",
    "current_picks",
]
