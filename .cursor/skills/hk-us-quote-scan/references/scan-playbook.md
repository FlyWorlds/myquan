# HK/US Quote Scan Playbook

Routing, metric definitions, symbol/schema notes, report skeleton, empty-data handling, and QA for `hk-us-quote-scan`. Read this before the first scan in a session. The exact call contract for every method still comes from the `pandadata-api` skill.

## 1. Routing table

| Need | HK method | US method | Key params |
|---|---|---|---|
| Identity & industry classification | `get_hk_detail` | `get_us_detail` | `symbol`, `fields`, `status` |
| Daily OHLCV / liquidity | `get_hk_daily` | `get_us_daily` | `symbol`, `start_date`, `end_date` (≤5y span) |
| Adjusted-price factor | `get_adj_factor` | `get_adj_factor` | per `pandadata-api` |
| Latest price-volume / valuation | `get_stock_pv_indicator` | `get_stock_pv_metric` | `symbol`, `fields` |
| Industry / sector median baseline | `get_stock_industry_median` | `get_stock_sector_median` | `symbol`, `fields` |

Empty `symbol` list on `get_hk_daily` / `get_us_daily` returns the whole market for the window — use for cross-section scans, but keep the window tight (heavy pull).

## 2. Symbol & schema notes

- **HK symbols**: 4-digit zero-padded + `.HK` (e.g. `0001.HK`, `0700.HK`). **US symbols**: bare ticker (e.g. `AAPL`, `A`).
- **Schema differs by market.** HK daily carries auction and price-limit fields (`opn_auc`, `opn_aucvol`, `cls_aucvol`, `uplimit*`, `lolimit*`, `lmt_refpr2`, `navalue`) that US daily does not; US daily carries block-trade fields (`blkcount`, `blkvolum`). Both carry `amount`, `vwap`, `num_moves`, `bid`, `ask`. Confirm the exact field list per market in `pandadata-api` before relying on any column.
- `close` on HK daily is the *theoretical* close; `alt_close` is the adjusted close (same value). Do not assume raw `close` is dividend-adjusted — apply `get_adj_factor` for return calcs.
- `get_hk_detail` / `get_us_detail` take a `status` flag (`1` listed, `0` delisted, `-1` unknown, `None` any). Report `delisted_date` when present; do not treat a delisted name as tradable.

## 3. Metric definitions (all derived — label them)

- **Window return (adjusted)**: `(adj_close_end / adj_close_start) - 1`, where `adj_close = close * adj_factor` over the window. State the window and that adjustment was applied. Never span an ex-rights date on raw `close`.
- **Realized volatility**: standard deviation of daily log returns over the window, optionally annualized (state the annualization factor and trading-day count used).
- **Average daily turnover / amount**: mean of `amount` (成交额) over the window; if a float-share field is available, turnover = 成交量 / 流通股, otherwise report 成交额 and 成交笔数 (`num_moves`) as the liquidity proxy and say so.
- **Price-volume / valuation metric**: read directly from `get_stock_pv_indicator` (HK) / `get_stock_pv_metric` (US); report the metric name verbatim from the source. Do not rename or reconstruct a metric the source did not provide.
- **Industry-relative position**: `metric_name(name) − metric_name(sector_median)` using `get_stock_industry_median` (HK) / `get_stock_sector_median` (US). Report as "高于/低于 行业中位 X"; this is a relative statement, not cheap/expensive.

## 4. Report skeleton (8 sections)

```
# 港美股行情估值扫描 · <市场> · <范围> · <数据日>
## 1. 摘要                （范围、市场、货币、数据日/窗口、3–5 条要点）
## 2. 标的与分类          （名称、板块/交易所、行业分类、上市状态）
## 3. 行情与流动性        （区间 OHLC、成交额、VWAP、成交笔数、日均流动性）
## 4. 复权收益与波动      （复权区间收益、波动率，注明已用 get_adj_factor）
## 5. 价量估值指标        （每个指标 + 来源接口 + 数据日）
## 6. 行业相对位置        （各指标 vs 行业/板块中位，方向与差距）
## 7. 风险提示            （克制措辞，非投资建议）
## 8. 数据说明            （表格见下）
```

数据说明表：`数据模块 | 市场 | 来源接口 | 查询窗口 | 返回行数 | 数据日 | 备注`。

## 5. Empty-data / failure handling

- HK/US coverage and field availability vary by name (small caps, recent listings, delisted names). If a section's method returns empty, keep the heading and write `无数据（<method>，<window>）`, do not drop it.
- If a whole-market cross-section pull is too slow or times out, narrow to the requested basket or shorten the window, generate available sections, and add a concise note under 数据说明.
- If `get_adj_factor` is unavailable for a name, report raw-price return **with an explicit caveat** that it is not ex-rights adjusted; never silently present a raw-price multi-day return as adjusted.

## 6. QA checklist

- [ ] Every price/valuation figure labeled with market **and** currency (HKD/USD).
- [ ] No HK and US figures mixed in one table without a market column.
- [ ] Every metric labeled with its data date / window.
- [ ] Multi-day returns spanning ex-rights use adjusted prices; adjustment stated.
- [ ] Source-note table present with method, window, row count, data date per module.
- [ ] Empty sections say `无数据` with method + window, not omitted.
- [ ] Wording is factual/relative; no directional calls or trading instructions.
- [ ] Ends with the standard disclaimer.
