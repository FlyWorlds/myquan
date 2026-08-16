[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 📊 HK/US Consensus Radar Skill

> A sourced **sell-side analyst consensus** view of **Hong Kong and US equities** — rating diffusion (strong-buy/buy/hold/sell/strong-sell), target-price upside vs current price, long-term growth expectations, and week/month consensus revisions — for a single name or a basket. Every number is traced to a Pandadata interface, market, currency, and data date.

## What it is

`hk-us-consensus-radar` is an **Agent Skill** answering "**what do analysts think about these HK/US names right now**": how buy/hold/sell ratings are distributed, how far the consensus target price sits above/below the current price, expected long-term growth, and whether ratings and target prices were revised up or down over the past week/month.

It reads *what analysts expect* (`get_stock_recommendation_*` / `get_stock_ncycl_*`), complementing the sibling `hk-us-quote-scan`, which reads *what the market did* (price/liquidity/valuation). Current price is used only to anchor target-price upside. Every claim carries its source interface, market, currency, and data date. Consensus is an **as-of snapshot of analyst opinion** — not a price forecast, and not the company's own guidance.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | Reads / market | When |
|---|---|---|
| 📊 **hk-us-consensus-radar** (this) | **HK/US sell-side consensus** (ratings/TP/growth/revisions) | HK/US analyst consensus, target-price upside, recent upgrades/downgrades |
| 🌏 `hk-us-quote-scan` | **HK/US price/liquidity/valuation** | Price, volume, valuation-vs-industry — **complementary** (opinion × price) |
| 📅 `earnings-season-tracker` | **A-share company self-forecasts** | A-share earnings-season company guidance (different source & market) |
| 🩺 `a-share-stock-dossier` / 🔎 `stock-screener` | **A-share** | A-share deep dive / screening |

## Market split (important)

Consensus data is split by market: **different method names, same schema.** Never call the HK method for a US ticker or vice versa.

| Market | Rating + target price | Non-cyclical (growth / TP) | Price anchor |
|---|---|---|---|
| Hong Kong | `get_stock_recommendation_consensus` | `get_stock_ncycl_consensus` | `get_hk_daily` |
| United States | `get_stock_recommendation_estimate` | `get_stock_ncycl_estimate` | `get_us_daily` |

## Report sections × interfaces

| Section | HK method | US method | Answers |
|---|---|---|---|
| Rating distribution | `get_stock_recommendation_consensus` | `get_stock_recommendation_estimate` | Strong-buy/buy/hold/sell/strong-sell counts, buy share, net rating |
| Target price & upside | above + `get_hk_daily` | above + `get_us_daily` | Consensus target (mean/median/high/low) and upside vs current price |
| Long-term growth | `get_stock_ncycl_consensus` (`LTGROWTH`) | `get_stock_ncycl_estimate` (`LTGROWTH`) | Expected 3–5y growth and dispersion |
| Coverage & dispersion | both families (`estimates_num`, `std`) | same | How many analysts cover it; consensus tightness |
| Consensus revisions | `_week` / `_month` suffixed fields | same | Rating migration and target-price revision over the recent window |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api         ~/.claude/skills/pandadata-api
cp -r skill-hk-us-consensus-radar ~/.claude/skills/hk-us-consensus-radar
```

Then ask, e.g. "what's the sell-side consensus on 0700.HK and how much target-price upside is left?" or "rank these US names by net rating and target-price upside".

## Core constraints

- Verify call contracts and available `_week`/`_month` suffixes via `pandadata-api` first.
- Use the correct method family per market (HK `_consensus`, US `_estimate`).
- Every upside states its target-price source (mean/median) and current-price anchor date; same currency both sides.
- Report coverage depth beside every consensus statistic; flag thin coverage.
- Do not blend `LTGROWTH` and `TP`.
- Present consensus as analyst opinion, not a price forecast or company guidance.
- Report no-coverage / empty results explicitly; do not omit.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
