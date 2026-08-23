"""策略六 · 因子绑定：因子6 组合动量 ETF 轮动。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.etf_combo_momentum import DEFAULT_PARAMS, DEFAULT_UNIVERSE

STRATEGY_ID = "strategy6"
STRATEGY_NAME = "组合动量ETF轮动"

_p = DEFAULT_PARAMS
_univ = "、".join(code[2:] for code, _ in DEFAULT_UNIVERSE)

FACTOR_BINDINGS = (
    bind_factor(
        "factor6",
        role="both",
        label="因子6·组合动量ETF轮动",
        n=_p["n"],
        n2=_p["n2"],
        w=_p["w"],
        top_k=_p["top_k"],
        hold_days=_p["hold_days"],
        min_score=_p["min_score"],
        defensive=_p["defensive"],
        filter_desc=(
            f"宽基ETF（{_univ}）收盘组合动量 "
            f"ROC({_p['n']})+{_p['w']:g}×ROC({_p['n2']}) "
            f"Top{_p['top_k']} → 次日开盘轮入；"
            f"最高分<= {_p['min_score']} 空仓；每{_p['hold_days']}日再平衡；"
            "持仓分数跌破门槛下一开盘风控空仓"
        ),
    ),
)
