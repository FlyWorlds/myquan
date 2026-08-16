from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from backtest import release_checks, run_backtest
from factor import (
    DIAGNOSTIC_COLUMNS,
    FACTOR_ID,
    STANDARD_COLUMNS,
    calculate_factor,
    extract_calendar_trade_dates,
    load_real_lhb_details,
    load_real_quotes,
    load_real_trade_calendar,
    sample_lhb_detail,
    sample_quotes,
    sample_trade_calendar,
    validate_production_output,
)


def _symbols(details: pd.DataFrame) -> list[str]:
    column = "symbol" if "symbol" in details.columns else "ts_code"
    return sorted(details[column].astype(str).unique())


def _build(real: bool, start_date: str | None, end_date: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if real:
        if not start_date or not end_date:
            raise ValueError("--real 必须提供 --start-date 和 --end-date")
        details = load_real_lhb_details(start_date, end_date)
        calendar = load_real_trade_calendar(start_date, end_date)
        quotes = load_real_quotes(start_date, end_date, _symbols(pd.DataFrame(details)))
    else:
        details = sample_lhb_detail()
        calendar = sample_trade_calendar()
        quotes = sample_quotes()
    factor = calculate_factor(details, calendar, quotes=quotes, dynamic_seat_quality=False, update_time="2026-06-12T15:30:00")
    return factor, pd.DataFrame(quotes)


def check_schema(factor: pd.DataFrame, calendar: pd.DataFrame) -> None:
    missing = set(STANDARD_COLUMNS + DIAGNOSTIC_COLUMNS) - set(factor.columns)
    assert not missing, f"结果缺少字段: {sorted(missing)}"
    validate_production_output(factor, valid_trade_dates=extract_calendar_trade_dates(calendar))
    assert set(factor["factor_id"]) == {FACTOR_ID}
    assert factor["confidence"].between(0, 1).all()
    assert factor["factor_value"].notna().all()


def check_no_future_function(details: pd.DataFrame, calendar: pd.DataFrame, quotes: pd.DataFrame) -> None:
    full = calculate_factor(details, calendar, quotes=quotes, dynamic_seat_quality=False, update_time="2026-06-12T15:30:00")
    last_date = full["trade_date"].max()
    quote_cut = quotes.loc[pd.to_datetime(quotes["trade_date"]) <= pd.to_datetime(last_date)].copy()
    detail_date = "date" if "date" in details.columns else "trade_date"
    detail_cut = details.loc[pd.to_datetime(details[detail_date].astype(str)) <= pd.to_datetime(last_date)].copy()
    cal_date = next(col for col in ["trade_date", "date", "nature_date", "cal_date"] if col in calendar.columns)
    cal_cut = calendar.loc[pd.to_datetime(calendar[cal_date].astype(str)) <= pd.to_datetime(last_date)].copy()
    recalculated = calculate_factor(detail_cut, cal_cut, quotes=quote_cut, dynamic_seat_quality=False, update_time="2026-06-12T15:30:00")
    left = full.loc[full["trade_date"].eq(last_date)].sort_values("ts_code").reset_index(drop=True)
    right = recalculated.loc[recalculated["trade_date"].eq(last_date)].sort_values("ts_code").reset_index(drop=True)
    assert left["factor_value"].round(10).equals(right["factor_value"].round(10))
    assert left["signal"].equals(right["signal"])


def check_backtest_contract(metrics: dict) -> None:
    required = {
        "rank_ic",
        "rank_icir",
        "layer_mean",
        "long_short_mean",
        "buy_mdd",
        "buy_turnover",
        "train_rank_ic",
        "test_rank_ic",
        "buy_yearly_mean",
        "signal_samples",
    }
    missing = required - set(metrics)
    assert not missing, f"回测缺少规则要求指标: {sorted(missing)}"
    assert set(metrics["layer_mean"]) == {"L1", "L2", "L3", "L4", "L5"}


def check_overfitting_and_out_of_sample(metrics: dict, require_values: bool) -> None:
    for key in ["train_rank_ic", "test_rank_ic", "buy_train_mean", "buy_test_mean", "buy_worst_year_mean"]:
        assert key in metrics, f"缺少 {key}，无法完成过拟合/样本外检查"
        if require_values:
            assert pd.notna(metrics[key]), f"{key} 为空，无法完成过拟合/样本外检查"
    assert isinstance(metrics["buy_yearly_mean"], dict), "跨年度表现必须按年份输出"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证最终版 A06 可成交因子")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.real:
        if not args.start_date or not args.end_date:
            raise ValueError("--real 必须提供 --start-date 和 --end-date")
        details = pd.DataFrame(load_real_lhb_details(args.start_date, args.end_date))
        calendar = pd.DataFrame(load_real_trade_calendar(args.start_date, args.end_date))
        quotes = pd.DataFrame(load_real_quotes(args.start_date, args.end_date, _symbols(details)))
        factor = calculate_factor(details, calendar, quotes=quotes, dynamic_seat_quality=False)
    else:
        details = sample_lhb_detail()
        calendar = sample_trade_calendar()
        quotes = sample_quotes()
        factor = calculate_factor(details, calendar, quotes=quotes, dynamic_seat_quality=False, update_time="2026-06-12T15:30:00")

    check_schema(factor, pd.DataFrame(calendar))
    check_no_future_function(pd.DataFrame(details), pd.DataFrame(calendar), pd.DataFrame(quotes))
    metrics = run_backtest(factor, quotes)
    check_backtest_contract(metrics)
    check_overfitting_and_out_of_sample(metrics, require_values=args.real)
    checks = release_checks(metrics)
    print("生产字段、主键、有效交易日、信号枚举和无未来函数检查通过")
    print("过拟合、样本外、跨年度与回测指标契约检查已覆盖")
    print(f"回测口径: {metrics['evaluation_rule']}")
    print(f"回测时间: {datetime.now().isoformat(timespec='seconds')}")
    print(f"release_pass: {all(checks.values())}")
    print(f"failed_checks: {[key for key, passed in checks.items() if not passed]}")


if __name__ == "__main__":
    main()
