from __future__ import annotations

import argparse
from datetime import timedelta
from typing import Any

import pandas as pd

from factor import (
    FACTOR_MODE_FINAL,
    calculate_factor,
    load_real_lhb_details,
    load_real_quotes,
    load_real_trade_calendar,
    sample_lhb_detail,
    sample_quotes,
    sample_trade_calendar,
)


DEFAULT_ROUND_TRIP_COST = 0.003
DEFAULT_LIMIT_BUFFER = 0.001


def _normalise_quotes(input_data: Any) -> pd.DataFrame:
    df = pd.DataFrame(input_data).copy()
    rename = {}
    if "symbol" in df.columns and "ts_code" not in df.columns:
        rename["symbol"] = "ts_code"
    if "date" in df.columns and "trade_date" not in df.columns:
        rename["date"] = "trade_date"
    df = df.rename(columns=rename)
    required = {"trade_date", "ts_code", "open", "close", "limit_up"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"行情数据缺少字段: {sorted(missing)}")
    if "trade_status" not in df.columns:
        df["trade_status"] = ""
    keep = ["trade_date", "ts_code", "open", "close", "limit_up", "trade_status"]
    df = df[keep].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="raise").dt.strftime("%Y-%m-%d")
    df["ts_code"] = df["ts_code"].astype(str)
    for col in ["open", "close", "limit_up"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _tradable_status(values: pd.Series) -> pd.Series:
    text = values.fillna("").astype(str).str.strip().str.lower()
    bad = text.isin({"false", "no", "n", "停牌", "暂停", "suspend", "halt", "退市"})
    return ~bad


def build_executable_forward_returns(
    quotes: Any,
    round_trip_cost: float = DEFAULT_ROUND_TRIP_COST,
    limit_buffer: float = DEFAULT_LIMIT_BUFFER,
) -> pd.DataFrame:
    """Build executable returns: buy at t+1 open, skip limit-up/suspended, sell at t+2 close."""
    df = _normalise_quotes(quotes)
    grouped = df.groupby("ts_code", sort=False)
    df["entry_open"] = grouped["open"].shift(-1)
    df["entry_limit_up"] = grouped["limit_up"].shift(-1)
    df["entry_trade_status"] = grouped["trade_status"].shift(-1)
    df["exit_close"] = grouped["close"].shift(-2)
    df["gross_return"] = df["exit_close"] / df["entry_open"] - 1.0
    df["forward_return"] = df["gross_return"] - float(round_trip_cost)
    df["executable"] = (
        df["entry_open"].gt(0)
        & df["exit_close"].gt(0)
        & df["entry_limit_up"].gt(0)
        & df["entry_open"].lt(df["entry_limit_up"].mul(1.0 - float(limit_buffer)))
        & _tradable_status(df["entry_trade_status"])
    )
    return df[
        [
            "trade_date",
            "ts_code",
            "entry_open",
            "entry_limit_up",
            "exit_close",
            "gross_return",
            "forward_return",
            "executable",
        ]
    ].dropna(subset=["gross_return", "forward_return"]).reset_index(drop=True)


def build_forward_returns(quotes: Any) -> pd.DataFrame:
    """Compatibility alias; all final evaluations use executable returns."""
    frame = build_executable_forward_returns(quotes)
    return frame.loc[frame["executable"], ["trade_date", "ts_code", "forward_return"]].reset_index(drop=True)


def _daily_rank_ic(frame: pd.DataFrame) -> float:
    if len(frame) < 2:
        return float("nan")
    factor_rank = frame["factor_value"].rank()
    return_rank = frame["forward_return"].rank()
    if factor_rank.nunique() < 2 or return_rank.nunique() < 2:
        return float("nan")
    return float(factor_rank.corr(return_rank))


def _ir(returns: pd.Series) -> float:
    std = returns.std()
    return 0.0 if returns.empty or pd.isna(std) or std == 0 else float(returns.mean() / std * (252**0.5))


def _mdd(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    curve = (1.0 + returns).cumprod()
    return float((curve / curve.cummax() - 1.0).min())


def _turnover(panel: pd.DataFrame, dates: list[str]) -> float:
    selected = panel.loc[panel["signal"].eq("buy")].groupby("trade_date")["ts_code"].apply(set).to_dict()
    previous: set[str] | None = None
    values = []
    for trade_date in dates:
        current = selected.get(trade_date, set())
        if previous is not None:
            union = current | previous
            values.append(1.0 - len(current & previous) / len(union) if union else 0.0)
        previous = current
    return float(pd.Series(values).mean()) if values else 0.0


def _layer_metrics(panel: pd.DataFrame, layers: int = 5) -> dict[str, Any]:
    ranked = panel.copy()
    pct_rank = ranked.groupby("trade_date")["factor_value"].rank(pct=True, method="average")
    ranked["layer"] = ((pct_rank * layers - 1e-12).astype(int) + 1).clip(1, layers)
    layer_mean = ranked.groupby("layer")["forward_return"].mean()
    layer_count = ranked.groupby("layer")["forward_return"].size()
    daily = ranked.groupby(["trade_date", "layer"])["forward_return"].mean().unstack()
    long_short = daily.get(layers, pd.Series(dtype=float)) - daily.get(1, pd.Series(dtype=float))
    long_short = long_short.dropna()
    return {
        "layer_mean": {f"L{layer}": float(layer_mean.get(layer, 0.0)) for layer in range(1, layers + 1)},
        "layer_count": {f"L{layer}": int(layer_count.get(layer, 0)) for layer in range(1, layers + 1)},
        "long_short_mean": float(long_short.mean()) if not long_short.empty else 0.0,
        "long_short_ir": _ir(long_short),
        "long_short_mdd": _mdd(long_short),
    }


def _signal_samples(panel: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    columns = [
        "trade_date",
        "ts_code",
        "factor_value",
        "signal",
        "entry_open",
        "exit_close",
        "forward_return",
        "executable",
    ]
    sample = panel.loc[panel["signal"].eq("buy"), columns].sort_values(
        ["trade_date", "factor_value"],
        ascending=[False, False],
    ).head(limit)
    return sample.round({"factor_value": 6, "entry_open": 4, "exit_close": 4, "forward_return": 6}).to_dict("records")


def run_backtest(
    factor: pd.DataFrame,
    quotes: Any,
    round_trip_cost: float = DEFAULT_ROUND_TRIP_COST,
    limit_buffer: float = DEFAULT_LIMIT_BUFFER,
) -> dict[str, Any]:
    returns = build_executable_forward_returns(quotes, round_trip_cost=round_trip_cost, limit_buffer=limit_buffer)
    all_panel = factor.merge(returns, on=["trade_date", "ts_code"], how="inner")
    panel = all_panel.loc[all_panel["executable"]].copy()
    if panel.empty:
        raise ValueError("没有可成交评估样本")

    dates = sorted(panel["trade_date"].unique())
    daily_rank_ic = panel.groupby("trade_date")[["factor_value", "forward_return"]].apply(_daily_rank_ic).dropna()
    split_date = dates[len(dates) // 2]
    train_ic = daily_rank_ic.loc[daily_rank_ic.index <= split_date]
    test_ic = daily_rank_ic.loc[daily_rank_ic.index > split_date]
    yearly_ic = daily_rank_ic.groupby(daily_rank_ic.index.astype(str).str[:4]).mean()

    buy_all = factor.loc[factor["signal"].eq("buy"), ["trade_date", "ts_code"]]
    buy = panel.loc[panel["signal"].eq("buy")].copy()
    buy_daily = buy.groupby("trade_date")["forward_return"].mean().reindex(dates).fillna(0.0)
    buy_yearly = buy.groupby(buy["trade_date"].str[:4])["forward_return"].mean()
    buy_train = buy.loc[buy["trade_date"] <= split_date, "forward_return"]
    buy_test = buy.loc[buy["trade_date"] > split_date, "forward_return"]
    layers = _layer_metrics(panel)

    metrics = {
        "evaluation_rule": "signal after t close; buy t+1 open; skip suspended/open-limit-up; sell t+2 close",
        "round_trip_cost": float(round_trip_cost),
        "limit_buffer": float(limit_buffer),
        "rows": int(len(panel)),
        "days": int(len(dates)),
        "rank_ic": float(daily_rank_ic.mean()),
        "rank_icir": float(daily_rank_ic.mean() / daily_rank_ic.std()) if daily_rank_ic.std() else 0.0,
        "train_rank_ic": float(train_ic.mean()),
        "test_rank_ic": float(test_ic.mean()),
        "worst_year_rank_ic": float(yearly_ic.min()),
        "split_date": split_date,
        "buy_signal_count": int(len(buy_all)),
        "buy_executable_count": int(len(buy)),
        "buy_blocked_count": int(len(buy_all) - len(buy)),
        "buy_active_days": int(buy["trade_date"].nunique()),
        "buy_mean": float(buy["forward_return"].mean()) if not buy.empty else 0.0,
        "buy_win_rate": float(buy["forward_return"].gt(0).mean()) if not buy.empty else 0.0,
        "buy_ir": _ir(buy_daily),
        "buy_mdd": _mdd(buy_daily),
        "buy_turnover": _turnover(panel, dates),
        "buy_train_mean": float(buy_train.mean()) if not buy_train.empty else 0.0,
        "buy_test_mean": float(buy_test.mean()) if not buy_test.empty else 0.0,
        "buy_worst_year_mean": float(buy_yearly.min()) if not buy_yearly.empty else 0.0,
        "buy_yearly_mean": {str(key): float(value) for key, value in buy_yearly.items()},
        "signal_samples": _signal_samples(all_panel),
    }
    metrics.update(layers)
    return metrics


def release_checks(metrics: dict[str, Any]) -> dict[str, bool]:
    return {
        "sample_days": metrics["days"] >= 500,
        "rank_ic": metrics["rank_ic"] >= 0.03,
        "test_rank_ic": metrics["test_rank_ic"] >= 0.02,
        "buy_samples": metrics["buy_executable_count"] >= 15,
        "buy_mean": metrics["buy_mean"] >= 0.01,
        "buy_win_rate": metrics["buy_win_rate"] >= 0.55,
        "buy_train": metrics["buy_train_mean"] > 0,
        "buy_test": metrics["buy_test_mean"] > 0,
        "buy_worst_year": metrics["buy_worst_year_mean"] > 0,
        "buy_mdd": metrics["buy_mdd"] >= -0.25,
    }


def _detail_symbols(details: Any) -> list[str]:
    frame = pd.DataFrame(details)
    column = "symbol" if "symbol" in frame.columns else "ts_code"
    return sorted(frame[column].astype(str).unique())


def _shift(value: str, days: int) -> str:
    return (pd.to_datetime(value).date() + timedelta(days=days)).strftime("%Y%m%d")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回测最终版 A06 可成交因子")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--round-trip-cost", type=float, default=DEFAULT_ROUND_TRIP_COST)
    parser.add_argument("--limit-buffer", type=float, default=DEFAULT_LIMIT_BUFFER)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.real:
        if not args.start_date or not args.end_date:
            raise ValueError("--real 必须提供 --start-date 和 --end-date")
        fetch_start = _shift(args.start_date, -260)
        quote_end = _shift(args.end_date, 10)
        details = load_real_lhb_details(fetch_start, args.end_date)
        calendar = load_real_trade_calendar(fetch_start, quote_end)
        quotes = load_real_quotes(fetch_start, quote_end, _detail_symbols(details))
        factor = calculate_factor(
            details,
            calendar,
            quotes=quotes,
            factor_mode=FACTOR_MODE_FINAL,
            dynamic_seat_quality=False,
        )
        factor = factor.loc[
            (pd.to_datetime(factor["trade_date"]) >= pd.to_datetime(args.start_date))
            & (pd.to_datetime(factor["trade_date"]) <= pd.to_datetime(args.end_date))
        ]
    else:
        quotes = sample_quotes()
        factor = calculate_factor(sample_lhb_detail(), sample_trade_calendar(), quotes=quotes, dynamic_seat_quality=False)
    metrics = run_backtest(factor, quotes, args.round_trip_cost, args.limit_buffer)
    checks = release_checks(metrics)
    for key, value in metrics.items():
        print(f"{key}: {value}")
    print(f"release_pass: {all(checks.values())}")
    print(f"failed_checks: {[key for key, passed in checks.items() if not passed]}")


if __name__ == "__main__":
    main()
