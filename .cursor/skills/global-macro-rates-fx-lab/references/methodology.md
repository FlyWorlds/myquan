# Methodology — Global Macro Rates & FX

This playbook records how the skill turns public rate and FX series (plus Pandadata
`get_macro_gb`) into a factual regime read. Everything here is descriptive; nothing is a trade
recommendation.

## 1. The DM rate complex

For each developed market in scope (US always; EUR-area / Japan / UK on request) collect four
pieces:

| Item | US public series | Meaning |
| --- | --- | --- |
| Policy rate | central-bank policy page / FRED policy series | current target rate / stance |
| 2y yield | `DGS2` | front-end, policy-expectations sensitive |
| 10y yield | `DGS10` | long-end, term-premium + growth/inflation |
| 2s10s slope | `T10Y2Y` (already 10y − 2y) | curve shape |
| Real 10y | `DFII10` | 10y TIPS real yield |

Key computations:

- **2s10s slope** = 10y − 2y. FRED publishes it directly as `T10Y2Y` (in **percentage points**).
  If you compute it yourself from `DGS10 − DGS2`, mark it as a calculated value and keep the same
  unit. A negative slope is an **inversion** — report it as the state of the curve, not a call.
- **Breakeven inflation** (optional) ≈ nominal 10y (`DGS10`) − real 10y (`DFII10`). Label it a
  derived proxy for market-implied inflation, not an official series, unless you pull the FRED
  breakeven series directly.
- **Steepening vs flattening** = sign of the change in 2s10s over the window. State the window.

## 2. USD and the major pairs

- **Dollar index proxy:** use the broad trade-weighted dollar `DTWEXBGS` as a DXY-style gauge.
  It is a public FRED index (re-based periodically) — note the index base and that it is broad,
  not the ICE DXY basket, so do not quote a DXY point level from it; report direction and
  percentage change.
- **Major pairs:** EURUSD, USDJPY, GBPUSD from ECB reference rates or a public exchange-rate host.

Quoting-convention rule (do not get this backwards):

| Pair | Quote | "Stronger USD" implies |
| --- | --- | --- |
| EURUSD | USD per 1 EUR | pair **falls** |
| GBPUSD | USD per 1 GBP | pair **falls** |
| USDJPY | JPY per 1 USD | pair **rises** |

Cross-check: a rising dollar index should line up with EURUSD/GBPUSD down and USDJPY up. Flag any
pair that disagrees with the index as a divergence rather than forcing a narrative.

## 3. Pandadata international-macro layer

Delegate to the `pandadata-api` skill and call **only** `get_macro_gb`:

```python
import panda_data
result = panda_data.get_macro_gb(
    start_date="20260101",
    end_date="20260430",
)
# columns: symbol, period_date, data_value
```

- Optionally pass `symbol` to narrow to a specific international indicator code, and `fields` to
  trim columns. Do not invent extra parameters or response fields — the contract is exactly
  `symbol / period_date / data_value`.
- Align `period_date` to the same window as the public series. Because `get_macro_gb` returns raw
  indicator codes, keep the `symbol` code visible and describe it factually rather than guessing a
  friendly name you cannot verify.

## 4. Regime read (factual synthesis)

Combine the pieces into a described regime, each statement tied to a series:

- Curve: steepening / flattening / inverted (from 2s10s and its change).
- Real rates: rising / falling (from `DFII10`).
- Dollar: broadly firm / soft (from `DTWEXBGS`) and whether the major pairs agree.
- Confirmations / contradictions between public series and `get_macro_gb`.

Use hedged, descriptive language (`显示`, `可能提示`, `需要验证`, `与…相互印证`). Never output a
buy/sell/hold or a rate-direction bet.

## 5. Pitfalls

- **FRED lag & revision.** Daily yield series can be a day or more stale and the latest print may
  revise. Always show the as-of/vintage date and flag provisional prints.
- **Percent vs basis points.** Yields and slopes in percent/percentage points; if a reader wants
  bps, 1pp = 100bp — state the unit on every spread and never mix the two.
- **FX quoting direction.** See the table in §2; the most common error is treating USDJPY like
  EURUSD.
- **Index proxy misuse.** `DTWEXBGS` is a broad re-based index, not the tradable ICE DXY; report
  change/direction, not a spot DXY level.
- **Wrong-skill substitution.** China domestic macro belongs to `macro-monitor`; China alt-data to
  `macro-altdata-nowcast`. This skill is overseas/global only.
- **Inversion over-reading.** `2s10s < 0` is a curve state, not a recession forecast or trade.

## 6. Graceful degradation

- If a FRED/FX series is unavailable, report the gap explicitly (series id, window, provider) and
  continue with the series you do have rather than fabricating a value.
- If `get_macro_gb` returns empty for the window, state the queried `start_date`/`end_date` and
  fall back to a public-series-only regime read, noting the Pandadata layer is missing.
- If regions conflict, present both observations side by side instead of averaging them into a
  single false signal.
