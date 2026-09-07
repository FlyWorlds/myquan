"""援军战法 · 决策层：因子26（回落波止损）买卖；因子22 止损后收盘动量再买。"""

from __future__ import annotations

from typing import Any

from strategy.close_momentum import rebuy_signal
from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.factor_registry import get_factor
from strategy.core.protocols import FactorBinding
from strategy.open_break import TICK_SIZE, ceil_to_tick
from strategy.strategies.strategy1.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME

_PRIMARY = "factor26"


class Strategy1Decision(BaseDecisionEngine):
    """
    决策规则：
    - 空仓 + 因子允许 + high 触开盘买点或攻击波买点 → buy（因子26）
    - 有仓 + 非 T+1 + low 触回落波止损（分时最高×(1−pct)）→ sell；
      若同日收盘动量成立 → buy（因子22，隐含先止损再买）
    - 空仓 + 当日已止损（meta.stop_sold_today）+ 收盘动量 → buy（因子22）
    - 其余 → hold
    """

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def levels_for(self, binding: FactorBinding, ctx: MarketContext) -> dict[str, Any]:
        factor = get_factor(binding.factor_id)
        if factor.levels is None:
            return {}
        params = binding.merged_params()
        entry_pct = float(params.get("entry_pct", params.get("threshold_pct", 0.025)))
        pullback = float(
            params.get("pullback_pct", params.get("stop_pct", entry_pct))
        )
        tick = float(params.get("tick", 0.01))
        raw = factor.levels(
            ctx.open,
            entry_pct=entry_pct,
            stop_pct=pullback,
            pullback_pct=pullback,
            high_px=float(ctx.high),
            low_px=float(ctx.low),
            tick=tick,
        )
        out = dict(raw or {})
        if "buy" not in out and "buy_trigger" in out:
            out["buy"] = out["buy_trigger"]
        return out

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
        binding = self.binding(_PRIMARY) or self.binding("factor1")
        if binding is None:
            return Decision.hold("援军战法未绑定因子26/因子1")

        levels = self.levels_for(binding, ctx)
        buy_px = float(levels.get("buy") or 0)
        stop_px = float(levels.get("stop") or 0)
        if buy_px <= 0 or stop_px <= 0:
            return Decision.hold("开盘价无效，无法计算买卖点")

        high = float(ctx.high)
        low = float(ctx.low)
        fid = binding.factor_id

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
                    reason=f"回落波止损 {stop_px:.2f}（高{high:.2f}）",
                    factor_id=fid,
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("stop", fid, "pullback_wave"),
                )
            return Decision.hold(
                "持有",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("hold",),
            )

        # 空仓：当日已止损 → 优先因子22
        if bool((ctx.meta or {}).get("stop_sold_today")):
            rebuy = self._factor22_rebuy(ctx, stop_px=stop_px, buy_px=buy_px)
            if rebuy is not None:
                meta = dict(rebuy.meta)
                meta["stop_sold"] = True
                return Decision(
                    action="buy",
                    reason=rebuy.reason,
                    price=rebuy.price,
                    size_mode=rebuy.size_mode,
                    size_value=rebuy.size_value,
                    factor_id="factor22",
                    meta=meta,
                )

        if not self.factor_allowed(binding, ctx):
            return Decision.hold(
                "前日过滤未过",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("filter",),
            )
        open_buy = float(levels.get("open_buy") or buy_px)
        attack_buy = float(levels.get("attack_buy") or 0)
        hit_open = high + 1e-12 >= open_buy
        hit_attack = attack_buy > 0 and (high + 1e-12 >= attack_buy)
        if hit_open or hit_attack:
            if hit_attack and (not hit_open or attack_buy <= open_buy + 1e-12):
                fill = attack_buy
                reason = f"攻击波买点 {fill:.2f}（低{low:.2f}）"
                tags = ("entry", fid, "attack_wave")
            else:
                fill = open_buy
                reason = f"开盘突破买点 {fill:.2f}"
                tags = ("entry", fid, "open_break")
            return Decision.buy(
                fill,
                reason=reason,
                factor_id=fid,
                buy_price=fill,
                stop_price=stop_px,
                tags=tags,
            )
        return Decision.hold(
            "空仓观望",
            buy_price=buy_px,
            stop_price=stop_px,
            tags=("flat",),
        )


def create_decision_engine(spec=None) -> Strategy1Decision:  # noqa: ANN001
    del spec
    return Strategy1Decision(FACTOR_BINDINGS)
