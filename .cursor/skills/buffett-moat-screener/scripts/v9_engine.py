"""Pure V9 mechanics: full-A point-in-time universe and event-driven state."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .core import A_SHARE_PATTERN, DEFAULT_THRESHOLDS


STRUCTURAL_WARNING_REASONS = {
    "cash_conversion_3y_below_40pct",
    "owner_earnings_negative_years",
    "debt_to_profit_between_4_and_6",
    "data_confidence_decline",
    "quality_score_soft_warning",
}


def _date(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA:
        return ""
    normalized = str(value).replace("-", "")[:8]
    return "" if normalized in {"00000000", "99999999", "NaT", "nan"} else normalized


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace(".SS", ".SH")


def resolve_all_a(details: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """Return point-in-time SH/SZ names, including historical delistings."""
    if details is None or details.empty:
        return pd.DataFrame(columns=["symbol", "listed_date", "de_listed_date", "universe_status"])
    work = details.copy()
    symbol_col = "symbol" if "symbol" in work else "stock_symbol" if "stock_symbol" in work else None
    if not symbol_col:
        return pd.DataFrame(columns=["symbol", "listed_date", "de_listed_date", "universe_status"])
    work["symbol"] = work[symbol_col].map(_symbol)
    work = work[work["symbol"].str.match(r"^\d{6}\.(SH|SZ)$", case=False, na=False)].copy()
    listed_col = next((c for c in ("listed_date", "list_date", "ipo_date") if c in work), None)
    delisted_col = next((c for c in ("de_listed_date", "delisted_date", "out_date") if c in work), None)
    work["listed_date"] = work[listed_col].map(_date) if listed_col else ""
    work["de_listed_date"] = work[delisted_col].map(_date) if delisted_col else ""
    work = work[(work["listed_date"] == "") | (work["listed_date"] <= as_of_date)]
    work = work[(work["de_listed_date"] == "") | (work["de_listed_date"] > as_of_date)]
    work["universe_status"] = "listed_at_event"
    return work.drop_duplicates("symbol", keep="last").reset_index(drop=True)


def historical_universe(details: pd.DataFrame, dates: Sequence[str]) -> dict[str, list[str]]:
    return {_date(day): sorted(resolve_all_a(details, _date(day))["symbol"].tolist()) for day in dates}


def discover_backtest_start(calendar: pd.DataFrame, annual_frame: pd.DataFrame, *, minimum_years: int = 8) -> str | None:
    """Find the first trading date with enough point-in-time annual history."""
    if calendar is None or calendar.empty or annual_frame is None or annual_frame.empty:
        return None
    date_col = next((c for c in ("date", "trade_date", "cal_date") if c in calendar), None)
    if not date_col:
        return None
    dates = sorted(calendar[date_col].map(_date))
    work = annual_frame.copy()
    if "symbol" not in work or "year" not in work:
        return None
    work["symbol"] = work["symbol"].map(_symbol)
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    counts = work.dropna(subset=["year"]).groupby("symbol")["year"].nunique()
    if counts.empty or int(counts.max()) < minimum_years:
        return None
    earliest_year = int(work["year"].min())
    return next((day for day in dates if day[:4] and int(day[:4]) >= earliest_year + minimum_years - 1), dates[0] if dates else None)


def event_stream(calendar: pd.DataFrame, *, annual_dates: Sequence[str] = (), quarterly_dates: Sequence[str] = (), audit_dates: Sequence[str] = (), announcement_dates: Sequence[str] = ()) -> list[dict[str, str]]:
    """Normalize all triggers into deterministic event-day order."""
    events: list[dict[str, str]] = []
    for kind, values in (("annual_report", annual_dates), ("quarterly_report", quarterly_dates), ("audit", audit_dates), ("official_filing", announcement_dates)):
        for value in values:
            events.append({"event_date": _date(value), "event_type": kind})
    if calendar is not None and not calendar.empty:
        date_col = next((c for c in ("date", "trade_date", "cal_date") if c in calendar), None)
        if date_col:
            for value in calendar[date_col].map(_date):
                if value:
                    events.append({"event_date": value, "event_type": "daily_price"})
    return sorted(events, key=lambda item: (item["event_date"], item["event_type"]))


def next_open_date(calendar: pd.DataFrame, event_date: str) -> str | None:
    if calendar is None or calendar.empty:
        return None
    col = next((c for c in ("date", "trade_date", "cal_date") if c in calendar), None)
    open_col = next((c for c in ("is_open", "is_trade", "is_trading_day") if c in calendar), None)
    if not col:
        return None
    work = calendar.copy(); work["_date"] = work[col].map(_date)
    if open_col:
        work = work[pd.to_numeric(work[open_col], errors="coerce").fillna(0).gt(0)]
    values = sorted(value for value in work["_date"] if value > event_date)
    return values[0] if values else None


def quarterly_ttm(frame: pd.DataFrame, *, symbol: str | None = None) -> dict[str, Any]:
    """Compute TTM as current YTD + prior Q4 - prior-year same YTD atomically."""
    if frame is None or frame.empty:
        return {"ttm": {}, "coverage": "missing"}
    work = frame.copy()
    if symbol and "symbol" in work:
        work = work[work["symbol"].map(_symbol) == _symbol(symbol)]
    work["quarter"] = work["quarter"].astype(str).str.lower() if "quarter" in work else ""
    work["date"] = work["date"].map(_date) if "date" in work else ""
    fields = [c for c in ("parent_net_profit", "basic_eps", "operating_cash_flow", "revenue") if c in work]
    if not fields:
        return {"ttm": {}, "coverage": "missing"}
    work = work.sort_values(["quarter", "date"])
    result: dict[str, float] = {}
    latest = work[work["quarter"].str.match(r"^\d{4}q[1-3]$")]
    if latest.empty:
        return {"ttm": {}, "coverage": "missing"}
    row = latest.iloc[-1]; q = str(row["quarter"]); year = int(q[:4]); suffix = q[-2:]
    prior_q4 = work[work["quarter"].eq(f"{year - 1}q4")]
    prior_ytd = work[work["quarter"].eq(f"{year - 1}{suffix}")]
    if prior_q4.empty or prior_ytd.empty:
        return {"ttm": {}, "coverage": "missing"}
    # Pick the latest complete revision for the entire row, never fieldwise.
    prior_q4 = prior_q4.iloc[-1]; prior_ytd = prior_ytd.iloc[-1]
    for field in fields:
        current = pd.to_numeric(pd.Series([row[field]]), errors="coerce").iloc[0]
        q4 = pd.to_numeric(pd.Series([prior_q4[field]]), errors="coerce").iloc[0]
        ytd = pd.to_numeric(pd.Series([prior_ytd[field]]), errors="coerce").iloc[0]
        if pd.notna(current) and pd.notna(q4) and pd.notna(ytd):
            result[field] = float(current + q4 - ytd)
    revision_date = str(row["date"])
    return {
        "ttm": result,
        "quarter": q,
        "as_of_revision": revision_date,
        "event_date": revision_date,
        "coverage": "complete" if len(result) == len(fields) else "partial",
    }


def quarterly_safety_status(
    frame: pd.DataFrame, *, symbol: str | None = None, as_of: str | None = None,
    max_age_days: int = 180,
) -> dict[str, Any]:
    """Return a conservative TTM profit/EPS safety state for event updates."""
    work = frame.copy() if frame is not None else pd.DataFrame()
    if as_of and not work.empty and "date" in work:
        work = work[work["date"].astype(str).str.replace("-", "", regex=False) <= str(as_of)[:8]]
    result = quarterly_ttm(work, symbol=symbol)
    ttm = result.get("ttm", {})
    if result.get("coverage") != "complete":
        return {**result, "status": "missing"}
    revision = pd.to_datetime(str(result.get("event_date") or ""), format="%Y%m%d", errors="coerce")
    observed = pd.to_datetime(str(as_of or ""), format="%Y%m%d", errors="coerce")
    if pd.notna(revision) and pd.notna(observed) and (observed - revision).days > max(0, int(max_age_days)):
        return {**result, "status": "stale", "stale_days": int((observed - revision).days)}
    profit = pd.to_numeric(pd.Series([ttm.get("parent_net_profit")]), errors="coerce").iloc[0]
    eps = pd.to_numeric(pd.Series([ttm.get("basic_eps")]), errors="coerce").iloc[0]
    if pd.isna(profit) or pd.isna(eps):
        return {**result, "status": "missing"}
    return {**result, "status": "healthy" if float(profit) > 0 and float(eps) > 0 else "warning"}


def normalized_eps(eps_values: Sequence[Any]) -> float | None:
    values = pd.to_numeric(pd.Series(list(eps_values)), errors="coerce").dropna()
    values = values[values > 0]
    if values.empty:
        return None
    latest = float(values.iloc[-1]); median3 = float(values.tail(3).median())
    return min(latest, median3)


def valuation_score(*, cash_yield: float | None = None, normalized_pe: float | None = None, pb: float | None = None, bank: bool = False) -> float | None:
    def linear(value: float, points: Sequence[tuple[float, float]]) -> float:
        if value <= points[0][0]: return points[0][1]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if value <= x1: return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
        return points[-1][1]
    if bank:
        if normalized_pe is None or pb is None or normalized_pe <= 0 or pb <= 0: return None
        pe = linear(normalized_pe, [(8, 100), (10, 90), (12, 75), (15, 60)])
        book = linear(pb, [(0.8, 100), (1.0, 90), (1.4, 75), (1.8, 60)])
        return round((pe + book) / 2, 4)
    if cash_yield is None or cash_yield <= 0: return None
    return round(linear(cash_yield, [(0.03, 60), (0.04, 75), (0.05, 90), (0.0567, 100)]), 4)


def conviction_score(quality_score: float | None, qualitative_score: float | None, valuation: float | None) -> float | None:
    values = (quality_score, qualitative_score, valuation)
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return None
    return round(0.45 * float(quality_score) + 0.40 * float(qualitative_score) + 0.15 * float(valuation), 4)


def quantitative_proxy_score(quality_score: float | None, valuation: float | None) -> float | None:
    """Score used only by retrospective quant diagnostics.

    Historical periods cannot use today's discretionary review. A
    separate proxy keeps the production conviction formula untouched and
    avoids counting the same quality evidence as both quality and qualitative
    approval.  Historical ranking deliberately uses quality alone: valuation
    remains a reasonable-price entry gate, rather than allowing a cheaper but
    weaker business to outrank a better compounder. It must never be labelled
    as a qualitative verdict.
    """
    if quality_score is None or not math.isfinite(float(quality_score)):
        return None
    if valuation is None or not math.isfinite(float(valuation)):
        return None
    return round(float(quality_score), 4)


def policy_ceiling(conviction: float | None) -> float:
    if conviction is None: return 0.0
    value = float(conviction)
    return 0.25 if value >= 90 else 0.20 if value >= 82 else 0.15 if value >= 75 else 0.10 if value >= 70 else 0.0


def capacity_check(*, capital: float, median_turnover: float | None, valid_days: int, thresholds: Mapping[str, Any] | None = None) -> dict[str, Any]:
    limits = {**DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    target_value = capital * 0.25
    sufficient_days = valid_days >= int(limits["liquidity_valid_days_min"])
    sufficient_turnover = median_turnover is not None and target_value <= float(median_turnover) * float(limits["liquidity_participation_max"])
    return {"valid_days": int(valid_days), "median_turnover": median_turnover, "capacity_ok": bool(sufficient_days and sufficient_turnover), "reason": "ok" if sufficient_days and sufficient_turnover else "liquidity_or_capacity_insufficient"}


@dataclass(frozen=True)
class StateTransition:
    target_id: str
    action: str
    reason: str
    event_date: str


def transition_holding(previous: Mapping[str, Any], evidence: Mapping[str, Any] | None, *, event_date: str) -> tuple[dict[str, Any] | None, StateTransition]:
    symbol = str(previous["target_id"])
    warnings = int(previous.get("warning_count", previous.get("annual_warning_count", 0)))
    evidence = evidence or {}
    event_key = str(
        evidence.get("event_revision_date")
        or evidence.get("event_date")
        or event_date
    )
    # Both quantitative exits and qualitative red flags are independent
    # evidence channels.  Do not let one non-empty list hide the other.
    severe = set(evidence.get("sell_triggers") or [])
    severe.update(evidence.get("serious_flags") or [])
    severe.update({"st_risk", "delisting_risk"} & set(evidence.get("risk_flags") or []))
    if severe:
        return None, StateTransition(symbol, "exit", ",".join(sorted(severe)), event_date)
    if evidence.get("qualitative_verdict") == "reject":
        return None, StateTransition(symbol, "exit", "qualitative_serious_red_flag", event_date)
    if evidence.get("decision") == "insufficient_data":
        holding = {
            **dict(previous),
            **{k: evidence[k] for k in ("quality_score", "qualitative_score", "qualitative_confidence", "valuation_score", "conviction_score", "industry", "special_case") if k in evidence},
            "warning_count": warnings,
            "annual_warning_count": warnings,
            "review_action": "warning_hold",
            "last_event_date": event_date,
        }
        return holding, StateTransition(symbol, "warning_hold", "evidence_insufficient_no_forced_exit", event_date)
    # A pending review can mean an API outage or missing documents.  It is not
    # dated negative evidence and must freeze additions without accumulating a
    # sell warning.  Only an explicit role disagreement (or a supplied
    # qualitative warning marker) counts as a qualitative warning event.
    qualitative_pending = evidence.get("qualitative_verdict") == "qualitative_pending"
    qualitative_warning = (
        evidence.get("qualitative_verdict") == "disagreement"
        or evidence.get("qualitative_warning") is True
    )
    if qualitative_pending:
        # Preserve an existing dated-warning count, but do not add a new one
        # while evidence is unavailable.
        action, reason = "warning_hold", "qualitative_evidence_pending_no_new_warning"
        holding = {**dict(previous), **{k: evidence[k] for k in ("quality_score", "qualitative_score", "qualitative_confidence", "valuation_score", "conviction_score", "industry", "special_case") if k in evidence}, "warning_count": warnings, "annual_warning_count": warnings, "review_action": action, "last_event_date": event_date}
        if "conviction_score" in evidence:
            holding["policy_ceiling"] = policy_ceiling(evidence.get("conviction_score"))
        return holding, StateTransition(symbol, action, reason, event_date)
    warning_reasons = evidence.get("warning_reasons")
    structural_warning = (
        evidence.get("hold_status") == "warning"
        if warning_reasons is None
        else bool(STRUCTURAL_WARNING_REASONS.intersection(str(item) for item in warning_reasons))
    )
    warning = bool(structural_warning or qualitative_warning or evidence.get("quarterly_safety_status") == "warning")
    soft_score_warning = bool(
        evidence.get("hold_status") == "warning"
        and warning_reasons is not None
        and not structural_warning
        and not qualitative_warning
        and evidence.get("quarterly_safety_status") != "warning"
    )
    if soft_score_warning:
        holding = {**dict(previous), **{k: evidence[k] for k in ("quality_score", "qualitative_score", "qualitative_confidence", "valuation_score", "conviction_score", "industry", "special_case") if k in evidence}, "warning_count": 0, "annual_warning_count": 0, "review_action": "warning_hold", "last_event_date": event_date, "last_warning_event": ""}
        if "conviction_score" in evidence:
            holding["policy_ceiling"] = policy_ceiling(evidence.get("conviction_score"))
        return holding, StateTransition(symbol, "warning_hold", "quality_score_soft_warning_no_forced_exit", event_date)
    if warning:
        duplicate_warning = event_key == str(previous.get("last_warning_event", ""))
        if duplicate_warning:
            action, reason = "warning_hold", "duplicate_warning_event_no_new_count"
        else:
            warnings += 1
            if warnings >= 2:
                return None, StateTransition(symbol, "exit", "two_consecutive_independent_warnings", event_date)
            action, reason = "warning_hold", "first_independent_warning"
        last_warning_event = event_key
    else:
        warnings = 0
        action, reason = "hold", "thesis_not_broken"
        last_warning_event = ""
    holding = {**dict(previous), **{k: evidence[k] for k in ("quality_score", "qualitative_score", "qualitative_confidence", "valuation_score", "conviction_score", "industry", "special_case") if k in evidence}, "warning_count": warnings, "annual_warning_count": warnings, "review_action": action, "last_event_date": event_date, "last_warning_event": last_warning_event}
    if "conviction_score" in evidence:
        holding["policy_ceiling"] = policy_ceiling(evidence.get("conviction_score"))
    return holding, StateTransition(symbol, action, reason, event_date)


def opportunity_replacement(
    incumbent: Mapping[str, Any], newcomer: Mapping[str, Any], *, quantitative: bool = False
) -> bool:
    def number(value: Any) -> float:
        try:
            value = float(value)
            return value if math.isfinite(value) else -math.inf
        except (TypeError, ValueError):
            return -math.inf
    if not quantitative and (
        incumbent.get("qualitative_score") is None or newcomer.get("qualitative_score") is None
    ):
        return False
    if quantitative and incumbent.get("qualitative_score") is None and newcomer.get("qualitative_score") is None:
        # Historical replay cannot manufacture official-document judgments.
        # Use the explicitly labelled quantitative proxy only, while keeping
        # the same high opportunity-cost gaps for quality, price and proxy
        # conviction.
        return all(
            number(newcomer.get(new)) >= number(incumbent.get(old)) + gap
            for new, old, gap in (
                ("quality_score", "quality_score", 5),
                ("valuation_score", "valuation_score", 15),
                ("conviction_score", "conviction_score", 10),
            )
        )
    return all(number(newcomer.get(new)) >= number(incumbent.get(old)) + gap for new, old, gap in (("quality_score", "quality_score", 5), ("qualitative_score", "qualitative_score", 10), ("valuation_score", "valuation_score", 15), ("conviction_score", "conviction_score", 10)))


class EventEngine:
    """Deterministic incremental event dispatcher used by repeated builds."""

    def __init__(self, calendar: pd.DataFrame, *, state_date: str | None = None):
        self.calendar = calendar.copy() if calendar is not None else pd.DataFrame()
        self.state_date = _date(state_date)

    def pending(self, events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows = [dict(event) for event in events if _date(event.get("event_date")) > self.state_date]
        return sorted(rows, key=lambda event: (_date(event.get("event_date")), str(event.get("event_type", ""))))

    def execution_date(self, event_date: str) -> str | None:
        return next_open_date(self.calendar, _date(event_date))

    def apply(self, state: Mapping[str, Any], events: Sequence[Mapping[str, Any]], handler: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        current = dict(state); applied: list[dict[str, Any]] = []
        for event in self.pending(events):
            current = dict(handler(current, event))
            current["state_date"] = _date(event.get("event_date"))
            applied.append({**dict(event), "execution_date": self.execution_date(str(event.get("event_date")))})
        return current, applied
