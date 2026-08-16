# skill-alpha-f1-position-change

[简体中文](README.md) | **English**

> Futures Top-20 Position Breakout Alpha factor: computes long/short breakout signals from PandaAI futures position data and produces verifiable factor tables, backtest metrics, and a self-contained HTML visualization report.

<p align="center">
  <img alt="libraries" src="https://img.shields.io/badge/libraries-Futures%20Top20%20Position-blue">
  <img alt="factor" src="https://img.shields.io/badge/factor-F1-brightgreen">
  <img alt="type" src="https://img.shields.io/badge/type-alpha--development-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-PandaAI-9cf">
  <img alt="status" src="https://img.shields.io/badge/status-active-brightgreen">
  <img alt="validation" src="https://img.shields.io/badge/validation-L2%20contract--checked-success">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

`skill-alpha-f1-position-change` is a futures position-breakout factor Skill that computes the long/short breakout factor for top-20 broker positions and completes validation, backtesting, and offline reproduction.

This Skill is suitable for:

- Development and batch computation of futures top-20 position breakout factors
- Building factor matrices from main-contract position data (61 instruments across SHFE / INE / DCE / CZCE / GFEX / CFFEX markets)
- Complete workflows for factor validation, contract checking, and IC-stability backtesting
- Triggering deterministic factor computation and backtesting from Claude Code conversations

This Skill pulls real position and price data via the `panda_data` SDK, outputting factor tables, backtest metrics (IC/ICIR/layered returns/Calmar), a self-contained HTML visualization report, and offline fixtures for CI integration.

## Repository Contents

| File | Description |
|---|---|
| `SKILL.md` | Skill contract document (internal Agent use) |
| `scripts/factor.py` | Factor computation entry (positions → factor table) |
| `scripts/validate.py` | Factor validation (contract checks + IC stability + offline mode) |
| `scripts/backtest.py` | Backtest evaluation (real price returns for IC/ICIR) |
| `scripts/backtest_report_data.py` | Backtest timeseries wrapper (HTML report data source) |
| `scripts/report.py` | HTML report generator entry (matplotlib static charts) |
| `scripts/save_fixture.py` | One-time offline fixture generator |
| `scripts/fixtures/` | Offline test data (Parquet format) |
| `requirements.txt` | Python dependencies |
| `references/data_guide.md` | PandaAI data API reference |
| `LICENSE` | GPLv3 license |
| `README.md` / `README.en.md` | Chinese / English README |

## Directory Structure

```text
skill-alpha-f1-position-change/
├── SKILL.md
├── README.md
├── README.en.md
├── LICENSE
├── requirements.txt
├── references/
│   └── data_guide.md
├── scripts/
│   ├── factor.py                  # Factor compute (load_position_data / load_price_data)
│   ├── validate.py                # Validation (check_factor_contract 11 assertions)
│   ├── backtest.py                # Backtest (strict forward_return)
│   ├── backtest_report_data.py    # Timeseries wrapper (keeps curve / daily_ic / drawdown)
│   ├── report.py                  # HTML report generator (matplotlib + base64)
│   ├── save_fixture.py            # Offline fixture generator
│   └── fixtures/                  # Offline test data (generated after first run)
│       ├── sample_positions.parquet
│       └── sample_prices.parquet
└── reports/                       # Report artifacts (.gitignored)
    ├── backtest_result.json       # Intermediate data (full timeseries)
    └── report.html                # Final HTML report (self-contained)
```

## Data Requirements

Input contract for calling `panda_data.get_future_netposi_rank` and `get_future_daily`:

| Field | Type | Description |
|---|---|---|
| `underlying_symbol` | str | Instrument code (e.g., `"AP"`), no contract month, no exchange suffix |
| `date` | str | Trading date in YYYYMMDD format |
| `broker_name` | str | Broker name |
| `net_position` | int | Net position volume |
| `position_type` | str | Position type: `long` or `short` |

Input contract details:

- **underlying_symbol format**: Instrument code (`"AP"`, `"AU"`), not contract code (`"AP801"`)
- **Case**: Must be uppercase
- **Error handling**: panda_data silently skips invalid codes, returns empty DataFrame; this Skill raises `ValueError` when `combined_df.empty`
- **API field contract**: Must return `underlying_symbol` field; if returns `symbol` / `code` / `instrument_id`, `validate_input` auto-maps aliases with `[INFO]` warning

## Quick Start

### Environment Setup

```bash
export PANDA_DATA_USERNAME=your_username
export PANDA_DATA_PASSWORD=your_password

# Optional: control data range
export PANDA_DATA_START_DATE=2026-01-01
export PANDA_DATA_END_DATE=2026-03-31
```

