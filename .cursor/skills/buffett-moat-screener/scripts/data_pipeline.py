"""Point-in-time A-share data acquisition and annual normalization."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

import numpy as np
import pandas as pd

from .core import DEFAULT_INDEX, FINANCIAL_FIELDS
from .panda_adapter import PandaDataError, fetch as _panda_fetch
from .v9_engine import resolve_all_a


_CACHE_DIR: Path | None = None


def configure_cache(cache_dir: str | Path | None) -> None:
    """Set a run-scoped, data-only cache for expensive Panda reads."""
    global _CACHE_DIR
    if cache_dir is None:
        _CACHE_DIR = None
        return
    _CACHE_DIR = Path(cache_dir)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(name: str, kwargs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"name": name, "kwargs": kwargs},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fetch(name: str, **kwargs: Any) -> pd.DataFrame:
    """Read Panda data with an optional immutable request cache.

    Cache files contain only returned market data. Credentials remain owned by
    ``panda_adapter`` and are never part of the cache key or payload.
    """
    retry_delays = kwargs.pop("_retry_delays", None)
    cache_path = None
    if _CACHE_DIR is not None:
        cache_path = _CACHE_DIR / f"{name}-{_cache_key(name, kwargs)}.parquet"
        if cache_path.exists():
            try:
                cached = pd.read_parquet(cache_path)
                if kwargs.get("annual_only") and "quarter" in cached.columns:
                    cached = cached[cached["quarter"].astype(str).str.lower().str.match(r"^\d{4}q4$")].copy()
                return cached
            except (OSError, ValueError, ImportError):
                cache_path.unlink(missing_ok=True)
    if retry_delays is None:
        result = _panda_fetch(name, **kwargs)
    else:
        result = _panda_fetch(name, _retry_delays=retry_delays, **kwargs)
    if cache_path is not None:
        temporary = cache_path.with_name(
            f"{cache_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            try:
                result.to_parquet(temporary, index=False)
            except Exception:
                # Reference endpoints occasionally return mixed object columns
                # (for example numeric values plus NaN text).  Normalize only
                # the cache copy; callers still receive the original frame.
                if temporary.exists():
                    temporary.unlink(missing_ok=True)
                safe = result.copy()
                for column in safe.select_dtypes(include=["object"]).columns:
                    safe[column] = safe[column].map(
                        lambda value: None if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)
                    )
                safe.to_parquet(temporary, index=False)
                result = safe
            try:
                temporary.replace(cache_path)
            except (FileNotFoundError, PermissionError):
                # Another process may have completed the same immutable
                # request while this worker was serializing its response.
                # Prefer the completed cache and keep the current response;
                # never turn a harmless cache race into a failed backtest.
                if not cache_path.exists():
                    raise
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # A concurrent writer owns the shared temporary path.
                pass
    return result


CANONICAL_FIELDS = {
    "parent_net_profit": ("is_n_income_attr_p",),
    "parent_equity": ("bs_total_hldr_eqy_exc_min_int",),
    "total_assets": ("bs_total_assets",),
    "gross_profit": ("is_gross_profit",),
    "revenue": ("is_revenue",),
    "gross_capex": ("cfs_cash_paid_asset",),
    "operating_cash_flow": ("cfs_net_cash_operating", "cfs_net_cashflow_operate"),
    "basic_eps": ("is_basic_eps",),
    "operating_profit": ("is_operate_profit",),
    "total_profit": ("is_total_profit",),
    "income_tax": ("is_income_tax",),
    "cash_equivalents": ("cfs_end_cash_equiv",),
}
DEBT_FIELDS = (
    "bs_longterm_loan",
    "bs_bonds_payable",
    "bs_lease_liab",
    "bs_noncurrent_liab_due_1y",
)


def clean_symbol(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    symbol = str(value).strip().upper()
    return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol


def discover_symbols(as_of: str, index_symbol: str = DEFAULT_INDEX) -> list[str]:
    start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
    frame = fetch(
        "get_index_weights",
        index_symbol=index_symbol,
        start_date=start,
        end_date=as_of,
        fields=["index_symbol", "stock_symbol", "date"],
    )
    if frame.empty:
        raise PandaDataError("Panda Data 未返回指数权重")
    symbol_column = "stock_symbol" if "stock_symbol" in frame else "symbol"
    if symbol_column not in frame or "date" not in frame:
        raise PandaDataError("指数权重缺少 stock_symbol/date")
    dated = frame.copy()
    dated["date"] = dated["date"].astype(str)
    dated = dated[dated["date"] <= as_of]
    if dated.empty:
        raise PandaDataError("截止日之前没有指数权重截面")
    latest = dated[dated["date"] == dated["date"].max()]
    return sorted({symbol for symbol in latest[symbol_column].map(clean_symbol) if symbol})


def discover_all_a(as_of: str) -> tuple[list[str], pd.DataFrame]:
    """Discover the full point-in-time SH/SZ universe from security metadata.

    This intentionally does not use the index endpoint and therefore includes
    historical constituents and delisted names visible in Panda metadata.
    """
    details = fetch("get_stock_detail", status=None)
    universe = resolve_all_a(details, as_of)
    if universe.empty:
        raise PandaDataError("Panda Data 未返回截止日有效的沪深 A 股股票池")
    return sorted(universe["symbol"].astype(str).unique()), universe


def fetch_financial_history(
    symbols: list[str], as_of: str, years: int = 12, batch_size: int = 20,
    *, annual_only: bool = False,
) -> pd.DataFrame:
    latest_year = int(as_of[:4])
    start_year = latest_year - years
    frames: list[pd.DataFrame] = []
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        chunk_start = start_year
        while chunk_start <= latest_year:
            chunk_end = min(chunk_start + 4, latest_year)
            frame = fetch(
                "get_fina_reports",
                symbol=batch,
                start_quarter=f"{chunk_start}q1",
                end_quarter=f"{chunk_end}q4",
                date=as_of,
                is_latest=False,
                fields=FINANCIAL_FIELDS,
            )
            if not frame.empty:
                if annual_only and "quarter" in frame.columns:
                    frame = frame[frame["quarter"].astype(str).str.lower().str.match(r"^\d{4}q4$")].copy()
                frames.append(frame)
            chunk_start = chunk_end + 1
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def select_atomic_annual_revisions(
    frame: pd.DataFrame, as_of: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if frame.empty:
        return frame.copy(), []
    required = {"symbol", "quarter", "date"}
    if not required.issubset(frame.columns):
        raise PandaDataError(f"财报缺少字段：{sorted(required - set(frame.columns))}")
    work = frame.copy()
    work["symbol"] = work["symbol"].map(clean_symbol)
    work["quarter"] = work["quarter"].astype(str).str.lower()
    work["date"] = work["date"].astype(str).str.replace("-", "", regex=False)
    work = work[
        work["quarter"].str.match(r"^\d{4}q4$") & (work["date"] <= str(as_of)[:8])
    ].drop_duplicates()
    if work.empty:
        return work, []
    keys = ["symbol", "quarter"]
    work = work.sort_values(keys + ["date"], kind="stable")
    latest_date = work.groupby(keys, sort=False)["date"].transform("max")
    latest_rows = work[work["date"].eq(latest_date)].copy()
    conflicts: list[dict[str, Any]] = []
    value_columns = [column for column in latest_rows.columns if column not in {"date"}]
    if value_columns:
        varying = latest_rows.groupby(keys, sort=False)[value_columns].nunique(dropna=False).gt(1).any(axis=1)
        for (symbol, quarter), is_conflict in varying.items():
            if bool(is_conflict):
                published_at = latest_rows.loc[
                    (latest_rows["symbol"] == symbol) & (latest_rows["quarter"] == quarter), "date"
                ].max()
                conflicts.append({"symbol": symbol, "quarter": quarter, "published_at": published_at})
    selected = latest_rows.drop_duplicates(keys, keep="last").reset_index(drop=True)
    return selected, conflicts


def normalize_annual_history(
    frame: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = pd.DataFrame()
    result["symbol"] = frame["symbol"].map(clean_symbol)
    result["year"] = pd.to_numeric(
        frame["quarter"].astype(str).str.extract(r"(\d{4})", expand=False),
        errors="coerce",
    )
    result["published_at"] = frame["date"].astype(str)
    result["revision_id"] = (
        result["year"].astype("Int64").astype(str) + "-" + result["published_at"]
    )
    for target, sources in CANONICAL_FIELDS.items():
        values = pd.Series(np.nan, index=frame.index, dtype=float)
        for source in sources:
            if source in frame:
                values = values.fillna(pd.to_numeric(frame[source], errors="coerce"))
        result[target] = values
    debt_parts = []
    for field in DEBT_FIELDS:
        if field in frame:
            debt_parts.append(pd.to_numeric(frame[field], errors="coerce"))
    if debt_parts:
        debt = pd.concat(debt_parts, axis=1)
        result["long_term_interest_bearing_debt"] = debt.sum(axis=1, min_count=1)
    else:
        result["long_term_interest_bearing_debt"] = np.nan

    latest_prices: dict[str, float] = {}
    if not prices.empty and {"symbol", "date", "close"}.issubset(prices.columns):
        priced = prices.copy()
        priced["symbol"] = priced["symbol"].map(clean_symbol)
        priced["close"] = pd.to_numeric(priced["close"], errors="coerce")
        priced = priced.dropna(subset=["symbol", "close"]).sort_values("date")
        latest_prices = priced.groupby("symbol")["close"].last().to_dict()
    result["close"] = result["symbol"].map(latest_prices)
    return result.dropna(subset=["symbol", "year"]).sort_values(["symbol", "year"]).reset_index(drop=True)


def fetch_prices(symbols: list[str], as_of: str) -> pd.DataFrame:
    start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")
    return fetch(
        "get_stock_daily",
        symbol=symbols,
        start_date=start,
        end_date=as_of,
        fields=["symbol", "date", "close"],
    )


def fetch_signal_price_frames(
    symbols: list[str], signal_dates: list[str], batch_size: int = 50, *, return_failures: bool = False
) -> dict[str, pd.DataFrame] | tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Fetch only the short raw-price windows needed for signal valuation.

    A long historical price series is required only for selected holdings in
    the return replay.  Screening needs the last close near each signal date,
    so downloading every day for every universe name wastes requests and can
    make a full-A run appear hung.
    """
    frames: dict[str, list[pd.DataFrame]] = {str(day): [] for day in signal_dates}
    failures: list[dict[str, Any]] = []
    for day in sorted(frames):
        try:
            end = datetime.strptime(day, "%Y%m%d")
        except ValueError:
            continue
        start = (end - timedelta(days=30)).strftime("%Y%m%d")
        for offset in range(0, len(symbols), max(1, batch_size)):
            try:
                frame = fetch(
                    "get_stock_daily",
                    symbol=symbols[offset : offset + max(1, batch_size)],
                    start_date=start,
                    end_date=day,
                    fields=["symbol", "date", "close"],
                    # Signal prices are optional evidence for a date. A
                    # rate-limit response should fail that date quickly and
                    # let the outer checkpoint loop continue.
                    _retry_delays=(0, None),
                    _timeout_seconds=10,
                )
            except PandaDataError as exc:
                failures.append({"signal_date": day, "offset": offset, "error": str(exc)[:200]})
                if "500010" in str(exc) or "请求次数超限" in str(exc):
                    break
                continue
            if not frame.empty:
                frames[day].append(frame)
    output: dict[str, pd.DataFrame] = {}
    for day, parts in frames.items():
        if not parts:
            output[day] = pd.DataFrame()
            continue
        work = pd.concat(parts, ignore_index=True, sort=False)
        if {"symbol", "date"}.issubset(work.columns):
            work["symbol"] = work["symbol"].map(clean_symbol)
            work["date"] = work["date"].astype(str).str.replace("-", "", regex=False)
            work = work.drop_duplicates(["symbol", "date"], keep="last")
        output[day] = work.reset_index(drop=True)
    return (output, failures) if return_failures else output


