from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

FACTOR_ID = "A06"
FACTOR_NAME = "游资席位冷却反转与协同突破"
DEFAULT_DATA_VERSION = "pandadata-lhb-hotmoney-executable-open-a06-v1"
FACTOR_MODE_FINAL = "hotmoney_executable_open"
VALID_FACTOR_MODES = {FACTOR_MODE_FINAL}
LHB_DETAIL_CHUNK_DAYS = int(os.getenv("ALPHA_LHB_DETAIL_CHUNK_DAYS", "31"))
MARKET_DATA_CHUNK_DAYS = int(os.getenv("ALPHA_MARKET_DATA_CHUNK_DAYS", "90"))
MARKET_DATA_SYMBOL_BATCH_SIZE = int(os.getenv("ALPHA_MARKET_DATA_SYMBOL_BATCH_SIZE", "300"))
DYNAMIC_QUALITY_WINDOW = int(os.getenv("ALPHA_AGENCY_QUALITY_WINDOW", "120"))
DYNAMIC_QUALITY_MIN_HISTORY = int(os.getenv("ALPHA_AGENCY_QUALITY_MIN_HISTORY", "3"))
SPIKE_REVERSAL_THRESHOLD = float(os.getenv("ALPHA_SPIKE_REVERSAL_THRESHOLD", "0.06"))
REQUIRED_DETAIL_COLUMNS = {"symbol", "date", "rank", "agency", "b_value"}
DEFAULT_EXCLUDE_AGENCY_KEYWORDS = [
    "机构专用",
    "沪股通专用",
    "深股通专用",
    "港股通专用",
    "瑞银证券",
    "摩根大通证券",
    "高盛",
    "中国国际金融股份有限公司",
]
LHB_DETAIL_FIELDS = [
    "symbol",
    "date",
    "type",
    "side",
    "rank",
    "agency",
    "b_value",
    "s_value",
    "reason",
]
MARKET_DATA_FIELDS = [
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "pre_close",
    "limit_up",
    "limit_down",
    "trade_status",
]
STANDARD_COLUMNS = [
    "trade_date",
    "asset_type",
    "ts_code",
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
DIAGNOSTIC_COLUMNS = [
    "same_day_top_agency_count",
    "consecutive_3_agency_count",
    "recent_repeat_agency_count",
    "max_recent_buy_days",
    "disclosure_repeat_agency_count",
    "max_consecutive_buy_days",
    "top_buy_value",
    "top_sell_value",
    "net_buy_value",
    "net_buy_to_amount",
    "sell_pressure",
    "avg_net_buy_ratio",
    "collaboration_strength",
    "avg_agency_quality",
    "max_agency_quality",
    "avg_agency_hist_win_rate",
    "avg_agency_hist_return",
    "avg_agency_net_persistence",
    "avg_agency_reversal_risk",
    "is_limit_up_close",
    "limit_up_streak",
    "recent_limit_up_count_5d",
    "recent_3d_return",
    "recent_5d_return",
    "ret_5d",
    "ret_10d",
    "volume_ratio",
    "upper_shadow_ratio",
    "position_state",
    "high_position_risk",
    "amount_zscore",
    "dynamic_quality_enabled",
    "same_day_top_agencies",
    "active_streak_agencies",
]
ALPHA_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCTION_OUTPUT = ALPHA_ROOT / "生产产物" / "数据库.parquet"


def _display_path(path: str | Path) -> str:
    try:
        return os.path.relpath(Path(path).resolve(), Path.cwd().resolve())
    except ValueError:
        return Path(path).name


def _normalise_date(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("日期不能为空")
    if text.endswith(".0"):
        text = text[:-2]
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"无法解析日期: {value}")
    return parsed.strftime("%Y-%m-%d")


def _normalise_date_series(values: pd.Series, field_name: str = "日期") -> pd.Series:
    text = values.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    parsed = pd.to_datetime(text, errors="coerce")
    bad = parsed.isna()
    if bad.any():
        example = values.loc[bad].head(1).iloc[0]
        raise ValueError(f"无法解析{field_name}: {example}")
    return parsed.dt.strftime("%Y-%m-%d")


def _compact_date(value: str) -> str:
    return _normalise_date(value).replace("-", "")


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return parts or None


def _chunk_list(values: list[str], size: int) -> list[list[str]]:
    chunk_size = max(1, int(size))
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def _exclude_keywords_from_env() -> list[str]:
    configured = _split_csv(os.getenv("ALPHA_EXCLUDE_AGENCY_KEYWORDS"))
    return configured if configured is not None else DEFAULT_EXCLUDE_AGENCY_KEYWORDS


def _date_defaults() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=45)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _shift_date(value: str, days: int) -> str:
    parsed = pd.to_datetime(_normalise_date(value)).date()
    return (parsed + timedelta(days=days)).strftime("%Y%m%d")


def _init_panda_data(panda_data: Any) -> None:
    username = os.getenv("PANDA_DATA_USERNAME")
    password = os.getenv("PANDA_DATA_PASSWORD")
    if username and password:
        panda_data.init_token(username=username, password=password)
        return
    if username or password:
        raise RuntimeError("PANDA_DATA_USERNAME 和 PANDA_DATA_PASSWORD 必须同时设置")


def _should_chunk_service_error(exc: Exception) -> bool:
    text = str(exc)
    return "600003" in text or "超过套餐限额" in text or "查询结果为空" in text


def _fetch_lhb_detail_once(
    panda_data: Any,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    lhb_type: str | list[str] | None,
) -> pd.DataFrame:
    return panda_data.get_lhb_detail(
        symbol=symbols,
        type=lhb_type,
        start_date=_compact_date(start_date),
        end_date=_compact_date(end_date),
        side="buy",
        fields=LHB_DETAIL_FIELDS,
    )


def _fetch_lhb_detail_chunked(
    panda_data: Any,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    lhb_type: str | list[str] | None,
    chunk_days: int = LHB_DETAIL_CHUNK_DAYS,
) -> pd.DataFrame:
    frames = []
    cursor = pd.to_datetime(_normalise_date(start_date)).date()
    end = pd.to_datetime(_normalise_date(end_date)).date()
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max(1, chunk_days) - 1), end)
        try:
            frame = _fetch_lhb_detail_once(
                panda_data,
                start_date=cursor.strftime("%Y%m%d"),
                end_date=chunk_end.strftime("%Y%m%d"),
                symbols=symbols,
                lhb_type=lhb_type,
            )
        except Exception as exc:
            if max(1, chunk_days) > 1 and _should_chunk_service_error(exc):
                frame = _fetch_lhb_detail_chunked(
                    panda_data,
                    start_date=cursor.strftime("%Y%m%d"),
                    end_date=chunk_end.strftime("%Y%m%d"),
                    symbols=symbols,
                    lhb_type=lhb_type,
                    chunk_days=7,
                )
            else:
                raise
        if not frame.empty:
            frames.append(frame)
        cursor = chunk_end + timedelta(days=1)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _fetch_market_data_once(
    panda_data: Any,
    start_date: str,
    end_date: str,
    symbols: list[str],
) -> pd.DataFrame:
    return panda_data.get_market_data(
        symbol=symbols,
        start_date=_compact_date(start_date),
        end_date=_compact_date(end_date),
        type="stock",
        fields=MARKET_DATA_FIELDS,
    )


