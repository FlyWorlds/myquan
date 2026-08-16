"""Pure indicator helpers for the oversold-rebound skill."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


NUMERIC_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
)


def to_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted copy with common market columns coerced to numeric."""
    df = frame.copy()
    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
        sort_columns = [column for column in ("symbol", "date") if column in df.columns]
        df = df.sort_values(sort_columns)
    return df.reset_index(drop=True)


def wilder_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's exponentially smoothed averages."""
    values = pd.to_numeric(close, errors="coerce")
    delta = values.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    alpha = 1 / window
    avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Add price, momentum, volatility, and reversal indicators."""
    df = to_numeric_frame(frame)
    if df.empty:
        return df

    close = df["close"]
    pre_close = df.get("pre_close", close.shift(1)).replace(0, np.nan)
    df["pct"] = (close / pre_close - 1) * 100

    for window in (5, 10, 20, 60):
        df[f"ma{window}"] = close.rolling(window).mean()
        df[f"ret_{window}d"] = (close / close.shift(window) - 1) * 100
        df[f"drawdown_{window}d"] = (close / close.rolling(window).max() - 1) * 100

    df["rsi6"] = wilder_rsi(close, 6)
    df["rsi14"] = wilder_rsi(close, 14)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = (df["dif"] - df["dea"]) * 2

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std(ddof=0)
    df["bb_mid"] = bb_mid
    df["bb_up"] = bb_mid + 2 * bb_std
    df["bb_lo"] = bb_mid - 2 * bb_std
    df["bb_pct"] = (close - df["bb_lo"]) / (df["bb_up"] - df["bb_lo"]).replace(0, np.nan) * 100

    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - pre_close).abs(),
            (df["low"] - pre_close).abs(),
        ],
        axis=1,
    )
    df["true_range"] = ranges.max(axis=1)
    df["atr14"] = df["true_range"].ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["atr14_pct"] = df["atr14"] / close.replace(0, np.nan) * 100

    volume = df.get("volume", pd.Series(index=df.index, dtype=float))
    amount = df.get("amount", pd.Series(index=df.index, dtype=float))
    df["volume_ma5"] = volume.rolling(5).mean()
    df["volume_ma20"] = volume.rolling(20).mean()
    df["volume_ratio_20"] = volume / df["volume_ma20"].replace(0, np.nan)
    df["amount_ma20"] = amount.rolling(20).mean()

    day_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["lower_shadow_ratio"] = (np.minimum(df["open"], close) - df["low"]) / day_range
    df["close_location"] = (close - df["low"]) / day_range
    df["body_ratio"] = (close - df["open"]).abs() / day_range

    rolling_low_3 = df["low"].shift(1).rolling(3).min()
    df["low_holds"] = df["low"] >= rolling_low_3
    df["ma5_reclaim"] = (close >= df["ma5"]) & (close.shift(1) < df["ma5"].shift(1))
    df["rsi_turn_up"] = (df["rsi6"] > df["rsi6"].shift(1)) & (df["rsi6"].shift(1) <= df["rsi6"].shift(2))
    df["macd_contracting"] = (
        (df["macd"] < 0)
        & (df["macd"] > df["macd"].shift(1))
        & (df["macd"].shift(1) <= df["macd"].shift(2))
    )
    df["decline_narrowing"] = (
        (df["pct"] < 0)
        & (df["pct"] > df["pct"].shift(1))
        & (df["pct"].shift(1) < 0)
    )
    return df


def latest_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    """Summarize the latest row and recent path for one symbol."""
    if frame.empty:
        return {}
    df = add_indicators(frame)
    row = df.iloc[-1]

    def number(name: str, digits: int = 2) -> float | None:
        value = row.get(name)
        if value is None or pd.isna(value) or not math.isfinite(float(value)):
            return None
        return round(float(value), digits)

    recent_pct = pd.to_numeric(df["pct"].tail(5), errors="coerce").dropna()
    consecutive_down = 0
    for value in reversed(recent_pct.tolist()):
        if value < 0:
            consecutive_down += 1
        else:
            break

    down_rows = df.tail(10).loc[df.tail(10)["pct"] < 0]
    down_volume_trend = None
    if len(down_rows) >= 3 and down_rows["volume"].notna().sum() >= 3:
        first = down_rows["volume"].iloc[: max(1, len(down_rows) // 2)].mean()
        second = down_rows["volume"].iloc[max(1, len(down_rows) // 2) :].mean()
        if first and not pd.isna(first) and not pd.isna(second):
            down_volume_trend = round(float(second / first), 3)

    last_three = df.tail(3)
    valid_trade = bool(
        number("close") is not None
        and ((number("volume") or 0) > 0 or (number("amount") or 0) > 0)
    )
    return {
        "date": str(row.get("date", "")),
        "close": number("close"),
        "pct": number("pct"),
        "ret_5d": number("ret_5d"),
        "ret_10d": number("ret_10d"),
        "ret_20d": number("ret_20d"),
        "drawdown_20d": number("drawdown_20d"),
        "drawdown_60d": number("drawdown_60d"),
        "rsi6": number("rsi6", 1),
        "rsi14": number("rsi14", 1),
        "bb_pct": number("bb_pct", 1),
        "macd": number("macd", 4),
        "atr14_pct": number("atr14_pct", 2),
        "volume_ratio_20": number("volume_ratio_20", 2),
        "amount_ma20": number("amount_ma20", 0),
        "lower_shadow_ratio": number("lower_shadow_ratio", 3),
        "close_location": number("close_location", 3),
        "ma5": number("ma5"),
        "ma20": number("ma20"),
        "consecutive_down_days": consecutive_down,
        "down_volume_trend": down_volume_trend,
        "low_holds": bool(row.get("low_holds", False)),
        "ma5_reclaim": bool(row.get("ma5_reclaim", False)),
        "rsi_turn_up": bool(row.get("rsi_turn_up", False)),
        "macd_contracting": bool(row.get("macd_contracting", False)),
        "decline_narrowing": bool(row.get("decline_narrowing", False)),
        "last_3_pcts": [round(float(value), 2) for value in pd.to_numeric(last_three["pct"], errors="coerce").dropna()],
        "history_rows": int(len(df)),
        "valid_trade": valid_trade,
    }


def cross_section_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    """Build market breadth statistics from stock daily rows."""
    if frame.empty or "date" not in frame.columns:
        return {}
    df = to_numeric_frame(frame)
    df["pct"] = (df["close"] / df["pre_close"].replace(0, np.nan) - 1) * 100
    valid = df.dropna(subset=["pct"])
    if valid.empty:
        return {}
    latest_date = valid["date"].max()
    latest = valid[valid["date"] == latest_date].copy()
    advances = int((latest["pct"] > 0).sum())
    declines = int((latest["pct"] < 0).sum())
    flats = int((latest["pct"] == 0).sum())
    total = len(latest)
    amount = latest.get("amount", pd.Series(index=latest.index, dtype=float)).fillna(0)
    total_amount = float(amount.sum())
    advancing_amount = float(amount[latest["pct"] > 0].sum())

    consecutive_down_ratio = None
    if "symbol" in valid.columns:
        recent_dates = sorted(valid["date"].unique())[-3:]
        recent = valid[valid["date"].isin(recent_dates)]
        complete = recent.groupby("symbol").filter(lambda group: group["date"].nunique() == len(recent_dates))
        if not complete.empty:
            down_by_symbol = complete.groupby("symbol")["pct"].apply(lambda values: bool((values < 0).all()))
            consecutive_down_ratio = round(float(down_by_symbol.mean() * 100), 1)

    daily_amount = valid.groupby("date")["amount"].sum(min_count=1) if "amount" in valid.columns else pd.Series(dtype=float)
    amount_ratio_20 = None
    amount_trend_5 = None
    if len(daily_amount.dropna()) >= 20:
        amount_ratio_20 = float(daily_amount.iloc[-1] / daily_amount.tail(20).mean())
    if len(daily_amount.dropna()) >= 10:
        previous = daily_amount.iloc[-10:-5].mean()
        if previous:
            amount_trend_5 = float(daily_amount.iloc[-5:].mean() / previous)

    return {
        "date": latest_date,
        "sample_size": total,
        "advances": advances,
        "declines": declines,
        "flats": flats,
        "advance_ratio_pct": round(advances / total * 100, 1) if total else None,
        "advance_decline_ratio": round(advances / max(declines, 1), 3),
        "median_pct": round(float(latest["pct"].median()), 2),
        "dispersion_pct": round(float(latest["pct"].std(ddof=0)), 2),
        "up_5_count": int((latest["pct"] >= 5).sum()),
        "down_5_count": int((latest["pct"] <= -5).sum()),
        "near_limit_up_count": int((latest["pct"] >= 9.5).sum()),
        "near_limit_down_count": int((latest["pct"] <= -9.5).sum()),
        "consecutive_down_3d_pct": consecutive_down_ratio,
        "total_amount_billion": round(total_amount / 1e8, 2),
        "advancing_amount_pct": round(advancing_amount / total_amount * 100, 1) if total_amount > 0 else None,
        "amount_ratio_20": round(amount_ratio_20, 3) if amount_ratio_20 is not None else None,
        "amount_trend_5": round(amount_trend_5, 3) if amount_trend_5 is not None else None,
        "note": "近涨停/近跌停采用统一 ±9.5% 阈值，不是交易所精确涨跌停统计。",
    }
