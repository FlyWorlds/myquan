# B12 Intraday Position Manager

Use this skill when you need dynamic intraday position management across multiple asset classes. Supports A-shares / A-share ETFs / index futures / commodity futures / HK stocks + ETFs; distinguishes T+1/T+0, previous-day/today positions, margin/cash, and outputs standardized 8-field position adjustment orders.

## ⚠️ Disclaimer

- **Research & Educational Use Only**: This skill is a quantitative trading research tool and does NOT constitute investment advice, financial advice, or trading recommendations of any kind.
- **No Guaranteed Returns**: Backtest or simulation results do not represent actual trading performance. Past performance does not predict future results. Users assume all trading risks.
- **Risk Boundaries**: This tool does not account for market liquidity, price limits, trading halts, slippage, or auction sessions. Generated orders may be unfillable or result in losses due to changing market conditions. All trading decisions are the sole responsibility of the user.
- **No Official Endorsement**: This is a QuantSkills community project. It has not been professionally audited or certified by any regulatory body and should not be considered an officially endorsed production-grade tool.

## Directory Structure

```
├── SKILL.md                                ← Skill specification (v2.1)
├── README.md                               ← Chinese README
├── README.en.md                            ← This file
├── LICENSE                                 ← GPL-3.0
├── INSTALL.md                              ← Multi-platform install guide
├── requirements.txt                        ← Dependency declaration
├── scripts/
│   ├── build.py                            ← Main entry point (run / validate_input)
│   ├── test.py                             ← Self-test script
│   ├── classify.py                         ← Asset classifier
│   ├── common.py                           ← Shared constants & utilities
│   ├── specs.py                            ← Contract spec loader
│   └── markets/
│       ├── __init__.py
│       ├── a_stock.py                      ← A-shares + A-ETF (T+1)
│       ├── index_future.py                 ← Index futures (IF/IC/IH/IM)
│       ├── commodity_future.py             ← Commodity futures (rb/cu/m/au/ag/i)
│       └── hk_stock.py                     ← HK stocks + ETFs (T+0)
└── references/
    ├── api_guide.md                        ← API reference
    └── contract_specs.json                 ← Central contract spec table
```

## Quick Start

```bash
cd scripts
python3 build.py
python3 test.py
```

## Core Design

1. **Five-level Priority Engine**: Force close (time-triggered) → Full stop-loss (loss ≥ 1%) → Halve position (loss ≥ 0.5%) → Add 50% (profit > 1%) → Hold. Quantities are rounded down to the asset's minimum trading unit (100 shares for A-shares, 1 contract for futures).

2. **T+1/T+0 Position Split**: Input uses `sellable_qty + locked_qty` instead of a single `current_qty`. T+1 assets (A-shares/ETFs) lock today's new positions from sale; T+0 assets (futures/HK stocks) allow full position operation.

3. **Capital Verification**: Buy orders calculate required cash (A-shares/HK stocks) or margin (futures). Insufficient funds result in `hold` — no partial degradation, avoiding half-filled order uncertainty.

4. **Modular Rule Engine**: `classify.py` identifies the asset → `specs.py` loads contract specs → each `markets/*.py` implements asset-specific logic independently. Adding a new asset class only requires a market module + `contract_specs.json` entry.

5. **Pure Python, Zero Dependencies**: Uses only the Python standard library (json, os, re, sys). No pandas, numpy, or other third-party packages.

## Supported Runtimes

| Platform | Install Guide |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Codex (OpenAI) | `INSTALL.md` § Codex |
| Cursor | `INSTALL.md` § Cursor |
| Hermes | `INSTALL.md` § Hermes |
| OpenClaw | `INSTALL.md` § OpenClaw |

## Verification Status

- build.py runs independently ✅
- validate_input checks ✅
- test.py covers: normal inputs, edge cases, multi-asset batches, insufficient funds, force-close triggers ✅

## Limitations & Future Work

| Limitation | Detail | Plan |
|---|---|---|
| Long-only | No short / hedge / spread / calendar combinations | v3 |
| No circuit breaker / halt awareness | Execution failures reported by caller | Integrate market status flags |
| Fixed fee rate | No stamp duty, transfer fee, or tiered commissions | Refine fee model |
| HK lot_size covers 6 stocks only | Fallback to 100 shares | Expand coverage table |
| Single currency per asset | Caller handles HKD/CNY conversion | Integrate FX rates |
| Limited commodity futures | rb/cu/m/au/ag/i only | Expand contract_specs.json |
| No auction session awareness | Time thresholds are hard cutoffs | Integrate trading calendar |
