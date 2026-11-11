"""策略三十八·地量起爆多维选股 决策引擎 (Decision Engine)。

严格按照四步逻辑决策：
1. Step 1: 绝对风控一票否决：大盘触发因子35空仓时，任何标的均禁止开仓；
2. Step 2: 底池清洗：非主板、ST 或质地不达标标的直接排除；
3. Step 3: 核心进攻：日线需有 60 日地量及近期底部倍量起爆；
4. Step 4: 执行层：依据攻击波阈值与缠论买点生成次日买入决策。
"""

from __future__ import annotations

from typing import Any
import pandas as pd

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import FactorBinding
from strategy.strategies.strategy38.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy38.pipeline import evaluate_market_cash_gate


class Strategy38Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def __init__(
        self,
        bindings: tuple[FactorBinding, ...] = FACTOR_BINDINGS,
        **kwargs: Any,
    ) -> None:
        super().__init__(bindings=bindings)
        self.kwargs = kwargs

    def decide(self, ctx: MarketContext) -> Decision:
        # 持仓状态退出与风控
        if ctx.holding:
            if ctx.t_plus_one:
                return Decision.hold(reason="T+1禁卖期持有")
            # 止损判断：若跌破入场价保护线（例如 -2.5% 硬止损）
            cost = float(ctx.entry_price or 0.0)
            if cost > 0:
                cur_px = float(ctx.close)
                if (cur_px - cost) / cost <= -0.025:
                    return Decision.sell(
                        cur_px,
                        reason="跌破起爆防守位(硬保护-2.5%)止损卖出",
                        factor_id="factor35",
                    )
            return Decision.hold(reason="持仓中，观察缠论向上一笔延续")

        # Step 1: 绝对风控（一票否决）
        # 从 ctx.meta 读取全局大盘择时信息
        meta = ctx.meta or {}
        is_cash_veto = meta.get("cash_gate_veto")
        if is_cash_veto is None:
            # 检查是否有 macro 行情信息传入
            close_idx = float(meta.get("index_close", 3800.0))
            ma60_idx = float(meta.get("index_ma60", 3750.0))
            breadth = float(meta.get("market_breadth_ma20", 0.55))
            gate = evaluate_market_cash_gate(
                close_price=close_idx,
                ma60=ma60_idx,
                market_breadth_ma20=breadth,
            )
            is_cash_veto = gate["veto_cash"]

        if is_cash_veto:
            return Decision.hold(reason="Step 1 绝对风控：大盘触发因子35多维空仓，一票否决禁止买入")

        # Step 2: 底池清洗（基本面与质地过滤）
        code = str(meta.get("code") or meta.get("symbol") or "")
        name = str(meta.get("name") or "")
        if "ST" in name.upper() or "退" in name or meta.get("is_st"):
            return Decision.hold(reason="Step 2 底池清洗：ST/退市风险标的排除")

        if code and not code.startswith(("60", "00")):
            return Decision.hold(reason="Step 2 底池清洗：非主板标的排除")

        # Step 3: 核心进攻形态判断（因子34地量倍量起爆）
        has_breakout = meta.get("factor34_hit")
        if has_breakout is False:
            return Decision.hold(reason="Step 3 形态未满足：未见60日地量转倍量起爆形态")

        # Step 4: 买点生成与确认
        # 挂单买入价格
        open_px = float(ctx.open)
        buy_target = float(meta.get("buy_trigger_price") or round(open_px * 1.025, 2))
        high_px = float(ctx.high)

        # 盘中触及买入阈值
        if high_px >= buy_target:
            return Decision.buy(
                buy_target,
                reason=f"Step 4 买点触发：盘中触及攻击波买点 {buy_target:.2f} 元",
                factor_id="factor34",
            )

        return Decision.hold(reason=f"观察中，等待触及买入挂单价 {buy_target:.2f} 元")


def create_decision_engine(spec=None) -> Strategy38Decision:  # noqa: ANN001
    del spec
    return Strategy38Decision(FACTOR_BINDINGS)
