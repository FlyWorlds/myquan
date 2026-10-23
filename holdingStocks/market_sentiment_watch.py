"""情绪与涨停公共数据，供策略八/十五使用。"""

from __future__ import annotations

import bisect
import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.strategies.strategy3.sentiment_phase import classify_mkt_lu_phase
from strategy.open_break import DEFAULT_PCT, TICK_SIZE, strategy_levels
from stock_names import resolve_stock_name

_MYQUAN = Path(__file__).resolve().parents[1]
SENTIMENT_PATH = _MYQUAN / "backtest" / "strategy3_first_board" / "mkt_sentiment_zz1000.parquet"
SUMMARY_PATH = _MYQUAN / "backtest" / "strategy3_first_board" / "summary.json"
UNIV_PATH = _MYQUAN / "backtest" / "strategy3_first_board" / "zz1000_univ.parquet"
UNIV_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
LU_TOL = 0.012

# 与 first_board 默认一致（T-1）
SENTIMENT_LAG = 1
MKT_LU_MIN: int | None = None
MKT_LU_MAX: int | None = None
MKT_LIANBAN_MIN: int | None = 2
MKT_MAX_HEIGHT_MIN: int | None = 2
MKT_MAX_HEIGHT_MAX: int | None = 5

_POOL_SCAN_CACHE: dict[str, list[dict[str, Any]]] = {}
_POOL_CACHE_VER = "lu_all_v2"


def limit_ratio(code: str) -> float:
    c = str(code).zfill(6)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def _is_limit_up_close(prev_close: float, close: float, high: float, lim: float) -> bool:
    if prev_close <= 0 or close <= 0:
        return False
    pct = close / prev_close - 1.0
    return pct >= lim - LU_TOL and close >= high * 0.995


