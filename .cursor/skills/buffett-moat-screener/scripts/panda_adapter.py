from __future__ import annotations

import importlib.metadata
import json
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

import numpy as np
import pandas as pd


SCHEMA_VERSION = "3.0.0"
PRODUCTION_KEY = ["trade_date", "build_id", "target_id", "result_type"]
_PROCESS_CREDENTIALS: tuple[str, str, str | None] | None = None
USERNAME_ENV = "PANDA_DATA_USERNAME"
PASSWORD_ENV = "PANDA_DATA_PASSWORD"
BASE_URL_ENV = "PANDA_DATA_BASE_URL"


class PandaDataError(RuntimeError):
    """Panda 数据边界的基础异常。"""


class PandaAuthenticationError(PandaDataError):
    """Panda 凭证不可用或被拒绝时抛出。"""


class PandaApiUnavailableError(PandaDataError):
    """已安装的开发包未提供必需接口时抛出。"""


def _request_timeout_seconds() -> float:
    try:
        value = float(os.environ.get("PANDA_DATA_REQUEST_TIMEOUT", "45"))
    except (TypeError, ValueError):
        value = 45.0
    return max(1.0, min(value, 300.0))


def _call_with_timeout(
    api: Any, kwargs: dict[str, Any], name: str, timeout_seconds: float | None = None
) -> Any:
    """Prevent a hung SDK read from blocking a full-A run indefinitely."""
    result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result.put((True, api(**kwargs)))
        except BaseException as exc:
            result.put((False, exc))

    thread = threading.Thread(target=worker, name=f"panda-{name}", daemon=True)
    thread.start()
    timeout = _request_timeout_seconds() if timeout_seconds is None else max(1.0, float(timeout_seconds))
    thread.join(timeout)
    if thread.is_alive():
        raise PandaDataError(f"{name} request timed out")
    ok, value = result.get_nowait()
    if not ok:
        raise value
    return value


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


def consume_environment_credentials() -> tuple[str, str, str | None]:
    """Move credentials from the process environment into private memory."""
    username = os.environ.get(USERNAME_ENV)
    password = os.environ.get(PASSWORD_ENV)
    base_url = os.environ.get(BASE_URL_ENV)
    for name in (USERNAME_ENV, PASSWORD_ENV, BASE_URL_ENV):
        os.environ.pop(name, None)
    if not username or not password:
        raise PandaAuthenticationError(
            f"请通过 {USERNAME_ENV} 和 {PASSWORD_ENV} 提供 Panda 凭证"
        )
    configure_process_credentials(username, password, base_url or None)
    return username, password, base_url or None


def clear_process_credentials() -> None:
    global _PROCESS_CREDENTIALS
    _PROCESS_CREDENTIALS = None
    try:
        from panda_data import auth_manager

        auth_manager.clear_auth()
    except (ImportError, AttributeError):
        pass


def sdk_version() -> str:
    try:
        return importlib.metadata.version("panda-data")
    except importlib.metadata.PackageNotFoundError as exc:
        raise PandaApiUnavailableError("尚未安装 panda_data") from exc


def get_api(name: str):
    import panda_data

    api = getattr(panda_data, name, None)
    if callable(api):
        return api

    # panda_data 0.0.12 文档包含这些接口，但缺少两个顶层导出。
    from panda_data.readers import market_reference_reader

    api = getattr(market_reference_reader, name, None)
    if callable(api):
        return api
    raise PandaApiUnavailableError(
        f"panda_data {sdk_version()} 未提供必需接口 {name}"
    )


