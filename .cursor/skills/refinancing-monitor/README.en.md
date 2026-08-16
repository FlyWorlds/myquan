[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 💧 Refinancing Monitor Skill

> An A-share **equity-refinancing monitor**: track **private placements** (`get_stock_private_placement`) and **rights issues** (`get_stock_allotment`) through their approval stages (proposal → resolution/review → CSRC approval → executed), measure dilution as a **share of total capital**, compare the issue/allotment price to the market price (discount and break-issue), and roll events up by industry — for the whole market over a window or a single name. Every figure is traced to its source interface and an announcement/stage date.

## What it is

`refinancing-monitor` is an **Agent Skill** that scans A-share private placements and rights issues around **refinancing events** and answers "**who is raising equity, how far along, how much dilution, at what price, and has it broken issue**". It is the **mirror** of [`buyback-monitor`](https://github.com/quantskills/skill-buyback-monitor): refinancing **raises** capital and **dilutes** existing holders — opposite direction, same event shape.

Both interfaces return **one row per event stage**, so the skill first **deduplicates to the deal**, then tracks its latest stage. It keeps **private placements** (to specific investors) and **rights issues** (pro-rata to all holders) as separate streams, measures dilution via new shares ÷ total capital (`get_share_float`), and compares the issue/allotment price to the market close for discount and break-issue.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 💧 **refinancing-monitor** (this) | **Refinancing events** (placements/rights) whole-market scan / single-name timeline | Recent placement scans, rights issues, dilution ranking, one name's break-issue |
| 🔁 `buyback-monitor` | **Buyback events** (capital return, opposite direction) | Who is buying back, cancellation buybacks |
| 🚨 `event-risk-alert` | Per-name **risk** events (unlocks/pledges/reductions) | Watch your own holdings (a completed placement creates a future unlock) |
| 🩺 `a-share-stock-dossier` | Single-name deep due diligence (capital action is one sub-section) | Full company dossier |

## Refinancing event model (read before analysis)

- **`issue_status`** — report each deal's **latest** stage; a proposal (预案) is intention, never presented as raised capital.
- **Placement vs rights** — the two interfaces are separate; always report the split (they dilute differently).
- **Dilution** — `issued_shares`/`actual_shares` ÷ total shares (`get_share_float`), labeled planned vs executed.
- **Discount / break-issue** — `issue_price`/`allotment_price` vs `get_stock_daily` close; executed and current close < issue price = break-issue (破发).
- **Take-up gap** — rights issue `actual_ratio` < `planned_ratio` = under-subscription.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Event overview | `get_stock_private_placement`, `get_stock_allotment` | New deals; placement vs rights; distinct deals after dedup |
| Stage funnel | `get_stock_private_placement` (`issue_status`) | Counts at proposal / review / approval / executed |
| Discount & break-issue | issue/allotment price + `get_stock_daily` | Price vs market; executed deals that broke issue |
| Dilution ranking | `issued_shares`/`actual_shares` + `get_share_float` | Largest by share of total capital |
| Take-up gap | `get_stock_allotment` (`planned` vs `actual`) | Under-subscribed rights issues |
| Industry distribution | `get_stock_industry` + above | Which industries raise equity most |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api       ~/.claude/skills/pandadata-api
cp -r skill-refinancing-monitor ~/.claude/skills/refinancing-monitor
```

Then ask, e.g. "scan the last 180 days of A-share private placements with a stage funnel and dilution ranking" or "which rights issues were under-subscribed?".

## Core constraints

- Verify the `get_stock_private_placement` / `get_stock_allotment` contract via `pandadata-api` first.
- Keep placements and rights issues as separate streams; deduplicate each across stages before any market-wide count.
- Always distinguish 预案 (planned) from executed capital.
- Compute dilution against a stated share base (`get_share_float`); note a missing base, do not guess.
- Compare price to market via `get_stock_daily` for discount and break-issue; state both as relative.
- Report empty results explicitly; a scan is a snapshot — label the window and date.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
