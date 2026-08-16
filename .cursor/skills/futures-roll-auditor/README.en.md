# Futures Roll Auditor

Community-maintained QuantSkills package for auditing selected-contract sequences and reproducible futures roll ledgers.

## Quick start

```bash
python scripts/audit_rolls.py --demo
python scripts/audit_rolls.py --input your_data.csv --adjustment-method difference --out report.json
```

## CLI parameters

| Argument | Requirement | Description |
| --- | --- | --- |
| `--demo` | Choose exactly one source | Use built-in rows; mutually exclusive with `--input` |
| `--input <csv>` | Choose exactly one source | Read a UTF-8 CSV whose `date` values use ISO-8601 `YYYY-MM-DD` |
| `--adjustment-method {none,difference,ratio}` | Optional | Record the adjustment method; defaults to `none` |
| `--out <json>` | Optional | Write JSON to a file; otherwise print it to standard output |

Supplying both data sources, or neither source, exits with argparse status 2.

The CSV must contain `date`, `front`, `back`, `selected`, `front_price`, and `back_price`. The report validates the selected contract, identifies changes, and records same-day roll gaps plus difference and ratio adjustment factors.

For PandaData acquisition, use [`skill-pandadata-api`](https://github.com/quantskills/skill-pandadata-api). Add volume, open interest, decision timestamps, expiry constraints, and the declared roll rule when rule compliance must be proven.

## Validation and limits

See [validation/README.md](validation/README.md). Adjustment factors are for research-series construction; executable PnL must use contract-level returns and costs.

GPL-3.0-only.
