"""行情数据拉取（各策略共用）。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

# 相邻两根日线日历间隔超过该值视为可疑缺口（含春节长假缓冲）
_MAX_BAR_GAP_DAYS = 20


def _latest_completed_weekday(now: dt.datetime | None = None) -> dt.date:
    """返回可安全拉取日线的最近工作日（收盘后 15:15 才包含当天）。"""
    now = now or dt.datetime.now()
    day = now.date()
    if (now.hour, now.minute) < (15, 15):
        day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _is_etf_symbol(symbol: str) -> bool:
    """识别常见场内 ETF / LOF 代码（带 sh/sz 前缀）。"""
    sym = str(symbol or "").strip().lower()
    if not sym.startswith(("sh", "sz")) or len(sym) < 8:
        return False
    code = sym[2:]
    return code.startswith(("51", "56", "58", "15", "16", "18"))


def _normalize_daily(
    raw: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """统一日线字段、交易时点与时区。"""
    if raw is None or raw.empty:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "symbol"]
        )
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
    if "date" not in df.columns:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "symbol"]
        )
    df["date"] = pd.to_datetime(df["date"])
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    df = df[(df["date"] >= start_ts) & (df["date"] < end_ts)]
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    if df.empty:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "symbol"]
        )
    df["symbol"] = symbol
    df["date"] = df["date"].dt.normalize() + pd.Timedelta(hours=15)
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    else:
        df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
    return df[["date", "open", "high", "low", "close", "volume", "symbol"]].reset_index(
        drop=True
    )


def _fetch_etf_daily_remote(symbol: str, start: str, end: str) -> pd.DataFrame:
    """ETF 前复权日线（东财 fund_etf_hist_em）。"""
    code = str(symbol).strip().lower()[2:]
    try:
        raw = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    except Exception as exc:
        raise RuntimeError(
            f"AkShare ETF 日线拉取失败: {symbol} {start}~{end}"
        ) from exc
    return _normalize_daily(raw, symbol=symbol, start=start, end=end)


def _fetch_stock_daily_remote(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股个股前复权日线。"""
    try:
        raw = ak.stock_zh_a_daily(
            symbol=symbol, start_date=start, end_date=end, adjust="qfq"
        )
    except Exception as exc:
        raise RuntimeError(
            f"AkShare 个股日线拉取失败: {symbol} {start}~{end}"
        ) from exc
    return _normalize_daily(raw, symbol=symbol, start=start, end=end)


def _fetch_daily_remote(symbol: str, start: str, end: str) -> pd.DataFrame:
    """从 AkShare 拉取指定区间的前复权日线（ETF / 个股分流）。"""
    sym = str(symbol or "").strip().lower()
    if not sym.startswith(("sh", "sz")):
        raise ValueError(f"仅支持 A 股 sh/sz 标的: {symbol}")
    if _is_etf_symbol(sym):
        return _fetch_etf_daily_remote(sym, start, end)
    return _fetch_stock_daily_remote(sym, start, end)


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume", "symbol"]
    )


def _cache_symbol_mismatch(df: pd.DataFrame, symbol: str) -> bool:
    if df.empty or "symbol" not in df.columns:
        return False
    syms = {
        str(s).strip().lower()
        for s in df["symbol"].dropna().tolist()
        if str(s).strip()
    }
    if not syms:
        return False
    return symbol.lower() not in syms or len(syms) > 1


def _cache_has_suspicious_gaps(df: pd.DataFrame) -> bool:
    if df is None or len(df) < 2:
        return False
    days = sorted(pd.to_datetime(df["date"]).dt.date.unique())
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days > _MAX_BAR_GAP_DAYS:
            return True
    return False


def _read_daily_cache(path: Path, symbol: str) -> pd.DataFrame:
    if not path.exists():
        return _empty_daily()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return _empty_daily()
    if df.empty or not {"date", "open", "high", "low", "close"}.issubset(df.columns):
        return _empty_daily()
    if _cache_symbol_mismatch(df, symbol):
        return _empty_daily()
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    else:
        df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
    df["symbol"] = symbol
    if "volume" not in df.columns:
        df["volume"] = 0.0
    out = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    if _cache_has_suspicious_gaps(out):
        return _empty_daily()
    return out


def _write_daily_cache(path: Path, daily: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = daily.sort_values("date").copy()
    if not out.empty:
        out["symbol"] = out["symbol"].astype(str)
    out.to_parquet(path, index=False)


def _default_daily_cache_path(symbol: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "data_cache" / f"{symbol.lower()}_daily_qfq.parquet"


def fetch_daily(
    symbol: str,
    start: str,
    end: str,
    *,
    cache_path: Path | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """读取前复权日线缓存，只拉取缓存区间外缺失数据。

    `force_refresh=True` 会重拉完整区间，用于前复权数据在除权除息后的全量校正。
    缓存标的不符或相邻 K 线日历缺口过大时，自动全量重拉。
    """
    requested_start = pd.Timestamp(start).date()
    requested_end = min(pd.Timestamp(end).date(), _latest_completed_weekday())
    if requested_end < requested_start:
        raise ValueError(f"无已收盘交易日: {symbol} {start}~{end}")
    cache_path = cache_path or _default_daily_cache_path(symbol)

    cache = (
        _read_daily_cache(cache_path, symbol)
        if cache_path is not None and not force_refresh
        else _empty_daily()
    )
    parts: list[pd.DataFrame] = [cache] if not cache.empty else []
    if force_refresh or cache.empty:
        remote = _fetch_daily_remote(
            symbol, requested_start.strftime("%Y%m%d"), requested_end.strftime("%Y%m%d")
        )
        if not remote.empty:
            parts = [remote]
    else:
        cache_days = pd.to_datetime(cache["date"]).dt.date
        cache_start = cache_days.min()
        cache_end = cache_days.max()
        if requested_start < cache_start:
            remote = _fetch_daily_remote(
                symbol,
                requested_start.strftime("%Y%m%d"),
                (cache_start - dt.timedelta(days=1)).strftime("%Y%m%d"),
            )
            if not remote.empty:
                parts.append(remote)
        if requested_end > cache_end:
            remote = _fetch_daily_remote(
                symbol,
                (cache_end + dt.timedelta(days=1)).strftime("%Y%m%d"),
                requested_end.strftime("%Y%m%d"),
            )
            if not remote.empty:
                parts.append(remote)

    if not parts:
        raise RuntimeError(f"未获取到日线: {symbol} {start}~{end}")
    merged = pd.concat(parts, ignore_index=True)
    merged = (
        merged.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    merged["symbol"] = symbol
    if _cache_has_suspicious_gaps(merged):
        # 增量合并后仍有大缺口 → 全量重拉
        merged = _fetch_daily_remote(
            symbol,
            requested_start.strftime("%Y%m%d"),
            requested_end.strftime("%Y%m%d"),
        )
        if merged.empty:
            raise RuntimeError(f"缺口修复后仍无日线: {symbol} {start}~{end}")
        merged["symbol"] = symbol
    if cache_path is not None:
        _write_daily_cache(cache_path, merged)

    days = pd.to_datetime(merged["date"]).dt.date
    out = merged[(days >= requested_start) & (days <= requested_end)].copy()
    if out.empty:
        raise RuntimeError(f"日线裁剪后为空: {symbol} {start}~{end}")
    return out.reset_index(drop=True)


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
