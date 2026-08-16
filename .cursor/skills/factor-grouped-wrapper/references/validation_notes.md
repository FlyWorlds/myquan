# Validation Notes

This Skill is a research workflow for grouped factor-pool selection.

## Mechanically Validated Behavior

- Configuration/path validation and non-overlapping Train < Validation < OOS splits.
- Long-form factor-bank key, numeric-column, duplicate-row, coverage, and preprocessing checks.
- Supported `execution_lag=1`, `horizon=1` target alignment.
- Deterministic source-balanced grouping and fixed groups within a stage.
- Backward, Forward, candidate reuse, state persistence, and interrupted-run resume behavior.
- Validation Pearson IC/ICIR and diagnostic RankIC/RankICIR calculation.
- Optional validation FactorBacktest invocation, standard hedged-NAV Sharpe calculation, candidate evidence persistence, and IC/Sharpe cache isolation.
- Frozen snapshot construction, OOS access controls, signal schema, FactorBacktest command construction, and metric parsing.

Run the repository tests and development smoke workflow before release. The smoke fixture uses synthetic data and does not invoke OOS FactorBacktest.

## Current Scope

- Version 1 supports CPU LightGBM only; MLP is not implemented. Independent candidates within one greedy iteration may execute concurrently.
- Independent seed paths and within-iteration candidates may execute concurrently through `runtime.seed_workers` and `runtime.candidate_workers`; dependent iterations inside each path remain sequential. LightGBM uses `model.n_jobs`, each FactorBacktest subprocess is capped by `runtime.backtest_threads`, and optional `runtime.preload_features` exchanges memory for fewer repeated feature reads.
- Search candidates are compared on one configured validation interval, not temporal cross-validation.
- Missing feature values are filled with the configured constant after daily transformation; the default is zero.
- FactorBacktest is an external Skill dependency. IC-primary search does not invoke it; Sharpe-primary search invokes it for validation candidates, and frozen OOS evaluation invokes it once per snapshot.

## Statistical Limitations

- Greedy grouped search can miss useful joint combinations and depends on group assignment, seed set, stage design, and acceptance threshold.
- Repeated validation comparisons can overfit the validation period even without OOS leakage.
- Pearson IC optimization and portfolio backtest performance can diverge because trading constraints, costs, turnover, tails, and nonlinear ranking behavior are not IC search objectives.
- Sharpe-primary search includes the configured trading constraints and costs but can overfit one validation period and is substantially slower.
- Survival frequency across configured seeds is diagnostic evidence, not a formal stability guarantee or automatic consensus rule.
- The included smoke fixture validates mechanics only; it says nothing about factor quality.

## Release Checks

From the repository root, run:

```bash
python /path/to/quantskills-registry/scripts/validate_skill.py .
python scripts/run_factor_grouped_wrapper.py --help
python -m pytest -q
python scripts/run_smoke.py
```

The smoke command generates synthetic data and runs `validate`, `prepare-cache`, `search-backward`, `search-forward`, and `freeze` with `examples/smoke_config.yaml`. Run `evaluate-oos` only with a real schema-compatible FactorBacktest data root and an explicit frozen research run.

## Risk Boundary

Outputs are research artifacts, not investment advice, a live signal recommendation, a return promise, or production trading validation.
