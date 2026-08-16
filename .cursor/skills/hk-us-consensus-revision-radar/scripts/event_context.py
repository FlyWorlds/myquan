"""Shared event normalization and reference-date utilities."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
import time
from typing import Callable

import pandas as pd

from scripts.auth_session import AuthenticationError


COMMON_EVENT_FIELDS = [
    "info_date",
    "symbol",
    "start_date",
    "end_date",
    "event_type",
    "event",
    "is_estimated",
    "fiscal_quarter",
]
DIVIDEND_FIELDS = [
    "publish_date",
    "symbol",
    "excute_date",
    "event_type",
    "number",
    "currency",
    "event",
]
EVENT_APIS = {
    "hk": {
        "dividend": ("get_stock_dividend_event", DIVIDEND_FIELDS),
        "capital_market": ("get_stock_market_event", COMMON_EVENT_FIELDS),
        "meeting": ("get_stock_meeting_event", COMMON_EVENT_FIELDS),
        "financial": ("get_stock_financial_event", COMMON_EVENT_FIELDS),
        "ir": ("get_stock_ir_event", COMMON_EVENT_FIELDS),
    },
    "us": {
        "dividend": ("get_stock_dividend_activity", DIVIDEND_FIELDS),
        "capital_market": ("get_stock_market_activity", COMMON_EVENT_FIELDS),
        "meeting": ("get_stock_meeting_activity", COMMON_EVENT_FIELDS),
        "financial": ("get_stock_financial_activity", COMMON_EVENT_FIELDS),
        "ir": ("get_stock_ir_activity", COMMON_EVENT_FIELDS),
    },
}


EVENT_COLUMNS: tuple[str, ...] = (
    "market",
    "symbol",
    "category",
    "event_type",
    "title",
    "publish_date",
    "start_date",
    "end_date",
    "is_estimated",
    "fiscal_quarter",
    "source_interfaces",
    "validation_status",
    "duplicate_count",
    "time_status",
)


@dataclass
class EventBundle:
    events: pd.DataFrame
    diagnostics: dict[str, object]
    source_interfaces: list[dict[str, str]]


def collect_market_events(
    panda_module,
    *,
    market: str,
    symbols: list[str],
    reference_date: str | None,
    past_days: int = 30,
    future_days: int = 30,
    discovery_days: int = 730,
    progress_callback: Callable[[str], None] | None = None,
) -> EventBundle:
    reference = _parse_date(reference_date)
    if reference is None:
        diagnostics = {
            "status": "unavailable",
            "event_reference_date": None,
            "event_window_start": None,
            "event_window_end": None,
            "announcement_query_start": None,
            "announcement_query_end": None,
            "event_past_days": past_days,
            "event_future_days": future_days,
            "event_discovery_days": discovery_days,
            "requested_symbol_count": len(set(symbols)),
            "returned_symbol_count": 0,
            "symbols_with_display_events": 0,
            "symbols_without_display_events": len(set(symbols)),
            "coverage_incomplete_symbol_count": 0,
            "returned_rows": 0,
            "display_event_rows": 0,
            "invalid_rows": 0,
            "unexpected_symbol_rows": 0,
            "outside_display_window_rows": 0,
            "exact_duplicate_rows": 0,
            "conflict_group_count": 0,
            "interface_diagnostics": _not_called_interface_diagnostics(market),
            "discovery_limitation": "PandaData事件接口按公告日期筛选；早于公告发现窗口发布的窗口内事件可能无法发现。",
        }
        return EventBundle(pd.DataFrame(columns=EVENT_COLUMNS), diagnostics, [])

    reference_text = reference.strftime("%Y%m%d")
    display_start = reference - timedelta(days=past_days)
    display_end = reference + timedelta(days=future_days)
    announcement_start = reference - timedelta(days=discovery_days)
    announcement_end = reference + timedelta(days=future_days)
    if not symbols:
        diagnostics = {
            "status": "empty",
            "event_reference_date": reference_text,
            "event_window_start": display_start.strftime("%Y%m%d"),
            "event_window_end": display_end.strftime("%Y%m%d"),
            "announcement_query_start": announcement_start.strftime("%Y%m%d"),
            "announcement_query_end": announcement_end.strftime("%Y%m%d"),
            "event_past_days": past_days,
            "event_future_days": future_days,
            "event_discovery_days": discovery_days,
            "requested_symbol_count": 0,
            "returned_symbol_count": 0,
            "symbols_with_display_events": 0,
            "symbols_without_display_events": 0,
            "coverage_incomplete_symbol_count": 0,
            "returned_rows": 0,
            "display_event_rows": 0,
            "invalid_rows": 0,
            "unexpected_symbol_rows": 0,
            "outside_display_window_rows": 0,
            "exact_duplicate_rows": 0,
            "conflict_group_count": 0,
            "interface_diagnostics": _not_called_interface_diagnostics(market),
            "discovery_limitation": "PandaData事件接口按公告日期筛选；早于公告发现窗口发布的窗口内事件可能无法发现。",
        }
        return EventBundle(pd.DataFrame(columns=EVENT_COLUMNS), diagnostics, [])
    diagnostics = {
        "status": "empty",
        "event_reference_date": reference_text,
        "event_window_start": display_start.strftime("%Y%m%d"),
        "event_window_end": display_end.strftime("%Y%m%d"),
        "announcement_query_start": announcement_start.strftime("%Y%m%d"),
        "announcement_query_end": announcement_end.strftime("%Y%m%d"),
        "event_past_days": past_days,
        "event_future_days": future_days,
        "event_discovery_days": discovery_days,
        "requested_symbol_count": len(set(symbols)),
        "returned_symbol_count": 0,
        "symbols_with_display_events": 0,
        "symbols_without_display_events": len(set(symbols)),
        "coverage_incomplete_symbol_count": 0,
        "returned_rows": 0,
        "display_event_rows": 0,
        "invalid_rows": 0,
        "unexpected_symbol_rows": 0,
        "outside_display_window_rows": 0,
        "exact_duplicate_rows": 0,
        "conflict_group_count": 0,
        "interface_diagnostics": [],
        "discovery_limitation": "PandaData事件接口按公告日期筛选；早于公告发现窗口发布的窗口内事件可能无法发现。",
    }
    sources: list[dict[str, str]] = []
    normalized_frames: list[pd.DataFrame] = []
    returned_symbols: set[str] = set()
    display_symbols: set[str] = set()
    incomplete_symbols: set[str] = set()
    for category, (interface, fields) in EVENT_APIS[market].items():
        frames: list[pd.DataFrame] = []
        attempts = 0
        successful_batches = 0
        last_error: Exception | None = None
        batch_count = (len(symbols) + 199) // 200
        try:
            endpoint = getattr(panda_module, interface)
        except AuthenticationError:
            raise
        except Exception as exc:
            diagnostics["interface_diagnostics"].append({
                "interface": interface,
                "category": category,
                "status": "failed",
                "attempts": 0,
                "batches": batch_count,
                "successful_batches": 0,
                "returned_rows": 0,
                "error_type": type(exc).__name__,
                "error_message": _sanitize_error(exc),
                "error_status_code": _extract_status_code(exc),
            })
            incomplete_symbols.update(symbols)
            if progress_callback is not None:
                progress_callback(interface)
            continue
        for offset in range(0, len(symbols), 200):
            batch = symbols[offset:offset + 200]
            frame = None
            for retry_index in range(3):
                attempts += 1
                try:
                    frame = endpoint(
                        symbol=batch,
                        fields=fields,
                        start_date=announcement_start.strftime("%Y%m%d"),
                        end_date=announcement_end.strftime("%Y%m%d"),
                    )
                    break
                except AuthenticationError:
                    raise
                except Exception as exc:
                    if not _is_retryable_exception(exc) or retry_index == 2:
                        last_error = exc
                        break
                    time.sleep(0.25 * (2 ** retry_index))
            if frame is not None:
                try:
                    result_frame = (
                        frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
                    )
                except Exception as exc:
                    last_error = exc
                    incomplete_symbols.update(batch)
                else:
                    frames.append(result_frame)
                    successful_batches += 1
            else:
                incomplete_symbols.update(batch)
        source_frame = (
            pd.concat(frames, ignore_index=True)
            if frames else pd.DataFrame()
        )
        normalized, counters = normalize_event_frame(
            source_frame,
            market=market,
            category=category,
            interface=interface,
            requested_symbols=set(symbols),
            reference_date=reference_text,
            past_days=past_days,
            future_days=future_days,
        )
        normalized_frames.append(normalized)
        diagnostics["returned_rows"] += len(source_frame)
        diagnostics["display_event_rows"] += counters["display_rows"]
        diagnostics["invalid_rows"] += int(
            (normalized["validation_status"] != "valid").sum()
        )
        diagnostics["unexpected_symbol_rows"] += counters["unexpected_symbol_rows"]
        diagnostics["outside_display_window_rows"] += counters["outside_display_window_rows"]
        if "symbol" in source_frame:
            returned_symbols.update(
                symbol for symbol in source_frame["symbol"].map(_text)
                if symbol in set(symbols)
            )
        display_symbols.update(normalized.loc[
            normalized["validation_status"] == "valid", "symbol"
        ].dropna())
        if last_error is not None and successful_batches == 0:
            interface_status = "failed"
        elif last_error is not None:
            interface_status = "partial"
        elif len(source_frame):
            interface_status = "success"
        else:
            interface_status = "empty"
        diagnostics["interface_diagnostics"].append({
            "interface": interface,
            "category": category,
            "status": interface_status,
            "attempts": attempts,
            "batches": batch_count,
            "successful_batches": successful_batches,
            "returned_rows": len(source_frame),
            "error_type": type(last_error).__name__ if last_error else None,
            "error_message": _sanitize_error(last_error) if last_error else None,
            "error_status_code": _extract_status_code(last_error),
        })
        sources.append({"category": category, "interface": interface})
        if progress_callback is not None:
            progress_callback(interface)

    events = (
        pd.concat(normalized_frames, ignore_index=True)
        if normalized_frames else pd.DataFrame(columns=EVENT_COLUMNS)
    )
    events, exact_duplicate_rows = _deduplicate_events(events)
    diagnostics["exact_duplicate_rows"] = exact_duplicate_rows
    diagnostics["conflict_group_count"] = _conflict_group_count(events)
    diagnostics["display_event_rows"] = int(
        (events["validation_status"] == "valid").sum()
    )
    display_symbols = set(events.loc[
        events["validation_status"] == "valid", "symbol"
    ].dropna())
    diagnostics["returned_symbol_count"] = len(returned_symbols)
    diagnostics["symbols_with_display_events"] = len(display_symbols)
    diagnostics["symbols_without_display_events"] = len(set(symbols) - display_symbols)
    diagnostics["coverage_incomplete_symbol_count"] = len(incomplete_symbols)
    diagnostics["status"] = _reduce_event_bundle_status(
        diagnostics["interface_diagnostics"],
        display_event_rows=diagnostics["display_event_rows"],
    )
    return EventBundle(events, diagnostics, sources)


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    text = str(value).strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def resolve_event_reference_date(metrics: pd.DataFrame) -> str | None:
    if metrics.empty or "price_date" not in metrics:
        return None
    parsed = metrics["price_date"].map(_parse_date)
    if "price_valid" in metrics:
        valid_prices = metrics["price_valid"].fillna(False).astype(bool)
    else:
        close = pd.to_numeric(
            metrics.get("close", pd.Series(pd.NA, index=metrics.index)),
            errors="coerce",
        )
        valid_prices = parsed.notna() & close.gt(0).fillna(False)
    core = metrics.get(
        "universe_eligible", pd.Series(False, index=metrics.index)
    ).fillna(False).astype(bool)
    candidates = parsed.loc[valid_prices & core].dropna()
    if candidates.empty:
        candidates = parsed.loc[valid_prices].dropna()
    return max(candidates).strftime("%Y%m%d") if not candidates.empty else None


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: object) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _date_text(value: object, parsed: date | None) -> str | None:
    if parsed is not None:
        return parsed.strftime("%Y%m%d")
    return _text(value)


def _normalize_estimate(value: object) -> object:
    if _is_missing(value):
        return pd.NA
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return value


def _raw_date_is_invalid(value: object) -> bool:
    return not _is_missing(value) and _parse_date(value) is None


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    status_code = str(_extract_status_code(exc) or "")
    return bool(
        re.search(r"^(429|5\d\d)$", status_code)
        or re.search(r"\b(429|5\d\d)\b", str(exc))
    )


def _extract_status_code(exc: Exception | None) -> int | None:
    if exc is None:
        return None
    raw = getattr(exc, "status_code", None)
    if isinstance(raw, int):
        return raw
    if raw is not None:
        match = re.search(r"\b(\d{3})\b", str(raw))
        if match:
            return int(match.group(1))
    match = re.search(r"\b(4\d\d|5\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def _sanitize_error(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    status_code = _extract_status_code(exc)
    if isinstance(exc, TimeoutError):
        return "Request timed out"
    if isinstance(exc, ConnectionError):
        return "Connection failed"
    if isinstance(exc, AttributeError):
        return "Interface unavailable"
    if isinstance(exc, ValueError):
        return "Invalid interface response or parameters"
    if status_code == 429:
        return "Rate limited by upstream service"
    if status_code is not None and 500 <= status_code <= 599:
        return "Upstream service error"
    if status_code is not None and 400 <= status_code <= 499:
        return "Upstream request rejected"
    return "Interface request failed"


def _not_called_interface_diagnostics(market: str) -> list[dict[str, object]]:
    return [
        {
            "interface": interface,
            "category": category,
            "status": "not_called",
            "attempts": 0,
            "batches": 0,
            "successful_batches": 0,
            "returned_rows": 0,
            "error_type": None,
            "error_message": None,
            "error_status_code": None,
        }
        for category, (interface, _) in EVENT_APIS[market].items()
    ]


def _reduce_event_bundle_status(
    interface_diagnostics: list[dict[str, object]],
    *,
    display_event_rows: int,
) -> str:
    statuses = [str(item.get("status")) for item in interface_diagnostics]
    if statuses and all(status == "failed" for status in statuses):
        return "unavailable"
    if any(status == "partial" for status in statuses):
        return "partial"
    if any(status == "failed" for status in statuses):
        return "partial"
    if display_event_rows > 0:
        return "available"
    return "empty"


def _deduplicate_events(events: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if events.empty:
        return events.copy(), 0
    keys = [
        "market", "symbol", "category", "event_type", "start_date", "end_date", "title",
    ]
    rows: list[dict[str, object]] = []
    duplicate_rows = 0
    for _, group in events.groupby(keys, dropna=False, sort=False):
        row = group.iloc[0].to_dict()
        interfaces = sorted({
            interface
            for value in group["source_interfaces"]
            for interface in _source_interface_list(value)
        })
        row["source_interfaces"] = interfaces
        row["duplicate_count"] = len(group)
        duplicate_rows += len(group) - 1
        rows.append(row)
    result = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    result = result.sort_values(
        ["symbol", "start_date", "end_date", "category", "event_type", "title"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    return result, duplicate_rows


def _source_interface_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [interface for interface in value if isinstance(interface, str)]
    return [value] if isinstance(value, str) else []


def _conflict_group_count(events: pd.DataFrame) -> int:
    valid = events.loc[events["validation_status"] == "valid"].copy()
    if valid.empty:
        return 0
    valid["_start"] = valid["start_date"].map(_parse_date)
    valid = valid[valid["_start"].notna()]
    conflicts = 0
    for _, group in valid.groupby(["market", "symbol", "event_type"], dropna=False):
        records = list(group[["_start", "title"]].itertuples(index=False, name=None))
        neighbors = [set() for _ in records]
        for index, (first_date, first_title) in enumerate(records):
            for other_index, (second_date, second_title) in enumerate(
                records[index + 1:], start=index + 1
            ):
                if (
                    first_title != second_title
                    and abs((first_date - second_date).days) <= 1
                ):
                    neighbors[index].add(other_index)
                    neighbors[other_index].add(index)
        seen: set[int] = set()
        for index, linked in enumerate(neighbors):
            if index in seen or not linked:
                continue
            conflicts += 1
            pending = [index]
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                pending.extend(neighbors[current] - seen)
    return conflicts


def normalize_event_frame(
    frame: pd.DataFrame,
    *,
    market: str,
    category: str,
    interface: str,
    requested_symbols: set[str],
    reference_date: str,
    past_days: int,
    future_days: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    reference = _parse_date(reference_date)
    display_start = reference - timedelta(days=past_days) if reference else None
    display_end = reference + timedelta(days=future_days) if reference else None
    is_dividend = category.lower() == "dividend"
    rows: list[dict[str, object]] = []
    counters = {
        "input_rows": len(frame),
        "display_rows": 0,
        "outside_display_window_rows": 0,
        "invalid_date_rows": 0,
        "missing_key_field_rows": 0,
        "unexpected_symbol_rows": 0,
    }

    for _, source in frame.iterrows():
        symbol = _text(source.get("symbol"))
        publish_raw = source.get("publish_date") if is_dividend else source.get("info_date")
        start_raw = source.get("excute_date") if is_dividend else source.get("start_date")
        end_raw = source.get("excute_date") if is_dividend else source.get("end_date")
        publish = _parse_date(publish_raw)
        start = _parse_date(start_raw)
        end = _parse_date(end_raw)

        title = (
            _text(source.get("title"))
            or _text(source.get("event"))
            or _text(source.get("event_type"))
            or "Unknown event"
        )
        has_missing_key_field = (
            not symbol or _is_missing(start_raw) or _is_missing(end_raw)
        )
        has_unexpected_symbol = bool(symbol) and symbol not in requested_symbols
        has_invalid_date = (
            _raw_date_is_invalid(publish_raw)
            or _raw_date_is_invalid(start_raw)
            or _raw_date_is_invalid(end_raw)
            or reference is None
            or (
                start is not None
                and end is not None
                and start > end
            )
        )

        if has_missing_key_field:
            counters["missing_key_field_rows"] += 1
        if has_unexpected_symbol:
            counters["unexpected_symbol_rows"] += 1
        if has_invalid_date:
            counters["invalid_date_rows"] += 1

        if has_missing_key_field:
            validation = "missing_key_field"
        elif has_unexpected_symbol:
            validation = "unexpected_symbol"
        elif has_invalid_date:
            validation = "invalid_date"
        else:
            validation = "valid"

        if validation != "valid":
            time_status = "invalid_date"
        elif start == end == reference:
            time_status = "today"
        elif start <= reference <= end:
            time_status = "ongoing"
        elif end < reference:
            time_status = "recent"
        else:
            time_status = "upcoming"

        normalized = {
            "market": market,
            "symbol": symbol,
            "category": category,
            "event_type": _text(source.get("event_type")),
            "title": title,
            "publish_date": _date_text(publish_raw, publish),
            "start_date": _date_text(start_raw, start),
            "end_date": _date_text(end_raw, end),
            "is_estimated": _normalize_estimate(source.get("is_estimated")),
            "fiscal_quarter": _text(source.get("fiscal_quarter")),
            "source_interfaces": [interface],
            "validation_status": validation,
            "duplicate_count": 1,
            "time_status": time_status,
        }

        if validation != "valid":
            rows.append(normalized)
            continue

        if end >= display_start and start <= display_end:
            counters["display_rows"] += 1
            rows.append(normalized)
        else:
            counters["outside_display_window_rows"] += 1

    result = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    return result, counters
