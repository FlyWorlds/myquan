"""因子3：动量因子（旧动量组合脚本 / 单票时序仍可用）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.momentum import DEFAULT_KIND, DEFAULT_PARAMS, momentum_rules_text

FACTOR_ID = "factor3"
FACTOR_NAME = "因子3·动量"

_RULES = (
    momentum_rules_text(DEFAULT_KIND, DEFAULT_PARAMS)
    + "\n\n"
    + """================================================================================
  组合用法（旧动量截面脚本，已归档 _unreg_s5）
================================================================================
  · 股票池：中证1000主板；收盘截面打分 → 次日开盘 · 袖套持有
  · 默认参数见 strategy.strategies._unreg_s5.portfolio.PORTFOLIO_DEFAULTS
  · 说明：A股中小盘截面上短期反转通常优于趋势动量；单票择时仍可用 dist_hl
  · 旧对照：因子3选票 + 开盘买 + 因子1止损，见
    strategy.strategies._unreg_s6.portfolio.run_f3_select_f1_stop_portfolio
  · 推荐组合：因子1前置（阴/小阳+禁双阳跨日）→ 因子3选股 → 因子1突破买/止损，见
    strategy.f3_f1_combo.run_f3_f1_combo
    对照脚本：backtest/compare_f3_f1_precond.py
================================================================================
""".strip()
)

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "动量族因子：组合默认截面反转/动量打分；"
        "单票时可 dist_hl 时序择时（收盘确认、次日开盘）"
    ),
    rules_text=_RULES,
    implemented=True,
    meta={
        "kind": "momentum",
        "standalone": True,
        "single_default_kind": DEFAULT_KIND,
        "single_default_params": {
            "n": DEFAULT_PARAMS["n"],
            "enter": DEFAULT_PARAMS["enter"],
            "exit": DEFAULT_PARAMS["exit"],
        },
        "mine_window": "2020+",
        "akquant_sharpe_kaicheng": 1.536,
    },
)

register_factor(SPEC, replace=True)
