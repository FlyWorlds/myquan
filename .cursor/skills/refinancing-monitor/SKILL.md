---
name: refinancing-monitor
description: Scan and track A-share equity-refinancing events — private placements
  (定向增发) and rights issues (配股) — with the Pandadata get_stock_private_placement
  and get_stock_allotment interfaces, following each event through its approval
  stages, measuring dilution against total share capital, comparing the issue/allotment
  price to the market price (discount and break-issue), and rolling events up by
  industry, for the whole market over a window or a single name. Use when the user
  asks for 再融资监控, 定增监控, 定向增发扫描, 定增破发, 定增折价, 配股监控, 配股比例, 稀释比例, 再融资进度, 增发预案,
  or an A-share equity-refinancing / dilution watch report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-refinancing-monitor
  repository_url: https://github.com/quantskills/skill-refinancing-monitor
  project_type: skill
  collection: refinancing-monitor
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - refinancing
  - private-placement
  - rights-issue
  - dilution
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
  summary_zh: A股再融资监控：以定向增发(get_stock_private_placement)与配股(get_stock_allotment)为中心，按进程(预案→过会→核准→实施完成)追踪事件、以占总股本比例衡量稀释强度、发行/配股价对比现价(折价与破发)、按行业聚合，支持全市场扫描与定时运行。
  summary_en: A-share equity-refinancing monitor tracking private placements and rights
    issues through their approval stages, measuring dilution vs total share capital,
    comparing issue/allotment price to market price (discount and break-issue), and
    rolling up by industry, for the whole market or a single name.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Refinancing Monitor

Use this skill to **scan and track A-share equity-refinancing events** — **定向增发 (private placement)** via `get_stock_private_placement` and **配股 (rights issue)** via `get_stock_allotment`: for the whole market over a time window or for a single name, follow each event through its approval stages, measure how much new equity dilutes total share capital, check whether the issue/allotment price sits at a discount to (or below) the market price, and roll events up by industry. Prefer Pandadata as the data source, keep every figure traceable to a source method and an announcement/stage date, and never invent amounts, ratios, stages, prices, or issue status.

## Scope And Positioning (read first to avoid overlap)

This skill is the **equity-refinancing (capital-raising / dilution) event** view — the mirror image of buyback-monitor's capital-return view. It is deliberately distinct from its siblings:

- Unlike `buyback-monitor` (share **buyback** = capital return, permanently or temporarily reducing float): refinancing **raises** capital and **dilutes** existing holders. Same event-scan shape, opposite direction. If the user wants buybacks, hand off to `buyback-monitor`.
- Unlike `event-risk-alert` (per-name watchlist monitoring of unlocks, pledges, reductions): this skill is a **market-wide refinancing-event scan**, not portfolio risk monitoring. Note that a completed placement creates a future 限售解禁 (`get_restricted_list`) — surface the linkage, but hand off holdings-risk watching to `event-risk-alert`.
- Unlike `a-share-stock-dossier` (single-name deep due diligence that mentions capital actions as one sub-section): this skill reads the two refinancing interfaces in depth across the whole market — stage funnel, dilution ranking, discount/break-issue. If the user wants a full company dossier, hand off to `a-share-stock-dossier`.
- Unlike a placement-discount alpha or backtest workflow: this skill monitors **event lifecycle, pricing, dilution, and break-issue status**. It does not define a predictive factor, portfolio construction rule, or performance claim.

## Refinancing Event Model (read before analysis)

Both interfaces return **one row per event stage**, so a single deal appears multiple times as it advances. Deduplicate to the deal, then track its stage.

- **定向增发 `get_stock_private_placement`**:
  - `issue_type` (发行类型, e.g. 非公开发行/竞价/定价) — classify the placement type verbatim.
  - `issue_status` (发行进度/状态) — the stage: 预案 → 股东大会通过 → 发审委/交易所通过 → 证监会核准 (`approval_date`) → 实施完成 (`listed_date`). Report the **latest** status; a 预案 is an intention, not raised capital.
  - `issued_shares` (发行股数), `issue_price` (发行价), `approval_date` (核准日), `listed_date` (上市日).
- **配股 `get_stock_allotment`**:
  - `planned_ratio` (计划配股比例) vs `actual_ratio` (实际配股比例) — the gap shows shareholder take-up (认购不足 when actual < planned).
  - `actual_shares` (实际配售股数), `allotment_price` (配股价), `record_date` (股权登记日), `ex_date` (除权日).
- **Dilution** — the primary intensity metric is new shares ÷ pre-event total shares: `issued_shares` (or `actual_shares`) against total share capital from `get_share_float`. State it as 稀释比例 (%) and mark whether the deal is executed or still 预案.
- **Discount / break-issue** — compare `issue_price` / `allotment_price` to the market close (`get_stock_daily`): a placement priced below market is at a discount to holders; a name trading **below** its executed issue price is 破发. Report as a relative observation.
- **Dates** — `announcement_date` (信息发布日), `approval_date`, `listed_date`, `record_date`, `ex_date`.

