---
name: buyback-monitor
description: Scan and track A-share share-buyback (repurchase) events with the Pandadata
  get_repurchase interface, following each event through its procedure stages, classifying
  buyback purpose (cancellation vs incentive vs value-management), measuring buyback
  intensity against total share capital, and comparing the price band to the market
  price, for the whole market over a window or a single name. Use when the user asks
  for 回购监控, 股票回购, 回购扫描, 回购进度, 注销式回购, 回购强度, 回购目的分类, 回购预案, 回购价格区间, or an A-share
  buyback watch report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-buyback-monitor
  repository_url: https://github.com/quantskills/skill-buyback-monitor
  project_type: skill
  collection: buyback-monitor
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - buyback
  - repurchase
  - capital-return
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
  summary_zh: A股股票回购监控：按事件进程(预案→决案→实施→完成/注销)追踪回购、区分回购目的(注销/激励/市值管理)、以占总股本比例衡量回购强度、价格区间对比现价，支持全市场扫描与定时运行。
  summary_en: A-share share-buyback monitor tracking repurchase events through their
    procedure stages, classifying purpose, measuring intensity vs total share capital,
    and comparing price band to market price, for the whole market or a single name.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Buyback Monitor

Use this skill to **scan and track A-share share-buyback (repurchase) events**: for the whole market over a time window or for a single name, follow each buyback through its procedure stages, tell apart a share-cancellation buyback from an incentive/ESOP buyback, measure how large the buyback is relative to total share capital, and check where the announced price band sits versus the current market price. Prefer Pandadata as the data source, keep every figure traceable to `get_repurchase` and an announcement/stage date, and never invent amounts, ratios, stages, or purposes.

## Scope And Positioning (read first to avoid overlap)

This skill is the **share-buyback event** view. It is deliberately distinct from its siblings:

