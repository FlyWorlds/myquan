"""援军战法 · 决策层：因子1信号 → 买 / 卖 / 持有。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.open_break import DEFAULT_PCT, is_small_yin
from strategy.strategies.strategy1.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy1Decision(BaseDecisionEngine):
    """
    决策规则（与 open_break / OpenBreak3 一致）：
    - 空仓 + 因子允许 + high 触买点 → buy
    - 有仓 + 非 T+1 + low 触止损 → sell
    - 有仓 + 非 T+1 + 连续小阴（可选）→ sell@收盘
    - 其余 → hold
    触发用 high/low，不用现价（避免漏触发）。
    """

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        binding = self.binding("factor1")
        if binding is None:
            return Decision.hold("援军战法未绑定因子1")

        levels = self.levels_for(binding, ctx)
        buy_px = float(levels.get("buy") or 0)
        stop_px = float(levels.get("stop") or 0)
        if buy_px <= 0 or stop_px <= 0:
            return Decision.hold("开盘价无效，无法计算买卖点")

        high = float(ctx.high)
        low = float(ctx.low)
        stop_pct = float(
            binding.params.get("stop_pct")
            or binding.params.get("entry_pct")
            or DEFAULT_PCT
        )
        sy_need = int(binding.params.get("consec_small_yin_exit") or 0)

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1 禁卖",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("t1",),
                )
            if low <= stop_px + 1e-12:
                return Decision.sell(
                    stop_px,
                    reason=f"触止损 {stop_px:.2f}",
                    factor_id="factor1",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("stop", "factor1"),
                )
            # N=2：今日小阴 + 前日小阴 → 收盘离场（回测持仓连阴的简化口径）
            if (
                sy_need >= 2
                and ctx.prev_open is not None
                and ctx.prev_close is not None
            ):
                today_sy = is_small_yin(
                    ctx.open, ctx.close, max_drop_pct=stop_pct
                )
                prev_sy = is_small_yin(
                    float(ctx.prev_open),
                    float(ctx.prev_close),
                    max_drop_pct=stop_pct,
                )
                if today_sy and prev_sy:
                    return Decision.sell(
                        float(ctx.close),
                        reason=f"连续小阴离场(实体跌幅≤{stop_pct*100:.1f}%)",
                        factor_id="factor1",
                        buy_price=buy_px,
                        stop_price=stop_px,
                        tags=("small_yin", "factor1"),
                    )
            return Decision.hold(
                "持仓未触止损",
                buy_price=buy_px,
                stop_price=stop_px,
            )

        if not self.factor_allowed(binding, ctx):
            return Decision.hold(
                "因子过滤未通过（前日/前前日条件）",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("filter",),
            )
        if high + 1e-12 >= buy_px:
            return Decision.buy(
                buy_px,
                reason=f"触买点 {buy_px:.2f}",
                factor_id="factor1",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("entry", "factor1"),
            )
        return Decision.hold(
            "空仓未触买点",
            buy_price=buy_px,
            stop_price=stop_px,
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy1Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy1Decision(bindings=bindings)
