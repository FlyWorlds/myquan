# FactorBacktest Integration

## Boundary

Locate the external entrypoint in this order: `backtest.skill_root`, `FACTOR_BACKTEST_SKILL_ROOT`, a sibling `skill-factor-backtest`, then `~/.codex/skills/skill-factor-backtest`. Always execute the external [FactorBacktest public CLI](https://github.com/quantskills/skill-factor-backtest/blob/main/scripts/run_factor_backtest.py) entrypoint with `subprocess.run`. Never import FactorBacktest's internal backtest engine.

## Signal schema

Write one Parquet file with exactly:

```text
date | ticker | prediction
```

Dates are `int64 YYYYMMDD`, tickers are non-negative `int64`, and predictions are finite. Never export learning targets to the backtest adapter.

## Validation search invocation

Invoke the CLI for search candidates only when `selection.primary_metric: sharpe`. Use the configured validation dates and `backtest.search_savemode` (default `2`). Persist each candidate signal, output directory, command, stdout, stderr, and subprocess thread limits. Independent candidate CLI calls may run concurrently because each uses an isolated process and output directory. Calculate selection Sharpe from `hedged_unrealized_pnl.pct_change()` and keep the wrapper-computed Pearson IC under `mean_ic`; store FactorBacktest rank IC under separate `backtest_*` fields. IC-primary modes must not invoke FactorBacktest during search.

## Frozen OOS invocation

Use `final_savemode` (default `3`) and the configured OOS dates for every frozen snapshot. Defaults are:

```text
longx=200
stock_pool=whole
trade_price_type=twap
buy_sell_shift=1
transaction=1.4
benchmark=benchmark
keep=0.8
turnover_mode=flex
init_cash=100000000
```

Combined Backward and Forward runs invoke the CLI three times for `original_a`, `backward_a_star`, and `forward_final`. Single-mode runs invoke it twice. `longx=50` belongs to optional sensitivity analysis and must not influence selection.

## Parsed metrics

Parse `stats.csv`, `ICs.csv`, and `group_ret.csv` after the CLI exits successfully:

- `total_return`: final absolute NAV divided by initial cash, minus one. Prefer `unrealized_pnl` when it is an absolute NAV column.
- `hedged_total_return`: final hedged NAV divided by initial cash, minus one. Prefer `hedged_unrealized_pnl`.
- `sharpe`: annualized mean/standard-deviation of `hedged_unrealized_pnl.pct_change()` using 252 trading days. Ignore `DailyPCT` for this calculation.
- `max_drawdown`: maximum absolute `MaxDrawdown` value.
- `mean_ic`: mean of the `1d` IC column, or the first numeric IC column when `1d` is absent.
- `icir`: mean IC divided by IC standard deviation, annualized by square root of 252.
- `monthly_hedged_returns`: month-end percentage changes in the hedged NAV series.

Validation candidate comparisons must use identical market data, validation timespan, strategy, costs, and overrides. Frozen OOS snapshot comparisons must also use identical settings, and their results are reporting evidence that must not feed back into factor selection.
