"""规范化 Panda 事件身份、市场、财务与审计证据。"""

from __future__ import annotations

try:
    from .core import (
        AUDIT_WARNING_PATTERN,
        Any,
        Iterable,
        Mapping,
        NET_PROFIT_FIELDS,
        NO_AUDIT_PATTERN,
        OPERATING_CASH_FIELDS,
        PandaDataError,
        TRADE_DIRECTIVE_PATTERN,
        datetime,
        fetch,
        hashlib,
        json,
        np,
        pd,
        re,
        timedelta,
    )
except ImportError:  # 支持直接执行脚本
    from core import (
        AUDIT_WARNING_PATTERN,
        Any,
        Iterable,
        Mapping,
        NET_PROFIT_FIELDS,
        NO_AUDIT_PATTERN,
        OPERATING_CASH_FIELDS,
        PandaDataError,
        TRADE_DIRECTIVE_PATTERN,
        datetime,
        fetch,
        hashlib,
        json,
        np,
        pd,
        re,
        timedelta,
    )
__all__ = ['_first_column', '_scalar', '_first_value', '_text', '_row_text', '_stable_id', '_date_token', '_max_date', '_event_identity', '_evidence_matrix', '_json_safe', '_attach_event_metadata', '_record_dates', '_assert_no_trade_directives', '_stock_name_map', '_map_text_to_symbol', '_market_evidence', '_latest_prices', '_trading_state_evidence', '_numeric', '_float_share_map', '_fundamental_checks', '_audit_evidence']

def _first_column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    return next((lowered[name.lower()] for name in names if name.lower() in lowered), None)

def _scalar(value: Any, default: Any = None) -> Any:
    return default if value is None or value is pd.NA or pd.isna(value) else value

def _first_value(*values: Any) -> Any:
    for value in values:
        cleaned = _scalar(value)
        if cleaned is not None and _text(cleaned).strip():
            return cleaned
    return None

def _text(value: Any) -> str:
    return str(_scalar(value, ""))

def _row_text(row: pd.Series, fields: Iterable[str]) -> str:
    return " ".join(_text(row.get(field)) for field in fields)

