[简体中文](README.md) | **English**

# 🕵️ HK/US Insider Radar Skill

> An HK/US **insider (董监高 / large-holder) trading signal radar**: separate **open-market buys vs sales** from **option exercises / gifts / scheduled sales**, weight by **insider role** (director/CEO/CFO/large holder) and `is_main_role`, net **shares and value** over a window, flag **cluster buying/selling** and **holding-trajectory** changes, and rank names by net insider direction — for one name or a watchlist. Every figure carries its source interface, filing/trade date, and currency.

## What it is

`hk-us-insider-radar` is an **Agent Skill** that reads HK `get_stock_insider_trade` and US `get_stock_insider_transaction` to answer "**who is buying their own company's shares with cash, who is selling, is it a director/officer or a peripheral holder, are they scaling in or exiting, and are multiple insiders clustering into buys**".

Both interfaces share the **same field schema** and return **one row per transaction** (`symbol`+`investor_name`+`transaction_date`). **Direction is not a separate field** — infer it from the **sign** of `adjusted_trade_shares` (negative = sell, positive = buy) together with `transaction_type`; `transaction_type`/`acquisition_type` further separate **open-market buys/sales** from **option exercises, gifts/inheritance, and scheduled sales**, with an open-market cash buy (especially by a director/CEO) the strongest signal. `insider_role`+`is_main_role` say *who* traded; `adjusted_sharehold` gives post-trade holdings for scale-in vs exit. `info_date` (filing) ≠ `transaction_date` (trade) — insiders file after the fact.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 🕵️ **hk-us-insider-radar** (this) | HK/US **insider-trading** signal | Is an insider buying or selling, cluster buying by directors, one name's net insider direction |
| 💹 `hk-us-quote-scan` | HK/US **price-volume / valuation** snapshot | Quote and valuation (this skill uses price only as context) |
| 🔮 `hk-us-consensus-radar` | Sell-side **analyst** consensus / ratings | What the street thinks (insiders ≠ analysts, often contrarian) |
| 🚨 `event-risk-alert` | A-share watchlist risk events (unlock/pledge/reduction) | A-share reduction monitoring (this skill covers HK/US, a different data model) |

## Insider trade model (read before analysis)

- **The headline net is open-market only**: option exercises, gifts, and scheduled sales are listed separately and never merged into the net.
- **Direction**: sign of `adjusted_trade_shares` + `transaction_type` together — never inferred from price or holdings.
- **Weighting**: directors/CEO/CFO/large holders weigh more; `is_main_role=1` marks the principal in a multi-insider filing.
- **Filing lag**: window is on `info_date` (filing); `transaction_date` (trade) comes earlier.
- **Currency**: value is split by `currency` (HKD/USD); never summed across currencies.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Overview | `get_stock_insider_trade` / `get_stock_insider_transaction` | Transactions, distinct insiders, total value by currency |
| Direction & type split | same (`transaction_type`, `acquisition_type`, signed shares) | Open-market buy/sale vs option/gift/plan; open-market net |
| Role weighting | same (`insider_role`, `is_main_role`) | Principals vs peripheral holders |
| Cluster buying/selling | same (per-insider aggregation) | Cross-insider clusters / repeat by one insider |
| Holding trajectory | same (`adjusted_sharehold`) | Scale-in / reduce / exit |
| Price context (optional) | `get_stock_pv_indicator` / `get_stock_pv_metric` | Where the trades sit vs the quote |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api        ~/.claude/skills/pandadata-api
cp -r skill-hk-us-insider-radar  ~/.claude/skills/hk-us-insider-radar
```

Then ask, e.g. "is anyone at 0700.HK buying or selling over the last 90 days, splitting open-market from option exercises?" or "any cluster insider buying at AAPL, with net buy and holding changes?".

## Core constraints

- Verify the `get_stock_insider_trade` / `get_stock_insider_transaction` contracts via `pandadata-api` first.
- Route by market: `.HK` → `get_stock_insider_trade`, US tickers → `get_stock_insider_transaction`.
- Keep the headline net **open-market only**; list option/gift/scheduled dispositions separately.
- Read direction from the **signed** share count and `transaction_type`, never from price or holdings alone.
- State the filing lag (`info_date` ≠ `transaction_date`); report value per `currency`; weight principals via `insider_role`/`is_main_role`.
- Report empty results explicitly; label the window and market.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
