"""持仓记录与盯盘：凯盛600552 / 楚江002171 / 国风000859 / 天通600330 / 深科技000021

功能：
  · 拉取当日开盘、最高、最低、现价（新浪1分钟）
  · 策略规则见 myquan/strategy/open_break.py（与 idnex.py / kskj2 一致）
  · 有仓：默认「持有」；低开 9:45 前未翻红 → 9:45 分钟收盘价全清
  · 触止损 → 自动结算；未触止损但尾盘收阴(≥14:55) → 按现价结算
  · 空仓：已触买/将买入 → 翻转并建议限价买
  · 本地 JSON 记录持仓成本与数量，计算浮盈亏；T+1 买入日提示不可卖

用法：
  python index.py              # 查看标的行情 + 持仓，并生成 HTML
  python index.py html         # 仅生成/打开 HTML 报告
  python index.py watch        # 长驻：每60秒更新行情，本地页倒计时自动刷新
  python index.py buy 002171 9.05 1000
  python index.py sell 002171 9.20 500
  python index.py set-cost 600552 15.95 --qty 400
  python index.py clear 002171
  python index.py history
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import webbrowser
from datetime import datetime
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import requests

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from strategy.open_break import (
    DEFAULT_PCT,
    ENTRY_PCT,
    EXIT_REASONS,
    GAP_DOWN_EXIT_HOUR,
    GAP_DOWN_EXIT_MINUTE,
    NEAR_POINTS,
    REASON_GAP945,
    REASON_STOP,
    REASON_YIN,
    STOP_PCT,
    TICK_SIZE,
    YIN_EXIT_HOUR,
    YIN_EXIT_MINUTE,
    bar_shape,
    eval_gap_down_945,
    is_t1_buy_day,
    is_yin,
    is_yang,
    is_yin_exit_window,
    strategy_levels,
    strategy_signal,
)

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / "holdings.json"
TRADES_FILE = ROOT / "trades.jsonl"
REPORT_FILE = ROOT / "holdings_report.html"
WATCH_META_FILE = ROOT / "holdings_watch.json"

WATCHLIST: list[dict[str, Any]] = [
    {"code": "600552", "sina": "sh600552", "market": "上证", "name": "凯盛科技"},
    {"code": "002171", "sina": "sz002171", "market": "深证", "name": "楚江新材"},
    {"code": "000859", "sina": "sz000859", "market": "深证", "name": "国风新材"},
    {"code": "600330", "sina": "sh600330", "market": "上证", "name": "天通股份"},
    {"code": "000021", "sina": "sz000021", "market": "深证", "name": "深科技"},
]

# 大盘指数（新浪 spot）
INDEX_WATCH: list[dict[str, str]] = [
    {"code": "sh000001", "name": "上证指数", "market": "上证"},
    {"code": "sz399001", "name": "深证成指", "market": "深证"},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """先写临时文件再替换，避免浏览器读到半截 HTML 导致布局闪乱。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _watchlist_codes_label() -> str:
    return " / ".join(w["code"] for w in WATCHLIST)


def _code_key(code: str) -> str:
    return "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]


def _watch_pct(item: dict[str, Any]) -> float:
    return float(item.get("pct", DEFAULT_PCT))


def _watch_tick(item: dict[str, Any]) -> float:
    return float(item.get("tick", TICK_SIZE))


def _px_digits(tick: float) -> int:
    """按最小变动价位决定价格小数位（ETF 0.001 → 3 位）。"""
    if tick <= 0:
        return 2
    if tick >= 1:
        return 0
    return max(0, -int(round(math.log10(tick))))


def _empty_position(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "market": item["market"],
        "qty": 0,
        "cost": None,
        "buy_time": None,
        "note": "",
    }


def _find_meta(code: str) -> dict[str, Any]:
    key = _code_key(code)
    for item in WATCHLIST:
        if item["code"] == key:
            return item
    codes = "/".join(w["code"] for w in WATCHLIST)
    raise KeyError(f"不在监控列表: {code}（仅支持 {codes}）")


def load_holdings() -> dict[str, Any]:
    if not HOLDINGS_FILE.exists():
        data = {
            "updated_at": None,
            "account_total": None,
            "account_cash": None,
            "positions": {
                w["code"]: _empty_position(w)
                for w in WATCHLIST
            },
            "realized_today": {},
        }
        save_holdings(data)
        return data
    with HOLDINGS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    positions = data.setdefault("positions", {})
    for w in WATCHLIST:
        positions.setdefault(w["code"], _empty_position(w))
    data.setdefault("realized_today", {})
    data.setdefault("account_total", None)
    data.setdefault("account_cash", None)
    data.setdefault("account_total_open", None)
    data.setdefault("account_total_open_session", None)
    return data


def _account_total_open(data: dict[str, Any] | None = None) -> float | None:
    data = data if data is not None else load_holdings()
    return _as_money(data.get("account_total_open"))


def _ensure_account_open_session(
    data: dict[str, Any],
    *,
    session: str,
    account_total: float | None,
) -> None:
    """跨日或首次：锁定日初总资产，供合计/当日盈亏%分母。"""
    open_session = str(data.get("account_total_open_session") or "")
    if open_session == session and _account_total_open(data) is not None:
        return
    if account_total is None or account_total <= 0:
        return
    data["account_total_open"] = round(float(account_total), 2)
    data["account_total_open_session"] = session
    save_holdings(data)


def _as_money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _account_cash(data: dict[str, Any] | None = None) -> float | None:
    data = data if data is not None else load_holdings()
    return _as_money(data.get("account_cash"))


def _holdings_market_value(rows: list[dict[str, Any]]) -> float:
    return sum(
        float(r["市值"])
        for r in rows
        if r.get("市值") is not None and int(r.get("持仓") or 0) > 0
    )


