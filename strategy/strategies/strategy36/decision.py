"""策略三十六决策：科技成长空仓避险决策引擎。

当因子36触发空仓时：
- 对科技池（创业板、科创板、深市科技票）保持现金观望（屏蔽买入开仓）；
- 对已有科技持仓标的，若满足卖出条件或T+1已解禁，则建议避险平仓规避成长风格深幅杀跌；
- 处于多头正常区间时，按基准策略执行。
"""

from __future__ import annotations

from typing import Any

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import FactorBinding
from strategy.factors.factor36 import evaluate_tech_cash_gate
from strategy.strategies.strategy36.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy36Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def __init__(self, bindings: tuple[FactorBinding, ...] = FACTOR_BINDINGS, **kwargs: Any) -> None:
        super().__init__(bindings=bindings)

    def decide(self, ctx: MarketContext) -> Decision:
        close_px = float(ctx.close) if ctx.close is not None else 0.0

        # 从上下文提取科技指数与广度指标
        macro = getattr(ctx, "macro", {}) or {}
        cyb_close = float(macro.get("cyb_close", macro.get("index_close", close_px)))
        cyb_ma20 = float(macro.get("cyb_ma20", cyb_close))
        cyb_ma60 = float(macro.get("cyb_ma60", cyb_close))
        sz_close = float(macro["sz_close"]) if macro.get("sz_close") is not None else None
        sz_ma60 = float(macro["sz_ma60"]) if macro.get("sz_ma60") is not None else None
        kc_close = float(macro["kc_close"]) if macro.get("kc_close") is not None else None
        kc_ma60 = float(macro["kc_ma60"]) if macro.get("kc_ma60") is not None else None

        tech_breadth = float(macro.get("tech_breadth_ma20", macro.get("market_breadth_ma20", 0.5)))
        tech_new_low = float(macro.get("tech_new_low_ratio", 0.0))
        current_cash_state = bool(macro.get("current_tech_cash_state", False))

        gate = evaluate_tech_cash_gate(
            cyb_close=cyb_close,
            cyb_ma20=cyb_ma20,
            cyb_ma60=cyb_ma60,
            sz_close=sz_close,
            sz_ma60=sz_ma60,
            kc_close=kc_close,
            kc_ma60=kc_ma60,
            tech_breadth_ma20=tech_breadth,
            tech_new_low_ratio=tech_new_low,
            current_cash_state=current_cash_state,
        )

        is_cash = gate["is_cash"]
        reason = gate["reason"]

        # 判断标的是否属于科技池 (创业板 300/301, 科创板 688, 或深市科技标的)
        symbol = str(ctx.meta.get("symbol") or getattr(ctx, "symbol", "") or "")
        is_tech_stock = symbol.startswith(("300", "301", "688")) or bool(macro.get("is_tech_sector", False))

        if is_cash:
            if ctx.has_position:
                if ctx.t_plus_one:
                    return Decision.hold(f"科技空仓预警生效·T+1锁定中: {reason}", tags=("t1", "factor36", "tech_defensive"))
                return Decision.sell(
                    close_px,
                    reason=f"因子36科技避险清仓: {reason}",
                    factor_id="factor36",
                    tags=("factor36", "risk_off", "tech_cash_gate"),
                )
            return Decision.hold(f"科技空仓防守观望: {reason}", tags=("factor36", "tech_defensive"))

        # 非科技空仓期，允许正常运作
        return Decision.hold("科技成长板块处于多头通道，正常运作", tags=("factor36", "tech_risk_on"))


def create_decision_engine(**kwargs: Any) -> Strategy36Decision:
    return Strategy36Decision(**kwargs)


__all__ = ["Strategy36Decision", "create_decision_engine"]