- Unlike `a-share-stock-dossier` (single-name deep due diligence that includes dividends and capital actions as one sub-section): this skill is a **buyback-event-centric scan** across the **whole market** (or a name's full buyback timeline), reading `get_repurchase` in depth — stage funnel, purpose mix, intensity ranking. If the user wants a full company dossier, hand off to `a-share-stock-dossier`.
- Unlike `event-risk-alert` (per-name watchlist monitoring of **risk** events — unlocks, pledges, reductions): a buyback is generally a **capital-return / positive** signal, and this skill is a **market scan**, not portfolio risk monitoring. If the user wants to watch their own holdings for risk, hand off to `event-risk-alert`.
- Unlike `earnings-season-tracker` (earnings-disclosure cross-section) and `market-daily-review` (daily whole-market review): those aggregate different event families. Buyback names surfaced here can be cross-checked against those, but the buyback signal itself lives here.

## Buyback Event Model (read before analysis)

`get_repurchase` returns **one row per stage per event**, so a single buyback appears multiple times as it advances. Deduplicate to the event, then track its stage.

- **Procedure (`procedure`)** — the event stage: 预案 (proposal) → 决案/股东大会通过 → 实施 (executing) → 完成/届满/注销 (done/expired/cancelled). Report the **latest** stage per event and, for tracking, the stage history. A 预案 is an intention, not an executed buyback — never treat them as equivalent.
- **Purpose (`purpose`, `buy_back_mode`, `write_off_date`)** — classify each buyback:
  - **注销式回购 (share cancellation)**: `write_off_date` present or purpose text indicates 注销/减少注册资本. Most shareholder-friendly — permanently reduces share count.
  - **股权激励 / 员工持股回购 (incentive/ESOP)**: purpose text indicates 股权激励/员工持股计划. Shares may later be re-issued; classify separately.
  - **市值管理 / 维护公司价值回购**: purpose text indicates 维护公司价值/股东权益.
  - Classify from the source `purpose` / `write_off_date` **verbatim signals**; if ambiguous, label `未分类` rather than guessing.
- **Intensity** — `buy_back_percent` (占总股本比例) is the primary intensity metric; `buy_back_value` (回购总金额, 元) and the planned range `value_floor` / `value_ceiling` give the absolute scale; `buy_back_volume` / `volume_floor` / `volume_ceiling` give the share count.
- **Price band** — `buy_back_price`, `price_floor`, `price_ceiling` define the announced price band. Compare to the current market price (`get_stock_daily`) to see whether the band is above or below market.
- **Dates** — `announcement_dt` (公告时间), `date`, `buy_back_start_date` / `buy_back_end_date` (回购期限), `write_off_date` (注销公告日).

## Workflow

1. Resolve the target: whole-market scan over a window, or a single name's buyback timeline. Confirm the date window (default a recent trailing window, e.g. last ~90 days, for a market scan).
2. Read `references/buyback-playbook.md` before the first run in a session. Use it for the routing table, stage/purpose/intensity definitions, dedup rules, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_repurchase` section in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Buyback events: `get_repurchase` for the window (empty `symbol` for whole market; a specific `symbol` for one name's history).
   - Identity & industry: `get_stock_detail` and `get_stock_industry` to name events and roll them up by sector.
   - Price context: `get_stock_daily` to place the announced price band and event date against the market price.
   - Calendar: `get_last_trade_date` / `get_trade_cal` to bound the window.
5. Dedup to events and compute: stage funnel (counts per `procedure`), purpose mix, intensity ranking (`buy_back_percent`, `buy_back_value`), price-band-vs-market, and per-industry aggregation. Keep raw row counts long enough to cite source method, window, and missing-data status.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/buyback/<scope>-<date>.md` (e.g. `reports/buyback/market-20260703.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing stage/purpose caveats, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 回购事件总览 | `get_repurchase` | New events in the window; distinct events after dedup. |
| 进程漏斗 | `get_repurchase` (`procedure`) | How many events at 预案 / 决案 / 实施 / 完成 / 注销. |
| 回购目的分类 | `get_repurchase` (`purpose`, `write_off_date`, `buy_back_mode`) | Cancellation vs incentive vs value-management mix. |
| 回购强度榜 | `get_repurchase` (`buy_back_percent`, `buy_back_value`) | Largest by share of total capital and by absolute amount. |
| 价格区间对比 | `get_repurchase` (price band) + `get_stock_daily` | Where the announced band sits vs current market price. |
| 行业分布 | `get_stock_industry` + the above | Which industries are buying back most. |

## Analysis Modes

- **Whole-market scan**: dedup all events in the window, then report the stage funnel, purpose mix, intensity leaders, and industry distribution. Distinguish **new proposals** from **executing/completed** — a wave of 预案 is intention, not executed capital return.
- **Single-name timeline**: one ticker's buyback history — stage progression with dates, planned range vs any executed figures, price band vs the price path, and whether it ends in cancellation (`write_off_date`).
- **Purpose quality read**: separate 注销式 (permanent share reduction, most accretive) from 激励式 (may re-issue). Report the mix; do not treat all buybacks as equally shareholder-friendly.
- **Price-band read**: compare `price_ceiling` / `buy_back_price` to the current close. A band set below market can signal the buyer's valuation view; state it as a relative observation, not a signal to act.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always label the stage.** Never report a buyback as "回购 X 亿元" without saying whether it is 预案 (planned) or actually executed. Planned amounts (`value_floor` / `value_ceiling`) are ranges, not spent capital.
- Mark the scan window and as-of date. Buyback events accumulate and progress; a scan is a snapshot — state the snapshot date and `announcement_dt` range.
- Classify purpose from source signals verbatim; label ambiguous cases `未分类` rather than guessing. Do not assert 注销 without `write_off_date` or an explicit cancellation purpose.
- Separate facts (raw amounts, ratios, stages), derived metrics (dedup counts, funnel, intensity ranks, industry aggregates), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section.
- Keep the tone factual and structural. Use "可能提示股东回报意愿", "注销式占比", "需要关注实施进度" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated buyback watch, create a task that runs on trading days after market close (e.g. after `18:00 Asia/Shanghai`) to catch that day's buyback announcements. Make it idempotent: if `reports/buyback/<scope>-<date>.md` exists, regenerate and overwrite. Skip non-trading days.

## Resource Guide

- `references/buyback-playbook.md`: routing table, stage/purpose/intensity definitions, dedup rules, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, stage/purpose caveats, window/date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_repurchase`, an announcement/stage date, and the scan window.
- Every buyback amount is labeled 预案 (planned range) vs executed; the two are never conflated.
- Purpose is classified from source signals; `注销` is asserted only with `write_off_date` or explicit cancellation purpose.
- Events are deduplicated across procedure stages before counting.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
