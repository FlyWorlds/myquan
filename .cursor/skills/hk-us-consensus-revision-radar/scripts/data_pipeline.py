"""PandaData collection and normalization for HK/US consensus research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


TRAJECTORY_HORIZONS = ("week", "1month", "3month", "6month", "12month")
HORIZONS = TRAJECTORY_HORIZONS
TARGET_BASE_FIELDS = [
    "mean", "median", "high", "low", "std", "estimates_num",
    "included_estimates_num",
]
RECOMMENDATION_BASE_FIELDS = [
    "mean", "strong_buy_num", "buy_num", "hold", "sell_num",
    "strong_sell_num", "no_opinion_num", "recommendations_num",
]


def consensus_fields(horizon: str) -> tuple[list[str], list[str]]:
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of: {', '.join(HORIZONS)}")
    ncycl = ["symbol", "currency", "indicator", *TARGET_BASE_FIELDS]
    recommendation = ["symbol", "currency", *RECOMMENDATION_BASE_FIELDS]
    ncycl.extend(f"mean_{period}" for period in TRAJECTORY_HORIZONS)
    recommendation.extend(f"mean_{period}" for period in TRAJECTORY_HORIZONS)
    return list(dict.fromkeys(ncycl)), list(dict.fromkeys(recommendation))

MARKET_APIS = {
    "hk": {
        "ncycl": "get_stock_ncycl_consensus",
        "recommendation": "get_stock_recommendation_consensus",
        "daily": "get_hk_daily",
        "detail": "get_hk_detail",
        "price_fields": [
            "symbol", "date", "close", "volume", "amount", "name", "trade_status",
        ],
        "detail_fields": [
            "symbol", "name", "cn_name", "local_name", "status", "trading_code",
            "rcs_asset_category_name", "business_sector", "economic_sector",
            "industry_group",
        ],
    },
    "us": {
        "ncycl": "get_stock_ncycl_estimate",
        "recommendation": "get_stock_recommendation_estimate",
        "daily": "get_us_daily",
        "detail": "get_us_detail",
        "price_fields": [
            "symbol", "date", "close", "volume", "name", "trade_status",
        ],
        "detail_fields": [
            "symbol", "name", "local_name", "status", "trading_code",
            "rcs_asset_category_name", "business_sector", "economic_sector",
            "industry_group",
        ],
    },
}


@dataclass(frozen=True)
class MarketFrames:
    market: str
    horizon: str
    ncycl: pd.DataFrame
    recommendations: pd.DataFrame
    prices: pd.DataFrame
    details: pd.DataFrame
    source_ncycl: str
    source_recommendation: str
    source_price: str
    source_detail: str
    diagnostics: dict[str, object]
    universe: tuple[str, ...]


def _date_window(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    end = date.today() if end_date is None else date.fromisoformat(
        f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    )
    start = end - timedelta(days=14) if start_date is None else date.fromisoformat(
        f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    )
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _parse_latest_trade_date(value: object) -> str | None:
    """Normalize PandaData's documented table response and legacy scalar forms."""
    candidate: object = value
    if isinstance(candidate, pd.DataFrame):
        if candidate.empty or "date" not in candidate.columns:
            return None
        values = candidate["date"].dropna()
        candidate = values.iloc[0] if not values.empty else None
    elif isinstance(candidate, pd.Series):
        values = candidate.dropna()
        candidate = values.iloc[0] if not values.empty else None
    elif isinstance(candidate, dict):
        candidate = candidate.get("date")
    elif isinstance(candidate, (list, tuple)):
        candidate = candidate[0] if candidate else None
    if candidate is None or pd.isna(candidate):
        return None
    text = str(candidate).strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
    except ValueError:
        return None
    return text


