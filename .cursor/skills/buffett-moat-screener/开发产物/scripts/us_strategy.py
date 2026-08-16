"""Point-in-time Buffett-style research backtest for a fixed US-stock roster.

The Panda US daily endpoint is unadjusted and has no total-return field. This
module corrects recognizable split jumps and reports price returns only. The
fixed roster is a research universe, not historical S&P 500 membership or a
reconstruction of Berkshire Hathaway holdings.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))
VERIFIED_PRICE_START = "20150102"
TRANSACTION_COST_BPS = 15.0
HOLD_TOP = 8

# Panda's US close history is inconsistent across corporate actions: Visa's
# older history is already back-adjusted, while Apple and Walmart retain a raw
# split jump. Apply a correction only when both the event and observed ratio
# agree; never infer a split from a large market loss.
KNOWN_SPLITS = {
    ("V", "2015-03-19"): 4.0,
    ("AAPL", "2020-08-31"): 4.0,
    ("WMT", "2024-02-26"): 3.0,
}

US_ROSTER_META = [
    ("AAPL", "Apple", "Technology Hardware", "品牌生态、服务收入与高资本回报"),
    ("MSFT", "Microsoft", "Software", "企业软件、云服务与订阅收入护城河"),
    ("KO", "Coca-Cola", "Beverages", "全球品牌、渠道与浓缩液轻资产模式"),
    ("AXP", "American Express", "Financial Services", "闭环支付网络与高价值客户黏性"),
    ("MCO", "Moody's", "Financial Information", "信用评级双寡头与数据订阅收入"),
    ("V", "Visa", "Payments", "全球支付网络效应与轻资产收费模式"),
    ("MA", "Mastercard", "Payments", "全球支付网络效应与跨境交易优势"),
    ("COST", "Costco", "Warehouse Retail", "会员制、低加价率与规模采购优势"),
    ("PG", "Procter & Gamble", "Consumer Staples", "日用消费品牌组合与全球分销"),
    ("WMT", "Walmart", "Warehouse Retail", "采购规模、供应链与全渠道零售"),
    ("OXY", "Occidental Petroleum", "Energy", "油气资源与周期现金流，需保留周期风险"),
    ("HD", "Home Depot", "Home Improvement", "专业客户网络、规模采购与门店效率"),
]

US_ROSTER = [symbol for symbol, *_ in US_ROSTER_META]
US_NAMES = {symbol: name for symbol, name, _, _ in US_ROSTER_META}
US_INDUSTRY = {symbol: industry for symbol, _, industry, _ in US_ROSTER_META}
US_THESIS = {symbol: thesis for symbol, _, _, thesis in US_ROSTER_META}

FINANCIAL_FIELDS = [
    "symbol",
    "is_net_income",
    "bs_common_equity_total",
    "bs_total_assets",
    "is_gross_profit",
    "is_revenue_goods_services",
    "cfs_capex_total",
    "bs_debt_lt_total",
    "is_eps_basic_inc_exord",
    "is_op_profit_before_non_recurring",
]


def _slice_date_ranges(start: str, end: str, years: int = 4) -> list[tuple[str, str]]:
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    ranges: list[tuple[str, str]] = []
    cursor = start_ts
    while cursor <= end_ts:
        range_end = min(cursor + pd.DateOffset(years=years) - pd.Timedelta(days=1), end_ts)
        ranges.append((cursor.strftime("%Y%m%d"), range_end.strftime("%Y%m%d")))
        cursor = range_end + pd.Timedelta(days=1)
    return ranges


def _slice_quarter_ranges(start_year: int, end_year: int) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    cursor = start_year
    while cursor <= end_year:
        range_end = min(cursor + 4, end_year)
        ranges.append((f"{cursor}q1", f"{range_end}q4"))
        cursor = range_end + 1
    return ranges


def fetch_us_prices(symbols: Iterable[str], start: str, end: str) -> pd.DataFrame:
    from scripts.dp_cache import cached_call

    frames: list[pd.DataFrame] = []
    fields = ["symbol", "date", "close", "pre_close"]
    for range_start, range_end in _slice_date_ranges(start, end):
        frame = cached_call(
            "get_us_daily",
            symbol=sorted(set(symbols)),
            start_date=range_start,
            end_date=range_end,
            fields=fields,
        )
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=fields)
    prices = pd.concat(frames, ignore_index=True)
    prices["symbol"] = prices["symbol"].astype(str).str.replace(r"\.NB$", "", regex=True)
    prices["date"] = pd.to_datetime(prices["date"].astype(str), errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices["pre_close"] = pd.to_numeric(prices.get("pre_close"), errors="coerce")
    return (
        prices.dropna(subset=["symbol", "date", "close"])
        .drop_duplicates(["symbol", "date"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )


def fetch_us_financials(symbols: Iterable[str], start_year: int, end_year: int) -> pd.DataFrame:
    from scripts.dp_cache import cached_call

    frames: list[pd.DataFrame] = []
    for start_quarter, end_quarter in _slice_quarter_ranges(start_year, end_year):
        frame = cached_call(
            "get_fina_ex",
            symbol=sorted(set(symbols)),
            start_quarter=start_quarter,
            end_quarter=end_quarter,
            is_latest=False,
            fields=FINANCIAL_FIELDS,
        )
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "fy_period", *FINANCIAL_FIELDS[1:]])
    financials = pd.concat(frames, ignore_index=True)
    financials["symbol"] = financials["symbol"].astype(str).str.replace(r"\.NB$", "", regex=True)
    financials["date"] = pd.to_datetime(financials["date"].astype(str), errors="coerce")
    financials["fy_period"] = financials["fy_period"].astype(str)
    for column in FINANCIAL_FIELDS[1:]:
        if column in financials:
            financials[column] = pd.to_numeric(financials[column], errors="coerce")
    return (
        financials.dropna(subset=["symbol", "date", "fy_period"])
        .drop_duplicates(["symbol", "fy_period", "date"], keep="last")
        .sort_values(["symbol", "date", "fy_period"])
        .reset_index(drop=True)
    )


def _safe_ratio(numerator: Any, denominator: Any, scale: float = 1.0) -> float | None:
    try:
        value = float(numerator) / float(denominator) * scale
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return value if math.isfinite(value) else None


def _mean(values: Iterable[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.mean(finite)) if finite else None


def _point_in_time_annuals(financials: pd.DataFrame, symbol: str, signal_date: pd.Timestamp) -> pd.DataFrame:
    visible = financials[
        (financials["symbol"] == symbol)
        & (financials["date"] <= signal_date)
        & financials["fy_period"].str.endswith("Q4")
    ].copy()
    if visible.empty:
        return visible
    visible["fiscal_year"] = pd.to_numeric(
        visible["fy_period"].str.extract(r"FY(\d{4})", expand=False), errors="coerce"
    )
    return (
        visible.dropna(subset=["fiscal_year"])
        .sort_values(["fiscal_year", "date"])
        .drop_duplicates("fiscal_year", keep="last")
        .sort_values("fiscal_year")
    )


def build_metrics(
    financials: pd.DataFrame,
    symbol: str,
    signal_date: pd.Timestamp,
    signal_close: float | None,
) -> dict[str, Any]:
    annuals = _point_in_time_annuals(financials, symbol, signal_date)
    last_ten = annuals.tail(10)
    last_five = annuals.tail(5)

    roe_values = [
        _safe_ratio(row.get("is_net_income"), row.get("bs_common_equity_total"), 100.0)
        for _, row in last_ten.iterrows()
    ]
    gross_values = [
        _safe_ratio(row.get("is_gross_profit"), row.get("is_revenue_goods_services"), 100.0)
        for _, row in last_five.iterrows()
    ]
    op_margin_values = [
        _safe_ratio(
            row.get("is_op_profit_before_non_recurring"),
            row.get("is_revenue_goods_services"),
            100.0,
        )
        for _, row in last_five.iterrows()
    ]
    gross_finite = [value for value in gross_values if value is not None]
    net_income_sum = pd.to_numeric(last_five.get("is_net_income"), errors="coerce").sum(min_count=1)
    capex_sum = pd.to_numeric(last_five.get("cfs_capex_total"), errors="coerce").abs().sum(min_count=1)
    capex_to_profit = (
        _safe_ratio(capex_sum, net_income_sum)
        if pd.notna(net_income_sum) and float(net_income_sum) > 0 and pd.notna(capex_sum)
        else None
    )
    latest = annuals.iloc[-1] if not annuals.empty else None
    latest_eps = float(latest["is_eps_basic_inc_exord"]) if latest is not None and pd.notna(latest.get("is_eps_basic_inc_exord")) else None
    current_pe = (
        _safe_ratio(signal_close, latest_eps)
        if signal_close is not None and latest_eps is not None and latest_eps > 0
        else None
    )
    latest_profit = float(latest["is_net_income"]) if latest is not None and pd.notna(latest.get("is_net_income")) else None
    latest_debt_to_equity = (
        _safe_ratio(latest.get("bs_debt_lt_total"), latest.get("bs_common_equity_total"))
        if latest is not None
        else None
    )

    counts = {
        "roe_years": sum(value is not None for value in roe_values),
        "gross_margin_years": len(gross_finite),
        "capex_years": int(last_five[["cfs_capex_total", "is_net_income"]].dropna().shape[0]) if not last_five.empty else 0,
        "operating_margin_years": sum(value is not None for value in op_margin_values),
    }
    # The provider starts most US fundamentals around FY2013. Preserve partial
    # early history and penalize it instead of claiming a complete 10-year mean.
    history_coverage = (
        0.30 * min(counts["roe_years"] / 10.0, 1.0)
        + 0.25 * min(counts["gross_margin_years"] / 5.0, 1.0)
        + 0.15 * min(counts["capex_years"] / 5.0, 1.0)
        + 0.15 * min(counts["operating_margin_years"] / 5.0, 1.0)
        + 0.15 * (1.0 if current_pe is not None else 0.0)
    )
    enough_history = counts["roe_years"] >= 2 and min(
        counts["gross_margin_years"], counts["capex_years"], counts["operating_margin_years"]
    ) >= 2
    return {
        "roe_mean_pct": _mean(roe_values) if enough_history else None,
        "gross_margin_mean_5y_pct": _mean(gross_values) if enough_history else None,
        "gross_margin_std_5y_pct_points": float(np.std(gross_finite, ddof=0)) if enough_history and gross_finite else None,
        "capex_to_profit_5y": capex_to_profit if enough_history else None,
        "operating_margin_mean_5y_pct": _mean(op_margin_values) if enough_history else None,
        "current_pe": current_pe,
        "latest_net_income": latest_profit,
        "latest_debt_to_equity": latest_debt_to_equity,
        "annual_report_count": int(len(annuals)),
        "latest_report_date": latest["date"].strftime("%Y%m%d") if latest is not None else None,
        "latest_fy_period": str(latest["fy_period"]) if latest is not None else None,
        "history_counts": counts,
        "history_coverage_ratio": round(float(history_coverage), 4),
    }


def _split_adjusted_return(
    close: Any, pre_close: Any, known_factor: float | None = None
) -> tuple[float | None, float]:
    raw_ratio = _safe_ratio(close, pre_close)
    if raw_ratio is None or raw_ratio <= 0:
        return None, 1.0
    if known_factor and known_factor > 0:
        corrected_ratio = raw_ratio * known_factor
        if 0.80 <= corrected_ratio <= 1.20:
            return corrected_ratio - 1.0, float(known_factor)
    return raw_ratio - 1.0, 1.0


def _return_matrix(prices: pd.DataFrame, symbols: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    subset = prices[prices["symbol"].isin(symbols)].copy()
    if subset.empty:
        return pd.DataFrame(), []
    corrected: list[float | None] = []
    factors: list[float] = []
    for symbol, date, close, pre_close in zip(
        subset["symbol"], subset["date"], subset["close"], subset["pre_close"]
    ):
        known_factor = KNOWN_SPLITS.get((str(symbol), pd.Timestamp(date).strftime("%Y-%m-%d")))
        value, factor = _split_adjusted_return(close, pre_close, known_factor)
        corrected.append(value)
        factors.append(factor)
    subset["price_return"] = corrected
    subset["split_factor"] = factors
    split_events = [
        {
            "symbol": str(row.symbol),
            "date": row.date.strftime("%Y-%m-%d"),
            "detected_factor": float(row.split_factor),
        }
        for row in subset.itertuples()
        if float(row.split_factor) != 1.0
    ]
    matrix = subset.pivot_table(index="date", columns="symbol", values="price_return", aggfunc="last").sort_index()
    return matrix, split_events


def _annual_signal_dates(index: pd.DatetimeIndex, start: str, end: str) -> list[pd.Timestamp]:
    dates = index[(index >= pd.to_datetime(start)) & (index <= pd.to_datetime(end))]
    if dates.empty:
        return []
    return [pd.Timestamp(group.iloc[0]) for _, group in pd.Series(dates, index=dates).groupby(dates.year)]


def _select_portfolio(candidates: list[dict[str, Any]], incumbents: list[str]) -> list[str]:
    by_symbol = {str(row["symbol"]): row for row in candidates}
    selected: list[str] = []
    industry_counts: dict[str, int] = {}

    def add(symbol: str) -> bool:
        row = by_symbol.get(symbol)
        if not row or not row.get("soft_eligible") or row.get("sell_triggers"):
            return False
        industry = str(row.get("industry") or "")
        if industry and industry_counts.get(industry, 0) >= 2:
            return False
        selected.append(symbol)
        if industry:
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
        return True

    for symbol in incumbents:
        if len(selected) >= HOLD_TOP:
            break
        add(symbol)
    for row in candidates:
        if len(selected) >= HOLD_TOP:
            break
        symbol = str(row["symbol"])
        if symbol not in selected:
            add(symbol)
    return selected


def _performance(nav: pd.Series) -> dict[str, float]:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "annual_volatility": 0.0, "sharpe": 0.0}
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    daily = nav.pct_change().dropna()
    annual_volatility = float(daily.std() * np.sqrt(252)) if not daily.empty else 0.0
    return {
        "total_return": total_return,
        "cagr": float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0),
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
        "annual_volatility": annual_volatility,
        "sharpe": float(daily.mean() / daily.std() * np.sqrt(252)) if not daily.empty and daily.std() > 0 else 0.0,
    }


def run_us_backtest(start: str, end: str) -> dict[str, Any]:
    from scripts.soft_scorer import score_payload

    requested_start = start
    effective_start = max(pd.to_datetime(start), pd.to_datetime(VERIFIED_PRICE_START)).strftime("%Y%m%d")
    prices = fetch_us_prices([*US_ROSTER, "SPY"], effective_start, end)
    if prices.empty:
        raise RuntimeError("Panda get_us_daily returned no usable rows for the verified US period")
    financials = fetch_us_financials(US_ROSTER, 2010, pd.to_datetime(end).year)
    returns, split_events = _return_matrix(prices, [*US_ROSTER, "SPY"])
    if returns.empty:
        raise RuntimeError("US price-return matrix is empty")
    signal_dates = _annual_signal_dates(returns.index, effective_start, end)
    strategy_returns = pd.Series(0.0, index=returns.index, dtype=float)
    holdings_log: list[dict[str, Any]] = []
    incumbents: list[str] = []

    close_matrix = prices.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    for index, signal_date in enumerate(signal_dates):
        candidates: list[dict[str, Any]] = []
        for symbol in US_ROSTER:
            close_series = close_matrix.get(symbol)
            visible_close = close_series.loc[:signal_date].dropna() if close_series is not None else pd.Series(dtype=float)
            signal_close = float(visible_close.iloc[-1]) if not visible_close.empty else None
            metrics = build_metrics(financials, symbol, signal_date, signal_close)
            scored = score_payload(
                {"target_id": symbol, "industry": US_INDUSTRY[symbol], "metrics": metrics}
            )
            history_coverage = float(metrics["history_coverage_ratio"])
            scored["base_soft_score"] = float(scored["total_score"])
            scored["history_coverage_ratio"] = history_coverage
            scored["total_score"] = round(float(scored["total_score"]) * (0.70 + 0.30 * history_coverage), 4)
            scored["soft_eligible"] = bool(scored["soft_eligible"] and history_coverage >= 0.35 and signal_close is not None)
            sell_triggers: list[str] = []
            if metrics.get("latest_net_income") is not None and float(metrics["latest_net_income"]) <= 0:
                sell_triggers.append("annual_profit_nonpositive")
            if signal_close is None:
                sell_triggers.append("price_unavailable")
            scored.update(
                {
                    "name": US_NAMES[symbol],
                    "thesis": US_THESIS[symbol],
                    "sell_triggers": sell_triggers,
                }
            )
            candidates.append(scored)
        candidates.sort(
            key=lambda row: (
                not bool(row["soft_eligible"]),
                -float(row["total_score"]),
                -float(row["history_coverage_ratio"]),
                str(row["symbol"]),
            )
        )
        picks = _select_portfolio(candidates, incumbents)
        new_entries = [symbol for symbol in picks if symbol not in incumbents]
        kept = [symbol for symbol in picks if symbol in incumbents]
        removed = [symbol for symbol in incumbents if symbol not in picks]
        old_weights = {symbol: 1.0 / len(incumbents) for symbol in incumbents} if incumbents else {}
        new_weights = {symbol: 1.0 / len(picks) for symbol in picks} if picks else {}
        turnover = 0.5 * (
            sum(
                abs(new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0))
                for symbol in set(old_weights) | set(new_weights)
            )
            + abs((0.0 if new_weights else 1.0) - (0.0 if old_weights else 1.0))
        )
        next_signal = signal_dates[index + 1] if index + 1 < len(signal_dates) else returns.index[-1]
        holding_mask = (returns.index > signal_date) & (returns.index <= next_signal)
        if picks:
            strategy_returns.loc[holding_mask] = returns.loc[holding_mask, picks].fillna(0.0).mean(axis=1)
        if signal_date in strategy_returns.index:
            strategy_returns.loc[signal_date] -= turnover * TRANSACTION_COST_BPS / 10000.0
        candidate_map = {str(row["symbol"]): row for row in candidates}
        removed_reasons = []
        for symbol in removed:
            row = candidate_map.get(symbol, {})
            triggers = list(row.get("sell_triggers") or [])
            removed_reasons.append(
                {
                    "symbol": symbol,
                    "name": US_NAMES[symbol],
                    "sell_triggers": triggers,
                    "reason": "、".join(triggers) if triggers else "固定研究池内状态不再满足可持有条件",
                }
            )
        holdings_log.append(
            {
                "date": signal_date.strftime("%Y%m%d"),
                "candidates": sum(bool(row["soft_eligible"]) for row in candidates),
                "picks": picks,
                "new_entries": new_entries,
                "kept": kept,
                "removed": removed,
                "turnover": float(turnover),
                "transaction_cost_bps": TRANSACTION_COST_BPS,
                "entry_details": [
                    {
                        "symbol": symbol,
                        "name": US_NAMES[symbol],
                        "industry": US_INDUSTRY[symbol],
                        "reason": US_THESIS[symbol],
                        "soft_score": candidate_map[symbol]["total_score"],
                        "base_soft_score": candidate_map[symbol]["base_soft_score"],
                        "score_coverage": candidate_map[symbol]["coverage_ratio"],
                        "history_coverage": candidate_map[symbol]["history_coverage_ratio"],
                        "metrics": candidate_map[symbol]["metrics"],
                    }
                    for symbol in picks
                ],
                "removed_reasons": removed_reasons,
                "reason_summary": (
                    f"固定美股研究池按点时财报软评分；长期持有优先。新入 {len(new_entries)}、"
                    f"保留 {len(kept)}、退出 {len(removed)}；最多 {HOLD_TOP} 只、同一行业最多 2 只。"
                ),
            }
        )
        incumbents = picks

    strategy_nav = (1.0 + strategy_returns.fillna(0.0)).cumprod()
    if not strategy_nav.empty:
        strategy_nav.iloc[0] = 1.0
    spy_returns = returns.get("SPY", pd.Series(dtype=float)).dropna()
    spy_nav = (1.0 + spy_returns).cumprod() if not spy_returns.empty else pd.Series(dtype=float)
    if not spy_nav.empty:
        spy_nav.iloc[0] = 1.0
    return {
        "market": "us",
        "mode": "fixed_research_roster_soft",
        "requested_start": requested_start,
        "start": effective_start,
        "end": end,
        "verified_price_start": VERIFIED_PRICE_START,
        "universe": US_ROSTER,
        "universe_size": len(US_ROSTER),
        "universe_definition": "fixed_research_roster_not_historical_sp500_or_berkshire_holdings",
        "financial_source": "Panda Data get_fina_ex, publication-date point-in-time filter",
        "price_source": "Panda Data get_us_daily",
        "return_definition": "explicit-known-split-adjusted price return; cash dividends excluded",
        "score_version": "soft-five-dimension-v1+history-coverage-v1",
        "transaction_cost_bps": TRANSACTION_COST_BPS,
        "portfolio_constraints": {"hold_top": HOLD_TOP, "max_names_per_industry": 2},
        "nav": {date.strftime("%Y-%m-%d"): float(value) for date, value in strategy_nav.items()},
        "benchmark_symbol": "SPY" if not spy_nav.empty else None,
        "benchmark_status": "available" if not spy_nav.empty else "unavailable_from_panda_get_us_daily",
        "benchmark_nav": {date.strftime("%Y-%m-%d"): float(value) for date, value in spy_nav.items()},
        "performance": _performance(strategy_nav),
        "benchmark_performance": _performance(spy_nav) if not spy_nav.empty else None,
        "holdings_log": holdings_log,
        "split_events": split_events,
        "coverage_note": "Panda US prices returned no usable 2010-2014 history; verified strategy starts in 2015. Fundamentals are sparse before FY2013 and are penalized by history coverage.",
    }


def _consume_credentials() -> tuple[str, str, str | None]:
    username = os.environ.pop("PANDA_DATA_USERNAME", "")
    password = os.environ.pop("PANDA_DATA_PASSWORD", "")
    base_url = os.environ.pop("PANDA_DATA_BASE_URL", "") or None
    if not username or not password:
        raise RuntimeError("PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD must be set")
    return username, password, base_url


def _login(username: str, password: str, base_url: str | None) -> None:
    import panda_data
    from panda_data.client import init as client_init

    kwargs: dict[str, Any] = {"username": username, "password": password}
    if base_url:
        kwargs["base_url"] = base_url
    panda_data.init_token(**kwargs)
    client_init(**kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=VERIFIED_PRICE_START)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default=str(ROOT / "生产产物" / "backtest_us_fixed_roster.json"))
    args = parser.parse_args()
    username, password, base_url = _consume_credentials()
    _login(username, password, base_url)
    del username, password, base_url
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "us": run_us_backtest(args.start, args.end),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
