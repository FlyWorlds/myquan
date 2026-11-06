"""策略三十五决策：多维空仓避险决策引擎。

当因子35触发空仓时：
- 对空仓标的保持现金观望（不发出买入信号）；
- 对已有持仓标的，若满足卖出条件或T+1已解禁，则建议清仓规避系统性下杀；
- 处于多头正常区间时，按基准策略执行。
"""

from __future__ import annotations

from typing import Any

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import FactorBinding
from strategy.factors.factor35 import evaluate_cash_gate
from strategy.strategies.strategy35.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy35Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def __init__(self, bindings: tuple[FactorBinding, ...] = FACTOR_BINDINGS, **kwargs: Any) -> None:
        super().__init__(bindings=bindings)

    def decide(self, ctx: MarketContext) -> Decision:
        close_px = float(ctx.close) if ctx.close is not None else 0.0
        
        # 从上下文提取大盘指标
        macro = getattr(ctx, "macro", {}) or {}
        index_close = float(macro.get("index_close", close_px))
        ma20 = float(macro.get("index_ma20", index_close))
        ma60 = float(macro.get("index_ma60", index_close))
        breadth = float(macro.get("market_breadth_ma20", 0.5))
        new_low_ratio = float(macro.get("new_low_ratio", 0.0))
        current_cash_state = bool(macro.get("current_cash_state", False))

        gate = evaluate_cash_gate(
            close_price=index_close,
            ma20=ma20,
            ma60=ma60,
            market_breadth_ma20=breadth,
            new_low_ratio=new_low_ratio,
            current_cash_state=current_cash_state,
        )

        is_cash = gate["is_cash"]
        reason = gate["reason"]

        if is_cash:
            if ctx.has_position:
                if ctx.t_plus_one:
                    return Decision.hold(f"空仓预警生效·T+1锁定中: {reason}", tags=("t1", "factor35", "cash_defensive"))
                return Decision.sell(
                    close_px,
                    reason=f"因子35避险清仓: {reason}",
                    factor_id="factor35",
                    tags=("factor35", "risk_off", "cash_gate"),
                )
            return Decision.hold(f"空仓防守观望: {reason}", tags=("factor35", "cash_defensive"))

        # 非空仓期，允许正常持仓或顺势持有
        return Decision.hold("大盘处于多头通道，正常运作", tags=("factor35", "risk_on"))


def create_decision_engine(**kwargs: Any) -> Strategy35Decision:
    return Strategy35Decision(**kwargs)


__all__ = ["Strategy35Decision", "create_decision_engine"]