def _chunks(values: list[str], size: int = 200) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _symbols_in(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "symbol" not in frame.columns:
        return set()
    return set(frame["symbol"].dropna().astype(str))


def _valid_price_symbols(frame: pd.DataFrame) -> set[str]:
    if (
        frame.empty or "symbol" not in frame.columns
        or "close" not in frame.columns or "date" not in frame.columns
    ):
        return set()
    close = pd.to_numeric(frame["close"], errors="coerce")
    valid = close.gt(0) & frame["date"].notna()
    return set(frame.loc[valid, "symbol"].dropna().astype(str))


def _tag_price_frames(
    frames: list[pd.DataFrame], is_fallback: bool
) -> list[pd.DataFrame]:
    tagged: list[pd.DataFrame] = []
    for frame in frames:
        copy = frame.copy()
        copy["_price_is_fallback"] = is_fallback
        tagged.append(copy)
    return tagged


def _query_in_batches(function, symbols: list[str], **kwargs) -> list[pd.DataFrame]:
    return [function(symbol=batch, **kwargs) for batch in _chunks(symbols)]


def _notify_progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def collect_market_data(
    panda_module,
    market: str,
    symbols: list[str] | None = None,
    horizon: str = "1month",
    start_date: str | None = None,
    end_date: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> MarketFrames:
    market_key = market.lower()
    if market_key not in MARKET_APIS:
        raise ValueError("market must be hk or us")
    api = MARKET_APIS[market_key]
    label = market_key.upper()
    query_symbols = symbols if symbols else [""]

    ncycl_function = getattr(panda_module, api["ncycl"])
    recommendation_function = getattr(panda_module, api["recommendation"])
    daily_function = getattr(panda_module, api["daily"])
    detail_function = getattr(panda_module, api["detail"])

    ncycl_fields, recommendation_fields = consensus_fields(horizon)
    _notify_progress(progress_callback, f"{label} 正在获取一致预期数据...")
    ncycl = ncycl_function(symbol=query_symbols, fields=ncycl_fields)
    recommendations = recommendation_function(
        symbol=query_symbols,
        fields=recommendation_fields,
    )
    consensus_retrieved_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime(
        "%Y-%m-%d %H:%M:%S %z"
    )
    _notify_progress(progress_callback, f"{label} 一致预期数据获取完成。")

    universe = sorted(_symbols_in(ncycl) | _symbols_in(recommendations))
    if symbols:
        universe = sorted(set(symbols))

    _notify_progress(progress_callback, f"{label} 正在获取证券名称、状态与类型...")
    detail_frames = _query_in_batches(
        detail_function,
        universe,
        fields=api["detail_fields"],
        status=None,
    )
    nonempty_details = [frame for frame in detail_frames if not frame.empty]
    details = (
        pd.concat(nonempty_details, ignore_index=True)
        if nonempty_details else pd.DataFrame()
    )
    _notify_progress(progress_callback, f"{label} 证券身份数据获取完成。")

    _notify_progress(progress_callback, f"{label} 正在获取行情数据...")
    price_frames: list[pd.DataFrame] = []
    initial_prices = pd.DataFrame()
    latest_date: str | None = None
    fallback_used = False
    initial_returned_symbols: set[str] = set()
    fallback_attempted_symbols: set[str] = set()
    fallback_returned_symbols: set[str] = set()
    latest_date_function = getattr(panda_module, "get_last_trade_date", None)

    if start_date is None and end_date is None and callable(latest_date_function):
        latest_date = _parse_latest_trade_date(
            latest_date_function(exchange=market_key.upper())
        )
        if latest_date:
            initial_frames = _query_in_batches(
                daily_function,
                universe,
                start_date=latest_date,
                end_date=latest_date,
                fields=api["price_fields"],
            )
            nonempty_initial = [
                frame for frame in initial_frames if not frame.empty
            ]
            initial_prices = (
                pd.concat(nonempty_initial, ignore_index=True)
                if nonempty_initial else pd.DataFrame()
            )
            initial_returned_symbols = _symbols_in(initial_prices)
            price_frames.extend(_tag_price_frames(initial_frames, False))
            matched_initial = _valid_price_symbols(initial_prices) & set(universe)
            missing_symbols = sorted(set(universe) - matched_initial)
            if missing_symbols:
                fallback_used = True
                fallback_attempted_symbols = set(missing_symbols)
                latest_day = date.fromisoformat(
                    f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:8]}"
                )
                fallback_start = (latest_day - timedelta(days=13)).strftime("%Y%m%d")
                fallback_frames = _query_in_batches(
                            daily_function,
                            missing_symbols,
                            start_date=fallback_start,
                            end_date=latest_date,
                            fields=api["price_fields"],
                        )
                fallback_returned_symbols = set().union(
                    *(_symbols_in(frame) for frame in fallback_frames)
                ) if fallback_frames else set()
                price_frames.extend(_tag_price_frames(fallback_frames, True))

    if not price_frames:
        start_value, end_value = _date_window(start_date, end_date)
        window_frames = _query_in_batches(
                daily_function,
                universe,
                start_date=start_value,
                end_date=end_value,
                fields=api["price_fields"],
            )
        initial_returned_symbols = set().union(
            *(_symbols_in(frame) for frame in window_frames)
        ) if window_frames else set()
        price_frames.extend(_tag_price_frames(window_frames, False))

    nonempty_prices = [frame for frame in price_frames if not frame.empty]
    prices = pd.concat(nonempty_prices, ignore_index=True) if nonempty_prices else pd.DataFrame()
    matched_symbols = _valid_price_symbols(prices) & set(universe)

    _notify_progress(progress_callback, f"{label} 行情数据获取完成。")

    diagnostics: dict[str, object] = {
        "consensus_retrieved_at": consensus_retrieved_at,
        "consensus_as_of": None,
        "historical_snapshot_label": horizon,
        "historical_snapshot_as_of": None,
        "requested_latest_date": latest_date,
        "price_initial_rows": int(len(initial_prices)),
        "price_fallback_used": fallback_used,
        "price_returned_rows": int(len(prices)),
        "price_matched_symbols": int(len(matched_symbols)),
        "price_universe_symbols": int(len(universe)),
        "price_match_rate": (
            len(matched_symbols) / len(universe) if universe else None
        ),
        "price_initial_returned_symbols": sorted(initial_returned_symbols),
        "price_fallback_attempted_symbols": sorted(fallback_attempted_symbols),
        "price_fallback_returned_symbols": sorted(fallback_returned_symbols),
    }
    if not prices.empty and "date" in prices.columns:
        price_dates = prices["date"].dropna().astype(str)
        diagnostics["price_date_min"] = price_dates.min() if not price_dates.empty else None
        diagnostics["price_date_max"] = price_dates.max() if not price_dates.empty else None

    return MarketFrames(
        market=market_key,
        horizon=horizon,
        ncycl=ncycl,
        recommendations=recommendations,
        prices=prices,
        details=details,
        source_ncycl=api["ncycl"],
        source_recommendation=api["recommendation"],
        source_price=api["daily"],
        source_detail=api["detail"],
        diagnostics=diagnostics,
        universe=tuple(universe),
    )


