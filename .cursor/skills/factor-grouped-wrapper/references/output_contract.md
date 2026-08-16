# Output Contract

## CLI Envelope

Every successful command prints one JSON object to stdout. Expected `status` values are `valid`, `cached`, `backward_done`, `forward_done`, `frozen`, and `oos_evaluated`. Contract, path, runtime, and lifecycle errors are printed to stderr and return exit code `2`.

## Run Directory

```text
run_YYYYMMDD_HHMMSS/
├── config.resolved.yaml
├── data_manifest.json
├── lifecycle.json
├── candidates/<candidate_id>/
├── groups/
├── paths/seed_<seed>/
├── development_checkpoint.json
├── pool_a_selection.json
├── pool_b_expansion.json          # Forward only
├── final_factor_pool.json
├── frozen_selection.json          # after freeze
├── oos_access_log.json            # after OOS access
├── oos/<snapshot_name>/           # after OOS evaluation
└── oos_comparison.json            # after OOS evaluation
```

The resolved configuration and cache fingerprint must match when resuming an existing run.

## Stable Development Outputs

### `pool_a_selection.json`

Written after Backward. Stable fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Search-state schema version, currently `3`. |
| `phase` | `backward`. |
| `input_factors` | Eligible pool A factors after the training coverage filter. |
| `selected_factors` | Best completed Backward path. |
| `removed_factors` | Eligible input factors not in the selected set. |
| `factor_count` | Selected factor count. |
| `primary_metric` | Configured search metric. |
| `best_seed`, `best_candidate_id` | Winning path and immutable candidate identifiers. |
| `search_metrics` | Validation metrics for the winning candidate. |
| `factor_survival_frequency` | Fraction of completed seed paths retaining each observed factor. |
| `paths` | Final candidate count and metrics for each completed seed. |
| `updated_at` | UTC timestamp. |

### `pool_b_expansion.json`

Written after Forward. Stable fields include `base_factors`, `candidate_factors`, `added_factors`, `rejected_factors`, `factor_count_before`, `factor_count_after`, `primary_metric`, `best_seed`, `best_candidate_id`, `search_metrics_before`, `search_metrics_after`, `paths`, and `updated_at`.

### `final_factor_pool.json`

Written after the last configured development mode. Stable fields include `phase`, `selected_from_pool_a`, `added_from_pool_b`, `final_factors`, `factor_count`, `primary_metric`, `best_seed`, `best_candidate_id`, `search_metrics`, and `updated_at`. In Backward-only mode, `added_from_pool_b` is empty. In standalone Forward mode, `selected_from_pool_a` is original eligible A.

Search metric objects always contain:

```text
mean_ic, icir, mean_rank_ic, rank_icir, valid_date_count, observation_count
```

Sharpe-primary searches additionally contain `sharpe`, `total_return`, `hedged_total_return`, `max_drawdown`, `monthly_hedged_returns`, `backtest_mean_rank_ic`, `backtest_rank_icir`, and `backtest_observation_count`.

## Frozen Selection

`frozen_selection.json` uses schema version `2` and contains:

- `status: frozen`
- `phase`, `selected_factors`, and `factor_count` for the final snapshot
- `snapshots`, each with `name`, `phase`, `factors`, `factor_count`, and optional validation `search_metrics`
- `config_fingerprint`, `cache_fingerprint`, and `frozen_at`

Snapshot names are derived from completed modes:

| Run | Snapshots |
| --- | --- |
| Backward only | `original_a`, `backward_a_star` |
| Forward only | `original_a`, `forward_final` |
| Backward then Forward | `original_a`, `backward_a_star`, `forward_final` |

Snapshots are still distinct evaluation stages when two factor lists happen to be identical.

## OOS Outputs

Each `oos/<snapshot_name>/evaluation.json` records the frozen factors, refit and OOS periods, row counts, parsed backtest metrics, signal path, FactorBacktest output directory, fingerprints, and completion time. `predictions.parquet` has exactly:

```text
date:int64 YYYYMMDD | ticker:int64 | prediction:finite numeric
```

`oos_comparison.json` uses schema version `2` and contains:

- `refit_period` and `oos_period`
- `factor_union`
- `snapshot_results` in frozen order
- adjacent-stage `comparisons` with `metric_deltas`
- configuration/cache fingerprints and `completed_at`

Parsed backtest metrics are `total_return`, `hedged_total_return`, `sharpe`, `max_drawdown`, `mean_ic`, `icir`, `monthly_hedged_returns`, and `observation_count`. Sharpe is calculated from changes in the hedged NAV.

## Resumable Internal Evidence

- `candidates/<candidate_id>/result.json` caches one factor tuple independently of seed/stage metadata. Sharpe candidates also store `validation_signal.parquet`, `validation_backtest/`, `backtest_invocation.json`, and stdout/stderr logs.
- `paths/seed_<seed>/<phase>_state.json` is the authoritative resumable path state.
- `<phase>_history.parquet` records every evaluated candidate row and acceptance flag.
- `groups/*.json` freezes deterministic group assignments for the run.
- `development_checkpoint.json` is overwritten with the latest completed Backward or Forward path comparison.
- `oos_access_log.json` appends started, completed, or failed OOS access events.

Treat these files as audit and recovery evidence. Downstream consumers should prefer the stable development, frozen, and OOS outputs above.