@lru_cache(maxsize=1)
def _load_sentiment_df() -> pd.DataFrame:
    if not SENTIMENT_PATH.is_file():
        return pd.DataFrame()
    df = pd.read_parquet(SENTIMENT_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


@lru_cache(maxsize=1)
def _load_univ() -> pd.DataFrame:
    if not UNIV_PATH.is_file():
        return pd.DataFrame()
    return pd.read_parquet(UNIV_PATH)


def _load_symbol_daily(symbol: str) -> pd.DataFrame | None:
    p = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not p.is_file():
        return None
    df = pd.read_parquet(p)
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    return d if len(d) >= 3 else None


def _trade_calendar() -> list[str]:
    df = _load_sentiment_df()
    if df.empty:
        return []
    return [str(d.date()) for d in df["date"]]


def _normalize_trade_date(trade_date: str) -> str | None:
    """将晋级日映射到情绪日历上最近的有效交易日（≤ trade_date）。"""
    if not trade_date:
        return None
    ds = _trade_calendar()
    if not ds:
        return None
    if trade_date in ds:
        return trade_date
    idx = bisect.bisect_right(ds, trade_date) - 1
    if idx < 0:
        return None
    return ds[idx]


def _prev_trade_date(trade_date: str) -> str | None:
    eff = _normalize_trade_date(trade_date)
    if eff is None:
        return None
    ds = _trade_calendar()
    try:
        idx = ds.index(eff)
    except ValueError:
        return None
    target = idx - max(SENTIMENT_LAG, 0)
    if target < 0:
        return None
    return ds[target]


def _gate_ok(row: dict[str, int]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    lu = int(row.get("mkt_lu", 0))
    lb = int(row.get("mkt_lianban", 0))
    h = int(row.get("mkt_max_height", 0))
    ok = True
    if MKT_LU_MIN is not None and lu < MKT_LU_MIN:
        ok = False
        reasons.append(f"涨停家数{lu}<{MKT_LU_MIN}")
    if MKT_LU_MAX is not None and lu > MKT_LU_MAX:
        ok = False
        reasons.append(f"涨停家数{lu}>{MKT_LU_MAX}")
    if MKT_LIANBAN_MIN is not None and lb < MKT_LIANBAN_MIN:
        ok = False
        reasons.append(f"连板家数{lb}<{MKT_LIANBAN_MIN}")
    if MKT_MAX_HEIGHT_MIN is not None and h < MKT_MAX_HEIGHT_MIN:
        ok = False
        reasons.append(f"最高板{h}<{MKT_MAX_HEIGHT_MIN}")
    if MKT_MAX_HEIGHT_MAX is not None and h > MKT_MAX_HEIGHT_MAX:
        ok = False
        reasons.append(f"最高板{h}>{MKT_MAX_HEIGHT_MAX}")
    return ok, reasons


def get_market_sentiment(trade_date: str) -> dict[str, Any]:
    """晋级日 trade_date 对应 T-1 情绪与门槛判定。"""
    raw = trade_date or ""
    effective = _normalize_trade_date(raw) if raw else None
    if not effective:
        df = _load_sentiment_df()
        effective = str(df["date"].iloc[-1].date()) if not df.empty else None
    ref = _prev_trade_date(effective or "")
    df = _load_sentiment_df()
    cache_note = ""
    if raw and effective and raw != effective:
        cache_note = f"行情日 {raw} 无本地情绪缓存，已回退至 {effective}"
    if ref is None or df.empty or not effective:
        return {
            "tradeDate": effective or raw,
            "rawTradeDate": raw or None,
            "sentimentDate": ref,
            "gateOk": False,
            "gateReasons": ["无情绪缓存"],
            "rules": _gate_rules_text(),
            "cacheNote": cache_note,
        }
    ts = pd.Timestamp(ref).normalize()
    hit = df[df["date"] == ts]
    if hit.empty:
        return {
            "tradeDate": effective,
            "rawTradeDate": raw or None,
            "sentimentDate": ref,
            "gateOk": False,
            "gateReasons": ["情绪日无数据"],
            "rules": _gate_rules_text(),
            "cacheNote": cache_note,
        }
    r = hit.iloc[0]
    row = {
        "mkt_lu": int(r["mkt_lu"]),
        "mkt_lianban": int(r["mkt_lianban"]),
        "mkt_max_height": int(r["mkt_max_height"]),
        "mkt_ladder_score": int(r["mkt_ladder_score"]),
    }
    ok, reasons = _gate_ok(row)
    phase = classify_mkt_lu_phase(row["mkt_lu"])
    return {
        "tradeDate": effective,
        "rawTradeDate": raw or None,
        "sentimentDate": ref,
        **row,
        **phase,
        "gateOk": ok,
        "gateReasons": reasons if not ok else [],
        "rules": _gate_rules_text(),
        "cacheNote": cache_note,
    }


def _gate_rules_text() -> str:
    parts = [f"T-{SENTIMENT_LAG}"]
    if MKT_LIANBAN_MIN is not None:
        parts.append(f"连板≥{MKT_LIANBAN_MIN}")
    if MKT_MAX_HEIGHT_MIN is not None or MKT_MAX_HEIGHT_MAX is not None:
        lo = MKT_MAX_HEIGHT_MIN if MKT_MAX_HEIGHT_MIN is not None else "—"
        hi = MKT_MAX_HEIGHT_MAX if MKT_MAX_HEIGHT_MAX is not None else "—"
        parts.append(f"最高板{lo}～{hi}")
    if MKT_LU_MIN is not None or MKT_LU_MAX is not None:
        lo = MKT_LU_MIN if MKT_LU_MIN is not None else "—"
        hi = MKT_LU_MAX if MKT_LU_MAX is not None else "—"
        parts.append(f"涨停家数{lo}～{hi}")
    return " · ".join(parts)


def load_backtest_summary() -> list[dict[str, Any]]:
    if not SUMMARY_PATH.is_file():
        return []
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _factor1_params() -> dict[str, Any]:
    return {"entry_pct": DEFAULT_PCT, "stop_pct": DEFAULT_PCT, "prev_entry_mode": "limit_up_ok"}


def _lu_at(
    i: int,
    *,
    prev: np.ndarray,
    c: np.ndarray,
    h: np.ndarray,
    lim: float,
) -> bool:
    pc = float(prev[i]) if np.isfinite(prev[i]) else 0.0
    if pc <= 0:
        return False
    return _is_limit_up_close(pc, float(c[i]), float(h[i]), lim)


def scan_yesterday_limit_up_pool(session: str) -> list[dict[str, Any]]:
    """中证1000 宇宙内，晋级日 session 的「昨日（T-1）收盘涨停」全池。"""
    effective = _normalize_trade_date(session) if session else None
    if not effective:
        return []
    cache_key = f"{_POOL_CACHE_VER}:{effective}"
    cached = _POOL_SCAN_CACHE.get(cache_key)
    if cached is not None:
        return cached

    univ = _load_univ()
    if univ.empty:
        _POOL_SCAN_CACHE[cache_key] = []
        return []

    prev_d = _prev_trade_date(effective)
    if prev_d is None:
        _POOL_SCAN_CACHE[cache_key] = []
        return []
    prev_ts = pd.Timestamp(prev_d).normalize()
    pool: list[dict[str, Any]] = []
    sess = pd.Timestamp(effective).normalize()

    for row in univ.itertuples(index=False):
        code = str(row.code).zfill(6)
        name = str(row.name)
        symbol = str(row.symbol)
        daily = _load_symbol_daily(symbol)
        if daily is None:
            continue

        d = daily
        idx_prev = d.index[d["date"] == prev_ts]
        if len(idx_prev) == 0:
            continue
        i = int(idx_prev[0])
        if i < 1:
            continue
        lim = limit_ratio(code)
        c = d["close"].to_numpy(float)
        h = d["high"].to_numpy(float)
        vol = d["volume"].to_numpy(float) if "volume" in d.columns else np.ones(len(d))
        prev = np.roll(c, 1)
        prev[0] = np.nan
        lu = np.zeros(len(c), dtype=bool)
        for k in range(1, len(c)):
            lu[k] = _lu_at(k, prev=prev, c=c, h=h, lim=lim)
        if not lu[i]:
            continue
        streak = 1
        k = i - 1
        while k >= 1 and lu[k]:
            streak += 1
            k -= 1
        first_board = streak == 1

        fb_close = float(c[i])
        gap_pct: float | None = None
        vol_ratio: float | None = None
        idx_sess = d.index[d["date"] == sess]
        if len(idx_sess) > 0:
            j = int(idx_sess[0])
            if j == i + 1:
                oj = float(d["open"].iloc[j])
                if fb_close > 0 and oj > 0:
                    gap = oj / fb_close - 1.0
                    gap_pct = round(gap * 100, 2)
                    vwin = vol[max(0, i - 20) : i + 1]
                    vr = float(vol[i]) / float(np.mean(vwin)) if len(vwin) and np.mean(vwin) > 0 else 1.0
                    vol_ratio = round(vr, 2)

        pool.append(
            {
                "code": code,
                "name": resolve_stock_name(symbol=symbol, code=code, name=name),
                "symbol": symbol,
                "涨停日": str(d["date"].iloc[i].date()),
                "涨停收": fb_close,
                "昨日首板": first_board,
                "连板": streak,
                "首板日": str(d["date"].iloc[i].date()) if first_board else None,
                "晋级低开%": gap_pct,
                "量比": vol_ratio,
            }
        )

    pool.sort(key=lambda x: (-int(x.get("连板") or 0), str(x.get("code") or "")))
    _POOL_SCAN_CACHE[cache_key] = pool
    return pool


def enrich_first_board_row(
    *,
    code: str,
    daily: pd.DataFrame,
    session: str,
    open_px: float,
) -> dict[str, Any]:
    """定盘池单票：昨日是否首板、晋级日 gap/量比（研究字段）。"""
    out: dict[str, Any] = {
        "昨日首板": False,
        "首板日": None,
        "晋级低开%": None,
        "量比": None,
        "晋级可跟踪": False,
    }
    if daily is None or daily.empty or not session:
        return out
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.sort_values("date").reset_index(drop=True)
    sess = pd.Timestamp(session).normalize()
    idx = d.index[d["date"] == sess]
    if len(idx) == 0:
        return out
    j = int(idx[0])
    if j < 2:
        return out
    i = j - 1
    lim = limit_ratio(code)
    c = d["close"].to_numpy(float)
    h = d["high"].to_numpy(float)
    o = d["open"].to_numpy(float)
    vol = d["volume"].to_numpy(float) if "volume" in d.columns else np.ones(len(d))
    prev = np.roll(c, 1)
    prev[0] = np.nan
    lu = np.zeros(len(c), dtype=bool)
    for k in range(1, len(c)):
        pc = float(prev[k]) if np.isfinite(prev[k]) else 0.0
        if pc > 0:
            lu[k] = _is_limit_up_close(pc, float(c[k]), float(h[k]), lim)
    first_board = bool(lu[i] and not (i >= 1 and lu[i - 1]))
    out["昨日首板"] = first_board
    if first_board:
        out["首板日"] = str(d["date"].iloc[i].date())
        fb_close = float(c[i])
        if fb_close > 0 and open_px > 0:
            gap = open_px / fb_close - 1.0
            out["晋级低开%"] = round(gap * 100, 2)
            vwin = vol[max(0, i - 20) : i + 1]
            vr = float(vol[i]) / float(np.mean(vwin)) if len(vwin) and np.mean(vwin) > 0 else 1.0
            out["量比"] = round(vr, 2)
            out["晋级可跟踪"] = bool(-4.5 <= gap * 100 <= -0.3 and vr >= 1.4)
    return out