def _account_total(
    rows: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> float | None:
    """总资产：优先 现金+市值；否则用登记的 account_total。"""
    data = data if data is not None else load_holdings()
    cash = _account_cash(data)
    if cash is not None and rows is not None:
        return round(cash + _holdings_market_value(rows), 2)
    return _as_money(data.get("account_total"))


def _available_cash(
    rows: list[dict[str, Any]],
    data: dict[str, Any] | None = None,
) -> float | None:
    data = data if data is not None else load_holdings()
    cash = _account_cash(data)
    if cash is not None:
        return round(cash, 2)
    total = _as_money(data.get("account_total"))
    if total is None:
        return None
    return round(total - _holdings_market_value(rows), 2)


def _today_opened_cost(rows: list[dict[str, Any]], session: str | None = None) -> float:
    """当日新开仓成本额（买入日记为当日的持仓）。"""
    session = session or str(pd.Timestamp.now().date())
    total = 0.0
    positions = load_holdings().get("positions", {})
    for r in rows:
        code = str(r.get("代码") or "")
        qty = int(r.get("持仓") or 0)
        if qty <= 0:
            continue
        pos = positions.get(code) or {}
        if not is_t1_buy_day(pos.get("buy_time"), session):
            continue
        cv = r.get("成本额")
        if cv is not None:
            total += float(cv)
        elif pos.get("cost") is not None:
            total += float(pos["cost"]) * qty
    return round(total, 2)


def _sync_account_total(rows: list[dict[str, Any]]) -> float | None:
    """有现金登记时，用 现金+市值 回写总资产。"""
    data = load_holdings()
    cash = _account_cash(data)
    if cash is None:
        return _as_money(data.get("account_total"))
    total = round(cash + _holdings_market_value(rows), 2)
    if data.get("account_total") != total:
        data["account_total"] = total
        save_holdings(data)
    return total


def save_holdings(data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    with HOLDINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _purge_stale_realized(data: dict[str, Any], session: str) -> None:
    """清除非当日已实现记录，避免隔日污染合计。"""
    realized = data.setdefault("realized_today", {})
    stale = [k for k, v in realized.items() if str(v.get("session") or "") != session]
    for k in stale:
        del realized[k]


def update_high_after_stop(
    *,
    code: str,
    stop_px: float,
    high_after: float | None,
    low_after: float | None,
    qty: int,
    px_digits: int,
) -> dict[str, Any] | None:
    """刷新已结算记录中的「止损后最高/最低」，并估算踏空幅度/金额。"""
    if high_after is None and low_after is None:
        return None
    data = load_holdings()
    realized = data.setdefault("realized_today", {})
    rec = realized.get(code)
    if not rec or rec.get("reason") != REASON_STOP:
        return None
    stop_px = float(stop_px)
    if high_after is not None:
        ha = float(high_after)
        old_h = rec.get("high_after_stop")
        if old_h is not None:
            ha = max(float(old_h), ha)
        rec["high_after_stop"] = round(ha, px_digits)
    if low_after is not None:
        la = float(low_after)
        old_l = rec.get("low_after_stop")
        if old_l is not None:
            la = min(float(old_l), la)
        rec["low_after_stop"] = round(la, px_digits)
    sold_qty = int(rec.get("qty") or qty)
    if rec.get("high_after_stop") is not None:
        ha = float(rec["high_after_stop"])
        rebound_pct = (ha / stop_px - 1.0) * 100.0 if stop_px > 0 else None
        miss_pnl = (ha - stop_px) * sold_qty
        rec["rebound_pct"] = None if rebound_pct is None else round(rebound_pct, 2)
        rec["miss_pnl"] = round(miss_pnl, 2)
    save_holdings(data)
    return rec


def apply_exit_fill(
    *,
    code: str,
    meta: dict[str, Any],
    fill_px: float,
    qty: int,
    cost: float | None,
    session: str,
    buy_time: str | None,
    prev_close: float | None,
    open_px: float,
    px_digits: int,
    reason: str,
    trade_note: str,
) -> dict[str, Any]:
    """卖出视为已成交：按成交价锁定盈亏、清仓，并写入当日已实现。"""
    data = load_holdings()
    _purge_stale_realized(data, session)
    realized = data.setdefault("realized_today", {})
    existing = realized.get(code)
    if (
        existing
        and str(existing.get("session") or "") == session
        and existing.get("reason") in EXIT_REASONS
    ):
        return existing

    fill_px = float(fill_px)
    cost_f = float(cost) if cost is not None else None
    pnl = (fill_px - cost_f) * qty if cost_f is not None else None
    pnl_pct = (fill_px / cost_f - 1.0) * 100.0 if cost_f and cost_f > 0 else None

    bought_today = is_t1_buy_day(buy_time, session)
    if bought_today:
        base_px = cost_f if cost_f is not None else float(open_px)
    elif prev_close is not None and float(prev_close) > 0:
        base_px = float(prev_close)
    else:
        base_px = cost_f if cost_f is not None else float(open_px)
    day_base = float(base_px) * qty if base_px else None
    day_pnl = (fill_px - base_px) * qty if base_px else None
    day_pnl_pct = (
        (fill_px / base_px - 1.0) * 100.0 if base_px and base_px > 0 else None
    )

    rec = {
        "session": session,
        "name": meta["name"],
        "market": meta["market"],
        "qty": int(qty),
        "price": round(fill_px, px_digits),
        "cost": None if cost_f is None else round(cost_f, 4),
        "pnl": None if pnl is None else round(float(pnl), 2),
        "pnl_pct": None if pnl_pct is None else round(float(pnl_pct), 2),
        "day_base": None if day_base is None else round(float(day_base), 2),
        "day_pnl": None if day_pnl is None else round(float(day_pnl), 2),
        "day_pnl_pct": None if day_pnl_pct is None else round(float(day_pnl_pct), 2),
        "reason": reason,
        "time": _now(),
    }
    realized[code] = rec

    pos = data["positions"].setdefault(code, _empty_position(meta))
    pos["qty"] = 0
    pos["cost"] = None
    pos["buy_time"] = None
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    pos["note"] = f"{reason}@{rec['price']} ({session})"

    save_holdings(data)
    append_trade(
        {
            "time": rec["time"],
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "price": rec["price"],
            "qty": qty,
            "after_qty": 0,
            "cost": rec["cost"],
            "pnl": rec["pnl"],
            "note": trade_note,
        }
    )
    return rec


def apply_stop_fill(
    *,
    code: str,
    meta: dict[str, Any],
    stop_px: float,
    qty: int,
    cost: float | None,
    session: str,
    buy_time: str | None,
    prev_close: float | None,
    open_px: float,
    px_digits: int,
) -> dict[str, Any]:
    """止损视为已成交：按止损价锁定盈亏、清仓，并写入当日已实现。"""
    return apply_exit_fill(
        code=code,
        meta=meta,
        fill_px=float(stop_px),
        qty=qty,
        cost=cost,
        session=session,
        buy_time=buy_time,
        prev_close=prev_close,
        open_px=open_px,
        px_digits=px_digits,
        reason=REASON_STOP,
        trade_note=f"{REASON_STOP}(自动)",
    )


def apply_yin_fill(
    *,
    code: str,
    meta: dict[str, Any],
    close_px: float,
    qty: int,
    cost: float | None,
    session: str,
    buy_time: str | None,
    prev_close: float | None,
    open_px: float,
    px_digits: int,
) -> dict[str, Any]:
    """尾盘收阴视为已成交：按现价/收盘价锁定盈亏并清仓。"""
    return apply_exit_fill(
        code=code,
        meta=meta,
        fill_px=float(close_px),
        qty=qty,
        cost=cost,
        session=session,
        buy_time=buy_time,
        prev_close=prev_close,
        open_px=open_px,
        px_digits=px_digits,
        reason=REASON_YIN,
        trade_note=f"{REASON_YIN}(自动)",
    )


def apply_gap_down_945_fill(
    *,
    code: str,
    meta: dict[str, Any],
    exit_px: float,
    qty: int,
    cost: float | None,
    session: str,
    buy_time: str | None,
    prev_close: float | None,
    open_px: float,
    px_digits: int,
) -> dict[str, Any]:
    """低开 9:45 未翻红：按 9:45 分钟 K 线收盘价全仓卖出并清仓。"""
    return apply_exit_fill(
        code=code,
        meta=meta,
        fill_px=float(exit_px),
        qty=qty,
        cost=cost,
        session=session,
        buy_time=buy_time,
        prev_close=prev_close,
        open_px=open_px,
        px_digits=px_digits,
        reason=REASON_GAP945,
        trade_note=f"{REASON_GAP945}(自动)",
    )


def append_trade(record: dict[str, Any]) -> None:
    with TRADES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extremes_after_stop_touch(
    day: pd.DataFrame, stop_px: float
) -> tuple[float | None, float | None]:
    """触及止损后（含触及那根分钟）到现在的最高价、最低价。"""
    if day is None or getattr(day, "empty", True):
        return None, None
    stop_px = float(stop_px)
    touched = day[day["low"] <= stop_px + 1e-12]
    if touched.empty:
        return None, None
    first_ts = touched.iloc[0]["ts"]
    after = day[day["ts"] >= first_ts]
    if after.empty:
        return None, None
    return float(after["high"].max()), float(after["low"].min())


def high_after_stop_touch(day: pd.DataFrame, stop_px: float) -> float | None:
    """触及止损后（含触及那根分钟）到现在的最高价。"""
    ha, _ = extremes_after_stop_touch(day, stop_px)
    return ha


def fetch_sina_spot(sina: str) -> dict[str, Any] | None:
    """新浪实时行情（竞价/开盘后分钟线未到时可用）。"""
    try:
        resp = requests.get(
            f"https://hq.sinajs.cn/list={sina}",
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=8,
        )
        text = resp.content.decode("gbk", "ignore").strip()
    except Exception:  # noqa: BLE001
        return None
    if '="' not in text:
        return None
    payload = text.split('="', 1)[1].rstrip('";')
    parts = payload.split(",")
    if len(parts) < 32:
        return None

    def _f(i: int) -> float:
        try:
            return float(parts[i])
        except (TypeError, ValueError):
            return 0.0

    open_px = _f(1)
    prev_close = _f(2)
    last_px = _f(3)
    high_px = _f(4)
    low_px = _f(5)
    bid = _f(6)
    ask = _f(7)
    # 竞价阶段 open/last 常为 0，用买卖一价作撮合参考
    if open_px <= 0:
        open_px = bid or ask or last_px
    if last_px <= 0:
        last_px = open_px or bid or ask
    if high_px <= 0:
        high_px = max(open_px, last_px)
    if low_px <= 0:
        low_px = min(x for x in (open_px, last_px) if x > 0) if open_px or last_px else 0.0
    if open_px <= 0 or last_px <= 0 or prev_close <= 0:
        return None
    session = parts[30] or str(pd.Timestamp.now().date())
    stamp = f"{session} {parts[31]}" if parts[31] else f"{session} 09:25:00"
    return {
        "session": session,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "last": last_px,
        "prev_close": prev_close,
        "last_ts": stamp,
    }


def _day_key_series(ts: pd.Series) -> pd.Series:
    """统一按日历日比较，避免 datetime64[us] 与 Timestamp 直接比较报错。"""
    return pd.to_datetime(ts).dt.strftime("%Y-%m-%d")


def fetch_today_quote(sina: str) -> dict[str, Any]:
    """用1分钟线拼当日开高低收；竞价/开盘初分钟线未到时回退新浪现价。"""
    today = str(pd.Timestamp.now().date())
    spot = fetch_sina_spot(sina)

    day = pd.DataFrame()
    prev_close: float | None = None
    try:
        raw = ak.stock_zh_a_minute(symbol=sina, period="1", adjust="")
    except Exception:  # noqa: BLE001
        raw = None

    if raw is not None and not raw.empty:
        df = raw.copy()
        df["ts"] = pd.to_datetime(df["day"])
        day_keys = _day_key_series(df["ts"])
        day = df[day_keys == today].copy()
        for col in ("open", "high", "low", "close"):
            if not day.empty:
                day[col] = pd.to_numeric(day[col], errors="coerce")
        if not day.empty:
            day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")

        prev = df[day_keys < today].copy()
        if not prev.empty:
            prev["close"] = pd.to_numeric(prev["close"], errors="coerce")
            prev = prev.dropna(subset=["close"]).sort_values("ts")
            if not prev.empty:
                prev_last = _day_key_series(prev["ts"]).iloc[-1]
                prev_day = prev[_day_key_series(prev["ts"]) == prev_last]
                if not prev_day.empty:
                    prev_close = float(prev_day.iloc[-1]["close"])

    # 当日分钟线已到：优先用分钟 OHLC
    if not day.empty:
        open_px = float(day.iloc[0]["open"])
        high_px = float(day["high"].max())
        low_px = float(day["low"].min())
        last_px = float(day.iloc[-1]["close"])
        last_ts = day.iloc[-1]["ts"]
        if prev_close is None and spot is not None:
            prev_close = float(spot["prev_close"])
        day_chg = None
        if prev_close is not None and prev_close > 0:
            day_chg = (last_px / prev_close - 1.0) * 100.0
        return {
            "session": today,
            "open": open_px,
            "high": high_px,
            "low": low_px,
            "last": last_px,
            "prev_close": prev_close,
            "day_chg_pct": day_chg,
            "last_ts": str(last_ts),
            "_day_bars": day,
        }

    # 竞价/开盘初：分钟线尚无今日，用新浪现价
    if spot is not None and spot["session"] == today:
        day_chg = None
        prev_close = float(spot["prev_close"])
        last_px = float(spot["last"])
        if prev_close > 0:
            day_chg = (last_px / prev_close - 1.0) * 100.0
        return {
            "session": today,
            "open": float(spot["open"]),
            "high": float(spot["high"]),
            "low": float(spot["low"]),
            "last": last_px,
            "prev_close": prev_close,
            "day_chg_pct": day_chg,
            "last_ts": str(spot["last_ts"]),
            "_day_bars": pd.DataFrame(),
        }

    # 非交易时段：退回最近一个交易日全日分钟线
    if raw is None or raw.empty:
        raise RuntimeError(f"无分钟行情: {sina}")
    df = raw.copy()
    df["ts"] = pd.to_datetime(df["day"])
    day_keys = _day_key_series(df["ts"])
    last_day = day_keys.max()
    day = df[day_keys == last_day].copy()
    for col in ("open", "high", "low", "close"):
        day[col] = pd.to_numeric(day[col], errors="coerce")
    day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
    if day.empty:
        raise RuntimeError(f"当日无有效分钟线: {sina}")
    prev = df[day_keys < last_day].copy()
    if not prev.empty:
        prev["close"] = pd.to_numeric(prev["close"], errors="coerce")
        prev = prev.dropna(subset=["close"]).sort_values("ts")
        if not prev.empty:
            prev_last = _day_key_series(prev["ts"]).iloc[-1]
            prev_day = prev[_day_key_series(prev["ts"]) == prev_last]
            if not prev_day.empty:
                prev_close = float(prev_day.iloc[-1]["close"])
    open_px = float(day.iloc[0]["open"])
    high_px = float(day["high"].max())
    low_px = float(day["low"].min())
    last_px = float(day.iloc[-1]["close"])
    last_ts = day.iloc[-1]["ts"]
    day_chg = None
    if prev_close is not None and prev_close > 0:
        day_chg = (last_px / prev_close - 1.0) * 100.0
    return {
        "session": last_day,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "last": last_px,
        "prev_close": prev_close,
        "day_chg_pct": day_chg,
        "last_ts": str(last_ts),
        "_day_bars": day,
    }


def points_vs_open(open_px: float, px: float) -> float:
    if open_px <= 0:
        return float("nan")
    return (px / open_px - 1.0) * 100.0


def pct_vs_open(open_px: float, px: float) -> float | None:
    """较开盘涨幅% = (现价/开盘-1)×100。"""
    v = points_vs_open(open_px, px)
    if v != v:
        return None
    return round(float(v), 2)


def fetch_indices() -> list[dict[str, Any]]:
    """拉取上证指数 / 深证成指：最新点数、涨跌点数、涨跌幅。"""
    try:
        spot = ak.stock_zh_index_spot_sina()
    except Exception as e:  # noqa: BLE001
        return [
            {
                "code": x["code"],
                "name": x["name"],
                "market": x["market"],
                "price": None,
                "chg_points": None,
                "chg_pct": None,
                "error": str(e),
            }
            for x in INDEX_WATCH
        ]

    out: list[dict[str, Any]] = []
    code_col = "代码" if "代码" in spot.columns else spot.columns[0]
    for item in INDEX_WATCH:
        row = spot[spot[code_col].astype(str) == item["code"]]
        if row.empty:
            out.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "market": item["market"],
                    "price": None,
                    "chg_points": None,
                    "chg_pct": None,
                    "error": "未找到指数",
                }
            )
            continue
        r = row.iloc[0]
        price = pd.to_numeric(r.get("最新价"), errors="coerce")
        chg_pts = pd.to_numeric(r.get("涨跌额"), errors="coerce")
        chg_pct = pd.to_numeric(r.get("涨跌幅"), errors="coerce")
        out.append(
            {
                "code": item["code"],
                "name": item["name"],
                "market": item["market"],
                "price": None if pd.isna(price) else float(price),
                "chg_points": None if pd.isna(chg_pts) else float(chg_pts),
                "chg_pct": None if pd.isna(chg_pct) else float(chg_pct),
                "error": None,
            }
        )
    return out


