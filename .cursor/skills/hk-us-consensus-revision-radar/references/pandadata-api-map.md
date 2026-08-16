# PandaData API Map

All raw observations used by this skill come from PandaData. Do not add fallback data sources.

| Market | Purpose | PandaData interface | Required fields |
|---|---|---|---|
| HK | Security identity and universe governance | `get_hk_detail` | `symbol`, `cn_name`, `local_name`, `name`, `status`, `trading_code`, `rcs_asset_category_name`, `business_sector`, `economic_sector`, `industry_group` |
| HK | Target-price consensus | `get_stock_ncycl_consensus` | `symbol`, `currency`, `indicator`, `mean`, `median`, `high`, `low`, `std`, `estimates_num`, `included_estimates_num`, `mean_week`, `mean_1month`, `mean_3month`, `mean_6month`, `mean_12month` |
| HK | Recommendation consensus | `get_stock_recommendation_consensus` | `symbol`, `currency`, `mean`, recommendation counts, `recommendations_num`, `mean_week`, `mean_1month`, `mean_3month`, `mean_6month`, `mean_12month` |
| HK | Latest returned daily close | `get_hk_daily` | `symbol`, `date`, `close`, `volume`, `amount`, `name`, `trade_status` |
| US | Security identity and universe governance | `get_us_detail` | `symbol`, `name`, `local_name`, `status`, `trading_code`, `rcs_asset_category_name`, `business_sector`, `economic_sector`, `industry_group` |
| US | Target-price consensus | `get_stock_ncycl_estimate` | same normalized target-price fields as HK |
| US | Recommendation consensus | `get_stock_recommendation_estimate` | same normalized recommendation fields as HK |
| US | Latest returned daily close | `get_us_daily` | `symbol`, `date`, `close`, `volume`, `name`, `trade_status` |
| US | Event: dividend/split | `get_stock_dividend_activity` | `symbol`, `publish_date`, `excute_date`, `event_type`, `number`, `currency`, `event` |
| US | Event: market/disclosure | `get_stock_market_activity` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| US | Event: investor conference | `get_stock_meeting_activity` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| US | Event: finance filing | `get_stock_financial_activity` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| US | Event: IR | `get_stock_ir_activity` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| HK | Event: dividend/split | `get_stock_dividend_event` | `symbol`, `publish_date`, `excute_date`, `event_type`, `number`, `currency`, `event` |
| HK | Event: market/disclosure | `get_stock_market_event` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| HK | Event: investor conference | `get_stock_meeting_event` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| HK | Event: finance filing | `get_stock_financial_event` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |
| HK | Event: IR | `get_stock_ir_event` | `info_date`, `symbol`, `start_date`, `end_date`, `event_type`, `event`, `is_estimated`, `fiscal_quarter` |

## Collection rules

- Authenticate before calling any interface.
- Use `indicator == "TP"` only for target-price analysis.
- Request only the fields listed above.
- Build the canonical display identity and conservative core-universe classification from detail data. Require `status == 1` and `rcs_asset_category_name` identifying an ordinary share for ranking eligibility; daily names are display fallback only.
- Request both current and selected-horizon target and recommendation fields so each security card can show the underlying evidence.
- Query the requested latest trading day first. For every symbol with a missing, nonnumeric, or nonpositive close, query that symbol over the preceding 14 calendar days regardless of the aggregate price match rate, then take the latest valid returned close per symbol.
- Record requested date, returned date range, initial row count, fallback status, matched symbols, universe size, and price match rate in report diagnostics.
- Classify unresolved price gaps and core-universe exclusions; never fill missing values with data from another vendor, with zero, or by forward filling.
- Validate target ranges, included/total estimate counts, recommendation bucket totals, and recommendation means without replacing PandaData source values.
- Store interface names in output provenance.
- A returned date is the source date; generation time is not a market-data timestamp.

## Event contracts and provenance

- Dividend/split interfaces use `publish_date` as the announcement filter, and `excute_date` as the execution/release date. The field name is `excute_date` in PandaData and must not be renamed before validation.
- Financial/market/meeting/IR interfaces use `info_date` as the announcement filter and `start_date` / `end_date` as execution period fields.
- Event status is derived in the report as one of: `ongoing`, `upcoming`, `recent`, `today`, or `invalid_date`.
- Deduplication key is: `market`, `symbol`, `category`, `event_type`, `start_date`, `end_date`, `title`.
- Event discovery and display windows are configurable with `event_discovery_days`, `event_past_days`, and `event_future_days` in the workflow. Defaults are 730, 30, and 30.
- Event module states are recorded as `available`, `partial`, `unavailable`, `disabled`, and `empty`.
- Only interfaces actually called and their results are listed in provenance; interfaces with no call must not be shown as source.

## Availability boundary

The target and recommendation interfaces used here expose aggregate consensus. They do not expose individual analyst/broker revision events. Consequently, revision breadth, contributor-level timing, and analyst accuracy cannot be calculated from this API map and must be reported as unavailable.
`get_last_trade_date` is an optional PandaData interface used only to probe the latest trading date. Its documented response is a table with a `date` column; the adapter also accepts a validated scalar/dict form for SDK-version compatibility. When it is unavailable, empty, or invalid, the workflow falls back to the configured/date-window query without inventing a market-data timestamp. The report lists this interface only when it was actually called and returned a valid date.
The report's source-provenance block lists the four market-specific interfaces above with their purposes, plus this optional date-probe interface when applicable.
