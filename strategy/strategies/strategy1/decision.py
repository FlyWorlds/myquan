"""援军战法 · 决策层：因子1信号 → 买 / 卖 / 持有；因子22 止损后收盘动量再买。"""

from __future__ import annotations

from strategy.close_momentum import rebuy_signal
from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.open_break import TICK_SIZE, ceil_to_tick
from strategy.strategies.strategy1.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy1Decision(BaseDecisionEngine):
    """
    决策规则（与 open_break / OpenBreak3 一致）：
    - 空仓 + 因子允许 + high 触买点 → buy（因子1）
    - 有仓 + 非 T+1 + low 触止损 → sell（因子1）；若同日收盘动量成立 → buy（因子22，隐含先止损再买）
    - 空仓 + 当日已止损（meta.stop_sold_today）+ 收盘动量 → buy（因子22）
    - 其余 → hold
    触发用 high/low，不用现价（避免漏触发）。
    """

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def _factor22_rebuy(self, ctx: MarketContext, *, stop_px: float, buy_px: float) -> Decision | None:
        binding = self.binding("factor22")
        if binding is None or not binding.enabled:
            return None
        params = binding.merged_params()
        bounce_pct = float(params.get("bounce_pct") or 0.01)
        candle = str(params.get("candle") or "any")
        mode = str(params.get("mode") or "close")
        out = rebuy_signal(
            open_px=float(ctx.open),
            high_px=float(ctx.high),
            low_px=float(ctx.low),
            close_px=float(ctx.price),
            bounce_pct=bounce_pct,
            candle=candle,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            tick_ceil=lambda p: ceil_to_tick(p, TICK_SIZE),
        )
        if not out.get("ok") or out.get("fill_px") is None:
            return None
        return Decision.buy(
            float(out["fill_px"]),
            reason=f"收盘动量再买 {out.get('reason')}",
            factor_id="factor22",
            buy_price=buy_px,
            stop_price=stop_px,
            tags=("rebuy", "factor22", "close_momentum"),
            thr=out.get("thr"),
        )

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

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1 禁卖",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("t1",),
                )
            if low <= stop_px + 1e-12:
                rebuy = self._factor22_rebuy(ctx, stop_px=stop_px, buy_px=buy_px)
                if rebuy is not None:
                    # 同 bar：先止损再买；调用方见 tags 含 rebuy 时先清仓再按 fill 开仓
                    meta = dict(rebuy.meta)
                    meta["implied_stop_then_rebuy"] = True
                    meta["stop_px"] = stop_px
                    return Decision(
                        action="buy",
                        reason=rebuy.reason,
                        price=rebuy.price,
                        size_mode=rebuy.size_mode,
                        size_value=rebuy.size_value,
                        factor_id="factor22",
                        meta=meta,
                    )
                return Decision.sell(
                    stop_px,
                    reason=f"触止损 {stop_px:.2f}",
                    factor_id="factor1",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("stop", "factor1"),
                )
            return Decision.hold(
                "持仓未触止损",
                buy_price=buy_px,
                stop_price=stop_px,
            )

        # 空仓：当日已止损 → 优先因子22
        if bool(ctx.meta.get("stop_sold_today")):
            rebuy = self._factor22_rebuy(ctx, stop_px=stop_px, buy_px=buy_px)
            if rebuy is not None:
                return rebuy
            return Decision.hold(
                "今日已止损·收盘动量未触发",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("stop_sold", "factor22"),
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
