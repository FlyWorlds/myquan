"""援军战法 · 决策层：因子26（浮盈回落一半）买卖；因子22 止损后收盘动量再买。

盘中实盘对齐以 `holdingStocks/index.py` 的 1 分钟路径为准（买/卖均 path-dependent）。
本引擎默认用日线/快照 OHLC，仅供回测粗算；若 ctx.meta 带 path_hit_buy / path_hit_stop
则尊重分钟路径，避免全日高低假触。
"""

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
    - 有仓 + 非 T+1 + low 触浮盈回落一半卖价 → sell；
      若同日收盘动量成立 → buy（因子22，隐含先止损再买）
    - 空仓 + 当日已卖出：仍可按因子26 再买；因子22 收盘动量为额外路径
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
        giveback = float(params.get("giveback_ratio", 0.5))
        tick = float(params.get("tick", 0.01))
        cost = None
        if ctx.entry_price is not None and float(ctx.entry_price) > 0:
            cost = float(ctx.entry_price)
        meta = ctx.meta or {}
        peak = 0.0
        path_peak = meta.get("path_peak_high")
        meta_peak = meta.get("peak_high")
        if path_peak is not None:
            try:
                peak = float(path_peak)
            except (TypeError, ValueError):
                peak = 0.0
        elif ctx.has_position:
            # 有仓卖价：禁止用当日快照 high 当峰值（与盯盘 seed 规则一致）
            if cost is not None:
                peak = cost
            if meta_peak is not None:
                try:
                    peak = max(peak, float(meta_peak))
                except (TypeError, ValueError):
                    pass
        else:
            peak = float(ctx.high)
            if meta_peak is not None:
                try:
                    peak = max(peak, float(meta_peak))
                except (TypeError, ValueError):
                    pass
        if cost is not None:
            peak = max(peak, cost)
        high_for_lv = peak if (ctx.has_position and peak > 0) else float(ctx.high)
        raw = factor.levels(
            ctx.open,
            entry_pct=entry_pct,
            stop_pct=pullback,
            pullback_pct=pullback,
            giveback_ratio=giveback,
            high_px=high_for_lv,
            low_px=float(ctx.low),
            cost_px=cost,
            peak_high=peak if peak > 0 else None,
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
        meta = ctx.meta or {}
        if meta.get("path_hit_stop") is not None:
            path_stop = bool(meta.get("path_hit_stop"))
        else:
            path_stop = low <= stop_px + 1e-12
        if meta.get("path_hit_buy") is not None:
            path_buy = bool(meta.get("path_hit_buy"))
        else:
            path_buy = None

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1 禁卖",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("t1",),
                )
            if path_stop:
                rebuy = None
                if (ctx.meta or {}).get("close_confirmed") is not False:
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
                    reason=f"浮盈回落一半 {stop_px:.2f}（高{high:.2f}）",
                    factor_id=fid,
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("stop", fid, "half_gain"),
                )
            return Decision.hold(
                "持有",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("hold",),
            )

        # 空仓：当日已卖出 → 优先尝试因子22；未成立则继续走因子26 开盘阈值再买
        if bool((ctx.meta or {}).get("stop_sold_today")):
            rebuy = None
            if (ctx.meta or {}).get("close_confirmed") is not False:
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
            # 门禁打开：不 return，落入下方因子26 再买

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
        if path_buy is False:
            return Decision.hold(
                "空仓观望",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("flat", "path"),
            )
        hit_entry = bool(path_buy) if path_buy is not None else (hit_open or hit_attack)
        if hit_entry:
            fill_meta = meta.get("path_buy_px")
            if fill_meta is not None:
                fill = float(fill_meta)
                kind = str(meta.get("path_buy_kind") or "")
                reason = (
                    f"攻击波买点 {fill:.2f}"
                    if kind == "attack"
                    else f"开盘突破买点 {fill:.2f}"
                )
                tags = ("entry", fid, kind or "path")
            elif hit_attack and (not hit_open or attack_buy <= open_buy + 1e-12):
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