def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(_text(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"

def _date_token(value: Any) -> str | None:
    text = re.sub(r"\D", "", _text(value))[:8]
    if len(text) != 8:
        return None
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text

def _max_date(*values: Any, fallback: str) -> str:
    dates = [date_value for value in values if (date_value := _date_token(value))]
    return max(dates) if dates else fallback

def _event_identity(
    situation_type: str,
    symbol: str | None,
    identity_parts: Iterable[Any],
    revision_parts: Iterable[Any],
) -> tuple[str, str]:
    event_id = _stable_id(
        f"event-{situation_type}",
        symbol or "unmapped",
        *identity_parts,
    )
    revision_id = _stable_id(
        f"revision-{situation_type}",
        event_id,
        *revision_parts,
    )
    return event_id, revision_id

def _evidence_matrix(
    evidence: Mapping[str, tuple[bool, bool, str]],
) -> dict[str, Any]:
    matrix: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []
    present_count = 0
    for name, (required, present, note) in evidence.items():
        status = "present" if present else "missing"
        matrix[name] = {"required": required, "status": status, "note": note}
        present_count += int(present)
        if required and not present:
            missing_required.append(name)
    status = (
        "complete"
        if not missing_required
        else "partial"
        if present_count
        else "insufficient"
    )
    return {
        "status": status,
        "missing_required": missing_required,
        "matrix": matrix,
    }

def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value

def _attach_event_metadata(
    payload: dict[str, Any],
    *,
    event_id: str,
    revision_id: str,
    event_state: str,
    lifecycle: list[dict[str, Any]],
    completeness: dict[str, Any],
) -> None:
    payload.update(
        {
            "event_id": event_id,
            "event_revision_id": revision_id,
            "event_state": event_state,
            "event_lifecycle": lifecycle,
            "evidence_completeness": completeness,
        }
    )
    sanitized = _json_safe(payload)
    payload.clear()
    payload.update(sanitized)

def _record_dates(
    *, source_data_date: str, actual_source_date: str, completeness: Mapping[str, Any]
) -> dict[str, str]:
    return {
        "source_data_date": source_data_date,
        "actual_source_date": actual_source_date,
        "coverage_status": str(completeness["status"]),
    }

def _assert_no_trade_directives(records: Iterable[Mapping[str, Any]]) -> None:
    for record in records:
        text = json.dumps(record.get("payload", {}), ensure_ascii=False, default=str)
        if TRADE_DIRECTIVE_PATTERN.search(text):
            raise PandaDataError("记录载荷包含禁止使用的交易指令用语")

def _stock_name_map(detail: pd.DataFrame) -> dict[str, str]:
    if detail.empty:
        return {}
    symbol_column = _first_column(detail, ["symbol", "stock_symbol"])
    name_columns = [
        column
        for column in ["name", "short_name", "security_name", "company_name", "full_name"]
        if column in detail
    ]
    if symbol_column is None:
        return {}
    mapping: dict[str, str] = {}
    for _, row in detail.iterrows():
        symbol = _text(row.get(symbol_column)).replace(".SS", ".SH")
        if not symbol:
            continue
        for column in name_columns:
            name = _text(row.get(column)).strip()
            if len(name) >= 2:
                mapping[name] = symbol
    return mapping

def _map_text_to_symbol(text: str, name_map: Mapping[str, str]) -> tuple[str | None, str]:
    matches = sorted({symbol for name, symbol in name_map.items() if name in text})
    if len(matches) == 1:
        return matches[0], "unique_name_match"
    if len(matches) > 1:
        return None, "ambiguous_name_match"
    return None, "no_name_match"

def _market_evidence(
    symbols: list[str], start_date: str, as_of: str
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if not symbols:
        return {}, {}
    frame = fetch(
        "get_stock_daily",
        symbol=symbols,
        start_date=start_date,
        end_date=as_of,
        fields=["symbol", "date", "close", "trade_status", "amount", "volume"],
        st=True,
    )
    if frame.empty or not {"symbol", "date", "close"}.issubset(frame.columns):
        return {}, {}
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.replace(".SS", ".SH", regex=False)
    frame["date"] = frame["date"].astype(str)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "trade_status" in frame:
        frame["trade_status"] = pd.to_numeric(frame["trade_status"], errors="coerce")
    for column in ("amount", "volume"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values("date")
    prices: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    for symbol, subset in frame.groupby("symbol"):
        priced = subset.dropna(subset=["close"])
        if not priced.empty:
            row = priced.iloc[-1]
            amount_values = priced["amount"].dropna().tail(20) if "amount" in priced else pd.Series(dtype=float)
            volume_values = priced["volume"].dropna().tail(20) if "volume" in priced else pd.Series(dtype=float)
            prices[str(symbol)] = {
                "date": str(row["date"]),
                "close": float(row["close"]),
                "trade_status": None
                if "trade_status" not in row.index or pd.isna(row.get("trade_status"))
                else int(row["trade_status"]),
                "amount": None if "amount" not in row.index or pd.isna(row.get("amount")) else float(row["amount"]),
                "volume": None if "volume" not in row.index or pd.isna(row.get("volume")) else float(row["volume"]),
                "average_20d_amount": float(amount_values.mean()) if not amount_values.empty else None,
                "average_20d_volume": float(volume_values.mean()) if not volume_values.empty else None,
            }
        histories[str(symbol)] = [
            {
                "date": str(row["date"]),
                "trade_status": None
                if "trade_status" not in row.index or pd.isna(row.get("trade_status"))
                else int(row["trade_status"]),
                "close": None if pd.isna(row.get("close")) else float(row["close"]),
                "amount": None if "amount" not in row.index or pd.isna(row.get("amount")) else float(row["amount"]),
                "volume": None if "volume" not in row.index or pd.isna(row.get("volume")) else float(row["volume"]),
            }
            for _, row in subset.iterrows()
        ]
    return prices, histories

def _latest_prices(symbols: list[str], start_date: str, as_of: str) -> dict[str, dict[str, Any]]:
    prices, _ = _market_evidence(symbols, start_date, as_of)
    return prices

def _trading_state_evidence(
    symbol: str | None,
    event_date: Any,
    histories: Mapping[str, list[dict[str, Any]]],
    as_of: str,
    window_days: int = 45,
) -> dict[str, Any]:
    anchor = _date_token(event_date)
    rows = histories.get(symbol or "", [])
    if anchor:
        start_dt = datetime.strptime(anchor, "%Y%m%d") - timedelta(days=window_days)
        end_dt = min(
            datetime.strptime(as_of, "%Y%m%d"),
            datetime.strptime(anchor, "%Y%m%d") + timedelta(days=window_days),
        )
        rows = [
            row
            for row in rows
            if (row_date := _date_token(row.get("date")))
            and start_dt <= datetime.strptime(row_date, "%Y%m%d") <= end_dt
        ]
    suspended_dates = [
        str(row["date"]) for row in rows if row.get("trade_status") not in (None, 0)
    ]
    resumption_dates: list[str] = []
    previous: int | None = None
    for row in rows:
        current = row.get("trade_status")
        if previous not in (None, 0) and current == 0:
            resumption_dates.append(str(row["date"]))
        if current is not None:
            previous = int(current)
    return {
        "window_anchor": anchor,
        "window_days": window_days,
        "observations": len(rows),
        "suspension_dates": suspended_dates,
        "resumption_dates": resumption_dates,
        "latest_trade_status": rows[-1].get("trade_status") if rows else None,
        "evidence_status": "present" if rows else "missing",
    }

def _numeric(row: pd.Series, candidates: Iterable[str]) -> float | None:
    column = next((candidate for candidate in candidates if candidate in row.index), None)
    if column is None:
        return None
    value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
    return None if pd.isna(value) else float(value)


def _float_share_map(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty or "symbol" not in frame:
        return {}
    value_column = _first_column(
        frame,
        ["circulation_a", "float_shares", "circulating_shares", "float_a_shares"],
    )
    if value_column is None:
        return {}
    date_column = _first_column(frame, ["date", "trade_date", "info_date"])
    ordered = frame.sort_values(date_column) if date_column else frame
    output: dict[str, float] = {}
    for symbol, subset in ordered.groupby("symbol"):
        value = pd.to_numeric(subset.iloc[-1][value_column], errors="coerce")
        if pd.notna(value) and float(value) > 0:
            output[str(symbol).replace(".SS", ".SH")] = float(value)
    return output

def _fundamental_checks(symbols: list[str], as_of: str) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    year = int(as_of[:4])
    frame = fetch(
        "get_fina_reports",
        symbol=symbols,
        start_quarter=f"{year - 3}q1",
        end_quarter=f"{year}q4",
        date=as_of,
        is_latest=False,
    )
    if frame.empty or "symbol" not in frame:
        return {}
    period_column = _first_column(frame, ["quarter", "end_date", "period_end_date", "date"])
    if period_column is None:
        return {}
    frame = frame.copy()
    frame["_year"] = pd.to_numeric(
        frame[period_column].astype(str).str.extract(r"((?:19|20)\d{2})", expand=False),
        errors="coerce",
    )
    if period_column == "quarter":
        frame = frame[frame[period_column].astype(str).str.lower().str.endswith("q4")]
    publication_column = _first_column(frame, ["date", "info_date", "announcement_date"])
    frame["_publication_date"] = (
        frame[publication_column].astype(str)
        if publication_column is not None
        else ""
    )
    if publication_column is not None:
        frame = frame[
            frame["_publication_date"].map(
                lambda value: (_date_token(value) or "99999999") <= as_of
            )
        ]
    result: dict[str, dict[str, Any]] = {}
    for symbol, subset in frame.groupby("symbol"):
        subset = (
            subset.sort_values(["_year", "_publication_date"])
            .drop_duplicates("_year", keep="last")
            .tail(2)
        )
        if subset.empty:
            continue
        latest = subset.iloc[-1]
        previous = subset.iloc[-2] if len(subset) > 1 else None
        profit = _numeric(latest, NET_PROFIT_FIELDS)
        cash = _numeric(latest, OPERATING_CASH_FIELDS)
        previous_profit = _numeric(previous, NET_PROFIT_FIELDS) if previous is not None else None
        evidence = {
            "latest_year": None if pd.isna(latest["_year"]) else int(latest["_year"]),
            "available_date": _date_token(latest.get("_publication_date")),
            "net_profit": profit,
            "previous_net_profit": previous_profit,
            "operating_cash_flow": cash,
            "profit_improving": None
            if profit is None or previous_profit is None
            else profit > previous_profit,
            "profit_positive": None if profit is None else profit > 0,
            "cash_flow_positive": None if cash is None else cash > 0,
        }
        values = [
            evidence["profit_improving"],
            evidence["profit_positive"],
            evidence["cash_flow_positive"],
        ]
        evidence["double_check"] = (
            "insufficient_evidence"
            if any(value is None for value in values)
            else "pass"
            if sum(bool(value) for value in values) >= 2
            else "fail"
        )
        result[str(symbol).replace(".SS", ".SH")] = evidence
    return result

def _audit_evidence(symbols: list[str], as_of: str) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    year = int(as_of[:4])
    frames = [
        fetch(
            "get_audit_opinion",
            symbol=symbols[offset : offset + 20],
            start_quarter=f"{year - 3}q1",
            end_quarter=f"{year}q4",
            market="cn",
            fields=[],
        )
        for offset in range(0, len(symbols), 20)
    ]
    frame = pd.concat([item for item in frames if not item.empty], ignore_index=True) if any(not item.empty for item in frames) else pd.DataFrame()
    if frame.empty or "symbol" not in frame:
        return {}
    frame = frame.copy()
    if "date" in frame:
        frame = frame[
            frame["date"].map(lambda value: (_date_token(value) or "00000000") <= as_of)
        ]
    result: dict[str, dict[str, Any]] = {}
    for symbol, subset in frame.groupby("symbol"):
        subset = subset.copy()
        subset["_date"] = subset.get("date", pd.Series(index=subset.index, dtype=object)).map(
            lambda value: _date_token(value) or "00000000"
        )
        subset = subset.sort_values(["_date", "quarter"] if "quarter" in subset else ["_date"])
        opinion_series = subset.get(
            "opinion", pd.Series(index=subset.index, dtype=object)
        ).astype(str)
        substantive = subset[
            opinion_series.str.strip().ne("")
            & ~opinion_series.str.contains(NO_AUDIT_PATTERN, na=False)
        ]
        latest_rows = substantive
        if not substantive.empty:
            latest_rows = substantive[substantive["_date"] == substantive["_date"].max()]
            financial_rows = latest_rows[
                latest_rows.get(
                    "audit_type", pd.Series(index=latest_rows.index, dtype=object)
                )
                .astype(str)
                .str.contains("financial", case=False, na=False)
            ]
            selected = financial_rows.iloc[-1] if not financial_rows.empty else latest_rows.iloc[-1]
        else:
            selected = subset.iloc[-1]
            latest_rows = subset.iloc[[-1]]
        opinion = _text(selected.get("opinion"))
        audit_type = _text(selected.get("audit_type"))
        has_substantive = bool(opinion.strip()) and not bool(NO_AUDIT_PATTERN.search(opinion))
        observations = [
            {
                "date": _date_token(item.get("date")),
                "quarter": _scalar(item.get("quarter")),
                "audit_type": _scalar(item.get("audit_type")),
                "agency": _scalar(item.get("agency")),
                "opinion": _scalar(item.get("opinion")),
            }
            for _, item in latest_rows.iterrows()
        ]
        warning = any(
            AUDIT_WARNING_PATTERN.search(
                f"{_text(item.get('opinion'))} {_text(item.get('audit_type'))}"
            )
            for item in observations
        )
        result[str(symbol).replace(".SS", ".SH")] = {
            "date": _date_token(selected.get("date")),
            "quarter": _scalar(selected.get("quarter")),
            "audit_type": _scalar(selected.get("audit_type")),
            "agency": _scalar(selected.get("agency")),
            "opinion": _scalar(selected.get("opinion")),
            "latest_observations": observations,
            "substantive_opinion_available": has_substantive,
            "warning_flag": warning,
            "evidence_status": "present" if has_substantive else "limited",
        }
    return result
