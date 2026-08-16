---
name: macro-altdata-nowcast
description: Track and nowcast industry prosperity from Pandadata's 宏观特色数据 (alternative-data)
  high-frequency series — online e-commerce (get_macro_ec), pharma (get_macro_md), energy-chemical
  (get_macro_eh), autos (get_macro_ad), home appliances (get_macro_ha), offline retail (get_macro_of),
  hiring (get_macro_rb), real estate (get_macro_re), electronics (get_macro_ed) and new-energy
  (get_macro_ep) — by first resolving opaque indicator codes via get_macro_detail, then computing
  YoY/MoM changes, trend, and lead/lag against official stats, for a single sector nowcast or a
  cross-sector prosperity dashboard. Use when the user asks for 另类数据, 高频行业景气, 电商/招聘/地产/汽车/家电高频数据,
  行业 nowcast, 特色数据监控, 景气度前瞻, or an alternative-data industry nowcasting report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-macro-altdata-nowcast
  repository_url: https://github.com/quantskills/skill-macro-altdata-nowcast
  project_type: skill
  collection: macro-altdata-nowcast
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - macro
  - alternative-data
  - high-frequency
  - industry-nowcast
  - prosperity
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
  summary_zh: 宏观特色（另类）高频数据行业景气 nowcasting：先用 get_macro_detail 解出不透明指标代码字典，再拉电商/医药/能化/汽车/家电/商超/招聘/地产/电子/电新等特色序列，算同比环比与趋势、与官方数据比领先滞后，输出单行业 nowcast 或跨行业景气仪表盘，支持定时监控。
  summary_en: Alternative-data high-frequency industry nowcasting that first resolves opaque
    indicator codes via get_macro_detail, then pulls e-commerce/pharma/energy-chemical/auto/
    appliance/offline-retail/hiring/real-estate/electronics/new-energy series, computes YoY/MoM
    and trend, and reads lead/lag against official stats, for a single-sector nowcast or a
    cross-sector prosperity dashboard.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Macro Alt-Data Nowcast

Use this skill to **read Pandadata's 宏观特色数据 (alternative, high-frequency) series and nowcast industry prosperity**: for one sector or a cross-sector dashboard, first **resolve the opaque indicator codes** (`EC0252098`-style) into names/units/frequency via `get_macro_detail`, then pull the matching `get_macro_*` series, compute **同比 (YoY) / 环比 (MoM)** changes and trend, and read the **lead/lag against official statistics** to say whether an industry is heating up or cooling. Prefer Pandadata as the data source, keep every figure traceable to a specific indicator code, its `get_macro_*` method, and a `period_date`, and never invent indicator meanings, values, or dates.

## Scope And Positioning (read first to avoid overlap)

This skill is the **alternative-data (特色数据) industry nowcast** view. It is deliberately distinct from its siblings:

- Unlike `macro-monitor` (official macro indicators — GDP/CPI/PPI/PMI/社融/M2/利率汇率 and the standard 宏观行业 series via `get_macro_na/in/pi/...`): this skill reads the **特色数据** family (`get_macro_ec/md/eh/ad/ha/of/rb/re/ed/ep`) — **alt data**, not official statistics. Alt data is **higher-frequency and more timely** but noisier and sample-biased; it *nowcasts* what official prints will later confirm. If the user wants official macro/industry monitoring, hand off to `macro-monitor`.
- Unlike `index-valuation-rotation` (index PE/PB percentile and industry price momentum): this skill reads **fundamental prosperity from alt data**, not price/valuation. Prosperity can lead price; keep the two separate.
- Unlike `futures-industrial-profit` (futures physical-market spot quotes & processing margins): that is commodity-chain data for futures varieties; this is consumer/industry alt data for macro sector reads.

## Alt-Data Model (read before analysis)

The 特色数据 methods share a **uniform, minimal schema** — `symbol` (指标代码), `period_date` (数据期), `data_value` (指标数值). Two consequences drive the whole workflow:

- **Indicator codes are opaque and must be resolved first.** `data_value=837.0` for `symbol=EC0252098` means nothing until you look up that code. **Always call `get_macro_detail` first** (with the matching `category`, e.g. `EC`, `MD`, `RE`) to get each code's `name`, `en_name`, `unit`, `frequency`, `stat_type`, `info_source`, and `data_begin_date`/`data_end_date`. Never report a raw code's value without its resolved name and unit.
- **The `category` maps to the method.** Each 特色 method covers one category: `get_macro_ec`=线上电商, `get_macro_md`=医药, `get_macro_eh`=能化, `get_macro_ad`=汽车, `get_macro_ha`=家电, `get_macro_of`=线下商超, `get_macro_rb`=招聘, `get_macro_re`=房地产, `get_macro_ed`=电子, `get_macro_ep`=电新. Use `get_macro_detail(category=...)` to enumerate the codes in a category, then `get_macro_<x>` to pull the series.
- **Frequency varies (daily/weekly/monthly).** Read `frequency` from the detail row; do not assume. YoY/MoM must respect the series' own frequency and its `stat_type` (level vs 累计 vs 同比 — some series are *already* a YoY figure; do not double-difference).
- **Alt data ≠ official truth.** It is a **sample** (one platform's e-commerce GMV, one job board's postings). It nowcasts direction and turning points; it is **not** the official number and carries sample/coverage bias. State this every time.
- **Dates.** `period_date` is the data period. Alt data updates faster than official prints — that *timeliness* is the whole point, but also means the latest points are provisional and may be revised.

