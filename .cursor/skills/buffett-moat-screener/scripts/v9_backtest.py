"""V9 quantitative retrospective replay and publishable diagnostics.

This module replays point-in-time quantitative evidence and marks the result
as a retrospective diagnostic. It does not add discretionary evidence to
historical signal dates.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import data_pipeline
    from scripts.core import DATA_VERSION, DEFAULT_THRESHOLDS, PORTFOLIO_RULE_REVISION, V9_CASH_LEG, V9_MAIN_BENCHMARK, V9_SECONDARY_BENCHMARK
    from scripts.feasibility import classify_economic_evidence, make_annual_schedule, simulate_portfolio, _asset_nav, _performance
    from scripts.panda_adapter import clear_process_credentials, sdk_version
    from scripts.portfolio import build_portfolio
    from scripts.reporting import write_validation_artifacts
    from scripts.screener import _normalise_quarterly, screen_symbols
    from scripts.v9_engine import quantitative_proxy_score, valuation_score
else:
    from . import data_pipeline
    from .core import DATA_VERSION, DEFAULT_THRESHOLDS, PORTFOLIO_RULE_REVISION, V9_CASH_LEG, V9_MAIN_BENCHMARK, V9_SECONDARY_BENCHMARK
    from .feasibility import classify_economic_evidence, make_annual_schedule, simulate_portfolio, _asset_nav, _performance
    from .panda_adapter import clear_process_credentials, sdk_version
    from .portfolio import build_portfolio
    from .reporting import write_validation_artifacts
    from .screener import _normalise_quarterly, screen_symbols
def rules_fingerprint(thresholds: Mapping[str, Any]) -> str:
    """Return a stable checkpoint key for every quantitative rule input."""
    digest = hashlib.sha256(
        json.dumps(dict(thresholds), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"{DATA_VERSION}:{PORTFOLIO_RULE_REVISION}:{digest}"


def stratified_sample_symbols(
    symbols: list[str], details: pd.DataFrame, limit: int, *, as_of: str | None = None, mature_only: bool = False
) -> list[str]:
    """Deterministically sample across market, listing vintage, and board."""
    if limit <= 0 or (len(symbols) <= limit and not mature_only):
        return sorted(set(symbols))
    work = details.copy() if isinstance(details, pd.DataFrame) else pd.DataFrame()
    symbol_column = "symbol" if "symbol" in work.columns else "stock_symbol"
    if symbol_column not in work:
        return sorted(set(symbols))[:: max(1, len(set(symbols)) // limit)][:limit]
    metadata = {}
    mature_cutoff = None
    if mature_only and as_of and str(as_of)[:4].isdigit():
        mature_cutoff = int(str(as_of)[:4]) - 8
    for _, row in work.iterrows():
        symbol = str(row.get(symbol_column) or "").upper()
        if symbol not in symbols:
            continue
        market = symbol.rsplit(".", 1)[-1]
        listed = str(row.get("listed_date") or "")[:4]
        if mature_cutoff is not None and listed.isdigit() and int(listed) > mature_cutoff:
            continue
        vintage = listed if not listed.isdigit() else str((int(listed) // 5) * 5)
        board = str(row.get("board_type") or "unknown")
        metadata[symbol] = (market, vintage, board)
    groups: dict[tuple[str, str, str], list[str]] = {}
    for symbol in sorted(set(symbols)):
        if mature_only and symbol not in metadata:
            continue
        groups.setdefault(metadata.get(symbol, (symbol.rsplit(".", 1)[-1], "unknown", "unknown")), []).append(symbol)
    ordered_groups = sorted(groups)
    selected: list[str] = []
    cursor = 0
    while len(selected) < limit and ordered_groups:
        key = ordered_groups[cursor % len(ordered_groups)]
        members = groups[key]
        if members:
            selected.append(members.pop(0))
        ordered_groups = [group for group in ordered_groups if groups[group]]
        cursor += 1
    return selected


def _quantitative_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare V9 quant-only records without pretending qualitative approval."""
    prepared: list[dict[str, Any]] = []
    for source in records:
        row = dict(source)
        value = valuation_score(
            cash_yield=row.get("cash_earnings_yield_proxy"),
            normalized_pe=row.get("normalized_pe"),
            pb=(row.get("metrics") or {}).get("pb"),
            bank=row.get("special_case") == "bank_roa",
        )
        row["valuation_score"] = value
        row["qualitative_verdict"] = "not_backtested"
        row["qualitative_confidence"] = None
        row["qualitative_score"] = None
        row["conviction_score"] = quantitative_proxy_score(row.get("quality_score"), value)
        row["conviction_mode"] = "quantitative_proxy"
        row["policy_ceiling"] = 0.0
        row["qualitative_gate_backtested"] = False
        prepared.append(row)
    return prepared