def fetch_price_history(
    symbols: list[str], start_date: str, end_date: str, batch_size: int = 50
) -> pd.DataFrame:
    """Fetch raw closes in date partitions for local point-in-time slicing."""
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _date_chunks(start_date, end_date, 5):
        for offset in range(0, len(symbols), batch_size):
            frame = fetch(
                "get_stock_daily",
                symbol=symbols[offset : offset + batch_size],
                start_date=chunk_start,
                end_date=chunk_end,
                fields=["symbol", "date", "close"],
            )
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    if {"symbol", "date"}.issubset(result.columns):
        result["symbol"] = result["symbol"].map(clean_symbol)
        result["date"] = result["date"].astype(str).str.replace("-", "", regex=False)
        result = result.drop_duplicates(["symbol", "date"], keep="last")
    return result.reset_index(drop=True)


def fetch_execution_prices(symbols: list[str], execution_date: str) -> dict[str, float]:
    frame = fetch(
        "get_stock_daily",
        symbol=symbols,
        start_date=execution_date,
        end_date=execution_date,
        fields=["symbol", "date", "open"],
    )
    if frame.empty or not {"symbol", "open"}.issubset(frame.columns):
        return {}
    work = frame.copy()
    work["symbol"] = work["symbol"].map(clean_symbol)
    work["open"] = pd.to_numeric(work["open"], errors="coerce")
    return {
        str(row["symbol"]): float(row["open"])
        for _, row in work.dropna(subset=["symbol", "open"]).iterrows()
        if float(row["open"]) > 0
    }


