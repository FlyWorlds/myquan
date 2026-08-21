"""冻结样本外、成本压力、区块 bootstrap 与多重检验诊断。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.chan.config import DEFAULT_CONFIG, ChanStrategyConfig
from strategy.strategies.strategy2.backtest import ANNUAL_BARS, ChanBacktestResult, run_chan_backtest


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def block_bootstrap_sharpe(
    returns: pd.Series,
    *,
    samples: int = 500,
    block_size: int = 40,
    seed: int = 42,
) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) < max(20, block_size):
        return {"sharpe_p05": 0.0, "sharpe_median": 0.0, "sharpe_p95": 0.0}
    rng = np.random.default_rng(seed)
    stats: list[float] = []
    block = min(int(block_size), len(values))
    for _ in range(int(samples)):
        chunks: list[np.ndarray] = []
        while sum(len(x) for x in chunks) < len(values):
            start = int(rng.integers(0, len(values) - block + 1))
            chunks.append(values[start : start + block])
        sample = np.concatenate(chunks)[: len(values)]
        vol = float(np.std(sample, ddof=1))
        stats.append(float(np.mean(sample) / vol * np.sqrt(ANNUAL_BARS)) if vol > 0 else 0.0)
    p05, median, p95 = np.quantile(stats, [0.05, 0.50, 0.95])
    return {
        "sharpe_p05": float(p05),
        "sharpe_median": float(median),
        "sharpe_p95": float(p95),
    }


def deflated_sharpe_probability(
    sharpe: float,
    returns: pd.Series,
    *,
    trials: int,
) -> float:
    """Bailey/Lopez de Prado DSR 的保守近似，显式惩罚试验次数。"""
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if len(values) < 30:
        return 0.0
    skew = float(values.skew())
    kurtosis = float(values.kurtosis()) + 3.0
    sr_std = math.sqrt(
        max(1.0 - skew * sharpe + (kurtosis - 1.0) * sharpe * sharpe / 4.0, 1e-12)
        / max(len(values) - 1, 1)
    )
    expected_max = math.sqrt(max(2.0 * math.log(max(int(trials), 1)), 0.0))
    adjusted = (float(sharpe) - expected_max * sr_std) / max(sr_std, 1e-12)
    return float(_normal_cdf(adjusted))


def estimate_pbo(journal: pd.DataFrame) -> float:
    required = {"discovery_score", "validation_score"}
    if journal.empty or not required.issubset(journal.columns):
        return 1.0
    data = journal[list(required)].apply(pd.to_numeric, errors="coerce").dropna()
    if len(data) < 4:
        return 1.0
    cutoff = data["discovery_score"].quantile(0.75)
    selected = data[data["discovery_score"] >= cutoff]
    median = data["validation_score"].median()
    return float((selected["validation_score"] < median).mean()) if len(selected) else 1.0


@dataclass
class FrozenValidationResult:
    backtest: ChanBacktestResult
    diagnostics: dict[str, Any]
    cost_stress: pd.DataFrame

    def save(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.backtest.equity.to_csv(output_dir / "final_test_equity.csv", index=False)
        self.backtest.yearly.to_csv(output_dir / "final_test_yearly.csv", index=False)
        self.backtest.trades.to_csv(output_dir / "final_test_trades.csv", index=False)
        self.backtest.picks.to_csv(output_dir / "final_test_picks.csv", index=False)
        self.cost_stress.to_csv(output_dir / "cost_stress.csv", index=False)
        (output_dir / "final_test_diagnostics.json").write_text(
            json.dumps(self.diagnostics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def validate_frozen_factor(
    panel: pd.DataFrame,
    factor_column: str | None,
    *,
    journal: pd.DataFrame | None = None,
    config: ChanStrategyConfig = DEFAULT_CONFIG,
    bootstrap_samples: int = 500,
) -> FrozenValidationResult:
    final = run_chan_backtest(
        panel,
        factor_column=factor_column,
        config=config,
        start=config.test_start,
        end=config.test_end,
        fee_rate=config.fee_rate,
    )
    stresses: list[dict[str, float]] = []
    for fee in config.stress_fee_rates:
        result = run_chan_backtest(
            panel,
            factor_column=factor_column,
            config=config,
            start=config.test_start,
            end=config.test_end,
            fee_rate=fee,
        )
        stresses.append(
            {
                "fee_rate": float(fee),
                "sharpe": float(result.stats["sharpe"]),
                "annual_return": float(result.stats["annual_return"]),
                "max_drawdown": float(result.stats["max_drawdown"]),
            }
        )
    delayed = panel.copy()
    delayed_column = None
    if factor_column and factor_column in delayed:
        delayed_column = f"{factor_column}_delay1"
        delayed[delayed_column] = delayed.groupby("symbol")[factor_column].shift(1)
    delayed_result = run_chan_backtest(
        delayed,
        factor_column=delayed_column,
        config=config,
        start=config.test_start,
        end=config.test_end,
        fee_rate=config.fee_rate,
    )
    bootstrap = block_bootstrap_sharpe(
        final.equity["net_return"],
        samples=bootstrap_samples,
        seed=config.random_seed,
    )
    trials = int(len(journal)) if journal is not None else 1
    dsr = deflated_sharpe_probability(
        final.stats["sharpe"],
        final.equity["net_return"],
        trials=max(trials, 1),
    )
    pbo = estimate_pbo(journal if journal is not None else pd.DataFrame())
    if (
        final.stats["sharpe"] >= 1.0
        and bootstrap["sharpe_p05"] > 0
        and dsr >= 0.95
        and pbo <= 0.30
    ):
        grade = "research-ready"
    elif final.stats["sharpe"] > 0 and final.stats["annual_return"] > 0:
        grade = "promising-but-unvalidated"
    else:
        grade = "reject"
    diagnostics = {
        "period": [config.test_start, config.test_end],
        "factor_column": factor_column,
        "final_test_touched": True,
        "test_stats": final.stats,
        "delayed_one_bar_sharpe": float(delayed_result.stats["sharpe"]),
        "bootstrap": bootstrap,
        "deflated_sharpe_probability": dsr,
        "pbo_estimate": pbo,
        "search_trials": trials,
        "decision": grade,
        "research_only": True,
        "limitations": [
            "若成分股为当前截面而非历史时点成分，结论上限为探索性",
            "未模拟盘口冲击和集合竞价排队",
            "30分钟仅用于小转大买点，卖点与持仓管理在日线",
            "历史回测不代表未来表现",
        ],
    }
    return FrozenValidationResult(
        backtest=final,
        diagnostics=diagnostics,
        cost_stress=pd.DataFrame(stresses),
    )


__all__ = [
    "FrozenValidationResult",
    "block_bootstrap_sharpe",
    "deflated_sharpe_probability",
    "estimate_pbo",
    "validate_frozen_factor",
]