def _fetch_market_data_chunked(
    panda_data: Any,
    start_date: str,
    end_date: str,
    symbols: list[str],
    chunk_days: int = MARKET_DATA_CHUNK_DAYS,
) -> pd.DataFrame:
    frames = []
    cursor = pd.to_datetime(_normalise_date(start_date)).date()
    end = pd.to_datetime(_normalise_date(end_date)).date()
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max(1, chunk_days) - 1), end)
        try:
            frame = _fetch_market_data_once(
                panda_data,
                start_date=cursor.strftime("%Y%m%d"),
                end_date=chunk_end.strftime("%Y%m%d"),
                symbols=symbols,
            )
        except Exception as exc:
            if max(1, chunk_days) > 7 and _should_chunk_service_error(exc):
                frame = _fetch_market_data_chunked(
                    panda_data,
                    start_date=cursor.strftime("%Y%m%d"),
                    end_date=chunk_end.strftime("%Y%m%d"),
                    symbols=symbols,
                    chunk_days=7,
                )
            else:
                raise
        if not frame.empty:
            frames.append(frame)
        cursor = chunk_end + timedelta(days=1)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_real_lhb_details(
    start_date: str,
    end_date: str,
    symbols: list[str] | None = None,
    lhb_type: str | list[str] | None = None,
) -> pd.DataFrame:
    try:
        import panda_data
    except ModuleNotFoundError as exc:
        raise RuntimeError("当前环境无法导入 panda_data，请检查 panda_data 及其依赖是否安装完整") from exc

    _init_panda_data(panda_data)
    try:
        raw = _fetch_lhb_detail_once(panda_data, start_date, end_date, symbols, lhb_type)
    except Exception as exc:
        if not _should_chunk_service_error(exc):
            raise
        print("龙虎榜明细整段拉取超限，改用分段拉取", flush=True)
        raw = _fetch_lhb_detail_chunked(panda_data, start_date, end_date, symbols, lhb_type)
    if raw.empty:
        raise ValueError("get_lhb_detail 未返回买方龙虎榜明细数据")
    return raw


def load_real_trade_calendar(start_date: str, end_date: str, exchange: str = "SH") -> pd.DataFrame:
    try:
        import panda_data
    except ModuleNotFoundError as exc:
        raise RuntimeError("当前环境无法导入 panda_data，请检查 panda_data 及其依赖是否安装完整") from exc

    _init_panda_data(panda_data)
    return panda_data.get_trade_cal(
        start_date=_compact_date(start_date),
        end_date=_compact_date(end_date),
        exchange=exchange,
        is_trading_day=1,
    )


