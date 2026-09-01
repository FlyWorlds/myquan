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
    · 禁「前面双阳且跨日≥5%」：
        前前日、前日均为阳线，且 前日收盘/前前日开盘 - 1 ≥ 5% → 今日不买
        （弱双阳跨日不足 5% 不禁；不另设单阳禁买，大阳已由「阴/小阳」过滤）
    · 阳线定义：收盘至少比开盘高 1 个最小价位；十字（开≈收）不算阳、也不算阴
  T+1：A 股买入当日不可卖（ETF 可设 t0=True 当日可卖）。

【有仓 · 卖出】优先级从高到低（买入当日不卖，除非 t0）：

  ① 止损
     · 当日最低价 <= floor(开盘价 × (1 - 阈值)) → 按止损触发价全清

  ② 未触止损
     · 无论阴线、阳线或十字，均继续持有

【术语】
  · 全清：可用仓位 100% 卖出

【费用假设（回测默认）】
  · 佣金万 0.86；杂费万 0.10（买卖）；卖出印花税万 5；滑点 0.1%

【说明】
  · 以上为因子1（开盘突破）规则。援军战法（strategy1）默认另叠因子2（回撤预警），
    完整组合规则：get_strategy("strategy1").print_rules()
================================================================================
"""

# --- 默认参数 ---
DEFAULT_PCT = 0.025
ENTRY_PCT = DEFAULT_PCT
STOP_PCT = DEFAULT_PCT
PREV_SMALL_YANG_PCT = 0.025
TICK_SIZE = 0.01
# 核心双阳过滤：第一根阳开盘 → 第二根阳收盘，涨幅≥该阈值才禁买
DEFAULT_BAN_DOUBLE_YANG = True
DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT = 0.05
DEFAULT_DOUBLE_YANG_COMBINED_MODE = "span"  # span | sum_body
DEFAULT_BAN_SINGLE_YANG = False
LOT_SIZE = 100
# 盯盘：|现价/因子价−1|×100 ≤ 此值 →「将买入/将止损」
NEAR_POINTS = 1.0
NEAR_FACTOR_PCT = NEAR_POINTS

REASON_STOP = "止损成交"
EXIT_REASONS = (REASON_STOP,)


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


def limit_down_price(
    prev_close: float | None,
    *,
    limit_down_pct: float = 0.10,
    tick: float = TICK_SIZE,
) -> float | None:
    """按昨收和日跌停幅度计算跌停价；缺昨收时不判断。"""
    if prev_close is None or float(prev_close) <= 0 or not 0 < limit_down_pct < 1:
        return None
    return floor_to_tick(float(prev_close) * (1.0 - limit_down_pct), tick)


def limit_down_state(
    *,
    prev_close: float | None,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    limit_down_pct: float = 0.10,
    tick: float = TICK_SIZE,
) -> dict[str, float | bool | None]:
    """识别日内跌停状态。

    一字跌停（开高低收均锁在跌停价）不可卖；若当日曾触及跌停且最高价
    回到跌停价之上，视为开板，按跌停价作为卖出委托基准。
    """
    limit_px = limit_down_price(
        prev_close, limit_down_pct=limit_down_pct, tick=tick
    )
    if limit_px is None:
        return {"limit_px": None, "touched": False, "locked": False, "opened": False}
    tolerance = max(float(tick) * 0.51, 1e-8)
    prices = (float(open_px), float(high_px), float(low_px), float(close_px))
    touched = float(low_px) <= float(limit_px) + tolerance
    locked = touched and all(abs(px - float(limit_px)) <= tolerance for px in prices)
    opened = touched and (not locked) and float(high_px) > float(limit_px) + tolerance
    return {
        "limit_px": float(limit_px),
        "touched": touched,
        "locked": locked,
        "opened": opened,
    }


def limit_up_price(
    prev_close: float | None,
    *,
    limit_up_pct: float = 0.10,
    tick: float = TICK_SIZE,
) -> float | None:
    """按昨收和日涨停幅度计算涨停价；缺昨收时不判断。"""
    if prev_close is None or float(prev_close) <= 0 or not 0 < limit_up_pct < 1:
        return None
    return ceil_to_tick(float(prev_close) * (1.0 + limit_up_pct), tick)


# 与 second_board.LU_TOL 一致：开盘涨幅达到涨停幅度−1.2pct 视为涨停开盘
LIMIT_UP_OPEN_TOL = 0.012


def limit_up_state(
    *,
    prev_close: float | None,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    limit_up_pct: float = 0.10,
    tick: float = TICK_SIZE,
) -> dict[str, float | bool | None]:
    """识别日内涨停状态。

    项目默认：一字涨停开盘不可买入（开盘已在涨停价，即使随后开板也不追）。
    locked：开高低收均锁在涨停价（全日一字）。
    """
    limit_px = limit_up_price(prev_close, limit_up_pct=limit_up_pct, tick=tick)
    if limit_px is None:
        return {
            "limit_px": None,
            "touched": False,
            "locked": False,
            "opened": False,
            "open_at_limit": False,
        }
    tolerance = max(float(tick) * 0.51, 1e-8)
    prices = (float(open_px), float(high_px), float(low_px), float(close_px))
    touched = float(high_px) >= float(limit_px) - tolerance
    locked = touched and all(abs(px - float(limit_px)) <= tolerance for px in prices)
    opened = touched and (not locked) and float(low_px) < float(limit_px) - tolerance
    open_at_limit = abs(float(open_px) - float(limit_px)) <= tolerance
    if prev_close and float(prev_close) > 0:
        open_ret = float(open_px) / float(prev_close) - 1.0
        open_at_limit = open_at_limit or (
            open_ret >= float(limit_up_pct) - LIMIT_UP_OPEN_TOL
        )
    return {
        "limit_px": float(limit_px),
        "touched": touched,
        "locked": locked,
        "opened": opened,
        "open_at_limit": bool(open_at_limit),
    }


def cannot_buy_limit_up(
    *,
    prev_close: float | None,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    limit_up_pct: float = 0.10,
    tick: float = TICK_SIZE,
) -> bool:
    """一字涨停开盘：不可新开仓。"""
    st = limit_up_state(
        prev_close=prev_close,
        open_px=open_px,
        high_px=high_px,
        low_px=low_px,
        close_px=close_px,
        limit_up_pct=limit_up_pct,
        tick=tick,
    )
    return bool(st["open_at_limit"] or st["locked"])


def is_miaoban_unbuyable(
    *,
    prev_close: float | None,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    limit_up_pct: float = 0.10,
    entry_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
) -> bool:
    """秒板/直线封板：非一字开盘但日内迅速封涨停，日线近似为买不到。

    与 b6-limitup-pool「首封≤09:31」一致的可买性约束；无分钟线时用
    「低贴开、振幅窄、收盘封板」近似。
    """
    if cannot_buy_limit_up(
        prev_close=prev_close,
        open_px=open_px,
        high_px=high_px,
        low_px=low_px,
        close_px=close_px,
        limit_up_pct=limit_up_pct,
        tick=tick,
    ):
        return True
    st = limit_up_state(
        prev_close=prev_close,
        open_px=open_px,
        high_px=high_px,
        low_px=low_px,
        close_px=close_px,
        limit_up_pct=limit_up_pct,
        tick=tick,
    )
    if not bool(st["touched"]):
        return False
    limit_px = float(st["limit_px"] or 0.0)
    o, h, l, c = float(open_px), float(high_px), float(low_px), float(close_px)
    if limit_px <= 0 or o <= 0:
        return False
    tol = max(float(tick) * 0.51, 1e-8)
    if abs(c - limit_px) > tol or abs(h - limit_px) > tol:
        return False
    if prev_close is None or float(prev_close) <= 0:
        return False
    open_ret = o / float(prev_close) - 1.0
    if open_ret >= float(limit_up_pct) - LIMIT_UP_OPEN_TOL:
        return True
    buy_px = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
    if buy_px >= limit_px - tol:
        return True
    # 低开后窄振幅直拉封板：突破买点窗口极短
    if l <= o * 1.015 and (h - l) / o <= 0.045 and open_ret < 0.05:
        return True
    # 低点从未触及买点（一字拉升穿越）
    if l > buy_px + tol and h >= limit_px - tol:
        return True
    return False


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
    limit_down_pct: float = 0.10,
) -> dict[str, Any]:
    """用日线简化重放，找最近一次买入或止损触发（含价）。"""
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
        blocked = False
        if prev2 is not None:
            blocked = should_block_entry_by_yang(
                float(prev2["open"]),
                float(prev2["close"]),
                float(prev["open"]),
                float(prev["close"]),
                tick=tick,
                ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
            )

        if holding:
            # T+1：买入当日不卖
            if buy_day is not None and day == buy_day:
                continue
            if l <= stop_px + 1e-12:
                limit_state = limit_down_state(
                    prev_close=float(prev["close"]),
                    open_px=o,
                    high_px=h,
                    low_px=l,
                    close_px=c,
                    limit_down_pct=limit_down_pct,
                    tick=tick,
                )
                if bool(limit_state["locked"]):
                    continue
                out["last_sell_date"] = day.date()
                out["last_sell_px"] = float(
                    limit_state["limit_px"]
                    if bool(limit_state["opened"])
                    else stop_px
                )
                holding = False
                buy_day = None
                continue
            continue

        if allows and (not blocked) and (h + 1e-12 >= buy_px):
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


def _merge_live_daily_bar(
    daily: pd.DataFrame,
    *,
    session: str,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
) -> pd.DataFrame:
    """将盘中快照并入日线末 bar（用于当日策略收益 mark）。"""
    if daily is None or daily.empty:
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp(str(session)[:10]),
                    "open": open_px,
                    "high": high_px,
                    "low": low_px,
                    "close": close_px,
                }
            ]
        )
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    sess = pd.Timestamp(str(session)[:10]).normalize()
    bar = {
        "date": sess,
        "open": float(open_px),
        "high": float(high_px),
        "low": float(low_px),
        "close": float(close_px),
    }
    if df.iloc[-1]["date"] == sess:
        df.iloc[-1] = bar
    elif sess > df.iloc[-1]["date"]:
        df = pd.concat([df, pd.DataFrame([bar])], ignore_index=True)
    return df


def replay_strategy_return_since(
    daily: pd.DataFrame,
    *,
    start_date: str = "2026-09-01",
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
    prev_entry_mode: str = "yin_or_small_yang",
    limit_down_pct: float = 0.10,
    initial_cash: float = 100_000.0,
    code: str = "",
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG,
    ban_single_yang: bool = DEFAULT_BAN_SINGLE_YANG,
    double_yang_combined_min_pct: float | None = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
) -> dict[str, Any]:
    """自 start_date 起空仓重放因子1，返回累计策略收益（含费用、整手、T+1）。"""
    from strategy.costs import ENGINE_COMMISSION_RATE, SLIPPAGE_VALUE, stamp_tax_for_code

    out: dict[str, Any] = {
        "return_pct": None,
        "pnl": None,
        "trades": 0,
        "holding": False,
        "start_date": str(start_date)[:10],
    }
    if daily is None or daily.empty:
        return out
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    if len(df) < 2:
        return out

    start = pd.Timestamp(str(start_date)[:10]).normalize()
    idxs = [i for i in range(len(df)) if pd.Timestamp(df.iloc[i]["date"]).normalize() >= start]
    if not idxs:
        return out

    stamp = stamp_tax_for_code(code)
    lot = 100
    target = 0.95
    cash = float(initial_cash)
    shares = 0.0
    buy_day: pd.Timestamp | None = None
    trades = 0

    for i in idxs:
        row = df.iloc[i]
        prev = df.iloc[i - 1] if i >= 1 else None
        prev2 = df.iloc[i - 2] if i >= 2 else None
        if prev is None:
            continue
        day = pd.Timestamp(row["date"]).normalize()
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if o <= 0 or c <= 0:
            continue
        buy_px = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
        stop_px = stop_trigger_price(o, stop_pct=stop_pct, tick=tick)

        if shares > 0:
            if buy_day is not None and day == buy_day:
                continue
            if l <= stop_px + 1e-12:
                lim = limit_down_state(
                    prev_close=float(prev["close"]),
                    open_px=o,
                    high_px=h,
                    low_px=l,
                    close_px=c,
                    limit_down_pct=limit_down_pct,
                    tick=tick,
                )
                if bool(lim["locked"]):
                    continue
                sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                sell_px *= 1.0 - SLIPPAGE_VALUE
                proceeds = shares * sell_px
                fee = proceeds * ENGINE_COMMISSION_RATE + proceeds * stamp
                cash += proceeds - fee
                shares = 0.0
                buy_day = None
                trades += 1
            continue

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
                tick=tick,
                ban_double_yang=ban_double_yang,
                ban_single_yang=ban_single_yang,
                double_yang_combined_min_pct=double_yang_combined_min_pct,
                double_yang_combined_mode=double_yang_combined_mode,
            )
        if allows and (not blocked) and (h + 1e-12 >= buy_px):
            px = buy_px * (1.0 + SLIPPAGE_VALUE)
            budget = cash * target
            raw = math.floor(budget / (px * lot)) * lot
            if raw >= lot:
                cost = raw * px
                fee = cost * ENGINE_COMMISSION_RATE
                if cost + fee <= cash:
                    cash -= cost + fee
                    shares = float(raw)
                    buy_day = day

    mark = float(df.iloc[idxs[-1]]["close"])
    equity = cash + shares * mark
    out["holding"] = shares > 0
    out["trades"] = trades
    out["pnl"] = round(equity - float(initial_cash), 2)
    out["return_pct"] = round((equity / float(initial_cash) - 1.0) * 100.0, 2)
    return out


def entry_filters_ok(
    prev_open: float | None,
    prev_close: float | None,
    prev2_open: float | None = None,
    prev2_close: float | None = None,
    *,
    entry_pct: float = DEFAULT_PCT,
    prev_entry_mode: str = "yin_or_small_yang",
    tick: float = TICK_SIZE,
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG,
    ban_single_yang: bool = DEFAULT_BAN_SINGLE_YANG,
    yang_min_pct: float = 0.0,
    double_yang_second_min_pct: float | None = None,
    double_yang_combined_min_pct: float | None = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    single_yang_min_pct: float | None = None,
) -> bool:
    """今日是否允许开仓（前日阴/小阳 + 双阳跨日过滤；十字不算阳）。"""
    if prev_entry_mode == "limit_up_ok":
        return True
    if prev_entry_mode != "any":
        if prev_open is None or prev_close is None:
            return False
        if not prev_day_allows_entry(
            float(prev_open),
            float(prev_close),
            prev_small_yang_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
            tick=tick,
        ):
            return False
    if should_block_entry_by_yang(
        prev2_open,
        prev2_close,
        prev_open,
        prev_close,
        tick=tick,
        ban_double_yang=ban_double_yang,
        ban_single_yang=ban_single_yang,
        yang_min_pct=yang_min_pct,
        double_yang_second_min_pct=double_yang_second_min_pct,
        double_yang_combined_min_pct=double_yang_combined_min_pct,
        double_yang_combined_mode=double_yang_combined_mode,
        single_yang_min_pct=single_yang_min_pct,
    ):
        return False
    return True



def is_yin(open_px: float, close_px: float, *, tick: float = TICK_SIZE) -> bool:
    """阴线：收盘至少低于开盘 1 跳；十字不算阴。"""
    return float(close_px) <= float(open_px) - float(tick) + 1e-12


def is_yang(open_px: float, close_px: float, *, tick: float = TICK_SIZE) -> bool:
    """阳线：收盘至少高于开盘 1 跳；十字（开≈收）不算阳。"""
    return float(close_px) >= float(open_px) + float(tick) - 1e-12


def is_doji(open_px: float, close_px: float, *, tick: float = TICK_SIZE) -> bool:
    """十字：实体小于 1 个最小价位。"""
    return abs(float(close_px) - float(open_px)) < float(tick) - 1e-12


def bar_shape(open_px: float, last_px: float, *, tick: float = TICK_SIZE) -> str:
    if is_yang(open_px, last_px, tick=tick):
        return "阳"
    if is_yin(open_px, last_px, tick=tick):
        return "阴"
    return "十字"


def prev_day_allows_entry(
    prev_open: float,
    prev_close: float,
    *,
    prev_small_yang_pct: float = PREV_SMALL_YANG_PCT,
    # yin_or_small_yang=阴线或小阳可买；yin_only=仅阴线，小阳次日不买
    prev_entry_mode: str = "yin_or_small_yang",
    tick: float = TICK_SIZE,
) -> bool:
    if prev_open <= 0:
        return False
    if prev_entry_mode in ("any", "limit_up_ok"):
        return True
    # 阴线或十字：允许（十字不算阳，视同可开仓的弱势日）
    if not is_yang(prev_open, prev_close, tick=tick):
        return True
    if prev_entry_mode == "yin_only":
        return False
    limit_px = prev_open * (1.0 + prev_small_yang_pct)
    return float(prev_close) < limit_px - 1e-8


def yang_ret_pct(open_px: float, close_px: float) -> float:
    """相对开盘涨幅（小数）。开盘无效时返回 nan。"""
    o = float(open_px)
    if o <= 0:
        return float("nan")
    return float(close_px) / o - 1.0


def counts_as_yang(
    open_px: float,
    close_px: float,
    *,
    tick: float = TICK_SIZE,
    min_pct: float = 0.0,
) -> bool:
    """是否计为阳线：至少 1 跳实体，且涨幅 >= min_pct。"""
    if not is_yang(open_px, close_px, tick=tick):
        return False
    if float(min_pct) > 0 and yang_ret_pct(open_px, close_px) + 1e-12 < float(min_pct):
        return False
    return True


def has_double_yang_before(
    prev2_open: float | None,
    prev2_close: float | None,
    prev_open: float | None,
    prev_close: float | None,
    *,
    tick: float = TICK_SIZE,
    yang_min_pct: float = 0.0,
    second_min_pct: float | None = None,
    combined_min_pct: float | None = None,
    # sum_body=两根实体涨幅相加；span=第一根开盘→第二根收盘
    combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
) -> bool:
    """前面双阳是否触发禁买。

    - yang_min_pct: 两根都要达到的最小阳线涨幅（0=仅需≥1跳）
    - second_min_pct: 第二根（前日）阳线涨幅下限；更弱则「排除」不禁买
    - combined_min_pct: 合计/跨日涨幅下限；不足则不禁买
    - combined_mode: sum_body | span（默认 span）
    """
    if None in (prev2_open, prev2_close, prev_open, prev_close):
        return False
    if prev2_open <= 0 or prev_open <= 0:
        return False
    if not counts_as_yang(
        prev2_open, prev2_close, tick=tick, min_pct=yang_min_pct
    ) or not counts_as_yang(prev_open, prev_close, tick=tick, min_pct=yang_min_pct):
        return False
    r2 = yang_ret_pct(prev2_open, prev2_close)
    r1 = yang_ret_pct(prev_open, prev_close)
    if second_min_pct is not None and r1 + 1e-12 < float(second_min_pct):
        return False
    if combined_min_pct is not None:
        mode = (combined_mode or DEFAULT_DOUBLE_YANG_COMBINED_MODE).lower()
        if mode == "span":
            # 第一根阳开盘 → 第二根阳收盘
            o0 = float(prev2_open)
            if o0 <= 0:
                return False
            combined = float(prev_close) / o0 - 1.0
        else:
            combined = r1 + r2
        if combined + 1e-12 < float(combined_min_pct):
            return False
    return True


def should_block_entry_by_yang(
    prev2_open: float | None,
    prev2_close: float | None,
    prev_open: float | None,
    prev_close: float | None,
    *,
    tick: float = TICK_SIZE,
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG,
    ban_single_yang: bool = DEFAULT_BAN_SINGLE_YANG,
    yang_min_pct: float = 0.0,
    double_yang_second_min_pct: float | None = None,
    double_yang_combined_min_pct: float | None = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    single_yang_min_pct: float | None = None,
) -> bool:
    """按单阳/双阳规则判断是否禁买。"""
    if ban_single_yang and prev_open is not None and prev_close is not None:
        thr = (
            float(single_yang_min_pct)
            if single_yang_min_pct is not None
            else float(yang_min_pct)
        )
        if counts_as_yang(prev_open, prev_close, tick=tick, min_pct=thr):
            return True
    if ban_double_yang:
        return has_double_yang_before(
            prev2_open,
            prev2_close,
            prev_open,
            prev_close,
            tick=tick,
            yang_min_pct=yang_min_pct,
            second_min_pct=double_yang_second_min_pct,
            combined_min_pct=double_yang_combined_min_pct,
            combined_mode=double_yang_combined_mode,
        )
    return False


def is_t1_buy_day(buy_time: str | None, session: str) -> bool:
    if not buy_time:
        return False
    return str(buy_time)[:10] == str(session)[:10]


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
    near_points: float = NEAR_FACTOR_PCT,
    allow_entry: bool = True,
) -> dict[str, Any]:
    """盯盘：按持仓输出一侧因子状态。

    · 接近预警：|现价/因子价 − 1|×100 ≤ near_points（默认 1%）
    · 统一字段：因子侧 / 因子价 / 因子触发 / 距已触发* / 距未触发*
    · 有仓：已触发=买入因子，未触发=卖出(止损)；空仓：已触发=卖出，未触发=买入
    · allow_entry=False 时不因触买点进入待买入（前日过滤未过）
    """
    holding = qty > 0
    hit_buy = bool(allow_entry) and (high_px + 1e-12 >= buy_trigger)
    hit_stop = low_px <= stop_px + 1e-12
    t1_lock = holding and (not t0) and is_t1_buy_day(buy_time, session)
    buy_lvl = entry_pct * 100.0
    stop_lvl = -stop_pct * 100.0
    pf = f"{{:.{px_digits}f}}"
    tick = 10 ** (-px_digits) if px_digits >= 0 else TICK_SIZE

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
    }

    def _finish(out: dict[str, Any]) -> dict[str, Any]:
        sell = out["side"] == "sell"
        if sell:
            # 有仓一律给出卖出因子价=止损价（含 T+1 仅展示、不可下单）
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
                # 建议挂单：有仓时对齐卖出因子价（止损）
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

        # 双距：上一个已触发因子 / 下一个未触发因子
        # 卖出侧取反：现价高于止损时为负，表示还需下跌才触发卖出
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
        # 兼容旧字段：距因子 = 距未触发（下一个）
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
        base.update(
            {
                "alert": "持有",
                "bg_class": "status-hold",
                "建议挂单": stop_px,
                "挂单说明": (
                    f"持有中，卖出因子价=开盘止损@{pf.format(stop_px)}，"
                    f"可预埋条件卖"
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