## Workflow

1. Resolve the target: whole-market scan over a window, or a single name's refinancing timeline. Confirm the date window (default a recent trailing window, e.g. last ~180 days, for a market scan — refinancing deals move slowly).
2. Read `references/refinancing-playbook.md` before the first run in a session. Use it for the routing table, stage/type/dilution definitions, dedup rules, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_stock_private_placement` / `get_stock_allotment` sections in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Placements: `get_stock_private_placement` for the window (empty `symbol` = whole market; a specific `symbol` = one name's history).
   - Rights issues: `get_stock_allotment` for the window.
   - Share base: `get_share_float` for total shares, to compute dilution ratio.
   - Identity & industry: `get_stock_detail` and `get_stock_industry` to name events and roll them up by sector.
   - Price context: `get_stock_daily` to place the issue/allotment price against the market price (discount / break-issue).
   - Unlock linkage (optional): `get_restricted_list` to note when a completed placement's shares become tradable.
   - Calendar: `get_last_trade_date` / `get_trade_cal` to bound the window.
5. Dedup to deals and compute: stage funnel (counts per status), placement-vs-rights mix, dilution ranking, discount/break-issue table, take-up gap for rights issues, and per-industry aggregation. Keep raw row counts long enough to cite source method, window, and missing-data status.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/refinancing/<scope>-<date>.md` (e.g. `reports/refinancing/market-20260705.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing stage caveats, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 再融资事件总览 | `get_stock_private_placement`, `get_stock_allotment` | New deals in the window; distinct deals after dedup; 定增 vs 配股 mix. |
| 进程漏斗 | `get_stock_private_placement` (`issue_status`) | How many deals at 预案 / 过会 / 核准 / 实施完成. |
| 折价与破发 | issue/allotment price + `get_stock_daily` | Where the issue/allotment price sits vs market; which executed deals are 破发. |
| 稀释强度榜 | `issued_shares`/`actual_shares` + `get_share_float` | Largest deals by share of total capital. |
| 认购缺口 | `get_stock_allotment` (`planned_ratio` vs `actual_ratio`) | Which rights issues were under-subscribed. |
| 行业分布 | `get_stock_industry` + the above | Which industries are raising equity most. |
| 解禁衔接（可选） | `get_restricted_list` | When completed placements' shares become tradable. |

## Analysis Modes

- **Whole-market scan**: dedup all deals in the window, then report the stage funnel, placement/rights mix, dilution leaders, discount/break-issue, and industry distribution. Distinguish **new proposals** from **executed** placements — a wave of 预案 is intention, not raised capital.
- **Single-name timeline**: one ticker's refinancing history — stage progression with dates, issue price vs the price path (including any 破发), dilution vs prior share base, and (for rights) planned vs actual take-up.
- **Dilution read**: rank by 稀释比例 (new shares ÷ pre-event total). State whether executed or 预案; large dilution at a deep discount is the most burdensome to holders.
- **Break-issue read**: for executed placements, compare the current close to `issue_price`. A name below its issue price (破发) is a relative observation about how the deal has fared, not a signal to act.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always label the stage.** Never report a placement as "定增募资 X 亿" without saying whether it is 预案 (planned) or 实施完成 (executed). A proposal can be revised or withdrawn.
- Mark the scan window and as-of date. Refinancing deals accumulate and progress slowly; a scan is a snapshot — state the snapshot date and `announcement_date` range.
- **Distinguish 定增 from 配股.** They dilute differently (placement to specific investors vs pro-rata to all holders); never merge them into one undifferentiated "再融资" number without the split.
- Separate facts (raw shares, prices, ratios, status), derived metrics (dilution %, discount %, dedup counts, funnel, take-up gap, industry aggregates), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section.
- Keep the tone factual and structural. Use "稀释比例较高", "发行价较现价折价 X%", "已破发", "认购不足" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated refinancing watch, create a task that runs on trading days after market close (e.g. after `18:00 Asia/Shanghai`) to catch that day's refinancing announcements. Make it idempotent: if `reports/refinancing/<scope>-<date>.md` exists, regenerate and overwrite. Skip non-trading days. Because deals move slowly, a weekly cadence is also reasonable — note the chosen cadence in the report.

## Resource Guide

- `references/refinancing-playbook.md`: routing table, stage/type/dilution definitions, dedup rules, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, stage caveats, 定增/配股 split, window/date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_stock_private_placement` / `get_stock_allotment`, an announcement/stage date, and the scan window.
- Every raised-capital figure is labeled 预案 (planned) vs 实施完成 (executed); the two are never conflated.
- 定增 and 配股 are reported separately; dilution is computed against a stated share base (`get_share_float`).
- Deals are deduplicated across stages before counting.
- Discount / break-issue uses `get_stock_daily` and is stated as a relative observation.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
