[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 🌏 HK/US Quote Scan Skill

> A sourced cross-market snapshot of **Hong Kong and US equities** — quotes, adjusted returns, liquidity, price-volume valuation, and industry-relative position — for a single name, a basket, or a whole-market cross-section. Every figure is traced to a Pandadata interface, market, currency, and data date.

## What it is

`hk-us-quote-scan` is an **Agent Skill** that answers "**what do these HK/US names look like on price, liquidity, valuation, and relative-to-industry position right now**": adjusted window return, realized volatility, average daily liquidity, price-volume valuation metrics, and where each metric sits versus its sector median.

The skill reads the `get_hk_*` / `get_us_*` / `get_stock_pv_*` / `get_stock_*_median` interface family. Every claim carries its source interface, market, currency, and data date; quotes are a **snapshot of one trading day**.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api). This skill decides *what to query and how to compute*, not *what the interface looks like*.

## Boundaries (avoid overlap)

| Skill | Market / view | When |
|---|---|---|
| 🌏 **hk-us-quote-scan** (this) | **HK / US** quote & valuation cross-section | HK/US quote-valuation snapshots, industry-relative valuation, HK/US basket compare |
| 📊 `hk-us-consensus-radar` | **HK / US** sell-side consensus | Analyst ratings & target prices — **complementary** (price-volume × opinion) |
| 📈 `market-daily-review` | **A-share** after-close review | A-share daily review (does not cover HK/US) |
| 🌡️ `index-valuation-rotation` | **A-share** index valuation & rotation | A-share index valuation/rotation (does not cover HK/US) |
| 🩺 `a-share-stock-dossier` | **A-share** single-name due diligence | Deep dive on one A-share name |
| 🗄️ `pandadata-warehouse` | Bulk local caching | Repeated large HK/US pulls → cache there, read from it |

## Report sections × interfaces

| Section | HK method | US method | Answers |
|---|---|---|---|
| Identity & classification | `get_hk_detail` | `get_us_detail` | Name, board/exchange, industry, listing status |
| Quotes & liquidity | `get_hk_daily` | `get_us_daily` | OHLCV, amount, VWAP, trade count, average turnover |
| Adjusted return | `get_hk_daily` + `get_adj_factor` | `get_us_daily` + `get_adj_factor` | Window return & volatility on adjusted prices |
| Price-volume valuation | `get_stock_pv_indicator` | `get_stock_pv_metric` | Latest price-volume / valuation metrics |
| Industry-relative position | `get_stock_industry_median` | `get_stock_sector_median` | Each metric vs its sector median |

## Symbol conventions

| Market | Symbol shape | Detail | Daily |
|---|---|---|---|
| Hong Kong | 4-digit zero-padded + `.HK` (`0001.HK`, `0700.HK`) | `get_hk_detail` | `get_hk_daily` |
| United States | bare ticker (`AAPL`, `NVDA`) | `get_us_detail` | `get_us_daily` |

An empty `symbol` list returns the whole market for the window (heavy — keep the window tight). HK and US response schemas differ (HK carries auction/limit fields, US carries block-trade fields) — confirm per market in `pandadata-api`.

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api    ~/.claude/skills/pandadata-api
cp -r skill-hk-us-quote-scan ~/.claude/skills/hk-us-quote-scan
```

Then ask in natural language, e.g. "give me a quote-valuation snapshot for 0700.HK over the last six months" or "compare AAPL, NVDA, MSFT on window return, liquidity, and valuation-vs-industry".

## Core constraints

- Verify every call contract via `pandadata-api` first; confirm HK/US fields per market.
- Label market and currency (HKD/USD) on every figure; never mix HK and US in one table.
- Use `get_adj_factor`-adjusted prices for multi-day returns spanning ex-rights events.
- Never net returns or amounts across currencies.
- Industry-relative reads are relative-to-median statements, not cheap/expensive verdicts.
- Report empty results as `无数据` with method + window; do not omit.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