def ensure_authenticated() -> None:
    import panda_data
    if _PROCESS_CREDENTIALS is None:
        consume_environment_credentials()
    username, password, base_url = _PROCESS_CREDENTIALS

    kwargs: dict[str, Any] = {"username": username, "password": password}
    if base_url:
        kwargs["base_url"] = base_url
    try:
        # panda_data 0.0.12 默认持久化加密凭证；本项目要求凭证与令牌仅保留在进程内。
        # 较新版本移除了 auth_manager，此处兼容处理：能拿到就临时禁用持久化，否则
        # 直接走 init_token（SDK 自身的 user.json 由 SDK 目录管理，与本 repo 无关）。
        try:
            from panda_data import auth_manager

            persist_credentials = auth_manager._persist_credentials
            auth_manager._persist_credentials = lambda *args, **kwargs: None
        except (ImportError, AttributeError):
            auth_manager = None
            persist_credentials = None
        try:
            panda_data.init_token(**kwargs)
        finally:
            if auth_manager is not None and persist_credentials is not None:
                auth_manager._persist_credentials = persist_credentials
        try:
            from panda_data.client import init as client_init

            client_init(**kwargs)
        except Exception:
            pass
    except Exception as exc:  # 不同版本的开发包使用不同异常类型。
        raise PandaAuthenticationError(
            f"panda_data 认证失败（{type(exc).__name__}）"
        ) from exc


def fetch(name: str, **kwargs: Any) -> pd.DataFrame:
    ensure_authenticated()
    result = None
    retry_delays = kwargs.pop("_retry_delays", None)
    timeout_seconds = kwargs.pop("_timeout_seconds", None)
    if retry_delays is None:
        retry_delays = (15, 30, 60, 120, None)
    for attempt, delay in enumerate(retry_delays):
        try:
            result = _call_with_timeout(get_api(name), kwargs, name, timeout_seconds)
            break
        except Exception as exc:
            message = str(exc)
            rate_limited = "500010" in message or "请求次数超限" in message
            if rate_limited and delay is not None:
                time.sleep(delay)
                continue
            if not rate_limited and isinstance(exc, PandaDataError):
                raise
            if rate_limited:
                raise PandaDataError(f"{name} failed after rate-limit retries") from exc
            raise PandaDataError(f"{name} failed: {exc}") from exc
    if result is None:
        return pd.DataFrame()
    if not isinstance(result, pd.DataFrame):
        try:
            result = pd.DataFrame(result)
        except Exception as exc:
            raise PandaDataError(f"{name} returned unsupported type {type(result)!r}") from exc
    return result.copy()


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
                "trade_date": str(record.get("trade_date", trade_date)),
                "build_id": build_id,
                "build_name": build_name,
                "target_id": str(record["target_id"]),
                "result_type": str(record["result_type"]),
                "result_value": str(record.get("result_value")),
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
    frame: pd.DataFrame,
    path: str | Path,
    *,
    upsert: bool = True,
    replace_all: bool = False,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    final_frame = frame.copy()
    if upsert and not replace_all and output.exists():
        existing = _upgrade_legacy_frame(pd.read_parquet(output))
        for column in final_frame.columns:
            if column not in existing:
                existing[column] = pd.NA
        for column in existing.columns:
            if column not in final_frame:
                final_frame[column] = pd.NA
        final_frame = pd.concat(
            [existing[final_frame.columns], final_frame], ignore_index=True, sort=False
        )
        final_frame = final_frame.drop_duplicates(PRODUCTION_KEY, keep="last")
    if final_frame.duplicated(PRODUCTION_KEY).any():
        raise PandaDataError(f"生产主键重复：{PRODUCTION_KEY}")
    if not replace_all:
        final_frame = final_frame.sort_values(PRODUCTION_KEY).reset_index(drop=True)
    else:
        final_frame = final_frame.reset_index(drop=True)
    for value in final_frame["result_json"]:
        json.loads(value)
    temporary = output.with_suffix(output.suffix + ".tmp")
    final_frame.to_parquet(temporary, index=False)
    temporary.replace(output)
    return output


def write_versioned_production(
    frame: pd.DataFrame, path: str | Path, data_version: str
) -> Path:
    """Rebuild on the first new-version write, then upsert only that version."""
    output = Path(path)
    replace_all = False
    if output.exists():
        existing = pd.read_parquet(output)
        replace_all = (
            "data_version" not in existing
            or set(existing["data_version"].dropna().astype(str)) != {str(data_version)}
        )
    return write_production(
        frame,
        output,
        upsert=not replace_all,
        replace_all=replace_all,
    )