def _rename_available(frame: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    return frame.rename(columns={key: value for key, value in mapping.items() if key in frame.columns})


def _metric_mapping(
    columns: Iterable[str],
    bases: list[str],
    prefix: str,
) -> dict[str, str]:
    mapping = {"currency": f"{prefix}_currency"}
    for column in columns:
        if any(column == base or column.startswith(f"{base}_") for base in bases):
            mapping[column] = f"{prefix}_{column}"
    return mapping


def _normalize_details(frames: MarketFrames) -> pd.DataFrame:
    details = frames.details.copy()
    if details.empty or "symbol" not in details.columns:
        return pd.DataFrame(columns=[
            "symbol", "detail_name", "name_source", "security_status",
            "security_type", "universe_eligible", "universe_exclusion_reason",
            "trading_code", "business_sector", "economic_sector", "industry_group",
        ])
    preferred = (
        ("cn_name", "local_name", "name")
        if frames.market == "hk"
        else ("name", "local_name")
    )
    display_name = pd.Series(pd.NA, index=details.index, dtype="object")
    for column in preferred:
        if column in details.columns:
            values = details[column].where(details[column].notna())
            values = values.map(
                lambda value: str(value).strip() if pd.notna(value) else pd.NA
            )
            values = values.where(values.ne(""))
            display_name = display_name.combine_first(values)
    category = details.get(
        "rcs_asset_category_name", pd.Series(pd.NA, index=details.index)
    )
    names = display_name.fillna("").astype(str)

    def classify_security(value: object, name: str) -> str:
        text = "" if pd.isna(value) else str(value).strip().lower()
        name_text = name.strip().lower()
        if "ordinary share" in text:
            return "ordinary_share"
        if "depositary receipt" in text or "depository receipt" in text:
            return "depositary_receipt"
        if "preferred" in text or "preference" in text:
            return "preferred_share"
        if "warrant" in text:
            return "warrant"
        if "fund" in text or "etf" in text:
            return "fund"
        if "bond" in text or "debt" in text or "note" in text:
            return "debt_security"
        if "structured" in text or "derivative" in text:
            return "derivative"
        nonordinary_name_terms = {
            "etf": "fund", "fund": "fund", "warrant": "warrant",
            "preferred": "preferred_share", "preference": "preferred_share",
        }
        for term, security_type in nonordinary_name_terms.items():
            if re.search(rf"\b{term}\b", name_text):
                return security_type
        return "unknown"

    security_type = pd.Series(
        [classify_security(value, name) for value, name in zip(category, names)],
        index=details.index,
        dtype="object",
    )
    status_raw = details.get("status", pd.Series(pd.NA, index=details.index))
    status_numeric = pd.to_numeric(status_raw, errors="coerce")
    active = status_numeric.eq(1)
    universe_eligible = active & security_type.eq("ordinary_share")
    exclusion_reason = pd.Series(pd.NA, index=details.index, dtype="object")
    exclusion_reason.loc[status_numeric.notna() & ~active] = "inactive_security"
    exclusion_reason.loc[status_numeric.isna()] = "unknown_security_status"
    exclusion_reason.loc[active & security_type.eq("unknown")] = "unknown_security_type"
    exclusion_reason.loc[active & ~security_type.isin(["ordinary_share", "unknown"])] = (
        "non_ordinary_security"
    )

    normalized = pd.DataFrame({
        "symbol": details["symbol"].astype(str),
        "detail_name": display_name,
        "name_source": frames.source_detail,
        "security_status": status_numeric.astype("Int64"),
        "security_type": security_type,
        "universe_eligible": universe_eligible.astype(bool),
        "universe_exclusion_reason": exclusion_reason,
    })
    for column in ("trading_code", "business_sector", "economic_sector", "industry_group"):
        normalized[column] = details.get(column, pd.Series(pd.NA, index=details.index))
    return normalized.drop_duplicates(subset=["symbol"], keep="last")


def normalize_market_frames(frames: MarketFrames) -> pd.DataFrame:
    ncycl = frames.ncycl.copy()
    if "symbol" not in ncycl.columns:
        ncycl = pd.DataFrame(columns=["symbol"])
    if "indicator" in ncycl.columns:
        ncycl = ncycl.loc[ncycl["indicator"] == "TP"].copy()
    ncycl = ncycl.drop_duplicates(subset=["symbol"], keep="last")
    ncycl = _rename_available(
        ncycl,
        _metric_mapping(ncycl.columns, ["mean", "median", "high", "low", "std"], "tp"),
    )

    recommendations = frames.recommendations.copy()
    if "symbol" not in recommendations.columns:
        recommendations = pd.DataFrame(columns=["symbol"])
    recommendations = recommendations.drop_duplicates(subset=["symbol"], keep="last")
    recommendation_mapping = {"currency": "rec_currency", "mean": "rec_mean"}
    recommendation_mapping.update(
        {
            column: f"rec_{column}"
            for column in recommendations.columns
            if column.startswith("mean_")
        }
    )
    recommendations = _rename_available(recommendations, recommendation_mapping)

    prices = frames.prices.copy()
    if not prices.empty:
        prices["date"] = prices["date"].astype(str)
        prices["_valid_price_sort"] = pd.to_numeric(
            prices.get("close"), errors="coerce"
        ).gt(0)
        prices = prices.sort_values(
            ["symbol", "_valid_price_sort", "date"], kind="mergesort"
        ).drop_duplicates(
            subset=["symbol"], keep="last"
        )
        prices = prices.drop(columns="_valid_price_sort")
        prices = prices.rename(columns={
            "date": "price_date", "name": "price_name",
            "_price_is_fallback": "price_is_fallback",
        })
        if "price_name" not in prices.columns:
            prices["price_name"] = pd.NA

    result = pd.DataFrame({"symbol": list(frames.universe)})
    result = result.merge(ncycl, on="symbol", how="left")
    result = result.merge(recommendations, on="symbol", how="left")
    if not prices.empty:
        result = result.merge(prices, on="symbol", how="left")
    else:
        for column in [
            "price_date", "close", "volume", "amount", "price_name", "trade_status",
            "price_is_fallback",
        ]:
            result[column] = pd.NA

    details = _normalize_details(frames)
    result = result.merge(details, on="symbol", how="left")
    result["name"] = result["detail_name"].combine_first(result["price_name"])
    result["name_source"] = result["name_source"].where(
        result["detail_name"].notna(),
        frames.source_price,
    )
    result.loc[result["name"].isna(), "name_source"] = pd.NA
    result = result.drop(columns=["detail_name", "price_name"], errors="ignore")
    result["universe_eligible"] = result.get(
        "universe_eligible", pd.Series(False, index=result.index)
    ).fillna(False).astype(bool)
    missing_detail = result["security_type"].isna()
    result.loc[missing_detail, "security_type"] = "unknown"
    result.loc[missing_detail, "universe_exclusion_reason"] = "missing_security_detail"
    close = pd.to_numeric(result.get("close"), errors="coerce")
    returned = result.get("price_date", pd.Series(pd.NA, index=result.index)).notna()
    result["price_valid"] = close.gt(0) & returned
    result["price_source_date"] = result.get("price_date")
    result["price_is_fallback"] = result.get(
        "price_is_fallback", pd.Series(False, index=result.index)
    ).fillna(False).astype(bool)
    price_reason = pd.Series(pd.NA, index=result.index, dtype="object")
    returned_evidence = set(
        frames.diagnostics.get("price_initial_returned_symbols", []) or []
    ) | set(frames.diagnostics.get("price_fallback_returned_symbols", []) or [])
    symbols = result["symbol"].astype(str)
    invalid_price = ~result["price_valid"]
    price_reason.loc[invalid_price] = "not_returned_by_api"
    price_reason.loc[invalid_price & symbols.isin(returned_evidence)] = (
        "invalid_or_nonpositive"
    )
    price_reason.loc[invalid_price & ~result["universe_eligible"]] = (
        "outside_core_universe"
    )
    result["price_missing_reason"] = price_reason
    result["market"] = frames.market
    result["source_ncycl"] = frames.source_ncycl
    result["source_recommendation"] = frames.source_recommendation
    result["source_price"] = frames.source_price
    result["source_detail"] = frames.source_detail
    return result.sort_values("symbol").reset_index(drop=True)