def collect_rows() -> list[dict[str, Any]]:
    """拉取行情并合并持仓；已触止损视为成交并锁定当日收益。"""
    holdings = load_holdings()
    positions = holdings.get("positions", {})
    realized_map = holdings.get("realized_today", {})
    rows: list[dict[str, Any]] = []
    session_today: str | None = None

    for w in WATCHLIST:
        code = w["code"]
        entry_pct = _watch_pct(w)
        stop_pct = entry_pct
        tick = _watch_tick(w)
        px_digits = _px_digits(tick)
        pct_pct = round(entry_pct * 100.0, 2)
        try:
            q = fetch_today_quote(w["sina"])
            session_today = q["session"]
            lv = strategy_levels(
                q["open"], entry_pct=entry_pct, stop_pct=stop_pct, tick=tick
            )
            vs = points_vs_open(q["open"], q["last"])
            vs_pct = pct_vs_open(q["open"], q["last"])
            day_chg = q.get("day_chg_pct")
            hit_buy = q["high"] + 1e-12 >= lv["buy_trigger"]
            hit_stop = q["low"] <= lv["stop"] + 1e-12
            pos = positions.get(code, {})
            qty = int(pos.get("qty") or 0)
            buy_time = pos.get("buy_time")
            cost = pos.get("cost")
            t0 = bool(w.get("t0"))
            t1_lock = qty > 0 and (not t0) and is_t1_buy_day(buy_time, q["session"])
            gap945 = eval_gap_down_945(
                open_px=float(q["open"]),
                prev_close=q.get("prev_close"),
                day_bars=q.get("_day_bars"),
                last_px=float(q["last"]),
                high_px=float(q["high"]),
            )

            # 低开 9:45 未翻红且可卖 → 视为成交（优先于止损）
            if qty > 0 and gap945["should_exit"] and not t1_lock:
                apply_gap_down_945_fill(
                    code=code,
                    meta=w,
                    exit_px=float(gap945["exit_px"]),
                    qty=qty,
                    cost=float(cost) if cost is not None else None,
                    session=q["session"],
                    buy_time=buy_time,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    px_digits=px_digits,
                )
                holdings = load_holdings()
                positions = holdings.get("positions", {})
                realized_map = holdings.get("realized_today", {})
                pos = positions.get(code, {})
                qty = int(pos.get("qty") or 0)
                cost = pos.get("cost")
                buy_time = pos.get("buy_time")

            # 已触止损且可卖 → 视为成交，锁定收益并清仓
            if qty > 0 and hit_stop and not t1_lock:
                apply_stop_fill(
                    code=code,
                    meta=w,
                    stop_px=float(lv["stop"]),
                    qty=qty,
                    cost=float(cost) if cost is not None else None,
                    session=q["session"],
                    buy_time=buy_time,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    px_digits=px_digits,
                )
                holdings = load_holdings()
                positions = holdings.get("positions", {})
                realized_map = holdings.get("realized_today", {})
                pos = positions.get(code, {})
                qty = int(pos.get("qty") or 0)
                cost = pos.get("cost")
                buy_time = pos.get("buy_time")

            # 未触止损、可卖、尾盘仍收阴 → 按现价结算（对齐 kskj 阴线收盘卖）
            if (
                qty > 0
                and (not hit_stop)
                and (not t1_lock)
                and is_yin(float(q["open"]), float(q["last"]))
                and is_yin_exit_window()
            ):
                apply_yin_fill(
                    code=code,
                    meta=w,
                    close_px=float(q["last"]),
                    qty=qty,
                    cost=float(cost) if cost is not None else None,
                    session=q["session"],
                    buy_time=buy_time,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    px_digits=px_digits,
                )
                holdings = load_holdings()
                positions = holdings.get("positions", {})
                realized_map = holdings.get("realized_today", {})
                pos = positions.get(code, {})
                qty = int(pos.get("qty") or 0)
                cost = pos.get("cost")
                buy_time = pos.get("buy_time")

            # 当日已卖出结算：收益冻结，不再跟现价
            realized = realized_map.get(code)
            if (
                realized
                and str(realized.get("session") or "") == q["session"]
                and realized.get("reason")
                in ("止损成交", "阴线收盘卖", "低开945未翻红", REASON_GAP945)
            ):
                fill_px = float(realized["price"])
                sold_qty = int(realized.get("qty") or 0)
                reason = str(realized.get("reason") or "")
                # 兼容旧记录：补当日基数
                if realized.get("day_base") is None and realized.get("day_pnl") is not None:
                    dpct = realized.get("day_pnl_pct")
                    if dpct is not None and abs(float(dpct)) > 1e-12:
                        realized["day_base"] = round(
                            float(realized["day_pnl"]) / (float(dpct) / 100.0), 2
                        )
                ha_show = None
                la_show = None
                rebound = None
                miss = None
                if reason == REASON_STOP:
                    ha, la = extremes_after_stop_touch(
                        q.get("_day_bars"), float(lv["stop"])
                    )
                    updated = update_high_after_stop(
                        code=code,
                        stop_px=float(lv["stop"]),
                        high_after=ha,
                        low_after=la,
                        qty=sold_qty,
                        px_digits=px_digits,
                    )
                    if updated:
                        realized = updated
                        realized_map[code] = updated
                    ha_show = realized.get("high_after_stop")
                    la_show = realized.get("low_after_stop")
                    rebound = realized.get("rebound_pct")
                    miss = realized.get("miss_pnl")
                live_last = round(q["last"], px_digits)
                note = (
                    f"已按{reason}@{fill_px:.{px_digits}f}，盈亏已锁定；现价仍实时更新"
                )
                if ha_show is not None:
                    note += f"；止损后最高{float(ha_show):.{px_digits}f}"
                    if rebound is not None:
                        note += f"（回抽{float(rebound):+.2f}%）"
                if la_show is not None:
                    note += f"；最低{float(la_show):.{px_digits}f}"
                rows.append(
                    {
                        "市场": w["market"],
                        "代码": code,
                        "名称": w["name"],
                        "交易日": q["session"],
                        "开盘": round(q["open"], px_digits),
                        "最高": round(q["high"], px_digits),
                        "最低": round(q["low"], px_digits),
                        "现价": live_last,
                        "成交价": round(fill_px, px_digits),
                        "止损后最高": ha_show,
                        "止损后最低": la_show,
                        "回抽%": rebound,
                        "踏空金额": miss,
                        "昨收": None
                        if q.get("prev_close") is None
                        else round(float(q["prev_close"]), px_digits),
                        "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                        "较开盘点": vs_pct,
                        "较开盘涨幅": vs_pct,
                        "阈值%": pct_pct,
                        "买点": lv["buy_trigger"],
                        "止损": lv["stop"],
                        "已触买": "是" if hit_buy else "否",
                        "已触止损": "是" if hit_stop or reason == REASON_STOP else "否",
                        "形态": bar_shape(q["open"], q["last"]),
                        "预警": reason,
                        "建议挂单": None,
                        "挂单说明": note,
                        "近买点": False,
                        "近止损": False,
                        "bg_class": "warn-sell",
                        "持仓": 0,
                        "卖出数量": sold_qty,
                        "成本": realized.get("cost"),
                        "浮盈": realized.get("pnl"),
                        "浮盈%": realized.get("pnl_pct"),
                        "当日盈亏": realized.get("day_pnl"),
                        "当日盈亏%": realized.get("day_pnl_pct"),
                        "当日基数": realized.get("day_base"),
                        "市值": 0.0,
                        "成本额": None,
                        "已实现": True,
                        "价位小数": px_digits,
                        "更新": q["last_ts"][11:19]
                        if len(q["last_ts"]) >= 19
                        else q["last_ts"],
                        "error": None,
                    }
                )
                continue

            sig = strategy_signal(
                open_px=q["open"],
                high_px=q["high"],
                low_px=q["low"],
                last_px=q["last"],
                session=q["session"],
                buy_trigger=lv["buy_trigger"],
                stop_px=lv["stop"],
                qty=qty,
                buy_time=buy_time,
                vs_open_pts=vs,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                px_digits=px_digits,
                t0=t0,
                prev_close=q.get("prev_close"),
                day_bars=q.get("_day_bars"),
            )
            pnl = None
            pnl_pct = None
            market_value = (q["last"] * qty) if qty > 0 else None
            cost_value = None
            day_pnl = None
            day_pnl_pct = None
            day_base = None
            if cost is not None:
                cost_f = float(cost)
                pnl_pct = (q["last"] / cost_f - 1.0) * 100.0
                if qty > 0:
                    pnl = (q["last"] - cost_f) * qty
                    cost_value = cost_f * qty
                else:
                    pnl = q["last"] - cost_f

            if qty > 0:
                bought_today = is_t1_buy_day(buy_time, q["session"])
                if bought_today:
                    base_px = float(cost) if cost is not None else float(q["open"])
                elif q.get("prev_close") is not None and float(q["prev_close"]) > 0:
                    base_px = float(q["prev_close"])
                else:
                    base_px = float(q["open"])
                day_base = base_px * qty
                day_pnl = (q["last"] - base_px) * qty
                day_pnl_pct = (
                    (q["last"] / base_px - 1.0) * 100.0 if base_px > 0 else None
                )

            rows.append(
                {
                    "市场": w["market"],
                    "代码": code,
                    "名称": w["name"],
                    "交易日": q["session"],
                    "开盘": round(q["open"], px_digits),
                    "最高": round(q["high"], px_digits),
                    "最低": round(q["low"], px_digits),
                    "现价": round(q["last"], px_digits),
                    "昨收": None
                    if q.get("prev_close") is None
                    else round(float(q["prev_close"]), px_digits),
                    "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                    "较开盘点": vs_pct,
                    "较开盘涨幅": vs_pct,
                    "阈值%": pct_pct,
                    "买点": lv["buy_trigger"],
                    "止损": lv["stop"],
                    "已触买": "是" if hit_buy else "否",
                    "已触止损": "是" if hit_stop else "否",
                    "形态": sig["形态"],
                    "预警": sig["alert"],
                    "建议挂单": sig["建议挂单"],
                    "挂单说明": sig["挂单说明"],
                    "近买点": sig["pending_buy"],
                    "近止损": sig["pending_sell"],
                    "bg_class": sig["bg_class"],
                    "持仓": qty,
                    "成本": None if cost is None else float(cost),
                    "浮盈": None if pnl is None else round(float(pnl), 2),
                    "浮盈%": None if pnl_pct is None else round(float(pnl_pct), 2),
                    "当日盈亏": None if day_pnl is None else round(float(day_pnl), 2),
                    "当日盈亏%": None
                    if day_pnl_pct is None
                    else round(float(day_pnl_pct), 2),
                    "当日基数": None if day_base is None else round(float(day_base), 2),
                    "市值": None if market_value is None else round(float(market_value), 2),
                    "成本额": None if cost_value is None else round(float(cost_value), 2),
                    "已实现": False,
                    "价位小数": px_digits,
                    "更新": q["last_ts"][11:19]
                    if len(q["last_ts"]) >= 19
                    else q["last_ts"],
                    "error": None,
                }
            )
        except Exception as e:  # noqa: BLE001
            pos = positions.get(code, {})
            rows.append(
                {
                    "市场": w["market"],
                    "代码": code,
                    "名称": w["name"],
                    "交易日": "-",
                    "开盘": None,
                    "最高": None,
                    "最低": None,
                    "现价": None,
                    "当日涨幅": None,
                    "较开盘点": None,
                    "较开盘涨幅": None,
                    "阈值%": pct_pct,
                    "买点": None,
                    "止损": None,
                    "已触买": "-",
                    "已触止损": "-",
                    "形态": "-",
                    "预警": "",
                    "建议挂单": None,
                    "挂单说明": "",
                    "近买点": False,
                    "近止损": False,
                    "bg_class": "",
                    "持仓": int(pos.get("qty") or 0),
                    "成本": pos.get("cost"),
                    "浮盈": None,
                    "浮盈%": None,
                    "昨收": None,
                    "当日盈亏": None,
                    "当日盈亏%": None,
                    "市值": None,
                    "成本额": None,
                    "已实现": False,
                    "价位小数": px_digits,
                    "更新": "-",
                    "error": str(e),
                }
            )

    if session_today:
        data = load_holdings()
        before = dict(data.get("realized_today") or {})
        _purge_stale_realized(data, session_today)
        if data.get("realized_today") != before:
            save_holdings(data)

    total_mv = sum(
        float(r["市值"])
        for r in rows
        if r.get("市值") is not None and int(r.get("持仓") or 0) > 0
    )
    account_total = _sync_account_total(rows)
    pos_base = account_total if account_total and account_total > 0 else (
        total_mv if total_mv > 0 else None
    )
    for r in rows:
        qty = int(r.get("持仓") or 0)
        mv = r.get("市值")
        if qty > 0 and mv is not None and pos_base and pos_base > 0:
            r["仓位%"] = round(float(mv) / pos_base * 100.0, 1)
        else:
            r["仓位%"] = 0.0 if r.get("已实现") else None
    return rows


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None or v == "-":
        return "-"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def _cls_chg(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 0:
        return "up"
    if x < 0:
        return "down"
    return "flat"


def _s(html: str) -> str:
    """包一层敏感数据标记，页内眼睛按钮可隐藏（指数区不使用）。"""
    return f'<span class="sensitive">{html}</span>'


def write_html_report(
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]] | None = None,
    path: Path = REPORT_FILE,
    *,
    refresh_sec: int | None = None,
) -> Path:
    """生成持仓盯盘 HTML。refresh_sec>0 时启用盯盘自动刷新脚本。"""
    indices = indices or []
    total_pnl = 0.0  # 未平仓浮盈 + 今日已结算盈亏
    total_day_pnl = 0.0  # 未平仓当日 + 已结算当日
    total_mv = 0.0
    total_mv_no_cost = 0.0
    total_cost = 0.0  # 未平仓成本 + 已结算成本（用于总盈亏%）
    total_day_base = 0.0
    settled_pnl = 0.0
    settled_day = 0.0
    settled_n = 0
    has_pos = False
    has_day = False
    for r in rows:
        qty = int(r.get("持仓") or 0)
        realized = bool(r.get("已实现"))
        # 总盈亏：持仓浮盈 + 已结算锁定盈亏
        if r.get("浮盈") is not None and (qty > 0 or realized):
            total_pnl += float(r["浮盈"])
            has_pos = True
        if r.get("当日盈亏") is not None and (qty > 0 or realized):
            total_day_pnl += float(r["当日盈亏"])
            has_day = True
            db = r.get("当日基数")
            if db is not None and float(db) > 0:
                total_day_base += float(db)
            else:
                dpct = r.get("当日盈亏%")
                if dpct is not None and abs(float(dpct)) > 1e-12:
                    total_day_base += float(r["当日盈亏"]) / (float(dpct) / 100.0)
                elif r.get("市值") is not None and not realized:
                    total_day_base += float(r["市值"]) - float(r["当日盈亏"])
        if realized:
            settled_n += 1
            if r.get("浮盈") is not None:
                settled_pnl += float(r["浮盈"])
            if r.get("当日盈亏") is not None:
                settled_day += float(r["当日盈亏"])
            if r.get("成本") is not None and r.get("卖出数量"):
                total_cost += float(r["成本"]) * int(r["卖出数量"])
        if r.get("市值") is not None and qty > 0:
            mv = float(r["市值"])
            total_mv += mv
            if r.get("成本额") is None:
                total_mv_no_cost += mv
        if r.get("成本额") is not None and qty > 0:
            total_cost += float(r["成本额"])
    total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else None
    total_day_pct = (
        (total_day_pnl / total_day_base * 100.0) if has_day and total_day_base > 0 else None
    )
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    available_cash = _available_cash(rows, holdings_meta)
    session_for_open = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        str(pd.Timestamp.now().date()),
    )
    _ensure_account_open_session(
        holdings_meta,
        session=session_for_open,
        account_total=account_total,
    )
    holdings_meta = load_holdings()
    account_open = _account_total_open(holdings_meta)
    # 有日初总资产时：合计盈亏=总资产相对日初变动；盈亏%统一用日初总资产做分母
    if account_total is not None and account_open is not None:
        total_pnl = round(float(account_total) - float(account_open), 2)
        has_pos = True
        total_pnl_pct = round(total_pnl / float(account_open) * 100.0, 2)
    if has_day and account_open is not None and account_open > 0:
        total_day_pct = round(total_day_pnl / float(account_open) * 100.0, 2)
    position_pct = (
        round(total_mv / account_total * 100.0, 1)
        if account_total and account_total > 0 and total_mv > 0
        else None
    )
    today_opened = _today_opened_cost(rows, session_for_open)

    index_cards = []
    for ix in indices:
        err = ix.get("error")
        price = ix.get("price")
        pts = ix.get("chg_points")
        pct = ix.get("chg_pct")
        index_cards.append(
            f"""
            <div class="index-card">
              <div class="index-name">
                <span class="market">{escape(str(ix.get('market','')))}</span>
                <strong>{escape(str(ix.get('name','')))}</strong>
                <code>{escape(str(ix.get('code','')))}</code>
              </div>
              {"<div class='err'>" + escape(str(err)) + "</div>" if err else f'''
              <div class="index-metrics">
                <div><span>点数</span><b>{_fmt_num(price, 2)}</b></div>
                <div><span>涨跌点数</span><b class="{_cls_chg(pts)}">{('-' if pts is None else f'{float(pts):+.2f}')}</b></div>
                <div><span>涨跌幅</span><b class="{_cls_chg(pct)}">{('-' if pct is None else f'{float(pct):+.2f}%')}</b></div>
              </div>
              '''}
            </div>
            """
        )

    cards = []
    for r in rows:
        err = r.get("error")
        day_chg = r.get("当日涨幅")
        vs_open = r.get("较开盘点")
        vs_open_pct = r.get("较开盘涨幅")
        pnl = r.get("浮盈")
        pnl_pct = r.get("浮盈%")
        day_pnl = r.get("当日盈亏")
        day_pnl_pct = r.get("当日盈亏%")
        alert = r.get("预警") or ""
        weight = r.get("仓位%")
        weight_txt = "" if weight is None else f" {float(weight):.1f}%"
        status_txt = f"{alert}{weight_txt}" if alert else (weight_txt.strip() or "-")
        bg = r.get("bg_class") or ""
        suggest_px = r.get("建议挂单")
        suggest_note = r.get("挂单说明") or ""
        alert_html = ""
        if alert:
            badge_cls = "tag-alert"
            if bg == "status-hold":
                badge_cls = "tag-hold"
            elif bg == "status-flat":
                badge_cls = "tag-flat"
            wt_html = (
                f'<span class="wt sensitive">{escape(weight_txt)}</span>' if weight_txt else ""
            )
            alert_html = (
                f'<div class="alert-badge {badge_cls}">'
                f"{escape(alert)}{wt_html}</div>"
            )
        pdg = int(r.get("价位小数") or 2)
        suggest_html = ""
        # 仅策略翻转（买卖触发）时展示建议挂单；持有/空仓不占版面
        if suggest_px is not None and bg in ("warn-buy", "warn-sell"):
            suggest_html = (
                f'<div class="suggest-order sensitive">'
                f'建议挂单 <strong>{_fmt_num(suggest_px, pdg)}</strong>'
                f'{" · " + escape(suggest_note) if suggest_note else ""}'
                f"</div>"
            )
        th_pct = r.get("阈值%")
        th_label = f"{float(th_pct):g}" if th_pct is not None else "2.5"
        card_cls = f"card {bg}".strip()
        cards.append(
            f"""
            <article class="{card_cls}">
              <header>
                <div class="title">
                  <span class="market">{escape(str(r['市场']))}</span>
                  <h2>{escape(str(r['名称']))}</h2>
                  <code>{escape(str(r['代码']))}</code>
                  {alert_html}
                </div>
                <div class="price">
                  <div class="last">{_s(_fmt_num(r.get('现价'), pdg))}</div>
                  <div class="chg {_cls_chg(day_pnl if (int(r.get('持仓') or 0) > 0 or r.get('已实现')) else day_chg)}">
                    {_s(f"当日 {('-' if day_pnl is None else f'{float(day_pnl):+.2f}')} {('-' if day_pnl_pct is None else f'{float(day_pnl_pct):+.2f}%')}" if (int(r.get('持仓') or 0) > 0 or r.get('已实现')) else f"当日 {('-' if day_chg is None else f'{float(day_chg):+.2f}%')}")}
                  </div>
                </div>
              </header>
              {"<p class='err'>行情失败: " + escape(str(err)) + "</p>" if err else ""}
              {suggest_html}
              <div class="grid">
                <div><span>开盘</span><b>{_s(_fmt_num(r.get('开盘'), pdg))}</b></div>
                <div><span>最高</span><b>{_s(_fmt_num(r.get('最高'), pdg))}</b></div>
                <div><span>最低</span><b>{_s(_fmt_num(r.get('最低'), pdg))}</b></div>
                <div><span>较开盘点</span><b class="{_cls_chg(vs_open)}">{_s('-' if vs_open is None else f'{float(vs_open):+.2f}')}</b></div>
                <div><span>较开盘涨幅</span><b class="{_cls_chg(vs_open_pct)}">{_s('-' if vs_open_pct is None else f'{float(vs_open_pct):+.2f}%')}</b></div>
                {('<div><span>成交价</span><b>' + _s(_fmt_num(r.get('成交价'), pdg)) + '</b></div>') if r.get('已实现') and r.get('成交价') is not None else ''}
                <div><span>形态</span><b>{escape(str(r.get('形态') or '-'))}</b></div>
                <div><span>买点 +{th_label}%</span><b class="{'tag-buy' if r.get('近买点') else ''}">{_s(_fmt_num(r.get('买点'), pdg))}</b></div>
                <div><span>止损 -{th_label}%</span><b class="{'tag-sell' if r.get('近止损') else ''}">{_s(_fmt_num(r.get('止损'), pdg))}</b></div>
                <div><span>已触买</span><b class="{'tag-yes' if r.get('已触买')=='是' else ''}">{escape(str(r.get('已触买')))}</b></div>
                <div><span>已触止损</span><b class="{'tag-sell' if r.get('已触止损')=='是' else ''}">{escape(str(r.get('已触止损')))}</b></div>
                {('<div><span>止损后最高</span><b>' + _s(_fmt_num(r.get('止损后最高'), pdg)) + '</b></div>') if r.get('已实现') and r.get('止损后最高') is not None else ''}
                {('<div><span>止损后最低</span><b>' + _s(_fmt_num(r.get('止损后最低'), pdg)) + '</b></div>') if r.get('已实现') and r.get('止损后最低') is not None else ''}
                {('<div><span>回抽%</span><b class="' + _cls_chg(r.get('回抽%')) + '">' + _s('-' if r.get('回抽%') is None else f"{float(r.get('回抽%')):+.2f}%") + '</b></div>') if r.get('已实现') and r.get('止损后最高') is not None else ''}
                {('<div><span>踏空金额</span><b class="' + _cls_chg(r.get('踏空金额')) + '">' + _s(_fmt_num(r.get('踏空金额'))) + '</b></div>') if r.get('已实现') and r.get('踏空金额') is not None else ''}
                <div><span>状态</span><b class="{'tag-alert' if bg in ('warn-buy','warn-sell') else ('tag-hold' if bg=='status-hold' else ('tag-flat' if bg=='status-flat' else ''))}">{escape(status_txt)}</b></div>
                <div><span>持仓</span><b>{_s(escape(str(r.get('卖出数量') if r.get('已实现') else r.get('持仓'))) + ('(已卖)' if r.get('已实现') else ''))}</b></div>
                <div><span>成本</span><b>{_s(_fmt_num(r.get('成本'), max(3, pdg)))}</b></div>
                <div><span>浮盈</span><b class="{_cls_chg(pnl)}">{_s(_fmt_num(pnl) + (' (已结算)' if r.get('已实现') else ''))}</b></div>
                <div><span>浮盈%</span><b class="{_cls_chg(pnl_pct)}">{_s('-' if pnl_pct is None else f'{float(pnl_pct):+.2f}%')}</b></div>
                <div><span>当日盈亏</span><b class="{_cls_chg(day_pnl)}">{_s(_fmt_num(day_pnl) + (' (锁定)' if r.get('已实现') else ''))}</b></div>
                <div><span>当日盈亏%</span><b class="{_cls_chg(day_pnl_pct)}">{_s('-' if day_pnl_pct is None else f'{float(day_pnl_pct):+.2f}%')}</b></div>
              </div>
              <footer>更新 {escape(str(r.get('更新') or '-'))}</footer>
            </article>
            """
        )

    refresh_head = ""
    refresh_script = ""
    watch_hint = "刷新请重新运行 <code>python index.py</code> 或 <code>python index.py html</code>。"
    hero_extra = ""
    if refresh_sec is not None and int(refresh_sec) > 0:
        sec = int(refresh_sec)
        refresh_head = (
            f'\n  <meta name="holdings-watch" content="{sec}" />'
        )
        hero_extra = (
            f' · <span class="watch-live">盯盘中</span>'
            f' · 下次更新 <strong id="watch-countdown">{sec}</strong>s'
        )
        watch_hint = (
            f"盯盘模式：服务端每 {sec} 秒重拉行情；倒计时到 0 后自动刷新本页。"
            " 停止请在终端 Ctrl+C。"
        )
        refresh_script = f"""
<script>
(function () {{
  const INTERVAL = {sec};
  const metaUrl = "/holdings_watch.json";
  const cdEl = document.getElementById("watch-countdown");
  const seenKey = "holdings_watch_seen";
  let lastStamp = sessionStorage.getItem(seenKey) || null;
  let left = INTERVAL;
  let reloading = false;

  function renderCd() {{
    if (cdEl) cdEl.textContent = String(Math.max(0, left));
  }}

  function reloadSamePage() {{
    if (reloading) return;
    reloading = true;
    const url = location.pathname + "?t=" + Date.now();
    location.replace(url);
  }}

  function parseStamp(s) {{
    if (!s) return null;
    const m = String(s).match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})[ T](\\d{{2}}):(\\d{{2}}):(\\d{{2}})/);
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
  }}

  async function syncFromServer() {{
    if (reloading) return;
    try {{
      const r = await fetch(metaUrl + "?t=" + Date.now(), {{ cache: "no-store" }});
      if (!r.ok) return;
      const j = await r.json();
      const stamp = j && (j.updated_at || j.ts);
      if (!stamp) return;

      // 只有服务端真的写出新数据才刷新本页（避免倒计时到0空刷）
      if (lastStamp && String(stamp) !== String(lastStamp)) {{
        sessionStorage.setItem(seenKey, String(stamp));
        reloadSamePage();
        return;
      }}
      lastStamp = String(stamp);
      sessionStorage.setItem(seenKey, lastStamp);

      const interval = Number(j.refresh_sec) || INTERVAL;
      const ts = (typeof j.ts === "number") ? j.ts : parseStamp(stamp);
      if (ts) {{
        const elapsed = Math.floor((Date.now() - ts) / 1000);
        // 到点后停在 0，等待服务端更新时间戳，不再强制 reload
        left = Math.max(0, interval - elapsed);
        renderCd();
      }}
    }} catch (e) {{}}
  }}

  renderCd();
  syncFromServer();
  setInterval(function () {{
    if (reloading) return;
    if (left > 0) {{
      left -= 1;
      renderCd();
    }}
    // 每秒轻量同步；到 0 后也持续等新时间戳
    if (left <= 0) syncFromServer();
  }}, 1000);
  setInterval(function () {{
    if (!reloading) syncFromServer();
  }}, 3000);
}})();
</script>
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />{refresh_head}
  <title>持仓盯盘 · {_watchlist_codes_label()}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg0: #f3f6f4;
      --bg1: #e7efe9;
      --ink: #14201a;
      --muted: #5c6f66;
      --line: #c9d6cf;
      --card: rgba(255,255,255,0.82);
      --up: #b42318;
      --down: #0b7a45;
      --accent: #1f6b4a;
      --warn: #9a6700;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Noto Sans SC", sans-serif;
      background:
        radial-gradient(1200px 600px at 10% -10%, #d9ebe0 0%, transparent 55%),
        radial-gradient(900px 500px at 100% 0%, #e4eef8 0%, transparent 50%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
    }}
    .wrap {{ width: min(1100px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 48px; }}
    .hero {{
      margin-bottom: 12px;
    }}
    .hero-row {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }}
    .privacy-toggle {{
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 42px;
      height: 42px;
      margin-top: 2px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--card);
      color: var(--muted);
      cursor: pointer;
      transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
    }}
    .privacy-toggle:hover {{
      color: var(--accent);
      border-color: #b7d2c4;
      background: rgba(255,255,255,0.95);
    }}
    .privacy-toggle svg {{ width: 22px; height: 22px; display: block; }}
    .privacy-toggle .icon-eye-on {{ display: none; }}
    body:not(.privacy-hidden) .privacy-toggle .icon-eye-on {{ display: block; }}
    body:not(.privacy-hidden) .privacy-toggle .icon-eye-off {{ display: none; }}
    body.privacy-hidden .sensitive {{
      filter: blur(7px);
      user-select: none;
      pointer-events: none;
    }}
    body.privacy-hidden .sensitive.up,
    body.privacy-hidden .sensitive.down,
    body.privacy-hidden .sensitive.flat {{
      color: transparent !important;
    }}
    .hero h1 {{
      margin: 0 0 6px; font-size: clamp(1.6rem, 3vw, 2.2rem); letter-spacing: -0.02em;
    }}
    .hero p {{ margin: 0; color: var(--muted); font-size: 0.95rem; }}
    .watch-live {{ color: var(--accent); font-weight: 600; }}
    #watch-countdown {{ color: var(--accent); font-variant-numeric: tabular-nums; }}
    .top-row {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
      align-items: stretch;
    }}
    .summary {{
      min-width: 0;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      backdrop-filter: blur(8px);
    }}
    .summary .label {{ color: var(--muted); font-size: 0.85rem; }}
    .summary .value {{ font-size: 1.55rem; font-weight: 700; margin-top: 4px; }}
    .summary .sub {{ color: var(--muted); font-size: 0.9rem; margin-top: 2px; }}
    .summary .day-line {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px dashed var(--line);
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
    }}
    .summary .day-line .day-label {{ color: var(--muted); font-size: 0.85rem; }}
    .summary .day-line .day-value {{ font-size: 1.05rem; font-weight: 700; }}
    .summary .meta {{ color: var(--muted); font-size: 0.78rem; margin-top: 8px; line-height: 1.4; }}
    .index-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      backdrop-filter: blur(8px);
      padding: 14px 16px;
      min-width: 0;
    }}
    .index-name {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }}
    .index-name strong {{ font-size: 1.05rem; }}
    .index-name code {{ color: var(--muted); font-size: 0.85rem; }}
    .index-metrics {{
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
    }}
    .index-metrics span {{ display: block; color: var(--muted); font-size: 0.78rem; }}
    .index-metrics b {{ font-size: 1.05rem; font-weight: 700; }}
    @media (max-width: 900px) {{
      .top-row {{ grid-template-columns: 1fr; }}
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--card);
      backdrop-filter: blur(8px);
      padding: 10px 12px;
      box-shadow: 0 6px 18px rgba(20, 32, 26, 0.04);
      transition: background 0.25s ease, border-color 0.25s ease;
    }}
    /* 将买入：红底；将卖出：绿底（A股习惯）；持有/空仓为中性态 */
    .card.warn-buy {{
      background: rgba(255, 214, 214, 0.92);
      border-color: #e08a8a;
      box-shadow: 0 8px 20px rgba(180, 35, 24, 0.10);
    }}
    .card.warn-sell {{
      background: rgba(198, 236, 214, 0.92);
      border-color: #6fbf8f;
      box-shadow: 0 8px 20px rgba(11, 122, 69, 0.10);
    }}
    .card.status-hold {{
      background: rgba(255,255,255,0.88);
      border-color: var(--line);
    }}
    .card.status-flat {{
      background: rgba(255,255,255,0.72);
      border-color: #d5ddd8;
    }}
    .card header {{ display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }}
    .market {{
      display: inline-block; font-size: 0.68rem; color: var(--accent);
      border: 1px solid #b7d2c4; border-radius: 999px; padding: 1px 6px; margin-bottom: 3px;
    }}
    .title h2 {{ margin: 0; font-size: 1.0rem; }}
    .title code {{ color: var(--muted); font-size: 0.78rem; }}
    .alert-badge {{
      display: inline-block;
      margin-top: 4px;
      padding: 2px 7px;
      border-radius: 5px;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      color: var(--up);
      background: rgba(180, 35, 24, 0.12);
      border: 1px solid rgba(180, 35, 24, 0.35);
    }}
    .card.warn-buy .alert-badge,
    .card.warn-sell .alert-badge {{
      color: var(--up);
      background: rgba(180, 35, 24, 0.16);
      border-color: rgba(180, 35, 24, 0.45);
    }}
    .card.status-hold .alert-badge {{
      color: var(--accent);
      background: rgba(31, 107, 74, 0.10);
      border-color: rgba(31, 107, 74, 0.30);
    }}
    .card.status-flat .alert-badge {{
      color: var(--muted);
      background: rgba(92, 111, 102, 0.08);
      border-color: rgba(92, 111, 102, 0.25);
    }}
    .alert-badge .wt {{
      margin-left: 2px;
      font-weight: 600;
      opacity: 0.85;
    }}
    .tag-hold {{ color: var(--accent); font-weight: 700; }}
    .tag-flat {{ color: var(--muted); }}
    .suggest-order {{
      margin: 0 0 8px;
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 0.78rem;
      background: rgba(255,255,255,0.55);
      border: 1px dashed var(--line);
    }}
    .suggest-order strong {{ font-size: 0.92rem; margin-left: 4px; }}
    .price {{ text-align: right; }}
    .last {{ font-size: 1.35rem; font-weight: 700; line-height: 1.1; }}
    .chg {{ font-size: 0.8rem; margin-top: 2px; }}
    .grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 4px 8px;
      border-top: 1px dashed var(--line); padding-top: 8px;
    }}
    .grid div span {{ display: block; color: var(--muted); font-size: 0.68rem; }}
    .grid div b {{ font-size: 0.86rem; font-weight: 600; }}
    .up {{ color: var(--up); }}
    .down {{ color: var(--down); }}
    .flat {{ color: var(--muted); }}
    .tag-yes {{ color: var(--accent); }}
    .tag-warn {{ color: var(--warn); }}
    .tag-alert {{ color: var(--up); font-weight: 700; }}
    .tag-buy {{ color: var(--up); }}
    .tag-sell {{ color: var(--down); }}
    .err {{ color: var(--up); font-size: 0.8rem; }}
    footer {{ margin-top: 8px; color: var(--muted); font-size: 0.72rem; }}
    .note {{ margin-top: 18px; color: var(--muted); font-size: 0.86rem; line-height: 1.5; }}
    @media (min-width: 900px) {{
      .cards {{ grid-template-columns: repeat(4, 1fr); }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="hero-row">
        <div>
          <h1>持仓盯盘</h1>
          <p>{_watchlist_codes_label()} ±2.5% · {_now()}{hero_extra}</p>
        </div>
        <button type="button" id="privacy-toggle" class="privacy-toggle" title="点击隐藏持仓数据" aria-label="显示或隐藏持仓数据" aria-pressed="false">
          <svg class="icon-eye-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
            <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
            <line x1="1" y1="1" x2="23" y2="23"/>
          </svg>
          <svg class="icon-eye-on" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="top-row">
      {''.join(index_cards)}
      <div class="summary">
        <div class="label">合计盈亏</div>
        <div class="value {_cls_chg(total_pnl if has_pos else None)}">
          {_s('-' if not has_pos else f'{total_pnl:+.2f}')}
          <span style="font-size:0.95rem;font-weight:600;margin-left:6px;">
            {_s('-' if total_pnl_pct is None else f'{total_pnl_pct:+.2f}%')}
          </span>
        </div>
        <div class="day-line">
          <span class="day-label">当日盈亏</span>
          <span class="day-value {_cls_chg(total_day_pnl if has_day else None)}">
            {_s('-' if not has_day else f'{total_day_pnl:+.2f}')}
            {_s(' ' + ('-' if total_day_pct is None else f'{total_day_pct:+.2f}%'))}
          </span>
        </div>
        <div class="meta sensitive">
          总资产 {_fmt_num(account_total)}
          · 可用 {_fmt_num(available_cash)}
          · 仓位 {('-' if position_pct is None else f'{position_pct:.1f}%')}
          · 市值 {_fmt_num(total_mv if total_mv else None)}
          · 成本 {_fmt_num(total_cost if total_cost else None)}
          · 当日开仓 {_fmt_num(today_opened if today_opened > 0 else None)}
          {f' · 未计成本市值 {_fmt_num(total_mv_no_cost)}' if total_mv_no_cost > 0 else ''}
          {f' · 今日结算{settled_n}笔 盈亏{settled_pnl:+.2f}/当日{settled_day:+.2f}' if settled_n > 0 else ''}
        </div>
      </div>
    </div>
    <div class="cards">
      {''.join(cards)}
    </div>
    <p class="note">
      大盘：点数=最新指数点位；涨跌点数/涨跌幅相对昨收。
      个股：默认 ±2.5%（ceil/floor，同 strategy/open_break.py）。
      合计盈亏=总资产相对日初总资产的变动（有登记日初总资产时）；否则=未平仓浮盈+今日已结算。
      当日盈亏=未平仓当日变动 + 今日已结算锁定；盈亏%分母优先用日初总资产。
      仓位%=个股市值/总资产；已结算标的仓位为 0%。
      总资产=可用现金+持仓市值；当日开仓=今日买入持仓的成本额。
      空仓默认「空仓」，已触买/将买入 → 翻转红底并建议限价@买点；
      有仓默认「持有」，低开≥09:45未翻红 → 按09:45分钟收盘价全清；已触止损 → 自动清仓；将止损 → 翻转绿底预警；
      未触止损但盘中收阴 →「阴线·待尾盘」；≥14:55 仍阴 → 按现价阴线结算。
      {watch_hint}
    </p>
  </div>
  {refresh_script}
<script>
(function () {{
  const KEY = "holdings_privacy_hidden";
  const btn = document.getElementById("privacy-toggle");
  if (!btn) return;

  function isHidden() {{
    const v = localStorage.getItem(KEY);
    if (v === null) return false;
    return v === "1";
  }}

  function apply(hidden) {{
    document.body.classList.toggle("privacy-hidden", hidden);
    localStorage.setItem(KEY, hidden ? "1" : "0");
    btn.setAttribute("aria-pressed", hidden ? "true" : "false");
    btn.title = hidden ? "点击显示持仓数据" : "点击隐藏持仓数据";
  }}

  apply(isHidden());
  btn.addEventListener("click", function () {{
    apply(!document.body.classList.contains("privacy-hidden"));
  }});
}})();
</script>
</body>
</html>
"""
    _atomic_write_text(path, html, encoding="utf-8")
    if refresh_sec is not None and int(refresh_sec) > 0:
        # 必须先写完 HTML，再更新时间戳，避免刷新时读到旧布局/半截文件
        _atomic_write_text(
            WATCH_META_FILE,
            json.dumps(
                {
                    "updated_at": _now(),
                    "refresh_sec": int(refresh_sec),
                    "ts": int(datetime.now().timestamp() * 1000),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return path


def cmd_status(args: argparse.Namespace) -> None:
    rows = collect_rows()
    indices = fetch_indices()
    print(f"\n持仓盯盘  {_now()}")
    print(f"策略参考: kskj2 ±{DEFAULT_PCT*100:.1f}% / 有仓默认持有")
    print(f"  卖出优先: ①低开{GAP_DOWN_EXIT_HOUR:02d}:{GAP_DOWN_EXIT_MINUTE:02d}未翻红 ②止损 ③阴线≥{YIN_EXIT_HOUR:02d}:{YIN_EXIT_MINUTE:02d}")
    print(f"持仓文件: {HOLDINGS_FILE}")
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    available = _available_cash(rows, holdings_meta)
    total_mv = _holdings_market_value(rows)
    position_pct = (
        round(total_mv / account_total * 100.0, 1)
        if account_total and account_total > 0 and total_mv > 0
        else None
    )
    session_for_open = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        str(pd.Timestamp.now().date()),
    )
    today_opened = _today_opened_cost(rows, session_for_open)
    if account_total is not None:
        print(
            f"总资产: {account_total:.2f} 元 · 可用: "
            f"{available if available is not None else '-'} 元 · "
            f"仓位: {('-' if position_pct is None else f'{position_pct:.1f}%')} · "
            f"当日开仓: {today_opened:.2f} 元"
        )
    print("-" * 108)
    print("【大盘】")
    for ix in indices:
        if ix.get("error"):
            print(f"  {ix['name']}: 失败 {ix['error']}")
            continue
        pts = ix["chg_points"]
        pct = ix["chg_pct"]
        print(
            f"  {ix['market']}{ix['name']}: 点数 {_fmt_num(ix['price'])} | "
            f"涨跌点数 {('-' if pts is None else f'{pts:+.2f}')} | "
            f"涨跌幅 {('-' if pct is None else f'{pct:+.2f}%')}"
        )
    print("-" * 108)

    show_rows = []
    for r in rows:
        pdg = int(r.get("价位小数") or 2)

        def _p(v: Any, d: int = pdg) -> str:
            return "-" if v is None else _fmt_num(v, d)

        show_rows.append(
            {
                "市场": r["市场"],
                "代码": r["代码"],
                "名称": r["名称"],
                "开盘": _p(r["开盘"]),
                "现价": _p(r["现价"]),
                "当日涨幅": "-" if r["当日涨幅"] is None else r["当日涨幅"],
                "较开盘点": "-" if r["较开盘点"] is None else r["较开盘点"],
                "较开盘涨幅": "-"
                if r.get("较开盘涨幅") is None
                else f"{float(r['较开盘涨幅']):+.2f}%",
                "阈值%": r.get("阈值%"),
                "最高": _p(r["最高"]),
                "最低": _p(r["最低"]),
                "买点": _p(r["买点"]),
                "止损": _p(r["止损"]),
                "已触买": r["已触买"],
                "已触止损": r["已触止损"],
                "形态": r.get("形态") or "-",
                "状态": (
                    (r.get("预警") or "-")
                    + (
                        f" {float(r['仓位%']):.1f}%"
                        if r.get("仓位%") is not None
                        else ""
                    )
                ),
                "建议挂单": _p(r.get("建议挂单")),
                "挂单说明": r.get("挂单说明") or "-",
                "持仓": r["持仓"],
                "成本": _p(r["成本"], max(3, pdg)),
                "浮盈": r["error"] if r.get("error") else ("-" if r["浮盈"] is None else r["浮盈"]),
                "浮盈%": "-" if r["浮盈%"] is None else r["浮盈%"],
                "当日盈亏": "-" if r.get("当日盈亏") is None else r["当日盈亏"],
                "当日盈亏%": "-" if r.get("当日盈亏%") is None else r["当日盈亏%"],
                "止损后最高": _p(r.get("止损后最高")),
                "止损后最低": _p(r.get("止损后最低")),
                "回抽%": "-" if r.get("回抽%") is None else r.get("回抽%"),
                "踏空": "-" if r.get("踏空金额") is None else r.get("踏空金额"),
                "更新": r["更新"],
            }
        )
    cols = [
        "市场", "代码", "名称", "开盘", "现价", "当日涨幅", "较开盘点", "较开盘涨幅", "阈值%",
        "最高", "最低", "买点", "止损", "已触买", "已触止损", "形态", "状态",
        "建议挂单", "挂单说明", "持仓", "成本", "浮盈", "浮盈%", "当日盈亏", "当日盈亏%",
        "止损后最高", "止损后最低", "回抽%", "踏空", "更新",
    ]
    print(pd.DataFrame(show_rows)[cols].to_string(index=False))
    print("-" * 108)
    day_total = 0.0
    day_n = 0
    stock_pnl = 0.0
    stock_n = 0
    for r in show_rows:
        raw = next((x for x in rows if x["代码"] == r["代码"]), {})
        if raw.get("浮盈") is not None and (
            int(raw.get("持仓") or 0) > 0 or raw.get("已实现")
        ):
            stock_pnl += float(raw["浮盈"])
            stock_n += 1
        if r["当日盈亏"] != "-":
            try:
                day_total += float(r["当日盈亏"])
                day_n += 1
            except (TypeError, ValueError):
                pass
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    account_open = _account_total_open(holdings_meta)
    if account_total is not None and account_open is not None:
        eq_pnl = round(float(account_total) - float(account_open), 2)
        eq_pct = round(eq_pnl / float(account_open) * 100.0, 2)
        print(f"合计盈亏: {eq_pnl:+.2f} ({eq_pct:+.2f}%)  [总资产 {account_total:.2f} vs 日初 {account_open:.2f}]")
    elif stock_n:
        print(f"合计盈亏: {stock_pnl:+.2f}  [持股浮盈+已结算]")
    if day_n:
        if account_open is not None and account_open > 0:
            day_pct = day_total / float(account_open) * 100.0
            pct_txt = f"{day_pct:+.2f}%"
        else:
            pct_txt = "-"
        print(f"合计当日盈亏: {day_total:+.2f} ({pct_txt})")
    else:
        print("合计当日盈亏: -")

    report = write_html_report(rows, indices=indices)
    print(f"HTML 报告: {report}")
    if not getattr(args, "no_open", False):
        webbrowser.open(report.resolve().as_uri())
    print("说明: 当日涨幅=(现价/昨收-1)×100；较开盘涨幅=(现价/开盘-1)×100")
    print("     当日盈亏: 隔夜仓=(现价-昨收)×数量；当日买入=(现价-成本)×数量")
    print("     低开≥09:45且9:45前未翻红=按09:45分钟K线收盘价全清")
    print("     已触止损=视为已成交：按止损价锁定浮盈/当日盈亏并清仓，之后不再随现价变动")
    print("     未触止损但尾盘(≥14:55)仍收阴=按现价阴线结算（对齐 kskj2）")
    print("     有仓默认「持有」；低开·待945/将止损仅预警未成交；盘中暂阴仅预警")
    print("     买点/止损按 ±2.5% ceil/floor（同 strategy/open_break.py）")


def cmd_html(args: argparse.Namespace) -> None:
    rows = collect_rows()
    indices = fetch_indices()
    report = write_html_report(rows, indices=indices)
    print(f"HTML 报告已生成: {report}")
    for ix in indices:
        if ix.get("error"):
            print(f"  {ix['name']}: 失败 {ix['error']}")
            continue
        pts = ix["chg_points"]
        pct = ix["chg_pct"]
        print(
            f"  {ix['name']}: 点数 {_fmt_num(ix['price'])} | "
            f"涨跌点数 {('-' if pts is None else f'{pts:+.2f}')} | "
            f"涨跌幅 {('-' if pct is None else f'{pct:+.2f}%')}"
        )
    if not getattr(args, "no_open", False):
        webbrowser.open(report.resolve().as_uri())


def cmd_set_account(args: argparse.Namespace) -> None:
    total = float(args.total)
    if total <= 0:
        raise ValueError("总资产必须 > 0")
    data = load_holdings()
    data["account_total"] = round(total, 2)
    # 若未单独登记现金，用总资产反推（需已有市值时更准，此处仅记总值）
    save_holdings(data)
    print(f"已设总资产: {data['account_total']:.2f} 元")


def cmd_set_cash(args: argparse.Namespace) -> None:
    cash = float(args.cash)
    if cash < 0:
        raise ValueError("可用现金不能为负")
    data = load_holdings()
    data["account_cash"] = round(cash, 2)
    save_holdings(data)
    print(f"已设可用现金: {data['account_cash']:.2f} 元")


def cmd_set_cost(args: argparse.Namespace) -> None:
    """仅登记/修改成本价（可不填数量）。"""
    meta = _find_meta(args.code)
    code = meta["code"]
    cost = float(args.cost)
    if cost <= 0:
        raise ValueError("成本价必须 > 0")
    data = load_holdings()
    pos = data["positions"].setdefault(
        code,
        {
            "name": meta["name"],
            "market": meta["market"],
            "qty": 0,
            "cost": None,
            "buy_time": None,
            "note": "",
        },
    )
    pos["cost"] = round(cost, 4)
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if args.qty is not None:
        pos["qty"] = int(args.qty)
    if not pos.get("buy_time"):
        pos["buy_time"] = _now()
    if args.note:
        pos["note"] = args.note
    save_holdings(data)
    print(
        f"已设成本: {meta['market']}{code} {meta['name']} "
        f"成本={pos['cost']} 持仓={pos.get('qty', 0)}"
    )


def cmd_buy(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    price = float(args.price)
    qty = int(args.qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")

    data = load_holdings()
    pos = data["positions"].setdefault(
        code,
        {
            "name": meta["name"],
            "market": meta["market"],
            "qty": 0,
            "cost": None,
            "buy_time": None,
            "note": "",
        },
    )
    old_qty = int(pos.get("qty") or 0)
    old_cost = float(pos["cost"]) if pos.get("cost") is not None else None
    new_qty = old_qty + qty
    if old_qty > 0 and old_cost is not None:
        new_cost = (old_cost * old_qty + price * qty) / new_qty
    else:
        new_cost = price
    pos["qty"] = new_qty
    pos["cost"] = round(new_cost, 4)
    pos["buy_time"] = _now()
    if args.note:
        pos["note"] = args.note
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash - price * qty, 2)
    save_holdings(data)
    append_trade(
        {
            "time": _now(),
            "side": "buy",
            "code": code,
            "name": meta["name"],
            "price": price,
            "qty": qty,
            "after_qty": new_qty,
            "avg_cost": pos["cost"],
            "note": args.note or "",
        }
    )
    print(
        f"买入记录: {meta['market']}{code} {meta['name']} "
        f"{qty}股 @ {price:.2f} → 持仓{new_qty} 成本{pos['cost']:.4f}"
    )


def cmd_sell(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    price = float(args.price)
    qty = int(args.qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")

    data = load_holdings()
    pos = data["positions"].get(code)
    if not pos or int(pos.get("qty") or 0) <= 0:
        raise RuntimeError(f"{code} 当前无持仓")
    old_qty = int(pos["qty"])
    if qty > old_qty:
        raise RuntimeError(f"卖出数量 {qty} > 持仓 {old_qty}")
    cost = float(pos["cost"]) if pos.get("cost") is not None else price
    buy_time = pos.get("buy_time")
    pnl = (price - cost) * qty
    new_qty = old_qty - qty
    pos["qty"] = new_qty
    if new_qty == 0:
        pos["cost"] = None
        pos["buy_time"] = None
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash + price * qty, 2)

    # 全清时写入当日已实现，供合计盈亏/卡片锁定展示
    session = str(pd.Timestamp.now().date())
    note = args.note or ""
    if new_qty == 0:
        _purge_stale_realized(data, session)
        reason = REASON_STOP if "止损" in note else "阴线收盘卖"
        bought_today = is_t1_buy_day(buy_time, session)
        base_px = cost if (bought_today or cost) else price
        day_base = float(base_px) * qty
        day_pnl = (price - base_px) * qty
        day_pnl_pct = (price / base_px - 1.0) * 100.0 if base_px > 0 else None
        px_digits = 3 if abs(price) < 10 else 2
        data.setdefault("realized_today", {})[code] = {
            "session": session,
            "name": meta["name"],
            "market": meta["market"],
            "qty": int(qty),
            "price": round(price, px_digits),
            "cost": round(cost, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round((price / cost - 1.0) * 100.0, 2) if cost > 0 else None,
            "day_base": round(day_base, 2),
            "day_pnl": round(day_pnl, 2),
            "day_pnl_pct": None if day_pnl_pct is None else round(day_pnl_pct, 2),
            "reason": reason,
            "time": _now(),
        }
        pos["note"] = f"{reason}@{price} ({session})"

    save_holdings(data)
    append_trade(
        {
            "time": _now(),
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "price": price,
            "qty": qty,
            "after_qty": new_qty,
            "avg_cost": cost,
            "realized_pnl": round(pnl, 2),
            "note": note,
        }
    )
    print(
        f"卖出记录: {meta['market']}{code} {meta['name']} "
        f"{qty}股 @ {price:.2f} 实现盈亏 {pnl:.2f} → 剩余{new_qty}"
    )


def cmd_clear(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    data = load_holdings()
    pos = data["positions"].get(code)
    if not pos:
        print("无记录")
        return
    pos["qty"] = 0
    pos["cost"] = None
    pos["buy_time"] = None
    save_holdings(data)
    print(f"已清空持仓: {code} {meta['name']}")


def cmd_history(_: argparse.Namespace) -> None:
    if not TRADES_FILE.exists():
        print("暂无成交记录")
        return
    lines = TRADES_FILE.read_text(encoding="utf-8").strip().splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]
    if not rows:
        print("暂无成交记录")
        return
    print(pd.DataFrame(rows).to_string(index=False))


def _refresh_once(refresh_sec: int) -> Path:
    rows = collect_rows()
    indices = fetch_indices()
    return write_html_report(rows, indices=indices, refresh_sec=refresh_sec)


def cmd_watch(args: argparse.Namespace) -> None:
    """长驻进程：本地 HTTP + 定时拉行情写报告，浏览器自动刷新。"""
    interval = max(15, int(args.interval))
    host = str(args.host)
    port = int(args.port)
    stop = threading.Event()
    refresh_lock = threading.Lock()

    def safe_refresh() -> Path:
        with refresh_lock:
            return _refresh_once(interval)

    print(f"首次拉取行情…")
    try:
        report = safe_refresh()
        print(f"报告已生成: {report}")
    except Exception as e:
        print(f"首次更新失败: {e}")
        raise

    def loop() -> None:
        while not stop.wait(interval):
            try:
                safe_refresh()
                print(f"[{_now()}] 行情已更新 → {REPORT_FILE.name}")
            except Exception as e:
                print(f"[{_now()}] 更新失败: {e}")

    worker = threading.Thread(target=loop, name="holdings-watch", daemon=True)
    worker.start()

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, fmt: str, *log_args: Any) -> None:
            path = getattr(self, "path", "") or ""
            if WATCH_META_FILE.name in path or REPORT_FILE.name in path:
                return
            if path.startswith("/api/"):
                return
            super().log_message(fmt, *log_args)

        def end_headers(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in (
                f"/{REPORT_FILE.name}",
                f"/{WATCH_META_FILE.name}",
                "/api/refresh",
            ):
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
            super().end_headers()

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle_refresh(self) -> None:
            try:
                safe_refresh()
                print(f"[{_now()}] 手动更新 → {REPORT_FILE.name}")
                self._send_json(200, {"ok": True, "updated_at": _now()})
            except Exception as e:
                print(f"[{_now()}] 手动更新失败: {e}")
                self._send_json(500, {"ok": False, "error": str(e)})

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/api/refresh":
                self._handle_refresh()
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/api/refresh":
                self._handle_refresh()
                return
            self.send_error(404, "Not Found")

    server = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{port}/{REPORT_FILE.name}"
    print(f"盯盘服务已启动: {url}")
    print(f"刷新间隔: {interval}s · Ctrl+C 停止")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        stop.set()
        server.shutdown()
        print("已停止盯盘服务")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="三只股票持仓记录与盯盘")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="查看行情+持仓并生成 HTML（默认）")
    s.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    s.set_defaults(func=cmd_status)

    html_p = sub.add_parser("html", help="生成并打开 HTML 报告")
    html_p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    html_p.set_defaults(func=cmd_html)

    w = sub.add_parser("watch", help="长驻盯盘：每60秒更新行情并自动刷新页面")
    w.add_argument("--interval", type=int, default=60, help="刷新秒数，默认60")
    w.add_argument("--host", default="127.0.0.1", help="监听地址")
    w.add_argument("--port", type=int, default=8765, help="端口，默认8765")
    w.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    w.set_defaults(func=cmd_watch)

    b = sub.add_parser("buy", help="记录买入")
    b.add_argument("code")
    b.add_argument("price", type=float)
    b.add_argument("qty", type=int)
    b.add_argument("--note", default="")
    b.set_defaults(func=cmd_buy)

    e = sub.add_parser("sell", help="记录卖出")
    e.add_argument("code")
    e.add_argument("price", type=float)
    e.add_argument("qty", type=int)
    e.add_argument("--note", default="")
    e.set_defaults(func=cmd_sell)

    c = sub.add_parser("clear", help="清空某标的持仓")
    c.add_argument("code")
    c.set_defaults(func=cmd_clear)

    sc = sub.add_parser("set-cost", help="登记/修改成本价")
    sc.add_argument("code")
    sc.add_argument("cost", type=float)
    sc.add_argument("--qty", type=int, default=None, help="可选：同时登记数量")
    sc.add_argument("--note", default="")
    sc.set_defaults(func=cmd_set_cost)

    sa = sub.add_parser("set-account", help="登记账户总资产")
    sa.add_argument("total", type=float, help="账户总资产（元）")
    sa.set_defaults(func=cmd_set_account)

    scash = sub.add_parser("set-cash", help="登记可用现金")
    scash.add_argument("cash", type=float, help="可用现金（元）")
    scash.set_defaults(func=cmd_set_cash)

    h = sub.add_parser("history", help="查看成交流水")
    h.set_defaults(func=cmd_history)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "cmd", None):
        # 默认走 status，并打开 HTML
        args.no_open = False
        cmd_status(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
