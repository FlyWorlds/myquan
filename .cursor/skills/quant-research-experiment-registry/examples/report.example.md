# Reproducibility Report (Synthetic Example)

## Status

`partial`: the directory, configuration and result artifacts were registered locally. Live PandaData and specialized leakage checks were not run.

## Evidence

- Configuration: `tests/fixtures/minimal_experiment/config.json`
- Query: declared `get_stock_daily` fixture query
- Result: `tests/fixtures/minimal_experiment/results.json`
- Text report: `tests/fixtures/minimal_experiment/report.md`

## Unresolved

- Provider availability/publication metadata is not present.
- `skill-numerical-leak-check` was not invoked.
- Synthetic fixtures do not validate live market-data correctness.

This report is a research record, not investment advice.