def load_real_quotes(start_date: str, end_date: str, symbols: list[str]) -> pd.DataFrame:
    try:
        import panda_data
    except ModuleNotFoundError as exc:
        raise RuntimeError("当前环境无法导入 panda_data，请检查 panda_data 及其依赖是否安装完整") from exc

    _init_panda_data(panda_data)
    clean_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
    if not clean_symbols:
        raise ValueError("load_real_quotes 需要至少一个股票代码")
    if len(clean_symbols) > MARKET_DATA_SYMBOL_BATCH_SIZE:
        frames = []
        batches = _chunk_list(clean_symbols, MARKET_DATA_SYMBOL_BATCH_SIZE)
        for batch_index, batch in enumerate(batches, start=1):
            print(f"行情按股票分批拉取 {batch_index}/{len(batches)} size={len(batch)}", flush=True)
            frames.append(load_real_quotes(start_date=start_date, end_date=end_date, symbols=batch))
        quotes = pd.concat(frames, ignore_index=True)
        return (
            quotes.drop_duplicates(["trade_date", "ts_code"], keep="last")
            .sort_values(["ts_code", "trade_date"])
            .reset_index(drop=True)
        )

    try:
        raw = _fetch_market_data_once(panda_data, start_date, end_date, clean_symbols)
    except Exception as exc:
        if not _should_chunk_service_error(exc):
            raise
        print("行情整段拉取超限，改用分段拉取", flush=True)
        raw = _fetch_market_data_chunked(panda_data, start_date, end_date, clean_symbols)
    if raw.empty:
        raise ValueError("get_market_data 未返回行情数据")
    quotes = raw.rename(columns={"symbol": "ts_code", "date": "trade_date"}).copy()
    available_cols = ["trade_date", "ts_code", *[col for col in MARKET_DATA_FIELDS if col in quotes.columns]]
    quotes = quotes[available_cols].copy()
    quotes["trade_date"] = quotes["trade_date"].map(_normalise_date)
    quotes["ts_code"] = quotes["ts_code"].astype(str)
    if "close" not in quotes.columns:
        raise ValueError("get_market_data 未返回 close 字段")
    numeric_cols = [col for col in MARKET_DATA_FIELDS if col in quotes.columns and col != "trade_status"]
    for col in numeric_cols:
        quotes[col] = pd.to_numeric(quotes[col], errors="coerce")
    if quotes[["trade_date", "ts_code", "close"]].isna().any().any():
        raise ValueError("get_market_data 行情数据存在空日期、空代码或非法 close")
    return quotes.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _normalise_market_quotes(input_data: Any) -> pd.DataFrame:
    if isinstance(input_data, pd.DataFrame):
        df = input_data.copy(deep=False)
    else:
        df = pd.DataFrame(input_data).copy()
    rename_map = {}
    if "symbol" in df.columns and "ts_code" not in df.columns:
        rename_map["symbol"] = "ts_code"
    if "date" in df.columns and "trade_date" not in df.columns:
        rename_map["date"] = "trade_date"
    if rename_map:
        df = df.rename(columns=rename_map)

    required = {"trade_date", "ts_code", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"行情输入缺少字段: {sorted(missing)}")
    keep_cols = ["trade_date", "ts_code", *[col for col in MARKET_DATA_FIELDS if col in df.columns]]
    if "close" not in keep_cols:
        keep_cols.append("close")
    out = df[keep_cols].copy()
    out["trade_date"] = _normalise_date_series(out["trade_date"], "行情日期")
    out["ts_code"] = out["ts_code"].astype(str)
    numeric_cols = [col for col in MARKET_DATA_FIELDS if col in out.columns and col != "trade_status"]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if out[["trade_date", "ts_code", "close"]].isna().any().any():
        raise ValueError("行情输入存在空值或非法收盘价")
    return out.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _trade_status_is_tradable(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.lower()
    if text.eq("").all():
        return pd.Series(True, index=series.index)
    bad_tokens = ["停牌", "暂停", "suspend", "halt", "退市"]
    bad = text.isin({"false", "no", "n"})
    for token in bad_tokens:
        bad = bad | text.str.contains(token, regex=False, na=False)
    return ~bad


def _consecutive_true_streak(values: pd.Series) -> pd.Series:
    flags = values.fillna(False).astype(bool)
    groups = flags.ne(flags.shift(fill_value=False)).cumsum()
    streak = flags.groupby(groups).cumcount().add(1)
    return streak.where(flags, 0).astype(int)


def _position_state(ret_10d: pd.Series) -> pd.Series:
    state = pd.Series("mid_position", index=ret_10d.index, dtype="object")
    state.loc[ret_10d <= 0.20] = "low_position"
    state.loc[ret_10d >= 0.50] = "high_position"
    return state


def build_board_quote_features(quotes: Any) -> pd.DataFrame:
    df = _normalise_market_quotes(quotes)
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    grouped = df.groupby("ts_code", sort=False)

    if "pre_close" not in df.columns:
        df["pre_close"] = grouped["close"].shift(1)
    if "limit_up" not in df.columns:
        df["limit_up"] = pd.NA
    if "high" not in df.columns:
        df["high"] = df["close"]
    for col in ["open", "low", "volume", "limit_down"]:
        if col not in df.columns:
            df[col] = pd.NA
    if "amount" not in df.columns:
        df["amount"] = pd.NA
    if "trade_status" not in df.columns:
        df["trade_status"] = ""
    for col in ["open", "close", "high", "low", "volume", "amount", "pre_close", "limit_up", "limit_down"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    grouped = df.groupby("ts_code", sort=False)

    fallback_limit = df["pre_close"].where(df["pre_close"].notna(), grouped["close"].shift(1)) * 1.10
    df["effective_limit_up"] = pd.to_numeric(df["limit_up"], errors="coerce").where(
        pd.to_numeric(df["limit_up"], errors="coerce").gt(0),
        fallback_limit,
    )
    df["is_tradable"] = _trade_status_is_tradable(df["trade_status"])
    df["is_limit_up_close"] = (
        df["is_tradable"]
        & df["close"].notna()
        & df["effective_limit_up"].notna()
        & df["close"].ge(df["effective_limit_up"].mul(0.999))
    )
    df["limit_up_streak"] = grouped["is_limit_up_close"].transform(_consecutive_true_streak).astype(int)
    df["recent_limit_up_count_5d"] = (
        grouped["is_limit_up_close"]
        .transform(lambda s: s.astype(float).rolling(5, min_periods=1).sum())
        .fillna(0)
        .astype(int)
    )
    df["recent_3d_return"] = (df["close"] / grouped["close"].shift(3) - 1).fillna(0.0)
    df["recent_5d_return"] = (df["close"] / grouped["close"].shift(5) - 1).fillna(0.0)
    df["ret_5d"] = df["recent_5d_return"]
    df["ret_10d"] = (df["close"] / grouped["close"].shift(10) - 1).fillna(0.0)

    amount = pd.to_numeric(df["amount"], errors="coerce")
    rolling_mean = grouped["amount"].transform(lambda s: pd.to_numeric(s, errors="coerce").shift(1).rolling(20, min_periods=5).mean())
    rolling_std = grouped["amount"].transform(lambda s: pd.to_numeric(s, errors="coerce").shift(1).rolling(20, min_periods=5).std())
    df["amount_zscore"] = ((amount - rolling_mean) / rolling_std.replace(0, float("nan"))).fillna(0.0).clip(-5, 5)
    volume = pd.to_numeric(df["volume"], errors="coerce")
    volume_mean = grouped["volume"].transform(lambda s: pd.to_numeric(s, errors="coerce").shift(1).rolling(20, min_periods=5).mean())
    amount_ratio = amount / rolling_mean.replace(0, float("nan"))
    volume_ratio = volume / volume_mean.replace(0, float("nan"))
    df["volume_ratio"] = volume_ratio.where(volume_ratio.notna(), amount_ratio).fillna(1.0).clip(0, 20)
    price_range = (df["high"] - df["low"]).replace(0, float("nan"))
    upper_shadow = df["high"] - pd.concat([df["open"], df["close"]], axis=1).max(axis=1)
    df["upper_shadow_ratio"] = (upper_shadow / price_range).fillna(0.0).clip(0, 1)
    df["position_state"] = _position_state(df["ret_10d"])
    df["high_position_risk"] = (
        df["ret_10d"].ge(0.50)
        | df["ret_5d"].ge(0.30)
        | (df["upper_shadow_ratio"].ge(0.35) & df["amount_zscore"].ge(2.0))
        | df["limit_up_streak"].ge(3)
    )

    # Do not deep-copy the full market panel here. Full refreshes can contain
    # several million quote rows; the merge below only needs a column view.
    return df[
        [
            "trade_date",
            "ts_code",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "pre_close",
            "limit_up",
            "limit_down",
            "trade_status",
            "effective_limit_up",
            "is_tradable",
            "is_limit_up_close",
            "limit_up_streak",
            "recent_limit_up_count_5d",
            "recent_3d_return",
            "recent_5d_return",
            "ret_5d",
            "ret_10d",
            "volume_ratio",
            "upper_shadow_ratio",
            "position_state",
            "high_position_risk",
            "amount_zscore",
        ]
    ]


def build_agency_quality_labels(quotes: Any) -> pd.DataFrame:
    df = build_board_quote_features(quotes).copy()
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    grouped = df.groupby("ts_code", sort=False)
    df["next_high"] = grouped["high"].shift(-1)
    df["next_close"] = grouped["close"].shift(-1)
    df["next_limit_up"] = grouped["effective_limit_up"].shift(-1)
    df["next2_close"] = grouped["close"].shift(-2)
    has_next_limit = (
        df["next_limit_up"].notna()
        & df["next_limit_up"].gt(0)
        & df["next_close"].notna()
        & df["next_high"].notna()
    )
    df["next_day_touch_limit_up"] = pd.NA
    df["next_day_close_limit_up"] = pd.NA
    df.loc[has_next_limit, "next_day_touch_limit_up"] = (
        df.loc[has_next_limit, "next_high"].ge(df.loc[has_next_limit, "next_limit_up"].mul(0.999)).astype(float)
    )
    df.loc[has_next_limit, "next_day_close_limit_up"] = (
        df.loc[has_next_limit, "next_close"].ge(df.loc[has_next_limit, "next_limit_up"].mul(0.999)).astype(float)
    )
    df["entry_return_t1_to_t2"] = df["next2_close"] / df["next_close"] - 1
    return df[
        [
            "trade_date",
            "ts_code",
            "next_day_touch_limit_up",
            "next_day_close_limit_up",
            "entry_return_t1_to_t2",
        ]
    ].dropna(subset=["next_day_close_limit_up"]).reset_index(drop=True)


def validate_lhb_detail(input_data: Any) -> pd.DataFrame:
    df = pd.DataFrame(input_data).copy()
    if df.empty:
        raise ValueError("龙虎榜明细数据不能为空")

    rename_map = {}
    if "ts_code" in df.columns and "symbol" not in df.columns:
        rename_map["ts_code"] = "symbol"
    if "trade_date" in df.columns and "date" not in df.columns:
        rename_map["trade_date"] = "date"
    if rename_map:
        df = df.rename(columns=rename_map)

    missing = REQUIRED_DETAIL_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"龙虎榜明细缺少必要字段: {sorted(missing)}")

    df = df.copy()
    df["trade_date"] = df["date"].map(_normalise_date)
    df["ts_code"] = df["symbol"].astype(str).str.strip()
    df["agency"] = df["agency"].astype(str).str.strip()
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["b_value"] = pd.to_numeric(df["b_value"], errors="coerce")
    if "s_value" in df.columns:
        df["s_value"] = pd.to_numeric(df["s_value"], errors="coerce").fillna(0.0)
    else:
        df["s_value"] = 0.0

    bad_numeric = df[["rank", "b_value"]].isna().any(axis=1)
    if bad_numeric.any():
        raise ValueError(f"rank 或 b_value 存在无法解析的数值，异常行数: {int(bad_numeric.sum())}")

    if "side" in df.columns:
        side = df["side"].astype(str).str.lower().str.strip()
        df = df.loc[side.eq("buy")].copy()

    df = df.loc[(df["ts_code"] != "") & (df["agency"] != "") & (df["b_value"] > 0)].copy()
    if df.empty:
        raise ValueError("清洗后没有有效买方席位记录")

    df["rank"] = df["rank"].astype(int)
    df["gross_value"] = df["b_value"] + df["s_value"].clip(lower=0)
    df["net_buy_value"] = df["b_value"] - df["s_value"].clip(lower=0)
    df["net_buy_ratio"] = df["net_buy_value"] / df["gross_value"].where(df["gross_value"] > 0, df["b_value"])
    df["net_buy_ratio"] = df["net_buy_ratio"].clip(lower=-1, upper=1).fillna(1.0)
    return df.sort_values(["ts_code", "trade_date", "rank", "agency"]).reset_index(drop=True)


def _extract_trade_dates(calendar: Any, detail_dates: pd.Series) -> list[str]:
    detail_set = {_normalise_date(value) for value in detail_dates.dropna().unique()}
    if calendar is None:
        return sorted(detail_set)

    cal_df = pd.DataFrame(calendar).copy()
    if cal_df.empty:
        return sorted(detail_set)

    date_col = next(
        (col for col in ["trade_date", "date", "nature_date", "cal_date"] if col in cal_df.columns),
        None,
    )
    if date_col is None:
        return sorted(detail_set)

    if "is_trading_day" in cal_df.columns:
        flag = cal_df["is_trading_day"].astype(str).str.lower().isin({"1", "true", "yes"})
        cal_df = cal_df.loc[flag].copy()
    dates = {_normalise_date(value) for value in cal_df[date_col].dropna().unique()}
    return sorted(dates | detail_set)


def extract_calendar_trade_dates(calendar: Any) -> set[str]:
    """Return valid trading dates from a PandaData trade-calendar frame."""
    cal_df = pd.DataFrame(calendar).copy()
    if cal_df.empty:
        raise ValueError("交易日历为空")
    date_col = next(
        (col for col in ["trade_date", "date", "nature_date", "cal_date"] if col in cal_df.columns),
        None,
    )
    if date_col is None:
        raise ValueError("交易日历缺少日期字段")
    if "is_trading_day" in cal_df.columns:
        flag = cal_df["is_trading_day"].astype(str).str.lower().isin({"1", "true", "yes"})
        cal_df = cal_df.loc[flag].copy()
    return {_normalise_date(value) for value in cal_df[date_col].dropna().unique()}


def _eligible_buy_seats(
    detail: pd.DataFrame,
    top_n: int,
    top_agencies: list[str] | None,
    filter_hot_money: bool,
    min_buy_value: float,
    min_net_buy_ratio: float,
    exclude_agency_keywords: list[str] | None,
) -> pd.DataFrame:
    if top_n <= 0:
        raise ValueError("top_n 必须大于 0")
    eligible = detail.loc[detail["rank"].between(1, top_n)].copy()
    if top_agencies:
        whitelist = {agency.strip() for agency in top_agencies if agency.strip()}
        eligible = eligible.loc[eligible["agency"].isin(whitelist)].copy()
    if filter_hot_money:
        keywords = exclude_agency_keywords or []
        for keyword in keywords:
            eligible = eligible.loc[~eligible["agency"].str.contains(keyword, regex=False, na=False)].copy()
        eligible = eligible.loc[eligible["net_buy_ratio"] >= min_net_buy_ratio].copy()
        eligible = eligible.loc[eligible["net_buy_value"] > 0].copy()
        eligible = eligible.loc[eligible["b_value"] >= min_buy_value].copy()
    if eligible.empty:
        raise ValueError("没有符合 rank/top_agencies 条件的买方席位记录")
    eligible["rank_weight"] = ((top_n + 1 - eligible["rank"]) / top_n).clip(lower=0.2, upper=1.0)
    eligible["agency_quality"] = eligible["agency"].map(_agency_quality)
    eligible["seat_strength"] = (
        eligible["b_value"].map(lambda value: math.log1p(max(float(value), 0.0) / 10_000_000.0))
        * eligible["rank_weight"]
        * eligible["net_buy_ratio"].clip(lower=0)
        * eligible["agency_quality"]
    )
    return eligible


def _join_unique(values: pd.Series) -> str:
    return "|".join(sorted({str(value) for value in values.dropna() if str(value)}))


def _agency_quality(agency: str) -> float:
    text = str(agency)
    if "营业部" in text:
        return 1.0
    if "分公司" in text:
        return 0.75
    return 0.60


def _neutral_dynamic_quality(seat_days: pd.DataFrame) -> pd.DataFrame:
    out = seat_days.copy()
    out["agency_base_quality"] = out["agency_quality"].astype(float)
    out["agency_hist_win_rate"] = 0.50
    out["agency_hist_return"] = 0.0
    out["agency_net_persistence"] = 0.55
    out["agency_reversal_risk"] = 0.0
    out["dynamic_quality_enabled"] = 0
    return out


def _quote_event_features(quotes: Any, spike_reversal_threshold: float) -> pd.DataFrame:
    quote_df = _normalise_market_quotes(quotes)
    if quote_df.empty:
        return pd.DataFrame(
            columns=[
                "trade_date",
                "ts_code",
                "event_forward_return",
                "event_return_known_date",
                "event_board_success",
                "same_day_return",
                "spike_reversal_flag",
            ]
        )

    quote_df = quote_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    by_symbol = quote_df.groupby("ts_code", sort=False)["close"]
    quote_df["prev_close"] = by_symbol.shift(1)
    quote_df["next_close"] = by_symbol.shift(-1)
    quote_df["next2_close"] = by_symbol.shift(-2)
    quote_df["event_return_known_date"] = quote_df.groupby("ts_code", sort=False)["trade_date"].shift(-2)
    quote_df["same_day_return"] = quote_df["close"] / quote_df["prev_close"] - 1
    quote_df["event_forward_return"] = quote_df["next2_close"] / quote_df["next_close"] - 1
    labels = build_agency_quality_labels(quote_df)
    quote_df = quote_df.merge(
        labels[["trade_date", "ts_code", "next_day_close_limit_up"]],
        on=["trade_date", "ts_code"],
        how="left",
    )
    quote_df["event_board_success"] = quote_df["next_day_close_limit_up"]
    valid_reversal = quote_df["same_day_return"].notna() & quote_df["event_forward_return"].notna()
    quote_df["spike_reversal_flag"] = pd.NA
    quote_df.loc[valid_reversal, "spike_reversal_flag"] = (
        (quote_df.loc[valid_reversal, "same_day_return"] >= spike_reversal_threshold)
        & (quote_df.loc[valid_reversal, "event_forward_return"] <= 0)
    ).astype(float)
    return quote_df[
        [
            "trade_date",
            "ts_code",
            "event_forward_return",
            "event_return_known_date",
            "event_board_success",
            "same_day_return",
            "spike_reversal_flag",
        ]
    ].copy()


def _shifted_rolling_mean(series: pd.Series, window: int, min_history: int) -> pd.Series:
    return series.shift(1).rolling(window=window, min_periods=min_history).mean()


def _rolling_known_history(
    events: pd.DataFrame,
    current_rows: pd.DataFrame,
    quality_window: int,
    min_history: int,
) -> pd.DataFrame:
    known = events.dropna(subset=["event_return_known_date"]).copy()
    if known.empty:
        return pd.DataFrame(columns=["agency", "trade_date"])

    known["known_date"] = pd.to_datetime(known["event_return_known_date"], errors="coerce")
    known = known.dropna(subset=["known_date"]).copy()
    if known.empty:
        return pd.DataFrame(columns=["agency", "trade_date"])

    known["win_flag"] = known["event_forward_return"].gt(0).astype(float)
    known["net_persistence_raw"] = known["net_buy_ratio"].clip(lower=0, upper=1)
    agency_known = (
        known.groupby(["agency", "known_date"], as_index=False)
        .agg(
            day_win_rate=("win_flag", "mean"),
            day_avg_return=("event_forward_return", "mean"),
            day_net_persistence=("net_persistence_raw", "mean"),
            day_reversal_risk=("spike_reversal_flag", "mean"),
        )
        .sort_values(["agency", "known_date"])
        .reset_index(drop=True)
    )
    if agency_known.empty:
        return pd.DataFrame(columns=["agency", "trade_date"])

    window = max(1, int(quality_window))
    min_periods = max(1, int(min_history))
    grouped = agency_known.groupby("agency", sort=False)
    for source, target in [
        ("day_win_rate", "agency_hist_win_rate"),
        ("day_avg_return", "agency_hist_return"),
        ("day_net_persistence", "agency_net_persistence"),
        ("day_reversal_risk", "agency_reversal_risk"),
    ]:
        agency_known[target] = grouped[source].transform(
            lambda series: series.rolling(window=window, min_periods=min_periods).mean()
        )

    history_cols = [
        "agency",
        "known_date",
        "agency_hist_win_rate",
        "agency_hist_return",
        "agency_net_persistence",
        "agency_reversal_risk",
    ]
    history = agency_known[history_cols].dropna(
        subset=[
            "agency_hist_win_rate",
            "agency_hist_return",
            "agency_net_persistence",
            "agency_reversal_risk",
        ],
        how="all",
    )
    if history.empty:
        return pd.DataFrame(columns=["agency", "trade_date"])

    current = current_rows[["agency", "trade_date"]].drop_duplicates().copy()
    current["trade_dt"] = pd.to_datetime(current["trade_date"], errors="coerce")
    current = current.dropna(subset=["trade_dt"]).sort_values(["agency", "trade_dt"]).reset_index(drop=True)
    history = history.sort_values(["agency", "known_date"]).reset_index(drop=True)
    merged_parts = []
    for agency, left in current.groupby("agency", sort=False):
        right = history.loc[history["agency"].eq(agency)].copy()
        if right.empty:
            continue
        merged = pd.merge_asof(
            left.sort_values("trade_dt"),
            right.sort_values("known_date"),
            left_on="trade_dt",
            right_on="known_date",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["agency"] = agency
        merged_parts.append(merged)
    if not merged_parts:
        return pd.DataFrame(columns=["agency", "trade_date"])
    merged_history = pd.concat(merged_parts, ignore_index=True)
    return merged_history[
        [
            "agency",
            "trade_date",
            "agency_hist_win_rate",
            "agency_hist_return",
            "agency_net_persistence",
            "agency_reversal_risk",
        ]
    ].drop_duplicates(["agency", "trade_date"], keep="last")


def _apply_dynamic_agency_quality(
    seat_days: pd.DataFrame,
    quotes: Any | None,
    quality_window: int = DYNAMIC_QUALITY_WINDOW,
    min_history: int = DYNAMIC_QUALITY_MIN_HISTORY,
    spike_reversal_threshold: float = SPIKE_REVERSAL_THRESHOLD,
) -> pd.DataFrame:
    out = _neutral_dynamic_quality(seat_days)
    if quotes is None:
        return out

    features = _quote_event_features(quotes, spike_reversal_threshold=spike_reversal_threshold)
    if features.empty:
        return out

    events = out.merge(features, on=["trade_date", "ts_code"], how="left")
    history = _rolling_known_history(events, out, quality_window=quality_window, min_history=min_history)
    if history.empty:
        return out

    out = out.drop(
        columns=[
            "agency_hist_win_rate",
            "agency_hist_return",
            "agency_net_persistence",
            "agency_reversal_risk",
        ]
    ).merge(history, on=["agency", "trade_date"], how="left")

    out["agency_hist_win_rate"] = out["agency_hist_win_rate"].fillna(0.50).clip(lower=0, upper=1)
    out["agency_hist_return"] = out["agency_hist_return"].fillna(0.0).clip(lower=-0.08, upper=0.08)
    out["agency_net_persistence"] = out["agency_net_persistence"].fillna(0.55).clip(lower=0, upper=1)
    out["agency_reversal_risk"] = out["agency_reversal_risk"].fillna(0.0).clip(lower=0, upper=1)

    win_edge = out["agency_hist_win_rate"] - 0.50
    return_edge = (out["agency_hist_return"] / 0.03).clip(lower=-1, upper=1)
    persistence_edge = out["agency_net_persistence"] - 0.55
    reversal_penalty = out["agency_reversal_risk"]
    quality_multiplier = (
        1.0
        + win_edge.mul(0.45)
        + return_edge.mul(0.20)
        + persistence_edge.mul(0.25)
        - reversal_penalty.mul(0.35)
    ).clip(lower=0.55, upper=1.35)

    out["agency_quality"] = out["agency_base_quality"].mul(quality_multiplier).clip(lower=0.35, upper=1.35)
    out["seat_strength"] = (
        out["buy_value"].map(lambda value: math.log1p(max(float(value), 0.0) / 10_000_000.0))
        * out["rank_weight"]
        * out["net_buy_ratio"].clip(lower=0)
        * out["agency_quality"]
    )
    out["dynamic_quality_enabled"] = 1
    return out


def _add_repeat_buy_features(seat_days: pd.DataFrame, trade_window: int = 5, disclosure_window: int = 3) -> pd.DataFrame:
    out = seat_days.sort_values(["ts_code", "agency", "trade_index"]).copy()
    out["recent_buy_count_5d"] = 1
    for _, idx in out.groupby(["ts_code", "agency"], sort=False).groups.items():
        positions = out.loc[idx, "trade_index"].to_numpy()
        left = positions.searchsorted(positions - (trade_window - 1), side="left")
        out.loc[idx, "recent_buy_count_5d"] = pd.Series(
            range(1, len(positions) + 1),
            index=idx,
            dtype="int64",
        ).to_numpy() - left

    disclosure = out[["ts_code", "trade_date"]].drop_duplicates().sort_values(["ts_code", "trade_date"]).copy()
    disclosure["stock_disclosure_index"] = disclosure.groupby("ts_code").cumcount()
    out = out.merge(disclosure, on=["ts_code", "trade_date"], how="left")
    out["disclosure_recent_buy_count_3"] = 1
    for _, idx in out.groupby(["ts_code", "agency"], sort=False).groups.items():
        positions = out.loc[idx, "stock_disclosure_index"].to_numpy()
        left = positions.searchsorted(positions - (disclosure_window - 1), side="left")
        out.loc[idx, "disclosure_recent_buy_count_3"] = pd.Series(
            range(1, len(positions) + 1),
            index=idx,
            dtype="int64",
        ).to_numpy() - left

    out["recent_repeat_flag"] = out["recent_buy_count_5d"].ge(2).astype(int)
    out["disclosure_repeat_flag"] = out["disclosure_recent_buy_count_3"].ge(2).astype(int)
    return out


def _daily_zscore(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce").replace([float("inf"), float("-inf")], pd.NA)

    def transform(day: pd.Series) -> pd.Series:
        clean = pd.to_numeric(day, errors="coerce")
        if clean.notna().sum() < 2:
            return pd.Series(0.0, index=day.index)
        low = clean.quantile(0.01)
        high = clean.quantile(0.99)
        clipped = clean.clip(lower=low, upper=high)
        std = clipped.std(ddof=0)
        if not std or pd.isna(std):
            return pd.Series(0.0, index=day.index)
        return ((clipped - clipped.mean()) / std).fillna(0.0)

    temp = pd.DataFrame({"trade_date": frame["trade_date"], column: values})
    return temp.groupby("trade_date")[column].transform(transform).astype(float)


def calculate_factor(
    lhb_detail: Any,
    trade_calendar: Any | None = None,
    top_n: int = 5,
    streak_window: int = 3,
    top_agencies: list[str] | None = None,
    filter_hot_money: bool = True,
    min_buy_value: float = 5_000_000,
    min_net_buy_ratio: float = 0.55,
    exclude_agency_keywords: list[str] | None = None,
    quotes: Any | None = None,
    dynamic_seat_quality: bool = False,
    factor_mode: str = FACTOR_MODE_FINAL,
    data_version: str = DEFAULT_DATA_VERSION,
    update_time: str | None = None,
) -> pd.DataFrame:
    if streak_window < 2:
        raise ValueError("streak_window 必须至少为 2")
    factor_mode = str(factor_mode).strip().lower()
    if factor_mode not in VALID_FACTOR_MODES:
        raise ValueError(f"factor_mode 必须是 {sorted(VALID_FACTOR_MODES)} 之一")

    detail = validate_lhb_detail(lhb_detail)
    eligible = _eligible_buy_seats(
        detail,
        top_n=top_n,
        top_agencies=top_agencies,
        filter_hot_money=filter_hot_money,
        min_buy_value=min_buy_value,
        min_net_buy_ratio=min_net_buy_ratio,
        exclude_agency_keywords=exclude_agency_keywords if exclude_agency_keywords is not None else _exclude_keywords_from_env(),
    )
    trade_dates = _extract_trade_dates(trade_calendar, eligible["trade_date"])
    trade_index = {trade_date: idx for idx, trade_date in enumerate(trade_dates)}

    seat_days = (
        eligible.groupby(["ts_code", "trade_date", "agency"], as_index=False)
        .agg(
            buy_value=("b_value", "sum"),
            sell_value=("s_value", "sum"),
            net_buy_value=("net_buy_value", "sum"),
            best_rank=("rank", "min"),
            rank_weight=("rank_weight", "max"),
            agency_quality=("agency_quality", "max"),
            seat_strength=("seat_strength", "sum"),
            row_count=("rank", "size"),
        )
        .copy()
    )
    seat_days["gross_value"] = seat_days["buy_value"] + seat_days["sell_value"].clip(lower=0)
    seat_days["net_buy_ratio"] = seat_days["net_buy_value"] / seat_days["gross_value"].where(
        seat_days["gross_value"] > 0,
        seat_days["buy_value"],
    )
    seat_days["net_buy_ratio"] = seat_days["net_buy_ratio"].clip(lower=-1, upper=1).fillna(1.0)
    seat_days["trade_index"] = seat_days["trade_date"].map(trade_index)
    if seat_days["trade_index"].isna().any():
        raise ValueError("交易日历无法覆盖龙虎榜日期")
    seat_days["trade_index"] = seat_days["trade_index"].astype(int)
    seat_days = seat_days.sort_values(["ts_code", "agency", "trade_index"]).reset_index(drop=True)
    seat_days = _apply_dynamic_agency_quality(seat_days, quotes=quotes if dynamic_seat_quality else None)

    seat_days["prev_trade_index"] = seat_days.groupby(["ts_code", "agency"])["trade_index"].shift(1)
    seat_days["new_run"] = (seat_days["trade_index"] - seat_days["prev_trade_index"]).ne(1)
    seat_days["run_id"] = seat_days.groupby(["ts_code", "agency"])["new_run"].cumsum()
    seat_days["streak_len"] = (
        seat_days.groupby(["ts_code", "agency", "run_id"]).cumcount().add(1).astype(int)
    )
    seat_days = _add_repeat_buy_features(seat_days, trade_window=5, disclosure_window=3)

    daily = (
        seat_days.groupby(["ts_code", "trade_date"], as_index=False)
        .agg(
            same_day_top_agency_count=("agency", "nunique"),
            top_buy_value=("buy_value", "sum"),
            top_sell_value=("sell_value", "sum"),
            net_buy_value=("net_buy_value", "sum"),
            avg_net_buy_ratio=("net_buy_ratio", "mean"),
            collaboration_strength=("seat_strength", "sum"),
            avg_agency_quality=("agency_quality", "mean"),
            max_agency_quality=("agency_quality", "max"),
            avg_agency_hist_win_rate=("agency_hist_win_rate", "mean"),
            avg_agency_hist_return=("agency_hist_return", "mean"),
            avg_agency_net_persistence=("agency_net_persistence", "mean"),
            avg_agency_reversal_risk=("agency_reversal_risk", "mean"),
            dynamic_quality_enabled=("dynamic_quality_enabled", "max"),
            max_consecutive_buy_days=("streak_len", "max"),
            recent_repeat_agency_count=("recent_repeat_flag", "sum"),
            max_recent_buy_days=("recent_buy_count_5d", "max"),
            disclosure_repeat_agency_count=("disclosure_repeat_flag", "sum"),
            best_rank=("best_rank", "min"),
            same_day_top_agencies=("agency", _join_unique),
        )
        .copy()
    )

    active = seat_days.loc[seat_days["streak_len"] >= streak_window].copy()
    if active.empty:
        daily["consecutive_3_agency_count"] = 0
        daily["streak_strength"] = 0.0
        daily["active_streak_agencies"] = ""
    else:
        active_daily = (
            active.groupby(["ts_code", "trade_date"], as_index=False)
            .agg(
                consecutive_3_agency_count=("agency", "nunique"),
                streak_strength=("seat_strength", "sum"),
                active_streak_agencies=("agency", _join_unique),
            )
            .copy()
        )
        daily = daily.merge(active_daily, on=["ts_code", "trade_date"], how="left")
        daily["consecutive_3_agency_count"] = daily["consecutive_3_agency_count"].fillna(0).astype(int)
        daily["streak_strength"] = daily["streak_strength"].fillna(0.0)
        daily["active_streak_agencies"] = daily["active_streak_agencies"].fillna("")

    if quotes is not None:
        board_features = build_board_quote_features(quotes)
        feature_cols = [
            "trade_date",
            "ts_code",
            "is_tradable",
            "is_limit_up_close",
            "limit_up_streak",
            "recent_limit_up_count_5d",
            "recent_3d_return",
            "recent_5d_return",
            "ret_5d",
            "ret_10d",
            "volume_ratio",
            "upper_shadow_ratio",
            "position_state",
            "high_position_risk",
            "amount_zscore",
            "amount",
        ]
        daily = daily.merge(board_features[feature_cols], on=["trade_date", "ts_code"], how="left")
    else:
        raise ValueError("最终因子必须传入包含 open/close/limit_up/amount 的行情数据")

    if "is_tradable" not in daily.columns:
        daily["is_tradable"] = True
    if "is_limit_up_close" not in daily.columns:
        daily["is_limit_up_close"] = False
    for col in ["limit_up_streak", "recent_limit_up_count_5d"]:
        if col not in daily.columns:
            daily[col] = 0
    for col in ["recent_3d_return", "recent_5d_return", "ret_5d", "ret_10d", "volume_ratio", "upper_shadow_ratio", "amount_zscore", "amount"]:
        if col not in daily.columns:
            daily[col] = 0.0
    if "position_state" not in daily.columns:
        daily["position_state"] = "mid_position"
    if "high_position_risk" not in daily.columns:
        daily["high_position_risk"] = False
    daily["is_tradable"] = daily["is_tradable"].fillna(False).astype(bool)
    daily["is_limit_up_close"] = daily["is_limit_up_close"].fillna(False).astype(bool)
    daily["limit_up_streak"] = pd.to_numeric(daily["limit_up_streak"], errors="coerce").fillna(0).astype(int)
    daily["recent_limit_up_count_5d"] = (
        pd.to_numeric(daily["recent_limit_up_count_5d"], errors="coerce").fillna(0).astype(int)
    )
    daily["position_state"] = daily["position_state"].fillna("mid_position").astype(str)
    daily["high_position_risk"] = daily["high_position_risk"].fillna(False).astype(bool)
    for col in ["recent_3d_return", "recent_5d_return", "ret_5d", "ret_10d", "volume_ratio", "upper_shadow_ratio", "amount_zscore", "amount"]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce").fillna(0.0)
    daily["net_buy_to_amount"] = (
        daily["net_buy_value"] / daily["amount"].where(daily["amount"] > 0, pd.NA)
    ).fillna(0.0).clip(lower=-1, upper=1)
    daily["sell_pressure"] = (
        daily["top_sell_value"] / daily["amount"].where(daily["amount"] > 0, pd.NA)
    ).fillna(0.0).clip(lower=0, upper=1)

    netbuy_rank_pct = daily.groupby("trade_date")["net_buy_to_amount"].rank(pct=True, method="average")
    final_buy = (
        netbuy_rank_pct.ge(0.90)
        & daily["recent_repeat_agency_count"].ge(1)
        & daily["same_day_top_agency_count"].ge(3)
        & daily["position_state"].eq("high_position")
        & daily["ret_5d"].le(0.45)
        & daily["ret_10d"].le(0.90)
        & daily["amount_zscore"].le(2.50)
        & daily["volume_ratio"].le(2.50)
    )
    final_watch = (
        netbuy_rank_pct.ge(0.80)
        & daily["recent_repeat_agency_count"].ge(1)
        & daily["same_day_top_agency_count"].ge(2)
        & daily["ret_5d"].le(0.55)
    )
    cooling_score = (
        -_daily_zscore(daily, "net_buy_to_amount")
        - _daily_zscore(daily, "ret_5d")
        - _daily_zscore(daily, "ret_10d")
    ).div(3.0)
    daily["factor_value"] = (
        cooling_score
        + final_watch.astype(float).mul(0.25)
        + final_buy.astype(float).mul(3.00)
    ).round(6)
    factor_rank_pct = daily.groupby("trade_date")["factor_value"].rank(pct=True, method="average")
    netbuy_rank_pct = daily.groupby("trade_date")["net_buy_to_amount"].rank(pct=True, method="average")
    has_core_signal = final_buy
    has_watch_signal = final_watch
    daily["signal"] = "hold"
    daily.loc[has_watch_signal, "signal"] = "watch"
    daily.loc[has_core_signal, "signal"] = "buy"

    daily["confidence"] = (
        factor_rank_pct.mul(0.35)
        + daily["net_buy_to_amount"].clip(0, 1).mul(0.20)
        + daily["recent_repeat_agency_count"].div(3).clip(upper=1).mul(0.18)
        + daily["same_day_top_agency_count"].div(top_n).clip(upper=1).mul(0.17)
        + daily["ret_5d"].le(0.45).astype(float).mul(0.10)
    ).clip(0, 1).round(4)

    update_time = update_time or datetime.now().isoformat(timespec="seconds")
    daily["score"] = (
        daily.groupby("trade_date")["factor_value"]
        .transform(lambda s: s.rank(pct=True, method="average").mul(100))
        .round(2)
    )
    daily["rank"] = daily.groupby("trade_date")["factor_value"].rank(
        ascending=False,
        method="first",
    ).astype(int)
    daily["asset_type"] = "stock"
    daily["factor_id"] = FACTOR_ID
    daily["factor_name"] = FACTOR_NAME
    daily["data_version"] = data_version
    daily["update_time"] = update_time
    daily["top_buy_value"] = daily["top_buy_value"].round(2)
    daily["top_sell_value"] = daily["top_sell_value"].round(2)
    daily["net_buy_value"] = daily["net_buy_value"].round(2)
    daily["net_buy_to_amount"] = daily["net_buy_to_amount"].round(6)
    daily["sell_pressure"] = daily["sell_pressure"].round(6)
    daily["avg_net_buy_ratio"] = daily["avg_net_buy_ratio"].round(4)
    daily["collaboration_strength"] = daily["collaboration_strength"].round(6)
    daily["avg_agency_quality"] = daily["avg_agency_quality"].round(4)
    daily["max_agency_quality"] = daily["max_agency_quality"].round(4)
    daily["avg_agency_hist_win_rate"] = daily["avg_agency_hist_win_rate"].round(4)
    daily["avg_agency_hist_return"] = daily["avg_agency_hist_return"].round(6)
    daily["avg_agency_net_persistence"] = daily["avg_agency_net_persistence"].round(4)
    daily["avg_agency_reversal_risk"] = daily["avg_agency_reversal_risk"].round(4)
    daily["is_limit_up_close"] = daily["is_limit_up_close"].astype(bool)
    daily["limit_up_streak"] = daily["limit_up_streak"].astype(int)
    daily["recent_limit_up_count_5d"] = daily["recent_limit_up_count_5d"].astype(int)
    daily["recent_3d_return"] = daily["recent_3d_return"].round(6)
    daily["recent_5d_return"] = daily["recent_5d_return"].round(6)
    daily["ret_5d"] = daily["ret_5d"].round(6)
    daily["ret_10d"] = daily["ret_10d"].round(6)
    daily["volume_ratio"] = daily["volume_ratio"].round(4)
    daily["upper_shadow_ratio"] = daily["upper_shadow_ratio"].round(4)
    daily["high_position_risk"] = daily["high_position_risk"].astype(bool)
    daily["amount_zscore"] = daily["amount_zscore"].round(4)
    for col in [
        "recent_repeat_agency_count",
        "max_recent_buy_days",
        "disclosure_repeat_agency_count",
    ]:
        daily[col] = daily[col].fillna(0).astype(int)
    daily["dynamic_quality_enabled"] = daily["dynamic_quality_enabled"].astype(int)

    output = daily[STANDARD_COLUMNS + DIAGNOSTIC_COLUMNS].sort_values(
        ["trade_date", "rank", "ts_code"]
    )
    return output.reset_index(drop=True)


def validate_production_output(result: pd.DataFrame, valid_trade_dates: set[str] | None = None) -> None:
    required = set(STANDARD_COLUMNS)
    missing = required - set(result.columns)
    if missing:
        raise ValueError(f"生产结果缺少字段: {sorted(missing)}")
    if result[list(required)].isna().any().any():
        raise ValueError("生产结果标准字段存在空值")
    duplicate = result.duplicated(["trade_date", "factor_id", "ts_code"], keep=False)
    if duplicate.any():
        examples = result.loc[duplicate, ["trade_date", "factor_id", "ts_code"]].head(5).to_dict("records")
        raise ValueError(f"生产结果主键重复，示例: {examples}")
    if not result["score"].between(0, 100).all():
        raise ValueError("score 必须位于 0-100")
    if not set(result["signal"]).issubset({"buy", "watch", "hold"}):
        raise ValueError("signal 只能为 buy/watch/hold")
    if set(result["factor_id"].astype(str)) != {FACTOR_ID}:
        raise ValueError(f"factor_id 必须全部为 {FACTOR_ID}")
    if set(result["asset_type"].astype(str)) != {"stock"}:
        raise ValueError("asset_type 必须全部为 stock")
    if valid_trade_dates is not None:
        invalid_dates = sorted(set(result["trade_date"].astype(str)) - set(valid_trade_dates))
        if invalid_dates:
            raise ValueError(f"生产结果包含非交易日，示例: {invalid_dates[:5]}")


def write_production(result: pd.DataFrame, output_path: str) -> None:
    validate_production_output(result)
    result.to_parquet(output_path, index=False)


def sample_lhb_detail() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["20260504", "000001.SZ", "buy", 1, "银河证券北京中关村营业部", 18_000_000, 200_000, "G0007"],
            ["20260505", "000001.SZ", "buy", 2, "银河证券北京中关村营业部", 22_000_000, 100_000, "G0007"],
            ["20260505", "000001.SZ", "buy", 3, "国泰君安上海江苏路营业部", 14_000_000, 0, "G0007"],
            ["20260506", "000001.SZ", "buy", 1, "银河证券北京中关村营业部", 26_000_000, 0, "G0007"],
            ["20260506", "000001.SZ", "buy", 2, "华泰证券深圳益田路营业部", 16_000_000, 0, "G0007"],
            ["20260507", "000001.SZ", "buy", 1, "银河证券北京中关村营业部", 19_000_000, 0, "T0020"],
            ["20260505", "000002.SZ", "buy", 1, "中信证券上海溧阳路营业部", 10_000_000, 0, "T0020"],
            ["20260505", "000002.SZ", "buy", 2, "华泰证券深圳益田路营业部", 11_000_000, 0, "T0020"],
            ["20260506", "000002.SZ", "buy", 1, "国泰君安上海江苏路营业部", 9_000_000, 0, "T0020"],
            ["20260507", "000003.SZ", "buy", 1, "中信证券上海溧阳路营业部", 8_000_000, 0, "G0007"],
        ],
        columns=["date", "symbol", "side", "rank", "agency", "b_value", "s_value", "type"],
    )


def sample_trade_calendar() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "nature_date": ["20260504", "20260505", "20260506", "20260507", "20260508"],
            "is_trading_day": [1, 1, 1, 1, 1],
        }
    )