def fetch_liquidity_observations(
    symbols: list[str], as_of: str, batch_size: int = 50
) -> pd.DataFrame:
    """Fetch the recent raw turnover window used by capacity checks."""
    end = datetime.strptime(as_of, "%Y%m%d")
    start = (end - timedelta(days=100)).strftime("%Y%m%d")
    frames: list[pd.DataFrame] = []
    for offset in range(0, len(symbols), max(1, batch_size)):
        frame = fetch(
            "get_stock_daily",
            symbol=symbols[offset : offset + max(1, batch_size)],
            start_date=start,
            end_date=as_of,
            fields=["symbol", "date", "close", "volume"],
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "turnover"])
    result = pd.concat(frames, ignore_index=True, sort=False)
    result["symbol"] = result["symbol"].map(clean_symbol)
    result["date"] = result["date"].astype(str).str.replace("-", "", regex=False)
    result["close"] = pd.to_numeric(result.get("close"), errors="coerce")
    result["volume"] = pd.to_numeric(result.get("volume"), errors="coerce")
    result["turnover"] = result["close"] * result["volume"]
    return result.dropna(subset=["symbol", "date", "turnover"]).drop_duplicates(
        ["symbol", "date"], keep="last"
    ).reset_index(drop=True)


def fetch_market_status_snapshot(symbols: list[str], as_of: str) -> pd.DataFrame:
    """Fetch both ordinary and ST snapshots; risk flags block only new entry."""
    frames: list[pd.DataFrame] = []
    for st in (False, True):
        frame = fetch(
            "get_stock_daily",
            symbol=symbols,
            start_date=as_of,
            end_date=as_of,
            fields=["symbol", "date", "open", "close", "volume", "trade_status", "is_st", "is_suspend"],
            st=st,
        )
        if not frame.empty:
            copy = frame.copy()
            copy["st_snapshot"] = st
            frames.append(copy)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    result["symbol"] = result.get("symbol", pd.Series(dtype=str)).map(clean_symbol)
    def flags(row: pd.Series) -> list[str]:
        st_value = row.get("is_st")
        suspended = row.get("is_suspend")
        status = str(row.get("trade_status") or "").lower()
        return [flag for flag, condition in {
            "st_risk": (False if pd.isna(st_value) else bool(st_value)) or bool(row.get("st_snapshot")),
            "suspension": (False if pd.isna(suspended) else bool(suspended)) or pd.isna(row.get("open")),
            "delisting_risk": any(token in status for token in ("pt", "delist", "退市")),
        }.items() if condition]
    result["risk_flags"] = result.apply(flags, axis=1)
    return result.drop_duplicates(["symbol", "date"], keep="last")


