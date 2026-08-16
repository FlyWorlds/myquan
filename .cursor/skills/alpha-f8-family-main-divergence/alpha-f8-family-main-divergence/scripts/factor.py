from __future__ import annotations

import math
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd


FACTOR_ID = "F8"
FACTOR_NAME = "家人主力分歧"
FAMILY_BROKERS = ["东方财富", "徽商期货", "平安期货"]
MAJOR_BROKERS = ["永安期货", "中信期货", "国泰君安"]
BUY_QUANTILE = 0.1
SELL_QUANTILE = 0.1
DATA_VERSION = "real-v1"
REQUIRED_COLUMNS = {"date", "underlying_symbol", "broker", "net_margin"}


_RATE_LIMIT_CODE = "500010"
_TOKEN_EXPIRED_CODE = "200004"


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


def load_real_position(
    underlying_symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    import panda_data

    username = _get_env("PANDA_DATA_USERNAME")
    password = _get_env("PANDA_DATA_PASSWORD")
    symbols = underlying_symbols if underlying_symbols is not None else _parse_underlying(os.getenv("PANDA_DATA_UNDERLYING"))
    start = _date_to_yyyymmdd(start_date or os.getenv("PANDA_DATA_START_DATE", "2024-01-01"))
    end = _date_to_yyyymmdd(end_date or os.getenv("PANDA_DATA_END_DATE", "2026-05-28"))

    panda_data.init_token(username=username, password=password)
    raw = _call_with_retry(
        panda_data.get_broker_netmarg,
        start_date=start,
        end_date=end,
        broker="",
        underlying_symbol=symbols,
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


def calculate_raw_weights(position_data: Any) -> pd.DataFrame:
    df = validate_input(position_data)
    base = (
        df.groupby(["date", "underlying_symbol"], as_index=False)
        .agg(total_abs_margin=("net_margin", lambda s: s.abs().sum()))
    )
    family_rows = df[df["broker"].isin(FAMILY_BROKERS)].copy()
    family = (
        df.assign(family_margin=df["net_margin"].where(df["broker"].isin(FAMILY_BROKERS), 0.0))
        .groupby(["date", "underlying_symbol"], as_index=False)
        .agg(family_net=("family_margin", "sum"))
    )
    family_hedge = (
        family_rows.assign(
            family_bull=family_rows["net_margin"].clip(lower=0),
            family_bear=(-family_rows["net_margin"]).clip(lower=0),
        )
        .groupby(["date", "underlying_symbol"], as_index=False)
        .agg(
            family_bull=("family_bull", "sum"),
            family_bear=("family_bear", "sum"),
        )
    )
    major_rows = df[df["broker"].isin(MAJOR_BROKERS)].copy()
    major = (
        major_rows.assign(
            major_bull=major_rows["net_margin"].clip(lower=0),
            major_bear=(-major_rows["net_margin"]).clip(lower=0),
        )
        .groupby(["date", "underlying_symbol"], as_index=False)
        .agg(
            major_net=("net_margin", "sum"),
            major_bull=("major_bull", "sum"),
            major_bear=("major_bear", "sum"),
        )
    )
    grouped = base.merge(family, on=["date", "underlying_symbol"], how="left").merge(
        family_hedge, on=["date", "underlying_symbol"], how="left"
    ).merge(major, on=["date", "underlying_symbol"], how="left")
    grouped["family_net"] = grouped["family_net"].fillna(0.0)
    grouped["family_bull"] = grouped["family_bull"].fillna(0.0)
    grouped["family_bear"] = grouped["family_bear"].fillna(0.0)
    grouped = grouped[grouped["total_abs_margin"] > 0].copy()
    grouped["major_total"] = grouped["major_bull"].fillna(0.0) + grouped["major_bear"].fillna(0.0)
    grouped = grouped[grouped["major_total"] > 0].copy()
    # Effective denominator adds the internal hedging within family brokers
    family_internal_hedge = grouped[["family_bull", "family_bear"]].min(axis=1) * 2
    denom = grouped["total_abs_margin"] + family_internal_hedge
    grouped["family_ratio"] = grouped["family_net"] / denom
    grouped["major_ratio"] = grouped["major_net"] / denom
    grouped["consistency"] = grouped[["major_bull", "major_bear"]].max(axis=1) / grouped["major_total"]
    grouped["consistency_strength"] = (2 * grouped["consistency"] - 1).clip(lower=0.0, upper=1.0)
    grouped["raw_weight"] = (grouped["major_ratio"] - grouped["family_ratio"]) * grouped["consistency_strength"]
    return grouped.sort_values(["date", "underlying_symbol"]).reset_index(drop=True)


def apply_cross_section_rank(raw: pd.DataFrame) -> pd.DataFrame:
    """Per-date cross-section percentile rank mapped to [-1, 1].

    Uses pandas rank(pct=True, method='average') within each date group.
    Ties are averaged. Single-symbol dates receive factor_value = 1.0.
    """
    result = raw.copy()
    result["factor_value"] = (
        result.groupby("date")["raw_weight"]
        .rank(pct=True, method="average")
        .mul(2)
        .sub(1)
    )
    return result.reset_index(drop=True)


def _score_and_signal(day: pd.DataFrame, buy_quantile: float, sell_quantile: float) -> pd.DataFrame:
    ranked = day.sort_values(["factor_value", "symbol"], ascending=[False, True]).copy()
    n = len(ranked)
    ranked["rank"] = range(1, n + 1)
    ranked["score"] = ranked["factor_value"].rank(pct=True, ascending=True, method="first").mul(100).round(2)
    buy_count = max(1, math.ceil(n * buy_quantile))
    sell_count = max(1, math.ceil(n * sell_quantile))
    ranked["signal"] = "hold"
    ranked.loc[ranked["rank"] <= buy_count, "signal"] = "buy"
    ranked.loc[ranked["rank"] > n - sell_count, "signal"] = "sell"
    ranked["confidence"] = (ranked["score"] / 100).round(4)
    return ranked


def calculate_factor(
    input_data: Any,
    update_time: str | None = None,
    buy_quantile: float = BUY_QUANTILE,
    sell_quantile: float = SELL_QUANTILE,
) -> pd.DataFrame:
    update_time = update_time or datetime.now().isoformat(timespec="seconds")
    grouped = apply_cross_section_rank(calculate_raw_weights(input_data))
    grouped["trade_date"] = grouped["date"].map(_date_to_iso)
    grouped["symbol"] = grouped["underlying_symbol"]

    factor = (
        grouped.groupby("trade_date", group_keys=True)
        .apply(lambda g: _score_and_signal(g, buy_quantile, sell_quantile), include_groups=False)
        .reset_index(level=0)
        .reset_index(drop=True)
    )
    factor["asset_type"] = "future"
    factor["factor_id"] = FACTOR_ID
    factor["factor_name"] = FACTOR_NAME
    factor["data_version"] = DATA_VERSION
    factor["update_time"] = update_time

    columns = [
        "trade_date",
        "asset_type",
        "symbol",
        "factor_id",
        "factor_name",
        "factor_value",
        "score",
        "rank",
        "signal",
        "confidence",
        "data_version",
        "update_time",
    ]
    return factor[columns].sort_values(["trade_date", "rank", "symbol"]).reset_index(drop=True)


if __name__ == "__main__":
    import pathlib
    result = calculate_factor(load_real_position(), update_time=datetime.now().isoformat(timespec="seconds"))
    print(result.to_string(index=False))
    out = pathlib.Path(__file__).parent.parent.parent / "alpha-f8-family-main-divergence-production" / "database.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out, index=False)
    print(f"写出 {len(result)} 行 → {out}")
