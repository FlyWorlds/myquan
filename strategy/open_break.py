"""相对开盘 ±pct 策略核心（回测与盯盘共用）。

规则摘要（默认 ±2.5%）：
  · 买入：high >= ceil(open×(1+entry_pct))，且前日形态过滤通过
  · 卖出（有仓，买入当日不卖）：
    1) 低开且 9:45 前未翻红（high<昨收）→ 9:45 价止损
    2) low <= floor(open×(1-stop_pct)) 止损
    3) 收盘 < 开盘 阴线卖
"""

from __future__ import annotations

import datetime as dt
import math
from datetime import datetime
from typing import Any

import pandas as pd

# --- 默认参数 ---
DEFAULT_PCT = 0.025
ENTRY_PCT = DEFAULT_PCT
STOP_PCT = DEFAULT_PCT
PREV_SMALL_YANG_PCT = 0.025
TICK_SIZE = 0.01
NEAR_POINTS = 1.0

GAP_DOWN_EXIT_HOUR = 9
GAP_DOWN_EXIT_MINUTE = 45
YIN_EXIT_HOUR = 14
YIN_EXIT_MINUTE = 55

REASON_STOP = "止损成交"
REASON_YIN = "阴线收盘卖"
REASON_GAP945 = "低开945未翻红"
EXIT_REASONS = (REASON_STOP, REASON_YIN, REASON_GAP945)


def ceil_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.ceil((float(px) - 1e-12) / tick) * tick, decimals)


def floor_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.floor((float(px) + 1e-12) / tick) * tick, decimals)


def entry_trigger_price(
    open_px: float,
    *,
    entry_pct: float = ENTRY_PCT,
    tick: float = TICK_SIZE,
) -> float:
    return ceil_to_tick(float(open_px) * (1.0 + entry_pct), tick)


def stop_trigger_price(
    open_px: float,
    *,
    stop_pct: float = STOP_PCT,
    tick: float = TICK_SIZE,
) -> float:
    return floor_to_tick(float(open_px) * (1.0 - stop_pct), tick)


def strategy_levels(
    open_px: float,
    *,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
) -> dict[str, float]:
    return {
        "buy_trigger": entry_trigger_price(open_px, entry_pct=entry_pct, tick=tick),
        "stop": stop_trigger_price(open_px, stop_pct=stop_pct, tick=tick),
    }


def is_yin(open_px: float, close_px: float) -> bool:
    return float(close_px) < float(open_px)


def is_yang(open_px: float, close_px: float) -> bool:
    return float(close_px) > float(open_px)


def bar_shape(open_px: float, last_px: float) -> str:
    if is_yang(open_px, last_px):
        return "阳"
    if is_yin(open_px, last_px):
        return "阴"
    return "十字"


def prev_day_allows_entry(
    prev_open: float,
    prev_close: float,
    *,
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT,
) -> bool:
    if prev_open <= 0:
        return False
    if prev_close <= prev_open:
        return True
    limit_px = prev_open * (1.0 + prev_small_yang_pct)
    return float(prev_close) < limit_px - 1e-8


def has_double_yang_before(
    prev2_open: float | None,
    prev2_close: float | None,
    prev_open: float | None,
    prev_close: float | None,
) -> bool:
    if None in (prev2_open, prev2_close, prev_open, prev_close):
        return False
    if prev2_open <= 0 or prev_open <= 0:
        return False
    return is_yang(prev2_open, prev2_close) and is_yang(prev_open, prev_close)


def is_t1_buy_day(buy_time: str | None, session: str) -> bool:
    if not buy_time:
        return False
    return str(buy_time)[:10] == str(session)[:10]