def fetch_trade_calendar(start_date: str, end_date: str) -> pd.DataFrame:
    frame = fetch(
        "get_trade_cal",
        start_date=start_date,
        end_date=end_date,
        exchange="SH",
    )
    if frame.empty:
        return pd.DataFrame(columns=["date", "is_open"])
    date_column = next(
        (name for name in ("date", "nature_date", "cal_date") if name in frame),
        None,
    )
    open_column = next(
        (name for name in ("is_open", "is_trade", "is_trading_day") if name in frame),
        None,
    )
    if date_column is None or open_column is None:
        raise PandaDataError("交易日历缺少日期或开市标记")
    result = pd.DataFrame(
        {
            "date": frame[date_column].astype(str).str.replace("-", "", regex=False),
            "is_open": pd.to_numeric(frame[open_column], errors="coerce").fillna(0).astype(int),
        }
    )
    return result.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def fetch_details(symbols: list[str]) -> pd.DataFrame:
    return fetch("get_stock_detail", symbol=symbols)


def industry_map(details: pd.DataFrame) -> dict[str, str]:
    if details.empty:
        return {}
    symbol_column = "symbol" if "symbol" in details else "stock_symbol"
    candidates = ["industry_name", "industry", "sw_industry_name", "sector_name"]
    industry_column = next((name for name in candidates if name in details), None)
    if symbol_column not in details or industry_column is None:
        return {}
    return {
        clean_symbol(row[symbol_column]): str(row[industry_column] or "")
        for _, row in details.iterrows()
        if clean_symbol(row[symbol_column])
    }


