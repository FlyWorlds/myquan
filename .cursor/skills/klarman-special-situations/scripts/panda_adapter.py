from __future__ import annotations

import importlib.metadata
import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

import numpy as np
import pandas as pd


SCHEMA_VERSION = "2.0.0"
PRODUCTION_KEY = ["trade_date", "build_id", "target_id", "result_type"]
_PROCESS_CREDENTIALS: tuple[str, str, str | None] | None = None
_CHECKPOINT_DIR: Path | None = None
_CHECKPOINT_BATCH_SIZE = 50
USERNAME_ENV = "PANDA_DATA_USERNAME"
PASSWORD_ENV = "PANDA_DATA_PASSWORD"
BASE_URL_ENV = "PANDA_DATA_BASE_URL"
API_NAME_ALIASES = {
    # The 2026-07-21 API document uses the stock-prefixed public names,
    # while panda-data 0.0.12 still exposes these reader functions internally.
    "get_stock_equity_illegal": ("get_stock_equity_illegal", "get_equity_illegal"),
    "get_stock_equity_placard": ("get_stock_equity_placard", "get_equity_placard"),
}
# The latest contract accepts a list, but the current service can reject large
# get_share_float payloads under account limits.  One-symbol checkpoints make
# the production scan resumable without weakening the coverage gate.
PER_SYMBOL_CHECKPOINT_APIS = {"get_share_float"}


class PandaDataError(RuntimeError):
    """Panda 数据边界的基础异常。"""


class PandaAuthenticationError(PandaDataError):
    """Panda 凭证不可用或被拒绝时抛出。"""


class PandaApiUnavailableError(PandaDataError):
    """已安装的开发包未提供必需接口时抛出。"""


def _safe_error_hint(exc: Exception) -> str:
    """Keep operational classification without persisting server text or credentials."""
    message = str(exc).lower()
    if any(token in message for token in ("限额", "quota", "rate limit", "rate-limit", "套餐")):
        return "quota_or_rate_limit"
    if any(token in message for token in ("timeout", "timed out", "connection", "network", "temporary")):
        return "transient_transport"
    if any(token in message for token in ("未上线", "not implemented", "not provided", "unavailable")):
        return "api_unavailable"
    return "data_or_service_error"


def configure_process_credentials(
    username: str, password: str, base_url: str | None = None
) -> None:
    """将 Panda 凭证仅保留在进程内存中，不修改环境变量。"""
    if not isinstance(username, str) or not username.strip():
        raise PandaAuthenticationError("账号必须是非空字符串")
    if not isinstance(password, str) or not password:
        raise PandaAuthenticationError("密码必须是非空字符串")
    if base_url is not None and not isinstance(base_url, str):
        raise PandaAuthenticationError("提供 base_url 时必须使用字符串")
    global _PROCESS_CREDENTIALS
    _PROCESS_CREDENTIALS = (username, password, base_url)


def clear_process_credentials() -> None:
    global _PROCESS_CREDENTIALS
    _PROCESS_CREDENTIALS = None


def configure_checkpointing(directory: str | Path | None, *, batch_size: int = 50) -> None:
    global _CHECKPOINT_DIR, _CHECKPOINT_BATCH_SIZE
    _CHECKPOINT_DIR = Path(directory) if directory is not None else None
    _CHECKPOINT_BATCH_SIZE = int(batch_size)
    if _CHECKPOINT_DIR is not None:
        _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def clear_checkpointing() -> None:
    global _CHECKPOINT_DIR
    _CHECKPOINT_DIR = None


def configure_from_environment(*, clear: bool = True) -> None:
    """Load named process environment variables without persisting or logging them."""
    username = os.environ.get(USERNAME_ENV)
    password = os.environ.get(PASSWORD_ENV)
    base_url = os.environ.get(BASE_URL_ENV)
    if not username or not password:
        raise PandaAuthenticationError(
            f"必须提供进程环境变量 {USERNAME_ENV} 和 {PASSWORD_ENV}"
        )
    configure_process_credentials(username, password, base_url)
    if clear:
        os.environ.pop(USERNAME_ENV, None)
        os.environ.pop(PASSWORD_ENV, None)
        os.environ.pop(BASE_URL_ENV, None)


