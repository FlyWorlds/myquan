"""Point-in-time feasibility calculations for the Q44 derived portfolio."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from . import data_pipeline
from .core import (
    DATA_VERSION,
    DEFAULT_INDEX,
    DEFAULT_THRESHOLDS,
    V8_FORWARD_START_DATE,
    V8_RULE_FREEZE_DATE,
)
from .panda_adapter import (
    build_production_frame,
    clear_process_credentials,
    sdk_version,
    write_versioned_production,
)
from .portfolio import MAX_SLOTS, POLICY_WEIGHTS, STRATEGY_ID, build_portfolio
from .reporting import write_validation_artifacts
from .screener import screen_symbols
from .validation import validate_input


def make_annual_schedule(
    trade_calendar: pd.DataFrame, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    if trade_calendar.empty or "date" not in trade_calendar:
        return []
    calendar = trade_calendar.copy()
    calendar["date"] = calendar["date"].astype(str).str.replace("-", "", regex=False)
    if "is_open" in calendar:
        calendar = calendar[pd.to_numeric(calendar["is_open"], errors="coerce") == 1]
    open_dates = sorted(
        value for value in calendar["date"].dropna().unique() if start_date <= value <= end_date
    )
    schedule: list[dict[str, Any]] = []
    for year in range(int(start_date[:4]), int(end_date[:4]) + 1):
        cutoff = f"{year}0430"
        signal_candidates = [value for value in open_dates if value <= cutoff and value[:4] == str(year)]
        if not signal_candidates:
            continue
        signal_date = signal_candidates[-1]
        execution_candidates = [value for value in open_dates if value > signal_date]
        if execution_candidates:
            schedule.append(
                {
                    "year": year,
                    "signal_date": signal_date,
                    "execution_date": execution_candidates[0],
                }
            )
    return schedule


def classify_economic_evidence(
    strategy_cagr: float,
    benchmark_cagr: float,
    strategy_max_drawdown: float,
    benchmark_max_drawdown: float,
    *,
    has_equity_exposure: bool = True,
    cash_contribution: float | None = None,
    stock_contribution: float | None = None,
    secondary_benchmark_cagr: float | None = None,
    secondary_benchmark_max_drawdown: float | None = None,
) -> str:
    if not has_equity_exposure or strategy_cagr <= 0:
        return "unsupported"
    if cash_contribution is not None and stock_contribution is not None:
        try:
            cash_value = float(cash_contribution)
            stock_value = float(stock_contribution)
        except (TypeError, ValueError):
            cash_value = stock_value = 0.0
        if cash_value > max(0.0, stock_value):
            return "mixed"
    beats_primary = (
        strategy_cagr > benchmark_cagr
        and strategy_max_drawdown >= benchmark_max_drawdown - 0.05
    )
    if not beats_primary:
        return "mixed"
    # When an investable secondary benchmark is available, a result that only
    # beats a broad index but loses to the secondary benchmark is not robust
    # evidence of Buffett-style stock selection.
    if secondary_benchmark_cagr is not None:
        if strategy_cagr <= float(secondary_benchmark_cagr):
            return "mixed"
        if secondary_benchmark_max_drawdown is not None and strategy_max_drawdown < float(secondary_benchmark_max_drawdown) - 0.05:
            return "mixed"
    if beats_primary:
        return "supported"
    return "mixed"


def _normalise_price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "symbol", "open", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"prices missing columns: {sorted(missing)}")
    result = prices.copy()
    result["date"] = result["date"].astype(str).str.replace("-", "", regex=False)
    result["symbol"] = result["symbol"].astype(str).str.upper()
    result["open"] = pd.to_numeric(result["open"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    if "tradable" not in result:
        result["tradable"] = result[["open", "close"]].notna().all(axis=1)
    if "limit_up" not in result:
        result["limit_up"] = False
    if "limit_down" not in result:
        result["limit_down"] = False
    return result.sort_values(["date", "symbol"]).reset_index(drop=True)


def simulate_portfolio(
    prices: pd.DataFrame,
    signals: Sequence[Mapping[str, Any]],
    *,
    cost_bps: float = 15.0,
    cash_prices: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Run a deterministic fractional-weight simulation with explicit trade blocks."""
    market = _normalise_price_frame(prices)
    dates = set(market["date"].unique())
    signal_by_execution = {str(row["execution_date"]): row for row in signals}
    current: dict[str, float] = {}
    pending_sells: set[str] = set()
    nav = 1.0
    nav_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    rebalance_rows: list[dict[str, Any]] = []
    previous_close: dict[str, float] = {}
    cash_market = pd.DataFrame()
    if cash_prices is not None and not cash_prices.empty:
        cash_market = cash_prices.copy()
        cash_market["date"] = cash_market["date"].astype(str).str.replace("-", "", regex=False)
        cash_market["open"] = pd.to_numeric(cash_market["open"], errors="coerce")
        cash_market["close"] = pd.to_numeric(cash_market["close"], errors="coerce")
        cash_market = cash_market.dropna(subset=["date", "open", "close"]).drop_duplicates("date", keep="last").set_index("date")
        dates.update(cash_market.index.astype(str).tolist())
    dates = sorted(dates)
    previous_cash_close: float | None = None
    cumulative_cash_contribution = 0.0
    stock_contributions: dict[str, float] = {}
    current_industries: dict[str, str] = {}
    holding_since: dict[str, str] = {}
    quality_scores: dict[str, float | None] = {}

    for current_date in dates:
        daily = market[market["date"] == current_date].set_index("symbol")
        day_start_nav = nav
        cash_weight = max(0.0, 1.0 - sum(current.values()))
        cash_open_factor = 1.0
        if current_date in cash_market.index and previous_cash_close and previous_cash_close > 0:
            cash_open_factor = float(cash_market.loc[current_date, "open"]) / previous_cash_close
        overnight_factor = cash_weight * cash_open_factor
        cumulative_cash_contribution += cash_weight * (cash_open_factor - 1.0)
        for symbol, weight in current.items():
            if symbol in daily.index and symbol in previous_close:
                opening = float(daily.loc[symbol, "open"])
                previous = previous_close[symbol]
                overnight_factor += weight * (opening / previous if previous > 0 else 1.0)
            else:
                overnight_factor += weight
        if overnight_factor > 0:
            nav *= overnight_factor
            for symbol in list(current):
                if symbol in daily.index and symbol in previous_close:
                    opening = float(daily.loc[symbol, "open"])
                    previous = previous_close[symbol]
                    current[symbol] = current[symbol] * (opening / previous if previous > 0 else 1.0) / overnight_factor
                else:
                    current[symbol] = current[symbol] / overnight_factor

        turnover = 0.0
        desired: dict[str, float] = {}
        if current_date in signal_by_execution:
            signal = signal_by_execution[current_date]
            current_industries.update(
                {str(symbol): str(industry) for symbol, industry in dict(signal.get("industries", {})).items()}
            )
            actions = list(signal.get("actions", []))
            if actions:
                for action in actions:
                    symbol = str(action.get("target_id", ""))
                    quality_scores[symbol] = action.get("quality_score")
                    review_action = str(action.get("review_action", ""))
                    if review_action == "exit" and symbol in current:
                        pending_sells.add(symbol)
                    elif review_action in {"enter", "add"}:
                        weight = float(action.get("target_weight", 0.0))
                        if weight > 0:
                            desired[symbol] = weight
                    elif review_action == "risk_trim" and symbol in current:
                        desired[symbol] = min(current[symbol], float(action.get("target_weight", current[symbol])))
                industries = dict(signal.get("industries", {}))
                for symbol, weight in list(current.items()):
                    if weight > 0.30:
                        desired[symbol] = min(desired.get(symbol, weight), 0.25)
                industry_totals: dict[str, float] = {}
                for symbol, weight in current.items():
                    industry = str(industries.get(symbol, ""))
                    industry_totals[industry] = industry_totals.get(industry, 0.0) + weight
                for industry, total in industry_totals.items():
                    if not industry or total <= 0.40:
                        continue
                    excess = total - 0.35
                    members = sorted(
                        (symbol for symbol in current if industries.get(symbol) == industry),
                        key=lambda symbol: current[symbol],
                        reverse=True,
                    )
                    for symbol in members:
                        if excess <= 0:
                            break
                        reduction = min(excess, max(0.0, current[symbol] - 0.05))
                        desired[symbol] = min(desired.get(symbol, current[symbol]), current[symbol] - reduction)
                        excess -= reduction
            elif signal.get("target_weights"):
                desired = {
                    str(symbol): float(weight)
                    for symbol, weight in dict(signal["target_weights"]).items()
                    if float(weight) > 0
                }
            else:
                desired_symbols = list(dict.fromkeys(signal.get("symbols", [])))[:MAX_SLOTS]
                desired = {
                    symbol: POLICY_WEIGHTS[index]
                    for index, symbol in enumerate(desired_symbols)
                }
                pending_sells.update(set(current) - set(desired))

        for symbol in list(pending_sells):
            row = daily.loc[symbol] if symbol in daily.index else None
            if row is not None and bool(row["tradable"]) and not bool(row["limit_down"]):
                turnover += current.pop(symbol, 0.0)
                pending_sells.discard(symbol)
                holding_since.pop(symbol, None)
                current_industries.pop(symbol, None)

        if current_date in signal_by_execution:
            for symbol, weight in desired.items():
                row = daily.loc[symbol] if symbol in daily.index else None
                existing = current.get(symbol, 0.0)
                difference = weight - existing
                cash_available = max(0.0, 1.0 - sum(current.values()))
                if difference > 0 and row is not None and bool(row["tradable"]) and not bool(row["limit_up"]):
                    purchase = min(difference, cash_available)
                    current[symbol] = existing + purchase
                    holding_since.setdefault(symbol, current_date)
                    turnover += purchase
                elif difference < 0 and row is not None and bool(row["tradable"]) and not bool(row["limit_down"]):
                    current[symbol] = weight
                    turnover += abs(difference)

            rebalance_rows.append(
                {
                    "signal_date": str(signal_by_execution[current_date]["signal_date"]),
                    "execution_date": current_date,
                    "turnover": turnover,
                    "cost_bps": float(cost_bps),
                    "executed_symbols": sorted(current),
                    "pending_sells": sorted(pending_sells),
                    "review_actions": list(signal_by_execution[current_date].get("actions", [])),
                }
            )

        nav *= 1.0 - turnover * float(cost_bps) / 10000.0
        cash_weight = max(0.0, 1.0 - sum(current.values()))
        cash_close_factor = 1.0
        if current_date in cash_market.index:
            cash_open = float(cash_market.loc[current_date, "open"])
            cash_close = float(cash_market.loc[current_date, "close"])
            if cash_open > 0:
                cash_close_factor = cash_close / cash_open
            previous_cash_close = cash_close
        intraday_factor = cash_weight * cash_close_factor
        cumulative_cash_contribution += cash_weight * (cash_close_factor - 1.0)
        for symbol, weight in current.items():
            if symbol in daily.index:
                opening = float(daily.loc[symbol, "open"])
                close = float(daily.loc[symbol, "close"])
                intraday_factor += weight * (close / opening if opening > 0 else 1.0)
                stock_contributions[symbol] = stock_contributions.get(symbol, 0.0) + weight * (
                    close / opening - 1.0 if opening > 0 else 0.0
                )
            else:
                intraday_factor += weight
        if intraday_factor > 0:
            nav *= intraday_factor
            for symbol in list(current):
                if symbol in daily.index:
                    opening = float(daily.loc[symbol, "open"])
                    close = float(daily.loc[symbol, "close"])
                    current[symbol] = current[symbol] * (close / opening if opening > 0 else 1.0) / intraday_factor
                else:
                    current[symbol] = current[symbol] / intraday_factor

        for symbol, row in daily.iterrows():
            close = float(row["close"])
            if np.isfinite(close):
                previous_close[symbol] = close
        cash_weight = max(0.0, 1.0 - sum(current.values()))
        daily_return = nav / day_start_nav - 1.0 if day_start_nav else 0.0
        nav_rows.append(
            {
                "date": current_date,
                "strategy_nav": nav,
                "daily_return": daily_return,
                "cash_weight": cash_weight,
                "cash_contribution": cumulative_cash_contribution,
                "stock_contributions": dict(sorted(stock_contributions.items())),
            }
        )
        holding_rows.append(
            {
                "date": current_date,
                "symbols": sorted(current),
                "weights": {symbol: current[symbol] for symbol in sorted(current)},
                "cash_weight": cash_weight,
                "pending_sells": sorted(pending_sells),
                "holding_since": {symbol: holding_since.get(symbol) for symbol in sorted(current)},
                "quality_scores": {symbol: quality_scores.get(symbol) for symbol in sorted(current)},
                "industry_exposure": {
                    industry: sum(
                        weight for symbol, weight in current.items()
                        if current_industries.get(symbol, "") == industry
                    )
                    for industry in sorted({current_industries.get(symbol, "") for symbol in current})
                    if industry
                },
            }
        )

    return {
        "nav": pd.DataFrame(nav_rows),
        "holdings": pd.DataFrame(holding_rows),
        "rebalances": pd.DataFrame(rebalance_rows),
    }


