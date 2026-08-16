from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_grouped_wrapper.backtest_evaluator import build_backtest_command, write_signal
from factor_grouped_wrapper.metrics import annualized_sharpe_from_nav, calculate_prediction_metrics, is_improvement, parse_backtest_metrics


def test_parse_factor_backtest_outputs(tmp_path: Path) -> None:
    dates = pd.date_range("2022-01-03", periods=50, freq="B")
    nav = 100.0 * np.cumprod(np.repeat(1.001, len(dates)))
    hedged_returns = np.resize(np.array([0.0010, -0.0003, 0.0008, 0.0001]), len(dates))
    hedged = 100.0 * np.cumprod(1.0 + hedged_returns)
    pd.DataFrame(
        {
            "date": dates.strftime("%Y%m%d"),
            "unrealized_pnl": nav,
            "hedged_unrealized_pnl": hedged,
            "DailyPCT": pd.Series(hedged).pct_change(),
            "MaxDrawdown": 0.0,
        }
    ).to_csv(tmp_path / "stats.csv", index=False)
    pd.DataFrame({"date": dates.strftime("%Y%m%d"), "1d": np.linspace(-0.02, 0.04, len(dates))}).to_csv(
        tmp_path / "ICs.csv", index=False
    )
    pd.DataFrame({"date": dates.strftime("%Y%m%d"), "group1": 1.0}).to_csv(
        tmp_path / "group_ret.csv", index=False
    )
    expected_sharpe = annualized_sharpe_from_nav(pd.Series(hedged))
    pd.read_csv(tmp_path / "stats.csv").assign(DailyPCT=99.0).to_csv(
        tmp_path / "stats.csv", index=False
    )
    metrics = parse_backtest_metrics(tmp_path, init_cash=100.0)
    assert metrics["sharpe"] == pytest.approx(expected_sharpe)
    assert metrics["total_return"] > metrics["hedged_total_return"] > 0
    assert metrics["mean_ic"] > 0
    assert metrics["icir"] > 0
    assert metrics["monthly_hedged_returns"]


def test_prediction_metrics_compute_daily_cross_sectional_pearson_ic() -> None:
    frame = pd.DataFrame(
        {
            "date": [20220103, 20220103, 20220103, 20220104, 20220104, 20220104],
            "prediction": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
            "target": [1.0, 2.0, 100.0, 100.0, 2.0, 1.0],
        }
    )
    metrics = calculate_prediction_metrics(frame)
    assert metrics["mean_rank_ic"] == pytest.approx(1.0)
    assert 0.0 < metrics["mean_ic"] < 1.0
    assert metrics["valid_date_count"] == 2


def test_acceptance_uses_only_primary_pearson_ic_delta() -> None:
    baseline = {"mean_ic": 0.10, "mean_rank_ic": 0.50}
    candidate = {"mean_ic": 0.101, "mean_rank_ic": 0.10}
    accepted, delta = is_improvement(
        candidate,
        baseline,
        {"primary_metric": "mean_ic", "min_delta": 0.001},
    )
    assert accepted
    assert delta == pytest.approx(0.001)


def test_public_backtest_command_and_exact_signal_schema(tmp_path: Path) -> None:
    backtest_root = tmp_path / "skill-factor-backtest"
    entrypoint = backtest_root / "scripts" / "run_factor_backtest.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("print('ok')\n", encoding="utf-8")
    config = {
        "data": {"market_data_root": str(tmp_path / "market")},
        "backtest": {
            "skill_root": str(backtest_root),
            "python_executable": "python",
            "strategy": "long_only_equal_weight",
            "init_cash": 100.0,
            "overrides": {"longx": 200, "buy_sell_shift": 1},
        },
    }
    signal_path = tmp_path / "signal.parquet"
    write_signal(
        pd.DataFrame({"date": ["2022-01-03"], "ticker": [1], "prediction": [0.5], "target": [99.0]}),
        signal_path,
    )
    assert pd.read_parquet(signal_path).columns.tolist() == ["date", "ticker", "prediction"]
    command = build_backtest_command(config, signal_path, tmp_path / "out", "2022-01-01", "2022-12-31", 2)
    assert command[1] == str(entrypoint)
    assert command[command.index("--factor-column") + 1] == "prediction"
    assert command.count("--override") == 2
