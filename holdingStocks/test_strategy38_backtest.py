import pytest
from holdingStocks.strategy38_backtest_service import Strategy38BacktestManager, simulate_strategy38_backtest, DEFAULT_BACKTEST_PARAMS

def test_simulate_strategy38_backtest_basic():
    params = {
        "universe": "hs300",
        "start_date": "2024-01-01",
        "end_date": "2024-06-30",
        "volume_multiple": 2.0,
        "take_profit_pct": 0.08,
        "stop_loss_pct": -0.04,
    }
    res = simulate_strategy38_backtest(params)
    assert "summary" in res
    assert "dates" in res
    assert "equity_curve" in res
    assert "benchmark_curve" in res
    assert "alpha_curve" in res
    assert "drawdown_curve" in res
    assert "trades" in res
    assert "stock_contributions" in res

    summary = res["summary"]
    assert "strategy_return_pct" in summary
    assert "alpha_pct" in summary
    assert "max_drawdown_pct" in summary
    assert "sharpe_ratio" in summary
    assert "win_rate_pct" in summary
    assert "total_trades" in summary

def test_strategy38_backtest_manager_status():
    status = Strategy38BacktestManager.get_status()
    assert "running" in status
    assert "progress" in status
    assert "latest" in status
    assert status["latest"] is not None