def sample_quotes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["2026-05-04", "000001.SZ", 9.82, 10.00, 10.25, 9.78, 1_200_000, 12_000_000, 9.80, 10.78, 8.82, "交易"],
            ["2026-05-05", "000001.SZ", 10.05, 10.20, 10.46, 9.98, 1_450_000, 15_000_000, 10.00, 11.00, 9.00, "交易"],
            ["2026-05-06", "000001.SZ", 10.45, 11.22, 11.22, 10.42, 2_300_000, 26_000_000, 10.20, 11.22, 9.18, "交易"],
            ["2026-05-07", "000001.SZ", 11.80, 12.34, 12.34, 11.70, 3_000_000, 36_000_000, 11.22, 12.34, 10.10, "交易"],
            ["2026-05-08", "000001.SZ", 12.20, 12.00, 12.30, 11.85, 2_100_000, 25_000_000, 12.34, 13.57, 11.11, "交易"],
            ["2026-05-04", "000002.SZ", 7.90, 8.00, 8.08, 7.88, 900_000, 7_200_000, 7.90, 8.69, 7.11, "交易"],
            ["2026-05-05", "000002.SZ", 8.05, 8.80, 8.80, 8.02, 1_600_000, 14_000_000, 8.00, 8.80, 7.20, "交易"],
            ["2026-05-06", "000002.SZ", 8.48, 8.05, 8.60, 8.00, 1_100_000, 9_000_000, 8.80, 9.68, 7.92, "交易"],
            ["2026-05-07", "000002.SZ", 8.03, 8.20, 8.30, 7.98, 980_000, 8_100_000, 8.05, 8.86, 7.25, "交易"],
            ["2026-05-08", "000002.SZ", 8.18, 8.15, 8.25, 8.02, 920_000, 7_600_000, 8.20, 9.02, 7.38, "交易"],
            ["2026-05-04", "000003.SZ", 5.95, 6.00, 6.05, 5.90, 720_000, 4_300_000, 5.92, 6.51, 5.33, "交易"],
            ["2026-05-05", "000003.SZ", 5.98, 5.95, 6.02, 5.88, 680_000, 4_000_000, 6.00, 6.60, 5.40, "交易"],
            ["2026-05-06", "000003.SZ", 5.96, 6.05, 6.12, 5.92, 740_000, 4_500_000, 5.95, 6.55, 5.36, "交易"],
            ["2026-05-07", "000003.SZ", 6.18, 6.66, 6.66, 6.16, 1_300_000, 8_600_000, 6.05, 6.66, 5.45, "交易"],
            ["2026-05-08", "000003.SZ", 6.60, 6.30, 6.62, 6.22, 980_000, 6_200_000, 6.66, 7.33, 5.99, "交易"],
        ],
        columns=[
            "trade_date",
            "ts_code",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "pre_close",
            "limit_up",
            "limit_down",
            "trade_status",
        ],
    )


