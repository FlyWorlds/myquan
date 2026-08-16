---
name: hk-us-quote-scan
description: Scan Hong Kong and US equities with Pandadata HK/US interfaces, building
  a sourced cross-market snapshot of quotes, adjusted returns, liquidity, valuation
  price-volume metrics, and industry-relative position for a single name or a basket.
  Use when the user asks for 港股行情, 美股行情, 港美股扫描, 港股估值, 美股估值分位, 港美股对比, 港美股相对行业位置,
  港美股流动性, ADR/中概股快照, or a Hong Kong / US equity quote-and-valuation report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-hk-us-quote-scan
  repository_url: https://github.com/quantskills/skill-hk-us-quote-scan
  project_type: skill
  collection: hk-us-quote-scan
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - hk-stock
  - us-stock
  - quote
  - valuation
  - cross-market
  - pandadata
  platforms:
  - claude-code
  - codex
  - hermes
  - openclaw
  - cursor
  status: draft
  validation_level: runnable
  maintainer_type: community
  summary_zh: 港美股行情、复权收益、流动性、价量估值与行业相对位的横截面快照，每个数据点标注来源接口、市场、币种与数据日。
  summary_en: Hong Kong and US equity cross-market snapshot covering quotes, adjusted
    returns, liquidity, price-volume valuation, and industry-relative position, each
    figure traced to a Pandadata interface.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# HK/US Quote Scan

Use this skill to build a **sourced snapshot of Hong Kong and US equities** — for a single name or a basket — covering price and adjusted return, liquidity/turnover, price-volume valuation metrics, and where each name sits relative to its industry peers. Prefer Pandadata as the data source, keep every figure traceable to an interface and data date, and never invent missing prices, valuations, or symbols.

## Scope And Positioning (read first to avoid overlap)

This skill is the **HK/US market** quote-and-valuation view. It is deliberately distinct from broad company dossiers and the A-share ecosystem:

- Unlike `market-daily-review` (A-share whole-market after-close review) and `index-valuation-rotation` (A-share index valuation percentiles and industry rotation): those cover **A-share only**. This skill covers **HK and US names**, which those skills do not touch.
- Unlike `a-share-stock-dossier` (single A-share deep due diligence): this skill is **cross-market and cross-section** over HK/US names and reads the HK/US interface family (`get_hk_*`, `get_us_*`, `get_stock_pv_*`, `get_stock_*_median`), not the A-share fundamentals family.
- Unlike `hk-stock-dossier` (one Hong Kong company across fundamentals, ownership, events, and risks): this skill is a **quote, liquidity, and valuation snapshot** for HK/US names or baskets. Use the dossier for full-company due diligence and this skill for a comparable market snapshot.
- Unlike `hk-us-consensus-radar` (sell-side analyst consensus for HK/US): that skill reads analyst ratings and target prices (`get_stock_recommendation_*`, `get_stock_ncycl_*`). This skill reads **prices, liquidity, and realized valuation metrics**. The two are complementary: pair a cheap price-volume percentile here with a bullish consensus there before drawing any conclusion.
- Unlike `pandadata-warehouse` (bulk local caching): this skill produces an **analysis report**, not a local database. For repeated large HK/US pulls, hand the caching off to `pandadata-warehouse` and read from there.

## Symbol Conventions

State the market explicitly; the symbol shape differs and must not be mixed.

| Market | Symbol shape | Detail method | Daily method |
|---|---|---|---|
| 香港 | 4-digit + `.HK`, e.g. `0001.HK`, `0700.HK` | `get_hk_detail` | `get_hk_daily` |
| 美国 | ticker, e.g. `AAPL`, `A`, `NVDA` | `get_us_detail` | `get_us_daily` |

`get_hk_daily` / `get_us_daily` accept a `symbol` list plus `start_date` / `end_date` (`YYYYMMDD`, ≤5-year span). Passing an empty `symbol` list returns the whole market for the window — use that for cross-section scans, but bound the date window tightly because the market-wide pull is heavy.

## Workflow

