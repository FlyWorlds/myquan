"""因子26 决策内核：开盘阈值买 + 多层止盈卖 + 因子22 收盘动量再买。

不含具体 strategyN。策略一/十六各自注入 bindings 与策略编号。
盘中实盘仍以盯盘 1 分钟路径为准；本引擎默认用日线/快照，ctx.meta 可带 path_hit_*。
"""

from __future__ import annotations

from typing import Any

from strategy.close_momentum import rebuy_signal
from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.factor_registry import get_factor
from strategy.core.protocols import FactorBinding
from strategy.open_break import TICK_SIZE, ceil_to_tick

_PRIMARY = "factor26"


class Factor26Decision(BaseDecisionEngine):
    """因子26/22 共用决策；strategy_id / strategy_name 由子类或构造注入。"""

    def levels_for(self, binding: FactorBinding, ctx: MarketContext) -> dict[str, Any]:
        factor = get_factor(binding.factor_id)
        if factor.levels is None:
            return {}
        params = binding.merged_params()
        entry_pct = float(params.get("entry_pct", params.get("threshold_pct", 0.025)))
        pullback = float(params.get("pullback_pct", params.get("stop_pct", entry_pct)))
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
        label = self.strategy_name or self.strategy_id or "因子26"
        if binding is None:
            return Decision.hold(f"{label} 未绑定因子26/因子1")

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
            # 无 1m 路径时不用全日 low 成交：同 bar 高低次序未知，会把「先高后低」
            # 误判成已触卖。盯盘不走本引擎；本引擎只在明确 path_hit_stop 时卖。
            path_stop = False
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
                    meta_out = dict(rebuy.meta)
                    meta_out["implied_stop_then_rebuy"] = True
                    meta_out["stop_px"] = stop_px
                    return Decision(
                        action="buy",
                        reason=rebuy.reason,
                        price=rebuy.price,
                        size_mode=rebuy.size_mode,
                        size_value=rebuy.size_value,
                        factor_id="factor22",
                        meta=meta_out,
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

        if bool((ctx.meta or {}).get("stop_sold_today")):
            rebuy = None
            if (ctx.meta or {}).get("close_confirmed") is not False:
                rebuy = self._factor22_rebuy(ctx, stop_px=stop_px, buy_px=buy_px)
            if rebuy is not None:
                meta_out = dict(rebuy.meta)
                meta_out["stop_sold"] = True
                return Decision(
                    action="buy",
                    reason=rebuy.reason,
                    price=rebuy.price,
                    size_mode=rebuy.size_mode,
                    size_value=rebuy.size_value,
                    factor_id="factor22",
                    meta=meta_out,
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
