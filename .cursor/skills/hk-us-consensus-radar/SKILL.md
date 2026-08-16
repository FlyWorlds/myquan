---
name: hk-us-consensus-radar
description: Track sell-side analyst consensus for Hong Kong and US equities with
  Pandadata consensus interfaces, aggregating buy/hold/sell rating diffusion, target-price
  upside versus current price, long-term growth expectations, and week/month consensus
  revisions into a sourced report for a single name or a basket. Use when the user
  asks for 港股一致预期, 美股一致预期, 卖方评级, 分析师评级分布, 目标价上行空间, 目标价空间, 评级上调下调, 一致预期变化,
  港美股买卖建议, or a Hong Kong / US analyst-consensus report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-hk-us-consensus-radar
  repository_url: https://github.com/quantskills/skill-hk-us-consensus-radar
  project_type: skill
  collection: hk-us-consensus-radar
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
  - hk-stock
  - us-stock
  - analyst-consensus
  - target-price
  - rating
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
  summary_zh: 港美股卖方一致预期雷达：评级分布(强买/买/持有/卖/强卖)、目标价相对现价上行空间、长期成长预期、周/月一致预期变化，每个数值标注来源接口与数据日。
  summary_en: Sell-side consensus radar for HK/US equities — rating diffusion, target-price
    upside vs current price, long-term growth expectations, and week/month revisions,
    each traced to a Pandadata interface.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# HK/US Consensus Radar

Use this skill to build a **sourced sell-side analyst consensus view of Hong Kong and US equities** — for a single name or a basket — covering how buy/hold/sell ratings are distributed, how far the consensus target price sits above or below the current price, what long-term growth analysts expect, and how the consensus has shifted over the past week/month. Prefer Pandadata as the data source, keep every number traceable to an interface and data date, and never invent ratings, target prices, or symbols.

## Scope And Positioning (read first to avoid overlap)

This skill is the **sell-side opinion** view for HK/US names. It reads the analyst-consensus interface family and is deliberately distinct from its siblings:

- Unlike `hk-us-quote-scan` (HK/US prices, liquidity, realized valuation): that skill reads what the *market* did (`get_hk_daily`, `get_stock_pv_*`). This skill reads what *analysts expect* (`get_stock_recommendation_*`, `get_stock_ncycl_*`). Pair them: a bullish consensus here means more when the price-volume percentile there is still low, and vice versa. This skill pulls current price from `get_hk_daily` / `get_us_daily` **only** to anchor target-price upside — not for market analysis.
- Unlike `earnings-season-tracker` (A-share **company self-issued** performance forecasts, `get_fina_forecast`): this skill reads **third-party sell-side** consensus for **HK/US** names, a different data source, opinion type, and market. A company's own forecast and analysts' consensus are not the same signal.
- Unlike `a-share-stock-dossier` / `stock-screener` (A-share): those are A-share only. Analyst-consensus interfaces in this SDK are the HK/US family; A-share consensus is out of scope here.
- Unlike `hk-stock-dossier` (one Hong Kong company across fundamentals, ownership, events, and risks): this skill isolates **sell-side consensus and revisions** across HK/US names or baskets. Use the dossier for broad due diligence and this skill for analyst-expectation monitoring.

## Market Split (important)

Consensus data is split by market with **different method names but the same schema**:

| Market | Rating & target-price consensus | Non-cyclical indicators (growth / TP) | Current price anchor |
|---|---|---|---|
| 香港 | `get_stock_recommendation_consensus` | `get_stock_ncycl_consensus` | `get_hk_daily` |
| 美国 | `get_stock_recommendation_estimate` | `get_stock_ncycl_estimate` | `get_us_daily` |

Never call the HK method for a US ticker or vice versa. Pass an empty `symbol` list to pull the whole market's consensus (heavy).

## Consensus Field Model

Both `recommendation` methods return, per name:

- **Rating counts**: `strong_buy_num`, `buy_num`, `hold`, `sell_num`, `strong_sell_num`, `no_opinion_num`, `recommendations_num`.
- **Target-price stats**: `mean`, `median`, `high`, `low` (consensus target price), plus `currency`.
- **Time-window suffixes**: many fields exist in `_week` / `_month` / `_6month` variants (e.g. `buy_num_week`, `high_week`, `std_6month`). Use the base-vs-suffix difference to measure **revisions** (rating migration and target-price drift). Confirm the exact available suffixes per field in `pandadata-api`; do not assume a suffix exists.

The `ncycl` methods return, per name and per `indicator`: `LTGROWTH` (未来 3–5 年长期成长预期) and `TP` (未来 1 年目标价), with `mean`, `median`, `high`, `low`, `std`, `estimates_num`, `included_estimates_num`.

