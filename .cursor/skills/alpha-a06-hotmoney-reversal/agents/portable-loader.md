# Portable Loader: A06 Hot-Money Reversal Alpha

This adapter lets Hermes, OpenClaw, and other agents load the QuantSkills A06 Alpha skill.

## Load Order

1. Read `SKILL.md` at the repository root.
2. Read `开发产物/SKILL.md` for the full development/runtime contract.
3. Read `生产产物/SKILL.md` only when the task is to inspect existing production Parquet results.

## When To Use

Use this skill for A06 tasks:

- hot-money seat factor calculation;
- leakage, overfitting, and out-of-sample validation;
- executable backtests with the documented `t+1` open entry and `t+2` close exit;
- production Parquet generation;
- acceptance-report inspection;
- production result queries.

## Standard Commands

Run from `开发产物/`:

```bash
python scripts/factor.py --demo
python scripts/validate.py
python scripts/backtest.py
python scripts/update_production.py --full-refresh --bootstrap-start-date 20230601
```

## Safety And Scope

- Official inputs are PandaData data or fixed PandaData raw snapshots.
- Do not recalculate production results during ordinary production-result queries.
- Do not treat research signals as investment advice.
- Do not include credentials, tokens, local absolute paths, private data, or cache files in commits.
- Preserve GPL-3.0-only licensing and QuantSkills attribution.
