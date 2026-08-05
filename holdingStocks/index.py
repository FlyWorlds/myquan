"""持仓记录与盯盘：与 strategy OpenBreak3「因子1」严格同步。

策略锁定 · 因子1（唯一在用）：
  · 买：high≥ceil(open×1.025)；前日阴/小阳；禁前面双阳；T+1
  · 卖（全清）：仅止损−2.5%
  · 卖出：仅开盘 −2.5% 止损全清

功能：
  · 拉取当日开盘、最高、最低、现价（东财 SSE + 新浪批量兜底；冷启动用分钟线）
  · 规则与回测共用 strategy/open_break.py
  · 有仓：仅止损自动结算（全清）；空仓：已触买/将买入建议限价
  · 本地 JSON 记录持仓；T+1 买入日不可卖

用法：
  python index.py              # 查看标的行情 + 持仓，并生成 HTML
  python index.py html         # 仅生成/打开 HTML 报告
  python index.py watch        # 长驻：行情事件驱动刷新；每日09:26强制刷新盯盘开盘价
  python index.py buy 600552 15.50 400
  python index.py sell 600552 16.20 400
  python index.py set-cost 600552 15.95 --qty 400
  python index.py set-cost 600552 15.445 --qty 800 --available 600 --today-cost 15.78
  python index.py clear 600552
  python index.py history
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import akshare as ak
import pandas as pd
import requests

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from quote_feed import LocalWsHub, QuoteFeedManager, ws_accept_key
from strategy.minute import pull_akshare_1m
from strategy.open_break import (
    DEFAULT_PCT,
    EXIT_REASONS,
    LOT_SIZE,
    NEAR_FACTOR_PCT,
    REASON_STOP,
    TICK_SIZE,
    bar_shape,
    entry_filters_ok,
    format_trigger_md,
    is_t1_buy_day,
    limit_down_state,
    replay_last_factor_triggers,
    strategy_levels,
    strategy_signal,
)
from strategy.data import fetch_daily
from strategy.config import KAICHENG

# 盯盘与回测共用：仅保留开盘−2.5%止损全清
STRATEGY_NAME = "因子1"

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / "holdings.json"
TRADES_FILE = ROOT / "trades.jsonl"
REPORT_FILE = ROOT / "holdings_report.html"
WATCH_META_FILE = ROOT / "holdings_watch.json"
WATCH_PID_FILE = ROOT / "holdings_watch.pid"

# watch 模式本地 WebSocket 广播（/ws）；非 watch 为 None
_ws_hub: LocalWsHub | None = None
_MIN_WATCH_REFRESH_SEC = 1.0
_INDEX_CACHE: dict[str, Any] = {"t": 0.0, "data": []}
_INDEX_CACHE_TTL_SEC = 15.0


def fetch_indices_cached(*, ttl_sec: float = _INDEX_CACHE_TTL_SEC) -> list[dict[str, Any]]:
    """盯盘高频刷新时缓存大盘指数，避免每次重拉拖慢推送。"""
    now = time.monotonic()
    cached = _INDEX_CACHE.get("data") or []
    if cached and (now - float(_INDEX_CACHE.get("t") or 0.0)) < float(ttl_sec):
        return list(cached)
    data = fetch_indices()
    _INDEX_CACHE["t"] = now
    _INDEX_CACHE["data"] = data
    return data


def _empty_position(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": meta["name"],
        "market": meta["market"],
        "qty": 0,
        "available": None,
        "cost": None,
        "today_cost": None,
        "buy_time": None,
        "note": "",
    }


def _sellable_qty(
    pos: dict[str, Any],
    qty: int,
    buy_time: str | None,
    session: str,
    *,
    t0: bool = False,
) -> int:
    """可卖数量：优先用持仓里的 available；否则买入日整仓不可卖。"""
    if qty <= 0:
        return 0
    if t0:
        return int(qty)
    raw = pos.get("available")
    if raw is not None:
        try:
            return max(0, min(int(raw), int(qty)))
        except (TypeError, ValueError):
            pass
    if is_t1_buy_day(buy_time, session):
        return 0
    return int(qty)


def _calc_day_pnl(
    *,
    last: float,
    qty: int,
    available: int,
    cost: float | None,
    prev_close: float | None,
    open_px: float,
    today_cost: float | None = None,
) -> tuple[float | None, float | None, float | None]:
    """分段当日盈亏：可用(=隔夜)按昨收，锁定(=今买)按今日买入价(非均价)。

    返回 (day_pnl, day_pnl_pct, day_base)。
    """
    if qty <= 0:
        return None, None, None
    avail = max(0, min(int(available), int(qty)))
    locked = int(qty) - avail
    last = float(last)
    open_px = float(open_px)
    cost_f = float(cost) if cost is not None else None
    today_f = float(today_cost) if today_cost is not None else None
    prev = float(prev_close) if prev_close is not None and float(prev_close) > 0 else None

    day_pnl = 0.0
    day_base = 0.0
    if avail > 0:
        base_ov = prev if prev is not None else (cost_f if cost_f is not None else open_px)
        day_pnl += (last - base_ov) * avail
        day_base += base_ov * avail
    if locked > 0:
        # 今买部分必须用成交价，不能用持仓均价
        base_td = (
            today_f
            if today_f is not None
            else (cost_f if cost_f is not None else open_px)
        )
        day_pnl += (last - base_td) * locked
        day_base += base_td * locked
    if day_base <= 0:
        return round(day_pnl, 2), None, None
    return round(day_pnl, 2), round(day_pnl / day_base * 100.0, 2), round(day_base, 2)

# 核心策略配置为唯一真相来源：盯盘仅跟随凯盛科技预设。
WATCHLIST: list[dict[str, Any]] = [
    {
        "code": KAICHENG.em_symbol,
        "sina": KAICHENG.symbol,
        "market": "上证",
        "name": KAICHENG.symbol_name,
        "pct": KAICHENG.threshold_pct,
        "tick": KAICHENG.tick,
        "t0": KAICHENG.t0,
        "limit_down_pct": KAICHENG.limit_down_pct,
        "prev_entry_mode": KAICHENG.prev_entry_mode,
    },
]
if KAICHENG.entry_ref != "today_open":
    raise RuntimeError("盯盘尚不支持非 today_open 买点基准，请先同步实现。")

# 竞价结束后强制刷新盯盘开盘价（写入报告/重算止损买点）；随 WATCHLIST 变化
OPEN_PRICE_REFRESH_HOUR = 9
OPEN_PRICE_REFRESH_MINUTE = 26

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


def _watch_limit_down_pct(item: dict[str, Any]) -> float:
    return float(item.get("limit_down_pct", 0.10))


def _px_digits(tick: float) -> int:
    """按最小变动价位决定价格小数位（ETF 0.001 → 3 位）。"""
    if tick <= 0:
        return 2
    if tick >= 1:
        return 0
    return max(0, -int(round(math.log10(tick))))


# 日线缓存：当日只拉一次，供前日过滤与最近因子触发
_DAILY_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}


def _watch_daily(sina: str, *, lookback_days: int = 120) -> pd.DataFrame:
    today = str(pd.Timestamp.now().date())
    cached = _DAILY_CACHE.get(sina)
    if cached and cached[0] == today and cached[1] is not None and not cached[1].empty:
        return cached[1]
    start = (pd.Timestamp.now() - pd.Timedelta(days=lookback_days)).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")
    try:
        df = fetch_daily(sina, start, end)
    except Exception:
        df = pd.DataFrame()
    _DAILY_CACHE[sina] = (today, df)
    return df


def _prev_bars_from_daily(
    daily: pd.DataFrame, session: str
) -> tuple[float | None, float | None, float | None, float | None]:
    """返回 (prev_open, prev_close, prev2_open, prev2_close)。"""
    if daily is None or daily.empty:
        return None, None, None, None
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
    d = d.dropna(subset=["open", "close"]).sort_values("date")
    sess = pd.Timestamp(session).normalize()
    hist = d[d["date"].dt.normalize() < sess]
    if hist.empty:
        return None, None, None, None
    prev = hist.iloc[-1]
    prev2 = hist.iloc[-2] if len(hist) >= 2 else None
    return (
        float(prev["open"]),
        float(prev["close"]),
        float(prev2["open"]) if prev2 is not None else None,
        float(prev2["close"]) if prev2 is not None else None,
    )


def _fill_dual_factor_dist(
    row: dict[str, Any],
    *,
    last_px: float,
    px_digits: int,
    triggered_side: str,
    triggered_px: float | None,
    next_side: str,
    next_px: float | None,
) -> None:
    """写入距已触发 / 距未触发（现价相对因子价）。

    买入侧：现价相对因子涨跌（上为正）；
    卖出侧：取反，表示还需下跌多少才到卖点（现价高于止损时为负）。
    """

    def _one(px: float | None, side: str) -> tuple[float | None, float | None]:
        if px is None or float(px) <= 0:
            return None, None
        dpx = round(float(last_px) - float(px), px_digits)
        dpct = round((float(last_px) / float(px) - 1.0) * 100.0, 2)
        if side == "卖出":
            dpx = round(-dpx, px_digits)
            dpct = round(-dpct, 2)
        return dpx, dpct

    t_px = None if triggered_px is None else round(float(triggered_px), px_digits)
    n_px = None if next_px is None else round(float(next_px), px_digits)
    d_t_px, d_t_pct = _one(t_px, triggered_side)
    d_n_px, d_n_pct = _one(n_px, next_side)
    row["已触发因子侧"] = triggered_side
    row["已触发因子价"] = t_px
    row["未触发因子侧"] = next_side
    row["未触发因子价"] = n_px
    row["距已触发价差"] = d_t_px
    row["距已触发%"] = d_t_pct
    row["距未触发价差"] = d_n_px
    row["距未触发%"] = d_n_pct
    row["距因子价差"] = d_n_px
    row["距因子%"] = d_n_pct


def _factor_memory(code: str) -> dict[str, Any]:
    data = load_holdings()
    mem = data.get("factor_memory") or {}
    rec = mem.get(_code_key(code)) or {}
    return rec if isinstance(rec, dict) else {}


def remember_factor_trigger(
    code: str,
    *,
    side: str,
    px: float,
    session: str,
    force: bool = False,
) -> None:
    """因子触发后固化触发价，供双距字段后续自动切换。"""
    if px is None or float(px) <= 0:
        return
    key = _code_key(code)
    data = load_holdings()
    mem = data.setdefault("factor_memory", {})
    rec = mem.setdefault(key, {})
    px_r = round(float(px), 4)
    side_l = str(side).lower()
    sess = str(session)[:10]
    if side_l in ("buy", "买入"):
        cur_d = str(rec.get("last_buy_factor_date") or "")[:10]
        cur_px = rec.get("last_buy_factor_px")
        # 同日同价跳过；非 force 时同日已有记录不覆盖（防成交价盖掉因子价）
        if cur_d == sess and cur_px is not None:
            if (not force) or abs(float(cur_px) - px_r) <= 1e-9:
                return
        rec["last_buy_factor_px"] = px_r
        rec["last_buy_factor_date"] = sess
    elif side_l in ("sell", "卖出", "stop", REASON_STOP):
        cur_d = str(rec.get("last_sell_factor_date") or "")[:10]
        cur_px = rec.get("last_sell_factor_px")
        if cur_d == sess and cur_px is not None:
            if (not force) or abs(float(cur_px) - px_r) <= 1e-9:
                return
        rec["last_sell_factor_px"] = px_r
        rec["last_sell_factor_date"] = sess
    else:
        return
    save_holdings(data)


def _apply_trigger_date_fields(
    row: dict[str, Any],
    *,
    sig: dict[str, Any],
    session: str,
    last_px: float,
    px_digits: int,
    buy_time: str | None,
    qty: int,
    replay: dict[str, Any],
    code: str | None = None,
    allow_entry: bool = True,
) -> None:
    """因子触发写最近触发日(M/D)；触发后双距自动翻转到「已触发/未触发」下一组。"""
    today_md = format_trigger_md(session)
    pos_st = str(sig.get("持仓状态") or "")
    hit_txt = str(sig.get("因子触发") or "")
    buy_lv = row.get("买点")
    stop_lv = row.get("止损")
    # 前日大阳等过滤未过时，今日买点仅展示、绝不算「已触发」
    hit_buy = bool(allow_entry) and (
        bool(sig.get("hit_buy")) or str(row.get("已触买") or "") == "是"
    )
    hit_stop = bool(sig.get("hit_stop")) or str(row.get("已触止损") or "") == "是"
    realized_px = row.get("成交价")
    sold_today = (
        realized_px is not None
        and float(realized_px) > 0
        and qty <= 0
        and str(row.get("预警") or "") in EXIT_REASONS
    )
    mem = _factor_memory(code) if code else {}

    # 触发瞬间：刚触发的一侧成为「已触发」，对侧今日因子成为「未触发」
    just_sold = bool(hit_stop or sold_today or (pos_st == "待卖出" and hit_txt == "已触发"))
    just_bought = bool(
        allow_entry
        and (hit_buy or (pos_st == "待买入" and hit_txt == "已触发"))
    )

    if just_sold and (qty > 0 or sold_today or pos_st == "待卖出"):
        trig_side, next_side = "卖出", "买入"
        trig_px = (
            float(realized_px)
            if realized_px is not None and float(realized_px) > 0
            else (float(stop_lv) if stop_lv is not None else None)
        )
        next_px = float(buy_lv) if buy_lv is not None else None
        if code and trig_px is not None:
            remember_factor_trigger(code, side="sell", px=trig_px, session=session)
    elif just_bought and qty <= 0:
        trig_side, next_side = "买入", "卖出"
        trig_px = float(buy_lv) if buy_lv is not None else None
        next_px = float(stop_lv) if stop_lv is not None else None
        if code and trig_px is not None:
            remember_factor_trigger(code, side="buy", px=trig_px, session=session)
    elif qty > 0:
        # 持有中：已触发=持仓对应那次买入因子（绝不用今日买点冒充）
        trig_side, next_side = "买入", "卖出"
        buy_day = str(buy_time or "")[:10]
        sess_day = str(session)[:10]
        mem_buy = mem.get("last_buy_factor_px")
        mem_buy_day = str(mem.get("last_buy_factor_date") or "")[:10]
        hist_buy = replay.get("last_buy_px")
        hist_buy_day = str(replay.get("last_buy_date") or "")[:10]
        trig_px = None
        # 记忆必须对上持仓买入日，否则视为脏数据
        if mem_buy is not None and buy_day and mem_buy_day == buy_day:
            trig_px = float(mem_buy)
        elif hist_buy is not None:
            trig_px = float(hist_buy)
        elif mem_buy is not None and (not buy_day) and mem_buy_day != sess_day:
            trig_px = float(mem_buy)
        elif buy_day == sess_day and buy_lv is not None:
            # 仅当日新买可用今日买点
            trig_px = float(buy_lv)
        next_px = float(stop_lv) if stop_lv is not None else None
        # 用持仓买入日因子固化/纠正记忆
        if code and trig_px is not None:
            seed_sess = buy_day or hist_buy_day or sess_day
            need_fix = (
                mem_buy is None
                or (buy_day and mem_buy_day != buy_day)
                or abs(float(mem_buy) - float(trig_px)) > 1e-9
            )
            if need_fix:
                remember_factor_trigger(
                    code, side="buy", px=trig_px, session=seed_sess, force=True
                )
    else:
        # 空仓：已触发=上次卖出因子；未触发=今日买点
        trig_side, next_side = "卖出", "买入"
        mem_sell = mem.get("last_sell_factor_px")
        hist_sell = replay.get("last_sell_px")
        if mem_sell is not None:
            trig_px = float(mem_sell)
        elif hist_sell is not None:
            trig_px = float(hist_sell)
        elif stop_lv is not None:
            trig_px = float(stop_lv)
        else:
            trig_px = None
        next_px = float(buy_lv) if buy_lv is not None else None

    _fill_dual_factor_dist(
        row,
        last_px=last_px,
        px_digits=px_digits,
        triggered_side=trig_side,
        triggered_px=trig_px,
        next_side=next_side,
        next_px=next_px,
    )

    # 盘中预警：已触发/接近 + 今日日期
    if pos_st in ("待买入", "待卖出") and hit_txt in ("已触发", "接近"):
        if hit_txt == "已触发" and today_md:
            row["因子触发"] = f"已触发 {today_md}"
        else:
            row["因子触发"] = hit_txt
        return

    # 有仓：最近买入日（持仓 buy_time / 记忆 / 日线重放）
    if qty > 0:
        md = (
            format_trigger_md(buy_time)
            or format_trigger_md(mem.get("last_buy_factor_date"))
            or format_trigger_md(replay.get("last_buy_date"))
        )
        if hit_txt == "未触发" and md:
            row["因子触发"] = md
        elif hit_txt == "不可用" and md:
            row["因子触发"] = f"不可用 {md}"
        return

    # 空仓：最近一次卖出因子日
    last_d = (
        mem.get("last_sell_factor_date")
        or replay.get("last_sell_date")
        or replay.get("last_trigger_date")
    )
    md = format_trigger_md(last_d)
    if md:
        row["因子触发"] = md
    else:
        row["因子触发"] = hit_txt or "未触发"



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
    data.setdefault("alert_sticky", {})
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


def _alert_sticky_map(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data if data is not None else load_holdings()
    raw = data.get("alert_sticky")
    return raw if isinstance(raw, dict) else {}


def _save_alert_sticky(session: str, sticky: dict[str, Any]) -> None:
    data = load_holdings()
    # 仅保留当日，避免跨日绿底粘住
    kept = {
        k: v
        for k, v in sticky.items()
        if isinstance(v, dict) and str(v.get("session") or "") == session
    }
    data["alert_sticky"] = kept
    save_holdings(data)


def _stabilize_sell_warn(
    *,
    code: str,
    session: str,
    sig: dict[str, Any],
    open_px: float,
    last_px: float,
    stop_px: float,
    vs_open_pts: float,
    stop_lvl: float,
    near_points: float = NEAR_FACTOR_PCT,
    sticky: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """绿底防抖：止损预警短时波动时避免30秒刷新闪没。"""
    sticky = sticky if sticky is not None else _alert_sticky_map()
    prev = sticky.get(code) if isinstance(sticky.get(code), dict) else None
    if prev and str(prev.get("session") or "") != session:
        prev = None

    bg = str(sig.get("bg_class") or "")
    alert = str(sig.get("alert") or "")

    if bg == "warn-sell":
        sticky[code] = {
            "session": session,
            "bg_class": "warn-sell",
            "alert": alert,
            "pending_sell": True,
            "建议挂单": sig.get("建议挂单"),
            "挂单说明": sig.get("挂单说明"),
            "near_stop": bool(sig.get("near_stop")),
        }
        return sig

    # 当前已非卖出预警：若仍处于近止损缓冲带，则保持上一帧绿底
    if prev and prev.get("bg_class") == "warn-sell":
        keep = False
        prev_alert = str(prev.get("alert") or "")
        # 将止损：距止损因子价仍在 near+0.5% 内则保持
        if "将止损" in prev_alert or prev.get("near_stop"):
            if stop_px > 0:
                dist_pct = abs(float(last_px) / float(stop_px) - 1.0) * 100.0
                if dist_pct <= (near_points + 0.5) + 1e-12:
                    keep = True
        # 已触止损：价格仍在止损价下方或附近则保持
        elif "止损" in prev_alert:
            if last_px <= stop_px * 1.003:
                keep = True

        if keep:
            out = dict(sig)
            out["bg_class"] = "warn-sell"
            out["pending_sell"] = True
            out["alert"] = prev_alert or alert or "将卖出"
            if prev.get("建议挂单") is not None and out.get("建议挂单") is None:
                out["建议挂单"] = prev.get("建议挂单")
            if prev.get("挂单说明") and not out.get("挂单说明"):
                out["挂单说明"] = prev.get("挂单说明")
            sticky[code] = {
                "session": session,
                "bg_class": "warn-sell",
                "alert": out["alert"],
                "pending_sell": True,
                "建议挂单": out.get("建议挂单"),
                "挂单说明": out.get("挂单说明"),
                "near_stop": bool(prev.get("near_stop")),
            }
            return out

        sticky.pop(code, None)

    return sig


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
    """当日新开仓成本额（锁定股 = 持仓 − 可用）。"""
    session = session or str(pd.Timestamp.now().date())
    total = 0.0
    positions = load_holdings().get("positions", {})
    for r in rows:
        code = str(r.get("代码") or "")
        qty = int(r.get("持仓") or 0)
        if qty <= 0:
            continue
        pos = positions.get(code) or {}
        sellable = _sellable_qty(
            pos, qty, pos.get("buy_time"), session, t0=False
        )
        locked = max(0, qty - sellable)
        if locked <= 0:
            continue
        if pos.get("today_cost") is not None:
            total += float(pos["today_cost"]) * locked
        elif pos.get("cost") is not None:
            total += float(pos["cost"]) * locked
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
    """卖出视为已成交：按成交价锁定盈亏；可只卖可用股，剩余锁定仓继续持有。"""
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

    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    sell_qty = max(0, min(int(qty), old_qty))
    if sell_qty <= 0:
        return existing or {}

    fill_px = float(fill_px)
    cost_f = float(cost) if cost is not None else None
    pnl = (fill_px - cost_f) * sell_qty if cost_f is not None else None
    pnl_pct = (fill_px / cost_f - 1.0) * 100.0 if cost_f and cost_f > 0 else None

    # 卖出可用(=隔夜)按昨收计当日盈亏；否则按成本
    avail_before = _sellable_qty(pos, old_qty, buy_time, session, t0=False)
    overnight_sell = sell_qty <= avail_before and avail_before > 0
    if overnight_sell and prev_close is not None and float(prev_close) > 0:
        base_px = float(prev_close)
    elif (not overnight_sell) and cost_f is not None:
        base_px = cost_f
    elif prev_close is not None and float(prev_close) > 0:
        base_px = float(prev_close)
    else:
        base_px = cost_f if cost_f is not None else float(open_px)
    day_base = float(base_px) * sell_qty if base_px else None
    day_pnl = (fill_px - base_px) * sell_qty if base_px else None
    day_pnl_pct = (
        (fill_px / base_px - 1.0) * 100.0 if base_px and base_px > 0 else None
    )

    rec = {
        "session": session,
        "name": meta["name"],
        "market": meta["market"],
        "qty": int(sell_qty),
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

    new_qty = old_qty - sell_qty
    pos["qty"] = new_qty
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if new_qty <= 0:
        pos["qty"] = 0
        pos["cost"] = None
        pos["buy_time"] = None
        pos["available"] = None
        pos["today_cost"] = None
        pos["note"] = f"{reason}@{rec['price']} ({session})"
    else:
        raw_avail = pos.get("available")
        if raw_avail is not None:
            try:
                pos["available"] = max(0, int(raw_avail) - sell_qty)
            except (TypeError, ValueError):
                pos["available"] = 0
        else:
            pos["available"] = 0
        # 卖的是隔夜可用仓，今日买入成本保留
        pos["note"] = f"{reason}@{rec['price']}×{sell_qty} 剩{new_qty} ({session})"

    save_holdings(data)
    append_trade(
        {
            "time": rec["time"],
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "price": rec["price"],
            "qty": sell_qty,
            "after_qty": int(pos["qty"]),
            "cost": rec["cost"],
            "pnl": rec["pnl"],
            "note": trade_note,
        }
    )
    if reason == REASON_STOP:
        remember_factor_trigger(code, side="sell", px=fill_px, session=session)
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
    """用1分钟线拼当日开高低；现价优先新浪实时，避免分钟末根滞后。

    分钟线优先框架 akshare：东财 `stock_zh_a_hist_min_em` → 新浪备用。
    """
    today = str(pd.Timestamp.now().date())
    spot = fetch_sina_spot(sina)

    day = pd.DataFrame()
    prev_close: float | None = None
    em_code = sina[2:] if len(sina) >= 8 and sina[:2].lower() in ("sh", "sz") else sina
    # 盯盘用未复权更贴近盘面现价；失败则 pull 内部仍会尝试新浪
    df = pull_akshare_1m(em_symbol=em_code, sina_symbol=sina, adjust="")

    if not df.empty:
        day_keys = _day_key_series(df["ts"])
        day = df[day_keys == today].copy()
        if not day.empty:
            day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
            # 开盘初偶发 open=0 的脏分钟，丢掉无效价
            day = day[
                (day["open"] > 0) & (day["high"] > 0) & (day["low"] > 0) & (day["close"] > 0)
            ]

        prev = df[day_keys < today].copy()
        if not prev.empty:
            prev = prev.dropna(subset=["close"]).sort_values("ts")
            if not prev.empty:
                prev_last = _day_key_series(prev["ts"]).iloc[-1]
                prev_day = prev[_day_key_series(prev["ts"]) == prev_last]
                if not prev_day.empty:
                    prev_close = float(prev_day.iloc[-1]["close"])

    spot_ok = spot is not None and str(spot.get("session") or "") == today

    # 当日分钟线已到：OHLC 用分钟，现价优先新浪实时
    if not day.empty:
        open_px = float(day.iloc[0]["open"])
        high_px = float(day["high"].max())
        low_px = float(day["low"].min())
        last_px = float(day.iloc[-1]["close"])
        last_ts = str(day.iloc[-1]["ts"])
        if spot_ok:
            # 实时现价覆盖滞后的分钟收盘；开盘价固定用首根分钟，避免新浪 open 抖动导致阴/阳翻转（绿底闪没）
            last_px = float(spot["last"])
            last_ts = str(spot["last_ts"])
            high_px = max(high_px, float(spot["high"]) if float(spot["high"]) > 0 else high_px)
            low_cand = float(spot["low"])
            if low_cand > 0:
                low_px = min(low_px, low_cand)
            if prev_close is None:
                prev_close = float(spot["prev_close"])
            # 仅当分钟开盘异常时才用新浪开盘兜底
            if open_px <= 0 and float(spot["open"]) > 0:
                open_px = float(spot["open"])
        elif prev_close is None and spot is not None:
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
            "last_ts": last_ts,
            "_day_bars": day,
        }

    # 竞价/开盘初：分钟线尚无今日，用新浪现价
    if spot_ok:
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
    if df.empty:
        raise RuntimeError(f"无分钟行情: {sina}")
    df = df.copy()
    day_keys = _day_key_series(df["ts"])
    last_day = day_keys.max()
    day = df[day_keys == last_day].copy()
    for col in ("open", "high", "low", "close"):
        day[col] = pd.to_numeric(day[col], errors="coerce")
    day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
    day = day[(day["open"] > 0) & (day["high"] > 0) & (day["low"] > 0) & (day["close"] > 0)]
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


def collect_rows(
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """拉取行情并合并持仓；已触止损视为成交并锁定当日收益。

    get_quote: 可选行情供给（watch 传入 QuoteHub）；默认 fetch_today_quote。
    """
    quote_fn = get_quote or fetch_today_quote
    holdings = load_holdings()
    positions = holdings.get("positions", {})
    realized_map = holdings.get("realized_today", {})
    sticky = _alert_sticky_map(holdings)
    rows: list[dict[str, Any]] = []
    session_today: str | None = None

    for w in WATCHLIST:
        code = w["code"]
        entry_pct = _watch_pct(w)
        stop_pct = entry_pct
        tick = _watch_tick(w)
        limit_down_pct = _watch_limit_down_pct(w)
        prev_entry_mode = str(w.get("prev_entry_mode") or "yin_or_small_yang")
        px_digits = _px_digits(tick)
        pct_pct = round(entry_pct * 100.0, 2)
        try:
            q = quote_fn(w["sina"])
            session_today = q["session"]
            lv = strategy_levels(
                q["open"], entry_pct=entry_pct, stop_pct=stop_pct, tick=tick
            )
            vs = points_vs_open(q["open"], q["last"])
            vs_pct = pct_vs_open(q["open"], q["last"])
            day_chg = q.get("day_chg_pct")
            daily = _watch_daily(w["sina"])
            prev_o, prev_c, prev2_o, prev2_c = _prev_bars_from_daily(daily, q["session"])
            allow_entry = entry_filters_ok(
                prev_o,
                prev_c,
                prev2_o,
                prev2_c,
                entry_pct=entry_pct,
                prev_entry_mode=prev_entry_mode,
            )
            replay = replay_last_factor_triggers(
                daily,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                tick=tick,
                prev_entry_mode=prev_entry_mode,
                limit_down_pct=limit_down_pct,
            )
            hit_buy_raw = q["high"] + 1e-12 >= lv["buy_trigger"]
            hit_buy = bool(allow_entry) and hit_buy_raw
            hit_stop = q["low"] <= lv["stop"] + 1e-12
            limit_state = limit_down_state(
                prev_close=q.get("prev_close"),
                open_px=float(q["open"]),
                high_px=float(q["high"]),
                low_px=float(q["low"]),
                close_px=float(q["last"]),
                limit_down_pct=limit_down_pct,
                tick=tick,
            )
            pos = positions.get(code, {})
            qty = int(pos.get("qty") or 0)
            buy_time = pos.get("buy_time")
            cost = pos.get("cost")
            t0 = bool(w.get("t0"))
            sellable = _sellable_qty(pos, qty, buy_time, q["session"], t0=t0)
            # 一字跌停封单不可卖；触及跌停后开板则按跌停价成交。
            stop_locked = bool(limit_state["locked"])
            stop_base_px = float(
                limit_state["limit_px"]
                if bool(limit_state["opened"])
                else lv["stop"]
            )
            # 盯盘按人工/云条件单的触发价记录，不对买卖触发价额外加滑点。
            stop_fill_px = stop_base_px
            # 已触止损且可卖 → 视为成交，锁定收益（只卖可用）
            if qty > 0 and hit_stop and sellable > 0 and not stop_locked:
                apply_stop_fill(
                    code=code,
                    meta=w,
                    stop_px=stop_fill_px,
                    qty=sellable,
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
                sellable = _sellable_qty(pos, qty, buy_time, q["session"], t0=t0)

            # 当日已卖出结算：全清时冻结收益；部分卖出则继续展示剩余仓
            realized = realized_map.get(code)
            if (
                realized
                and str(realized.get("session") or "") == q["session"]
                and realized.get("reason") in EXIT_REASONS
                and qty <= 0
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
                    # 无分钟线时用 hub/快照当日 high/low 退化
                    if ha is None:
                        try:
                            ha = float(q["high"]) if float(q["high"]) > 0 else None
                            la = float(q["low"]) if float(q["low"]) > 0 else None
                        except (TypeError, ValueError, KeyError):
                            ha, la = None, None
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
                # 已清仓：因子侧/持仓状态按空仓规则重算（预警才标买入）
                sig0 = strategy_signal(
                    open_px=q["open"],
                    high_px=q["high"],
                    low_px=q["low"],
                    last_px=q["last"],
                    session=q["session"],
                    buy_trigger=lv["buy_trigger"],
                    stop_px=lv["stop"],
                    qty=0,
                    buy_time=None,
                    vs_open_pts=vs,
                    entry_pct=entry_pct,
                    stop_pct=stop_pct,
                    px_digits=px_digits,
                    t0=t0,
                    allow_entry=allow_entry,
                )
                row0 = {
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
                        "较开盘点": vs,
                        "较开盘涨幅": vs_pct,
                        "阈值%": pct_pct,
                        "买点": lv["buy_trigger"],
                        "止损": lv["stop"],
                        "已触买": "是" if (qty <= 0 and hit_buy) else "否",
                        "已触止损": "是" if hit_stop or reason == REASON_STOP else "否",
                        "因子侧": sig0.get("因子侧"),
                        "因子价": sig0.get("因子价"),
                        "因子触发": sig0.get("因子触发"),
                        "持仓状态": sig0.get("持仓状态") or "空仓",
                        "已触发因子侧": sig0.get("已触发因子侧"),
                        "已触发因子价": sig0.get("已触发因子价"),
                        "未触发因子侧": sig0.get("未触发因子侧"),
                        "未触发因子价": sig0.get("未触发因子价"),
                        "距已触发价差": sig0.get("距已触发价差"),
                        "距已触发%": sig0.get("距已触发%"),
                        "距未触发价差": sig0.get("距未触发价差"),
                        "距未触发%": sig0.get("距未触发%"),
                        "距因子价差": sig0.get("距因子价差"),
                        "距因子%": sig0.get("距因子%"),
                        "形态": sig0.get("形态") or bar_shape(q["open"], q["last"]),
                        "预警": reason,
                        "建议挂单": sig0.get("建议挂单"),
                        "挂单说明": note,
                        "近买点": bool(sig0.get("pending_buy")),
                        "近止损": False,
                        "bg_class": sig0.get("bg_class") or "status-flat",
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
                _apply_trigger_date_fields(
                    row0,
                    sig=sig0,
                    session=q["session"],
                    last_px=float(q["last"]),
                    px_digits=px_digits,
                    buy_time=None,
                    qty=0,
                    replay=replay,
                    code=code,
                    allow_entry=allow_entry,
                )
                rows.append(row0)
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
                # 有可卖股时不当作整仓 T+1，避免「持有·T+1」误锁信号
                buy_time=None if sellable > 0 else buy_time,
                vs_open_pts=vs,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                px_digits=px_digits,
                t0=t0,
                allow_entry=allow_entry,
            )
            if qty > 0 and hit_stop and stop_locked:
                limit_px = float(limit_state["limit_px"])
                sig = dict(sig)
                sig.update(
                    {
                        "alert": "一字跌停封单·不可卖",
                        "bg_class": "warn-sell",
                        "pending_sell": True,
                        "建议挂单": None,
                        "挂单说明": (
                            f"跌停价{limit_px:.{px_digits}f}封单，"
                            "止损触发但不可成交；持仓延续，待开板"
                        ),
                        "因子触发": "不可成交",
                    }
                )
            sig = _stabilize_sell_warn(
                code=code,
                session=q["session"],
                sig=sig,
                open_px=float(q["open"]),
                last_px=float(q["last"]),
                stop_px=float(lv["stop"]),
                vs_open_pts=float(vs) if vs == vs else 0.0,
                stop_lvl=-stop_pct * 100.0,
                sticky=sticky,
            )
            if qty > 0 and sellable > 0 and sellable < qty:
                # 部分 T+1：状态标为持有·部分T+1
                alert = str(sig.get("alert") or "")
                if alert.startswith("持有"):
                    sig = dict(sig)
                    rest = alert[len("持有") :]
                    sig["alert"] = f"持有·部分T+1{rest}" if rest else "持有·部分T+1"
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
                today_cost = pos.get("today_cost")
                day_pnl, day_pnl_pct, day_base = _calc_day_pnl(
                    last=float(q["last"]),
                    qty=qty,
                    available=sellable,
                    cost=float(cost) if cost is not None else None,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    today_cost=float(today_cost) if today_cost is not None else None,
                )
                # 同日已部分卖出：把已实现当日盈亏并入
                if (
                    realized
                    and str(realized.get("session") or "") == q["session"]
                    and realized.get("reason") in EXIT_REASONS
                ):
                    rd = realized.get("day_pnl")
                    rb = realized.get("day_base")
                    if rd is not None:
                        day_pnl = round(float(day_pnl or 0) + float(rd), 2)
                    if rb is not None:
                        day_base = round(float(day_base or 0) + float(rb), 2)
                    if day_base and day_base > 0 and day_pnl is not None:
                        day_pnl_pct = round(float(day_pnl) / float(day_base) * 100.0, 2)

            row = {
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
                    "较开盘点": vs,
                    "较开盘涨幅": vs_pct,
                    "阈值%": pct_pct,
                    "买点": lv["buy_trigger"],
                    "止损": lv["stop"],
                    "已触买": "是" if (qty <= 0 and hit_buy) else "否",
                    "已触止损": "是" if hit_stop else "否",
                    "因子侧": sig.get("因子侧"),
                    "因子价": sig.get("因子价"),
                    "因子触发": sig.get("因子触发"),
                    "持仓状态": sig.get("持仓状态") or (
                        "持有" if qty > 0 else "空仓"
                    ),
                    "已触发因子侧": sig.get("已触发因子侧"),
                    "已触发因子价": sig.get("已触发因子价"),
                    "未触发因子侧": sig.get("未触发因子侧"),
                    "未触发因子价": sig.get("未触发因子价"),
                    "距已触发价差": sig.get("距已触发价差"),
                    "距已触发%": sig.get("距已触发%"),
                    "距未触发价差": sig.get("距未触发价差"),
                    "距未触发%": sig.get("距未触发%"),
                    "距因子价差": sig.get("距因子价差"),
                    "距因子%": sig.get("距因子%"),
                    "形态": sig["形态"],
                    "预警": sig["alert"],
                    "建议挂单": sig["建议挂单"],
                    "挂单说明": sig["挂单说明"],
                    "近买点": sig["pending_buy"],
                    "近止损": sig["pending_sell"],
                    "bg_class": sig["bg_class"],
                    "持仓": qty,
                    "可用": sellable if qty > 0 else 0,
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
            _apply_trigger_date_fields(
                row,
                sig=sig,
                session=q["session"],
                last_px=float(q["last"]),
                px_digits=px_digits,
                buy_time=buy_time,
                qty=qty,
                replay=replay,
                code=code,
                allow_entry=allow_entry,
            )
            rows.append(row)
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
                    "因子侧": "-",
                    "因子价": None,
                    "因子触发": "-",
                    "持仓状态": "-",
                    "已触发因子侧": "-",
                    "已触发因子价": None,
                    "未触发因子侧": "-",
                    "未触发因子价": None,
                    "距已触发价差": None,
                    "距已触发%": None,
                    "距未触发价差": None,
                    "距未触发%": None,
                    "距因子价差": None,
                    "距因子%": None,
                    "形态": "-",
                    "预警": "",
                    "建议挂单": None,
                    "挂单说明": "",
                    "近买点": False,
                    "近止损": False,
                    "bg_class": "",
                    "持仓": int(pos.get("qty") or 0),
                    "可用": 0,
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
        _save_alert_sticky(session_today, sticky)

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
        pos_status = str(r.get("持仓状态") or "")
        weight = r.get("仓位%")
        weight_txt = "" if weight is None else f" {float(weight):.1f}%"
        bg = r.get("bg_class") or ""
        suggest_px = r.get("建议挂单")
        suggest_note = r.get("挂单说明") or ""
        # 角标：持仓状态为主；附带策略明细（已触买/将止损/T+1 等）
        if alert.startswith("持有"):
            badge_txt = alert
            badge_cls = "tag-hold"
        elif pos_status == "持有":
            badge_txt = "持有"
            badge_cls = "tag-hold"
        elif pos_status == "待卖出":
            badge_txt = f"待卖出 · {alert}" if alert and alert != "待卖出" else "待卖出"
            badge_cls = "tag-alert"
        elif pos_status == "待买入":
            badge_txt = f"待买入 · {alert}" if alert and alert not in ("空仓", "待买入") else "待买入"
            badge_cls = "tag-alert"
        elif pos_status == "空仓":
            badge_txt = "空仓"
            badge_cls = "tag-flat"
        else:
            badge_txt = alert or pos_status or "-"
            badge_cls = "tag-alert"
        alert_html = ""
        if badge_txt and badge_txt != "-":
            wt_html = (
                f'<span class="wt sensitive">{escape(weight_txt)}</span>' if weight_txt else ""
            )
            alert_html = (
                f'<div class="alert-badge {badge_cls}">'
                f"{escape(badge_txt)}{wt_html}</div>"
            )
        pdg = int(r.get("价位小数") or 2)
        qty_card = int(r.get("持仓") or 0)
        suggest_html = ""
        # 待买入/待卖出：建议挂单=因子价；持有：展示卖出因子价（策略止损）
        factor_px_row = r.get("因子价")
        stop_px_row = r.get("止损")
        sell_factor_px = (
            factor_px_row
            if factor_px_row is not None
            else stop_px_row
        )
        if (
            suggest_px is not None
            and pos_status in ("待买入", "待卖出")
            and bg in ("warn-buy", "warn-sell")
            and factor_px_row is not None
            and abs(float(suggest_px) - float(factor_px_row)) <= 1e-9
        ):
            suggest_html = (
                f'<div class="suggest-order sensitive">'
                f'建议挂单 <strong>{_fmt_num(suggest_px, pdg)}</strong>'
                f'{" · " + escape(suggest_note) if suggest_note else ""}'
                f"</div>"
            )
        elif qty_card > 0 and sell_factor_px is not None and pos_status == "持有":
            thr = r.get("阈值%")
            thr_txt = (
                f"开盘−{float(thr):g}%"
                if thr is not None
                else f"开盘−{DEFAULT_PCT * 100:.1f}%"
            )
            t1_note = " · T+1暂不可卖" if "T+1" in alert else " · 可预埋条件卖"
            suggest_html = (
                f'<div class="suggest-order sensitive">'
                f'卖出因子价 <strong>{_fmt_num(sell_factor_px, pdg)}</strong>'
                f' · {escape(thr_txt)}止损{escape(t1_note)}'
                f"</div>"
            )
        card_cls = f"card {bg}".strip()
        factor_side = str(r.get("因子侧") or "-")
        factor_px = r.get("因子价")
        if factor_px is None and qty_card > 0:
            factor_px = stop_px_row
        factor_hit = str(r.get("因子触发") or "-")
        hit_live = factor_hit == "已触发" or str(factor_hit).startswith("已触发 ")
        near_live = factor_hit == "接近"
        hit_cls = (
            "tag-buy"
            if factor_side == "买入" and (hit_live or near_live)
            else (
                "tag-sell"
                if factor_side == "卖出" and (hit_live or near_live)
                else (
                    "tag-flat"
                    if factor_hit.startswith("不可用")
                    else ("tag-hold" if factor_side == "持有" or factor_hit not in ("-", "未触发", "") else "")
                )
            )
        )
        side_cls = (
            "tag-buy"
            if factor_side == "买入"
            else (
                "tag-sell"
                if factor_side == "卖出"
                else (
                    "tag-hold"
                    if factor_side == "持有"
                    else ("tag-flat" if factor_side == "空仓" else "")
                )
            )
        )
        # 有仓：因子价即卖出止损价，价格用卖出色标示
        factor_px_cls = (
            "tag-sell"
            if qty_card > 0 and factor_px is not None
            else side_cls
        )
        factor_px_label = (
            "卖出因子价"
            if qty_card > 0
            else ("买入因子价" if pos_status in ("待买入", "空仓") else "因子价")
        )
        pos_cls = (
            "tag-hold"
            if pos_status == "持有"
            else (
                "tag-alert"
                if pos_status in ("待卖出", "待买入")
                else ("tag-flat" if pos_status == "空仓" else "")
            )
        )
        trig_side = str(r.get("已触发因子侧") or ("买入" if qty_card > 0 else "卖出"))
        next_side = str(r.get("未触发因子侧") or ("卖出" if qty_card > 0 else "买入"))
        trig_ref = r.get("已触发因子价")
        next_ref = r.get("未触发因子价")
        d_trig_px = r.get("距已触发价差")
        d_trig_pct = r.get("距已触发%")
        d_next_px = r.get("距未触发价差")
        d_next_pct = r.get("距未触发%")

        def _dist_cell(
            label: str, side: str, ref_px: Any, dpx: Any, dpct: Any
        ) -> str:
            side_tag = "tag-buy" if side == "买入" else ("tag-sell" if side == "卖出" else "")
            ref_txt = (
                f"因子@{_fmt_num(ref_px, pdg)}" if ref_px is not None else ""
            )
            if dpx is not None and dpct is not None:
                body = (
                    f'<b class="{_cls_chg(dpct)}">'
                    f'{_s(f"{float(dpx):+.{pdg}f} ({float(dpct):+.2f}%)")}'
                    f"</b>"
                    f'<em class="{side_tag}">{escape(side)}{escape(ref_txt)}</em>'
                )
            else:
                body = (
                    f"<b>-</b>"
                    f'<em class="{side_tag}">{escape(side)}{escape(ref_txt)}</em>'
                )
            return (
                f'<div class="dist-factor">'
                f"<span>{escape(label)}</span>{body}</div>"
            )

        dist_html = (
            _dist_cell("距已触发因子", trig_side, trig_ref, d_trig_px, d_trig_pct)
            + _dist_cell("距未触发因子", next_side, next_ref, d_next_px, d_next_pct)
        )
        cards.append(
            f"""
            <article class="{card_cls}">
              <header>
                <div class="title">
                  <span class="market">{escape(str(r['市场']))}</span>
                  <h2 class="sensitive">{escape(str(r['名称']))}</h2>
                  <code class="sensitive">{escape(str(r['代码']))}</code>
                  {alert_html}
                </div>
                <div class="price">
                  <div class="last">{_s(_fmt_num(r.get('现价'), pdg))}</div>
                  <div class="chg {_cls_chg(day_chg)}">
                    {_s('-' if day_chg is None else f'{float(day_chg):+.2f}%')}
                  </div>
                </div>
              </header>
              {"<p class='err'>行情失败: " + escape(str(err)) + "</p>" if err else ""}
              {suggest_html}
              <div class="grid">
                <div><span>持仓状态</span><b class="{pos_cls}">{escape(pos_status or '-')}</b></div>
                <div><span>持股数</span><b>{_s(str(int(r.get('持仓') or 0)))}</b></div>
                <div><span>可卖</span><b>{_s(str(int(r.get('可用') or 0)) if int(r.get('持仓') or 0) > 0 else '-')}</b></div>
                <div><span>当日涨幅</span><b class="{_cls_chg(day_chg)}">{_s('-' if day_chg is None else f'{float(day_chg):+.2f}%')}</b></div>
                <div><span>开盘</span><b>{_s(_fmt_num(r.get('开盘'), pdg))}</b></div>
                <div><span>较开盘涨幅</span><b class="{_cls_chg(vs_open_pct)}">{_s('-' if vs_open_pct is None else f'{float(vs_open_pct):+.2f}%')}</b></div>
                <div><span>因子侧</span><b class="{side_cls}">{escape(factor_side)}</b></div>
                <div><span>{factor_px_label}</span><b class="{factor_px_cls}">{_s(_fmt_num(factor_px, pdg) if factor_px is not None else '-')}</b></div>
                <div><span>因子触发</span><b class="{hit_cls}">{escape(factor_hit)}</b></div>
                {dist_html}
              </div>
              <footer>更新 {escape(str(r.get('更新') or '-'))}</footer>
            </article>
            """
        )

    clock_now = _now()
    indices_html = "".join(index_cards)
    cards_html = "".join(cards)
    summary_html = f"""
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
    """
    top_html = indices_html + summary_html

    refresh_head = ""
    refresh_script = ""
    watch_hint = "刷新请重新运行 <code>python index.py</code> 或 <code>python index.py html</code>。"
    hero_extra = ""
    live_payload: dict[str, Any] | None = None
    if refresh_sec is not None and int(refresh_sec) > 0:
        sec = int(refresh_sec)
        refresh_head = ""
        hero_extra = (
            f' · <span class="watch-live">盯盘中</span>'
            f' · <span id="watch-status">WebSocket 连接中…</span>'
        )
        watch_hint = (
            "盯盘模式：WebSocket 推送就地更新数据，"
            "<strong>不会自动整页刷新</strong>（需整页时请手动 F5）。"
            " 停止请在终端 Ctrl+C。"
        )
        live_payload = {
            "type": "live",
            "ts": int(datetime.now().timestamp() * 1000),
            "updated_at": clock_now,
            "clock": clock_now,
            "top_html": top_html,
            "cards_html": cards_html,
            "refresh_sec": sec,
        }
        refresh_script = f"""
