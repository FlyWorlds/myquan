# skill-factor-grouped-wrapper

[简体中文](README.md) | **English**

<p align="center">
  <img src="pipeline/framework.png" alt="Factor Grouped Wrapper framework" width="820">
</p>

<p align="center">
  <img src="pipeline/pipeline.png" alt="Factor Grouped Wrapper workflow" width="820">
</p>

`skill-factor-grouped-wrapper` is a grouped greedy wrapper Skill for large quantitative factor banks. It holds preprocessing and CPU LightGBM parameters fixed, fits on the training period, ranks candidates with daily cross-sectional validation Pearson IC or transaction-cost-aware hedged Sharpe, and persists candidates, fixed groups, and paths for resume and audit.

Backward and Forward are independent modes. Backward removes groups from pool A; Forward adds groups from candidate pool B. When combined, every Forward seed starts from the single best selected pool A. IC-primary search never runs a trading backtest; Sharpe-primary search invokes the separate `skill-factor-backtest` CLI for every validation candidate. After the factor snapshots are frozen, the separate `skill-factor-backtest` CLI compares original A, Backward A*, and Forward final out of sample.

`role: skill` `platforms: codex / claude-code / cursor / hermes / openclaw` `category: factor` `status: active` `maintainer: community` `validation: runnable` `model: LightGBM` `search metric: Pearson IC or hedged Sharpe`

This repository is an X-Tech-group-maintained QUANTSKILLS Community Project. It has not received QUANTSKILLS certification, endorsement, or production-readiness approval. `validation: runnable` means only that repository tests and the synthetic smoke workflow pass.

## Runtime Entrypoints

| Platform | Entrypoint | Status |
| --- | --- | --- |
| Codex | `SKILL.md`, `agents/openai.yaml` | Locally execution-tested |
| Claude Code | `SKILL.md`, with `agents/portable-loader.md` as fallback | Standard entrypoint provided |
| Cursor | `agents/cursor-rule.mdc` | Adapter provided |
| Hermes | `agents/portable-loader.md` | Adapter provided |
| OpenClaw | `SKILL.md` or `agents/portable-loader.md` | Portable entrypoint provided |

Platforms other than the locally exercised Codex workflow load the same CLI and contracts; this table does not claim platform-specific end-to-end certification.

## Workflow

```text
validate
  -> prepare-cache
  -> search-backward     # optional mode one
  -> search-forward      # optional mode two, standalone or after Backward
  -> freeze
  -> evaluate-oos        # one FactorBacktest call per frozen snapshot
```

Development uses fixed roles:

```text
Train:      fit the fixed LightGBM model
Validation: compare candidates by configured daily cross-sectional Pearson IC or transaction-cost-aware hedged Sharpe
OOS:        remain sealed and never select factors, seeds, or parameters
```

The public research template uses 2010-2021 for training, 2022 for validation, and 2023 through 2026-01 for OOS. These dates are configuration values, not hard-coded runtime behavior.

## Inputs

Pool A and optional pool B are Parquet files or directory-backed Parquet datasets with long-form keys and wide numeric factor columns:

```text
date | ticker | alpha191_001 | alpha191_002 | ...
```

- `data.factor_bank` is required pool A.
- `data.external_factor_bank` is optional pool B for Forward.
- `initial_factors` and `external_factors` can limit columns; null selects every non-key column.
- Factor names must not overlap between A and B.

`data.market_data_root` must follow the `skill-factor-backtest` `BackTestData_pq` layout. The wrapper reads `trade_price.parquet` to build the supported next-day-execution, one-day forward-return target. FactorBacktest consumes the complete root during Sharpe-primary validation search and OOS evaluation.

See [Input Schema](references/input_schema.md) for every configuration field and preprocessing rule.

## Install

Use Python 3.11 or later:

```bash
python -m pip install -e .
```

Or install runtime dependencies directly:

```bash
python -m pip install -r requirements.txt
```

Sharpe-primary search and OOS evaluation require an accessible `skill-factor-backtest`. Configure `backtest.skill_root` or `FACTOR_BACKTEST_SKILL_ROOT`.

## Configure

Copy [the complete template](examples/config.yaml) and replace data and output paths. It demonstrates combined A+B use:

```yaml
data:
  factor_bank: /path/to/alpha191.parquet
  external_factor_bank: /path/to/alpha101_factormad.parquet

selection:
  primary_metric: mean_ic
  min_delta: 0.001
  forward_enabled: true
```

To optimize transaction-cost-aware validation hedged Sharpe instead, use:

```yaml
selection:
  primary_metric: sharpe
  min_delta: 0.05
  forward_enabled: true
```

For Backward only, set `external_factor_bank: null` and `forward_enabled: false`. For standalone Forward, retain pool B and `forward_enabled: true`, prepare the cache, and run `search-forward` directly.

`grouping.source_prefixes` must match real columns exactly. Use `alpha191_` for a column named `alpha191_001`.

## Run

