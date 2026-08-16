---
name: ma_crossover_signal
license: GPL-3.0-only
description: |
  Moving-average crossover for ONE symbol: fast vs slow MA (SMA/EMA), trend state, latest golden/death cross (date + bars ago), MA gap, price bias (乖离率). Auto-routes A-share / HK / US by suffix.
  Use when the user asks 金叉 / 死叉 / 均线 / 趋势 on a name, or "is X in an uptrend".

  **Why:** backed by our own `panda_data` (A-share) / `tqx_data` (HK/US) daily closes — no scraping. It computes both MAs on the SAME cleaned close series and detects a cross by the SIGN CHANGE of (fast − slow), so it reports the actual last cross with its date, not just "fast currently above slow" (which misses that the cross may be 40 bars stale). SMA or EMA via `ma_type`. Returns `state`/`last_cross=null` gracefully when history is shorter than `slow_period`. NOT a full backtest and NOT indicator series (RSI/MACD) — for those use the indicator/backtest skills.
parameters:
  - {name: stock_code, type: str, required: true, description: "Ticker. A 股 `600519` / `600519.SH`; 港股 `0700.HK`; 美股 `AAPL.NB`. `[A-Za-z0-9._-]+` only — rejected before any network call otherwise."}
  - {name: market, type: str, required: false, default: "auto", enum: ["auto", "cn", "hk", "us"], description: "Market routing. `auto` infers from suffix; pass `cn`/`hk`/`us` to force."}
  - {name: fast_period, type: int, required: false, default: 5, description: "Fast MA window in trading days (e.g. 5). Must be < `slow_period`."}
  - {name: slow_period, type: int, required: false, default: 20, description: "Slow MA window in trading days (e.g. 20). Must be > `fast_period`."}
  - {name: ma_type, type: str, required: false, default: "sma", enum: ["sma", "ema"], description: "`sma` = simple moving average; `ema` = exponential (span = period)."}
  - {name: start_date, type: str, required: false, default: "", description: "Window start `YYYYMMDD`. Empty → derived from `lookback_days` / `slow_period`."}
  - {name: end_date, type: str, required: false, default: "", description: "Window end `YYYYMMDD`. Empty → today."}
  - {name: lookback_days, type: int, required: false, default: 120, description: "Trailing trading-day target used only when `start_date` is empty (auto-extended to at least ~2.5×`slow_period` so both MAs are defined; calendar buffer added)."}
  - {name: max_signals, type: int, required: false, default: 5, description: "How many most-recent crossovers to list in `recent_signals` (newest last)."}
---

# ma_crossover_signal

Fast/slow moving-average crossover snapshot for one symbol across A-share / HK / US. Closes come from our own `panda_data` (A 股) / `tqx_data` (HK / US) daily endpoints; both MAs are computed on the same cleaned series.

## Output shape (JSON string)

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

## Definitions

| Field | Meaning |
|-------|---------|
| `state` | `bullish` when `fast_ma ≥ slow_ma` on the last bar, else `bearish` |
| `ma_gap_pct` | `(fast_ma − slow_ma) / slow_ma` |
| `price_bias_pct` | 乖离率 `(last_close − slow_ma) / slow_ma` |
| `last_cross.type` | `golden` (fast crosses **above** slow) or `death` (fast crosses **below** slow) |
| `bars_ago` | trading bars since that cross (0 = crossed on the last bar) |
| `recent_signals` | up to `max_signals` most-recent crosses, oldest→newest |

`last_cross` is `null` when no crossover occurred inside the window (or history < `slow_period`).

## When NOT to use

- RSI / MACD / KDJ indicator series → `analysis_technical` / the indicator skills.
- Full strategy P&L / backtest → the backtest skills.
- Risk/return ratios (夏普 / 回撤) → `risk_return_metrics`.
- Two-symbol relationship → `pair_correlation`.

## Why

"金叉了吗 / 还在上升趋势吗" is a recurring one-symbol question, and the naive answer —
"fast MA is above slow MA" — hides whether the cross is fresh or 40 bars old. Detecting the
cross by the sign change of (fast − slow) and returning its date + bars-ago gives the agent
the timing, not just the current ordering, in one panda_data / tqx_data-backed call.
