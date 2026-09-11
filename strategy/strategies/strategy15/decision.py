"""策略十五决策：因子1；F23/F24 日线止盈；震荡开 F22；F25 为 30m 叠加元数据。"""

from __future__ import annotations

from strategy.close_momentum import rebuy_signal
from strategy.core.context import Decision, MarketContext
from strategy.core.protocols import StrategySpec
from strategy.ladder_tp import resolve_ladder_tp_policy
from strategy.m30_chop import M30ChopParams, advisory_levels
from strategy.open_break import TICK_SIZE, ceil_to_tick
from strategy.strategies._factor26_decision import Factor26Decision
from strategy.strategies.strategy15.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy15Decision(Factor26Decision):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def _policy(self, ctx: MarketContext):
        meta = ctx.meta or {}
        return resolve_ladder_tp_policy(
            max_height=meta.get("mkt_max_height"),
            ladder_score=meta.get("mkt_ladder_score"),
            lianban=meta.get("mkt_lianban"),
        )

    def _factor25_params(self) -> M30ChopParams:
        binding = self.binding("factor25")
        raw = binding.merged_params() if binding is not None else {}
        return M30ChopParams(
            stop_confirm_bars=int(raw.get("stop_confirm_bars") or 2),
            trail_arm_pct=float(raw.get("trail_arm_pct") or 0.12),
            trail_giveback_pct=float(raw.get("trail_giveback_pct") or 0.05),
            reclaim_band=float(raw.get("reclaim_band") or 0.015),
            reclaim_premium_max=float(raw.get("reclaim_premium_max") or 0.015),
            reclaim_horizon=int(raw.get("reclaim_horizon") or 8),
        )

    def _use_factor25(self, ctx: MarketContext) -> bool:
        """震荡/常规梯度启用 F25；高潮关接回时一并提示关闭 30m 回补。"""
        binding = self.binding("factor25")
        if binding is None or not binding.enabled:
            return False
        return bool(self._policy(ctx).use_factor22)

    def _factor22_rebuy(self, ctx: MarketContext, *, stop_px: float, buy_px: float) -> Decision | None:
        if not self._policy(ctx).use_factor22:
            return None
        # 有 30m 回补窗时，日线 F22 让位（由回测/盯盘 F25 处理）
        if self._use_factor25(ctx) and (ctx.meta or {}).get("m30_reclaim_active"):
            return None
        binding = self.binding("factor22")
        if binding is None or not binding.enabled:
            return None
        params = binding.merged_params()
        out = rebuy_signal(
            open_px=float(ctx.open),
            high_px=float(ctx.high),
            low_px=float(ctx.low),
            close_px=float(ctx.price),
            bounce_pct=float(params.get("bounce_pct") or 0.01),
            candle=str(params.get("candle") or "any"),  # type: ignore[arg-type]
            mode=str(params.get("mode") or "close"),  # type: ignore[arg-type]
            tick_ceil=lambda p: ceil_to_tick(p, TICK_SIZE),
        )
        if not out.get("ok") or out.get("fill_px") is None:
            return None
        return Decision.buy(
            float(out["fill_px"]),
            reason=f"梯度允许·收盘动量再买 {out.get('reason')}",
            factor_id="factor22",
            buy_price=buy_px,
            stop_price=stop_px,
            tags=("rebuy", "factor22", "factor24"),
            thr=out.get("thr"),
        )

    def decide(self, ctx: MarketContext) -> Decision:
        policy = self._policy(ctx)
        binding = self.binding("factor1")
        if binding is None:
            return Decision.hold("策略十五未绑定因子1")
        levels = self.levels_for(binding, ctx)
        buy_px = float(levels.get("buy") or 0)
        stop_px = float(levels.get("stop") or 0)
        f25_on = self._use_factor25(ctx)
        f25p = self._factor25_params()
        cost = float(ctx.entry_price or 0) if ctx.has_position else 0.0
        sell_anchor = (ctx.meta or {}).get("m30_sell_px")
        try:
            sell_f = float(sell_anchor) if sell_anchor is not None else None
        except (TypeError, ValueError):
            sell_f = None
        extra = {
            "buy_price": buy_px,
            "stop_price": stop_px,
            "tp_pct": policy.tp_pct,
            "use_factor22": policy.use_factor22,
            "use_factor25": f25_on,
            "regime": policy.regime,
            "factor25": advisory_levels(
                cost=cost or None,
                stop_px=stop_px or None,
                sell_px=sell_f,
                params=f25p,
            ),
        }

        if ctx.has_position and not ctx.t_plus_one:
            if cost > 0 and not bool(ctx.meta.get("tp_half_done")):
                # 震荡启用 F25 时：日线固定 % 止盈让位给 30m trail（见回测引擎）
                if not f25_on:
                    tp_px = ceil_to_tick(cost * (1.0 + policy.tp_pct), TICK_SIZE)
                    if float(ctx.high) + 1e-12 >= tp_px:
                        qty = float(ctx.position_qty)
                        sell_qty = max(0.0, qty * float(policy.reduce_ratio))
                        return Decision.sell(
                            tp_px,
                            reason=f"因子23/24 止盈减半 @{tp_px:.2f}（目标{policy.tp_pct:.0%}）",
                            factor_id="factor23",
                            qty=sell_qty if sell_qty > 0 else None,
                            tags=("take_profit", "half", policy.tp_style),
                            **extra,
                        )
                else:
                    arm_px = ceil_to_tick(cost * (1.0 + f25p.trail_arm_pct), TICK_SIZE)
                    extra["trail_arm_px"] = arm_px

        d = super().decide(ctx)
        meta = dict(d.meta)
        meta.update(extra)
        meta["policy_reason"] = policy.reason
        if f25_on:
            meta["factor25_note"] = (
                "震荡·F25：止损需 30m 收盘确认；动态半仓；止损后差不多价回补"
            )
        return Decision(
            action=d.action,
            reason=d.reason,
            price=d.price,
            size_mode=d.size_mode,
            size_value=d.size_value,
            factor_id=d.factor_id,
            meta=meta,
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy15Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy15Decision(bindings=bindings)