def _revalue_reused_records(
    records: list[dict[str, Any]], price_frame: pd.DataFrame, thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Restore the price-dependent gate when replaying a price-free screen cache."""
    if price_frame is None or price_frame.empty:
        return records
    prices = price_frame.copy()
    prices["symbol"] = prices["symbol"].astype(str)
    prices["date"] = prices["date"].astype(str)
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    latest = prices.sort_values("date").dropna(subset=["close"]).drop_duplicates("symbol", keep="last")
    close_map = dict(zip(latest["symbol"], latest["close"]))
    for row in records:
        symbol = str(row.get("target_id"))
        close = close_map.get(symbol)
        metrics = row.setdefault("metrics", {})
        normalized_eps = metrics.get("normalized_eps")
        try:
            normalized_eps = float(normalized_eps)
            close = float(close)
        except (TypeError, ValueError):
            normalized_eps = None
            close = None
        normalized_pe = None if normalized_eps is None or normalized_eps <= 0 or close is None or close <= 0 else close / normalized_eps
        conversion = metrics.get("cash_conversion_5y")
        try:
            conversion = min(max(float(conversion), 0.0), 1.2)
        except (TypeError, ValueError):
            conversion = None
        cash_yield = None if normalized_pe is None or conversion is None else normalized_eps * conversion / close
        pb = metrics.get("pb")
        if pb is None and row.get("special_case") == "bank_roa":
            # The price-free cache predates the PB calculation.  Reconstruct
            # a transparent proxy from ROE and normalized EPS rather than
            # silently discarding banks during an offline rule replay.
            try:
                roe = float(metrics.get("roe_latest_pct")) / 100.0
                pb = close * roe / normalized_eps if roe > 0 and normalized_eps > 0 else None
            except (TypeError, ValueError):
                pb = None
            metrics["pb"] = pb
        metrics["latest_close"] = close
        metrics["normalized_pe"] = normalized_pe
        metrics["cash_earnings_yield_proxy"] = cash_yield
        row["normalized_pe"] = normalized_pe
        row["cash_earnings_yield_proxy"] = cash_yield
        is_bank = row.get("special_case") == "bank_roa"
        quality = float(row.get("quality_score") or 0.0)
        if is_bank:
            eligible = bool(
                quality >= float(thresholds.get("bank_quality_score_min", 75.0))
                and normalized_pe is not None and 0 < normalized_pe <= float(thresholds.get("bank_normalized_pe_max", 15.0))
                and metrics.get("pb") is not None and 0 < float(metrics["pb"]) <= float(thresholds.get("bank_pb_max", 1.8))
            )
        else:
            eligible = bool(
                quality >= float(thresholds.get("quality_score_min", 75.0))
                and normalized_pe is not None and 0 < normalized_pe <= float(thresholds.get("normalized_pe_max", 30.0))
                and cash_yield is not None and cash_yield >= float(thresholds.get("cash_earnings_yield_min", 0.03))
            )
        dilution_limit = thresholds.get("share_dilution_5y_max")
        if dilution_limit is not None:
            dilution_value = metrics.get("implied_share_dilution_5y")
            eligible = bool(
                eligible
                and dilution_value is not None
                and float(dilution_value) <= float(dilution_limit)
            )
        conversion_limit = thresholds.get("cash_conversion_3y_min")
        if conversion_limit is not None:
            recent_conversion = metrics.get("cash_conversion_3y")
            eligible = bool(
                eligible
                and recent_conversion is not None
                and float(recent_conversion) >= float(conversion_limit)
            )
        equity_growth_limit = thresholds.get("equity_cagr_5y_min")
        if equity_growth_limit is not None:
            equity_growth = metrics.get("equity_cagr_5y")
            eligible = bool(
                eligible
                and equity_growth is not None
                and float(equity_growth) >= float(equity_growth_limit)
            )
        owner_ratio_limit = thresholds.get("owner_earnings_positive_ratio_min")
        if owner_ratio_limit is not None:
            owner_ratio = metrics.get("owner_earnings_positive_year_ratio")
            eligible = bool(
                eligible
                and owner_ratio is not None
                and float(owner_ratio) >= float(owner_ratio_limit)
            )
        row["entry_eligible"] = eligible
        if row.get("decision") not in {"manual_review", "insufficient_data", "reject"}:
            row["decision"] = "research_candidate" if eligible else "watchlist"
    return records


def _equity_only_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize each signal to 100% invested stocks for attribution only."""
    normalized: list[dict[str, Any]] = []
    for signal in signals:
        weights = {
            str(symbol): float(weight)
            for symbol, weight in dict(signal.get("target_weights", {})).items()
            if str(symbol) != "CASH.CNY" and float(weight) > 0
        }
        total = sum(weights.values())
        target_weights = {symbol: weight / total for symbol, weight in weights.items()} if total > 0 else {}
        normalized.append({**signal, "actions": [], "target_weights": target_weights})
    return normalized


def _metrics(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    return _performance(frame, column)


def _history_ready_snapshots(
    snapshots: list[dict[str, Any]], raw_financials: pd.DataFrame, *, minimum_years: int = 8
) -> list[dict[str, Any]]:
    """Keep only dates with enough point-in-time annual evidence."""
    if raw_financials is None or raw_financials.empty:
        return []
    required = {"symbol", "quarter", "date"}
    if not required.issubset(raw_financials.columns):
        return []
    work = raw_financials.copy()
    work["symbol"] = work["symbol"].map(data_pipeline.clean_symbol)
    work["quarter"] = work["quarter"].astype(str).str.lower()
    work["date"] = work["date"].astype(str).str.replace("-", "", regex=False)
    work = work[work["quarter"].str.match(r"^\d{4}q4$")].copy()
    ready: list[dict[str, Any]] = []
    for snapshot in snapshots:
        signal_date = str(snapshot["signal_date"])
        visible = work[work["date"] <= signal_date]
        if visible.empty:
            continue
        selected, _ = data_pipeline.select_atomic_annual_revisions(visible, signal_date)
        if selected.empty:
            continue
        normalized = data_pipeline.normalize_annual_history(selected, pd.DataFrame())
        required_fields = [
            "parent_net_profit", "parent_equity", "basic_eps",
            "operating_cash_flow", "revenue",
        ]
        available = [field for field in required_fields if field in normalized.columns]
        if len(available) < len(required_fields):
            continue
        # N annual reports produce N-1 return observations. Require one
        # extra complete year so the scoring layer can calculate at least
        # ``minimum_years`` valid returns without silently padding history.
        counts = normalized.dropna(subset=available).groupby("symbol")["year"].nunique()
        if bool((counts >= minimum_years + 1).any()):
            ready.append(snapshot)
    return ready


def run_quantitative_backtest(
    input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Replay V9 quantitative rules over historical annual event dates.

    ``max_symbols`` is an optional operational limit for a smoke run.  The
    default is the full point-in-time SH/SZ universe and no index survivorship
    filter. No discretionary historical verdict is generated or reused.
    """
    options = dict(config or {})
    as_of = str(input_data["as_of_date"])
    # Retrieval bound only; the first usable signal is discovered from
    # point-in-time annual coverage after the financial fetch.
    # Use a broad retrieval bound when the caller does not specify one.  The
    # first usable signal is then discovered from actual calendar and annual
    # coverage, rather than being silently fixed to a convenient year.
    explicit_start = options.get("start_date")
    start_date = str(explicit_start or "20000101")
    batch_size = int(options.get("batch_size", 50))
    thresholds = {**DEFAULT_THRESHOLDS, **dict(options.get("thresholds", {}))}
    rules_fingerprint_value = rules_fingerprint(thresholds)
    max_symbols = options.get("max_symbols")
    reuse_preliminary_path = Path(options["reuse_preliminary"]) if options.get("reuse_preliminary") else None
    reuse_financials_path = Path(options["reuse_financials"]) if options.get("reuse_financials") else None
    validation_dir = Path(options.get("validation_dir") or Path(__file__).resolve().parents[1] / "validation" / "v9_quantitative_diagnostic")
    checkpoint_dir = Path(options.get("checkpoint_dir") or validation_dir / "checkpoint")
    checkpoint_path = checkpoint_dir / "signals_state.pkl"
    progress = bool(options.get("progress"))
    progress_log = Path(options["progress_log"]) if options.get("progress_log") else None

    def report(stage: str) -> None:
        if progress:
            print(f"[Q44] {stage}", flush=True)
        if progress_log:
            progress_log.parent.mkdir(parents=True, exist_ok=True)
            with progress_log.open("a", encoding="utf-8") as handle:
                handle.write(f"[Q44] {stage}\n")

    def save_checkpoint(payload: dict[str, Any]) -> None:
        save_checkpoint_file(checkpoint_path, payload)

    def save_checkpoint_file(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{__import__('os').getpid()}.tmp")
        with temporary.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(path)

    def load_checkpoint(manifest: dict[str, Any]) -> dict[str, Any] | None:
        return load_checkpoint_file(checkpoint_path, manifest)

    def load_checkpoint_file(path: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            with path.open("rb") as handle:
                payload = pickle.load(handle)
            if payload.get("manifest") == manifest:
                return payload
        except (OSError, EOFError, pickle.PickleError, AttributeError, ValueError):
            pass
        return None

    try:
        data_pipeline.configure_cache(options.get("cache_dir"))
        calendar = data_pipeline.fetch_trade_calendar(start_date, as_of)
        report("交易日历已加载")
        schedule = [row for row in make_annual_schedule(calendar, start_date, as_of) if row["execution_date"] <= as_of]
        if not schedule:
            raise RuntimeError("没有可用的年度事件和下一交易日")
        details = data_pipeline.fetch("get_stock_detail", status=None)
        report(f"股票池已加载：{len(details)} 条元数据")
        explicit = input_data.get("symbols")
        if explicit:
            all_symbols = sorted(set(explicit))
        else:
            historical = {
                row["signal_date"]: data_pipeline.resolve_all_a(details, row["signal_date"])["symbol"].astype(str).tolist()
                for row in schedule
            }
            all_symbols = sorted({symbol for values in historical.values() for symbol in values})
        if max_symbols:
            all_symbols = stratified_sample_symbols(
                all_symbols,
                details,
                int(max_symbols),
                as_of=as_of,
                mature_only=bool(options.get("mature_only", False)),
            )
        snapshots = []
        for row in schedule:
            symbols = sorted(set(explicit)) if explicit else sorted(set(historical[row["signal_date"]]) & set(all_symbols))
            snapshots.append({**row, "symbols": symbols})
        union = sorted({symbol for row in snapshots for symbol in row["symbols"]})
        if not union:
            raise RuntimeError("点时全 A 股票池为空")
        reused_preliminary = None
        if reuse_preliminary_path and reuse_preliminary_path.exists():
            with reuse_preliminary_path.open("rb") as handle:
                reused_preliminary = pickle.load(handle)
            reused_dates = set((reused_preliminary.get("manifest") or {}).get("signal_dates", []))
            snapshots = [row for row in snapshots if str(row["signal_date"]) in reused_dates]
            report(f"复用已验证的点时初筛数据：{len(snapshots)} 个信号日")
        # Historical replay disables the quarterly safety gate, so retain
        # only point-in-time Q4 rows.  Production screening still fetches the
        # complete quarterly history through its default ``annual_only=False``.
        if reuse_financials_path and reuse_financials_path.exists():
            raw_financials = pd.read_parquet(reuse_financials_path)
            if "quarter" in raw_financials:
                raw_financials = raw_financials[
                    raw_financials["quarter"].astype(str).str.lower().str.match(r"^\d{4}q4$")
                ].copy()
        elif reused_preliminary is not None:
            raw_financials = pd.DataFrame()
        else:
            raw_financials = data_pipeline.fetch_financial_history(
                union,
                as_of,
                years=max(12, int(as_of[:4]) - int(start_date[:4]) + 2),
                batch_size=batch_size,
                annual_only=True,
            )
        quarterly_cache = pd.DataFrame()
        report(f"财报已加载：{len(raw_financials)} 行")
        memberships = pd.DataFrame() if reused_preliminary is not None else data_pipeline.fetch_historical_industries(union)
        raw_prices = pd.DataFrame()
        report(f"行业已加载：{len(memberships)} 行")
        report(f"筛选价格已加载：{len(raw_prices)} 行")
        # Historical screening must have the same point-in-time audit
        # coverage as the annual statements.  Fetching only the latest three
        # years makes every earlier signal look like missing data and turns
        # the backtest into an unintended cash strategy.  The screen still
        # filters each opinion by ``published_at <= signal_date``.
        # Audit opinions are deliberately excluded from the historical
        # quantitative replay.  The production build keeps this gate strict;
        # the replay records the boundary instead of turning missing audit
        # history into an all-cash backtest.
        audit_histories: dict[str, list[dict[str, Any]]] = {}
        if reused_preliminary is None:
            snapshots = _history_ready_snapshots(snapshots, raw_financials, minimum_years=8)
        if not snapshots:
            raise RuntimeError("no signal date has at least eight point-in-time annual periods")
        report(f"usable signal dates: {snapshots[0]['signal_date']} - {snapshots[-1]['signal_date']}")
        annual_cache: dict[str, tuple[pd.DataFrame, list[dict[str, Any]]]] = {}
        if reused_preliminary is None:
            for snapshot in snapshots:
                day = str(snapshot["signal_date"])
                annual_cache[day] = data_pipeline.select_atomic_annual_revisions(raw_financials, day)
        checkpoint_manifest = {
            "checkpoint_version": 1,
            "data_version": DATA_VERSION,
            "rules_fingerprint": rules_fingerprint_value,
            "as_of_date": as_of,
            "start_date": start_date,
            "universe_count": len(all_symbols),
            "universe_digest": hashlib.sha256("\n".join(all_symbols).encode("utf-8")).hexdigest(),
            "signal_dates": [str(row["signal_date"]) for row in snapshots],
        }
        preliminary_path = checkpoint_dir / "preliminary_state.pkl"
        # Do a price-free quality pass first.  Prices remain mandatory for the
        # final valuation pass, but this avoids downloading closes for names
        # that already fail the point-in-time quality gate.
        empty_prices = pd.DataFrame(columns=["symbol", "date", "close"])
        preliminary_state = reused_preliminary or load_checkpoint_file(preliminary_path, checkpoint_manifest)
        if preliminary_state:
            preliminary_by_date = dict(preliminary_state.get("preliminary_by_date", {}))
            price_symbols = set(preliminary_state.get("price_symbols", []))
            if reused_preliminary is not None:
                # The screening metrics are unchanged by this experiment;
                # reconstruct only the warning taxonomy required by the new
                # long-term holding state machine.
                for rows in preliminary_by_date.values():
                    for row in rows:
                        metrics = row.get("metrics") or {}
                        reasons = []
                        if metrics.get("cash_conversion_3y") is not None and metrics["cash_conversion_3y"] < 0.40:
                            reasons.append("cash_conversion_3y_below_40pct")
                        if metrics.get("owner_earnings_positive_year_ratio_3y") is not None and metrics["owner_earnings_positive_year_ratio_3y"] < 2.0 / 3.0:
                            reasons.append("owner_earnings_negative_years")
                        if metrics.get("long_term_debt_to_profit") is not None and 4.0 <= metrics["long_term_debt_to_profit"] < 6.0:
                            reasons.append("debt_to_profit_between_4_and_6")
                        if float(row.get("missing_score_weight") or 0.0) > 10.0:
                            reasons.append("data_confidence_decline")
                        if 50.0 <= float(row.get("quality_score") or 0.0) < 70.0:
                            reasons.append("quality_score_soft_warning")
                        row["warning_reasons"] = reasons
            report(f"preliminary checkpoint restored: {len(price_symbols)} symbols")
        else:
            preliminary_by_date = {}
            price_symbols: set[str] = set()
            for snapshot in snapshots:
                signal_date = str(snapshot["signal_date"])
                report(f"quality pre-screen started: {signal_date}")
                selected_annual, annual_conflicts = annual_cache[signal_date]
                provisional, _ = screen_symbols(
                    sorted(set(snapshot["symbols"])),
                    signal_date,
                    thresholds=thresholds,
                    batch_size=batch_size,
                    raw_financials=raw_financials,
                    memberships=memberships,
                    price_frame=empty_prices,
                    audit_histories=audit_histories,
                    audit_gate=False,
                    quarterly_gate=False,
                    annual_frame=selected_annual,
                    annual_conflicts=annual_conflicts,
                    quarterly_frame=quarterly_cache,
                )
                provisional = _quantitative_records(provisional)
                preliminary_by_date[signal_date] = provisional
                price_symbols.update(
                    str(row["target_id"])
                    for row in provisional
                    if str(row.get("decision")) in {"research_candidate", "watchlist"}
                )
                report(f"quality pre-screen finished: {signal_date}")
            save_checkpoint_file(
                preliminary_path,
                {"manifest": checkpoint_manifest, "preliminary_by_date": preliminary_by_date, "price_symbols": sorted(price_symbols)},
            )
        report(f"quality pre-screen completed: {len(price_symbols)} symbols need signal prices")
        price_dir = checkpoint_dir / "signal_prices"
        expected_price_dates = [str(row["signal_date"]) for row in snapshots]
        cached_price_frames = {
            day: price_dir / f"{day}.parquet" for day in expected_price_dates
        }
        signal_price_frames: dict[str, pd.DataFrame] = {}
        price_window_failures: list[dict[str, Any]] = []
        if price_symbols:
            price_dir.mkdir(parents=True, exist_ok=True)
            # Fetch one signal date at a time and atomically persist it.  A
            # missing or rate-limited date is recorded without discarding
            # already completed dates; the next run retries only that gap.
            for day in expected_price_dates:
                cached = cached_price_frames[day]
                if cached.exists():
                    signal_price_frames[day] = pd.read_parquet(cached)
                    report(f"signal prices restored: {day}")
                    continue
                frames, failures = data_pipeline.fetch_signal_price_frames(
                    sorted(price_symbols), [day],
                    batch_size=batch_size, return_failures=True
                )
                price_window_failures.extend(failures)
                frame = frames.get(day, pd.DataFrame())
                if not frame.empty:
                    temporary = price_dir / f"{day}.{__import__('os').getpid()}.tmp"
                    frame.to_parquet(temporary, index=False)
                    temporary.replace(cached)
                    signal_price_frames[day] = frame
                    report(f"signal prices finished: {day}")
                else:
                    signal_price_frames[day] = frame
                    report(f"signal prices missing: {day}")
        else:
            signal_price_frames = {day: pd.DataFrame() for day in expected_price_dates}
        # Price frames are stored by signal date above; no long raw series is needed here.
        report("审计意见已加载")
        checkpoint_manifest = {
            "checkpoint_version": 1,
            "data_version": DATA_VERSION,
            "rules_fingerprint": rules_fingerprint_value,
            "as_of_date": as_of,
            "start_date": start_date,
            "universe_count": len(all_symbols),
            "universe_digest": hashlib.sha256("\n".join(all_symbols).encode("utf-8")).hexdigest(),
            "signal_dates": [str(row["signal_date"]) for row in snapshots],
        }
        cached_state = load_checkpoint(checkpoint_manifest)
        signals: list[dict[str, Any]] = list(cached_state.get("signals", [])) if cached_state else []
        coverage_history: list[dict[str, Any]] = list(cached_state.get("coverage_history", [])) if cached_state else []
        latest_records: list[dict[str, Any]] = list(cached_state.get("latest_records", [])) if cached_state else []
        state: dict[str, Any] = dict(cached_state.get("state", {})) if cached_state else {"holdings": [], "state_origin": "quantitative_historical_cash_start"}
        completed_dates = {str(row.get("signal_date")) for row in signals}
        if cached_state:
            report(f"checkpoint restored: {len(completed_dates)} signal dates")
        for snapshot in snapshots:
            signal_date = str(snapshot["signal_date"])
            if signal_date in completed_dates:
                continue
            symbols = sorted(
                {str(row["target_id"]) for row in preliminary_by_date.get(signal_date, [])}
                | {str(row["target_id"]) for row in state.get("holdings", [])}
            )
            price_frame = signal_price_frames.get(signal_date, pd.DataFrame())
            if reused_preliminary is not None:
                records = [
                    dict(row) for row in preliminary_by_date.get(signal_date, [])
                    if str(row.get("target_id")) in set(symbols)
                ]
                records = _revalue_reused_records(records, price_frame, thresholds)
            else:
                records, _ = screen_symbols(
                    symbols,
                    snapshot["signal_date"],
                    thresholds=thresholds,
                    batch_size=batch_size,
                    raw_financials=raw_financials,
                    memberships=memberships,
                    price_frame=price_frame,
                    audit_histories=audit_histories,
                    audit_gate=False,
                    quarterly_gate=False,
                    annual_frame=annual_cache[signal_date][0],
                    annual_conflicts=annual_cache[signal_date][1],
                    quarterly_frame=quarterly_cache,
                )
            records = _quantitative_records(records)
            latest_records = records
            coverage_history.append(
                {
                    "signal_date": snapshot["signal_date"],
                    "decision_counts": dict(pd.Series([str(row.get("decision", "missing")) for row in records], dtype="string").value_counts()),
                    "entry_eligible_count": int(sum(bool(row.get("entry_eligible")) for row in records)),
                    "price_window_rows": int(len(price_frame)),
                    "price_window_missing": bool(price_frame.empty),
                    "valid_return_years": dict(pd.Series([int((row.get("coverage") or {}).get("valid_return_years", 0)) for row in records], dtype="int64").value_counts()),
                }
            )
            portfolio = build_portfolio(
                records,
                signal_date=snapshot["signal_date"],
                execution_date=snapshot["execution_date"],
                prior_state=state,
                qualitative_required=False,
                quality_exit_min=thresholds.get("quality_exit_min"),
            )
            state = {
                "holdings": [dict(row) for row in portfolio["holdings"]],
                "state_origin": "quantitative_historical_replay",
                "state_date": snapshot["execution_date"],
            }
            evidence = {str(row["target_id"]): row for row in records}
            holding_map = {str(row["target_id"]): row for row in portfolio["holdings"]}
            actions = []
            for transition in portfolio.get("transitions", []):
                target = str(transition["target_id"])
                actions.append({
                    **transition,
                    "target_weight": float(holding_map.get(target, {}).get("policy_weight", 0.0)),
                    "quality_score": evidence.get(target, {}).get("quality_score"),
                    "conviction_score": evidence.get(target, {}).get("conviction_score"),
                })
            signals.append({
                "signal_date": snapshot["signal_date"],
                "execution_date": snapshot["execution_date"],
                "actions": actions,
                "target_weights": {str(row["target_id"]): float(row["policy_weight"]) for row in portfolio["holdings"]},
                "industries": {str(row["target_id"]): str(row.get("industry") or "") for row in portfolio["holdings"]},
            })
            completed_dates.add(signal_date)
            save_checkpoint({
                "manifest": checkpoint_manifest,
                "signals": signals,
                "coverage_history": coverage_history,
                "latest_records": latest_records,
                "state": state,
            })
            report(f"信号完成：{snapshot['signal_date']}")
        selected_symbols = sorted({str(symbol) for signal in signals for symbol in signal["target_weights"]})
        if not selected_symbols:
            decision_counts = pd.Series(
                [str(row.get("decision", "missing")) for row in latest_records], dtype="string"
            ).value_counts().to_dict()
            coverage_counts = pd.Series(
                [str((row.get("coverage") or {}).get("valid_return_years", 0)) for row in latest_records], dtype="string"
            ).value_counts().to_dict()
            raise RuntimeError(
                "V9 量化规则在回测期没有形成股票持仓；这不是成功回测；"
                f"latest_decisions={decision_counts}; valid_return_years={coverage_counts}"
            )
        first_execution = signals[0]["execution_date"]
        prices = data_pipeline.fetch_stock_backtest_prices(
            selected_symbols,
            first_execution,
            as_of,
            batch_size=batch_size,
            cache_dir=checkpoint_dir / "backtest_prices",
        )
        report(f"回测价格已加载：{len(prices)} 行")
        cash_prices = data_pipeline.fetch_fund_post(V9_CASH_LEG, first_execution, as_of)
        report("现金腿已加载")
        simulations = {str(cost): simulate_portfolio(prices, signals, cost_bps=float(cost), cash_prices=cash_prices) for cost in (0, 15, 30)}
        report("成本敏感性模拟完成")
        # Keep the main simulation's 511880 cash leg, and run a separate
        # zero-return cash control so the opportunity-cost comparison is real.
        zero_cash_simulation = simulate_portfolio(prices, signals, cost_bps=15.0, cash_prices=None)
        equity_only_simulation = simulate_portfolio(
            prices,
            _equity_only_signals(signals),
            cost_bps=15.0,
            cash_prices=None,
        )
        main = simulations["15"]
        benchmark_all = _asset_nav(data_pipeline.fetch_index_prices(V9_MAIN_BENCHMARK, first_execution, as_of), "benchmark_000985_nav")
        benchmark_secondary = _asset_nav(data_pipeline.fetch_fund_post(V9_SECONDARY_BENCHMARK, first_execution, as_of), "benchmark_510300_nav")
        cash_nav = _asset_nav(cash_prices, "cash_511880_nav")
        report("基准净值已计算")
        nav = main["nav"].copy()
        for comparison in (benchmark_all, benchmark_secondary, cash_nav):
            nav = nav.merge(comparison, on="date", how="left")
        nav = nav.sort_values("date").ffill().dropna(subset=["strategy_nav", "benchmark_000985_nav"])
        diagnostic_start = max("20220101", nav["date"].astype(str).min())
        periods = {
            "full": {"strategy": _metrics(nav, "strategy_nav"), "benchmark_000985": _metrics(nav, "benchmark_000985_nav"), "benchmark_510300": _metrics(nav, "benchmark_510300_nav"), "cash_511880": _metrics(nav, "cash_511880_nav")},
            "development": {"strategy": _metrics(nav[nav["date"].astype(str) < "20220101"], "strategy_nav"), "benchmark_000985": _metrics(nav[nav["date"].astype(str) < "20220101"], "benchmark_000985_nav")},
            "retrospective_diagnostic": {"strategy": _metrics(nav[nav["date"].astype(str) >= diagnostic_start], "strategy_nav"), "benchmark_000985": _metrics(nav[nav["date"].astype(str) >= diagnostic_start], "benchmark_000985_nav"), "benchmark_510300": _metrics(nav[nav["date"].astype(str) >= diagnostic_start], "benchmark_510300_nav")},
        }
        diagnostic_metrics = periods["retrospective_diagnostic"]
        diagnostic_strategy = diagnostic_metrics["strategy"]
        diagnostic_benchmark = diagnostic_metrics["benchmark_000985"]
        diagnostic_nav = main["nav"][main["nav"]["date"].astype(str) >= diagnostic_start]
        prior_nav = main["nav"][main["nav"]["date"].astype(str) < diagnostic_start]
        diagnostic_end = diagnostic_nav.iloc[-1] if not diagnostic_nav.empty else {}
        diagnostic_base = prior_nav.iloc[-1] if not prior_nav.empty else {}
        end_stocks = dict(diagnostic_end.get("stock_contributions", {}))
        base_stocks = dict(diagnostic_base.get("stock_contributions", {}))
        stock_contribution_total = sum(
            float(value) - float(base_stocks.get(symbol, 0.0) or 0.0)
            for symbol, value in end_stocks.items()
        )
        cash_contribution = float(diagnostic_end.get("cash_contribution", 0.0) or 0.0) - float(diagnostic_base.get("cash_contribution", 0.0) or 0.0)
        economic_evidence = classify_economic_evidence(
            float(diagnostic_strategy.get("cagr") or 0.0),
            float(diagnostic_benchmark.get("cagr") or 0.0),
            float(diagnostic_strategy.get("max_drawdown") or 0.0),
            float(diagnostic_benchmark.get("max_drawdown") or 0.0),
            has_equity_exposure=bool(selected_symbols),
            cash_contribution=cash_contribution,
            stock_contribution=stock_contribution_total,
            secondary_benchmark_cagr=float(diagnostic_metrics.get("benchmark_510300", {}).get("cagr") or 0.0),
            secondary_benchmark_max_drawdown=float(diagnostic_metrics.get("benchmark_510300", {}).get("max_drawdown") or 0.0),
        )
        final_holdings = state.get("holdings", [])
        final_stock_contributions = dict(main["nav"].iloc[-1].get("stock_contributions", {}) if not main["nav"].empty else {})
        contribution_abs_total = sum(abs(float(value)) for value in final_stock_contributions.values())
        top_contribution_symbol = None
        top_contribution_share = 0.0
        if final_stock_contributions and contribution_abs_total > 0:
            top_contribution_symbol, top_value = max(
                final_stock_contributions.items(), key=lambda item: abs(float(item[1]))
            )
            top_contribution_share = abs(float(top_value)) / contribution_abs_total
        current_actual_holdings: list[dict[str, Any]] = []
        actual_cash_weight = None
        if not main["holdings"].empty:
            latest_market_state = main["holdings"].iloc[-1]
            raw_weights = latest_market_state.get("weights", {})
            if isinstance(raw_weights, str):
                try:
                    raw_weights = json.loads(raw_weights)
                except (TypeError, ValueError, json.JSONDecodeError):
                    raw_weights = {}
            if isinstance(raw_weights, Mapping):
                actual_cash_weight = float(latest_market_state.get("cash_weight", 0.0) or 0.0)
                for holding in final_holdings:
                    symbol = str(holding.get("target_id", ""))
                    current_actual_holdings.append({
                        **dict(holding),
                        "actual_weight": float(raw_weights.get(symbol, 0.0) or 0.0),
                    })
        result: dict[str, Any] = {
            "strategy_id": "Q44-BUFFETT-A-SHARE-V9-QUANT",
            "data_version": DATA_VERSION,
            "as_of_date": as_of,
            "start_date": nav["date"].astype(str).min(),
            "universe": "all_a" if not explicit else "symbols",
            "universe_count": len(all_symbols),
            "signal_count": len(signals),
            "qualitative_gate_backtested": False,
            "audit_gate_backtested": False,
            "evidence_scope": "quantitative_retrospective_diagnostic",
            "economic_evidence": economic_evidence,
            "attribution_scope": {
                "stock_contribution_total": stock_contribution_total,
                "cash_contribution": cash_contribution,
                "cash_dominates": bool(cash_contribution > max(0.0, stock_contribution_total)),
                "top_stock_contribution_symbol": top_contribution_symbol,
                "top_stock_contribution_share": top_contribution_share,
                "concentration_warning": bool(top_contribution_share > 0.50),
            },
            "validation_level": "runnable",
            "periods": periods,
            "cost_sensitivity_bps": {cost: _performance(simulations[cost]["nav"], "strategy_nav") for cost in ("0", "15", "30")},
            "cash_sensitivity": {
                "511880": _performance(main["nav"], "strategy_nav"),
                "zero_percent": _performance(zero_cash_simulation["nav"], "strategy_nav"),
            },
            "equity_only_sensitivity": _performance(equity_only_simulation["nav"], "strategy_nav"),
            "nav_curve": main["nav"].merge(benchmark_all, on="date", how="left").merge(benchmark_secondary, on="date", how="left").merge(cash_nav, on="date", how="left").ffill().to_dict("records"),
            "holdings_history": main["holdings"].to_dict("records"),
            "rebalance_history": main["rebalances"].to_dict("records"),
            "current_holdings": final_holdings,
            "current_cash_weight": max(0.0, 1.0 - sum(float(row.get("policy_weight", 0.0)) for row in final_holdings)),
            "current_actual_holdings": current_actual_holdings,
            "current_actual_cash_weight": actual_cash_weight,
            "coverage_summary": {
                "universe_count": len(all_symbols),
                "signal_history": coverage_history,
                "latest": coverage_history[-1] if coverage_history else {},
                "price_window_failures": price_window_failures,
            },
            "attribution": {"stock_contributions": final_stock_contributions, "cash_contribution": (main["nav"].iloc[-1].get("cash_contribution", 0.0) if not main["nav"].empty else 0.0), "sell_reasons": [action for signal in signals for action in signal["actions"] if action.get("review_action") == "exit"], "quality_score_history": [action for signal in signals for action in signal["actions"]]},
            "forward_validation": {"eligible": False, "reason": "V9 正式物化后尚未积累 252 个交易日"},
            "lookahead_audit": {"passed": all(str(signal["signal_date"]) < str(signal["execution_date"]) for signal in signals)},
            "engineering_gates": {"point_in_time_audit": all(str(signal["signal_date"]) < str(signal["execution_date"]) for signal in signals), "qualitative_gate_backtested": False, "audit_gate_backtested": False, "price_coverage": not prices.empty and not price_window_failures, "benchmark_coverage": not benchmark_all.empty, "risk_disclosure": True},
            "disclaimer": "Quantitative retrospective only. This is not a return guarantee or investment advice.",
        }
        validation_dir.mkdir(parents=True, exist_ok=True)
        result["validation_artifacts"] = {name: str(path) for name, path in write_validation_artifacts(result, validation_dir).items()}
        report("报告与验证产物已写入")
        return result
    finally:
        data_pipeline.configure_cache(None)
        clear_process_credentials()


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Q44 V9 quantitative retrospective diagnostic")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument(
        "--start-date",
        default=None,
        help="可选的财报检索起点；省略时从宽检索区间自动发现首个有效信号日",
    )
    parser.add_argument("--max-symbols", type=int)
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--validation-dir")
    parser.add_argument("--cache-dir")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--progress-log")
    parser.add_argument("--mature-only", action="store_true")
    parser.add_argument("--reuse-preliminary")
    parser.add_argument("--reuse-financials")
    parser.add_argument("--normalized-eps-years", type=int)
    parser.add_argument("--share-dilution-max", type=float)
    parser.add_argument("--cash-conversion-3y-min", type=float)
    parser.add_argument("--equity-cagr-5y-min", type=float)
    parser.add_argument("--owner-earnings-positive-min", type=float)
    parser.add_argument("--quality-exit-min", type=float)
    args = parser.parse_args()
    config = {"batch_size": args.batch_size}
    if args.start_date:
        config["start_date"] = args.start_date
    if args.max_symbols:
        config["max_symbols"] = args.max_symbols
    if args.validation_dir:
        config["validation_dir"] = args.validation_dir
    if args.cache_dir:
        config["cache_dir"] = args.cache_dir
    if args.progress:
        config["progress"] = True
    if args.progress_log:
        config["progress_log"] = args.progress_log
    if args.mature_only:
        config["mature_only"] = True
    if args.reuse_preliminary:
        config["reuse_preliminary"] = args.reuse_preliminary
    if args.reuse_financials:
        config["reuse_financials"] = args.reuse_financials
    if args.normalized_eps_years:
        config["thresholds"] = {"normalized_eps_years": args.normalized_eps_years}
    if args.share_dilution_max is not None:
        config.setdefault("thresholds", {})["share_dilution_5y_max"] = args.share_dilution_max
    if args.cash_conversion_3y_min is not None:
        config.setdefault("thresholds", {})["cash_conversion_3y_min"] = args.cash_conversion_3y_min
    if args.equity_cagr_5y_min is not None:
        config.setdefault("thresholds", {})["equity_cagr_5y_min"] = args.equity_cagr_5y_min
    if args.owner_earnings_positive_min is not None:
        config.setdefault("thresholds", {})["owner_earnings_positive_ratio_min"] = args.owner_earnings_positive_min
    if args.quality_exit_min is not None:
        config.setdefault("thresholds", {})["quality_exit_min"] = args.quality_exit_min
    input_data = {"as_of_date": args.as_of_date}
    if args.symbols:
        input_data["symbols"] = args.symbols
    else:
        input_data["universe"] = "all_a"
    result = run_quantitative_backtest(input_data, config)
    print(json.dumps({
        "strategy_id": result["strategy_id"],
        "data_version": result["data_version"],
        "evidence_scope": result["evidence_scope"],
        "qualitative_gate_backtested": result["qualitative_gate_backtested"],
        "periods": result["periods"],
        "validation_artifacts": result["validation_artifacts"],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
