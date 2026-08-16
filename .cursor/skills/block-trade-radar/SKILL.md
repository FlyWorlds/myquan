---
name: block-trade-radar
description: Scan and read A-share block-trade (大宗交易) activity with the Pandadata
  get_block_trade interface, joining each trade to the same-day close from get_stock_daily
  to compute discount/premium (折溢价率), reading institutional (机构专用) buy/sell direction,
  flagging repeated discounted takeovers and same-branch wash-like prints, and ranking
  names by block-trade amount and premium/discount — for the whole market over a window
  or a single name. Use when the user asks for 大宗交易, 大宗折价, 大宗溢价, 折溢价率, 机构专用接盘,
  大宗交易扫描, 大宗成交榜, 折价接盘, or an A-share block-trade radar report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-block-trade-radar
  repository_url: https://github.com/quantskills/skill-block-trade-radar
  project_type: skill
  collection: block-trade-radar
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - block-trade
  - discount-premium
  - institutional-flow
  - corporate-action
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
  summary_zh: A股大宗交易折溢价雷达：把每笔大宗成交价对齐同日收盘价算折溢价率、读机构专用买卖方向、标记重复折价接盘与同营业部对倒式打款、按成交额与折溢价排榜，支持全市场扫描、单票时间线与定时运行。
  summary_en: A-share block-trade radar that joins each block trade to the same-day close
    to compute discount/premium, reads institutional (机构专用) buy/sell direction, flags
    repeated discounted takeovers and same-branch wash-like prints, and ranks names by
    amount and premium/discount, for the whole market or a single name.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "补充扫描窗口、行业范围、折溢价阈值或重点席位；留空则按默认近期开窗扫描"
  },
  "fields": [
    {
      "key": "symbol",
      "label": "股票代码（可选）",
      "type": "text",
      "placeholder": "如：600519.SH；留空扫描全市场"
    },
    {
      "key": "date",
      "label": "截至日期",
      "type": "date",
      "help": "留空由前端使用今天，并自动按交易日处理"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请运行 A 股大宗交易雷达{{#symbol}}，聚焦 {{symbol}}{{/symbol}}{{#date}}，截至 {{date}}{{/date}}，计算相对同日收盘价的折溢价率，识别机构专用买卖方向、重复折价接盘与买卖营业部相同的疑似对倒，并按成交额和折溢价排名，输出中文报告。"
}
```

# Block Trade Radar

Use this skill to **scan and read A-share block-trade (大宗交易) activity**: for the whole market over a window or a single name, join every block trade to the **same-day close** to compute a **discount/premium rate (折溢价率)**, read whether the buyer or seller is **机构专用 (institutional seat)**, flag **repeated discounted takeovers** and **same-branch (buyer==seller) prints**, and rank names by block-trade amount and by premium/discount. Prefer Pandadata as the data source, keep every figure traceable to `get_block_trade` (plus the `get_stock_daily` close used for the discount math) and a trade date, and never invent prices, amounts, discounts, or directions.

## Scope And Positioning (read first to avoid overlap)

This skill is the **block-trade discount/premium** view. It is deliberately distinct from its siblings:

- Unlike `market-daily-review` (daily whole-market review that merely *lists* the day's block trades as one line item): this skill is a **block-trade-centric** analysis — same-day discount/premium math, institutional-direction read, repeat-discount and wash-print flags, and a cross-sectional premium/amount ranking. If the user wants a full end-of-day market review, hand off to `market-daily-review`.
- Unlike `smart-money-profiler` (龙虎榜 / 北向 / 两融 "smart money" across **营业部 seat** behaviour on the daily公开信息 board): block trades are a **separate off-exchange channel** with their own discount signal; this skill reads `get_block_trade` in depth rather than the 龙虎榜 board. Names surfaced here can be cross-checked there.
- Unlike `event-risk-alert` (per-name watchlist risk monitoring — unlocks, pledges, reductions): a block trade may *implement* a shareholder reduction but is not itself a filing-level risk event. If the user wants to watch their own holdings for reduction/unlock risk, hand off to `event-risk-alert`.
- Unlike `a-share-stock-dossier` (single-name deep due diligence): this skill is a block-trade scan, not a company dossier.

## Block Trade Model (read before analysis)

`get_block_trade` returns **one row per block-trade print** (成交笔), keyed by `symbol` + `date` + `sequence_id`. A single name on a single day may have several prints; a large reduction is often split into many.

- **Discount/premium (折溢价率)** — *not* a returned field; you compute it. `折溢价率 = price / 同日收盘价 - 1`, where the close comes from `get_stock_daily` for the same `symbol` and `date`. Negative = 折价 (below market, the common case — a buyer demands a discount to absorb a block); positive = 溢价 (above market, rarer, sometimes signals demand). Always state the close you used.
- **Direction / institutional flag** — `buyer` and `seller` are 营业部/席位 names. `机构专用` on the **buyer** side = an institution is *absorbing* the block (接盘); on the **seller** side = an institution is *distributing* (出货). Read direction from the seat text verbatim; do not infer identity beyond what the string says.
- **Same-branch print (对倒式)** — when `buyer == seller` (same 营业部), the print may be an internal transfer / 过券 rather than a genuine change of beneficial ownership. **Flag it**; do not count it as directional institutional flow.
- **Scale** — `amount` (成交额, 元) and `volume` (成交量, 股) size each print. `price` is the block price. Aggregate per name per day for a name-level view; keep print-level detail for the timeline.
- **Dates** — `date` is the trade date. A scan over a window is a snapshot of prints in that window.

## Workflow

1. Resolve the target: whole-market scan over a window, or a single name's block-trade timeline. Confirm the date window (default a recent trailing window, e.g. last ~30 trading days, for a market scan).
2. Read `references/block-trade-playbook.md` before the first run in a session. Use it for the routing table, the discount/premium formula and edge cases, direction/wash-print rules, aggregation rules, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_block_trade` and `get_stock_daily` sections in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Block trades: `get_block_trade` for the window (empty `symbol` for whole market; a specific `symbol` for one name's history).
   - Same-day close for the discount math: `get_stock_daily` for the traded `symbol`s over the window.
   - Identity & industry: `get_stock_detail` and `get_stock_industry` to name prints and roll them up by sector.
   - Calendar: `get_last_trade_date` / `get_trade_cal` to bound the window.
5. Compute per print: 折溢价率 against the same-day close; tag buyer/seller institutional direction; flag same-branch prints. Aggregate per name per day (总成交额, 笔数, 加权折溢价率), then rank: largest by amount, deepest 折价, notable 溢价, repeat-discount names, and net institutional 接盘/出货. Keep raw print counts long enough to cite source method, window, and missing-close status.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/block-trade/<scope>-<date>.md` (e.g. `reports/block-trade/market-20260706.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, a missing discount-basis (close) note, missing wash-print/institutional caveats, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 大宗成交总览 | `get_block_trade` | Prints in the window; distinct names & total amount. |
| 折溢价分布 | `get_block_trade` (`price`) + `get_stock_daily` (close) | How prints split across 折价 / 平价 / 溢价 and how deep. |
| 机构专用方向 | `get_block_trade` (`buyer`, `seller`) | Net institutional 接盘 (buy) vs 出货 (sell). |
| 成交额 / 折价榜 | `get_block_trade` (`amount`) + computed 折溢价率 | Largest by amount, deepest discount, repeat-discount names. |
| 对倒式提示 | `get_block_trade` (`buyer==seller`) | Same-branch prints to exclude from directional read. |
| 行业分布 | `get_stock_industry` + the above | Which industries see the most block-trade flow. |

## Analysis Modes

- **Whole-market scan**: all prints in the window → 折溢价 distribution, net institutional direction, largest-by-amount and deepest-discount leaders, repeat-discount names, and industry distribution. Separate genuine directional prints from same-branch (`buyer==seller`) prints.
- **Single-name timeline**: one ticker's block-trade history — each print's date, discount/premium vs that day's close, buyer/seller direction, and whether prints cluster (e.g. a reduction being worked off in pieces).
- **Discount read**: a persistent, deepening 折价 with `机构专用` on the seller side may indicate distribution pressure; a shrinking discount or 溢价 with institutional buyers may indicate absorption. State these as **relative observations**, not signals to act.
- **Wash-print screen**: surface `buyer==seller` prints separately and exclude them from the institutional net; they are internal transfers, not a change in beneficial ownership.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always state the discount basis.** 折溢价率 is derived; name the close (`get_stock_daily`, same `symbol`+`date`) it was computed against. Never present a 折溢价率 without its price basis.
- **Never over-read a single print.** One large 折价 block is a transaction, not a verdict; aggregate and look for repetition before calling anything a pattern.
- Read direction from `buyer`/`seller` text verbatim; `机构专用` is a seat label, not a named institution — do not invent who it is. Flag `buyer==seller` prints as possible 对倒/过券.
- Mark the scan window and as-of date. Prints accumulate; a scan is a snapshot — state the snapshot date and the trade-date range.
- Separate facts (raw price, amount, volume, seats), derived metrics (折溢价率, per-name aggregates, ranks, net institutional flow), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section. If the same-day close is missing for a print, mark 折溢价率 as 待补 rather than fabricating a basis.
- Keep the tone factual and structural. Use "折价接盘", "净接盘/净出货", "可能提示承接/派发意愿" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated block-trade radar, create a task that runs on trading days after market close (e.g. after `18:00 Asia/Shanghai`) to catch that day's block-trade prints. Make it idempotent: if `reports/block-trade/<scope>-<date>.md` exists, regenerate and overwrite. Skip non-trading days.

## Resource Guide

- `references/block-trade-playbook.md`: routing table, discount/premium formula and edge cases, direction/wash-print rules, aggregation rules, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, the discount-basis (close) note, institutional/wash-print caveats, window/date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_block_trade`, a trade date, the scan window, and (for 折溢价率) the `get_stock_daily` close used.
- 折溢价率 is always presented with its price basis; a missing close is marked 待补, never fabricated.
- Institutional direction is read from `buyer`/`seller` text; `机构专用` is never named as a specific institution.
- `buyer==seller` prints are flagged and excluded from the directional net.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
