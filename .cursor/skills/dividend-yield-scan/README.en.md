[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 💰 Dividend Yield Scan Skill

> An A-share **high-dividend / dividend-quality cross-section**: compute the trailing **dividend yield** from cash dividends and price, rank it, measure **payout continuity** (consecutive dividend years), **separate real cash return from stock dividends (送转)**, list upcoming **ex-dividend dates**, and roll names up by industry — for the whole market or a basket. Every figure is traced to a dividend interface and a dividend date.

## What it is

`dividend-yield-scan` is an **Agent Skill** that scans A-share dividends and answers "**who yields the most, how many years running, cash or 送转, and when does it go ex-dividend**".

It joins four interfaces: `get_stock_cash_dividend` (cash → yield), `get_stock_dividend` (`div_type` → cash vs 送转), `get_stock_dividend_amount` (total amount + proposal/execution stage), and `get_stock_split` (送转/split context).

> ⚠️ **One key pitfall**: `div_cash_gross` is the pre-tax cash dividend **per `round_lot`** (typically 10 shares), so **per-share = `div_cash_gross` / `round_lot`**. Forgetting the divisor inflates yield 10×. Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 💰 **dividend-yield-scan** (this) | **Dividend / high-yield cross-section** (yield · continuity · cash vs 送转) | Yield ranking, high-dividend lists, continuity streaks, dividend quality |
| 🔎 `stock-screener` | Natural-language multi-filter screening ("连续分红" is one filter slot) | Combine dividend with unrelated filters (northbound / pledge / industry) |
| 🩺 `a-share-stock-dossier` | Single-name deep due diligence (dividends are one sub-section) | Full company dossier |
| 📈 `index-valuation-rotation` | Index PE/PB percentiles / industry momentum | Valuation / rotation lens (complements dividend style) |

## Dividend model (read before analysis)

- **Yield method** — per-share = `div_cash_gross` / `round_lot`; trailing yield = trailing-12M cash DPS ÷ latest close (`get_stock_daily`); state window + price date + "cash only, 送转 excluded".
- **Cash vs 送转** — `transferred/bonus share` is not cash return; never fold into cash yield.
- **Proposed ≠ paid** — label `get_stock_dividend_amount`'s `event_stage` (预案 vs 方案实施).
- **Yield is backward-looking** — based on paid/declared dividends, not a forecast.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Dividend overview | `get_stock_cash_dividend`, `get_stock_dividend` | Recent dividends; cash vs 送转 mix |
| Yield ranking | `get_stock_cash_dividend` (÷ `round_lot`) + `get_stock_daily` | Highest trailing yield |
| Continuity | `get_stock_cash_dividend` (multi-year) | Consecutive dividend years |
| Cash vs 送转 | `get_stock_dividend` (`div_type`) | Which "dividends" are real cash |
| Ex-dividend calendar | `get_stock_cash_dividend` (`ex_date`) | Upcoming ex-dividend dates |
| Payout (optional) | `get_stock_dividend_amount` + fina | Payout vs net profit |
| Industry distribution | `get_stock_industry` + above | Which industries pay the most cash |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api       ~/.claude/skills/pandadata-api
cp -r skill-dividend-yield-scan ~/.claude/skills/dividend-yield-scan
```

Then ask, e.g. "give me a whole-market dividend-yield ranking, cash only, with the method stated" or "the longest-streak, highest-yield names in CSI 300".

## Core constraints

- Verify the dividend-method contracts via `pandadata-api` first (especially `round_lot`).
- Per-share cash = `div_cash_gross` / `round_lot`; state the divisor to avoid a 10× error.
- Every yield states trailing window, price date, and "cash only, 送转 excluded".
- Separate cash from 送转; label `get_stock_dividend_amount` stages (预案 vs 实施).
- Frame yield as backward-looking, not a forecast.
- Report empty results explicitly; label the window and date.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
