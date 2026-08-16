"""Category-scoped Panda capability checks and auditable gap records."""

from __future__ import annotations

from typing import Any, Callable
import re
import time

import pandas as pd

_DEFAULT_MAX_ATTEMPTS = 2

try:
    from .evidence import (
        _attach_event_metadata,
        _event_identity,
        _evidence_matrix,
        _record_dates,
    )
    from .panda_adapter import PandaAuthenticationError, PandaDataError
except ImportError:
    from evidence import (
        _attach_event_metadata,
        _event_identity,
        _evidence_matrix,
        _record_dates,
    )
    from panda_adapter import PandaAuthenticationError, PandaDataError


def _failure_classification(exc: PandaDataError) -> str:
    message = str(exc).lower()
    if re.search(r"限额|quota|rate.?limit|套餐", message):
        return "quota_or_rate_limit"
    if re.search(r"transient_transport|timeout|timed out|connection|network|temporar", message):
        return "transient_transport"
    if re.search(r"未上线|not implemented|not provide|unavailable", message):
        return "api_unavailable"
    return "data_or_service_error"


def _attempt(callable_: Callable[..., Any], *args: Any, max_attempts: int = 2, **kwargs: Any) -> tuple[Any, int]:
    for attempt in range(1, max_attempts + 1):
        try:
            return callable_(*args, **kwargs), attempt
        except PandaAuthenticationError:
            raise
        except PandaDataError as exc:
            retryable = _failure_classification(exc) in {"quota_or_rate_limit", "transient_transport"}
            if not retryable or attempt == max_attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 4))
    raise PandaDataError("capability retry exhausted")


def configure_capability_retries(max_attempts: int) -> None:
    global _DEFAULT_MAX_ATTEMPTS
    _DEFAULT_MAX_ATTEMPTS = int(max_attempts)


def fetch_with_capability(
    capabilities: dict[str, dict[str, Any]],
    fetcher: Callable[..., pd.DataFrame],
    name: str,
    max_attempts: int | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    try:
        selected_attempts = _DEFAULT_MAX_ATTEMPTS if max_attempts is None else max_attempts
        frame, attempts = _attempt(fetcher, name, max_attempts=selected_attempts, **kwargs)
    except PandaAuthenticationError:
        raise
    except PandaDataError as exc:
        capabilities[name] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "failure_class": _failure_classification(exc),
            "attempts": selected_attempts,
        }
        return pd.DataFrame()
    capabilities[name] = {"status": "available", "row_count": len(frame), "attempts": attempts}
    return frame


def evidence_with_capability(
    capabilities: dict[str, dict[str, Any]],
    name: str,
    function: Callable[..., Any],
    *args: Any,
    max_attempts: int | None = None,
) -> Any:
    try:
        selected_attempts = _DEFAULT_MAX_ATTEMPTS if max_attempts is None else max_attempts
        result, attempts = _attempt(function, *args, max_attempts=selected_attempts)
    except PandaAuthenticationError:
        raise
    except PandaDataError as exc:
        capabilities[name] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "failure_class": _failure_classification(exc),
            "attempts": selected_attempts,
        }
        return {}
    capabilities[name] = {"status": "available", "attempts": attempts}
    return result


def build_coverage_gap_records(
    capabilities: dict[str, dict[str, Any]], as_of: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for api_name, capability in capabilities.items():
        if capability["status"] != "unavailable":
            continue
        event_id, revision_id = _event_identity(
            "coverage_gap", None, [api_name], [capability["error_type"], as_of]
        )
        completeness = _evidence_matrix(
            {"api_available": (True, False, f"Panda API {api_name} 当前不可用")}
        )
        payload = {
            "api": api_name,
            "failure_class": capability.get("failure_class"),
            "attempts": capability.get("attempts"),
            "discovery_status": "coverage_gap",
            "underwriting_status": "underwriting_incomplete",
            "access_assumption": None,
            "knowledge_cutoff": as_of,
            "klarman_gates": {"matrix": {}, "missing_required": ["api_available"]},
            "deal_terms": {},
            "valuation": {},
            "downside_case": {},
            "risk_budget_inputs": {},
        }
        _attach_event_metadata(
            payload,
            event_id=event_id,
            revision_id=revision_id,
            event_state="source_unavailable",
            lifecycle=[{"stage": "capability_checked", "date": as_of}],
            completeness=completeness,
        )
        records.append(
            {
                "target_id": event_id,
                "result_type": "coverage_gap",
                "result_value": "insufficient_evidence",
                "payload": payload,
                **_record_dates(
                    source_data_date=as_of,
                    actual_source_date=as_of,
                    completeness=completeness,
                ),
            }
        )
    return records