<script>
(function () {{
  const metaUrl = "/holdings_watch.json";
  const wsPath = (location.protocol === "https:" ? "wss://" : "ws://")
    + location.host + "/ws";
  const statusEl = document.getElementById("watch-status");
  const clockEl = document.getElementById("live-clock");
  let useWs = false;
  let ws = null;
  let wsRetry = 0;
  let syncing = false;
  let lastTs = null;

  function setStatus(text) {{
    if (statusEl) statusEl.textContent = text;
  }}

  function applyLive(j) {{
    if (!j || j.type !== "live") return;
    if (j.ts != null && lastTs != null && String(j.ts) === String(lastTs)) return;
    lastTs = j.ts != null ? String(j.ts) : lastTs;
    const top = document.getElementById("live-top-row");
    const cards = document.getElementById("live-cards");
    if (top && typeof j.top_html === "string") top.innerHTML = j.top_html;
    if (cards && typeof j.cards_html === "string") cards.innerHTML = j.cards_html;
    if (clockEl && j.clock) clockEl.textContent = j.clock;
    if (j.updated_at) setStatus("实时 " + j.updated_at);
  }}

  async function syncFallback() {{
    if (useWs || syncing) return;
    syncing = true;
    try {{
      const r = await fetch(metaUrl + "?t=" + Date.now(), {{ cache: "no-store" }});
      if (!r.ok) return;
      const j = await r.json();
      applyLive(j);
      setStatus("兜底同步 " + (j.updated_at || ""));
    }} catch (e) {{
      setStatus("推送断开，等待重连…");
    }} finally {{
      syncing = false;
    }}
  }}

  function connectWs() {{
    try {{
      ws = new WebSocket(wsPath);
    }} catch (e) {{
      useWs = false;
      setStatus("WebSocket 不可用，改用兜底同步");
      return;
    }}
    ws.onopen = function () {{
      useWs = true;
      wsRetry = 0;
      setStatus("WebSocket 已连接");
    }};
    ws.onmessage = function (ev) {{
      try {{
        applyLive(JSON.parse(ev.data || "{{}}"));
      }} catch (e) {{}}
    }};
    ws.onclose = function () {{
      useWs = false;
      ws = null;
      setStatus("推送断开，重连中…");
      const delay = Math.min(15000, 1000 * Math.pow(2, wsRetry++));
      setTimeout(connectWs, delay);
    }};
    ws.onerror = function () {{
      try {{ ws && ws.close(); }} catch (e) {{}}
    }};
  }}

  connectWs();
  // 仅在 WS 断开时用 JSON 就地补数，绝不 location.reload
  setInterval(function () {{
    if (!useWs) syncFallback();
  }}, Math.max(3000, {sec} * 1000));
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
    body.privacy-hidden h2.sensitive,
    body.privacy-hidden code.sensitive {{
      filter: blur(8px);
      color: transparent;
      text-shadow: 0 0 10px rgba(28, 35, 51, 0.55);
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
    #watch-status {{ color: var(--accent); font-variant-numeric: tabular-nums; }}
    #live-clock {{ font-variant-numeric: tabular-nums; }}
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
    .grid .dist-factor {{
      grid-column: 1 / -1;
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }}
    .grid .dist-factor span {{ display: inline; margin-right: 6px; }}
    .grid .dist-factor b {{
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.01em;
      flex: 1;
      text-align: right;
    }}
    .grid .dist-factor em {{
      font-style: normal;
      font-size: 0.72rem;
      font-weight: 600;
      min-width: 2em;
      text-align: right;
    }}
    .up {{ color: var(--up); }}
    .down {{ color: var(--down); }}
    .flat {{ color: var(--muted); }}
    .tag-yes {{ color: var(--accent); }}
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
          <p><span class="sensitive">{escape(_watchlist_codes_label())}</span> · {STRATEGY_NAME} ±{DEFAULT_PCT*100:.1f}% · 仅止损全清 · <span id="live-clock">{escape(clock_now)}</span>{hero_extra}</p>
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
    <div class="top-row" id="live-top-row">
      {top_html}
    </div>
    <div class="cards" id="live-cards">
      {cards_html}
    </div>
    <p class="note">
      策略锁定 {STRATEGY_NAME}（与 strategy/open_break 回测同源；卖出仅保留止损）。
      持仓状态：待买入=空仓且进入买入预警带；待卖出=有仓且进入止损预警；否则空仓或持有。
      因子侧：待卖出预警→卖出；待买入预警→买入；其余→持有或空仓。
      因子触发：盘中预警写「已触发 M/D」；否则为最近一次因子触发日（无年份）。
      卖出全清：仅止损。
      距已触发/未触发：因子一旦触发即自动翻转（买→已触发=买点、未触发=止损；卖→已触发=止损、未触发=买点），并写入 factor_memory。
      卖出侧距%为负=还需下跌到止损；买入侧距%为正=相对买点已上涨/还需上涨。
      因子价=买点（空仓预警）或止损价；持有态额外展示「卖出因子价」=开盘−阈值止损，可预埋条件卖。
      |距未触发%|≤{NEAR_FACTOR_PCT:g}% → 将买入/将止损。
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
    if live_payload is not None:
        # 先写完 HTML，再推送完整 live 载荷（页面就地改 DOM，不整页刷新）
        _atomic_write_text(
            WATCH_META_FILE,
            json.dumps(live_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        hub = _ws_hub
        if hub is not None:
            try:
                hub.broadcast_json(live_payload)
            except Exception:  # noqa: BLE001
                pass
    return path


def cmd_status(args: argparse.Namespace) -> None:
    rows = collect_rows()
    indices = fetch_indices()
    print(f"\n持仓盯盘  {_now()}")
    print(
        f"策略: {STRATEGY_NAME} ±{DEFAULT_PCT*100:.1f}% "
        f"（卖出仅保留止损）"
    )
    print(
        f"  卖出全清: 仅止损"
    )
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

    report = _write_html_respecting_watch(rows, indices=indices)
    print(f"HTML 报告: {report}")
    if not getattr(args, "no_open", False):
        url = _report_url_if_watching()
        webbrowser.open(url if url else report.resolve().as_uri())
    print(f"策略: {STRATEGY_NAME} ±{DEFAULT_PCT*100:.1f}%（与 open_break 回测同源）")
    print("说明: 当日涨幅=(现价/昨收-1)×100；较开盘涨幅=(现价/开盘-1)×100")
    print("     当日盈亏: 隔夜仓=(现价-昨收)×可用；今买=(现价-今买成交价)×锁定")
    print(
        f"     卖出全清: 仅止损"
    )
    print("     已触止损=视为成交并锁定盈亏；盘中预警未成交仅提示")
    print("     买入过滤: 前日阴/小阳 + 禁前面双阳；T+1 当日不可卖")


def cmd_html(args: argparse.Namespace) -> None:
    rows = collect_rows()
    indices = fetch_indices()
    report = _write_html_respecting_watch(rows, indices=indices)
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
        url = _report_url_if_watching()
        webbrowser.open(url if url else report.resolve().as_uri())


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
    pos = data["positions"].setdefault(code, _empty_position(meta))
    pos["cost"] = round(cost, 4)
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if args.qty is not None:
        pos["qty"] = int(args.qty)
    if getattr(args, "available", None) is not None:
        avail = int(args.available)
        qty_now = int(pos.get("qty") or 0)
        if avail < 0 or (qty_now > 0 and avail > qty_now):
            raise ValueError(f"可用数量须在 0..持仓({qty_now}) 之间")
        pos["available"] = avail
    if getattr(args, "today_cost", None) is not None:
        tc = float(args.today_cost)
        if tc <= 0:
            raise ValueError("今日买入价必须 > 0")
        pos["today_cost"] = round(tc, 4)
    if not pos.get("buy_time"):
        pos["buy_time"] = _now()
    if args.note:
        pos["note"] = args.note
    save_holdings(data)
    avail_s = pos.get("available")
    tc_s = pos.get("today_cost")
    print(
        f"已设成本: {meta['market']}{code} {meta['name']} "
        f"成本={pos['cost']} 持仓={pos.get('qty', 0)}"
        + (f" 可用={avail_s}" if avail_s is not None else "")
        + (f" 今买价={tc_s}" if tc_s is not None else "")
    )


def cmd_buy(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    price = float(args.price)
    qty = int(args.qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")

    data = load_holdings()
    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    old_cost = float(pos["cost"]) if pos.get("cost") is not None else None
    # 加仓前可卖股保留；新买部分 T+1 锁定
    if old_qty > 0:
        if pos.get("available") is not None:
            try:
                old_avail = max(0, min(int(pos["available"]), old_qty))
            except (TypeError, ValueError):
                old_avail = old_qty
        else:
            session = str(pd.Timestamp.now().date())
            old_avail = (
                0
                if is_t1_buy_day(pos.get("buy_time"), session)
                else old_qty
            )
    else:
        old_avail = 0
    locked_before = max(0, old_qty - old_avail)
    old_today = (
        float(pos["today_cost"]) if pos.get("today_cost") is not None else None
    )
    new_qty = old_qty + qty
    if old_qty > 0 and old_cost is not None:
        new_cost = (old_cost * old_qty + price * qty) / new_qty
    else:
        new_cost = price
    # 今日买入均价（仅锁定股的成交价加权）
    if locked_before > 0 and old_today is not None:
        pos["today_cost"] = round(
            (old_today * locked_before + price * qty) / (locked_before + qty), 4
        )
    else:
        pos["today_cost"] = round(price, 4)
    pos["qty"] = new_qty
    pos["cost"] = round(new_cost, 4)
    pos["available"] = int(old_avail)
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
        f"{qty}股 @ {price:.2f} → 持仓{new_qty} 可用{pos['available']} "
        f"成本{pos['cost']:.4f} 今买价{pos['today_cost']:.4f}"
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
    raw_avail = pos.get("available")
    if raw_avail is not None:
        try:
            pos["available"] = max(0, min(int(raw_avail) - qty, new_qty))
        except (TypeError, ValueError):
            pos["available"] = 0 if new_qty > 0 else None
    if new_qty == 0:
        pos["cost"] = None
        pos["buy_time"] = None
        pos["available"] = None
        pos["today_cost"] = None
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash + price * qty, 2)

    # 全清时写入当日已实现，供合计盈亏/卡片锁定展示
    session = str(pd.Timestamp.now().date())
    note = args.note or ""
    if new_qty == 0:
        _purge_stale_realized(data, session)
        reason = REASON_STOP if "止损" in note else "手动卖出"
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
    pos["available"] = None
    pos["today_cost"] = None
    pos["note"] = ""
    sticky = data.get("alert_sticky")
    if isinstance(sticky, dict):
        sticky.pop(code, None)
    save_holdings(data)
    print(f"已清空持仓: {code} {meta['name']}")


def cmd_clear_all(_: argparse.Namespace) -> None:
    """清空全部盯盘标的持仓与当日已实现、绿底粘滞。"""
    data = load_holdings()
    for w in WATCHLIST:
        data["positions"][w["code"]] = _empty_position(w)
    data["realized_today"] = {}
    data["alert_sticky"] = {}
    data["account_total"] = None
    data["account_cash"] = None
    data["account_total_open"] = None
    data["account_total_open_session"] = None
    data["last_session"] = None
    save_holdings(data)
    print(f"已清空全部持仓（{len(WATCHLIST)} 只）与当日结算记录")


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


def _refresh_once(
    refresh_sec: int,
    *,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> Path:
    rows = collect_rows(get_quote=get_quote)
    indices = fetch_indices_cached()
    return write_html_report(rows, indices=indices, refresh_sec=refresh_sec)


def _parse_hhmm(text: str) -> tuple[int, int]:
    parts = str(text).strip().replace("：", ":").split(":")
    if len(parts) != 2:
        raise ValueError(f"时间格式应为 HH:MM，收到: {text!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"非法时间: {text!r}")
    return hour, minute


def _next_open_refresh_at(
    now: datetime | None = None,
    *,
    hour: int = OPEN_PRICE_REFRESH_HOUR,
    minute: int = OPEN_PRICE_REFRESH_MINUTE,
) -> datetime:
    """下一档开盘价刷新时刻（默认每日 09:26）。"""
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def _log_watchlist_opens(rows: list[dict[str, Any]]) -> None:
    by_code = {str(r.get("代码")): r for r in rows}
    print(f"[{_now()}] 开盘价定时刷新 · 盯盘 {_watchlist_codes_label()}")
    for w in WATCHLIST:
        r = by_code.get(w["code"], {})
        open_px = r.get("开盘")
        stop_px = r.get("止损")
        last_px = r.get("现价")
        print(
            f"  {w['name']}({w['code']}) "
            f"开盘={open_px if open_px is not None else '-'} "
            f"止损={stop_px if stop_px is not None else '-'} "
            f"现价={last_px if last_px is not None else '-'}"
        )


def _refresh_open_prices(
    refresh_sec: int,
    *,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> Path:
    """强制拉一次行情，用最新开盘重算买点/止损并写报告。"""
    rows = collect_rows(get_quote=get_quote)
    indices = fetch_indices()
    path = write_html_report(rows, indices=indices, refresh_sec=refresh_sec)
    _log_watchlist_opens(rows)
    return path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_watch_lock() -> dict[str, Any] | None:
    if not WATCH_PID_FILE.exists():
        return None
    try:
        raw = WATCH_PID_FILE.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            data = json.loads(raw)
            pid = int(data.get("pid") or 0)
        else:
            pid = int(raw)
            data = {"pid": pid}
        if pid and _pid_alive(pid):
            return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _acquire_watch_lock(*, host: str, port: int) -> None:
    """防止多个 watch 同时写 HTML，页面会来回跳变。"""
    existing = _read_watch_lock()
    if existing:
        old = int(existing.get("pid") or 0)
        if old and old != os.getpid():
            raise SystemExit(
                f"盯盘已在运行 (pid={old})。\n"
                f"请先在对应终端 Ctrl+C 停掉，再重新启动，"
                f"否则新旧进程会抢写报告。"
            )
    WATCH_PID_FILE.write_text(
        json.dumps(
            {"pid": os.getpid(), "host": host, "port": int(port)},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _release_watch_lock() -> None:
    try:
        if not WATCH_PID_FILE.exists():
            return
        raw = WATCH_PID_FILE.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            cur = int(json.loads(raw).get("pid") or 0)
        else:
            cur = int(raw)
        if cur == os.getpid():
            WATCH_PID_FILE.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass


def _report_url_if_watching() -> str | None:
    lock = _read_watch_lock()
    if not lock:
        return None
    host = str(lock.get("host") or "127.0.0.1")
    port = lock.get("port")
    if port is None:
        return None
    return f"http://{host}:{int(port)}/{REPORT_FILE.name}"


def _write_html_respecting_watch(
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]] | None = None,
) -> Path:
    """status/html 写报告时：若盯盘在跑则保留刷新脚本，避免撕掉自动刷新。"""
    lock = _read_watch_lock()
    if not lock:
        return write_html_report(rows, indices=indices)
    refresh_sec = 60
    try:
        meta = json.loads(WATCH_META_FILE.read_text(encoding="utf-8"))
        refresh_sec = int(meta.get("refresh_sec") or refresh_sec)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    print(
        f"检测到盯盘进程 (pid={lock.get('pid')})，保留自动刷新写入报告。"
    )
    return write_html_report(rows, indices=indices, refresh_sec=refresh_sec)


def cmd_watch(args: argparse.Namespace) -> None:
    """长驻进程：东财 SSE/新浪兜底行情 + 本地 HTTP/WS 推页。"""
    global _ws_hub
    interval = max(2, int(args.interval))
    host = str(args.host)
    port = int(args.port)
    open_h, open_m = _parse_hhmm(
        getattr(args, "open_at", None)
        or f"{OPEN_PRICE_REFRESH_HOUR:02d}:{OPEN_PRICE_REFRESH_MINUTE:02d}"
    )
    _acquire_watch_lock(host=host, port=port)
    stop = threading.Event()
    refresh_lock = threading.Lock()
    ws_hub = LocalWsHub()
    _ws_hub = ws_hub

    sinas = [str(w["sina"]).lower() for w in WATCHLIST]
    feed = QuoteFeedManager(
        sinas,
        on_log=lambda m: print(f"[{_now()}] {m}"),
    )

    def get_quote(sina: str) -> dict[str, Any]:
        q = feed.get_quote(sina)
        if q is None:
            q = fetch_today_quote(sina)
            feed.seed(sina, q)
        return q

    def reseed_all() -> None:
        for w in WATCHLIST:
            q = fetch_today_quote(w["sina"])
            feed.seed(w["sina"], q)

    def safe_refresh() -> Path:
        with refresh_lock:
            return _refresh_once(interval, get_quote=get_quote)

    def safe_open_refresh() -> Path:
        with refresh_lock:
            reseed_all()
            return _refresh_open_prices(interval, get_quote=get_quote)

    print("冷启动：拉取开盘/分钟线并 seed…")
    try:
        reseed_all()
        feed.start()
        report = safe_refresh()
        print(f"报告已生成: {report}")
    except Exception as e:
        feed.stop()
        _ws_hub = None
        _release_watch_lock()
        print(f"首次更新失败: {e}")
        raise

    def loop() -> None:
        last = 0.0
        while not stop.is_set():
            feed.wait_update(timeout=float(interval))
            if stop.is_set():
                break
            wait_more = _MIN_WATCH_REFRESH_SEC - (time.monotonic() - last)
            if wait_more > 0 and stop.wait(wait_more):
                break
            last = time.monotonic()
            try:
                safe_refresh()
                print(f"[{_now()}] 行情已更新 → {REPORT_FILE.name}")
            except Exception as e:
                print(f"[{_now()}] 更新失败: {e}")

    def open_price_loop() -> None:
        """每日固定时刻刷新盯盘开盘价（默认 09:26，集合竞价结束）。"""
        while not stop.is_set():
            nxt = _next_open_refresh_at(hour=open_h, minute=open_m)
            wait = (nxt - datetime.now()).total_seconds()
            print(
                f"[{_now()}] 下次开盘价刷新 {_watchlist_codes_label()} @ "
                f"{nxt.strftime('%Y-%m-%d %H:%M:%S')}（约 {wait:.0f}s）"
            )
            if stop.wait(max(1.0, wait)):
                break
            try:
                safe_open_refresh()
                print(f"[{_now()}] 开盘价已写入 → {REPORT_FILE.name}")
            except Exception as e:
                print(f"[{_now()}] 开盘价刷新失败: {e}")

    worker = threading.Thread(target=loop, name="holdings-watch", daemon=True)
    worker.start()
    open_worker = threading.Thread(
        target=open_price_loop, name="holdings-open-refresh", daemon=True
    )
    open_worker.start()

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, fmt: str, *log_args: Any) -> None:
            path = getattr(self, "path", "") or ""
            if WATCH_META_FILE.name in path or REPORT_FILE.name in path:
                return
            if path.split("?", 1)[0] == "/ws":
                return
            super().log_message(fmt, *log_args)

        def end_headers(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in (f"/{REPORT_FILE.name}", f"/{WATCH_META_FILE.name}"):
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/ws":
                self._handle_ws_upgrade()
                return
            super().do_GET()

        def _handle_ws_upgrade(self) -> None:
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self.send_error(400, "Missing Sec-WebSocket-Key")
                return
            if (self.headers.get("Upgrade") or "").lower() != "websocket":
                self.send_error(400, "Expected Upgrade: websocket")
                return
            accept = ws_accept_key(key)
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            try:
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass
            self.close_connection = True
            ws_hub.serve_client(self.connection)

    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        feed.stop()
        _ws_hub = None
        _release_watch_lock()
        raise SystemExit(
            f"端口 {host}:{port} 无法绑定（可能已有盯盘在跑）。\n"
            f"请先停掉旧进程再启动，避免抢写报告。\n{e}"
        ) from e
    url = f"http://{host}:{port}/{REPORT_FILE.name}"
    print(f"盯盘服务已启动: {url}")
    print(f"本地 WebSocket: ws://{host}:{port}/ws")
    print(
        f"策略同步: {STRATEGY_NAME} ±{DEFAULT_PCT*100:.1f}% · 仅止损全清"
    )
    print(
        f"行情: 东财 SSE + 新浪批量兜底 · 刷新节流≥{_MIN_WATCH_REFRESH_SEC:.0f}s · "
        f"无行情保底 {interval}s · Ctrl+C 停止"
    )
    print(
        f"开盘价定时: 每日 {open_h:02d}:{open_m:02d} 刷新盯盘标的 "
        f"({_watchlist_codes_label()})"
    )
    print("展示: 当日涨幅=现价/昨收；盈亏金额=持仓当日盈亏（勿与涨幅%混淆）")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止盯盘")
    finally:
        stop.set()
        feed.stop()
        _ws_hub = None
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        _release_watch_lock()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="持仓记录与盯盘")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="查看行情+持仓并生成 HTML（默认）")
    s.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    s.set_defaults(func=cmd_status)

    html_p = sub.add_parser("html", help="生成并打开 HTML 报告")
    html_p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    html_p.set_defaults(func=cmd_html)

    w = sub.add_parser(
        "watch",
        help="长驻盯盘：东财SSE/新浪兜底行情 + 本地WS推页",
    )
    w.add_argument(
        "--interval",
        type=int,
        default=5,
        help="无行情时的保底刷新秒数，默认5",
    )
    w.add_argument("--host", default="127.0.0.1", help="监听地址")
    w.add_argument("--port", type=int, default=8765, help="端口，默认8765")
    w.add_argument(
        "--open-at",
        default=f"{OPEN_PRICE_REFRESH_HOUR:02d}:{OPEN_PRICE_REFRESH_MINUTE:02d}",
        help="每日强制刷新盯盘开盘价的时刻，默认09:26",
    )
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

    ca = sub.add_parser("clear-all", help="清空全部持仓与当日结算")
    ca.set_defaults(func=cmd_clear_all)

    sc = sub.add_parser("set-cost", help="登记/修改成本价")
    sc.add_argument("code")
    sc.add_argument("cost", type=float)
    sc.add_argument("--qty", type=int, default=None, help="可选：同时登记数量")
    sc.add_argument("--available", type=int, default=None, help="可选：可卖数量（T+1）")
    sc.add_argument(
        "--today-cost",
        type=float,
        default=None,
        help="可选：今日买入成交价（当日盈亏用，非持仓均价）",
    )
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
