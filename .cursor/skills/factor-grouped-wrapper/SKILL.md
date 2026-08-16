---
name: factor-grouped-wrapper
description: Run resumable grouped greedy wrapper selection for large quantitative factor banks with CPU LightGBM, validation-period Pearson IC or FactorBacktest Sharpe scoring, backward elimination, optional forward inclusion, frozen stage snapshots, and sealed out-of-sample FactorBacktest comparison. Use when an agent needs to reduce Alpha101/Alpha191 or other wide factor pools, add candidates from an external factor bank, resume an interrupted search, freeze original/backward/forward factor sets, or compare their OOS trading performance. Also use for Chinese requests such as 分组因子筛选、因子池淘汰、前向加入、后向删除、wrapper 因子选择或筛选后回测。
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-factor-grouped-wrapper
  repository_url: https://github.com/quantskills/skill-factor-grouped-wrapper
  project_type: skill
  collection: factor-selection
  maintainer: X-Tech-group
quantSkills:
  project_type: skill
  category: factor
  tags:
    - factor-selection
    - grouped-wrapper
    - backward-elimination
    - forward-selection
    - lightgbm
    - pearson-ic
    - sharpe
    - factor-backtest
  platforms:
    - claude-code
    - codex
    - openclaw
    - cursor
  status: active
  validation_level: runnable
  maintainer_type: community
  summary_zh: 使用 LightGBM 与验证期 Pearson IC 或扣费对冲 Sharpe 对大规模因子池执行可恢复的分组后向剔除和前向加入，并比较冻结集合的样本外回测。
  summary_en: Run resumable grouped backward elimination and forward inclusion with LightGBM validation Pearson IC or hedged Sharpe, then compare frozen OOS backtests.
  license: GPL-3.0-only
  requires:
    - skill-factor-backtest
---

# Factor Grouped Wrapper

Use this skill to select factor subsets by retraining a fixed CPU LightGBM model. Score validation predictions with daily cross-sectional Pearson IC by default, or call the external `factor-backtest` public CLI on the validation period to optimize transaction-cost-aware hedged Sharpe. Treat Backward elimination and Forward inclusion as independent modes that can also share one run. Always reserve OOS FactorBacktest results for frozen snapshots.

## Core Workflow

1. Read `references/input_schema.md` and validate the wide factor bank and FactorBacktest market-data root.
2. Copy `examples/config.yaml`, set the real data paths, and keep OOS dates sealed during development.
3. Run validation and build the reusable preprocessed cache:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml validate
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml prepare-cache
```

4. Run grouped backward elimination. Compare all seed paths by the configured validation metric, select one best pool A result, and resume by passing the existing run directory:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml search-backward
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml search-backward --run-dir /path/to/run
```

5. Run optional Forward inclusion when `data.external_factor_bank` is configured and `selection.forward_enabled=true`. Start from the selected pool A when Backward has run, or from original A in standalone Forward mode:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml search-forward --run-dir /path/to/run
```

6. Inspect development histories, then freeze all available snapshots: original A, Backward A*, and Forward final. Do not evaluate OOS before freezing:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml freeze --run-dir /path/to/run
```

7. Run one OOS command. It refits every frozen snapshot on train plus validation and invokes `$factor-backtest` once per snapshot:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml evaluate-oos --run-dir /path/to/run
```

## Integrity Rules

- Fit search candidates only on the configured training period (2010-2021 in the public template) and rank them only on the configured validation period (2022 in the template).
- Keep LightGBM parameters, preprocessing, tradable universe, backtest parameters, and group assignments fixed while comparing candidates. Use `runtime.candidate_workers` to parallelize independent candidates within one greedy iteration and `runtime.seed_workers` to parallelize independent seed paths; dependent iterations inside each path remain sequential. Use `runtime.preload_features` only when sufficient memory is available.
- Use `mean_ic` as the default optimization target with an IC-scale `min_delta`. Set `primary_metric: sharpe` and a Sharpe-scale `min_delta` to rank candidates by validation-period, transaction-cost-aware hedged Sharpe. Retain IC metrics as diagnostics and tie-break evidence in Sharpe mode.
- Never tune on, rank candidates with, or repeatedly inspect the configured OOS period (2023 through 2026-01 in the template).
- Refuse OOS evaluation without `frozen_selection.json`; refuse overwriting an existing OOS evaluation unless `--force` is explicit.
- Invoke `skill-factor-backtest/scripts/run_factor_backtest.py`; do not import its internal engine. In Sharpe mode call it only on validation predictions during search; after freezing call it on OOS predictions for reporting.

## Output Contract

Use `pool_a_selection.json` as the Backward result, `pool_b_expansion.json` as the optional Forward result, and `final_factor_pool.json` as the final development result. `freeze` combines these files with the original eligible A factors from the cache manifest. When Forward is disabled or pool B is empty, write the final pool immediately from pool A. Treat `development_checkpoint.json`, per-seed states, histories, groups, and candidate directories as resumable internal evidence. Read `references/output_contract.md` before consuming these files programmatically.

The frozen selection contains every available stage snapshot. Combined Backward and Forward runs produce exactly three OOS signals and three FactorBacktest evaluations: original A, Backward A*, and Forward final. Backward-only or Forward-only runs produce two. Search metrics always include prediction IC diagnostics; Sharpe mode also includes validation trading metrics and candidate-level backtest evidence. Read `references/algorithm.md` and `references/factor-backtest-integration.md` before changing search or scoring behavior.

## Project Status

Treat this repository as an X-Tech-group-maintained QUANTSKILLS Community Project. Interpret `runnable` as local tests and synthetic smoke validation only, not QUANTSKILLS certification, endorsement, investment advice, or production readiness.

## References

- `references/input_schema.md`: configuration fields, input schema, date alignment, preprocessing, and cache layout.
- `references/output_contract.md`: stable outputs, resumable evidence, and OOS comparison fields.
- `references/algorithm.md`: grouping, backward/forward search, acceptance, and sealed OOS rules.
- `references/factor-backtest-integration.md`: public CLI invocation and parsed metrics.
- `references/source_boundary.md`: allowed data sources, publication boundaries, and OOS integrity.
- `references/validation_notes.md`: tested behavior, limitations, and research-risk boundaries.
