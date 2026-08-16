---
name: earnings-season-tracker
description: Scan the whole A-share market across earnings-season time windows with
  Pandadata interfaces, aggregating performance forecasts, flash and quarterly
  reports, audit opinions, and industry-level earnings prosperity into a sourced
  cross-sectional report, with optional scheduled runs during earnings season. Use
  when the user asks for 财报季扫描, 业绩预告统计, 预增预减分布, 超预期暴雷个股榜, 审计非标清单, 行业业绩景气分布,
  全市场财报横截面, or to set up a scheduled earnings-season scan.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-earnings-season-tracker
  repository_url: https://github.com/quantskills/skill-earnings-season-tracker
  project_type: skill
  collection: earnings-season-tracker
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - earnings-season
  - fina-forecast
  - cross-section
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
  summary_zh: 按财报季时间窗对全市场做业绩横截面扫描：预告类型分布、超预期/暴雷榜、行业业绩景气、年报季审计非标清单 —— 每个数据点可溯源，支持财报季定时运行。
  summary_en: Whole-market A-share earnings-season scanner covering forecast-type
    distribution, beat/miss leaders, industry earnings prosperity, and audit-opinion
    watchlists.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "补充财报季扫描范围、报告期、行业关注点或定时运行要求"
  },
  "fields": [
    {
      "key": "date",
      "label": "扫描基准日期",
      "type": "date",
      "help": "留空时按最新可用交易日判断当前财报季窗口"
    },
    {
      "key": "mode",
      "label": "扫描模式",
      "type": "select",
      "default": "full",
      "options": [
        { "value": "full", "label": "全市场综合扫描" },
        { "value": "forecast", "label": "业绩预告分布" },
        { "value": "beat_miss", "label": "超预期与暴雷" },
        { "value": "industry", "label": "行业业绩景气" },
        { "value": "audit", "label": "审计非标清单" }
      ]
    },
    {
      "key": "period",
      "label": "报告期",
      "type": "text",
      "placeholder": "如：2025年报、2026Q1；留空则按基准日期推断"
    },
    {
      "key": "focus",
      "label": "重点关注",
      "type": "text",
      "placeholder": "如：半导体行业、预增占比、非标审计意见"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请执行 A 股财报季 {{mode}}。{{#date}}扫描基准日期为 {{date}}。{{/date}}{{#period}}目标报告期为 {{period}}。{{/period}}{{#focus}}重点关注：{{focus}}。{{/focus}}按披露窗口扫描全市场，统计预告类型、披露进度、超预期与暴雷、行业景气及适用时的审计非标，逐项标注 Pandadata 方法、报告期、快照日期与缺失数据，并输出中文报告。"
}
```

# Earnings Season Tracker

Use this skill to scan the **entire A-share market across an earnings-season time window** and produce a sourced cross-sectional report: who issued performance forecasts, how forecast types are distributed, which names beat or blew up, how earnings prosperity spreads across industries, and which companies received non-standard audit opinions during annual-report season. Prefer Pandadata as the data source, keep every statistic traceable to an interface and report period, and never invent missing figures.

## Scope And Positioning (read first to avoid overlap)

This skill is the **whole-market cross-section, time-window** view of earnings disclosure events. It is deliberately distinct from its sibling skills:

- Unlike `a-share-stock-dossier` (single-name deep due diligence): this skill scans the **whole market**, not one ticker. If the user wants to drill into a specific name surfaced by a scan, hand off to `a-share-stock-dossier`.
- Unlike `stock-screener` (one-shot natural-language conditional filtering): this skill aggregates statistics **around the time window of earnings-disclosure events**, not arbitrary user conditions. If the user wants to filter by custom conditions, hand off to `stock-screener`.
- Unlike `event-risk-alert` (scheduled per-name monitoring of a user watchlist/holdings): this skill is a **full-market scan**, not portfolio monitoring. If the user wants to watch their own holdings, hand off to `event-risk-alert`.

Industry-level output here is designed to **cross-check** the macro/industry prosperity view from `macro-monitor`: a sector showing clustered earnings beats here can be corroborated against its top-down prosperity reading there, and vice versa.

## Earnings-Season Calendar

A-share disclosure has a fixed rhythm. Pick the window from the target date unless the user specifies one.

| Window | Months | Primary focus | Lead methods |
|---|---|---|---|
| 年报业绩预告潮 | January (esp. by Jan 31) | Mandatory/voluntary annual forecasts | `get_fina_forecast` |
| 年报 + 一季报季 | April (esp. by Apr 30) | Annual reports, Q1 reports, audit opinions | `get_fina_reports`, `get_audit_opinion`, `get_fina_forecast` |
| 中报季 | July–August (esp. by Aug 31) | Interim forecasts and interim reports | `get_fina_forecast`, `get_fina_reports` |
| 三季报季 | October (esp. by Oct 31) | Q3 forecasts and Q3 reports | `get_fina_forecast`, `get_fina_reports` |

If the run date falls outside an active window, say so and offer either the most recent completed disclosure period or a lookback scan, instead of forcing a thin report.

## Workflow

1. Resolve the target window. If the user gives a report period (e.g. `2025年报`, `2026Q1`) or month, use it; otherwise infer the active window from the run date via `get_last_trade_date` and `get_trade_cal`. State the report period (`end_date`) and disclosure window explicitly in the report.
2. Read `references/earnings-season-guide.md` before the first scan in a session. Use it for the routing table, forecast-type definitions, beat/miss rules, industry-aggregation method, report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the exact method section in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence in this order:
   - Calendar and universe: `get_last_trade_date`, `get_trade_cal`, `get_trade_list`.
   - Forecast scan: `get_fina_forecast` across the market for the target report period.
   - Landed disclosures: `get_fina_performance` (flash) and `get_fina_reports` (quarterly three statements) to track actual progress and beat/miss versus forecast.
   - Audit opinions (annual season only): `get_audit_opinion` to compile non-standard opinions.
   - Industry mapping: `get_industry_constituents` / `get_stock_industry` / `get_industry_detail` to roll names up into sectors.
5. Compute cross-sectional statistics from raw rows: forecast-type counts and shares, change-magnitude leaders, disclosure progress (disclosed vs. universe), beat/miss tallies, and per-industry earnings prosperity. Keep raw row counts long enough to cite source method, report period, and missing-data status.
6. Generate the Markdown report following the skeleton in the guide. Save to `reports/earnings/<period>.md` (e.g. `reports/earnings/2025A.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, missing report-period labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 披露进度概览 | `get_trade_list`, `get_fina_forecast`, `get_fina_performance`, `get_fina_reports` | How many names have disclosed (forecast/flash/report) vs. the universe? |
| 业绩预告类型分布 | `get_fina_forecast` | Distribution of 预增/预减/扭亏/首亏/续亏/略增/略减/续盈/不确定; magnitude ranking. |
| 超预期 / 暴雷个股榜 | `get_fina_forecast`, `get_fina_performance`, `get_fina_reports` | Largest upside surprises and largest blow-ups by forecast type and change magnitude. |
| 行业业绩景气分布 | `get_industry_constituents`, `get_stock_industry`, `get_industry_detail` + the above | Which industries are collectively beating or blowing up. Cross-checks `macro-monitor`. |
| 审计非标清单（年报季） | `get_audit_opinion` | Names with qualified / adverse / disclaimer / emphasis-of-matter opinions. |

## Analysis Modes

- **Forecast-type distribution**: bucket every `get_fina_forecast` row by its forecast-type field, then report counts and shares. Use the change-magnitude field (forecast net-profit change percent, or the documented low/high bounds) to rank the biggest movers. Define the buckets per `references/earnings-season-guide.md`; do not re-label types the source did not assign.
- **Beat / miss**: a "beat" or "miss" is a derived judgment. State the comparison basis explicitly — forecast vs. prior-period actual, flash vs. forecast, or report vs. forecast — and the fields used. Never assert a beat/miss without naming the baseline.
- **Industry aggregation**: map each name to its industry via `get_stock_industry` (or by intersecting `get_industry_constituents`), then aggregate forecast types and change magnitudes per industry to rank sector earnings prosperity. State the industry taxonomy (e.g. the field returned by `get_industry_detail`) used.
- **Audit watchlist**: in annual-report season, list every name whose `get_audit_opinion` is not a standard unqualified opinion, with the opinion type verbatim. Treat non-standard opinions as a high-risk signal, not a verdict.

## Report Rules

- Write in Chinese unless the user requests another language.
- Label the report period (`end_date`) on every financial figure and distinguish single-quarter from cumulative (累计) caliber; never mix them silently.
- Mark the disclosure window and as-of date. Forecast, flash, and final-report data accumulate through the season, so a scan is a snapshot — state the snapshot date.
- Separate facts, derived metrics, and judgment. Label derived calculations such as type shares, disclosure progress, change-magnitude ranks, beat/miss tallies, and industry aggregates.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section.
- Keep the tone factual and structural. Use "可能提示", "需要关注", and "与...共同出现" rather than directional calls; never give trading instructions or personalized investment advice.
- When a call fails or a full-market aggregation is too slow, keep the report useful by generating available sections and adding a concise missing-data note under "数据说明".

## Automation (earnings-season scheduling)

When the user asks for an automated earnings-season scan, create a task that runs **only during active earnings-season windows** (Jan / Apr / Jul–Aug / Oct), preferably each trading day after `18:30 Asia/Shanghai` so late disclosures settle. Make the task idempotent: if `reports/earnings/<period>.md` already exists, regenerate and overwrite it so the running snapshot stays current. Skip non-trading days and dormant months instead of producing an empty report.

## Resource Guide

- `references/earnings-season-guide.md`: routing table, forecast-type definitions, beat/miss rules, industry-aggregation method, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, report-period labels, and the disclaimer.

## Quality Bar

- Every material claim must trace to a Pandadata method, report period (`end_date`), and scan window.
- Comparisons must use the same report period and caliber where possible; single-quarter and cumulative are never mixed unless clearly labeled.
- Forecast types are reported as the source assigns them; beat/miss is always stated with its baseline.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
