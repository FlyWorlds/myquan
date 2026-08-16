[简体中文](README.md) | **English**

# 🎯 Block Trade Radar Skill

> An A-share **block-trade (大宗交易) discount/premium radar**: join every block-trade print to the **same-day close** to compute a discount/premium rate, read **机构专用 (institutional-seat)** buy/sell direction, flag **repeated discounted takeovers** and **same-branch wash-like prints**, and rank names by amount and by discount — for the whole market over a window or a single name. Every figure carries its source interface, trade date, and (for the discount) the close it was computed against.

## What it is

`block-trade-radar` is an **Agent Skill** that scans A-share `get_block_trade` around **block trades** and answers "**who is taking blocks at a discount / offloading at a premium, how deep, is the institutional seat absorbing or distributing, and which prints are same-branch wash trades**".

`get_block_trade` returns **one row per print** (`symbol`+`date`+`sequence_id`); a large reduction is often split into many prints. **The discount/premium is not a field** — the skill computes it against the `get_stock_daily` same-day close: `折溢价率 = price / same-day close − 1` (negative = discount, positive = premium). `机构专用` on the buyer = 接盘 (absorbing), on the seller = 出货 (distributing) — an anonymous seat, never named. `buyer == seller` prints are treated as 对倒/过券 (internal transfers), listed separately and excluded from the directional net. Every claim carries its source interface, trade date, and discount basis; a scan is an as-of snapshot.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 🎯 **block-trade-radar** (this) | **Block-trade discount/premium** whole-market scan / single-name timeline | Recent block-trade scans, deepest discounted takeovers, amount ranking, one name's block-trade discount |
| 📈 `market-daily-review` | Daily whole-market review (block trades are one line item) | Full end-of-day review |
| 🧠 `smart-money-profiler` | 龙虎榜 / northbound / margin "smart money" across **营业部 seats** | The daily 龙虎榜 board (block trades are a separate off-exchange channel) |
| 🚨 `event-risk-alert` | Per-name **risk** events (unlocks/pledges/reductions) | Watch your own holdings for risk |

## Block-trade model (read before analysis)

- **Discount/premium** (computed): `price / same-day close − 1`; negative = discount (common — buyer demands a discount to absorb), positive = premium (rarer); missing close → mark `待补` and exclude.
- **Direction**: `机构专用` on buyer = absorbing, on seller = distributing — anonymous seat, not named.
- **Wash prints**: `buyer == seller` (same branch) → internal transfer, listed separately and excluded from the directional net.
- **Aggregation**: aggregate per `symbol`+`date` (print count, total amount, amount-weighted discount) before ranking.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Overview | `get_block_trade` | Prints, names, total amount in the window |
| Discount/premium distribution | `get_block_trade` (`price`) + `get_stock_daily` (close) | Split across deep-discount / discount / par / premium |
| Institutional direction | `get_block_trade` (`buyer`, `seller`) | Net absorbing vs distributing |
| Amount / discount ranking | `get_block_trade` (`amount`) + computed rate | Largest by amount, deepest discount, repeat-discount names |
| Wash-print flag | `get_block_trade` (`buyer==seller`) | Same-branch prints excluded from the net |
| Industry distribution | `get_stock_industry` + above | Which industries see the most block flow |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api     ~/.claude/skills/pandadata-api
cp -r skill-block-trade-radar ~/.claude/skills/block-trade-radar
```

Then ask, e.g. "scan the last 30 trading days of A-share block trades with a discount distribution and institutional direction" or "which names show the deepest discounted takeovers?".

## Core constraints

- Verify the `get_block_trade` and `get_stock_daily` contracts via `pandadata-api` first.
- Compute 折溢价率 as `price / same-day close − 1`, always naming the `get_stock_daily` close basis; mark missing-close prints `待补`.
- Read direction from `buyer`/`seller` verbatim; `机构专用` is anonymous — never name it.
- Flag `buyer==seller` prints as wash trades and exclude them from the directional net.
- Aggregate prints per `symbol`+`date` before ranking.
- Report empty results explicitly; a scan is a snapshot — label the window and date.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