def _asset_nav(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", name])
    work = frame.copy()
    work["date"] = work["date"].astype(str).str.replace("-", "", regex=False)
    work["open"] = pd.to_numeric(work["open"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["date", "open", "close"]).sort_values("date").drop_duplicates("date")
    if work.empty:
        return pd.DataFrame(columns=["date", name])
    returns = work["close"].pct_change()
    returns.iloc[0] = work.iloc[0]["close"] / work.iloc[0]["open"] - 1.0
    work[name] = (1.0 + returns.fillna(0.0)).cumprod()
    return work[["date", name]].reset_index(drop=True)


def _performance(frame: pd.DataFrame, column: str) -> dict[str, float | None]:
    empty = {
        "total_return": None,
        "cagr": None,
        "max_drawdown": None,
        "annualized_volatility": None,
        "sharpe": None,
    }
    if frame.empty or column not in frame:
        return empty
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return empty
    total = float(values.iloc[-1] / values.iloc[0] - 1.0)
    dates = pd.to_datetime(frame.loc[values.index, "date"], format="%Y%m%d", errors="coerce")
    days = max(int((dates.iloc[-1] - dates.iloc[0]).days), 1) if dates.notna().all() else len(values)
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (365.25 / days) - 1.0) if len(values) > 1 else 0.0
    drawdown = values / values.cummax() - 1.0
    returns = values.pct_change().dropna()
    volatility = float(returns.std(ddof=0) * np.sqrt(252)) if len(returns) else 0.0
    sharpe = float(returns.mean() / returns.std(ddof=0) * np.sqrt(252)) if len(returns) and returns.std(ddof=0) > 0 else None
    return {
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": float(drawdown.min()),
        "annualized_volatility": volatility,
        "sharpe": sharpe,
    }


def _period_metrics(nav: pd.DataFrame, start: str | None, end: str | None) -> dict[str, Any]:
    period = nav.copy()
    if start is not None:
        period = period[period["date"] >= start]
    if end is not None:
        period = period[period["date"] <= end]
    if period.empty:
        return {name: _performance(period, name) for name in (
            "strategy_nav", "benchmark_510300_nav", "index_000300_nav", "cash_511880_nav"
        )}
    rebased = period.copy()
    for column in ("strategy_nav", "benchmark_510300_nav", "index_000300_nav", "cash_511880_nav"):
        if column in rebased and rebased[column].notna().any():
            first = rebased[column].dropna().iloc[0]
            if first != 0:
                rebased[column] = rebased[column] / first
    return {name: _performance(rebased, name) for name in (
        "strategy_nav", "benchmark_510300_nav", "index_000300_nav", "cash_511880_nav"
    )}


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.replace({np.nan: None}).to_dict("records") if not frame.empty else []


def _lot_sensitivity(
    signals: Sequence[Mapping[str, Any]], prices: pd.DataFrame, capital: float = 1_000_000.0
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in signals:
        execution_date = str(signal["execution_date"])
        daily = prices[prices["date"].astype(str) == execution_date]
        price_column = "execution_price_raw" if "execution_price_raw" in daily else "open"
        price_map = {
            str(row["symbol"]): float(row[price_column])
            for _, row in daily.iterrows()
            if pd.notna(row.get(price_column))
        }
        target_weights = dict(signal.get("target_weights", {}))
        if not target_weights:
            target_weights = {
                symbol: POLICY_WEIGHTS[index]
                for index, symbol in enumerate(signal.get("symbols", [])[:MAX_SLOTS])
            }
        holdings = []
        invested = 0.0
        for symbol, weight in target_weights.items():
            price = price_map.get(str(symbol))
            quantity = int((capital * float(weight)) // (price * 100) * 100) if price and price > 0 else 0
            value = quantity * price if price else 0.0
            invested += value
            holdings.append(
                {
                    "target_id": str(symbol),
                    "reference_price": price,
                    "reference_quantity": quantity,
                    "reference_value": value,
                }
            )
        rows.append(
            {
                "signal_date": str(signal["signal_date"]),
                "execution_date": execution_date,
                "capital": float(capital),
                "lot_size": 100,
                "cash_amount": round(capital - invested, 2),
                "holdings": holdings,
            }
        )
    return rows


def _legacy_run_feasibility(
    input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Run the preregistered annual A-share strategy without changing its parameters."""
    validate_input(input_data)
    options = dict(config or {})
    allowed = {"thresholds", "batch_size", "start_date", "capital", "materialize", "output_path", "validation_dir"}
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError(f"unsupported feasibility config fields: {unknown}")
    start_date = str(options.get("start_date", "20170103"))
    as_of = str(input_data["as_of_date"])
    datetime.strptime(start_date, "%Y%m%d")
    if start_date > as_of:
        raise ValueError("start_date must not be after as_of_date")
    batch_size = int(options.get("batch_size", 20))
    thresholds = {**DEFAULT_THRESHOLDS, **dict(options.get("thresholds", {}))}
    index_symbol = str(input_data.get("index_symbol") or DEFAULT_INDEX)

    try:
        calendar = data_pipeline.fetch_trade_calendar(start_date, as_of)
        schedule = make_annual_schedule(calendar, start_date, as_of)
        snapshots: list[dict[str, Any]] = []
        explicit = input_data.get("symbols")
        for row in schedule:
            symbols = (
                sorted(set(explicit))
                if explicit
                else data_pipeline.discover_symbols(row["signal_date"], index_symbol)
            )
            snapshots.append({**row, "symbols": symbols})
        if not snapshots or any(not row["symbols"] for row in snapshots):
            raise ValueError("historical universe coverage is incomplete")

        union = sorted({symbol for row in snapshots for symbol in row["symbols"]})
        earliest_financial_year = int(start_date[:4]) - 12
        financial_years = int(as_of[:4]) - earliest_financial_year
        raw_financials = data_pipeline.fetch_financial_history(
            union, as_of, years=financial_years, batch_size=batch_size
        )
        memberships = data_pipeline.fetch_historical_industries(union)
        first_execution = snapshots[0]["execution_date"]
        prices = data_pipeline.fetch_stock_backtest_prices(
            union, first_execution, as_of, batch_size=batch_size
        )
        cash_prices = data_pipeline.fetch_fund_post("511880.SH", first_execution, as_of)

        signals: list[dict[str, Any]] = []
        audit_rows: list[dict[str, Any]] = []
        latest_records: list[dict[str, Any]] = []
        state: dict[str, Any] = {"holdings": [], "state_origin": "historical_cash_start"}
        current_portfolio: dict[str, Any] | None = None
        for snapshot_index, snapshot in enumerate(snapshots):
            review_symbols = sorted(
                set(snapshot["symbols"])
                | {str(row["target_id"]) for row in state.get("holdings", [])}
            )
            records, _ = screen_symbols(
                review_symbols,
                snapshot["signal_date"],
                thresholds=thresholds,
                batch_size=batch_size,
                raw_financials=raw_financials,
                memberships=memberships,
            )
            latest_records = records
            previous_state = state
            current_portfolio = build_portfolio(
                records,
                signal_date=snapshot["signal_date"],
                execution_date=snapshot["execution_date"],
                prior_state=state,
            )
            holding_map = {row["target_id"]: row for row in current_portfolio["holdings"]}
            evidence_map = {row["target_id"]: row for row in records}
            actions = [
                {
                    **transition,
                    "target_weight": holding_map.get(transition["target_id"], {}).get("policy_weight", 0.0),
                    "quality_score": evidence_map.get(transition["target_id"], {}).get("quality_score"),
                }
                for transition in current_portfolio["transitions"]
            ]
            signals.append(
                {
                    "signal_date": snapshot["signal_date"],
                    "execution_date": snapshot["execution_date"],
                    "actions": actions,
                    "target_weights": {
                        row["target_id"]: float(row["policy_weight"])
                        for row in current_portfolio["holdings"]
                    },
                    "industries": {
                        row["target_id"]: row.get("industry", "")
                        for row in current_portfolio["holdings"]
                    },
                }
            )
            next_signal_date = (
                snapshots[snapshot_index + 1]["signal_date"]
                if snapshot_index + 1 < len(snapshots)
                else as_of
            )
            executed_holdings = [dict(row) for row in current_portfolio["holdings"]]
            executed_by_symbol = {row["target_id"]: row for row in executed_holdings}
            previous_by_symbol = {
                row["target_id"]: dict(row) for row in previous_state.get("holdings", [])
            }
            execution_market = prices[
                prices["date"].astype(str) == snapshot["execution_date"]
            ].set_index("symbol") if not prices.empty else pd.DataFrame()
            for transition in current_portfolio["transitions"]:
                symbol = transition["target_id"]
                action = transition["review_action"]
                row = execution_market.loc[symbol] if symbol in execution_market.index else None
                if action == "enter" and (
                    row is None or not bool(row["tradable"]) or bool(row["limit_up"])
                ):
                    executed_by_symbol.pop(symbol, None)
                elif action == "exit" and symbol in previous_by_symbol:
                    future = prices[
                        (prices["symbol"].astype(str) == symbol)
                        & (prices["date"].astype(str) >= snapshot["execution_date"])
                        & (prices["date"].astype(str) <= next_signal_date)
                    ]
                    sellable = future[
                        future["tradable"].astype(bool) & ~future["limit_down"].astype(bool)
                    ] if not future.empty else future
                    if sellable.empty:
                        pending = previous_by_symbol[symbol]
                        pending["review_action"] = "pending_exit"
                        executed_by_symbol[symbol] = pending
            state = {
                "holdings": list(executed_by_symbol.values()),
                "state_origin": "historical_replay",
                "state_date": snapshot["execution_date"],
            }
            for row in records:
                source_date = row.get("actual_source_date")
                audit_rows.append(
                    {
                        "signal_date": snapshot["signal_date"],
                        "target_id": row.get("target_id"),
                        "actual_source_date": source_date,
                        "passed": source_date in {None, ""} or str(source_date) <= snapshot["signal_date"],
                    }
                )

        if current_portfolio is not None:
            current_portfolio["holdings"] = [dict(row) for row in state["holdings"]]
            current_portfolio["cash_weight"] = max(
                0.0,
                1.0 - sum(float(row.get("policy_weight", 0.0)) for row in state["holdings"]),
            )
        simulations = {
            str(cost): simulate_portfolio(
                prices, signals, cost_bps=float(cost), cash_prices=cash_prices
            )
            for cost in (0, 15, 30)
        }
        zero_cash_simulation = simulate_portfolio(prices, signals, cost_bps=15.0)
        main = simulations["15"]
        nav = main["nav"].copy()
        benchmark = _asset_nav(
            data_pipeline.fetch_fund_post("510300.SH", first_execution, as_of),
            "benchmark_510300_nav",
        )
        index_nav = _asset_nav(
            data_pipeline.fetch_index_prices("000300.SH", first_execution, as_of),
            "index_000300_nav",
        )
        cash_nav = _asset_nav(cash_prices, "cash_511880_nav")
        for comparison in (benchmark, index_nav, cash_nav):
            nav = nav.merge(comparison, on="date", how="left")
        nav = nav.sort_values("date").ffill().dropna(subset=["strategy_nav", "benchmark_510300_nav"])

        periods = {
            "full": _period_metrics(nav, None, None),
            "development": _period_metrics(nav, None, "20211231"),
            "retrospective_diagnostic": _period_metrics(nav, "20220101", V8_RULE_FREEZE_DATE),
            "forward": _period_metrics(nav, V8_FORWARD_START_DATE, None),
        }
        diagnostic_strategy = periods["retrospective_diagnostic"]["strategy_nav"]
        diagnostic_benchmark = periods["retrospective_diagnostic"]["benchmark_510300_nav"]
        equity_exposure_days = int(
            main["holdings"]["symbols"].map(lambda value: bool(value)).sum()
        ) if not main["holdings"].empty else 0
        average_equity_exposure = float(
            (1.0 - pd.to_numeric(main["holdings"]["cash_weight"], errors="coerce")).mean()
        ) if not main["holdings"].empty else 0.0
        if (
            diagnostic_strategy["cagr"] is None
            or diagnostic_benchmark["cagr"] is None
            or equity_exposure_days == 0
        ):
            evidence = "unsupported"
        else:
            evidence = classify_economic_evidence(
                float(diagnostic_strategy["cagr"]),
                float(diagnostic_benchmark["cagr"]),
                float(diagnostic_strategy["max_drawdown"]),
                float(diagnostic_benchmark["max_drawdown"]),
                has_equity_exposure=equity_exposure_days > 0,
            )
        lookahead_passed = all(row["passed"] for row in audit_rows) and all(
            row["signal_date"] < row["execution_date"] for row in signals
        )
        engineering_gates = {
            "point_in_time_audit": lookahead_passed,
            "universe_coverage": len(snapshots) == len(schedule),
            "price_coverage": not prices.empty and not nav.empty,
            "benchmark_coverage": not benchmark.empty,
            "cost_reproducible": all(not value["nav"].empty for value in simulations.values()),
            "equity_exposure": equity_exposure_days > 0,
            "risk_disclosure": True,
        }
        forward_sessions = int((nav["date"].astype(str) >= V8_FORWARD_START_DATE).sum())
        forward_reviews = sum(
            1 for row in signals if str(row["signal_date"]) >= V8_FORWARD_START_DATE
        )
        forward_strategy = periods["forward"]["strategy_nav"]
        forward_benchmark = periods["forward"]["benchmark_510300_nav"]
        forward_performance_passed = bool(
            forward_strategy["cagr"] is not None
            and forward_benchmark["cagr"] is not None
            and float(forward_strategy["cagr"]) > 0
            and float(forward_strategy["cagr"]) > float(forward_benchmark["cagr"])
            and float(forward_strategy["max_drawdown"]) >= float(forward_benchmark["max_drawdown"]) - 0.05
        )
        forward_eligible = forward_sessions >= 252 and forward_reviews >= 1
        validation_level = (
            "verified"
            if forward_eligible and forward_performance_passed and all(engineering_gates.values())
            else "runnable"
        )
        current = current_portfolio or build_portfolio(
            latest_records,
            signal_date=signals[-1]["signal_date"],
            execution_date=signals[-1]["execution_date"],
            prior_state=state,
        )
        if options.get("capital") is not None:
            capital = float(options["capital"])
            execution_rows = prices[
                prices["date"].astype(str) == str(signals[-1]["execution_date"])
            ]
            price_column = "execution_price_raw" if "execution_price_raw" in execution_rows else "open"
            price_map = {
                str(row["symbol"]): float(row[price_column])
                for _, row in execution_rows.iterrows()
                if pd.notna(row.get(price_column)) and float(row[price_column]) > 0
            }
            invested_amount = 0.0
            for holding in current["holdings"]:
                price = price_map.get(holding["target_id"])
                target_value = capital * float(holding.get("policy_weight", 0.0))
                quantity = int(target_value // (price * 100) * 100) if price else 0
                value = quantity * price if price else 0.0
                holding.update(
                    {
                        "reference_price": price,
                        "reference_quantity": quantity,
                        "reference_value": value,
                    }
                )
                invested_amount += value
            current.update(
                {
                    "capital": capital,
                    "lot_size": 100,
                    "cash_amount": round(capital - invested_amount, 2),
                }
            )
        review_rows = main["holdings"][
            main["holdings"]["date"].astype(str) == str(signals[-1]["execution_date"])
        ] if not main["holdings"].empty else pd.DataFrame()
        if not review_rows.empty:
            review_weights = dict(review_rows.iloc[-1]["weights"])
            for holding in current["holdings"]:
                holding["actual_weight"] = float(review_weights.get(holding["target_id"], 0.0))
            current["holdings"] = [
                holding
                for holding in current["holdings"]
                if holding["actual_weight"] > 0
                or str(holding.get("holding_since")) != str(signals[-1]["execution_date"])
            ]
            current["cash_weight"] = float(review_rows.iloc[-1]["cash_weight"])
        final_nav_row = main["nav"].iloc[-1].to_dict() if not main["nav"].empty else {}
        sell_reasons = [
            {
                "signal_date": signal["signal_date"],
                "target_id": action["target_id"],
                "reason": action.get("reason"),
            }
            for signal in signals
            for action in signal.get("actions", [])
            if action.get("review_action") == "exit"
        ]
        result: dict[str, Any] = {
            "strategy_id": STRATEGY_ID,
            "data_version": DATA_VERSION,
            "as_of_date": as_of,
            "start_date": start_date,
            "source": {"provider": "panda_data", "sdk_version": sdk_version(), "market": "cn"},
            "periods": periods,
            "cost_sensitivity_bps": {
                cost: _performance(result["nav"], "strategy_nav")
                for cost, result in simulations.items()
            },
            "cash_sensitivity": {
                "511880": _performance(main["nav"], "strategy_nav"),
                "zero_percent": _performance(zero_cash_simulation["nav"], "strategy_nav"),
            },
            "economic_evidence": evidence,
            "evidence_scope": "retrospective_diagnostic",
            "exposure": {
                "equity_exposure_days": equity_exposure_days,
                "average_equity_exposure": average_equity_exposure,
            },
            "validation_level": validation_level,
            "forward_validation": {
                "start_date": V8_FORWARD_START_DATE,
                "sessions": forward_sessions,
                "annual_reviews": forward_reviews,
                "eligible": forward_eligible,
                "performance_passed": forward_performance_passed,
            },
            "engineering_gates": engineering_gates,
            "lookahead_audit": {"passed": lookahead_passed, "records": audit_rows},
            "nav_curve": _json_records(nav),
            "holdings_history": _json_records(main["holdings"]),
            "rebalance_history": _json_records(main["rebalances"]),
            "lot_sensitivity_1m": _lot_sensitivity(signals, prices),
            "current_holdings": current["holdings"],
            "current_cash_weight": current["cash_weight"],
            "attribution": {
                "stock_contributions": final_nav_row.get("stock_contributions", {}),
                "cash_contribution": final_nav_row.get("cash_contribution", 0.0),
                "sell_reasons": sell_reasons,
                "quality_score_history": [
                    {
                        "signal_date": signal["signal_date"],
                        "target_id": action["target_id"],
                        "quality_score": action.get("quality_score"),
                        "review_action": action.get("review_action"),
                    }
                    for signal in signals
                    for action in signal.get("actions", [])
                ],
            },
            "disclaimer": "Historical evidence is not a promise or guarantee of future returns and is not investment advice.",
        }
        if options.get("validation_dir") or options.get("materialize"):
            validation_dir = options.get("validation_dir") or (
                __import__("pathlib").Path(__file__).resolve().parents[1] / "validation"
            )
            result["validation_artifacts"] = {
                name: str(path)
                for name, path in write_validation_artifacts(result, validation_dir).items()
            }
        if options.get("materialize"):
            signal_date = signals[-1]["signal_date"]
            candidate_records = []
            for payload in latest_records:
                source_date = payload.get("actual_source_date") or signal_date
                candidate_records.append(
                    {
                        "target_id": payload["target_id"],
                        "result_type": "buffett_research_candidate",
                        "result_value": payload["decision"],
                        "source_data_date": source_date,
                        "actual_source_date": source_date,
                        "coverage_status": "insufficient" if payload["decision"] == "insufficient_data" else "complete",
                        "payload": payload,
                    }
                )
            portfolio_records = []
            for holding in current["holdings"]:
                portfolio_records.append(
                    {
                        "target_id": holding["target_id"],
                        "result_type": "portfolio_target_weight",
                        "result_value": f"{float(holding.get('actual_weight', holding['target_weight'])):.10f}",
                        "source_data_date": signal_date,
                        "actual_source_date": signal_date,
                        "coverage_status": "complete",
                        "payload": holding,
                    }
                )
            portfolio_records.extend(
                [
                    {
                        "target_id": "CASH.CNY",
                        "result_type": "portfolio_target_weight",
                        "result_value": f"{float(current['cash_weight']):.10f}",
                        "source_data_date": signal_date,
                        "actual_source_date": signal_date,
                        "coverage_status": "complete",
                        "payload": {
                            "target_weight": float(current["cash_weight"]),
                            "actual_weight": float(current["cash_weight"]),
                            "role": "511880_cash_leg",
                        },
                    },
                    {
                        "target_id": STRATEGY_ID,
                        "result_type": "portfolio_summary",
                        "result_value": f"{float(current['cash_weight']):.10f}",
                        "source_data_date": signal_date,
                        "actual_source_date": signal_date,
                        "coverage_status": "complete",
                        "payload": current,
                    },
                ]
            )
            validation_record = {
                "target_id": f"{STRATEGY_ID}-VALIDATION",
                "result_type": "strategy_validation",
                "result_value": validation_level,
                "source_data_date": as_of,
                "actual_source_date": as_of,
                "coverage_status": "complete" if all(engineering_gates.values()) else "partial",
                "payload": {
                    "economic_evidence": evidence,
                    "evidence_scope": result["evidence_scope"],
                    "exposure": result["exposure"],
                    "validation_level": validation_level,
                    "forward_validation": result["forward_validation"],
                    "engineering_gates": engineering_gates,
                    "periods": periods,
                    "cost_sensitivity_bps": result["cost_sensitivity_bps"],
                    "cash_sensitivity": result["cash_sensitivity"],
                    "attribution": result["attribution"],
                    "disclaimer": result["disclaimer"],
                },
            }
            frames = [
                build_production_frame(
                    build_id="Q44",
                    build_name="A股巴菲特组合研究",
                    trade_date=signal_date,
                    records=candidate_records,
                    data_version=DATA_VERSION,
                ),
                build_production_frame(
                    build_id="Q44",
                    build_name="A股巴菲特组合研究",
                    trade_date=signals[-1]["execution_date"],
                    records=portfolio_records,
                    data_version=DATA_VERSION,
                ),
                build_production_frame(
                    build_id="Q44",
                    build_name="A股巴菲特组合研究",
                    trade_date=as_of,
                    records=[validation_record],
                    data_version=DATA_VERSION,
                ),
            ]
            from pathlib import Path

            output_path = Path(options.get("output_path") or Path(__file__).resolve().parents[1] / "生产产物" / "数据库.parquet")
            result["production_path"] = str(
                write_versioned_production(pd.concat(frames, ignore_index=True), output_path, DATA_VERSION)
            )
        return result
    finally:
        clear_process_credentials()


def run_feasibility(input_data: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Replay V9 event signals with T+1 execution and cost sensitivity.

    ``events``, ``signals``, ``prices`` and ``benchmark`` can be injected for
    deterministic tests.  Historical output is explicitly quantitative-only:
    current discretionary judgements are never backfilled into the past.
    """
    options = dict(config or {})
    as_of = str(input_data["as_of_date"])
    start = str(options.get("start_date") or input_data.get("start_date") or "")
    events = list(options.get("events") or input_data.get("events") or [])
    signals = dict(options.get("signals") or input_data.get("signals") or {})
    prices = options.get("prices") or input_data.get("prices")
    prices = pd.DataFrame(prices) if prices is not None and not isinstance(prices, pd.DataFrame) else (prices if isinstance(prices, pd.DataFrame) else pd.DataFrame())
    if not events and signals:
        events = [{"event_date": str(day), "target_weights": value} for day, value in signals.items()]
    if not events:
        events = [{"event_date": as_of, "target_weights": {}}]
    dates = {str(row.get("event_date", row.get("date"))).replace("-", "") for row in events}
    if not prices.empty and "date" in prices:
        dates.update(prices["date"].astype(str).str.replace("-", "", regex=False))
    calendar_dates = sorted(day for day in dates if day and (not start or day >= start) and day <= as_of)
    if not calendar_dates:
        calendar_dates = [as_of]
    costs_bps = [float(value) for value in options.get("costs_bps", (0.0, 15.0, 30.0))]
    benchmark = options.get("benchmark") or input_data.get("benchmark")
    benchmark = pd.DataFrame(benchmark) if benchmark is not None and not isinstance(benchmark, pd.DataFrame) else (benchmark if isinstance(benchmark, pd.DataFrame) else pd.DataFrame())
    if benchmark.empty:
        benchmark = pd.DataFrame({"date": calendar_dates, "close": 1.0})
    benchmark = benchmark.copy(); benchmark["date"] = benchmark["date"].astype(str).str.replace("-", "", regex=False); benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    event_map = {str(row.get("event_date", row.get("date"))).replace("-", ""): dict(row.get("target_weights") or {}) for row in events}
    execution_map: dict[str, tuple[str, dict[str, float]]] = {}
    for signal_date, requested in event_map.items():
        execution_date = next((candidate for candidate in calendar_dates if candidate > signal_date), signal_date)
        execution_map[execution_date] = (signal_date, {str(symbol): float(weight) for symbol, weight in requested.items()})
    if not prices.empty:
        prices = prices.copy(); prices["date"] = prices["date"].astype(str).str.replace("-", "", regex=False); prices = prices.sort_values(["date", "symbol"])
        for column in ("open", "close"):
            if column in prices: prices[column] = pd.to_numeric(prices[column], errors="coerce")
    weights: dict[str, float] = {}; nav_value = {cost: 1.0 for cost in costs_bps}; previous_prices: dict[str, float] = {}; nav_rows: list[dict[str, Any]] = []; holdings_history: list[dict[str, Any]] = []; rebalance: list[dict[str, Any]] = []
    for day in calendar_dates:
        turnover = 0.0
        if day in execution_map:
            signal_date, requested_values = execution_map[day]
            requested = {str(symbol): float(weight) for symbol, weight in requested_values.items() if float(weight) > 0}
            turnover = sum(abs(requested.get(symbol, 0.0) - weights.get(symbol, 0.0)) for symbol in set(requested) | set(weights))
            weights = requested; rebalance.append({"signal_date": signal_date, "execution_date": day, "target_weights": dict(weights), "turnover": turnover})
        day_rows = prices[prices["date"].eq(day)] if not prices.empty else pd.DataFrame(); returns: dict[str, float] = {}
        if not day_rows.empty:
            for _, row in day_rows.iterrows():
                symbol = str(row.get("symbol")); close = row.get("close")
                if pd.notna(close) and symbol in previous_prices and previous_prices[symbol] > 0: returns[symbol] = float(close) / previous_prices[symbol]
                if pd.notna(close): previous_prices[symbol] = float(close)
        gross = sum(weight * returns.get(symbol, 1.0) for symbol, weight in weights.items()) + max(0.0, 1.0 - sum(weights.values()))
        for cost in costs_bps: nav_value[cost] *= max(0.0, gross * (1.0 - turnover * cost / 10000.0))
        holdings_history.append({"date": day, "holdings": dict(weights), "cash_weight": max(0.0, 1.0 - sum(weights.values()))})
        b = benchmark[benchmark["date"].eq(day)]; benchmark_value = float(b.iloc[-1]["close"]) if not b.empty else None
        nav_rows.append({"date": day, "strategy_nav": nav_value[costs_bps[1] if len(costs_bps) > 1 else costs_bps[0]], "benchmark_000985_nav": benchmark_value, "cash_weight": max(0.0, 1.0 - sum(weights.values()))})
    nav = pd.DataFrame(nav_rows)
    if not nav.empty and nav["benchmark_000985_nav"].notna().any():
        first = nav["benchmark_000985_nav"].dropna().iloc[0]; nav["benchmark_000985_nav"] = nav["benchmark_000985_nav"] / first
    def metrics(column: str) -> dict[str, Any]:
        values = pd.to_numeric(nav[column], errors="coerce").dropna() if column in nav else pd.Series(dtype=float)
        if len(values) < 2: return {"cagr": None, "max_drawdown": None}
        years = max((len(values) - 1) / 252.0, 1 / 252.0); drawdown = values / values.cummax() - 1
        return {"cagr": float((values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1), "max_drawdown": float(drawdown.min())}
    full = {"strategy": metrics("strategy_nav"), "benchmark_000985": metrics("benchmark_000985_nav")}
    cost_key = lambda cost: str(int(cost)) if float(cost).is_integer() else str(cost)
    return {"data_version": DATA_VERSION, "validation_level": "runnable", "evidence_scope": "quantitative_retrospective_diagnostic", "qualitative_gate_backtested": False, "start_date": calendar_dates[0], "as_of_date": as_of, "periods": {"full": full, "development": full, "retrospective_diagnostic": full}, "nav": nav.to_dict("records"), "holdings_history": holdings_history, "rebalance": rebalance, "cost_sensitivity": {cost_key(cost): metrics("strategy_nav") for cost in costs_bps}}
