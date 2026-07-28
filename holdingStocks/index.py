"""持仓记录与盯盘：深证000893 / 上证600552 / 深证002171 / 上证510580

功能：
  · 拉取当日开盘、最高、最低、现价（新浪1分钟）
  · 默认与 kskj600552 一致 ±2.5%（ceil/floor）；510580 为 ±1.2%
  · 空仓：已触买/将买入 → 建议限价买@触发价；有仓：已触止损/将止损/阴线卖 → 建议挂单价
  · 本地 JSON 记录持仓成本与数量，计算浮盈亏；T+1 买入日提示不可卖

用法：
  python index.py              # 查看标的行情 + 持仓，并生成 HTML
  python index.py html         # 仅生成/打开 HTML 报告
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
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / "holdings.json"
TRADES_FILE = ROOT / "trades.jsonl"
REPORT_FILE = ROOT / "holdings_report.html"

# 默认对称阈值（与 kskj600552 一致 ±2.5%）；单标的可在 WATCHLIST 用 pct 覆盖
DEFAULT_PCT = 0.025
ENTRY_PCT = DEFAULT_PCT
STOP_PCT = DEFAULT_PCT
TICK_SIZE = 0.01
# 距买点/止损点若干「点」内触发预警（相对开盘的百分点）
NEAR_POINTS = 1.0

WATCHLIST: list[dict[str, Any]] = [
    {"code": "000893", "sina": "sz000893", "market": "深证", "name": "亚钾国际"},
    {"code": "600552", "sina": "sh600552", "market": "上证", "name": "凯盛科技"},
    {"code": "002171", "sina": "sz002171", "market": "深证", "name": "楚江新材"},
    {
        "code": "510580",
        "sina": "sh510580",
        "market": "上证",
        "name": "易方达中证500ETF",
        "pct": 0.012,
        "tick": 0.001,
        "t0": True,  # ETF 当日可买卖
    },
]

# 大盘指数（新浪 spot）
INDEX_WATCH: list[dict[str, str]] = [
    {"code": "sh000001", "name": "上证指数", "market": "上证"},
    {"code": "sz399001", "name": "深证成指", "market": "深证"},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
            "positions": {
                w["code"]: _empty_position(w)
                for w in WATCHLIST
            },
        }
        save_holdings(data)
        return data
    with HOLDINGS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    positions = data.setdefault("positions", {})
    for w in WATCHLIST:
        positions.setdefault(w["code"], _empty_position(w))
    return data


def save_holdings(data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    with HOLDINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_trade(record: dict[str, Any]) -> None:
    with TRADES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def fetch_today_quote(sina: str) -> dict[str, Any]:
    """用1分钟线拼当日开高低收（现价=最新分钟收盘）；并取昨收算当日涨幅。"""
    raw = ak.stock_zh_a_minute(symbol=sina, period="1", adjust="")
    if raw is None or raw.empty:
        raise RuntimeError(f"无分钟行情: {sina}")
    df = raw.copy()
    df["ts"] = pd.to_datetime(df["day"])
    today = pd.Timestamp.now().normalize()
    day = df[df["ts"].dt.normalize() == today].copy()
    if day.empty:
        # 非交易时段：退回最近一个交易日全日
        last_day = df["ts"].dt.normalize().max()
        day = df[df["ts"].dt.normalize() == last_day].copy()
        session_ts = last_day
        session = str(last_day.date())
    else:
        session_ts = today
        session = str(today.date())

    for col in ("open", "high", "low", "close"):
        day[col] = pd.to_numeric(day[col], errors="coerce")
    day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
    if day.empty:
        raise RuntimeError(f"当日无有效分钟线: {sina}")

    # 昨收：会话日前一交易日最后一根分钟收盘
    prev_days = df[df["ts"].dt.normalize() < session_ts]
    prev_close = None
    if not prev_days.empty:
        prev_last_day = prev_days["ts"].dt.normalize().max()
        prev = prev_days[prev_days["ts"].dt.normalize() == prev_last_day].copy()
        prev["close"] = pd.to_numeric(prev["close"], errors="coerce")
        prev = prev.dropna(subset=["close"]).sort_values("ts")
        if not prev.empty:
            prev_close = float(prev.iloc[-1]["close"])

    open_px = float(day.iloc[0]["open"])
    high_px = float(day["high"].max())
    low_px = float(day["low"].min())
    last_px = float(day.iloc[-1]["close"])
    last_ts = day.iloc[-1]["ts"]
    day_chg = None
    if prev_close is not None and prev_close > 0:
        day_chg = (last_px / prev_close - 1.0) * 100.0
    return {
        "session": session,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "last": last_px,
        "prev_close": prev_close,
        "day_chg_pct": day_chg,
        "last_ts": str(last_ts),
    }


def ceil_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    """买入触发价：向上取整到 tick（与 kskj 一致）。"""
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.ceil((float(px) - 1e-12) / tick) * tick, decimals)


def floor_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    """止损触发价：向下取整到 tick（与 kskj 一致）。"""
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.floor((float(px) + 1e-12) / tick) * tick, decimals)


def strategy_levels(
    open_px: float,
    *,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
) -> dict[str, float]:
    buy = ceil_to_tick(float(open_px) * (1.0 + entry_pct), tick)
    stop = floor_to_tick(float(open_px) * (1.0 - stop_pct), tick)
    return {"buy_trigger": buy, "stop": stop}


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


def _is_t1_buy_day(buy_time: str | None, session: str) -> bool:
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
) -> dict[str, Any]:
    """按 kskj 规则生成预警与建议挂单价（盯盘用现价近似收盘判阴阳）。"""
    holding = qty > 0
    hit_buy = high_px + 1e-12 >= buy_trigger
    hit_stop = low_px <= stop_px + 1e-12
    yin = is_yin(open_px, last_px)
    t1_lock = holding and (not t0) and _is_t1_buy_day(buy_time, session)
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
            base["alert"] = "T+1不可卖"
            base["挂单说明"] = "今日买入，明日再判止损/阴线"
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
        if yin:
            close_limit = round(last_px, px_digits)
            base.update(
                {
                    "pending_sell": True,
                    "alert": "阴线卖",
                    "bg_class": "warn-sell",
                    "建议挂单": close_limit,
                    "挂单说明": f"尾盘限价卖@{pf.format(close_limit)}（以收盘价为准）",
                }
            )
            return base
        if abs(vs_open_pts - stop_lvl) <= NEAR_POINTS + 1e-12:
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
        return base

    # 空仓：仅提示买入相关
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
    if abs(vs_open_pts - buy_lvl) <= NEAR_POINTS + 1e-12:
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
    return base


def points_vs_open(open_px: float, px: float) -> float:
    if open_px <= 0:
        return float("nan")
    return (px / open_px - 1.0) * 100.0


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
    """拉取行情并合并持仓，返回行字典列表。"""
    holdings = load_holdings()
    positions = holdings.get("positions", {})
    rows: list[dict[str, Any]] = []

    for w in WATCHLIST:
        code = w["code"]
        entry_pct = _watch_pct(w)
        stop_pct = entry_pct
        tick = _watch_tick(w)
        px_digits = _px_digits(tick)
        pct_pct = round(entry_pct * 100.0, 2)
        try:
            q = fetch_today_quote(w["sina"])
            lv = strategy_levels(
                q["open"], entry_pct=entry_pct, stop_pct=stop_pct, tick=tick
            )
            vs = points_vs_open(q["open"], q["last"])
            day_chg = q.get("day_chg_pct")
            hit_buy = q["high"] + 1e-12 >= lv["buy_trigger"]
            hit_stop = q["low"] <= lv["stop"] + 1e-12
            pos = positions.get(code, {})
            qty = int(pos.get("qty") or 0)
            buy_time = pos.get("buy_time")
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
                t0=bool(w.get("t0")),
            )
            cost = pos.get("cost")
            pnl = None
            pnl_pct = None
            market_value = (q["last"] * qty) if qty > 0 else None
            cost_value = None
            day_pnl = None
            day_pnl_pct = None
            if cost is not None:
                cost_f = float(cost)
                pnl_pct = (q["last"] / cost_f - 1.0) * 100.0
                if qty > 0:
                    pnl = (q["last"] - cost_f) * qty
                    cost_value = cost_f * qty
                else:
                    pnl = q["last"] - cost_f

            # 当日盈亏：隔夜仓=(现价-昨收)×数量；当日买入=(现价-成本)×数量（无成本则用开盘）
            if qty > 0:
                bought_today = _is_t1_buy_day(buy_time, q["session"])
                if bought_today:
                    base_px = float(cost) if cost is not None else float(q["open"])
                    day_pnl = (q["last"] - base_px) * qty
                    day_pnl_pct = (q["last"] / base_px - 1.0) * 100.0 if base_px > 0 else None
                elif q.get("prev_close") is not None and float(q["prev_close"]) > 0:
                    base_px = float(q["prev_close"])
                    day_pnl = (q["last"] - base_px) * qty
                    day_pnl_pct = (q["last"] / base_px - 1.0) * 100.0

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
                    "较开盘点": round(vs, 2),
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
                    "当日盈亏%": None if day_pnl_pct is None else round(float(day_pnl_pct), 2),
                    "市值": None if market_value is None else round(float(market_value), 2),
                    "成本额": None if cost_value is None else round(float(cost_value), 2),
                    "价位小数": px_digits,
                    "更新": q["last_ts"][11:19] if len(q["last_ts"]) >= 19 else q["last_ts"],
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
                    "价位小数": px_digits,
                    "更新": "-",
                    "error": str(e),
                }
            )
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


def write_html_report(
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]] | None = None,
    path: Path = REPORT_FILE,
) -> Path:
    """生成持仓盯盘 HTML。"""
    indices = indices or []
    total_pnl = 0.0
    total_day_pnl = 0.0
    total_mv = 0.0
    total_mv_no_cost = 0.0
    total_cost = 0.0
    total_day_base = 0.0  # 当日盈亏分母：昨收×数量（当日买则用成本/开盘）
    has_pos = False
    has_day = False
    for r in rows:
        qty = int(r.get("持仓") or 0)
        if r.get("浮盈") is not None and qty > 0:
            total_pnl += float(r["浮盈"])
            has_pos = True
        if r.get("当日盈亏") is not None and qty > 0:
            total_day_pnl += float(r["当日盈亏"])
            has_day = True
            # 由金额与百分比反推基数；无%时用 市值-当日盈亏
            dpct = r.get("当日盈亏%")
            if dpct is not None and abs(float(dpct)) > 1e-12:
                total_day_base += float(r["当日盈亏"]) / (float(dpct) / 100.0)
            elif r.get("市值") is not None:
                total_day_base += float(r["市值"]) - float(r["当日盈亏"])
        if r.get("市值") is not None and qty > 0:
            mv = float(r["市值"])
            total_mv += mv
            # 无成本仓市值单独统计，避免「市值-成本≠浮盈」误解
            if r.get("成本额") is None:
                total_mv_no_cost += mv
        if r.get("成本额") is not None:
            total_cost += float(r["成本额"])
    total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else None
    total_day_pct = (
        (total_day_pnl / total_day_base * 100.0) if has_day and total_day_base > 0 else None
    )

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
        pnl = r.get("浮盈")
        pnl_pct = r.get("浮盈%")
        day_pnl = r.get("当日盈亏")
        day_pnl_pct = r.get("当日盈亏%")
        alert = r.get("预警") or ""
        bg = r.get("bg_class") or ""
        suggest_px = r.get("建议挂单")
        suggest_note = r.get("挂单说明") or ""
        alert_html = ""
        if alert:
            alert_html = f'<div class="alert-badge tag-alert">{escape(alert)}</div>'
        pdg = int(r.get("价位小数") or 2)
        suggest_html = ""
        if suggest_px is not None:
            suggest_html = (
                f'<div class="suggest-order">'
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
                  <div class="last">{_fmt_num(r.get('现价'), pdg)}</div>
                  <div class="chg {_cls_chg(day_pnl if int(r.get('持仓') or 0) > 0 else day_chg)}">
                    {f"当日 {('-' if day_pnl is None else f'{float(day_pnl):+.2f}')} {('-' if day_pnl_pct is None else f'{float(day_pnl_pct):+.2f}%')}" if int(r.get('持仓') or 0) > 0 else f"当日 {('-' if day_chg is None else f'{float(day_chg):+.2f}%')}"}
                  </div>
                </div>
              </header>
              {"<p class='err'>行情失败: " + escape(str(err)) + "</p>" if err else ""}
              {suggest_html}
              <div class="grid">
                <div><span>开盘</span><b>{_fmt_num(r.get('开盘'), pdg)}</b></div>
                <div><span>最高</span><b>{_fmt_num(r.get('最高'), pdg)}</b></div>
                <div><span>最低</span><b>{_fmt_num(r.get('最低'), pdg)}</b></div>
                <div><span>较开盘</span><b class="{_cls_chg(vs_open)}">{('-' if vs_open is None else f'{float(vs_open):+.2f}')}</b></div>
                <div><span>形态</span><b>{escape(str(r.get('形态') or '-'))}</b></div>
                <div><span>买点 +{th_label}%</span><b class="{'tag-buy' if r.get('近买点') else ''}">{_fmt_num(r.get('买点'), pdg)}</b></div>
                <div><span>止损 -{th_label}%</span><b class="{'tag-sell' if r.get('近止损') else ''}">{_fmt_num(r.get('止损'), pdg)}</b></div>
                <div><span>已触买</span><b class="{'tag-yes' if r.get('已触买')=='是' else ''}">{escape(str(r.get('已触买')))}</b></div>
                <div><span>已触止损</span><b class="{'tag-sell' if r.get('已触止损')=='是' else ''}">{escape(str(r.get('已触止损')))}</b></div>
                <div><span>预警</span><b class="{'tag-alert' if alert else ''}">{escape(alert) if alert else '-'}</b></div>
                <div><span>持仓</span><b>{escape(str(r.get('持仓')))}</b></div>
                <div><span>成本</span><b>{_fmt_num(r.get('成本'), max(3, pdg))}</b></div>
                <div><span>浮盈</span><b class="{_cls_chg(pnl)}">{_fmt_num(pnl)}</b></div>
                <div><span>浮盈%</span><b class="{_cls_chg(pnl_pct)}">{'-' if pnl_pct is None else f'{float(pnl_pct):+.2f}%'}</b></div>
                <div><span>当日盈亏</span><b class="{_cls_chg(day_pnl)}">{_fmt_num(day_pnl)}</b></div>
                <div><span>当日盈亏%</span><b class="{_cls_chg(day_pnl_pct)}">{'-' if day_pnl_pct is None else f'{float(day_pnl_pct):+.2f}%'}</b></div>
              </div>
              <footer>更新 {escape(str(r.get('更新') or '-'))}</footer>
            </article>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>持仓盯盘 · 000893 / 600552 / 002171 / 510580</title>
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
      display: flex; flex-wrap: wrap; gap: 18px; justify-content: space-between; align-items: end;
      margin-bottom: 16px;
    }}
    .hero h1 {{
      margin: 0 0 6px; font-size: clamp(1.6rem, 3vw, 2.2rem); letter-spacing: -0.02em;
    }}
    .hero p {{ margin: 0; color: var(--muted); font-size: 0.95rem; }}
    .summary {{
      min-width: 260px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      backdrop-filter: blur(8px);
    }}
    .summary .label {{ color: var(--muted); font-size: 0.85rem; }}
    .summary .value {{ font-size: 1.8rem; font-weight: 700; margin-top: 4px; }}
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
    .summary .day-line .day-value {{ font-size: 1.15rem; font-weight: 700; }}
    .summary .meta {{ color: var(--muted); font-size: 0.86rem; margin-top: 8px; }}
    .index-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .index-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      backdrop-filter: blur(8px);
      padding: 14px 16px;
    }}
    .index-name {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }}
    .index-name strong {{ font-size: 1.05rem; }}
    .index-name code {{ color: var(--muted); font-size: 0.85rem; }}
    .index-metrics {{
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
    }}
    .index-metrics span {{ display: block; color: var(--muted); font-size: 0.78rem; }}
    .index-metrics b {{ font-size: 1.05rem; font-weight: 700; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--card);
      backdrop-filter: blur(8px);
      padding: 16px;
      box-shadow: 0 10px 30px rgba(20, 32, 26, 0.04);
      transition: background 0.25s ease, border-color 0.25s ease;
    }}
    /* 将买入：红底；将卖出：绿底（A股习惯） */
    .card.warn-buy {{
      background: rgba(255, 214, 214, 0.92);
      border-color: #e08a8a;
      box-shadow: 0 10px 28px rgba(180, 35, 24, 0.12);
    }}
    .card.warn-sell {{
      background: rgba(198, 236, 214, 0.92);
      border-color: #6fbf8f;
      box-shadow: 0 10px 28px rgba(11, 122, 69, 0.12);
    }}
    .card header {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .market {{
      display: inline-block; font-size: 0.75rem; color: var(--accent);
      border: 1px solid #b7d2c4; border-radius: 999px; padding: 2px 8px; margin-bottom: 6px;
    }}
    .title h2 {{ margin: 0; font-size: 1.2rem; }}
    .title code {{ color: var(--muted); font-size: 0.9rem; }}
    .alert-badge {{
      display: inline-block;
      margin-top: 8px;
      padding: 3px 10px;
      border-radius: 6px;
      font-size: 0.82rem;
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
    .suggest-order {{
      margin: 0 0 10px;
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 0.88rem;
      background: rgba(255,255,255,0.55);
      border: 1px dashed var(--line);
    }}
    .suggest-order strong {{ font-size: 1.05rem; margin-left: 4px; }}
    .price {{ text-align: right; }}
    .last {{ font-size: 1.7rem; font-weight: 700; line-height: 1.1; }}
    .chg {{ font-size: 0.95rem; margin-top: 4px; }}
    .grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px;
      border-top: 1px dashed var(--line); padding-top: 12px;
    }}
    .grid div span {{ display: block; color: var(--muted); font-size: 0.78rem; }}
    .grid div b {{ font-size: 0.98rem; font-weight: 600; }}
    .up {{ color: var(--up); }}
    .down {{ color: var(--down); }}
    .flat {{ color: var(--muted); }}
    .tag-yes {{ color: var(--accent); }}
    .tag-warn {{ color: var(--warn); }}
    .tag-alert {{ color: var(--up); font-weight: 700; }}
    .tag-buy {{ color: var(--up); }}
    .tag-sell {{ color: var(--down); }}
    .err {{ color: var(--up); font-size: 0.9rem; }}
    footer {{ margin-top: 12px; color: var(--muted); font-size: 0.8rem; }}
    .note {{ margin-top: 18px; color: var(--muted); font-size: 0.86rem; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>持仓盯盘</h1>
        <p>000893 / 600552 / 002171 ±2.5% · 510580 ±1.2% · {_now()}</p>
      </div>
      <div class="summary">
        <div class="label">合计浮盈</div>
        <div class="value {_cls_chg(total_pnl if has_pos else None)}">
          {('-' if not has_pos else f'{total_pnl:+.2f}')}
          <span style="font-size:0.95rem;font-weight:600;margin-left:6px;">
            {('-' if total_pnl_pct is None else f'{total_pnl_pct:+.2f}%')}
          </span>
        </div>
        <div class="day-line">
          <span class="day-label">当日盈亏</span>
          <span class="day-value {_cls_chg(total_day_pnl if has_day else None)}">
            {('-' if not has_day else f'{total_day_pnl:+.2f}')}
            {" " + ('-' if total_day_pct is None else f'{total_day_pct:+.2f}%')}
          </span>
        </div>
        <div class="meta">
          市值 {_fmt_num(total_mv if total_mv else None)}
          · 成本 {_fmt_num(total_cost if total_cost else None)}
          {f' · 未计成本市值 {_fmt_num(total_mv_no_cost)}' if total_mv_no_cost > 0 else ''}
        </div>
      </div>
    </div>
    <div class="index-row">
      {''.join(index_cards)}
    </div>
    <div class="cards">
      {''.join(cards)}
    </div>
    <p class="note">
      大盘：点数=最新指数点位；涨跌点数/涨跌幅相对昨收。
      个股：默认 ±2.5%（ceil/floor，同 kskj600552）；510580 为 ±1.2%。
      市值=现价×持仓数量（全部有仓合计）；成本/浮盈仅统计已登记成本的仓位。
      若有未登记成本仓（如510580），会出现「市值−成本≠浮盈」，属正常。
      当日盈亏：隔夜仓=(现价−昨收)×数量；当日买入=(现价−成本)×数量。
      空仓：已触买/将买入 → 建议限价@买点；有仓：已触止损/将止损/阴线卖 → 建议挂单价。
      未触发且距买卖点 ≤1 点：将买入红底、将止损绿底。刷新请重新运行
      <code>python index.py</code> 或 <code>python index.py html</code>。
    </p>
  </div>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def cmd_status(args: argparse.Namespace) -> None:
    rows = collect_rows()
    indices = fetch_indices()
    print(f"\n持仓盯盘  {_now()}")
    print(f"策略参考: 默认 ±{DEFAULT_PCT*100:.1f}%（510580 ±1.2%）/ 阴线收盘出")
    print(f"持仓文件: {HOLDINGS_FILE}")
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
                "阈值%": r.get("阈值%"),
                "最高": _p(r["最高"]),
                "最低": _p(r["最低"]),
                "买点": _p(r["买点"]),
                "止损": _p(r["止损"]),
                "已触买": r["已触买"],
                "已触止损": r["已触止损"],
                "形态": r.get("形态") or "-",
                "预警": r.get("预警") or "-",
                "建议挂单": _p(r.get("建议挂单")),
                "挂单说明": r.get("挂单说明") or "-",
                "持仓": r["持仓"],
                "成本": _p(r["成本"], max(3, pdg)),
                "浮盈": r["error"] if r.get("error") else ("-" if r["浮盈"] is None else r["浮盈"]),
                "浮盈%": "-" if r["浮盈%"] is None else r["浮盈%"],
                "当日盈亏": "-" if r.get("当日盈亏") is None else r["当日盈亏"],
                "当日盈亏%": "-" if r.get("当日盈亏%") is None else r["当日盈亏%"],
                "更新": r["更新"],
            }
        )
    cols = [
        "市场", "代码", "名称", "开盘", "现价", "当日涨幅", "较开盘点", "阈值%",
        "最高", "最低", "买点", "止损", "已触买", "已触止损", "形态", "预警",
        "建议挂单", "挂单说明", "持仓", "成本", "浮盈", "浮盈%", "当日盈亏", "当日盈亏%", "更新",
    ]
    print(pd.DataFrame(show_rows)[cols].to_string(index=False))
    print("-" * 108)
    day_total = 0.0
    day_base = 0.0
    day_n = 0
    for r in rows:
        if r.get("当日盈亏") is not None and int(r.get("持仓") or 0) > 0:
            day_total += float(r["当日盈亏"])
            day_n += 1
            dpct = r.get("当日盈亏%")
            if dpct is not None and abs(float(dpct)) > 1e-12:
                day_base += float(r["当日盈亏"]) / (float(dpct) / 100.0)
            elif r.get("市值") is not None:
                day_base += float(r["市值"]) - float(r["当日盈亏"])
    if day_n:
        day_pct = (day_total / day_base * 100.0) if day_base > 0 else None
        pct_txt = "-" if day_pct is None else f"{day_pct:+.2f}%"
        print(f"合计当日盈亏: {day_total:+.2f} ({pct_txt})")
    else:
        print("合计当日盈亏: -")

    report = write_html_report(rows, indices=indices)
    print(f"HTML 报告: {report}")
    if not getattr(args, "no_open", False):
        webbrowser.open(report.resolve().as_uri())
    print("说明: 当日涨幅=(现价/昨收-1)×100；较开盘点=(现价/开盘-1)×100")
    print("     当日盈亏: 隔夜仓=(现价-昨收)×数量；当日买入=(现价-成本)×数量")
    print("     买点/止损按各标的阈值 ceil/floor；510580=±1.2%，其余=±2.5%")
    print("     预警触发时显示建议挂单价；有仓优先止损/阴线，空仓才提示买入")


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
    pnl = (price - cost) * qty
    new_qty = old_qty - qty
    pos["qty"] = new_qty
    if new_qty == 0:
        pos["cost"] = None
        pos["buy_time"] = None
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
            "note": args.note or "",
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="三只股票持仓记录与盯盘")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="查看行情+持仓并生成 HTML（默认）")
    s.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    s.set_defaults(func=cmd_status)

    html_p = sub.add_parser("html", help="生成并打开 HTML 报告")
    html_p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    html_p.set_defaults(func=cmd_html)

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