def historical_industry_map(frame: pd.DataFrame, as_of: str) -> dict[str, str]:
    """Resolve industry memberships effective on a historical signal date."""
    if frame.empty:
        return {}
    symbol_column = "symbol" if "symbol" in frame else "stock_symbol"
    industry_column = next(
        (name for name in ("industry_name", "industry", "sw_industry_name") if name in frame),
        None,
    )
    if symbol_column not in frame or industry_column is None or "in_date" not in frame:
        return {}
    work = frame.copy()
    work["_symbol"] = work[symbol_column].map(clean_symbol)
    work["_in"] = work["in_date"].fillna("").astype(str).str.replace("-", "", regex=False)
    if "out_date" in work:
        work["_out"] = work["out_date"].fillna("").astype(str).str.replace("-", "", regex=False)
    else:
        work["_out"] = ""
    work = work[(work["_in"] <= as_of) & ((work["_out"] == "") | (work["_out"] > as_of))]
    work = work.sort_values(["_symbol", "_in"], kind="stable").drop_duplicates("_symbol", keep="last")
    return {
        row["_symbol"]: str(row[industry_column] or "")
        for _, row in work.iterrows()
        if row["_symbol"]
    }


def fetch_historical_industries(symbols: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for offset in range(0, len(symbols), 100):
        frame = fetch(
            "get_industry_constituents",
            stock_symbol=symbols[offset : offset + 100],
            level="L1",
            fields=["stock_symbol", "l1_code", "in_date", "out_date"],
        )
        if not frame.empty:
            frames.append(frame)
    memberships = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if memberships.empty:
        return memberships
    details = fetch("get_industry_detail", level="L1", fields=["industry_code", "industry_name"])
    if not details.empty and {"industry_code", "industry_name"}.issubset(details.columns):
        names = details.set_index("industry_code")["industry_name"].astype(str).to_dict()
        memberships["industry_name"] = memberships.get("l1_code").map(names)
    return memberships


def _date_chunks(start_date: str, end_date: str, years: int) -> list[tuple[str, str]]:
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    chunks: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        try:
            boundary = cursor.replace(year=cursor.year + years) - timedelta(days=1)
        except ValueError:
            boundary = cursor.replace(month=2, day=28, year=cursor.year + years) - timedelta(days=1)
        chunk_end = min(boundary, end)
        chunks.append((cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def fetch_stock_backtest_prices(
    symbols: list[str], start_date: str, end_date: str, batch_size: int = 50,
    cache_dir: str | Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cache_root = Path(cache_dir) if cache_dir is not None else None
    if cache_root is not None:
        cache_root.mkdir(parents=True, exist_ok=True)
    ordered_symbols = sorted(set(str(symbol).upper() for symbol in symbols))
    for chunk_start, chunk_end in _date_chunks(start_date, end_date, 5):
        for offset in range(0, len(ordered_symbols), batch_size):
            batch = ordered_symbols[offset : offset + batch_size]
            batch_digest = hashlib.sha256("\n".join(batch).encode("utf-8")).hexdigest()[:12]
            cache_path = (
                cache_root / f"{chunk_start}-{chunk_end}-{offset:08d}-{batch_digest}.parquet"
                if cache_root is not None else None
            )
            if cache_path is not None and cache_path.exists():
                try:
                    cached = pd.read_parquet(cache_path)
                    if not cached.empty:
                        frames.append(cached)
                    continue
                except (OSError, ValueError):
                    cache_path.unlink(missing_ok=True)
            adjusted = fetch(
                "get_stock_daily_post",
                symbol=batch,
                start_date=chunk_start,
                end_date=chunk_end,
                fields=["symbol", "date", "open", "close", "volume"],
                st=True,
            )
            raw = fetch(
                "get_stock_daily",
                symbol=batch,
                start_date=chunk_start,
                end_date=chunk_end,
                fields=["symbol", "date", "open", "close", "pre_close", "volume", "limit_up", "limit_down"],
                st=True,
            )
            if adjusted.empty:
                merged = pd.DataFrame()
            else:
                merged = adjusted.rename(columns={"volume": "adjusted_volume"}).merge(
                raw[[column for column in ("symbol", "date", "open", "pre_close", "volume", "limit_up", "limit_down") if column in raw]],
                on=["symbol", "date"],
                how="left",
                suffixes=("", "_raw"),
                )
                raw_open = pd.to_numeric(merged.get("open_raw"), errors="coerce")
                pre_close = pd.to_numeric(merged.get("pre_close"), errors="coerce")
                raw_volume = pd.to_numeric(merged.get("volume"), errors="coerce")
                merged["tradable"] = raw_open.notna() & raw_volume.fillna(0).gt(0)
                ratio = raw_open / pre_close
                raw_limit_up = merged.get("limit_up")
                raw_limit_down = merged.get("limit_down")
                if raw_limit_up is not None:
                    upper = pd.to_numeric(raw_limit_up, errors="coerce")
                    if upper.dropna().isin([0, 1]).all():
                        merged["limit_up"] = upper.fillna(0).astype(bool)
                    else:
                        merged["limit_up"] = raw_open.ge(upper * (1.0 - 1e-8)).fillna(ratio.ge(1.095))
                else:
                    merged["limit_up"] = ratio.ge(1.095)
                if raw_limit_down is not None:
                    lower = pd.to_numeric(raw_limit_down, errors="coerce")
                    if lower.dropna().isin([0, 1]).all():
                        merged["limit_down"] = lower.fillna(0).astype(bool)
                    else:
                        merged["limit_down"] = raw_open.le(lower * (1.0 + 1e-8)).fillna(ratio.le(0.905))
                else:
                    merged["limit_down"] = ratio.le(0.905)
                merged = merged.assign(execution_price_raw=raw_open)[
                    ["symbol", "date", "open", "close", "execution_price_raw", "tradable", "limit_up", "limit_down"]
                ]
                frames.append(merged)
            if cache_path is not None and not merged.empty:
                temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
                merged.to_parquet(temporary, index=False)
                temporary.replace(cache_path)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    if {"symbol", "date"}.issubset(result.columns):
        result["symbol"] = result["symbol"].map(clean_symbol)
        result["date"] = result["date"].astype(str).str.replace("-", "", regex=False)
        result = result.drop_duplicates(["symbol", "date"], keep="last")
    return result.reset_index(drop=True)


def fetch_fund_post(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    frames = []
    for chunk_start, chunk_end in _date_chunks(start_date, end_date, 1):
        frame = fetch(
            "get_fund_daily_post",
            symbol=[symbol],
            start_date=chunk_start,
            end_date=chunk_end,
            fields=["symbol", "date", "open", "close"],
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    if {"symbol", "date"}.issubset(result.columns):
        result["symbol"] = result["symbol"].map(clean_symbol)
        result["date"] = result["date"].astype(str).str.replace("-", "", regex=False)
        result = result.drop_duplicates(["symbol", "date"], keep="last")
    return result.sort_values(["symbol", "date"]).reset_index(drop=True)


def fetch_adjusted_return_factors(
    symbols: list[str], start_date: str, end_date: str, batch_size: int = 50
) -> dict[str, float]:
    frames: list[pd.DataFrame] = []
    for offset in range(0, len(symbols), batch_size):
        frame = fetch(
            "get_stock_daily_post",
            symbol=symbols[offset : offset + batch_size],
            start_date=start_date,
            end_date=end_date,
            fields=["symbol", "date", "close"],
            st=True,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return {}
    work = pd.concat(frames, ignore_index=True, sort=False)
    work["symbol"] = work["symbol"].map(clean_symbol)
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])
    factors: dict[str, float] = {}
    for symbol, group in work.groupby("symbol"):
        first, last = float(group.iloc[0]["close"]), float(group.iloc[-1]["close"])
        if first > 0 and last > 0:
            factors[str(symbol)] = last / first
    return factors


def asset_return_factor(frame: pd.DataFrame) -> float:
    if frame.empty or "close" not in frame:
        return 1.0
    values = pd.to_numeric(frame.sort_values("date")["close"], errors="coerce").dropna()
    if values.empty or values.iloc[0] <= 0 or values.iloc[-1] <= 0:
        return 1.0
    return float(values.iloc[-1] / values.iloc[0])


def fetch_index_prices(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    frames = []
    for chunk_start, chunk_end in _date_chunks(start_date, end_date, 5):
        frame = fetch(
            "get_index_daily",
            symbol=[symbol],
            start_date=chunk_start,
            end_date=chunk_end,
            fields=["symbol", "date", "open", "close"],
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    if {"symbol", "date"}.issubset(result.columns):
        result["symbol"] = result["symbol"].map(clean_symbol)
        result["date"] = result["date"].astype(str).str.replace("-", "", regex=False)
        result = result.drop_duplicates(["symbol", "date"], keep="last")
    return result.sort_values(["symbol", "date"]).reset_index(drop=True)


def fetch_audit_status(symbol: str, latest_year: int, as_of: str | None = None) -> str:
    history = fetch_audit_history(symbol, latest_year, as_of)
    return history[-1]["status"] if history else "missing"


def _normalise_audit_opinion(values: list[str]) -> str:
    lowered = [value.lower() for value in values]
    if any("adverse" in value or "否定" in value for value in lowered):
        return "adverse"
    if any("disclaimer" in value or "无法表示" in value for value in lowered):
        return "disclaimer"
    if any(("qualified" in value and "unqualified" not in value) or "保留" in value for value in lowered):
        return "qualified"
    if any("unqualified" in value or "无保留" in value for value in lowered):
        return "unqualified"
    return "missing"


def fetch_audit_history(
    symbol: str, latest_year: int, as_of: str | None = None, years: int = 3
) -> list[dict[str, Any]]:
    return fetch_audit_histories(
        {symbol: latest_year}, as_of=as_of, years=years, batch_size=1
    ).get(symbol, [])


def fetch_audit_histories(
    latest_year_by_symbol: dict[str, int],
    *,
    as_of: str | None = None,
    years: int = 3,
    batch_size: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    histories = {symbol: [] for symbol in latest_year_by_symbol}
    symbols = sorted(latest_year_by_symbol)
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        start_year = min(latest_year_by_symbol[symbol] for symbol in batch) - years + 1
        end_year = max(latest_year_by_symbol[symbol] for symbol in batch)
        frame = fetch(
            "get_audit_opinion",
            symbol=batch,
            start_quarter=f"{start_year}q4",
            end_quarter=f"{end_year}q4",
            market="cn",
            fields=["symbol", "quarter", "date", "audit_type", "opinion"],
        )
        if as_of is not None and not frame.empty and "date" in frame:
            frame = frame[frame["date"].astype(str) <= as_of]
        if frame.empty or not {"symbol", "opinion", "quarter"}.issubset(frame.columns):
            continue
        work = frame.copy()
        work["symbol"] = work["symbol"].map(clean_symbol)
        work["year"] = pd.to_numeric(
            work["quarter"].astype(str).str.extract(r"(\d{4})", expand=False), errors="coerce"
        )
        for (symbol, year), group in work.dropna(subset=["symbol", "year"]).groupby(["symbol", "year"]):
            if symbol not in histories:
                continue
            histories[symbol].append(
                {
                    "year": int(year),
                    "status": _normalise_audit_opinion(group["opinion"].dropna().astype(str).tolist()),
                    "published_at": str(group["date"].astype(str).max()) if "date" in group else None,
                }
            )
    for symbol in histories:
        histories[symbol].sort(key=lambda row: row["year"])
    return histories
