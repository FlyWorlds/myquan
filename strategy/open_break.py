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

  ① 止损
     · 当日最低价 <= floor(开盘价 × (1 - 阈值)) → 按止损触发价全清

  ② 未触止损
     · 无论阴线、阳线或十字，均继续持有

【术语】
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
    · 统一字段：因子侧 / 因子价 / 因子触发 / 距因子价差 / 距因子%
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
                out["因子价"] = round(float(stop_px), px_digits)
                out["距因子价差"] = dist_stop_px
                out["距因子%"] = dist_stop_pct
                out["actionable"] = True
                alert = str(out.get("alert") or "")
                if out.get("hit_stop") or "已触止损" in alert:
                    out["因子触发"] = "已触发"
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