1. Resolve the target: single name, an explicit basket, or a whole-market cross-section for one market. Confirm the market (HK or US) and the date window. Default the window to a recent trailing period (e.g. last ~120 trading days) so return, volatility, and liquidity have enough history.
2. Read `references/scan-playbook.md` before the first scan in a session. Use it for the routing table, metric definitions (adjusted return, turnover, price-volume percentile, industry-relative position), the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the exact method section in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials. HK and US response schemas differ (HK carries auction/limit fields; US carries block-trade fields) — confirm per market.
4. Collect evidence per market:
   - Identity & classification: `get_hk_detail` / `get_us_detail` for name, board/exchange, `business_sector` / `economic_sector` / `industry_group`, listing status.
   - Quotes: `get_hk_daily` / `get_us_daily` for OHLCV, `amount`, `vwap`, `num_moves` over the window.
   - Adjusted return: `get_adj_factor` to restore prices before computing multi-day returns across ex-rights events.
   - Valuation & price-volume: `get_stock_pv_indicator` (HK) / `get_stock_pv_metric` (US) for latest price-volume/valuation indicators.
   - Industry-relative position: `get_stock_industry_median` (HK) / `get_stock_sector_median` (US) for the peer-median baseline to place each name against its sector.
5. Compute cross-sectional metrics from raw rows: window return (adjusted), realized volatility, average daily turnover/amount, and each valuation metric's position **relative to its industry/sector median**. Keep raw row counts long enough to cite source method, data date, and missing-data status.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/hk-us/<market>-<scope>-<date>.md` (e.g. `reports/hk-us/hk-basket-20260703.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing data-date labels, mixed-market leakage, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | HK methods | US methods | What it answers |
|---|---|---|---|
| 标的与分类 | `get_hk_detail` | `get_us_detail` | Name, board/exchange, industry classification, listing status. |
| 行情与流动性 | `get_hk_daily` | `get_us_daily` | OHLCV, 成交额, VWAP, 成交笔数, average turnover over the window. |
| 复权收益 | `get_hk_daily` + `get_adj_factor` | `get_us_daily` + `get_adj_factor` | Window return and volatility on adjusted prices. |
| 价量估值指标 | `get_stock_pv_indicator` | `get_stock_pv_metric` | Latest price-volume / valuation indicators per name. |
| 行业相对位置 | `get_stock_industry_median` | `get_stock_sector_median` | Where each valuation/price-volume metric sits vs its sector median. |

## Analysis Modes

- **Single-name snapshot**: one HK or US ticker over the window — identity, adjusted return path, liquidity profile, valuation metrics, and industry-relative read.
- **Basket compare**: an explicit list within one market — rank by window return, turnover, and valuation-vs-median. Keep the market homogeneous; never rank HK and US names in the same table without labeling currency and market.
- **Cross-market pairing**: the same economic exposure across markets (e.g. an A/H pair discussed alongside its US-listed ADR when the user names both) — present side by side, but never net returns across currencies; report each in its own currency and flag the FX caveat.
- **Industry-relative position**: for each valuation/price-volume metric, compare the name to its `..._median` sector baseline and report the direction and gap. This is a relative statement, not a cheap/expensive verdict.

## Report Rules

- Write in Chinese unless the user requests another language.
- Label the **market and currency** on every price and valuation figure (HKD vs USD). Never mix HK and US figures in one table without an explicit market column.
- Mark the data date / window on every metric. Quotes are a snapshot; state the as-of trading day.
- Use **adjusted prices** for any multi-day return that spans a dividend or split; state that `get_adj_factor` was applied. Never compare raw closes across an ex-rights date.
- Separate facts, derived metrics, and judgment. Label derived calculations such as window return, volatility, average turnover, and industry-relative gaps.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section — HK/US coverage and field availability vary by name.
- Keep the tone factual and structural. Use "可能提示", "需要关注", and "相对行业中位" rather than directional calls; never give trading instructions or personalized investment advice.

## Resource Guide

- `references/scan-playbook.md`: routing table, metric definitions, HK/US symbol and schema notes, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, market/currency labels, data-date labels, and the disclaimer.

## Quality Bar

- Every material claim must trace to a Pandadata method, data date, and queried window.
- HK and US figures are never mixed without a market/currency label; returns are never netted across currencies.
- Multi-day returns spanning ex-rights events use adjusted prices via `get_adj_factor`.
- Industry-relative reads are stated as relative-to-median, not as valuation verdicts.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
