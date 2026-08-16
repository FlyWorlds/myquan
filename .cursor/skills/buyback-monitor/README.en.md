[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 🔁 Buyback Monitor Skill

> An A-share **share-buyback (repurchase) monitor**: track each event through its procedure stages (proposal → resolution → executing → done/cancellation), classify buyback purpose (cancellation vs incentive vs value-management), measure intensity as a **share of total capital**, and compare the announced price band to the market price — for the whole market over a window or a single name. Every figure is traced to `get_repurchase` and an announcement/stage date.

## What it is

`buyback-monitor` is an **Agent Skill** that scans A-share `get_repurchase` around **buyback events** and answers "**who is buying back, how far along, for what purpose, how large, and at what price band**".

`get_repurchase` returns **one row per stage per event** (proposal → resolution → executing → …), so the skill first **deduplicates to the event**, then tracks its latest stage. It separates **cancellation buybacks** (permanently reduce share count, most accretive) from **incentive/ESOP buybacks** (shares may be re-issued), measures intensity via `buy_back_percent` (share of total capital), and compares the price band to the current price. Every claim carries its source interface and announcement/stage date; a scan is an **as-of snapshot** — buyback events accumulate and progress.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 🔁 **buyback-monitor** (this) | **Buyback events** whole-market scan / single-name timeline | Recent buyback scans, cancellation buybacks, intensity ranking, one name's buyback progress |
| 🩺 `a-share-stock-dossier` | Single-name deep due diligence (buyback is one sub-section) | Full company dossier |
| 🚨 `event-risk-alert` | Per-name **risk** events (unlocks/pledges/reductions) | Watch your own holdings for risk (buyback is usually a positive signal) |
| 📅 `earnings-season-tracker` / 📈 `market-daily-review` | Earnings / daily whole-market | Different event families; buyback names can cross-check |

## Buyback event model (read before analysis)

- **`procedure`** — report each event's **latest** stage; a proposal (预案) is intention, never presented as executed spend.
- **Purpose** — `write_off_date` or 注销/减少注册资本 → cancellation; 股权激励/员工持股 → incentive; 维护公司价值 → value-management; otherwise 未分类 (do not guess).
- **Intensity** — primary `buy_back_percent` (share of total capital); `buy_back_value` and `value_floor`/`value_ceiling` (planned range, **not** spent) for absolute scale.
- **Price band** — `price_floor`/`price_ceiling`/`buy_back_price` vs `get_stock_daily` close.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Event overview | `get_repurchase` | New events in window; distinct events after dedup |
| Stage funnel | `get_repurchase` (`procedure`) | Counts at proposal / resolution / executing / done / cancellation |
| Purpose classification | `get_repurchase` (`purpose`, `write_off_date`, `buy_back_mode`) | Cancellation vs incentive vs value-management mix |
| Intensity ranking | `get_repurchase` (`buy_back_percent`, `buy_back_value`) | Largest by share of capital and by amount |
| Price-band comparison | `get_repurchase` band + `get_stock_daily` | Band vs current market price |
| Industry distribution | `get_stock_industry` + above | Which industries buy back most |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api   ~/.claude/skills/pandadata-api
cp -r skill-buyback-monitor ~/.claude/skills/buyback-monitor
```

Then ask, e.g. "scan the last 90 days of A-share buybacks with a stage funnel and purpose mix" or "which cancellation buybacks are largest by share of total capital?".

## Core constraints

- Verify the `get_repurchase` contract via `pandadata-api` first.
- Deduplicate events across procedure stages before any market-wide count; report the latest stage.
- Always distinguish 预案 (planned range) from executed amounts.
- Classify purpose from source signals; assert cancellation only with `write_off_date` or an explicit purpose; ambiguous → 未分类.
- Rank intensity on `buy_back_percent` with absolute scale beside it.
- Report empty results explicitly; a scan is a snapshot — label the window and date.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
