---
name: institutional-research-tracker
description: Scan and track A-share institutional-research (investor-relations) activity
  with the Pandadata get_investor_activity interface, ranking which listed companies
  are being visited most, measuring how many distinct institutions participate,
  classifying participant institution types from the source text, rolling activity
  up by industry, and building a single-name research timeline, for the whole market
  over a window or one company. Use when the user asks for 机构调研监控, 机构调研热度, 调研统计,
  被调研排行, 调研次数, 机构关注度, 投资者关系活动, 谁在调研, 调研密集股, or an A-share institutional-research
  activity report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-institutional-research-tracker
  repository_url: https://github.com/quantskills/skill-institutional-research-tracker
  project_type: skill
  collection: institutional-research-tracker
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - institutional-research
  - investor-relations
  - attention
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
  summary_zh: A股机构调研热度监控：基于 get_investor_activity 统计被调研次数、参与机构广度、机构类型分布(从文本判定)、行业调研分布，并支持单票调研时间线，全市场扫描或单票，支持定时运行。
  summary_en: A-share institutional-research (investor-relations) activity monitor that
    ranks the most-visited companies, measures distinct-institution breadth, classifies
    participant institution types from source text, rolls up by industry, and builds
    a single-name research timeline, for the whole market or one company.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Institutional Research Tracker

Use this skill to **scan and track A-share institutional-research (investor-relations) activity** via `get_investor_activity`: for the whole market over a time window or for one company, rank which listed companies are being visited most, measure how many distinct institutions show up, classify participant institution types from the source text, roll activity up by industry, and build a single-name research timeline. Prefer Pandadata as the data source, keep every figure traceable to `get_investor_activity` and an activity date, and never invent visits, institutions, participants, or attendance counts.

## Scope And Positioning (read first to avoid overlap)

This skill is the **institutional-attention / research-heat** view. It is deliberately distinct from its siblings:

- Unlike `smart-money-profiler` (龙虎榜 seat identity, northbound behavior, capital consensus — actors that actually **traded**): institutional research is **attention/interest** (who visited a company), not executed capital flow. Being researched ≠ being bought. If the user wants who traded, hand off to `smart-money-profiler`.
- Unlike `earnings-season-tracker` (earnings-disclosure cross-section) and `market-daily-review` (daily whole-market review): those aggregate other event families. Research-heavy names surfaced here can be cross-checked against earnings and price action, but the research-attention signal itself lives here.
- Unlike `a-share-stock-dossier` (single-name deep due diligence): this skill reads `get_investor_activity` in depth across the whole market — heat ranking, institution breadth, type mix, industry distribution. For a full company dossier, hand off to `a-share-stock-dossier`.

## Research Activity Model (read before analysis)

`get_investor_activity` returns **one row per research event/announcement**. Fields are often sparse (the sample shows `participant` and `institute` as `None` for a generic "境内投资者" record), so handle missing fields explicitly and never fabricate names.

- **`symbol`, `date`** — the code and the announcement/activity date; the keys for counting and the timeline.
- **`institute`** — the participating institution(s). May be a single name, a delimited list, or None. **Distinct-institution breadth** per company is a core metric; parse the list conservatively and count None as 未披露.
- **`participant`** — named attendees; often None.
- **`investor_or_analyst_detail`** — free-text attendee/type detail (e.g. 境内投资者, 基金公司, 证券公司). Use it, together with `institute`, to classify **institution type** from **verbatim signals** only.
- **Counting** — the primary heat metric is the **number of research events** per company in the window; distinct-institution count is the breadth metric. State both; do not conflate "many visits by one house" with "broad interest".

## Institution Type Classification (from source text only)

Classify each participant/institution from the **verbatim** `institute` / `investor_or_analyst_detail` text:

| Class | Signal (verbatim) |
|---|---|
| 公募基金 | 基金管理 / 基金公司 / 资产管理（公募） |
| 券商 / 卖方 | 证券 / 证券公司 / 研究所 |
| 保险 | 保险 / 资产管理（险资）/ 养老 |
| 私募 | 私募 / 投资管理 / 资本 / 投资合伙 |
| 外资 / QFII | 外资 / QFII / 境外 / Capital / Asset Management (英文) |
| 其他 / 未披露 | none of the above clearly matches, or field is None |