def sdk_version() -> str:
    # The importable module and the distribution metadata use different names
    # across Panda Data releases (`panda_data` vs `panda-data`).  Probe both so
    # production metadata does not report a false missing-SDK error.
    for distribution in ("panda_data", "panda-data"):
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    raise PandaApiUnavailableError("尚未安装 panda_data")


def get_api(name: str):
    import panda_data

    candidates = API_NAME_ALIASES.get(name, (name,))
    for candidate in candidates:
        api = getattr(panda_data, candidate, None)
        if callable(api):
            return api

    # panda_data 0.0.12 has documented functions that are not top-level exports.
    from panda_data.readers import market_reference_reader

    for candidate in candidates:
        api = getattr(market_reference_reader, candidate, None)
        if callable(api):
            return api
    raise PandaApiUnavailableError(
        f"panda_data {sdk_version()} 未提供必需接口 {name}"
    )


def ensure_authenticated() -> None:
    import panda_data

    is_authenticated = getattr(panda_data, "is_authenticated", None)
    if callable(is_authenticated) and is_authenticated():
        return
    if getattr(panda_data, "_klarman_auth_done", False):
        return

    if _PROCESS_CREDENTIALS is None:
        raise PandaAuthenticationError(
            "真实运行前必须配置进程内 Panda 凭证"
        )
    username, password, base_url = _PROCESS_CREDENTIALS

    kwargs: dict[str, Any] = {"username": username, "password": password}
    if base_url:
        kwargs["base_url"] = base_url
    try:
        auth_manager = getattr(panda_data, "auth_manager", None)
        if auth_manager is not None and hasattr(auth_manager, "_persist_credentials"):
            persist_credentials = auth_manager._persist_credentials
            auth_manager._persist_credentials = lambda *args, **kwargs: None
            try:
                panda_data.init_token(**kwargs)
            finally:
                auth_manager._persist_credentials = persist_credentials
        else:
            panda_data.init_token(**kwargs)
        setattr(panda_data, "_klarman_auth_done", True)
    except Exception as exc:
        raise PandaAuthenticationError(
            f"panda_data 认证失败（{type(exc).__name__}）"
        ) from None


def _fetch_once(name: str, **kwargs: Any) -> pd.DataFrame:
    ensure_authenticated()
    try:
        result = get_api(name)(**kwargs)
    except PandaDataError:
        raise
    except Exception as exc:
        raise PandaDataError(
            f"{name} failed ({type(exc).__name__}): {_safe_error_hint(exc)}"
        ) from None
    if result is None:
        return pd.DataFrame()
    if not isinstance(result, pd.DataFrame):
        try:
            result = pd.DataFrame(result)
        except Exception as exc:
            raise PandaDataError(f"{name} returned unsupported type {type(result)!r}") from exc
    return result.copy()


