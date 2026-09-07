"""因子26 · 回落波阈值止损：买同因子1，止损=当日分时最高×(1−pullback)。

买入：开盘突破 ceil(open×(1+entry_pct))，过滤同因子1。
止损：floor(当日最高×(1−pullback_pct))；最高抬升则止损上移（分时回落波）。
默认 entry/pullback 均 ±2.5%。

日线回放用全日 high 估止损，同 bar high/low 有次序偏差；盯盘用实时 high 为准。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    NEAR_FACTOR_PCT,
    TICK_SIZE,
    bar_shape,
    entry_filters_ok,
    entry_trigger_price,
    floor_to_tick,
    is_t1_buy_day,
    prev_day_allows_entry,
    should_block_entry_by_yang,
)

DEFAULT_ENTRY_PCT = DEFAULT_PCT
DEFAULT_PULLBACK_PCT = DEFAULT_PCT

STRATEGY_RULES = """
================================================================================
  因子26 · 回落波阈值止损（买同开盘突破，止损跟分时最高回落）
================================================================================

【空仓 · 买入】与因子1相同
  触发：当日最高价 >= ceil(开盘价 × (1 + 阈值))，按触发价限价买入。
  过滤：前日阴/小阳；禁双阳跨日≥5%；T+1。

【有仓 · 卖出】
  止损价 = floor(当日分时最高价 × (1 − 回落阈值))
  · 最高抬升 → 止损上移（回落波）
  · 当日最低价 <= 止损价 → 按止损价全清
  · 买入当日不可卖（除非 t0）

