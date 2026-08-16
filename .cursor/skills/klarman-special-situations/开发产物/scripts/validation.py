"""校验仅查询模式的卡拉曼事件扫描输入。"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from .core import (
        Any,
        InputValidationError,
        Mapping,
        datetime,
    )
except ImportError:  # 支持直接执行脚本
    from core import (
        Any,
        InputValidationError,
        Mapping,
        datetime,
    )
__all__ = ['validate_input', 'validate_config']

_A_SHARE_SYMBOL = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")

def validate_input(input_data: Mapping[str, Any]) -> None:
    if not isinstance(input_data, Mapping) or not input_data:
        raise InputValidationError("input_data 必须是非空映射")
    allowed = {"as_of_date", "start_date", "symbols"}
    unknown = sorted(set(input_data) - allowed)
    if unknown:
        raise InputValidationError(f"未知输入字段: {unknown}")
    as_of = input_data.get("as_of_date")
    if not isinstance(as_of, str):
        raise InputValidationError("as_of_date 为必填项，格式为 YYYYMMDD")
    try:
        as_of_dt = datetime.strptime(as_of, "%Y%m%d")
    except ValueError as exc:
        raise InputValidationError("as_of_date 必须使用 YYYYMMDD 格式") from exc
    start = input_data.get("start_date")
    if start is not None:
        try:
            start_dt = datetime.strptime(str(start), "%Y%m%d")
        except ValueError as exc:
            raise InputValidationError("start_date 必须使用 YYYYMMDD 格式") from exc
        if start_dt > as_of_dt:
            raise InputValidationError("start_date 不得晚于 as_of_date")
    symbols = input_data.get("symbols")
    if symbols is not None:
        if not isinstance(symbols, list) or not all(isinstance(value, str) for value in symbols):
            raise InputValidationError("symbols 必须是字符串列表")
        invalid_symbols = sorted(
            {value for value in symbols if not _A_SHARE_SYMBOL.fullmatch(value)}
        )
        if invalid_symbols:
            raise InputValidationError(
                f"symbols 只接受 6 位代码加 .SH/.SZ/.BJ: {invalid_symbols}"
            )
    for forbidden in ("data", "dataframe", "prices", "financials", "announcements"):
        if forbidden in input_data:
            raise InputValidationError(
                f"禁止使用原始字段 {forbidden!r}；生产数据必须来自 panda_data"
            )


def validate_config(config: Mapping[str, Any] | None) -> None:
    if config is None:
        return
    if not isinstance(config, Mapping):
        raise InputValidationError("config 必须是映射")
    allowed = {
        "unlock_window_days",
        "placement_gain_alert_threshold",
        "minimum_margin_of_safety",
        "failure_probability_stress",
        "evidence_dir",
        "evidence_provider",
        "policy_path",
        "policy",
        "materialize",
        "output_path",
        "allow_partial_materialization",
        "progress_callback",
        "manifest_dir",
        "max_api_attempts",
        "checkpoint_dir",
        "checkpoint_batch_size",
    }
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise InputValidationError(f"未知配置字段: {unknown}")
    if config.get("evidence_dir") is not None and config.get("evidence_provider") is not None:
        raise InputValidationError("evidence_dir 与 evidence_provider 互斥")
    if config.get("policy") is not None and config.get("policy_path") is not None:
        raise InputValidationError("policy 与 policy_path 互斥")
    unlock_days = config.get("unlock_window_days", 90)
    if isinstance(unlock_days, bool) or not isinstance(unlock_days, int) or unlock_days <= 0:
        raise InputValidationError("unlock_window_days 必须是正整数")
    for name in ("placement_gain_alert_threshold", "minimum_margin_of_safety", "failure_probability_stress"):
        value = config.get(name)
        if value is not None:
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise InputValidationError(f"{name} 必须是 0 到 1 的数值") from exc
            if not 0 <= numeric <= 1:
                raise InputValidationError(f"{name} 必须是 0 到 1 的数值")
    if "materialize" in config and not isinstance(config["materialize"], bool):
        raise InputValidationError("materialize 必须是布尔值")
    if "allow_partial_materialization" in config and not isinstance(
        config["allow_partial_materialization"], bool
    ):
        raise InputValidationError("allow_partial_materialization 必须是布尔值")
    if config.get("output_path") is not None and not isinstance(
        config["output_path"], (str, Path)
    ):
        raise InputValidationError("output_path 必须是字符串或 Path")
    if config.get("progress_callback") is not None and not callable(
        config["progress_callback"]
    ):
        raise InputValidationError("progress_callback 必须可调用")
    if config.get("manifest_dir") is not None and not isinstance(config["manifest_dir"], (str, Path)):
        raise InputValidationError("manifest_dir 必须是字符串或 Path")
    attempts = config.get("max_api_attempts", 2)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 4:
        raise InputValidationError("max_api_attempts 必须是 1 到 4 的整数")
    if config.get("checkpoint_dir") is not None and not isinstance(config["checkpoint_dir"], (str, Path)):
        raise InputValidationError("checkpoint_dir 必须是字符串或 Path")
    batch_size = config.get("checkpoint_batch_size", 50)
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 200:
        raise InputValidationError("checkpoint_batch_size 必须是 1 到 200 的整数")
