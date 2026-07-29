"""1 分钟线拉取与标准化（回测低开 9:45 规则）。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import akshare as ak
import pandas as pd


def standardize_minute_1m(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    time_col = next((c for c in ("时间", "day", "date") if c in df.columns), None)
    if time_col is None:
        return pd.DataFrame()
    rename = {
        time_col: "ts",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
    }
    for src, dst in rename.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})
    need = ["ts", "open", "high", "low", "close"]
    if not all(c in df.columns for c in need):
        return pd.DataFrame()
    out = df[need].copy()
    out["ts"] = pd.to_datetime(out["ts"])
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["ts", "open", "high", "low", "close"])
    out = out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    if out["ts"].dt.tz is None:
        out["ts"] = out["ts"].dt.tz_localize("Asia/Shanghai")
    else:
        out["ts"] = out["ts"].dt.tz_convert("Asia/Shanghai")
    return out.reset_index(drop=True)


def fetch_minute_1m(
    *,
    sina_symbol: str,
    em_symbol: str,
    cache_path: Path,
    refresh: bool = False,
    lookback_days: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取 1 分钟线；回测可传 start_date/end_date（YYYYMMDD）拉全区间。"""
    cached = pd.DataFrame()
    if cache_path.exists() and not refresh:
        cached = standardize_minute_1m(pd.read_parquet(cache_path))

    chunks: list[pd.DataFrame] = []
    if start_date and end_date:
        start_dt = dt.datetime.strptime(start_date, "%Y%m%d")
        end_dt = dt.datetime.strptime(end_date, "%Y%m%d")
        cur = start_dt
        while cur <= end_dt:
            chunk_end = min(cur + dt.timedelta(days=40), end_dt)
            try:
                em = ak.stock_zh_a_hist_min_em(
                    symbol=em_symbol,
                    period="1",
                    start_date=cur.strftime("%Y-%m-%d 09:30:00"),
                    end_date=chunk_end.strftime("%Y-%m-%d 15:00:00"),
                    adjust="qfq",
                )
                part = standardize_minute_1m(em)
                if not part.empty:
                    chunks.append(part)
            except Exception:
                pass
            cur = chunk_end + dt.timedelta(days=1)
    else:
        end_dt = dt.datetime.now()
        start_dt = end_dt - dt.timedelta(days=max(lookback_days, 3))
        try:
            em = ak.stock_zh_a_hist_min_em(
                symbol=em_symbol,
                period="1",
                start_date=start_dt.strftime("%Y-%m-%d 09:30:00"),
                end_date=end_dt.strftime("%Y-%m-%d 15:00:00"),
                adjust="qfq",
            )
            chunks.append(standardize_minute_1m(em))
        except Exception:
            pass
        try:
            sina = standardize_minute_1m(
                ak.stock_zh_a_minute(symbol=sina_symbol, period="1", adjust="qfq")
            )
            chunks.append(sina)
        except Exception:
            pass

    fresh = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    parts = [x for x in (cached, fresh) if x is not None and not x.empty]
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    return out.reset_index(drop=True)