Validate and prepare the reusable development cache:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml validate
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml prepare-cache
```

Combined mode:

```bash
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml search-backward
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml search-forward --run-dir /path/to/run
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml freeze --run-dir /path/to/run
python scripts/run_factor_grouped_wrapper.py --config /path/to/config.yaml evaluate-oos --run-dir /path/to/run
```

The `search-backward` stdout JSON returns the newly created `run_dir`. Reuse it for later stages. To resume an interrupted search, rerun the same command with the same configuration and `--run-dir`; completed candidates are reused by fingerprint.

An existing OOS comparison is protected by default. Use `--force` only for an explicit rerun. Add `--report` to request the FactorBacktest PDF report.

## Search Behavior

At each Backward iteration, evaluate every `current - group` and accept only the best group whose primary metric improves by at least `min_delta`. Move to the next finer stage when the current stage cannot improve. Forward evaluates every `current + group` under the same acceptance rule and stops when no group passes.

For every seed and stage, factors are bucketed by `source_prefixes`, deterministically shuffled, and balanced across groups. Groups remain fixed inside that stage. Within each greedy iteration, independent candidates may run concurrently through `runtime.candidate_workers`; independent seed paths may run concurrently through `runtime.seed_workers`, while dependent iterations inside each path remain sequential. After all seed paths complete, the configured metric and diagnostic tie-breakers select one path. Survival frequency is evidence only; it does not vote a consensus pool.

See [Algorithm](references/algorithm.md) for exact grouping, ranking, and OOS-seal rules.

## Outputs

- `pool_a_selection.json`: Backward input, selected and removed A factors, best seed, and validation metrics.
- `pool_b_expansion.json`: Forward A base, B candidates, additions, rejections, and before/after metrics.
- `final_factor_pool.json`: final development factor tuple.
- `frozen_selection.json`: original A, Backward A*, and Forward final snapshots that are available in the run.
- `oos_comparison.json`: OOS snapshot backtests and adjacent-stage metric deltas.

IC-primary combined mode normally invokes FactorBacktest three times during OOS evaluation; Sharpe-primary mode additionally invokes it once per validation candidate. Backward-only or Forward-only mode invokes it twice. Stage snapshots remain distinct even when two factor lists happen to be equal.

See [Output Contract](references/output_contract.md) for field-level schemas and [FactorBacktest Integration](references/factor-backtest-integration.md) for invocation and metric parsing.

## Smoke Validation

The repository does not include real factor or market data. Generate the synthetic fixture and run through `freeze` with:

```bash
python scripts/run_smoke.py
```

For stage-by-stage inspection, run `python scripts/make_smoke_fixture.py`, then run `validate`, `prepare-cache`, and `search-backward` with `examples/smoke_config.yaml`; use the returned run directory for `search-forward` and `freeze`. Neither smoke path invokes OOS FactorBacktest or validates factor quality.

## Repository Layout

```text
├── SKILL.md
├── README.md / README.en.md
├── agents/
├── examples/
├── pipeline/
├── references/
├── scripts/
│   └── factor_grouped_wrapper/
└── tests/
```

## Current Boundaries

- Version 1 supports CPU LightGBM only, not MLP.
- Independent seed paths and within-iteration candidates may run concurrently through `runtime.seed_workers` and `runtime.candidate_workers`; dependent iterations inside each path remain sequential. LightGBM uses `model.n_jobs`, FactorBacktest subprocesses use `runtime.backtest_threads`, and `runtime.preload_features` trades memory for fewer repeated feature reads.
- Search uses one validation interval rather than temporal cross-validation.
- Greedy grouped search can miss jointly useful combinations and overfit validation comparisons.
- Pearson IC and Sharpe optimization can select different pools; repeatedly comparing one validation-period Sharpe can also overfit.
- Outputs are quantitative research artifacts, not investment advice, guaranteed returns, or production trading validation.

See [Validation Notes](references/validation_notes.md) and [Source Boundary](references/source_boundary.md).

## Community And Research Boundaries

| Item | Declaration |
| --- | --- |
| Data source | The repository bundles no real factor or market data and accepts only data the user has the right to use. |
| Example data | The smoke fixture is fully synthetic and validates mechanics, not factor quality. |
| Assumptions and parameters | `examples/config.yaml`, `references/input_schema.md`, and runtime validation are authoritative. |
| Known limitations | The current implementation is LightGBM-only and uses one validation interval with optional seed-path and within-iteration candidate concurrency; iterations inside each path remain sequential. |
| Risk boundary | Outputs are research artifacts, not investment advice, promised returns, official endorsement, or production trading validation. |

## Third-Party Dependencies And Attribution

This repository depends on [LightGBM](https://github.com/microsoft/LightGBM) (MIT), [NumPy](https://github.com/numpy/numpy) (BSD-3-Clause), [pandas](https://github.com/pandas-dev/pandas) (BSD-3-Clause), [Apache Arrow / PyArrow](https://github.com/apache/arrow) (Apache-2.0), and [PyYAML](https://github.com/yaml/pyyaml) (MIT). It invokes the separate [skill-factor-backtest](https://github.com/quantskills/skill-factor-backtest) (GPLv3) through its public CLI. Each dependency remains governed by its own license; this repository does not vendor their source.

`Alpha101`, `Alpha191`, and `FactorMAD` are naming examples for user-provided factor banks or external candidate sources only. This repository does not redistribute their real factor values, formulas, datasets, or third-party research artifacts.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
