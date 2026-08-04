"""相对开盘 ±pct 策略核心（回测与盯盘共用）。

详见同文件 STRATEGY_RULES 常量。
"""

from __future__ import annotations

import datetime as dt
import math
from datetime import datetime
from typing import Any

import pandas as pd

# --- 策略规则说明（回测 / 盯盘 / 文档共用）---
STRATEGY_RULES = """
================================================================================
  开盘突破策略（OpenBreak3）— 默认阈值 ±2.5%
================================================================================

【空仓 · 买入】
  触发：当日最高价 >= ceil(开盘价 × (1 + 阈值))，按触发价限价买入，仓位约 95%。
  过滤（须同时满足）：
    · 前一日为阴线，或「小阳」：收盘涨幅严格 < 阈值（收盘 < 开盘×(1+阈值)）
    · 前一日之前不能连续两根阳线（禁「前面双阳」）
  T+1：A 股买入当日不可卖（ETF 可设 t0=True 当日可卖）。

【有仓 · 卖出】优先级从高到低（买入当日不卖，除非 t0）：

  ① 低开 9:45 未翻红 → 全清
     · 前提：开盘价 < 昨收（低开）
     · 翻红（触及即算，9:45 前不含 9:45 那根 1 分钟 K）：
         9:45 前最高价 >= 昨收 → 视为已翻红，不卖，继续按 ②③ 处理
     · 未翻红：到了 09:45 仍满足 9:45 前最高 < 昨收 → 全部可卖仓位清仓
     · 成交价（二选一，由 GAP945_EXIT_MODE 配置）：
         - "1m"：09:45 那根 1 分钟 K 线的收盘价
         - "5m"：09:40~09:45 这根 5 分钟 K 线的收盘价（由 1 分钟线合成）
     · 无对应分钟 K 线则不触发（回测可用 proxy 开盘价近似，仅作历史对比）

  ② 止损
     · 当日最低价 <= floor(开盘价 × (1 - 阈值)) → 按止损触发价全清

  ③ 阴线收盘
     · 未触 ①②，且收盘 < 开盘 → 按收盘价全清
     · 盯盘：≥14:55 仍收阴则按现价结算

  ④ 阳线 / 十字
     · 继续持有

【失败实验 · 不可用】
  · 软减半（945/阴线减半、止损全清）：回测劣于原因子1，ENABLE_SOFT_HALF_EXIT 必须保持 False
  · 因子2/因子3：已从代码删除，规格见 strategy/README.md 归档

【术语】
  · 翻红：低开日后，9:45 前价格曾触及或超过昨收（>= 昨收）
  · 全清：可用仓位 100% 卖出

【费用假设（回测默认）】
  · 佣金万 0.854；卖出印花税 0.1%；滑点 0.1%
================================================================================
"""

# --- 默认参数 ---
DEFAULT_PCT = 0.025
ENTRY_PCT = DEFAULT_PCT
STOP_PCT = DEFAULT_PCT
PREV_SMALL_YANG_PCT = 0.025
TICK_SIZE = 0.01
LOT_SIZE = 100
# 回撤仓位管理：权益回撤≥半仓阈值 → 半仓；回撤<恢复阈值 → 才恢复全仓开仓
ENABLE_DD_SIZING = False
DD_HALF_PCT = 0.20
DD_FULL_PCT = 0.15
# 软减半实验失败不可用：必须保持 False（见 strategy/README.md）
ENABLE_SOFT_HALF_EXIT = False
# 盯盘：|现价/因子价−1|×100 ≤ 此值 →「将买入/将止损」
NEAR_POINTS = 1.0
NEAR_FACTOR_PCT = NEAR_POINTS

GAP_DOWN_EXIT_HOUR = 9
GAP_DOWN_EXIT_MINUTE = 45
# 945 卖出价："1m"=09:45 分钟收盘价；"5m"=09:40~09:45 五分钟收盘价
GAP945_EXIT_MODE = "1m"
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