## Workflow

1. Resolve the target: single name, an explicit basket, or a whole-market cross-section. Confirm the market (HK or US) so the correct method family is used. Confirm the current-price date for upside calculation.
2. Read `references/consensus-playbook.md` before the first run in a session. Use it for the routing table, metric definitions (rating diffusion, target-price upside, revision, coverage depth), the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the exact method section in `references/api-docs.md` to confirm parameters, fields, and which `_week` / `_month` suffixes exist; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence per market:
   - Ratings & target price: `get_stock_recommendation_consensus` (HK) / `get_stock_recommendation_estimate` (US).
   - Growth & 1-year TP: `get_stock_ncycl_consensus` (HK) / `get_stock_ncycl_estimate` (US), filtering `indicator` in {`LTGROWTH`, `TP`}.
   - Current price anchor: `get_hk_daily` / `get_us_daily` (latest close in window) — used only to compute upside.
5. Compute derived metrics from raw rows: rating diffusion (buy share, sell share, net rating), target-price upside = consensus TP / current price − 1, coverage depth (`recommendations_num`, `estimates_num`), consensus dispersion (`std`, high–low band), and revisions from `_week` / `_month` deltas. Keep raw row counts long enough to cite source method, data date, and missing-data status.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/consensus/<market>-<scope>-<date>.md` (e.g. `reports/consensus/us-basket-20260703.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing data-date labels, a missing upside-baseline note, mixed-market leakage, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | HK method | US method | What it answers |
|---|---|---|---|
| 评级分布 | `get_stock_recommendation_consensus` | `get_stock_recommendation_estimate` | Strong-buy / buy / hold / sell / strong-sell counts; buy vs sell share; net rating. |
| 目标价与上行空间 | `get_stock_recommendation_consensus` (+ `get_hk_daily`) | `get_stock_recommendation_estimate` (+ `get_us_daily`) | Consensus target (mean/median/high/low) and upside vs current price. |
| 长期成长预期 | `get_stock_ncycl_consensus` (`LTGROWTH`) | `get_stock_ncycl_estimate` (`LTGROWTH`) | Expected 3–5y long-term growth and its dispersion. |
| 覆盖广度与分歧 | both consensus + ncycl (`estimates_num`, `std`) | same | How many analysts cover it; how tight/wide the consensus is. |
| 一致预期变化 | `_week` / `_month` suffixed fields | same | Rating migration and target-price revision over the recent window. |

## Analysis Modes

- **Single-name radar**: one HK or US name — rating breakdown, target-price upside, growth expectation, coverage depth, dispersion, and recent revision.
- **Basket ranking**: an explicit list within one market — rank by net rating, target-price upside, or recent upgrade momentum. Keep the market homogeneous and label the currency.
- **Consensus revision**: use `_week` / `_month` deltas to flag names where buys rose/fell or target price was revised up/down. State the two windows compared; a revision is a change in analyst opinion, not a price move.
- **Upside vs conviction**: cross-read high target-price upside against coverage depth and dispersion — a large upside from one analyst with a wide band is weaker evidence than a modest upside with deep, tight coverage. Report both; never rank on upside alone.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Every upside figure must name its baseline**: consensus target-price source (mean vs median) and the current-price date used. Never state an upside without the anchor price and date.
- Label the market and currency on every target price. Never mix HK and US names in one table without a market column.
- Consensus is an **as-of snapshot** of analyst views; state the data date. It is not a forecast of price and not the company's own guidance.
- Separate facts (raw counts, raw target prices), derived metrics (shares, upside, revisions), and judgment. Label all derived calculations.
- Report coverage depth alongside any consensus statistic. A consensus from very few analysts is thin evidence — say so with `recommendations_num` / `estimates_num`.
- Treat empty API results as evidence. State "无数据" with the method name and queried symbol instead of silently omitting a section — many small caps have no coverage.
- Keep the tone factual and structural. Use "一致预期偏多/偏空", "覆盖偏薄", "近一月上调" rather than directional calls; never give trading instructions or personalized investment advice.

## Resource Guide

- `references/consensus-playbook.md`: routing table, metric definitions, market-split and suffix notes, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, market/currency labels, upside-baseline note, data-date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to a Pandadata method, data date, and market.
- Every upside states its target-price source (mean/median) and current-price anchor date.
- HK and US names are never mixed without a market/currency label.
- Coverage depth is reported alongside any consensus statistic; thin coverage is flagged.
- Consensus is presented as analyst opinion, not as a price forecast or company guidance.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