## Workflow

1. Resolve the target: a single sector nowcast (e.g. 地产高频, 招聘景气), or a cross-sector prosperity dashboard across several 特色 categories. Confirm the date window (default a recent trailing window sized to the series frequency).
2. Read `references/altdata-playbook.md` before the first run in a session. Use it for the category→method map, the mandatory code-resolution step, YoY/MoM and stat_type rules, the prosperity scoring convention, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open that dependency's method index and the `get_macro_detail` + relevant `get_macro_*` API-documentation sections to confirm parameters and fields; do not invent parameters, fields, codes, or credentials.
4. Collect evidence:
   - **First**: `get_macro_detail(category=<X>)` to enumerate and name the indicator codes for each category in scope (capture name/unit/frequency/stat_type/source/coverage dates).
   - **Then**: `get_macro_<x>` for the resolved codes over the window (pass `symbol` to narrow to key indicators when the category is large).
5. Per indicator: attach its resolved name/unit/frequency; compute latest level, 同比/环比 (respecting `stat_type` — skip differencing if the series is already YoY), a short trend read (rising/flat/falling over the last K periods), and where the latest point sits vs its own history. Aggregate per category into a **prosperity read** (heating/cooling), labelling the scoring convention. Where a matching official series exists, note the alt-data **lead** vs `macro-monitor`'s official print — as an observation, not a claim of causation.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/altdata/<scope>-<date>.md` (e.g. `reports/altdata/dashboard-20260707.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, a missing code-resolution note, missing alt-data-caveat, missing frequency/window labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 指标字典 | `get_macro_detail` | What each opaque code means: name, unit, frequency, source, coverage. |
| 行业景气快照 | `get_macro_ec/md/eh/ad/ha/of/rb/re/ed/ep` | Latest level + 同比/环比 for the sector's key indicators. |
| 趋势与拐点 | same series over the window | Rising/flat/falling; recent turning points. |
| 跨行业对比 | multiple 特色 categories | Which sectors are heating vs cooling. |
| 与官方数据的领先 | 特色 series vs `macro-monitor` official | Where alt data leads the official print (observation only). |

## Analysis Modes

- **Single-sector nowcast**: resolve one category's codes, pull the key series, compute YoY/MoM + trend, and give a heating/cooling read for that industry with the indicators cited.
- **Cross-sector dashboard**: run several categories, score each into a prosperity read, and rank sectors from most-heating to most-cooling — with the scoring convention labelled.
- **Lead/lag read**: place an alt-data series next to its official counterpart (e.g. 招聘数据 vs 官方就业, 地产高频 vs 官方地产投资) and note whether alt data has turned earlier. State as **relative observation**, never a forecast guarantee.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Resolve every code first.** Never present a raw `symbol` code or its `data_value` without the `get_macro_detail` name, unit, and frequency behind it.
- **Respect `stat_type`.** If a series is already a YoY/累计 figure, do not compute another 同比 on top of it — read it as published and say so.
- **Label the data as alternative/sample.** Every prosperity read must state that 特色数据 is a timely **sample** that nowcasts, not the official statistic; note coverage/source from `info_source`.
- Mark **frequency** (daily/weekly/monthly) and the window for each series; the latest points are provisional.
- Separate facts (resolved indicator, level, source), derived metrics (YoY/MoM, trend, prosperity score, rank), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method/category and window instead of silently omitting a section.
- Keep the tone factual and structural. Use "景气回升/走弱", "环比转正", "或领先官方读数" rather than directional market calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated alt-data monitor, create a task that runs on a cadence matched to the series frequency (e.g. weekly for weekly series). Make it idempotent: if `reports/altdata/<scope>-<date>.md` exists, regenerate and overwrite. Re-resolve `get_macro_detail` periodically — indicator codes and coverage can change.

## Resource Guide

- `references/altdata-playbook.md`: the category→method map, the mandatory code-resolution step, YoY/MoM & stat_type rules, prosperity scoring convention, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, the code-resolution (get_macro_detail) note, the alt-data/sample caveat, frequency/window labels, and the disclaimer.

## Quality Bar

- Every indicator carries its resolved name, unit, and frequency from `get_macro_detail`; no raw code or bare `data_value` stands alone.
- YoY/MoM respects each series' `stat_type`; already-YoY series are not double-differenced.
- Every prosperity read states that 特色数据 is a timely sample (with source/coverage), not the official statistic.
- Cross-sector scoring and any lead/lag call are labelled conventions/observations, not forecasts.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