def half_lot_qty(qty: float | int, *, lot_size: int = LOT_SIZE) -> int:
    """可减半仓数量：约 1/2，向下取整到整手；不足 2 手则 0。"""
    q = int(qty)
    lot = max(1, int(lot_size))
    return (q // 2 // lot) * lot


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


def format_trigger_md(d: dt.date | datetime | pd.Timestamp | str | None) -> str | None:
    """因子触发日期展示：M/D（无年份、无前导零）。"""
    if d is None:
        return None
    if isinstance(d, str):
        ts = pd.Timestamp(d[:10])
    else:
        ts = pd.Timestamp(d)
    if pd.isna(ts):
        return None
    return f"{int(ts.month)}/{int(ts.day)}"


def replay_last_factor_triggers(
    daily: pd.DataFrame,
    *,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
    prev_entry_mode: str = "yin_or_small_yang",
) -> dict[str, Any]:
    """用日线简化重放，找最近一次买/卖因子触发（含价）。945 无分钟时跳过。"""
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
        c = float(row["close"])
        if o <= 0:
            continue
        buy_px = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
        stop_px = stop_trigger_price(o, stop_pct=stop_pct, tick=tick)
        allows = prev_day_allows_entry(
            float(prev["open"]),
            float(prev["close"]),
            prev_small_yang_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
        )
        double = False
        if prev2 is not None:
            double = has_double_yang_before(
                float(prev2["open"]),
                float(prev2["close"]),
                float(prev["open"]),
                float(prev["close"]),
            )

        if holding:
            # T+1：买入当日不卖
            if buy_day is not None and day == buy_day:
                continue
            if l <= stop_px + 1e-12:
                out["last_sell_date"] = day.date()
                out["last_sell_px"] = float(stop_px)
                holding = False
                buy_day = None
                continue
            if is_yin(o, c):
                out["last_sell_date"] = day.date()
                out["last_sell_px"] = float(c)
                holding = False
                buy_day = None
                continue
            continue

        if allows and (not double) and (h + 1e-12 >= buy_px):
            out["last_buy_date"] = day.date()
            out["last_buy_px"] = float(buy_px)
            holding = True
            buy_day = day

    out["holding"] = holding
    if out["last_sell_date"] and (
        out["last_buy_date"] is None or out["last_sell_date"] >= out["last_buy_date"]
    ):
        out["last_trigger_date"] = out["last_sell_date"]
        out["last_trigger_px"] = out["last_sell_px"]
        out["last_trigger_side"] = "sell"
    elif out["last_buy_date"] is not None:
        out["last_trigger_date"] = out["last_buy_date"]
        out["last_trigger_px"] = out["last_buy_px"]
        out["last_trigger_side"] = "buy"
    return out


def entry_filters_ok(
    prev_open: float | None,
    prev_close: float | None,
    prev2_open: float | None = None,
    prev2_close: float | None = None,
    *,
    entry_pct: float = DEFAULT_PCT,
    prev_entry_mode: str = "yin_or_small_yang",
) -> bool:
    """今日是否允许开仓（前日阴/小阳 + 禁前面双阳）。"""
    if prev_open is None or prev_close is None:
        return False
    if not prev_day_allows_entry(
        float(prev_open),
        float(prev_close),
        prev_small_yang_pct=entry_pct,
        prev_entry_mode=prev_entry_mode,
    ):
        return False
    if has_double_yang_before(prev2_open, prev2_close, prev_open, prev_close):
        return False
    return True



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
    # yin_or_small_yang=阴线或小阳可买；yin_only=仅阴线，小阳次日不买
    prev_entry_mode: str = "yin_or_small_yang",
) -> bool:
    if prev_open <= 0:
        return False
    if prev_close <= prev_open:
        return True
    if prev_entry_mode == "yin_only":
        return False
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


