# Input Schema

## Configuration

Pass one YAML file with these required top-level mappings:

```text
data, split, label, preprocess, model, grouping, selection, backtest, runtime
```

Relative paths are resolved from the configuration file directory. The CLI rejects overlapping or unordered train, validation, and OOS periods.

### Data

| Field | Type | Behavior |
| --- | --- | --- |
| `factor_bank` | path | Required pool A Parquet file or directory-backed Parquet dataset. |
| `external_factor_bank` | path or null | Optional pool B dataset used only by Forward. |
| `market_data_root` | path | Required FactorBacktest-compatible market-data root. |
| `initial_factors` | list or null | Pool A columns to use; null selects every non-key column. |
| `external_factors` | list or null | Pool B columns to use; null selects every non-key column. |

Pool A and pool B factor names must not overlap.

### Split and label

`split` requires `train_start`, `train_end`, `valid_start`, `valid_end`, `oos_start`, and `oos_end`, with:

```text
train_start <= train_end < valid_start <= valid_end < oos_start <= oos_end
```

Version 1 requires `label.execution_lag=1` and `label.horizon=1`. `backtest.overrides.buy_sell_shift` must equal the execution lag.

### Preprocessing

| Field | Type | Constraint |
| --- | --- | --- |
| `min_factor_coverage` | float | Training-row coverage threshold in `[0,1]`. |
| `winsor_lower` | float | Lower daily cross-sectional quantile. |
| `winsor_upper` | float | Upper quantile, strictly above the lower quantile. |
| `cross_sectional_zscore` | bool | Apply daily population-standard-deviation z-score when true. |
| `fill_value` | float | Fill remaining transformed feature missing values. |
| `min_assets_per_date` | int | Minimum finite observations per factor/date and minimum finite targets per date. |

### Model

Version 1 accepts only `model.type=lgbm`. `model.n_jobs` must be positive. `model.params` is passed to `lightgbm.LGBMRegressor`; the runtime overrides its `n_jobs` with `model.n_jobs`.

### Grouping and selection

| Field | Type | Behavior |
| --- | --- | --- |
| `grouping.seeds` | list[int] | Unique, non-empty deterministic search seeds. Independent paths may run concurrently through `runtime.seed_workers`; each path remains deterministic. |
| `grouping.source_prefixes` | list[str] | Optional exact column prefixes used to spread sources across groups. Unmatched factors share `__other__`. |
| `grouping.backward_stages` | list[mapping] | Each stage needs a unique `name` and exactly one positive `target_group_count` or `group_size`. |
| `enter_when_factor_count_at_most` | int, optional | Skip a stage when the current factor count is above this threshold. |
| `grouping.forward_group_size` | int | Maximum target size used to form balanced pool B groups. |
| `selection.primary_metric` | string | One of `mean_ic`, `icir`, `mean_rank_ic`, `rank_icir`, or `sharpe`. `sharpe` invokes validation FactorBacktest for every candidate. |
| `selection.min_delta` | float | Non-negative minimum primary-metric improvement required for acceptance. |
| `selection.forward_enabled` | bool | Enables Forward; also requires a non-empty eligible pool B. |

`source_prefixes` must match actual column names. For columns such as `alpha191_001`, use `alpha191_`, not `alpha191__`.

### Backtest and runtime

`backtest.skill_root` and `backtest.python_executable` are optional explicit locations. The remaining fields configure the public `factor-backtest` CLI: `strategy`, `init_cash`, `search_savemode`, `final_savemode`, `reverse`, and `overrides`. Sharpe search defaults `search_savemode` to `2` and accepts only `2` or `3` because `stats.csv` is required. `runtime.output_root` stores run directories; `runtime.cache_root` stores reusable development and OOS caches. `runtime.candidate_workers` (default `1`) evaluates independent candidates within one greedy iteration concurrently. `runtime.seed_workers` (default `1`) runs independent seed paths concurrently; dependent iterations inside each path remain sequential. `runtime.backtest_threads` (default `1`) caps OpenMP, OpenBLAS, MKL, and NumExpr threads in each FactorBacktest subprocess. `runtime.preload_features` (default `false`) keeps the aligned train and validation feature union in memory to avoid repeated Parquet reads. Worker counts must be positive and preloading must be boolean. These four execution-only settings do not invalidate candidate IDs or resume state; resuming updates `config.resolved.yaml` to record their current values.

Use `examples/config.yaml` as the complete combined Backward plus Forward template. Set `external_factor_bank: null` and `forward_enabled: false` for Backward-only use.

## Factor Banks

Provide one Parquet file or directory-backed Parquet dataset with unique long-form keys and wide numeric feature columns:

```text
date | ticker | alpha191_001 | alpha191_002 | ...
```

- `date` must be integer-like `YYYYMMDD`, a parseable date string, or a timestamp.
- `ticker` must be a non-negative integer or integer-like string.
- Selected factor columns must be numeric; infinities become missing values.
- Duplicate `(date,ticker)` rows are rejected.
- Training coverage is calculated over all training rows before preprocessing. Factors below the threshold are excluded from the cache and every later stage.

## Market-Data Root

Use the schema accepted by `skill-factor-backtest`:

```text
BackTestData_pq/
├── calendar.parquet
├── name_dict.parquet
├── adjfactor.parquet
├── pre_close.parquet
├── trade_price.parquet
├── balance_price.parquet
├── open_price.parquet
├── mask_isopen.parquet
├── mask_isST.parquet
└── Benchmark/<benchmark>.parquet
```

Ticker columns in matrix Parquets must convert to non-negative integers. The wrapper reads `trade_price.parquet` to construct labels; FactorBacktest consumes the complete root during validation search when Sharpe is primary and during every OOS evaluation.

## Target Alignment

For a signal observed on trading date `t`, the supported target is:

```text
target[t] = trade_price[t + 2] / trade_price[t + 1] - 1
```

This matches `execution_lag=1`, `horizon=1`, and the default next-day execution convention.

## Preprocessing and Cache

Apply the following independently on each date and factor:

1. Replace infinities with missing values.
2. Winsorize at the configured daily quantiles.
3. Optionally cross-sectionally z-score.
4. Set a factor/date cross-section to missing when it has fewer than `min_assets_per_date` finite raw values.
5. Fill remaining feature missing values with `fill_value` and store float32 yearly Parquets.
6. Retain only rows with finite targets for fitting and metrics.

The development cache covers train plus validation. The OOS cache is created only after freezing and contains the union of frozen snapshot factors. Cache manifests record source descriptors, factor eligibility, files, checksums, splits, and fingerprints.