Never assign a type without a matching source signal; ambiguous or None → 未披露.

## Workflow

1. Resolve the target: whole-market scan over a window, or one company's research timeline. Confirm the date window (default a recent trailing window, e.g. last ~30 days, for a market scan).
2. Read `references/research-playbook.md` before the first run in a session. Use it for the routing table, counting/breadth/type definitions, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_investor_activity` section in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Research activity: `get_investor_activity` for the window (empty `symbol` = whole market; a specific `symbol` = one name's history).
   - Identity & industry: `get_stock_detail` and `get_stock_industry` to name companies and roll them up by sector.
   - Price context (optional): `get_stock_daily` to place the research date against the price path — a descriptive cross-check only, never a causal claim.
   - Calendar: `get_last_trade_date` / `get_trade_cal` to bound the window.
5. Compute: research-event counts per company (heat ranking), distinct-institution breadth, institution-type mix, industry distribution, and (for one name) the activity timeline. Keep raw row counts long enough to cite source method, window, and missing-field status.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/research/<scope>-<date>.md` (e.g. `reports/research/market-20260705.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing field-sparsity caveats, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 调研活动总览 | `get_investor_activity` | Research events in the window; distinct companies visited. |
| 调研热度榜 | `get_investor_activity` (count by `symbol`) | Which companies were researched most (event count). |
| 机构参与广度 | `get_investor_activity` (distinct `institute`) | Which companies drew the most **distinct** institutions. |
| 机构类型分布 | `get_investor_activity` (`institute`, `investor_or_analyst_detail`) | 公募/券商/保险/私募/外资 mix from source text. |
| 行业调研分布 | `get_stock_industry` + the above | Which industries are being researched most. |
| 单票调研时间线 | `get_investor_activity` (one `symbol`) | One company's research cadence and participants. |

## Analysis Modes

- **Whole-market scan**: rank companies by research-event count over the window, report distinct-institution breadth, the institution-type mix, and the industry distribution. Distinguish **frequency** (many visits) from **breadth** (many distinct institutions).
- **Single-name timeline**: one ticker's research history — dates, participating institutions, and any type pattern. Note field sparsity where `institute`/`participant` are None.
- **Attention read**: high research frequency and broad institution breadth indicate elevated institutional **attention** — an interest signal, not a flow or performance signal. State it descriptively.
- **Price cross-check (optional)**: place research dates against the `get_stock_daily` path as a descriptive overlay only; never assert that research caused a move.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Separate frequency from breadth.** "被调研 12 次" (event count) and "12 家机构参与" (distinct institutions) are different metrics; report both and never merge them.
- Mark the scan window and as-of date. Research activity accumulates; a scan is a snapshot — state the snapshot date and the `date` range covered.
- Classify institution type from source signals verbatim; label ambiguous or None cases 未披露 rather than guessing. Do not invent attendee or institution names.
- Handle field sparsity explicitly. When `institute`/`participant` are None, say so; do not silently drop the record or fabricate a name.
- Separate facts (raw events, dates, institution text), derived metrics (event counts, distinct-institution counts, type mix, industry aggregates), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section.
- Keep the tone factual and structural. Use "机构调研关注度较高", "参与机构较广", "调研密集" rather than directional calls; being researched is attention, not endorsement — never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated research-heat watch, create a task that runs on trading days after market close (e.g. after `18:00 Asia/Shanghai`) to catch that day's investor-relations announcements. Make it idempotent: if `reports/research/<scope>-<date>.md` exists, regenerate and overwrite. Skip non-trading days.

## Resource Guide

- `references/research-playbook.md`: routing table, counting/breadth/type definitions, report skeleton, empty-data and field-sparsity handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, frequency-vs-breadth separation, field-sparsity caveats, window/date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_investor_activity` and an activity date within the stated window.
- Research **frequency** (event count) and **breadth** (distinct institutions) are reported as separate metrics.
- Institution type is classified from verbatim source text; ambiguous / None → 未披露; no fabricated names.
- Field sparsity (None `institute`/`participant`) is surfaced, not hidden.
- Being researched is framed as **attention**, never as a buy signal or endorsement.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