def _gap945_cutoff_ts(day0: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(day0).normalize() + pd.Timedelta(
        hours=GAP_DOWN_EXIT_HOUR, minutes=GAP_DOWN_EXIT_MINUTE
    )
    if ts.tzinfo is None:
        return ts.tz_localize("Asia/Shanghai")
    return ts.tz_convert("Asia/Shanghai")


def bar_close_at_time(
    bars: pd.DataFrame | None,
    hour: int = GAP_DOWN_EXIT_HOUR,
    minute: int = GAP_DOWN_EXIT_MINUTE,
) -> float | None:
    """取指定时刻的 1 分钟 K 线收盘价（如 09:45 那根）。"""
    if bars is None or bars.empty:
        return None
    b = bars.sort_values("ts")
    mask = (b["ts"].dt.hour == hour) & (b["ts"].dt.minute == minute)
    hit = b[mask]
    if hit.empty:
        return None
    return float(hit.iloc[-1]["close"])


def bar_close_5m_940_945(
    bars: pd.DataFrame | None,
    *,
    day0: pd.Timestamp | None = None,
) -> float | None:
    """09:40~09:45 五分钟 K 线收盘价（由 1 分钟线合成：窗口内最后一根 1m 的收盘价）。

    窗口 [09:40, 09:45] 含 09:45 那根 1 分钟 K，与「5 分钟 K 在 9:45 收盘」一致。
    """
    if bars is None or bars.empty:
        return None
    b = bars.sort_values("ts")
    if day0 is None:
        day0 = pd.Timestamp(b.iloc[0]["ts"]).normalize()
    if day0.tzinfo is None:
        day0 = day0.tz_localize("Asia/Shanghai")
    else:
        day0 = day0.tz_convert("Asia/Shanghai")
    start = day0 + pd.Timedelta(hours=9, minutes=40)
    end = day0 + pd.Timedelta(hours=9, minutes=GAP_DOWN_EXIT_MINUTE)
    slot = b[(b["ts"] >= start) & (b["ts"] <= end)]
    if slot.empty:
        return None
    return float(slot.iloc[-1]["close"])


def gap945_exit_close(
    bars: pd.DataFrame | None,
    *,
    mode: str = GAP945_EXIT_MODE,
    day0: pd.Timestamp | None = None,
) -> float | None:
    """低开 945 规则卖出价：1m 或 5m 收盘价。"""
    if mode == "5m":
        return bar_close_5m_940_945(bars, day0=day0)
    return bar_close_at_time(bars)


def morning_high_before_gap945(
    bars: pd.DataFrame | None,
    *,
    open_px: float,
    day0: pd.Timestamp | None = None,
) -> float:
    """9:45 前（不含 9:45 这根）的最高价；无分钟线时用 open。"""
    if bars is None or bars.empty:
        return float(open_px)
    b = bars.sort_values("ts").copy()
    b["ts"] = pd.to_datetime(b["ts"])
    if day0 is None:
        day0 = pd.Timestamp(b.iloc[0]["ts"]).normalize()
    cutoff = _gap945_cutoff_ts(day0)
    # 与分钟线对齐：比较时统一去掉时区，避免 datetime64[us] vs tz Timestamp
    if getattr(cutoff, "tzinfo", None) is not None:
        cutoff = cutoff.tz_localize(None)
    if getattr(b["ts"].dt, "tz", None) is not None:
        b["ts"] = b["ts"].dt.tz_localize(None)
    before = b[b["ts"] < cutoff]
    if before.empty:
        return float(open_px)
    return max(float(open_px), float(before["high"].max()))


def eval_gap_down_945(
    *,
    open_px: float,
    prev_close: float | None,
    day_bars: pd.DataFrame | None,
    last_px: float,
    high_px: float | None = None,
    now: datetime | None = None,
    exit_mode: str = GAP945_EXIT_MODE,
) -> dict[str, Any]:
    """低开 + 9:45 前未翻红 → 按 gap945_exit_close 全仓卖出。

    翻红：9:45 前（不含 9:45 这根）high >= 昨收（触及即算，不卖）。
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

    day0: pd.Timestamp | None = None
    if day_bars is not None and not day_bars.empty:
        day0 = pd.Timestamp(day_bars.iloc[0]["ts"]).normalize()
        if day0.tzinfo is None:
            day0 = day0.tz_localize("Asia/Shanghai")
        else:
            day0 = day0.tz_convert("Asia/Shanghai")
        morning_high = morning_high_before_gap945(
            day_bars, open_px=open_px, day0=day0
        )
        exit_px = gap945_exit_close(day_bars, mode=exit_mode, day0=day0)
    else:
        day_high = float(high_px) if high_px is not None else float(last_px)
        morning_high = max(float(open_px), day_high)
        exit_px = None

    out["morning_high"] = morning_high
    flipped = gap_down_flipped_red(morning_high, prev_close)
    out["flipped"] = flipped
    if flipped:
        return out
    if is_gap_down_exit_window(now) and exit_px is not None:
        out["should_exit"] = True
        out["exit_px"] = float(exit_px)
    return out


def build_gap_down_945_map(
    daily: pd.DataFrame,
    minute: pd.DataFrame | None = None,
    *,
    exit_mode: str = GAP945_EXIT_MODE,
) -> dict[str, dict[str, float | str]]:
    """回测用：预计算触发日；卖出价=gap945_exit_close（无则跳过）。"""
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
            day0 = day_min["ts"].dt.normalize().iloc[0]
            mh = morning_high_before_gap945(day_min, open_px=open_px, day0=day0)
            if gap_down_flipped_red(mh, prev_close):
                continue
            exit_close = gap945_exit_close(day_min, mode=exit_mode, day0=day0)
            if exit_close is None:
                continue
            src = "1m" if exit_mode == "1m" else "5m"
            out[day] = {
                "exit_px": float(exit_close),
                "prev_close": prev_close,
                "open_px": open_px,
                "source": src,
            }
    return out


def build_gap_down_945_proxy_map(
    daily: pd.DataFrame,
    minute: pd.DataFrame | None = None,
    *,
    proxy: str = "open",
    exit_mode: str = GAP945_EXIT_MODE,
) -> dict[str, dict[str, float | str]]:
    """回测用：有分钟线用精确 gap945 价；否则低开且日高<昨收时用 proxy 近似。

    proxy: open=开盘价近似；mid=(open+high)/2
    """
    out = build_gap_down_945_map(daily, minute, exit_mode=exit_mode)
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

    for i in range(1, len(daily)):
        row = daily.iloc[i]
        day = str(row["day"])
        if day in out:
            continue
        prev_close = float(daily.iloc[i - 1]["close"])
        open_px = float(row["open"])
        high_px = float(row["high"])
        if prev_close <= 0 or open_px <= 0 or open_px + 1e-12 >= prev_close:
            continue
        if high_px + 1e-12 >= prev_close:
            continue
        if proxy == "mid":
            exit_px = (open_px + high_px) / 2.0
            src = "proxy_mid"
        else:
            exit_px = open_px
            src = "proxy_open"
        out[day] = {
            "exit_px": float(exit_px),
            "prev_close": prev_close,
            "open_px": open_px,
            "source": src,
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
    near_points: float = NEAR_FACTOR_PCT,
    sellable_qty: int | None = None,
    lot_size: int = LOT_SIZE,
    allow_entry: bool = True,
) -> dict[str, Any]:
    """盯盘：按持仓输出一侧因子状态。

    · 接近预警：|现价/因子价 − 1|×100 ≤ near_points（默认 1%）
    · 统一字段：因子侧 / 因子价 / 因子触发 / 距因子价差 / 距因子%
    · allow_entry=False 时不因触买点进入待买入（前日过滤未过）
    """
    holding = qty > 0
    hit_buy = bool(allow_entry) and (high_px + 1e-12 >= buy_trigger)
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
    tick = 10 ** (-px_digits) if px_digits >= 0 else TICK_SIZE

    avail = int(sellable_qty) if sellable_qty is not None else int(qty)
    half_q = half_lot_qty(avail, lot_size=lot_size)

    dist_buy_px = round(float(last_px) - float(buy_trigger), px_digits)
    dist_stop_px = round(float(last_px) - float(stop_px), px_digits)
    dist_buy_pct = (
        round((float(last_px) / float(buy_trigger) - 1.0) * 100.0, 2)
        if float(buy_trigger) > 0
        else None
    )
    dist_stop_pct = (
        round((float(last_px) / float(stop_px) - 1.0) * 100.0, 2)
        if float(stop_px) > 0
        else None
    )
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
    }

    def _finish(out: dict[str, Any]) -> dict[str, Any]:
        sell = out["side"] == "sell"
        if sell:
            if out.get("t1_lock"):
                out["因子价"] = None
                out["距因子价差"] = None
                out["距因子%"] = None
                out["因子触发"] = "不可用"
                out["建议挂单"] = None
            else:
                # 默认因子价=止损价；945/阴线收盘决策价覆盖，并重算距因子
                if out.get("_suggest_factor_px") is not None:
                    fp = float(out["_suggest_factor_px"])
                    out["因子价"] = round(fp, px_digits)
                    out["距因子价差"] = round(float(last_px) - fp, px_digits)
                    out["距因子%"] = (
                        round((float(last_px) / fp - 1.0) * 100.0, 2) if fp > 0 else None
                    )
                else:
                    out["因子价"] = round(float(stop_px), px_digits)
                    out["距因子价差"] = dist_stop_px
                    out["距因子%"] = dist_stop_pct
                out["actionable"] = True
                alert = str(out.get("alert") or "")
                if out.get("hit_stop") or "已触止损" in alert:
                    out["因子触发"] = "已触发"
                elif "945未翻红" in alert or alert == "低开945未翻红":
                    out["因子触发"] = "已触发"
                elif "低开" in alert or "945" in alert:
                    out["因子触发"] = "接近"
                elif "阴线收盘卖" in alert:
                    out["因子触发"] = "已触发"
                elif "阴线" in alert:
                    out["因子触发"] = "接近"
                elif out.get("near_stop") or "将止损" in alert:
                    out["因子触发"] = "接近"
                else:
                    out["因子触发"] = "未触发"
                # 建议挂单：仅已给出时强制对齐因子价
                if out.get("建议挂单") is not None and out.get("因子价") is not None:
                    out["建议挂单"] = round(float(out["因子价"]), px_digits)
                elif out.get("建议挂单") is not None and out.get("因子价") is None:
                    out["建议挂单"] = None
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
        out.pop("_suggest_factor_px", None)
        # 持仓状态：待买入仅预警带内；待卖出仅卖出预警；否则空仓/持有
        if sell:
            if out.get("t1_lock"):
                out["持仓状态"] = "持有"
            elif bool(out.get("pending_sell")):
                out["持仓状态"] = "待卖出"
            else:
                out["持仓状态"] = "持有"
        else:
            if bool(out.get("pending_buy")):
                out["持仓状态"] = "待买入"
            else:
                out["持仓状态"] = "空仓"
        # 因子侧：仅预警时标买卖；其余与持仓状态一致（持有/空仓）
        pos_st = str(out.get("持仓状态") or "")
        if pos_st == "待卖出":
            out["因子侧"] = "卖出"
        elif pos_st == "待买入":
            out["因子侧"] = "买入"
        elif pos_st == "持有":
            out["因子侧"] = "持有"
        else:
            out["因子侧"] = "空仓"
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
        # 低开未翻红：盘中预警；09:45 才决策并给挂单价
        if gap945["active"] and not gap945["flipped"]:
            prev_s = pf.format(float(prev_close)) if prev_close is not None else "-"
            if gap945["should_exit"]:
                exit_px = round(float(gap945["exit_px"]), px_digits)
                base.update(
                    {
                        "pending_sell": True,
                        "alert": "低开945未翻红",
                        "bg_class": "warn-sell",
                        "_suggest_factor_px": exit_px,
                        "建议挂单": exit_px,
                        "挂单说明": (
                            f"低开且{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}"
                            f"前未翻红(昨收{prev_s})，"
                            f"按因子价(09:45收盘)全清@{pf.format(exit_px)}"
                        ),
                    }
                )
                return _finish(base)
            base.update(
                {
                    "pending_sell": True,
                    "alert": "低开·待945",
                    "bg_class": "warn-sell",
                    "建议挂单": None,  # 9:45 前只预警，不做挂单决策
                    "挂单说明": (
                        f"低开未翻红(昨收{prev_s})，盘中预警；"
                        f"{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}"
                        f"仍未翻红才按09:45因子价全清"
                    ),
                }
            )
            return _finish(base)
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
                        f"距止损因子价在{near_points:g}%内（现差{dist_stop_pct:+.2f}%），"
                        f"预埋条件卖@{pf.format(stop_px)}"
                    ),
                }
            )
            return _finish(base)
        if is_yin(open_px, last_px):
            if is_yin_exit_window():
                # 阴线收盘因子价=现价（收盘）
                yin_px = round(float(last_px), px_digits)
                base.update(
                    {
                        "pending_sell": True,
                        "alert": "阴线收盘卖",
                        "bg_class": "warn-sell",
                        "_suggest_factor_px": yin_px,
                        "建议挂单": yin_px,
                        "挂单说明": (
                            f"未触止损但收阴，尾盘按收盘因子价卖@{pf.format(yin_px)}"
                        ),
                    }
                )
            else:
                base.update(
                    {
                        "pending_sell": True,
                        "alert": "阴线·待尾盘",
                        "bg_class": "warn-sell",
                        "建议挂单": None,  # 尾盘前只预警
                        "挂单说明": (
                            f"暂阴(现价<开盘)；≥{YIN_EXIT_HOUR:02d}:{YIN_EXIT_MINUTE:02d}"
                            f"仍收阴则按收盘因子价卖，阳线翻红则继续持有"
                        ),
                    }
                )
            return _finish(base)
        base.update(
            {
                "alert": "持有",
                "bg_class": "status-hold",
                "挂单说明": "",
                "建议挂单": None,
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
                    f"距买点因子价在{near_points:g}%内（现差{dist_buy_pct:+.2f}%），"
                    f"预埋限价买@{pf.format(buy_trigger)}"
                ),
            }
        )
        return _finish(base)
    base.update(
        {
            "alert": "空仓",
            "bg_class": "status-flat",
            "挂单说明": "",
            "建议挂单": None,
            "pending_buy": False,
        }
    )
    return _finish(base)