def _parse_args() -> argparse.Namespace:
    default_start, default_end = _date_defaults()
    parser = argparse.ArgumentParser(description="计算游资席位协同 Alpha")
    parser.add_argument("--start-date", default=os.getenv("PANDA_DATA_START_DATE", default_start))
    parser.add_argument("--end-date", default=os.getenv("PANDA_DATA_END_DATE", default_end))
    parser.add_argument("--symbols", default=os.getenv("PANDA_DATA_SYMBOLS"))
    parser.add_argument("--lhb-type", default=os.getenv("PANDA_DATA_LHB_TYPE"))
    parser.add_argument("--top-n", type=int, default=int(os.getenv("ALPHA_TOP_N", "5")))
    parser.add_argument("--streak-window", type=int, default=3)
    parser.add_argument("--top-agencies", default=os.getenv("ALPHA_TOP_AGENCIES"))
    parser.add_argument("--no-hot-money-filter", action="store_true", help="关闭默认机构/外资投行过滤")
    parser.add_argument("--min-buy-value", type=float, default=float(os.getenv("ALPHA_MIN_BUY_VALUE", "5000000")))
    parser.add_argument("--min-net-buy-ratio", type=float, default=float(os.getenv("ALPHA_MIN_NET_BUY_RATIO", "0.55")))
    parser.add_argument("--exclude-agency-keywords", default=os.getenv("ALPHA_EXCLUDE_AGENCY_KEYWORDS"))
    parser.add_argument("--factor-mode", choices=sorted(VALID_FACTOR_MODES), default=os.getenv("ALPHA_FACTOR_MODE", FACTOR_MODE_FINAL))
    parser.add_argument("--no-dynamic-seat-quality", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quality-quote-end-date", default=os.getenv("PANDA_DATA_QUALITY_QUOTE_END_DATE"), help="行情数据截止日，默认等于 end-date")
    parser.add_argument("--data-version", default=DEFAULT_DATA_VERSION)
    parser.add_argument("--output", help="可选：写入生产 Parquet 路径")
    parser.add_argument("--print-limit", type=int, default=int(os.getenv("ALPHA_PRINT_LIMIT", "50")))
    parser.add_argument("--demo", action="store_true", help="使用内置样例数据做离线烟测，不作为生产结果")
    return parser.parse_args()


def _run_default_production_update() -> None:
    from update_production import update_production

    end_date = date.today().strftime("%Y%m%d")
    bootstrap_start = (date.today() - timedelta(days=365 * 3 + 2)).strftime("%Y%m%d")
    lookback_days = int(os.getenv("ALPHA_DEFAULT_LOOKBACK_DAYS", "10"))
    quality_lookback_days = int(os.getenv("ALPHA_DEFAULT_QUALITY_LOOKBACK_DAYS", "260"))
    result = update_production(
        output_path=DEFAULT_PRODUCTION_OUTPUT,
        end_date=end_date,
        bootstrap_start_date=bootstrap_start,
        lookback_days=lookback_days,
        quality_lookback_days=quality_lookback_days,
        full_refresh=False,
        data_version=DEFAULT_DATA_VERSION,
    )
    print(f"A06 生产更新完成: {_display_path(DEFAULT_PRODUCTION_OUTPUT)}")
    print(f"结果行数: {len(result)}")
    print(f"日期范围: {result['trade_date'].min()} 至 {result['trade_date'].max()}")
    print(f"data_version: {DEFAULT_DATA_VERSION}")


def main() -> None:
    if len(sys.argv) == 1:
        _run_default_production_update()
        return

    args = _parse_args()
    top_agencies = _split_csv(args.top_agencies)

    if args.demo:
        details = sample_lhb_detail()
        calendar = sample_trade_calendar()
        quality_quotes = sample_quotes()
        data_version = "sample-a06-v1"
    else:
        details = load_real_lhb_details(
            start_date=args.start_date,
            end_date=args.end_date,
            symbols=_split_csv(args.symbols),
            lhb_type=_split_csv(args.lhb_type) if args.lhb_type and "," in args.lhb_type else args.lhb_type,
        )
        calendar = load_real_trade_calendar(args.start_date, args.end_date)
        quality_quotes = None
        detail_frame = pd.DataFrame(details)
        symbol_col = "symbol" if "symbol" in detail_frame.columns else "ts_code"
        quality_quotes = load_real_quotes(
            start_date=args.start_date,
            end_date=args.quality_quote_end_date or args.end_date,
            symbols=sorted(detail_frame[symbol_col].astype(str).unique()),
        )
        data_version = args.data_version

    result = calculate_factor(
        details,
        trade_calendar=calendar,
        top_n=args.top_n,
        streak_window=args.streak_window,
        top_agencies=top_agencies,
        filter_hot_money=not args.no_hot_money_filter,
        min_buy_value=args.min_buy_value,
        min_net_buy_ratio=args.min_net_buy_ratio,
        exclude_agency_keywords=_split_csv(args.exclude_agency_keywords) if args.exclude_agency_keywords else None,
        quotes=quality_quotes,
        dynamic_seat_quality=False,
        factor_mode=args.factor_mode,
        data_version=data_version,
    )
    preview = result.head(args.print_limit) if args.print_limit > 0 else result.head(0)
    if not preview.empty:
        print(preview.to_string(index=False))
    print(f"结果行数: {len(result)}")
    if args.output:
        write_production(result, args.output)
        print(f"已写入: {_display_path(args.output)}")


if __name__ == "__main__":
    main()
