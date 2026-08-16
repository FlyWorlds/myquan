from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def normalize_dates(values: pd.Series | pd.Index) -> pd.DatetimeIndex:
    series = pd.Series(values, copy=False)
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce")
    else:
        raw = series.astype("string").str.strip()
        compact = raw.str.fullmatch(r"\d{8}").fillna(False)
        parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
        if compact.any():
            parsed.loc[compact] = pd.to_datetime(raw.loc[compact], format="%Y%m%d", errors="coerce")
        if (~compact).any():
            parsed.loc[~compact] = pd.to_datetime(raw.loc[~compact], errors="coerce")
    if pd.isna(parsed).any():
        raise ValueError("Date values contain invalid or unparseable entries")
    return pd.DatetimeIndex(parsed)


def normalize_tickers(values: pd.Series | pd.Index, source: str = "ticker") -> pd.Series:
    raw = pd.Series(values, copy=False).astype("string").str.strip()
    numeric = pd.to_numeric(raw, errors="coerce")
    invalid = numeric.isna() | ~np.isfinite(numeric) | (numeric < 0) | (numeric % 1 != 0)
    if invalid.any():
        examples = raw.loc[invalid].dropna().unique().tolist()[:5]
        raise ValueError(f"{source} contains non-negative non-integer values: {examples}")
    return numeric.astype("int64")


def load_trade_price_matrix(market_root: str | Path) -> pd.DataFrame:
    path = Path(market_root) / "trade_price.parquet"
    frame = pd.read_parquet(path)
    for date_column in ("date", "tradeDate", "datetime"):
        if date_column in frame.columns:
            frame = frame.set_index(date_column)
            break
    frame.index = normalize_dates(frame.index)
    frame.index.name = "date"
    if frame.index.duplicated().any():
        raise ValueError("trade_price.parquet contains duplicate dates")
    tickers = normalize_tickers(pd.Index(frame.columns), "trade_price columns")
    if tickers.duplicated().any():
        raise ValueError("trade_price.parquet contains duplicate ticker columns after normalization")
    frame.columns = tickers.to_numpy()
    return frame.sort_index().apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def build_forward_target(
    trade_price: pd.DataFrame,
    execution_lag: int = 1,
    horizon: int = 1,
) -> pd.DataFrame:
    if execution_lag != 1 or horizon != 1:
        raise ValueError("Version 1 supports execution_lag=1 and horizon=1 only")
    execution = trade_price.shift(-execution_lag)
    exit_price = trade_price.shift(-(execution_lag + horizon))
    target = exit_price.div(execution).sub(1.0).replace([np.inf, -np.inf], np.nan)
    target.index.name = "date"
    return target


def target_to_long(target: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    selected = target.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    stacked = selected.rename_axis(columns="ticker").stack(future_stack=True).rename("target")
    output = stacked.dropna().reset_index()
    output["ticker"] = normalize_tickers(output["ticker"], "target ticker").to_numpy()
    output["date"] = pd.to_datetime(output["date"])
    return output.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)
