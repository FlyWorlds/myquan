from __future__ import annotations

import math
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd


_RATE_LIMIT_CODE = "500010"
_TOKEN_EXPIRED_CODE = "200004"

FACTOR_ID = "F5"
FACTOR_NAME = "会员持仓集中度"
TOP_N = 5
CONCENTRATION_THRESHOLD = 0.60
BUY_QUANTILE = 0.1
SELL_QUANTILE = 0.1
DATA_VERSION = "real-v2"
ZSCORE_WINDOW = 60
MIN_ZSCORE_PERIODS = 20
REQUIRED_COLUMNS = {"date", "underlying_symbol", "broker", "net_margin"}


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"请先设置环境变量 {name}")
    return value


def _date_to_yyyymmdd(value: str) -> str:
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"日期必须是 YYYY-MM-DD 或 YYYYMMDD: {value}")
    return text


def _date_to_iso(value: str) -> str:
    return pd.to_datetime(str(value), format="%Y%m%d").strftime("%Y-%m-%d")


def _parse_underlying(value: str | None) -> list[str] | None:
    if not value or value.strip().lower() == "all":
        return None
    symbols = [item.strip().upper() for item in value.split(",") if item.strip()]
    return symbols or None


def _call_with_retry(fn, *args, max_retries: int = 6, base_wait: float = 10.0, **kwargs):
    import panda_data
    from panda_data.exceptions import ServiceError

    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except ServiceError as e:
            err = str(e)
            if _TOKEN_EXPIRED_CODE in err and attempt < max_retries - 1:
                print(f"  [Token过期] 重新登录后重试 (第 {attempt + 1}/{max_retries} 次)...")
                try:
                    panda_data.init_token()
                except Exception as login_err:
                    print(f"  [Token过期] 重新登录失败: {login_err}")
                continue
            elif attempt < max_retries - 1:
                wait = base_wait * (2 ** attempt)
                reason = "限频" if _RATE_LIMIT_CODE in err else "网络瞬时错误"
                print(f"  [{reason}] {err[:80]} → 等待 {wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
                time.sleep(wait)
            else:
                raise
        except (TimeoutError, OSError, ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = base_wait * (2 ** attempt)
                print(f"  [网络超时] {str(e)[:80]} → 等待 {wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
                time.sleep(wait)
            else:
                raise


def load_real_position(
    underlying_symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    import panda_data

    username = _get_env("PANDA_DATA_USERNAME")
    password = _get_env("PANDA_DATA_PASSWORD")
    if underlying_symbols is None:
        underlying_symbols = _parse_underlying(os.getenv("PANDA_DATA_UNDERLYING"))
    start = _date_to_yyyymmdd(start_date or os.getenv("PANDA_DATA_START_DATE", "2024-01-01"))
    end = _date_to_yyyymmdd(end_date or os.getenv("PANDA_DATA_END_DATE", "2026-05-28"))

    panda_data.init_token(username=username, password=password)
    raw = _call_with_retry(
        panda_data.get_broker_netmarg,
        start_date=start,
        end_date=end,
        broker="",
        underlying_symbol=underlying_symbols,
    )
    if raw.empty:
        raise ValueError("Panda data 未返回席位净持仓保证金数据")
    return raw[["date", "underlying_symbol", "broker", "net_margin"]]


def validate_input(input_data: Any) -> pd.DataFrame:
    df = pd.DataFrame(input_data)
    if df.empty:
        raise ValueError("席位净持仓数据不能为空")
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"席位净持仓数据缺少必要字段: {sorted(missing)}")
    cleaned = df.copy()
    cleaned["date"] = cleaned["date"].astype(str).str.replace("-", "", regex=False)
    invalid_dates = ~cleaned["date"].str.fullmatch(r"\d{8}")
    if invalid_dates.any():
        raise ValueError("date 必须是 YYYYMMDD 或 YYYY-MM-DD")
    cleaned["underlying_symbol"] = cleaned["underlying_symbol"].astype(str).str.upper()
    cleaned["broker"] = cleaned["broker"].astype(str)
    try:
        cleaned["net_margin"] = pd.to_numeric(cleaned["net_margin"], errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError(f"net_margin 必须为数值: {e}") from e
    if cleaned["underlying_symbol"].str.len().eq(0).any():
        raise ValueError("underlying_symbol 不能为空")
    if cleaned["broker"].str.len().eq(0).any():
        raise ValueError("broker 不能为空")
    return cleaned.sort_values(["date", "underlying_symbol", "broker"]).reset_index(drop=True)


def _top_n_sum(series: pd.Series, n: int) -> float:
    return float(series.nlargest(n).sum())


def calculate_raw_weights(position_data: Any) -> pd.DataFrame:
    df = validate_input(position_data)

    total_margin = (
        df.groupby(["date", "underlying_symbol"], as_index=False)
        .agg(total_margin=("net_margin", lambda s: s.abs().sum()))
    )
    total_margin = total_margin[total_margin["total_margin"] > 0].copy()
    if total_margin.empty:
        raise ValueError("所有品种席位保证金总量均为 0，无法计算因子")

    bull = (
        df[df["net_margin"] > 0]
        .groupby(["date", "underlying_symbol"], as_index=False)
        .agg(bull_top5=("net_margin", lambda s: _top_n_sum(s, TOP_N)))
    )
    bear = (
        df[df["net_margin"] < 0]
        .groupby(["date", "underlying_symbol"], as_index=False)
        .agg(bear_top5=("net_margin", lambda s: _top_n_sum(s.abs(), TOP_N)))
    )

    result = total_margin.merge(bull, on=["date", "underlying_symbol"], how="left")
    result = result.merge(bear, on=["date", "underlying_symbol"], how="left")
    result["bull_top5"] = result["bull_top5"].fillna(0.0)
    result["bear_top5"] = result["bear_top5"].fillna(0.0)
    result["bull_ratio"] = result["bull_top5"] / result["total_margin"]
    result["bear_ratio"] = result["bear_top5"] / result["total_margin"]
    result["raw_weight"] = result["bear_ratio"] - result["bull_ratio"]

    return result.sort_values(["date", "underlying_symbol"]).reset_index(drop=True)


def calculate_delta_weights(raw: pd.DataFrame) -> pd.DataFrame:
    """对 calculate_raw_weights 输出的 raw_weight 做逐品种一阶差分。

    第一个可用日无前日数据，整行丢弃。
    输出包含原有列（date, underlying_symbol, raw_weight 等）+ delta_raw 列。
    """
    df = raw.sort_values(["underlying_symbol", "date"]).copy()
    df["prev_raw"] = df.groupby("underlying_symbol")["raw_weight"].shift(1)
    df["delta_raw"] = df["raw_weight"] - df["prev_raw"]
    df = df.dropna(subset=["prev_raw"]).drop(columns=["prev_raw"]).reset_index(drop=True)
    return df


def apply_time_series_zscore(
    raw: pd.DataFrame,
    window: int = ZSCORE_WINDOW,
    min_periods: int = MIN_ZSCORE_PERIODS,
) -> pd.DataFrame:
    if window <= 1:
        raise ValueError("zscore_window 必须大于 1")
    min_periods = max(2, min(min_periods, window))
    result = raw.sort_values(["underlying_symbol", "date"]).copy()
    rolling = result.groupby("underlying_symbol")["raw_weight"].rolling(window=window, min_periods=min_periods)
    mean = rolling.mean().reset_index(level=0, drop=True)
    std = rolling.std().reset_index(level=0, drop=True)
    zscore = (result["raw_weight"] - mean) / std
    zscore = zscore.replace([float("inf"), float("-inf")], pd.NA)
    result["factor_value"] = (
        ((result["raw_weight"] - mean) / std)
        .replace([float("inf"), float("-inf")], pd.NA)
        .where(std > 0, 0.0)
    )
    return result.dropna(subset=["factor_value"]).reset_index(drop=True)


def _score_and_signal(
    day: pd.DataFrame,
    buy_quantile: float = BUY_QUANTILE,
    sell_quantile: float = SELL_QUANTILE,
    concentration_threshold: float = CONCENTRATION_THRESHOLD,
) -> pd.DataFrame:
    ranked = day.sort_values(["factor_value", "symbol"], ascending=[False, True]).copy()
    n = len(ranked)
    ranked["rank"] = range(1, n + 1)
    ranked["score"] = ranked["factor_value"].rank(pct=True, ascending=True, method="first").mul(100).round(2)

    buy_cutoff = math.ceil(n * (1 - buy_quantile))
    sell_cutoff = math.ceil(n * sell_quantile)
    ranked["signal"] = "hold"

    bull_ok = ranked["bull_ratio"] > concentration_threshold
    bear_ok = ranked["bear_ratio"] > concentration_threshold

    ranked.loc[(ranked["rank"] <= buy_cutoff) & (ranked["factor_value"] > 0) & bull_ok, "signal"] = "buy"
    ranked.loc[(ranked["rank"] > n - sell_cutoff) & (ranked["factor_value"] < 0) & bear_ok, "signal"] = "sell"
    ranked["confidence"] = (ranked["score"] / 100).round(4)
    return ranked


def calculate_factor(
    input_data: Any,
    update_time: str | None = None,
    buy_quantile: float = BUY_QUANTILE,
    sell_quantile: float = SELL_QUANTILE,
    concentration_threshold: float = CONCENTRATION_THRESHOLD,
    zscore_window: int = ZSCORE_WINDOW,
    min_zscore_periods: int = MIN_ZSCORE_PERIODS,
) -> pd.DataFrame:
    update_time = update_time or datetime.now().isoformat(timespec="seconds")

    # Level 路径：翻转后的水平值 Z-score
    grouped = calculate_raw_weights(input_data)
    level = apply_time_series_zscore(
        grouped[["date", "underlying_symbol", "raw_weight", "bull_ratio", "bear_ratio"]],
        window=zscore_window,
        min_periods=min_zscore_periods,
    ).rename(columns={"factor_value": "zscore_level"})

    # Delta 路径：level_raw 一阶差分的 Z-score
    delta_raw_df = calculate_delta_weights(
        grouped[["date", "underlying_symbol", "raw_weight"]]
    )
    delta_input = delta_raw_df[["date", "underlying_symbol", "delta_raw"]].rename(
        columns={"delta_raw": "raw_weight"}
    )
    delta = apply_time_series_zscore(
        delta_input,
        window=zscore_window,
        min_periods=min_zscore_periods,
    ).rename(columns={"factor_value": "zscore_delta"})
    # apply_time_series_zscore 对首个 delta 点（std 为 NaN）会强制输出 0.0 而非 NaN，
    # 需手动过滤掉每个品种累计点数不足 min_zscore_periods 的行
    delta_sorted = delta.sort_values(["underlying_symbol", "date"])
    delta_sorted["_cum"] = delta_sorted.groupby("underlying_symbol").cumcount() + 1
    delta = delta_sorted[delta_sorted["_cum"] >= min_zscore_periods].drop(columns=["_cum"])

    # 合并：两路都有值才保留，等权混合
    merged = level.merge(
        delta[["date", "underlying_symbol", "zscore_delta"]],
        on=["date", "underlying_symbol"],
        how="inner",
    )
    merged["factor_value"] = 0.5 * merged["zscore_level"] + 0.5 * merged["zscore_delta"]

    merged["trade_date"] = merged["date"].map(_date_to_iso)
    merged["symbol"] = merged["underlying_symbol"]

    factor = (
        merged.groupby("trade_date", group_keys=True)
        .apply(
            lambda g: _score_and_signal(g, buy_quantile, sell_quantile, concentration_threshold),
            include_groups=False,
        )
        .reset_index(level=0)
        .reset_index(drop=True)
    )
    factor["asset_type"] = "future"
    factor["factor_id"] = FACTOR_ID
    factor["factor_name"] = FACTOR_NAME
    factor["data_version"] = DATA_VERSION
    factor["update_time"] = update_time

    columns = [
        "trade_date", "asset_type", "symbol", "factor_id", "factor_name",
        "factor_value", "score", "rank", "signal", "confidence",
        "data_version", "update_time",
    ]
    return factor[columns].sort_values(["trade_date", "rank", "symbol"]).reset_index(drop=True)


if __name__ == "__main__":
    import pathlib
    result = calculate_factor(load_real_position(), update_time=datetime.now().isoformat(timespec="seconds"))
    print(result.to_string(index=False))
    out = pathlib.Path(__file__).parent.parent.parent / "alpha-f5-member-position-concentration-production" / "database.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out, index=False)
    print(f"写出 {len(result)} 行 → {out}")
