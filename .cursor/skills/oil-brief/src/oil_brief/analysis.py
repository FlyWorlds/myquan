"""Technical analysis module — computes indicators, support/resistance, and trend analysis."""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_ma(df: pd.DataFrame, periods: list[int] = [5, 10, 20, 60]) -> pd.DataFrame:
    """Compute moving averages for given periods."""
    result = df.copy()
    for p in periods:
        result[f"ma{p}"] = result["close"].rolling(window=p).mean()
    return result


def compute_bollinger(df: pd.DataFrame, period: int = 20, std: int = 2) -> pd.DataFrame:
    """Compute Bollinger Bands."""
    result = df.copy()
    result["boll_mid"] = result["close"].rolling(window=period).mean()
    rolling_std = result["close"].rolling(window=period).std()
    result["boll_upper"] = result["boll_mid"] + std * rolling_std
    result["boll_lower"] = result["boll_mid"] - std * rolling_std
    return result


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Compute Relative Strength Index."""
    result = df.copy()
    delta = result["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result["rsi"] = 100 - (100 / (1 + rs))
    return result


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Compute MACD indicator."""
    result = df.copy()
    ema_fast = result["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = result["close"].ewm(span=slow, adjust=False).mean()
    result["macd"] = ema_fast - ema_slow
    result["macd_signal"] = result["macd"].ewm(span=signal, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]
    return result


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Compute Average True Range for volatility."""
    result = df.copy()
    high_low = result["high"] - result["low"]
    high_close = np.abs(result["high"] - result["close"].shift())
    low_close = np.abs(result["low"] - result["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    result["atr"] = tr.rolling(window=period, min_periods=period).mean()
    return result


def find_support_resistance(
    df: pd.DataFrame,
    lookback: int = 60,
) -> dict[str, list[dict[str, Any]]]:
    """Identify key support and resistance levels near current price.

    Methodology:
    - MA below price = support; above price = resistance
    - Bollinger Bands
    - Recent pivot points within proximity of price
    - Recent session extremes
    - Round psychological levels

    Returns:
        Dict with 'support' and 'resistance' lists, each with
        dicts: level, strength (strong/medium/weak), source.
    """
    recent = df.tail(lookback).copy()
    latest_price = float(recent["close"].iloc[-1])
    supports = []
    resistances = []

    # 1. Moving averages — directional (MA below price = support, above = resistance)
    ma_config = [(5, "medium"), (10, "medium"), (20, "strong"), (60, "strong")]
    for period, strength in ma_config:
        col = f"ma{period}"
        if col not in recent.columns:
            continue
        ma_val = recent[col].iloc[-1]
        if pd.isna(ma_val):
            continue
        level = round(float(ma_val), 2)
        dist = abs(level - latest_price) / latest_price
        if dist > 0.10:
            continue  # too far from current price, skip
        if level <= latest_price:
            supports.append({"level": level, "strength": strength, "source": f"MA{period}"})
        else:
            resistances.append({"level": level, "strength": strength, "source": f"MA{period}"})

    # 2. Bollinger Bands
    for band_key, band_col, direction in [
        ("boll_lower", "boll_lower", "support"),
        ("boll_upper", "boll_upper", "resistance"),
    ]:
        val = recent[band_col].iloc[-1] if band_col in recent.columns else None
        if val is not None and not pd.isna(val) and abs(val - latest_price) / latest_price <= 0.10:
            level = round(float(val), 2)
            if direction == "support" and level < latest_price:
                supports.append({"level": level, "strength": "strong", "source": "布林下轨"})
            elif direction == "resistance" and level > latest_price:
                resistances.append({"level": level, "strength": "strong", "source": "布林上轨"})

    # Bollinger mid line
    if "boll_mid" in recent.columns:
        mid = recent["boll_mid"].iloc[-1]
        if not pd.isna(mid) and abs(mid - latest_price) / latest_price <= 0.10:
            level = round(float(mid), 2)
            if level <= latest_price:
                supports.append({"level": level, "strength": "medium", "source": "布林中轨(MA20)"})
            else:
                resistances.append({"level": level, "strength": "medium", "source": "布林中轨(MA20)"})

    # 3. Recent pivot points within 8% of price
    for window in [5, 10]:
        # Local lows
        roll_min = recent["low"].rolling(window=window * 2 + 1, center=True).min()
        pivot_lows = recent[recent["low"] == roll_min]
        for _, row in pivot_lows.iterrows():
            low = float(row["low"])
            if low < latest_price and low >= latest_price * 0.92:
                supports.append({"level": round(low, 2), "strength": "medium", "source": f"{window}日枢轴低点"})
        # Local highs
        roll_max = recent["high"].rolling(window=window * 2 + 1, center=True).max()
        pivot_highs = recent[recent["high"] == roll_max]
        for _, row in pivot_highs.iterrows():
            high = float(row["high"])
            if high > latest_price and high <= latest_price * 1.08:
                resistances.append({"level": round(high, 2), "strength": "medium", "source": f"{window}日枢轴高点"})

    # 4. Recent session extremes
    last_3 = recent.tail(3)
    labels = ["前日", "前2日", "昨日"]
    for i, (_, row) in enumerate(last_3.iterrows()):
        if i >= len(labels):
            break
        low = float(row["low"])
        high = float(row["high"])
        if low < latest_price and low >= latest_price * 0.92:
            supports.append({"level": round(low, 2), "strength": "weak", "source": f"{labels[i]}最低"})
        if high > latest_price and high <= latest_price * 1.08:
            resistances.append({"level": round(high, 2), "strength": "weak", "source": f"{labels[i]}最高"})

    # 5. Round psychological levels near price
    magnitude = 10 ** max(0, len(str(int(latest_price))) - 2)
    base = round(latest_price / magnitude) * magnitude
    for offset in range(-3, 4):
        level = base + offset * magnitude
        if abs(level - latest_price) / latest_price > 0.08:
            continue
        strength = "strong" if level == base else "weak"
        if level < latest_price:
            supports.append({"level": level, "strength": strength, "source": "整数关口"})
        elif level > latest_price:
            resistances.append({"level": level, "strength": strength, "source": "整数关口"})

    # Deduplicate (merge within tolerance) and sort
    supports = _dedupe_and_sort(supports, descending=True)
    resistances = _dedupe_and_sort(resistances, descending=False)

    return {
        "support": supports[:5],
        "resistance": resistances[:5],
    }


def _dedupe_and_sort(
    levels: list[dict[str, Any]],
    descending: bool = False,
    tolerance: float = 1.0,
) -> list[dict[str, Any]]:
    """Deduplicate levels within tolerance and sort.

    Sort priority: strength first (strong > medium > weak), then level proximity.
    For supports (descending=False by caller): strong supports closest to price come first.
    For resistances (descending=False): strong resistances closest to price come first.
    """
    if not levels:
        return []

    strength_rank = {"strong": 0, "medium": 1, "weak": 2}

    sorted_levels = sorted(
        levels,
        key=lambda x: (strength_rank.get(x.get("strength", "weak"), 2),
                        -x["level"] if descending else x["level"]),
    )
    deduped = []
    for level in sorted_levels:
        if not deduped or abs(level["level"] - deduped[-1]["level"]) > tolerance:
            deduped.append(level)
    return deduped


def analyze_trend(df: pd.DataFrame) -> dict[str, Any]:
    """Analyze current trend direction and strength.

    Returns:
        Dict with: trend, strength, slope_pct, duration_days, above_ma20, rsi.
    """
    if df.empty or len(df) < 20:
        return {"trend": "neutral", "strength": "unknown", "duration_days": 0}

    latest = df.iloc[-1]
    close_series = df["close"]

    # Short-term momentum (5-day)
    ma5 = close_series.rolling(5).mean()

    # Medium-term (20-day MA)
    ma20 = close_series.rolling(20).mean()

    # RSI
    rsi_latest = latest.get("rsi", 50)
    if rsi_latest is None or pd.isna(rsi_latest):
        rsi_latest = 50

    # Price slope over 10 days (percent change)
    if len(df) >= 10:
        slope = (close_series.iloc[-1] - close_series.iloc[-10]) / close_series.iloc[-10] * 100
    else:
        slope = 0

    # Price relative to MA20
    above_ma20 = not pd.isna(ma20.iloc[-1]) and close_series.iloc[-1] > ma20.iloc[-1]

    # Determine trend
    if slope > 3 and above_ma20:
        trend = "up"
        strength = "strong" if slope > 6 else "moderate"
    elif slope < -3 and not above_ma20:
        trend = "down"
        strength = "strong" if slope < -6 else "moderate"
    elif abs(slope) <= 3:
        trend = "neutral"
        strength = "weak"
    else:
        # Slope is moderate but against MA position — mixed signals
        trend = "neutral"
        strength = "weak"

    # Count consecutive up/down days
    price_changes = close_series.diff()
    direction = (price_changes > 0).astype(int)
    if len(direction) > 1:
        current_dir = direction.iloc[-1]
        duration = 0
        for i in range(len(direction) - 1, -1, -1):
            if direction.iloc[i] == current_dir:
                duration += 1
            else:
                break
    else:
        duration = 1

    return {
        "trend": trend,
        "strength": strength,
        "slope_pct": round(slope, 2),
        "duration_days": duration,
        "above_ma20": bool(above_ma20),
        "rsi": round(float(rsi_latest), 1),
    }


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators on the DataFrame."""
    if df.empty:
        return df
    result = compute_ma(df)
    result = compute_bollinger(result)
    result = compute_rsi(result)
    result = compute_macd(result)
    result = compute_atr(result)
    return result


def get_latest_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Get the latest values of all indicators as a flat dict."""
    if df.empty:
        return {}

    latest = df.iloc[-1]
    indicators = {
        "close": float(latest.get("close", 0)),
        "open": float(latest.get("open", 0)),
        "high": float(latest.get("high", 0)),
        "low": float(latest.get("low", 0)),
        "volume": float(latest.get("volume", 0)),
        "oi": float(latest.get("oi", 0)),
    }

    if len(df) > 1:
        prev_close = float(df.iloc[-2]["close"])
        indicators["change"] = indicators["close"] - prev_close
        indicators["change_pct"] = (indicators["close"] / prev_close - 1) * 100
    else:
        indicators["change"] = 0
        indicators["change_pct"] = 0

    for field in ["ma5", "ma10", "ma20", "ma60",
                  "boll_upper", "boll_mid", "boll_lower",
                  "rsi", "macd", "macd_signal", "macd_hist", "atr"]:
        val = latest.get(field)
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            indicators[field] = round(float(val), 2)

    return indicators
