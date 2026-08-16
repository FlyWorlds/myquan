"""Validate V9 full-A input and materialized production contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pathlib import Path

import pandas as pd

from .core import A_SHARE_PATTERN, DATA_VERSION, InputValidationError


PRODUCTION_COLUMNS = [
    "trade_date", "build_id", "build_name", "target_id", "result_type",
    "result_value", "result_json", "source_data_date", "data_version",
    "update_time", "schema_version", "run_id", "coverage_status", "actual_source_date",
]
PRODUCTION_RESULT_TYPES = {
    "buffett_research_candidate",
    "qualitative_review",
    "portfolio_target_weight",
    "portfolio_state_transition",
    "portfolio_summary",
    "strategy_validation",
    "universe_summary",
}


def validate_input(input_data: Mapping[str, Any]) -> None:
    if not isinstance(input_data, Mapping) or not input_data:
        raise InputValidationError("input_data 必须是非空映射")
    if "markets" in input_data:
        raise InputValidationError("markets 已删除；V9 只支持沪深 A 股")

    as_of = input_data.get("as_of_date")
    if not isinstance(as_of, str):
        raise InputValidationError("as_of_date 为必填项，格式为 YYYYMMDD")
    try:
        datetime.strptime(as_of, "%Y%m%d")
    except ValueError as exc:
        raise InputValidationError("as_of_date 必须使用 YYYYMMDD 格式") from exc

    symbols = input_data.get("symbols")
    index_symbol = input_data.get("index_symbol")
    universe = input_data.get("universe")
    provided = [value is not None for value in (symbols, index_symbol, universe)]
    if sum(provided) > 1:
        raise InputValidationError("universe、symbols 与 index_symbol 不能同时提供")
    if universe is not None and universe != "all_a":
        raise InputValidationError("universe 只支持 all_a")
    if symbols is not None:
        if not isinstance(symbols, list) or not symbols or not all(
            isinstance(value, str) for value in symbols
        ):
            raise InputValidationError("symbols 必须是非空字符串列表")
        invalid = [value for value in symbols if not A_SHARE_PATTERN.fullmatch(value)]
        if invalid:
            raise InputValidationError(f"只支持 A 股代码：{invalid}")
    if index_symbol is not None and (
        not isinstance(index_symbol, str) or not A_SHARE_PATTERN.fullmatch(index_symbol)
    ):
        raise InputValidationError("index_symbol 必须是 A 股指数代码")

    allowed = {"as_of_date", "symbols", "index_symbol", "universe"}
    unknown = sorted(set(input_data) - allowed)
    if unknown:
        raise InputValidationError(f"不支持的输入字段：{unknown}")


def validate_production(path: str | Path) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    if list(frame.columns) != PRODUCTION_COLUMNS:
        raise InputValidationError("production columns do not match the 14-column contract")
    if frame.empty:
        raise InputValidationError("production file is empty")
    if set(frame["data_version"].astype(str)) != {DATA_VERSION}:
        raise InputValidationError(f"production data_version is not {DATA_VERSION}")
    if set(frame["schema_version"].astype(str)) != {"3.0.0"}:
        raise InputValidationError("production schema_version is not 3.0.0")
    if not set(frame["result_type"]).issubset(PRODUCTION_RESULT_TYPES):
        raise InputValidationError("production contains an unknown result_type")
    if frame.duplicated(["trade_date", "build_id", "target_id", "result_type"]).any():
        raise InputValidationError("production primary key is duplicated")
    if not frame["result_value"].map(lambda value: isinstance(value, str)).all():
        raise InputValidationError("result_value must be string typed")
    return {
        "rows": int(len(frame)),
        "result_types": sorted(set(frame["result_type"])),
        "data_version": DATA_VERSION,
        "schema_version": "3.0.0",
    }
