# Example output — ma_crossover_signal

Call:

```bash
python scripts/ma_crossover_signal.py 600519.SH --fast-period 5 --slow-period 20
```

Representative JSON result (values illustrative):

```json
{
  "stock_code": "600519.SH",
  "market": "cn",
  "start_date": "20260101",
  "end_date": "20260526",
  "observations": 96,
  "ma_type": "sma",
  "fast_period": 5,
  "slow_period": 20,
  "last_close": 1685.0,
  "fast_ma": 1690.2,
  "slow_ma": 1662.4,
  "state": "bullish",
  "ma_gap_pct": 0.0167,
  "price_bias_pct": 0.0136,
  "last_cross": {"type": "golden", "date": "20260512", "bars_ago": 9, "close": 1650.0},
  "recent_signals": [
    {"type": "death",  "date": "20260318", "close": 1590.0},
    {"type": "golden", "date": "20260512", "close": 1650.0}
  ]
}
```

Notes:

- A cross is the **sign change of (fast − slow)**; `golden` = fast crosses above slow,
  `death` = below. `bars_ago = 0` means it crossed on the last bar.
- No crossover in the window (or history `< slow_period`) → `last_cross` is `null`.
- `fast_period >= slow_period`, illegal `ma_type`, or too-short history → a structured
  `Error: …` string.