def is_yin_exit_window(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return (now.hour, now.minute) >= (YIN_EXIT_HOUR, YIN_EXIT_MINUTE)


def gap_down_flipped_red(morning_high: float, prev_close: float) -> bool:
    """9:45 前是否翻红：最高点 >= 昨收。"""
    return float(morning_high) + 1e-12 >= float(prev_close)


def is_gap_down_exit_window(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return (now.hour, now.minute) >= (GAP_DOWN_EXIT_HOUR, GAP_DOWN_EXIT_MINUTE)


def is_gap_down_945_window(now: datetime | None = None) -> bool:
    """兼容旧名。"""
    return is_gap_down_exit_window(now)


def eval_gap_down_945(
    *,
    open_px: float,
    prev_close: float | None,
    day_bars: pd.DataFrame | None,
    last_px: float,
    high_px: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """低开 + 9:45 前未翻红 → 止损。

    翻红：9:45 前 high >= 昨收。无分钟线时用当日 high_px 近似。
    """
    now = now or datetime.now()
    out: dict[str, Any] = {
        "active": False,
        "flipped": False,
        "should_exit": False,
        "exit_px": None,
        "morning_high": None,
    }
    if prev_close is None or float(prev_close) <= 0:
        return out
    prev_close = float(prev_close)
    open_px = float(open_px)
    if open_px + 1e-12 >= prev_close:
        return out
    out["active"] = True

    morning_high = float(open_px)
    exit_px = float(last_px)
    if day_bars is not None and not day_bars.empty:
        bars = day_bars.sort_values("ts")
        day0 = pd.Timestamp(bars.iloc[0]["ts"]).normalize()
        cutoff = day0 + pd.Timedelta(
            hours=GAP_DOWN_EXIT_HOUR, minutes=GAP_DOWN_EXIT_MINUTE
        )
        morning = bars[bars["ts"] <= cutoff]
        if not morning.empty:
            morning_high = float(morning["high"].max())
            bar_exit = morning[
                (morning["ts"].dt.hour == GAP_DOWN_EXIT_HOUR)
                & (morning["ts"].dt.minute == GAP_DOWN_EXIT_MINUTE)
            ]
            if not bar_exit.empty:
                exit_px = float(bar_exit.iloc[-1]["close"])
            elif is_gap_down_exit_window(now):
                exit_px = float(morning.iloc[-1]["close"])
    else:
        day_high = float(high_px) if high_px is not None else float(last_px)
        morning_high = max(float(open_px), day_high)

    out["morning_high"] = morning_high
    flipped = gap_down_flipped_red(morning_high, prev_close)
    out["flipped"] = flipped
    if flipped:
        return out
    if is_gap_down_exit_window(now):
        out["should_exit"] = True
        out["exit_px"] = exit_px
    return out


def build_gap_down_945_map(
    daily: pd.DataFrame,
    minute: pd.DataFrame | None = None,
) -> dict[str, dict[str, float | str]]:
    """回测用：预计算每个交易日是否触发低开 9:45 未翻红止损。"""
    daily = daily.copy()
    ts = pd.to_datetime(daily["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    else:
        ts = ts.dt.tz_convert("Asia/Shanghai")
    daily["day"] = ts.dt.strftime("%Y-%m-%d")
    daily["open"] = pd.to_numeric(daily["open"], errors="coerce")
    daily["high"] = pd.to_numeric(daily["high"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")

    by_day: dict[str, pd.DataFrame] = {}
    if minute is not None and not minute.empty:
        m = minute.copy()
        m["day"] = m["ts"].dt.strftime("%Y-%m-%d")
        for d, grp in m.groupby("day"):
            by_day[str(d)] = grp.sort_values("ts")

    out: dict[str, dict[str, float | str]] = {}
    for i in range(1, len(daily)):
        row = daily.iloc[i]
        prev_close = float(daily.iloc[i - 1]["close"])
        open_px = float(row["open"])
        day = str(row["day"])
        if prev_close <= 0 or open_px <= 0 or open_px + 1e-12 >= prev_close:
            continue

        day_min = by_day.get(day)
        if day_min is not None and not day_min.empty:
            cutoff = day_min["ts"].dt.normalize().iloc[0] + pd.Timedelta(
                hours=GAP_DOWN_EXIT_HOUR, minutes=GAP_DOWN_EXIT_MINUTE
            )
            morning = day_min[day_min["ts"] <= cutoff]
            if morning.empty:
                continue
            if gap_down_flipped_red(float(morning["high"].max()), prev_close):
                continue
            bar_exit = morning[
                morning["ts"].dt.time
                == dt.time(GAP_DOWN_EXIT_HOUR, GAP_DOWN_EXIT_MINUTE)
            ]
            if bar_exit.empty:
                bar_exit = morning.iloc[[-1]]
            out[day] = {
                "exit_px": float(bar_exit.iloc[-1]["close"]),
                "prev_close": prev_close,
                "open_px": open_px,
                "source": "1m",
            }
            continue

        day_high = float(row["high"])
        if gap_down_flipped_red(day_high, prev_close):
            continue
        out[day] = {
            "exit_px": open_px,
            "prev_close": prev_close,
            "open_px": open_px,
            "source": "daily_proxy",
        }
    return out


def strategy_signal(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    last_px: float,
    session: str,
    buy_trigger: float,
    stop_px: float,
    qty: int,
    buy_time: str | None,
    vs_open_pts: float,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    px_digits: int = 2,
    t0: bool = False,
    prev_close: float | None = None,
    day_bars: pd.DataFrame | None = None,
    near_points: float = NEAR_POINTS,
) -> dict[str, Any]:
    """盯盘：生成持有/翻转状态与挂单建议。"""
    holding = qty > 0
    hit_buy = high_px + 1e-12 >= buy_trigger
    hit_stop = low_px <= stop_px + 1e-12
    t1_lock = holding and (not t0) and is_t1_buy_day(buy_time, session)
    gap945 = eval_gap_down_945(
        open_px=open_px,
        prev_close=prev_close,
        day_bars=day_bars,
        last_px=last_px,
        high_px=high_px,
    )
    buy_lvl = entry_pct * 100.0
    stop_lvl = -stop_pct * 100.0
    pf = f"{{:.{px_digits}f}}"

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
    }

    if holding:
        if t1_lock:
            base.update(
                {
                    "alert": "持有·T+1",
                    "bg_class": "status-hold",
                    "挂单说明": "今日买入，明日再判止损",
                }
            )
            return base
        if gap945["active"] and not gap945["flipped"]:
            prev_s = pf.format(float(prev_close)) if prev_close is not None else "-"
            if gap945["should_exit"]:
                exit_px = round(float(gap945["exit_px"]), px_digits)
                base.update(
                    {
                        "pending_sell": True,
                        "alert": "低开945未翻红",
                        "bg_class": "warn-sell",
                        "建议挂单": exit_px,
                        "挂单说明": (
                            f"低开且{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}"
                            f"前未翻红(昨收{prev_s})，按{GAP_DOWN_EXIT_HOUR:02d}:"
                            f"{GAP_DOWN_EXIT_MINUTE:02d}价止损@{pf.format(exit_px)}"
                        ),
                    }
                )
                return base
            base.update(
                {
                    "pending_sell": True,
                    "alert": "低开·待945",
                    "bg_class": "warn-sell",
                    "建议挂单": round(float(last_px), px_digits),
                    "挂单说明": (
                        f"低开(昨收{prev_s})，"
                        f"≥{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}"
                        f"未翻红则止损"
                    ),
                }
            )
            return base
        if hit_stop:
            base.update(
                {
                    "pending_sell": True,
                    "alert": "已触止损",
                    "bg_class": "warn-sell",
                    "建议挂单": stop_px,
                    "挂单说明": f"条件卖@{pf.format(stop_px)}；未成交则尾盘市价",
                }
            )
            return base
        if abs(vs_open_pts - stop_lvl) <= near_points + 1e-12:
            base.update(
                {
                    "near_stop": True,
                    "pending_sell": True,
                    "alert": "将止损",
                    "bg_class": "warn-sell",
                    "建议挂单": stop_px,
                    "挂单说明": f"预埋条件卖@{pf.format(stop_px)}",
                }
            )
            return base
        if is_yin(open_px, last_px):
            if is_yin_exit_window():
                base.update(
                    {
                        "pending_sell": True,
                        "alert": "阴线收盘卖",
                        "bg_class": "warn-sell",
                        "建议挂单": round(float(last_px), px_digits),
                        "挂单说明": (
                            f"未触止损但收阴，尾盘按现价卖@{pf.format(last_px)}"
                        ),
                    }
                )
            else:
                base.update(
                    {
                        "pending_sell": True,
                        "alert": "阴线·待尾盘",
                        "bg_class": "warn-sell",
                        "建议挂单": round(float(last_px), px_digits),
                        "挂单说明": (
                            f"暂阴(现价<开盘)；≥{YIN_EXIT_HOUR:02d}:{YIN_EXIT_MINUTE:02d}"
                            f"仍收阴则按收盘卖，阳线翻红则继续持有"
                        ),
                    }
                )
            return base
        base.update(
            {
                "alert": "持有",
                "bg_class": "status-hold",
                "挂单说明": "未触发策略，继续持有",
            }
        )
        return base

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
        return base
    if abs(vs_open_pts - buy_lvl) <= near_points + 1e-12:
        base.update(
            {
                "near_buy": True,
                "pending_buy": True,
                "alert": "将买入",
                "bg_class": "warn-buy",
                "建议挂单": buy_trigger,
                "挂单说明": f"预埋限价买@{pf.format(buy_trigger)}",
            }
        )
        return base
    base.update(
        {
            "alert": "空仓",
            "bg_class": "status-flat",
            "挂单说明": "等待冲高买点",
        }
    )
    return base
