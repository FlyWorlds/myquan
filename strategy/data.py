"""行情数据拉取（各策略共用）。"""

from __future__ import annotations

import datetime as dt

import akshare as ak
import pandas as pd
import requests


def fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    raw: pd.DataFrame | None = None
    try:
        raw = ak.stock_zh_a_daily(
            symbol=symbol, start_date=start, end_date=end, adjust="qfq"
        )
    except Exception:
        raw = None
    if raw is None or raw.empty:
        code = symbol[2:] if len(symbol) > 2 and symbol[:2] in ("sh", "sz") else symbol
        raw = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    if raw is None or raw.empty:
        raise RuntimeError(f"未获取到日线: {symbol} {start}~{end}")

    df = raw.copy()
    rename = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "date" not in df.columns and "日期" in df.columns:
        df = df.rename(columns={"日期": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df["symbol"] = symbol
    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    return df[["date", "open", "high", "low", "close", "volume", "symbol"]].reset_index(
        drop=True
    )


def fetch_today_snapshot(symbol: str) -> dict | None:
    """东财当日快照（未收盘时补全最新一根日线）。"""
    if len(symbol) < 8 or symbol[:2] not in ("sh", "sz"):
        return None
    market = "1" if symbol.startswith("sh") else "0"
    code = symbol[2:]
    try:
        resp = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": f"{market}.{code}",
                "fields": "f43,f44,f45,f46,f47,f60",
            },
            timeout=10,
        )
        data = resp.json().get("data") or {}
        o, h, low, c = (float(data[k]) / 100.0 for k in ("f46", "f44", "f45", "f43"))
        vol = float(data.get("f47") or 0.0)
        if min(o, h, low, c) <= 0:
            return None
        today = dt.date.today()
        ts = pd.Timestamp(today) + pd.Timedelta(hours=15)
        ts = ts.tz_localize("Asia/Shanghai")
        return {
            "date": ts,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "volume": vol,
            "symbol": symbol,
        }
    except Exception:
        return None


def append_today_if_missing(daily: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """若日线未含当日，尝试用快照补一条。"""
    if daily.empty:
        return daily
    today = dt.date.today()
    last_day = pd.to_datetime(daily["date"].iloc[-1]).date()
    if last_day >= today:
        return daily
    snap = fetch_today_snapshot(symbol)
    if snap is None:
        return daily
    row = pd.DataFrame([snap])
    return pd.concat([daily, row], ignore_index=True)