### Four-Step Run

```bash
cd scripts/

# 1. Factor computation
python factor.py
# Output: factor table (trade_date, symbol, factor_value, score, signal, confidence, ...)

# 2. Factor validation
python validate.py
# Output: contract checks (11 assertions) + IC stability + score distribution

# 3. Backtest evaluation
python backtest.py
# Output: IC, ICIR, Rank IC, Rank ICIR, layered returns, Calmar, MDD, turnover

# 4. HTML report generation
python report.py
# Output: reports/report.html (self-contained, with 4 base64-embedded charts)
```

### Offline Mode (CI Friendly)

```bash
# 1. Generate fixtures once (requires network + credentials)
python save_fixture.py
# Generates scripts/fixtures/sample_positions.parquet + sample_prices.parquet

# 2. Subsequent validation without network
export PANDA_DATA_OFFLINE=1
python validate.py

# 3. Generate HTML report offline (no credentials needed, opens in browser)
python report.py --offline --open
```

`check_factor_contract` (11 contract assertions) always runs offline and does not depend on any fixture.

In offline mode, if `panda_data` SDK is not installed locally, `report.py` automatically injects a stub module to bypass `factor.py`'s top-level import; when pyarrow 19 is incompatible with legacy parquet files, it falls back to `fastparquet`.

## Input Configuration

| Environment Variable | Required | Default | Description |
|---|---|---|---|
| `PANDA_DATA_USERNAME` | ✓ | — | PandaAI account |
| `PANDA_DATA_PASSWORD` | ✓ | — | PandaAI password |
| `PANDA_DATA_START_DATE` | — | 90 days before current date | Start date (YYYY-MM-DD) |
| `PANDA_DATA_END_DATE` | — | Current date | End date (YYYY-MM-DD) |
| `PANDA_DATA_OFFLINE` | — | `0` | When `1`, enables offline mode loading from fixture |
| `PANDA_DATA_DEBUG` | — | `0` | When `1`, prints schema probe on first API call |

## Signal Generation Rules

Factor value formula:

```
factor_value = long_change_rate - short_change_rate
```

Where:

```
long_change_rate  = (today_long_total - yesterday_long_total) / |yesterday_long_total|
short_change_rate = (today_short_total - yesterday_short_total) / |yesterday_short_total|
```

Signal threshold `CHANGE_THRESHOLD = 0.02` (2%):

| Signal | Trigger Condition |
|---|---|
| `buy` | long_change_rate ≥ 2% OR short_change_rate ≤ -2% |
| `sell` | long_change_rate ≤ -2% OR short_change_rate ≥ 2% |
| `hold` | Otherwise |

Score formula (z-score + logistic squash):

```
z = (factor_value - cross-sectional mean) / (cross-sectional σ)
score = 100 / (1 + exp(-z))      # Range (0, 100) open interval
confidence = |z|                  # Std deviations from cross-sectional mean
```

When daily instrument count N<5, degraded: `score = NaN`, `signal = hold`.

## Output Files

Factor table fields output by `factor.py`:

| Field | Description |
|---|---|
| `trade_date` | Trading date (YYYY-MM-DD) |
| `asset_type` | Asset type (fixed as `future`) |
| `symbol` | Instrument code |
| `factor_id` | Factor ID (fixed as `F1`) |
| `factor_name` | Factor name ("期货前20席位持仓突变") |
| `factor_value` | Raw factor value (long_change_rate - short_change_rate) |
| `score` | (0, 100) standardized score (z-score via logistic squash) |
| `rank` | Cross-sectional rank |
| `signal` | Trading signal: `buy` / `sell` / `hold` |
| `confidence` | `|z-score|`, std deviations from cross-sectional mean |
| `long_total` / `short_total` | Today's top-20 long/short position totals |
| `prev_long_total` / `prev_short_total` | Yesterday's long/short position totals |
| `long_change_rate` / `short_change_rate` | Long/short change rates |
| `long_broker_count` / `short_broker_count` | Number of brokers in computation |
| `data_version` | Data version (`real-v1`) |
| `update_time` | Latest data date + A-share close time 15:30 (ISO 8601) |

## HTML Backtest Report

`scripts/report.py` renders the backtest result as a self-contained single HTML file (base64-embedded charts, viewable offline). Default output is `reports/report.html`, with intermediate `reports/backtest_result.json` in the same directory.

### Report Contents

