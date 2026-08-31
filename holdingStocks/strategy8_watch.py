"""策略八·题材联动 — 当日涨停定题材 + 当日因子1 ±阈值。"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stock_names import lookup_names_for_codes, resolve_stock_name
from strategy.open_break import DEFAULT_PCT, TICK_SIZE, strategy_levels
from strategy.strategies.strategy8.concept_index import (
    load_concept_maps,
    theme_lu_stats,
)
from strategy3_watch import (
    _factor1_params as _s3_factor1_params,
    _gate_rules_text,
    _load_sentiment_df,
    _load_symbol_daily,
    _load_univ,
    _lu_at,
    _normalize_trade_date,
    get_market_sentiment,
    limit_ratio,
)

_MYQUAN = Path(__file__).resolve().parents[1]
SUMMARY_PATH = _MYQUAN / "backtest" / "strategy8_theme_linkage" / "summary.json"
LU_TOL = 0.012
MIN_THEME_LU = 3
POOL_MODE = "linkage"
_POOL_CACHE: dict[str, dict[str, Any]] = {}
_POOL_CACHE_VER = "names_v3"


def _display_stock_name(
    *,
    code: str,
    symbol: str = "",
    raw_name: str = "",
    quote_name: str = "",
) -> str:
    """题材池展示名：忽略宇宙表里的 code 占位，强制走名称缓存。"""
    c = str(code).zfill(6)
    sym = str(symbol or "").strip()
    for candidate in (raw_name, quote_name):
        hit = resolve_stock_name(symbol=sym, code=c, name=str(candidate or ""))
        if hit:
            return hit
    return resolve_stock_name(symbol=sym, code=c, name="") or c


@lru_cache(maxsize=1)
def _concept_maps() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    univ = _load_univ()
    if univ.empty or "code" not in univ.columns:
        return {}, {}
    codes = tuple(sorted(str(c).zfill(6) for c in univ["code"]))
    return load_concept_maps(codes)


def load_backtest_summary() -> list[dict[str, Any]]:
    if not SUMMARY_PATH.is_file():
        return []
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _factor1_params() -> dict[str, Any]:
    try:
        from strategy.strategies.strategy8.bindings import FACTOR_BINDINGS

        for b in FACTOR_BINDINGS:
            if b.factor_id == "factor1" and b.enabled:
                return dict(b.params)
    except Exception:  # noqa: BLE001
        pass
    return _s3_factor1_params()


def _quote_is_limit_up(code: str, quote: dict[str, Any] | None) -> bool:
    if not quote:
        return False
    prev = float(quote.get("prev_close") or quote.get("preclose") or 0)
    last = float(quote.get("last") or quote.get("price") or 0)
    high = float(quote.get("high") or last)
    if prev <= 0 or last <= 0:
        return False
    lim = limit_ratio(code)
    pct = last / prev - 1.0
    return pct >= lim - LU_TOL and last >= high * 0.995


def _scan_today_lu_codes(
    univ: pd.DataFrame,
    session: str,
    *,
    quotes: dict[str, dict[str, Any]] | None = None,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """当日涨停池：优先行情判断，否则用日线收盘涨停（盘后/历史）。"""
    sess = pd.Timestamp(session).normalize()
    lu_codes: set[str] = set()
    lu_meta: dict[str, dict[str, Any]] = {}
    quotes = quotes or {}

    from watch_config import sina_of

    for row in univ.itertuples(index=False):
        code = str(row.code).zfill(6)
        symbol = str(row.symbol)
        name = _display_stock_name(code=code, symbol=symbol, raw_name=str(row.name))
        sina = sina_of(code).lower()
        q = quotes.get(sina)
        if _quote_is_limit_up(code, q):
            lu_codes.add(code)
            prev = float(q.get("prev_close") or q.get("preclose") or 0) if q else 0.0
            lu_meta[code] = {
                "code": code,
                "symbol": symbol,
                "name": name,
                "涨停收": float(q.get("last") or 0) if q else None,
                "昨收": prev if prev > 0 else None,
            }
            continue

        daily = _load_symbol_daily(symbol)
        if daily is None:
            continue
        idx = daily.index[daily["date"] == sess]
        if len(idx) == 0:
            continue
        j = int(idx[0])
        if j < 1:
            continue
        lim = limit_ratio(code)
        c = daily["close"].to_numpy(float)
        h = daily["high"].to_numpy(float)
        prev_arr = np.roll(c, 1)
        prev_arr[0] = np.nan
        if not _lu_at(j, prev=prev_arr, c=c, h=h, lim=lim):
            continue
        lu_codes.add(code)
        lu_meta[code] = {
            "code": code,
            "symbol": symbol,
            "name": name,
            "涨停收": float(c[j]),
            "昨收": float(prev_arr[j]) if np.isfinite(prev_arr[j]) else None,
        }
    return lu_codes, lu_meta


def scan_theme_linkage_pool(
    session: str,
    *,
    quotes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """当日涨停 → 热题材 → 题材成分/联动候选（当日阈值买）。"""
    effective = _normalize_trade_date(session) if session else None
    if not effective:
        return {"themeDate": None, "hotThemes": [], "rows": []}
    cache_key = f"{_POOL_CACHE_VER}:{effective}:{POOL_MODE}"
    if cache_key in _POOL_CACHE and not quotes:
        return _POOL_CACHE[cache_key]

    code_concepts, concept_codes = _concept_maps()
    univ = _load_univ()
    if univ.empty or "code" not in univ.columns:
        out = {
            "themeDate": effective,
            "luCount": 0,
            "hotThemes": [],
            "rows": [],
        }
        if not quotes:
            _POOL_CACHE[cache_key] = out
        return out
    lu_codes, lu_meta = _scan_today_lu_codes(univ, effective, quotes=quotes)

    theme_lu_counts: dict[str, int] = defaultdict(int)
    for code in lu_codes:
        for concept in code_concepts.get(code, []):
            theme_lu_counts[concept] += 1
    hot_themes = [
        {"name": k, "luCount": v, "members": len(concept_codes.get(k, []))}
        for k, v in sorted(theme_lu_counts.items(), key=lambda x: (-x[1], x[0]))
        if v >= MIN_THEME_LU
    ]

    sess = pd.Timestamp(effective).normalize()
    rows: list[dict[str, Any]] = []
    for row in univ.itertuples(index=False):
        code = str(row.code).zfill(6)
        symbol = str(row.symbol)
        name = _display_stock_name(code=code, symbol=symbol, raw_name=str(row.name))
        theme_lu, theme_name, theme_members = theme_lu_stats(
            code, lu_codes, code_to_concepts=code_concepts, concept_to_codes=concept_codes
        )
        if theme_lu < MIN_THEME_LU:
            continue
        in_lu = code in lu_codes
        if POOL_MODE == "linkage" and in_lu:
            continue
        if POOL_MODE == "lu_theme" and not in_lu:
            continue
        pool_tag = "当日涨停" if in_lu else "题材联动"
        item: dict[str, Any] = {
            "code": code,
            "symbol": symbol,
            "name": name,
            "题材": theme_name,
            "题材涨停数": theme_lu,
            "题材成分数": theme_members,
            "类型": pool_tag,
            "当日涨停": in_lu,
        }
        daily = _load_symbol_daily(symbol)
        if daily is not None:
            idx_sess = daily.index[daily["date"] == sess]
            if len(idx_sess) > 0:
                j = int(idx_sess[0])
                item["开盘"] = float(daily["open"].iloc[j])
                item["现价"] = float(daily["close"].iloc[j])
        rows.append(item)

    rows.sort(key=lambda r: (-int(r["题材涨停数"]), r["类型"] != "题材联动", r["code"]))
    out = {
        "themeDate": effective,
        "luCount": len(lu_codes),
        "hotThemes": hot_themes[:20],
        "rows": rows,
    }
    if not quotes:
        _POOL_CACHE[cache_key] = out
    return out


def _px_digits(tick: float) -> int:
    return 3 if tick < 0.05 else 2


def _factor_side_label(*, last: float, open_px: float, buy: float, stop: float) -> str:
    if last <= 0 or open_px <= 0:
        return "—"
    if last <= stop + 1e-9:
        return "止损侧"
    if last >= buy - 1e-9:
        return "突破侧"
    return "区间内"


def enrich_theme_row(item: dict[str, Any], *, quote: dict[str, Any] | None, gate_ok: bool) -> dict[str, Any]:
    f1p = _factor1_params()
    entry_pct = float(f1p.get("entry_pct") or DEFAULT_PCT)
    stop_pct = float(f1p.get("stop_pct") or entry_pct)
    tick = float(f1p.get("tick") or TICK_SIZE)
    quote_name = str(quote.get("name") or "") if quote else ""
    code = str(item.get("code") or "").zfill(6)
    display_name = _display_stock_name(
        code=code,
        symbol=str(item.get("symbol") or ""),
        raw_name=str(item.get("name") or ""),
        quote_name=quote_name,
    )
    row = {
        "代码": code,
        "名称": display_name,
        "题材": item.get("题材"),
        "题材涨停数": item.get("题材涨停数"),
        "类型": item.get("类型"),
        "当日涨停": item.get("当日涨停"),
        "可操作": gate_ok,
        "买点": None,
        "止损": None,
        "阈值%": f"±{entry_pct * 100:.1f}",
        "因子侧": "—",
        "挂单说明": "—",
        "现价": None,
        "开盘": None,
    }
    if not quote:
        row["挂单说明"] = "无行情" if gate_ok else "情绪未过·观望"
        return row
    open_px = float(quote.get("open") or item.get("开盘") or 0)
    last = float(quote.get("last") or item.get("现价") or 0)
    high = float(quote.get("high") or last)
    lv = strategy_levels(open_px, entry_pct=entry_pct, stop_pct=stop_pct, tick=tick)
    px_digits = _px_digits(tick)
    row["开盘"] = round(open_px, px_digits) if open_px > 0 else None
    row["现价"] = round(last, px_digits) if last > 0 else None
    row["买点"] = round(lv["buy_trigger"], px_digits)
    row["止损"] = round(lv["stop"], px_digits)
    row["因子侧"] = _factor_side_label(
        last=last, open_px=open_px, buy=lv["buy_trigger"], stop=lv["stop"]
    )
    hit_buy = gate_ok and high + 1e-12 >= lv["buy_trigger"]
    if not gate_ok:
        row["挂单说明"] = "情绪未过·观望"
    elif hit_buy:
        row["挂单说明"] = "已触买点"
    else:
        row["挂单说明"] = "待突破"
    return row


def build_strategy8_payload(
    *,
    session: str | None = None,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
    batch_quote: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    trade_date = session or ""
    if not trade_date:
        df = _load_sentiment_df()
        trade_date = str(df["date"].iloc[-1].date()) if not df.empty else str(pd.Timestamp.now().date())

    effective = _normalize_trade_date(trade_date) or trade_date
    sentiment = get_market_sentiment(trade_date)
    gate_ok = bool(sentiment.get("gateOk"))

    from watch_config import sina_of

    univ = _load_univ()
    if univ.empty or "code" not in univ.columns:
        codes: list[str] = []
    else:
        codes = [str(c).zfill(6) for c in univ["code"]]
    sinas = [sina_of(c).lower() for c in codes]
    quotes: dict[str, dict[str, Any]] = {}
    if batch_quote and sinas:
        quotes = {k.lower(): v for k, v in batch_quote(sinas).items()}
    if get_quote:
        for s in sinas:
            if quotes.get(s):
                continue
            try:
                q = get_quote(s)
                if q:
                    quotes[s] = q
            except Exception:  # noqa: BLE001
                pass

    scanned = scan_theme_linkage_pool(effective, quotes=quotes)
    pool = scanned.get("rows") or []

    pool_sinas = [sina_of(str(p["code"])) for p in pool]
    if batch_quote:
        more = batch_quote([s.lower() for s in pool_sinas])
        quotes.update({k.lower(): v for k, v in more.items()})

    rows = []
    for item in pool:
        code = str(item.get("code") or "")
        sina = sina_of(code).lower()
        row = enrich_theme_row(item, quote=quotes.get(sina), gate_ok=gate_ok)
        rows.append(row)

    name_map = lookup_names_for_codes([str(r.get("代码") or "") for r in rows])
    for row in rows:
        c = str(row.get("代码") or "").zfill(6)
        if not row.get("名称") or str(row.get("名称")) == c:
            row["名称"] = name_map.get(c) or row.get("名称") or c

    return {
        "sentiment": sentiment,
        "hotThemes": scanned.get("hotThemes") or [],
        "themeDate": scanned.get("themeDate"),
        "luCount": scanned.get("luCount"),
        "poolCount": len(rows),
        "rows": rows,
        "nameMap": name_map,
        "backtest": load_backtest_summary(),
        "rules": f"当日涨停定题材≥{MIN_THEME_LU} · 当日因子1 ±阈值 · {_gate_rules_text()}",
    }