【默认】entry / pullback 均为 2.5%。
【说明】盯盘用实时最高；日线回测用全日 high（同 bar 有次序偏差）。
================================================================================
"""


def pullback_stop_price(
    day_high: float,
    *,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
    tick: float = TICK_SIZE,
) -> float:
    """分时最高回落阈值止损价。"""
    h = float(day_high)
    if h <= 0:
        return 0.0
    return floor_to_tick(h * (1.0 - float(pullback_pct)), tick)


def strategy_levels(
    open_px: float,
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float | None = None,
    pullback_pct: float | None = None,
    high_px: float | None = None,
    tick: float = TICK_SIZE,
    **_extra: Any,
) -> dict[str, float]:
    """buy 锚定开盘；stop 锚定当日最高（缺省用开盘，等价开盘回落）。"""
    pb = float(
        pullback_pct
        if pullback_pct is not None
        else (stop_pct if stop_pct is not None else DEFAULT_PULLBACK_PCT)
    )
    anchor = float(high_px) if high_px is not None and float(high_px) > 0 else float(open_px)
    buy = entry_trigger_price(open_px, entry_pct=entry_pct, tick=tick)
    stop = pullback_stop_price(anchor, pullback_pct=pb, tick=tick)
    return {
        "buy_trigger": buy,
        "buy": buy,
        "stop": stop,
        "day_high": anchor,
        "pullback_pct": pb,
    }


def rules_text(
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    pullback_pct: float = DEFAULT_PULLBACK_PCT,
) -> str:
    return (
        f"因子26-回落波阈值止损\n"
        f"  · 买：开盘+{entry_pct*100:.1f}%（过滤同因子1）\n"
        f"  · 卖：分时最高回落 {pullback_pct*100:.1f}% 全清；最高抬升止损上移\n"
        f"  · 默认绑策略一（替代因子1 止损形态）"
    )


def strategy_signal(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    last_px: float,
    session: str,
    buy_trigger: float | None = None,
    stop_px: float | None = None,
    qty: int,
    buy_time: str | None,
    vs_open_pts: float,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float = DEFAULT_PULLBACK_PCT,
    pullback_pct: float | None = None,
    px_digits: int = 2,
    t0: bool = False,
    near_points: float = NEAR_FACTOR_PCT,
    allow_entry: bool = True,
    tick: float = TICK_SIZE,
) -> dict[str, Any]:
    """盯盘信号：买同开盘突破；止损跟分时最高回落。"""
    pb = float(pullback_pct if pullback_pct is not None else stop_pct)
    lv = strategy_levels(
        open_px,
        entry_pct=entry_pct,
        pullback_pct=pb,
        high_px=high_px,
        tick=tick,
    )
    buy_trigger = float(buy_trigger if buy_trigger is not None else lv["buy_trigger"])
    stop_px = float(stop_px if stop_px is not None else lv["stop"])

    holding = qty > 0
    hit_buy = bool(allow_entry) and (high_px + 1e-12 >= buy_trigger)
    hit_stop = low_px <= stop_px + 1e-12
    t1_lock = holding and (not t0) and is_t1_buy_day(buy_time, session)
    buy_lvl = entry_pct * 100.0
    stop_lvl = -pb * 100.0
    pf = f"{{:.{px_digits}f}}"

    def _dist(ref_px: float) -> tuple[float | None, float | None]:
        if float(ref_px) <= 0:
            return None, None
        dpx = round(float(last_px) - float(ref_px), px_digits)
        dpct = round((float(last_px) / float(ref_px) - 1.0) * 100.0, 2)
        return dpx, dpct

    dist_buy_px, dist_buy_pct = _dist(buy_trigger)
    dist_stop_px, dist_stop_pct = _dist(stop_px)
    near_buy_band = (
        dist_buy_pct is not None and abs(float(dist_buy_pct)) <= near_points + 1e-12
    )
    near_stop_band = (
        dist_stop_pct is not None and abs(float(dist_stop_pct)) <= near_points + 1e-12
    )

    base: dict[str, Any] = {
        "near_buy": False,
        "near_stop": False,
        "pending_buy": False,
        "pending_sell": False,
        "alert": "",
        "bg_class": "",
        "建议挂单": None,
        "挂单说明": "",
        "形态": bar_shape(open_px, last_px),
        "t1_lock": t1_lock,
        "dist_buy": round(vs_open_pts - buy_lvl, 2),
        "dist_stop": round(vs_open_pts - stop_lvl, 2),
        "距买点价差": dist_buy_px,
        "距买点%": dist_buy_pct,
        "距止损价差": dist_stop_px,
        "距止损%": dist_stop_pct,
        "side": "sell" if holding else "buy",
        "因子侧": "卖出" if holding else "买入",
        "因子价": None,
        "因子触发": "不可用",
        "持仓状态": "待买入",
        "hit_buy": hit_buy,
        "hit_stop": hit_stop,
        "actionable": False,
        "near_pct": near_points,
        "stop_kind": "pullback_wave",
        "day_high": float(high_px),
        "pullback_pct": pb,
    }

    def _finish(out: dict[str, Any]) -> dict[str, Any]:
        sell = out["side"] == "sell"
        if sell:
            out["因子价"] = round(float(stop_px), px_digits)
            out["距因子价差"] = dist_stop_px
            out["距因子%"] = dist_stop_pct
            if out.get("t1_lock"):
                out["因子触发"] = "不可用"
                out["建议挂单"] = None
                out["actionable"] = False
            else:
                out["actionable"] = True
                alert = str(out.get("alert") or "")
                if out.get("hit_stop") or "已触止损" in alert:
                    out["因子触发"] = "已触发"
                elif out.get("near_stop") or "将止损" in alert:
                    out["因子触发"] = "接近"
                else:
                    out["因子触发"] = "未触发"
                if out.get("建议挂单") is not None and out.get("因子价") is not None:
                    out["建议挂单"] = round(float(out["因子价"]), px_digits)
        else:
            out["因子价"] = round(float(buy_trigger), px_digits)
            out["距因子价差"] = dist_buy_px
            out["距因子%"] = dist_buy_pct
            out["actionable"] = True
            if out.get("hit_buy"):
                out["因子触发"] = "已触发"
            elif out.get("near_buy") or out.get("pending_buy"):
                out["因子触发"] = "接近"
            else:
                out["因子触发"] = "未触发"
            if out.get("建议挂单") is not None:
                out["建议挂单"] = round(float(buy_trigger), px_digits)
        if sell:
            if out.get("t1_lock"):
                out["持仓状态"] = "持有"
            elif bool(out.get("pending_sell")):
                out["持仓状态"] = "待卖出"
            else:
                out["持仓状态"] = "持有"
        else:
            out["持仓状态"] = "待买入" if bool(out.get("pending_buy")) else "空仓"
        pos_st = str(out.get("持仓状态") or "")
        if pos_st == "待卖出":
            out["因子侧"] = "卖出"
        elif pos_st == "待买入":
            out["因子侧"] = "买入"
        elif pos_st == "持有":
            out["因子侧"] = "持有"
        else:
            out["因子侧"] = "空仓"
        if holding:
            trig_side, trig_px = "买入", round(float(buy_trigger), px_digits)
            next_side, next_px = "卖出", round(float(stop_px), px_digits)
        else:
            trig_side, trig_px = "卖出", round(float(stop_px), px_digits)
            next_side, next_px = "买入", round(float(buy_trigger), px_digits)

        def _signed(px: float, side: str) -> tuple[float | None, float | None]:
            dpx, dpct = _dist(px)
            if dpx is None or dpct is None:
                return None, None
            if side == "卖出":
                return round(-dpx, px_digits), round(-dpct, 2)
            return dpx, dpct

        d_trig_px, d_trig_pct = _signed(trig_px, trig_side)
        d_next_px, d_next_pct = _signed(next_px, next_side)
        out["已触发因子侧"] = trig_side
        out["已触发因子价"] = trig_px
        out["未触发因子侧"] = next_side
        out["未触发因子价"] = next_px
        out["距已触发价差"] = d_trig_px
        out["距已触发%"] = d_trig_pct
        out["距未触发价差"] = d_next_px
        out["距未触发%"] = d_next_pct
        out["距因子价差"] = d_next_px
        out["距因子%"] = d_next_pct
        return out

    if holding:
        if t1_lock:
            base.update(
                {
                    "alert": "持有·T+1",
                    "bg_class": "status-hold",
                    "挂单说明": "",
                    "建议挂单": None,
                    "pending_sell": False,
                    "near_stop": False,
                    "actionable": False,
                }
            )
            return _finish(base)
        base["actionable"] = True
        if hit_stop:
            base.update(
                {
                    "pending_sell": True,
                    "alert": "已触止损",
                    "bg_class": "warn-sell",
                    "建议挂单": stop_px,
                    "挂单说明": (
                        f"回落波止损@{pf.format(stop_px)}"
                        f"（高{pf.format(float(high_px))}回落{pb*100:.1f}%）"
                    ),
                }
            )
            return _finish(base)
        if near_stop_band:
            base.update(
                {
                    "near_stop": True,
                    "pending_sell": True,
                    "alert": "将止损",
                    "bg_class": "warn-sell",
                    "建议挂单": stop_px,
                    "挂单说明": (
                        f"距回落波止损在{near_points:g}%内"
                        f"（高{pf.format(float(high_px))}→止{pf.format(stop_px)}）"
                    ),
                }
            )
            return _finish(base)
        base.update(
            {
                "alert": "持有",
                "bg_class": "status-hold",
                "建议挂单": stop_px,
                "挂单说明": (
                    f"回落波止损=分时最高×(1-{pb*100:.1f}%)"
                    f"@{pf.format(stop_px)}"
                ),
                "pending_sell": False,
            }
        )
        return _finish(base)

    if hit_buy:
        base.update(
            {
                "pending_buy": True,
                "alert": "已触买",
                "bg_class": "warn-buy",
                "建议挂单": buy_trigger,
                "挂单说明": f"限价买@{pf.format(buy_trigger)}",
            }
        )
        return _finish(base)
    if allow_entry and near_buy_band:
        base.update(
            {
                "near_buy": True,
                "pending_buy": True,
                "alert": "将买入",
                "bg_class": "warn-buy",
                "建议挂单": buy_trigger,
                "挂单说明": (
                    f"距买点在{near_points:g}%内（现差{dist_buy_pct:+.2f}%），"
                    f"预埋限价买@{pf.format(buy_trigger)}"
                ),
            }
        )
        return _finish(base)
    base.update(
        {
            "alert": "空仓",
            "bg_class": "status-flat",
            "建议挂单": buy_trigger if allow_entry else None,
            "挂单说明": "" if allow_entry else "前日过滤未过，今日不买",
        }
    )
    return _finish(base)


def replay_last_factor_triggers(
    daily: pd.DataFrame,
    *,
    entry_pct: float = DEFAULT_ENTRY_PCT,
    stop_pct: float = DEFAULT_PULLBACK_PCT,
    pullback_pct: float | None = None,
    tick: float = TICK_SIZE,
    prev_entry_mode: str = "yin_or_small_yang",
    limit_down_pct: float = 0.10,
) -> dict[str, Any]:
    """日线简化重放（止损用全日 high；同 bar 有次序偏差）。"""
    del limit_down_pct  # 接口兼容
    pb = float(pullback_pct if pullback_pct is not None else stop_pct)
    out: dict[str, Any] = {
        "last_buy_date": None,
        "last_buy_px": None,
        "last_sell_date": None,
        "last_sell_px": None,
        "holding": False,
        "last_trigger_date": None,
        "last_trigger_px": None,
        "last_trigger_side": None,
    }
    if daily is None or daily.empty:
        return out
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    if len(df) < 2:
        return out

    holding = False
    buy_day: pd.Timestamp | None = None
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2] if i >= 2 else None
        day = pd.Timestamp(row["date"]).normalize()
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        if o <= 0:
            continue
        buy_px = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
        stop_px = pullback_stop_price(h, pullback_pct=pb, tick=tick)
        allows = prev_day_allows_entry(
            float(prev["open"]),
            float(prev["close"]),
            prev_small_yang_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
        )
        blocked = False
        if prev2 is not None:
            blocked = should_block_entry_by_yang(
                float(prev2["open"]),
                float(prev2["close"]),
                float(prev["open"]),
                float(prev["close"]),
                ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
            )
        if holding:
            sess = str(day.date())
            buy_time = str(buy_day.date()) if buy_day is not None else None
            if not is_t1_buy_day(buy_time, sess) and l <= stop_px + 1e-12:
                out["last_sell_date"] = day
                out["last_sell_px"] = stop_px
                out["last_trigger_date"] = day
                out["last_trigger_px"] = stop_px
                out["last_trigger_side"] = "sell"
                holding = False
                buy_day = None
            continue
        if allows and (not blocked) and h + 1e-12 >= buy_px:
            out["last_buy_date"] = day
            out["last_buy_px"] = buy_px
            out["last_trigger_date"] = day
            out["last_trigger_px"] = buy_px
            out["last_trigger_side"] = "buy"
            holding = True
            buy_day = day

    out["holding"] = holding
    return out


__all__ = [
    "DEFAULT_ENTRY_PCT",
    "DEFAULT_PULLBACK_PCT",
    "STRATEGY_RULES",
    "pullback_stop_price",
    "strategy_levels",
    "strategy_signal",
    "replay_last_factor_triggers",
    "rules_text",
    "entry_filters_ok",
]