| Section | Description |
|---|---|
| Summary cards | 8 core metrics: IC / ICIR / Rank IC / Rank ICIR / IR(SHR*) / CR / ARR / MDD |
| Sample statistics | Total samples, buy/sell/hold signal counts, turnover |
| Layered return comparison | Low vs High group mean returns and spread |
| Cumulative return & drawdown | Two subplots: cumulative return (top), drawdown fill (bottom) |
| Daily IC time series | Pearson IC vs Rank IC, two-line comparison |
| Signal distribution by date | Stacked buy/sell/hold counts per trading day |
| Top 20 symbols by signal | Horizontal stacked bars, sorted by total signal count |
| Top 20 symbols detail table | Symbol / Buy / Sell / Hold / Total |
| Evaluation convention | Strict convention `forward_return = close_{t+1}/open_{t+1} - 1` |

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--offline` | False | Force offline mode (uses fixtures, no credentials) |
| `--json-path` | `reports/backtest_result.json` | Intermediate JSON output path |
| `--html-path` | `reports/report.html` | Final HTML output path |
| `--dpi` | 100 | Chart DPI (controls PNG size) |
| `--open` | False | Auto-open in default browser after generation |

### Examples

```bash
# Offline mode (most common)
python scripts/report.py --offline --open

# Custom output path
python scripts/report.py --offline --html-path reports/custom.html

# Reduce HTML size (for email attachments)
python scripts/report.py --offline --dpi 80
```

Chart labels inside the report are in English (to avoid matplotlib Chinese font cross-platform issues); HTML text is in English in this README's version. A single HTML is about 250KB at dpi=100.

## Recommendations for Large-Scale Runs

- **API batching**: Single API call ≤ 8 instruments (`BATCH_SIZE = 8`) to avoid server limits
- **Network retry**: Skip on per-batch empty return, raise only when all batches empty
- **Offline fixture**: Use `PANDA_DATA_OFFLINE=1` in CI, loading from `fixtures/sample_*.parquet`
- **DEBUG probe**: With `PANDA_DATA_DEBUG=1`, the first API call prints returned field names and first 3 sample rows

## Validation Approach

### Strict forward_return Convention

```
forward_return_t = close_{t+1} / open_{t+1} - 1
```

Signal generated after market close on day t → enter at day t+1 open → exit at day t+1 close. **Avoids future functions and look-ahead bias.**

### IC Stability Test

First-half and second-half sample ICs must have same sign and `|IC| > 0.02` (industry empirical lower bound).

### Factor Contract 11 Assertions

`check_factor_contract` covers:

1. Key columns exist (defense against pure-long KeyError)
2. `rank` integer type
3. `rank` monotonically corresponds to `factor_value` (per day)
4. `factor_value == long_change_rate - short_change_rate` math equivalence
5. `long_total` / `short_total` non-negative
6. `change_rate` range `[-1, +∞)`
7. `factor_id` equals `"F1"`
8. `data_version` equals `"real-v1"`
9. `trade_date` format YYYY-MM-DD
10. `update_time` format ISO 8601
11. `signal` subset check

## Project Status and Risk Boundaries

### Completed (as of 2026-07)

14 rounds of fixes:

| Round | Topic |
|---|---|
| 1 | IC autocorrelation / no-price backtest / alpha 0 evidence / threshold mismatch |
| 2 | score/confidence standardization bias |
| 3 | pandas FutureWarning |
| 4 | API batch fetching (BATCH_SIZE=8) |
| 5 | symbols market-wide expansion (73 instruments) |
| 6-7 | Deleted 11 low-liquidity instruments (61 remaining) |
| 8 | underlying_symbol input contract + alias mapping + DEBUG probe |
| 9 | validate offline mode + 11 contract assertions + fixture |
| 10 | Pure-long instrument KeyError defense |
| 11 | `_load_fixture_or_network` online prices loading |
| 12 | Dynamic `update_time` derivation (latest data date + 15:30) |
| 13 | HTML backtest report generation (`backtest_report_data.py` + `report.py` + matplotlib) |

### Known Uncovered

- **CFFEX treasury factor semantics**: Financial futures position structure differs from commodities; factor effectiveness to be verified empirically
- **GFEX suffix runtime validation**: `SI/LC/PS_DOMINANT.GFE` format untested by API; may need to change to `GFEX`
- **PS polysilicon short history**: Listed 2024-12-13, factor statistics may be unstable

### Boundaries

What this Skill does NOT do:

- Does not call LLMs
- Does not read non-PandaAI API keys
- Does not provide trading recommendations
- Does not perform out-of-sample walk-forward optimization (only first/second-half IC stability)

## License

[GPL-3.0](LICENSE) © 2026 PandaTest
