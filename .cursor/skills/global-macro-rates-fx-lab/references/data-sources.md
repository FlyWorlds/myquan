# Data Sources — Global Macro Rates & FX

All sources here are **public** or delegated to the `pandadata-api` skill. No API keys, tokens, or
private datasets are shipped in this repo. Cite the series id and observation date for every
number you use.

## 1. FRED public series (Federal Reserve Bank of St. Louis)

Accessed via the public FRED site / FRED public API. Series are free and public; note that they
lag and revise.

| Series id | Description | Unit | Frequency |
| --- | --- | --- | --- |
| `DGS2` | 2-Year Treasury constant-maturity yield | percent | daily (business) |
| `DGS10` | 10-Year Treasury constant-maturity yield | percent | daily (business) |
| `T10Y2Y` | 10Y minus 2Y Treasury spread (2s10s) | percentage points | daily (business) |
| `DFII10` | 10-Year TIPS (real) constant-maturity yield | percent | daily (business) |
| `DTWEXBGS` | Nominal Broad US Dollar Index (trade-weighted) | index (re-based) | daily (business) |

Notes: these are the core US rate complex + dollar proxy. For non-US regions pull the equivalent
sovereign 2y/10y from the relevant central bank or a public FRED international series when
available; if not available, state the gap rather than substituting a US number.

## 2. Central-bank policy pages (public)

For the current policy-rate level and stance (facts only, not forward guidance interpretation):

- **Federal Reserve** — federal funds target range.
- **ECB** — main refinancing / deposit facility rate.
- **Bank of Japan** — policy balance rate / short-term policy rate.
- **Bank of England** — Bank Rate.

Record the rate level and the meeting/effective date; do not paraphrase forward guidance as a
prediction.

## 3. Public FX references

For EURUSD / USDJPY / GBPUSD spot levels:

- **ECB euro foreign-exchange reference rates** — daily reference fixes (euro-based; invert or
  cross as needed, stating the convention).
- **Public exchange-rate hosts** — free/open exchange-rate endpoints for daily major-pair levels.

Always record the source and the fix date/time. Apply the quoting-convention table in
`methodology.md`.

## 4. Pandadata — international macro (delegated)

- **Method:** `get_macro_gb` (宏观行业·国际宏观) — the **only** Pandadata method this skill uses.
- **Contract:** `get_macro_gb(symbol=None, start_date="YYYYMMDD", end_date="YYYYMMDD", fields=None)`
- **Response columns:** `symbol` (indicator code), `period_date` (data period), `data_value` (float).
- **Access:** delegate the actual call to the `pandadata-api` skill; that skill owns credential
  loading, its own method-index and doc-search contract checks, and error handling. Do not
  hardcode credentials here and do not invent additional methods, symbols, or fields.

Example (for reference; run through the `pandadata-api` skill):

```python
import panda_data
result = panda_data.get_macro_gb(start_date="20260101", end_date="20260430")
print(result)  # columns: symbol, period_date, data_value
```

## 5. Vintage & freshness

- FRED daily series can be one or more business days behind and revise; label the as-of date and
  flag provisional prints.
- Central-bank policy rates change only on meeting dates; carry the last effective level with its
  date.
- FX reference fixes are once-daily; intraday moves are not captured — say so.
- `get_macro_gb` periods follow the indicator's own release cadence; align `period_date` before
  comparing with daily public series.
