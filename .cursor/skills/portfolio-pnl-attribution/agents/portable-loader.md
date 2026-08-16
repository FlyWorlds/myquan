# Portable Runtime Loader

This file is the portable entrypoint for Hermes-compatible and other Markdown-driven runtimes.

## Activation

Load `../SKILL.md` when a user asks for realized portfolio P&L attribution, security or sector contribution analysis, fee reconciliation, or benchmark-relative performance accounting.

## Execution

1. Load `../references/input_contract.md` and verify the supplied columns and decimal-return convention.
2. Run `../scripts/attribute_portfolio.py` with the user-provided positions and returns, plus optional benchmark and fees.
3. Inspect `security_attribution.csv`, `sector_attribution.csv`, `daily_attribution.csv`, and `summary.json`.
4. Surface missing joins, duplicate keys, weight-sum warnings, and reconciliation errors in the final report.

Do not use this entrypoint for ex-ante risk attribution, portfolio optimization, or investment advice.
