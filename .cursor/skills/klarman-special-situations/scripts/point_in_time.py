"""公告、解禁、阶段与可交易性的点时控制。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd


def _token(value: object) -> str | None:
    match = pd.Series([value], dtype="string").str.extract(r"((?:19|20)\d{6})", expand=False).iloc[0]
    return None if pd.isna(match) else str(match)


def filter_publications(frame: pd.DataFrame, as_of: str, columns: Iterable[str] = ("publication_date", "date", "info_date", "announcement_date", "stage_date")) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    tokens = pd.Series(pd.NA, index=frame.index, dtype="string")
    found_column = False
    for column in columns:
        if column not in frame:
            continue
        found_column = True
        tokens = tokens.fillna(frame[column].map(_token).astype("string"))
    if not found_column:
        return frame.iloc[0:0].copy()
    return frame.loc[tokens.notna() & (tokens <= as_of)].copy()


def visible_unlocks(frame: pd.DataFrame, as_of: str, window_days: int) -> pd.DataFrame:
    visible = filter_publications(frame, as_of)
    if visible.empty:
        return visible
    relieve_column = next((name for name in ("relieve_date", "unlock_date", "listing_date") if name in visible), None)
    if relieve_column is None:
        return visible.iloc[0:0].copy()
    relieve = visible[relieve_column].map(_token)
    end = (datetime.strptime(as_of, "%Y%m%d") + timedelta(days=window_days)).strftime("%Y%m%d")
    return visible.loc[relieve.notna() & (relieve > as_of) & (relieve <= end)].copy()


def next_tradable_open(prices: pd.DataFrame, signal_date: str, max_wait_days: int = 10) -> dict[str, object] | None:
    if prices.empty or not {"date", "open"}.issubset(prices.columns):
        return None
    frame = prices.copy(); frame["_date"] = frame["date"].map(_token)
    frame = frame.loc[frame["_date"].notna() & (frame["_date"] > signal_date)].sort_values("_date").head(max_wait_days)
    if "trade_status" in frame:
        frame = frame.loc[pd.to_numeric(frame["trade_status"], errors="coerce").fillna(1) == 0]
    frame = frame.loc[pd.to_numeric(frame["open"], errors="coerce") > 0]
    if frame.empty:
        return None
    row = frame.iloc[0]
    return {"date": str(row["_date"]), "open": float(row["open"])}