def _checkpoint_key(name: str, symbols: list[str], kwargs: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"api": name, "symbols": symbols, "kwargs": kwargs},
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _checkpoint_parquet_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize unstable SDK object columns before checkpoint serialization."""
    normalized = frame.copy()
    object_columns = [
        column
        for column in normalized.columns
        if pd.api.types.is_object_dtype(normalized[column].dtype)
    ]
    for column in object_columns:
        series = normalized[column].map(
            lambda value: None
            if isinstance(value, str) and value.strip().lower() in {"nan", "<na>"}
            else value
        )
        values = [value for value in series if value is not None and value is not pd.NA]
        families: set[str] = set()
        for value in values:
            if isinstance(value, (bool, np.bool_)):
                families.add("bool")
            elif isinstance(value, (int, float, np.integer, np.floating)):
                families.add("number")
            elif isinstance(value, str):
                families.add("text")
            elif isinstance(value, (pd.Timestamp, datetime)):
                families.add("datetime")
            else:
                families.add("other")
        if len(families) > 1 or "other" in families:
            series = series.map(
                lambda value: None
                if value is None or value is pd.NA
                else (
                    canonical_json(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
            )
        normalized[column] = series
    return normalized


def fetch(name: str, **kwargs: Any) -> pd.DataFrame:
    symbols = kwargs.get("symbol")
    if _CHECKPOINT_DIR is None or not isinstance(symbols, list) or not symbols:
        return _fetch_once(name, **kwargs)
    frames: list[pd.DataFrame] = []
    stable_kwargs = {key: value for key, value in kwargs.items() if key != "symbol"}
    batch_size = 1 if name in PER_SYMBOL_CHECKPOINT_APIS else _CHECKPOINT_BATCH_SIZE
    for offset in range(0, len(symbols), batch_size):
        batch = [str(value) for value in symbols[offset : offset + batch_size]]
        key = _checkpoint_key(name, batch, stable_kwargs)
        path = _CHECKPOINT_DIR / f"{name}-{offset:06d}-{key}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
            continue
        request_symbol: str | list[str] = batch[0] if name in PER_SYMBOL_CHECKPOINT_APIS else batch
        frame = _fetch_once(name, **{**stable_kwargs, "symbol": request_symbol})
        frame = _checkpoint_parquet_frame(frame)
        temporary = path.with_suffix(".tmp")
        try:
            frame.to_parquet(temporary, index=False)
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        # Return the same inferred dtypes on a fresh fetch and a cached replay.
        frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def require_columns(frame: pd.DataFrame, columns: Iterable[str], source: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise PandaDataError(f"{source} missing required columns: {', '.join(missing)}")


def _json_default(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"{type(value).__name__} 类型的对象无法序列化为 JSON")


def canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        default=_json_default,
    )


def build_production_frame(
    *,
    build_id: str,
    build_name: str,
    trade_date: str,
    records: Iterable[Mapping[str, Any]],
    data_version: str,
    schema_version: str = SCHEMA_VERSION,
    run_id: str | None = None,
) -> pd.DataFrame:
    update_time = datetime.now(timezone.utc).isoformat()
    current_run_id = run_id or f"{build_id}-{trade_date}-{uuid4().hex[:12]}"
    rows: list[dict[str, Any]] = []
    for record in records:
        payload = record.get("payload", {})
        rows.append(
            {
                "trade_date": trade_date,
                "build_id": build_id,
                "build_name": build_name,
                "target_id": str(record["target_id"]),
                "result_type": str(record["result_type"]),
                "result_value": record.get("result_value"),
                "result_json": canonical_json(payload),
                "source_data_date": record.get("source_data_date"),
                "data_version": data_version,
                "update_time": update_time,
                "schema_version": schema_version,
                "run_id": current_run_id,
                "coverage_status": record.get("coverage_status", "complete"),
                "actual_source_date": record.get(
                    "actual_source_date", record.get("source_data_date")
                ),
            }
        )
    frame = pd.DataFrame(rows)
    required = [
        "trade_date",
        "build_id",
        "build_name",
        "target_id",
        "result_type",
        "result_value",
        "result_json",
        "source_data_date",
        "data_version",
        "update_time",
        "schema_version",
        "run_id",
        "coverage_status",
        "actual_source_date",
    ]
    if frame.empty:
        return pd.DataFrame(columns=required)
    if frame[required].isna().any().any():
        missing = frame.columns[frame.isna().any()].tolist()
        raise PandaDataError(f"生产行的必需字段存在空值：{missing}")
    if frame.duplicated(PRODUCTION_KEY).any():
        raise PandaDataError(f"生产主键重复：{PRODUCTION_KEY}")
    for value in frame["result_json"]:
        json.loads(value)
    return frame[required]


def _upgrade_legacy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    upgraded = frame.copy()
    if "schema_version" not in upgraded:
        upgraded["schema_version"] = "1.0.0"
    if "run_id" not in upgraded:
        upgraded["run_id"] = "legacy"
    if "coverage_status" not in upgraded:
        upgraded["coverage_status"] = "legacy"
    if "actual_source_date" not in upgraded:
        upgraded["actual_source_date"] = upgraded.get("source_data_date")
    return upgraded


def write_production(
    frame: pd.DataFrame, path: str | Path, *, upsert: bool = True
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    final_frame = frame.copy()
    if upsert and output.exists():
        existing = _upgrade_legacy_frame(pd.read_parquet(output))
        for column in final_frame.columns:
            if column not in existing:
                existing[column] = pd.NA
        for column in existing.columns:
            if column not in final_frame:
                final_frame[column] = pd.NA
        # A production run is a complete snapshot for each trade_date + build_id
        # partition.  Replace those partitions wholesale so recovered APIs do not
        # leave stale coverage gaps or vanished candidates behind.
        partitions = final_frame[["trade_date", "build_id"]].drop_duplicates()
        partition_keys = {
            (str(row["trade_date"]), str(row["build_id"]))
            for _, row in partitions.iterrows()
        }
        keep = ~existing.apply(
            lambda row: (str(row["trade_date"]), str(row["build_id"]))
            in partition_keys,
            axis=1,
        )
        final_frame = pd.concat(
            [existing.loc[keep, final_frame.columns], final_frame],
            ignore_index=True,
            sort=False,
        )
    if final_frame.duplicated(PRODUCTION_KEY).any():
        raise PandaDataError(f"生产主键重复：{PRODUCTION_KEY}")
    final_frame = final_frame.sort_values(PRODUCTION_KEY).reset_index(drop=True)
    for value in final_frame["result_json"]:
        json.loads(value)
    temporary = output.with_suffix(output.suffix + ".tmp")
    final_frame.to_parquet(temporary, index=False)
    temporary.replace(output)
    return output


def inspect_production(
    path: str | Path, *, expected_data_version: str
) -> dict[str, Any]:
    """Validate the production artifact without triggering a Panda query."""
    source = Path(path)
    if not source.exists():
        return {
            "status": "missing_artifact",
            "path": str(source.resolve()),
            "expected_data_version": expected_data_version,
            "row_count": 0,
        }
    try:
        frame = _upgrade_legacy_frame(pd.read_parquet(source))
    except Exception as exc:
        return {
            "status": "invalid_artifact",
            "path": str(source.resolve()),
            "expected_data_version": expected_data_version,
            "error_type": type(exc).__name__,
        }
    required = {
        "trade_date",
        "build_id",
        "build_name",
        "target_id",
        "result_type",
        "result_value",
        "result_json",
        "data_version",
        "update_time",
    }
    missing = sorted(required - set(frame.columns))
    invalid_json = 0
    if "result_json" in frame:
        for value in frame["result_json"].dropna():
            try:
                json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                invalid_json += 1
    duplicate_keys = (
        int(frame.duplicated(PRODUCTION_KEY).sum())
        if all(column in frame for column in PRODUCTION_KEY)
        else None
    )
    current = (
        frame.loc[frame["data_version"].astype(str) == expected_data_version]
        if "data_version" in frame
        else frame.iloc[0:0]
    )
    scope_types: set[str] = set()
    if not current.empty and "result_json" in current:
        for value in current["result_json"].dropna():
            try:
                payload = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            scope = payload.get("scan_scope") if isinstance(payload, Mapping) else None
            if isinstance(scope, Mapping) and scope.get("type"):
                scope_types.add(str(scope["type"]))
    status = "current"
    if missing or invalid_json or duplicate_keys:
        status = "invalid_artifact"
    elif current.empty:
        status = "stale_artifact"
    elif "all_a_share" not in scope_types:
        status = "partial_artifact"
    return {
        "status": status,
        "path": str(source.resolve()),
        "expected_data_version": expected_data_version,
        "row_count": len(frame),
        "current_row_count": len(current),
        "trade_dates": sorted(frame.get("trade_date", pd.Series(dtype=str)).astype(str).unique().tolist()),
        "data_versions": sorted(frame.get("data_version", pd.Series(dtype=str)).astype(str).unique().tolist()),
        "scope_types": sorted(scope_types),
        "missing_columns": missing,
        "duplicate_keys": duplicate_keys,
        "invalid_json": invalid_json,
    }
