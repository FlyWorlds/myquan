"""因子25：30 分钟震荡减磨损（确认止损 + 动态半仓止盈 + 卖飞回补）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.m30_chop import (
    DEFAULT_RECLAIM_BAND,
    DEFAULT_RECLAIM_HORIZON,
    DEFAULT_RECLAIM_PREMIUM_MAX,
    DEFAULT_STOP_CONFIRM_BARS,
    DEFAULT_TRAIL_ARM_PCT,
    DEFAULT_TRAIL_GIVEBACK_PCT,
    DEFAULT_TRAIL_REDUCE_RATIO,
    M30ChopParams,
    M30ChopState,
    advisory_levels,
    f1_entry_allowed,
    reclaim_signal,
    rules_text,
    stop_confirm_signal,
    trail_signal,
)

FACTOR_ID = "factor25"
FACTOR_NAME = "因子25-30分钟震荡减磨损"


def _params_from_kw(kw: dict[str, Any]) -> M30ChopParams:
    return M30ChopParams(
        stop_confirm_bars=int(kw.get("stop_confirm_bars", DEFAULT_STOP_CONFIRM_BARS)),
        reclaim_band=float(kw.get("reclaim_band", DEFAULT_RECLAIM_BAND)),
        reclaim_premium_max=float(
            kw.get("reclaim_premium_max", DEFAULT_RECLAIM_PREMIUM_MAX)
        ),
        reclaim_horizon=int(kw.get("reclaim_horizon", DEFAULT_RECLAIM_HORIZON)),
        reclaim_require_yang=bool(kw.get("reclaim_require_yang", True)),
        reclaim_break_prior_high=bool(kw.get("reclaim_break_prior_high", True)),
        reclaim_require_above_day_stop=bool(
            kw.get("reclaim_require_above_day_stop", True)
        ),
        reclaim_enabled=bool(kw.get("reclaim_enabled", True)),
        trail_arm_pct=float(kw.get("trail_arm_pct", DEFAULT_TRAIL_ARM_PCT)),
        trail_giveback_pct=float(
            kw.get("trail_giveback_pct", DEFAULT_TRAIL_GIVEBACK_PCT)
        ),
        trail_reduce_ratio=float(
            kw.get("trail_reduce_ratio", DEFAULT_TRAIL_REDUCE_RATIO)
        ),
        suppress_f1_during_reclaim=bool(kw.get("suppress_f1_during_reclaim", True)),
        no_f1_if_day_low_hit_stop=bool(kw.get("no_f1_if_day_low_hit_stop", True)),
    )


def signal(**kw: Any) -> dict[str, Any]:
    """单棒判定（需调用方维护 M30ChopState，或传入 state 字典字段）。

    常用关键字：open/high/low/close、stop_px、cost、has_position、t_plus_one、
    action 候选 ``trail|stop|reclaim|f1_gate|advisory``（默认按优先级全检）。
    """
    params = _params_from_kw(kw)
    state = kw.get("state")
    if not isinstance(state, M30ChopState):
        state = M30ChopState(
            below_stop_streak=int(kw.get("below_stop_streak") or 0),
            peak_high=float(kw.get("peak_high") or 0),
            tp_half_done=bool(kw.get("tp_half_done") or False),
            sell_px=(
                float(kw["sell_px"])
                if kw.get("sell_px") is not None
                else None
            ),
            sell_qty=float(kw.get("sell_qty") or 0),
            reclaim_left=int(kw.get("reclaim_left") or 0),
            sell_reason=kw.get("sell_reason"),
            prior_bar_high=(
                float(kw["prior_bar_high"])
                if kw.get("prior_bar_high") is not None
                else None
            ),
            day_low_hit_stop=bool(kw.get("day_low_hit_stop") or False),
        )

    open_px = float(kw.get("open") or kw.get("open_px") or 0)
    high = float(kw.get("high") or kw.get("high_px") or 0)
    low = float(kw.get("low") or kw.get("low_px") or 0)
    close = float(kw.get("close") or kw.get("close_px") or 0)
    stop_px = float(kw.get("stop_px") or 0)
    cost = float(kw.get("cost") or kw.get("entry_price") or 0)
    has_pos = bool(kw.get("has_position") or False)
    t1 = bool(kw.get("t_plus_one") or False)
    mode = str(kw.get("action") or kw.get("mode") or "all")

    out: dict[str, Any] = {
        "kind": "m30_chop",
        "params": params.as_dict(),
        "advisory": advisory_levels(
            cost=cost or None,
            stop_px=stop_px or None,
            sell_px=state.sell_px,
            params=params,
        ),
    }

    if mode in ("advisory",):
        return out

    if has_pos and mode in ("all", "trail"):
        out["trail"] = trail_signal(
            high=high,
            close=close,
            cost=cost,
            state=state,
            params=params,
            t_plus_one=t1,
        )
    if has_pos and mode in ("all", "stop"):
        out["stop"] = stop_confirm_signal(
            close=close,
            stop_px=stop_px,
            state=state,
            params=params,
            t_plus_one=t1,
        )
    if (not has_pos) and mode in ("all", "reclaim"):
        out["reclaim"] = reclaim_signal(
            open_px=open_px,
            high=high,
            low=low,
            close=close,
            day_stop_px=stop_px,
            state=state,
            params=params,
        )
    if mode in ("all", "f1_gate"):
        out["f1_gate"] = f1_entry_allowed(state, params, has_position=has_pos)

    out["state"] = {
        "below_stop_streak": state.below_stop_streak,
        "peak_high": state.peak_high,
        "tp_half_done": state.tp_half_done,
        "sell_px": state.sell_px,
        "sell_qty": state.sell_qty,
        "reclaim_left": state.reclaim_left,
        "sell_reason": state.sell_reason,
        "day_low_hit_stop": state.day_low_hit_stop,
    }
    return out


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "30m 确认止损 + 峰值回撤半仓止盈 + 止损后差不多价回补；"
        "震荡市叠在策略十五/因子1 上；见 docs/FACTOR25.md"
    ),
    rules_text=rules_text(),
    implemented=True,
    signal=signal,
    meta={
        "kind": "m30_chop",
        "category": "take_profit",
        "overlay": "factor1_m30",
        "status": "research",
        "backtest": "backtest/strategy15_m30_chop/",
        "default_trail_arm_pct": DEFAULT_TRAIL_ARM_PCT,
        "default_reclaim_band": DEFAULT_RECLAIM_BAND,
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "signal"]
