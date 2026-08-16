# Input Contract

`positions.csv` must contain `date,symbol,weight`; add `sector` for sector totals. `returns.csv` must contain `date,symbol,asset_return`, where returns are decimal fractions (0.01 means 1%). Optional `benchmark.csv` contains `date,benchmark_return`. Optional `fees.csv` contains `date,fee`, also as a decimal fraction of portfolio value.

Dates are normalized to calendar dates. Positions and returns must have one row per `(date, symbol)`. A position is joined only to the return on the same date. The script intentionally fails on missing joins or duplicate keys so that silent look-ahead and accidental aggregation do not pass.
