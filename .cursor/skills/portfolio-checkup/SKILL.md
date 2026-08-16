---
name: portfolio-checkup
description: Portfolio-level checkup skill for an A-share holdings list, built on Pandadata
  interfaces. It aggregates single-stock signals up to the portfolio layer, covering
  structure and concentration (industry/concept exposure, top-N weight, HHI), weighted
  valuation and financial-quality distribution, portfolio risk exposure aggregation
  (unlock/pledge/reduction/ST share of portfolio), and benchmark deviation (industry
  over/underweight vs an index, range return and correlation). Use when the user asks for
  组合体检、持仓诊断、持仓组合分析、行业集中度、HHI 集中度、基准偏离、组合风险敞口、解禁质押减持聚合、组合估值分布、组合相对沪深300偏离,
  or a one-stop portfolio health report for a self-maintained holdings list.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-portfolio-checkup
  repository_url: https://github.com/quantskills/skill-portfolio-checkup
  project_type: skill
  collection: portfolio-checkup
  creator: abgyjaguo
  creator_url: https://github.com/abgyjaguo
  maintainer: abgyjaguo
  maintainer_url: https://github.com/abgyjaguo
quantSkills:
  project_type: skill
  category: analyst
  tags:
    - a-share
    - portfolio-checkup
    - concentration
    - benchmark-deviation
    - risk-exposure
    - pandadata
  platforms:
    - claude-code
    - codex
    - hermes
    - openclaw
    - cursor
  status: draft
  validation_level: rules-only
  maintainer_type: community
  summary_zh: 输入一个持仓组合清单（代码+权重/市值），输出组合层级的体检报告：结构与集中度、估值与财务质量分布、风险敞口聚合（解禁/质押/减持/ST）、基准偏离与资金面。
  summary_en: Portfolio-level checkup skill that uses Pandadata to aggregate single-stock signals into portfolio structure, concentration, weighted valuation/quality, risk exposure, and benchmark deviation.
  license: GPL-3.0-only
  requires:
    - skill-pandadata-api
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "粘贴持仓代码及权重/市值，或上传 portfolio.json，并补充体检范围",
    "required": true
  },
  "fields": [
    {
      "key": "index",
      "label": "对比基准",
      "type": "select",
      "default": "000300.SH",
      "options": [
        { "value": "000300.SH", "label": "沪深300" },
        { "value": "000905.SH", "label": "中证500" },
        { "value": "000016.SH", "label": "上证50" },
        { "value": "000852.SH", "label": "中证1000" },
        { "value": "399006.SZ", "label": "创业板指" }
      ]
    },
    {
      "key": "focus",
      "label": "重点关注",
      "type": "text",
      "placeholder": "例如：行业集中度、解禁质押、估值质量或基准偏离"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}读取并规范化用户持仓，明确按权重、市值或等权的统一权重口径，以 {{index}} 为基准，{{#focus}}重点检查：{{focus}}；{{/focus}}聚合分析行业/概念集中度、Top-N 与 HHI、估值和财务质量、解禁/质押/减持/ST 风险暴露、基准行业偏离及区间收益相关性，披露数据覆盖权重和缺失项，仅给风险提醒，输出中文报告。"
}
```

# Portfolio Checkup

Use this skill to turn a **holdings list** (symbols plus weights or market value) into a sourced Chinese **portfolio-level** health report. It does not analyze one stock in isolation: it rolls single-stock facts up to the portfolio layer and answers questions like *how concentrated am I, how much of my book is exposed to unlocks/pledges/reductions, and where do I deviate from my benchmark*.

This is the **orchestration / portfolio layer** of the Pandadata skill family. It reuses the single-point logic of three sibling skills and lifts it to the portfolio level:

- **`a-share-stock-dossier`** (single-stock due diligence) — when a constituent looks risky and the user wants to drill down, hand that one symbol off to `a-share-stock-dossier`. This skill stays at the weighted-aggregate altitude.
- **`event-risk-alert`** (per-symbol event alerts) — instead of firing one alert per stock, this skill **aggregates the same event signals into portfolio exposure percentages**: "X% of my book unlocks in the next 90 days", "Y% sits in high-pledge names".
- **`index-valuation-rotation`** (index / industry layer) — borrow its benchmark and industry logic to compute the portfolio's **deviation from a benchmark index** and per-industry over/underweight, instead of analyzing the index for its own sake.

## Anti-Collision Positioning

Write this section's distinctions into every report's data notes so users understand the altitude.

| Sibling skill | Its altitude | This skill's difference |
|---|---|---|
| `a-share-stock-dossier` | One symbol, deep | **Weighted aggregation across the whole list.** Single-stock deep dives are delegated to dossier; here a constituent is one row contributing to a portfolio metric. |
| `event-risk-alert` | Per-symbol, time-triggered alerts | **Portfolio exposure rollup.** Answers "how much of my portfolio (by weight) is exposed to unlock / pledge / reduction / ST", not "which stock fires which alert today". |
| `index-valuation-rotation` | Index / industry universe | **The user's own holdings, relative to a benchmark.** Computes industry over/underweight and range return/correlation of the portfolio against an index, not standalone index valuation. |

## Core Workflow

1. **Load the portfolio.** Read the user's holdings from a local `portfolio.json` (format below) or from the symbols and weights the user pastes in. Normalize each symbol to `XXXXXX.SH` / `XXXXXX.SZ` (infer `SH` for `600/601/603/605/688/689`, `SZ` for `000/001/002/003/300/301`; ask when ambiguous).
2. **Resolve the weight basis.** Decide and state the weighting basis once, up front: by user-given `weight`, by user-given `market_value`, or — only if neither is present — equal weight. Normalize weights to sum to 1 (100%). Every weighted aggregate later must use this same basis. See `references/checkup-guide.md` for the weight-basis rules and the equal-weight fallback.
3. **Confirm scope and benchmark.** Default benchmark is 沪深300 (`000300.SH`) unless the user names another index. Default windows: latest available data; ~3 fiscal years of statements; 1 year of price data; next 12 months of forward unlock events. Confirm any user override.
4. **Read the guide.** Before the first checkup in a session, read `references/checkup-guide.md` for concentration/HHI formulas, weighted-aggregation methods, risk-exposure rollup rules and default thresholds, benchmark-deviation algorithm, the checkup score, and the report blueprint.
5. **Use `pandadata-api` for all real data calls.** Open its `references/method-index.md` and the exact method section in `references/api-docs.md` before calling its `scripts/call_api.py`. Do not invent method names, parameters, fields, symbols, or credentials.
6. **Collect per-stock evidence, then aggregate.** For each module, fetch the per-symbol rows first, then roll them up with the stated weight basis. Keep enough raw rows or row counts to cite source method, data date / report period, and missing-data status.
7. **Produce Markdown by default.** If the user wants Word/PDF/HTML, generate the analytical content here first, then hand off to the relevant document skill for layout.

## Module → Interface Map

Confirm exact parameters and fields via `pandadata-api` before every call. Methods below are verified against the Pandadata method index.

| Module | Pandadata methods | What it produces at portfolio level |
|---|---|---|
| 1. Structure & concentration | `get_stock_industry` · `get_industry_constituents` · `get_concept_constituents` | Weighted industry distribution, concept exposure, top-N weight, HHI concentration index. |
| 2. Valuation & financial quality | `get_index_indicator` · `get_fina_reports` · `get_fina_forecast` · `get_share_float` | Weighted PE/PB/ROE/growth/leverage distribution vs the benchmark index's valuation; forecast-warning share. |
| 3. Portfolio risk exposure | `get_restricted_list` · `get_stock_pledge` · `get_stock_pledge_stat` · `get_stock_shareholder_change` · `get_stock_status_change` | Share of portfolio (by weight) exposed to upcoming unlocks, high pledge, planned reductions, and ST status — as exposure percentages, not per-stock alerts. |
| 4. Benchmark deviation | `get_index_weights` · `get_index_indicator` · `get_stock_daily` | Per-industry over/underweight vs benchmark index weights; portfolio range return, correlation, and concentration risk vs benchmark. |
| 5. Funds overlay (optional) | `get_hsgt_hold` · `get_margin` · `get_lhb_list` | Recent northbound, margin, and 龙虎榜 activity summarized across constituents. |

Notes on method scope (verified against `api-docs.md`):
- `get_stock_pledge` is the **per-symbol** pledge method; use its `acc_pledge_total_ratio` (累计质押占公司总股本比例) field to flag high-pledge constituents and sum their weights. `get_stock_pledge_stat` is a **market/exchange-level** statistic (no `symbol` parameter) — use it only as a market backdrop, never as a per-stock value.
- `get_index_weights` returns `weight` only when you request it via `fields`; benchmark industry weights come from joining its constituents to `get_stock_industry`.
- `get_stock_detail` does **not** return market cap or total shares. For market-cap weighting fallback, derive shares from `get_share_float` (`total` / `free_circulation`) times `close` from `get_stock_daily`, and label the estimate.

## Analysis Rules

- **State the weight basis everywhere.** Every weighted number (weighted PE, exposure %, industry weight) must say whether it is weighted by user `weight`, by `market_value`, or equal weight, and confirm the weights summed to 100% (note any residual cash or unmapped symbols).
- **Separate facts, derived metrics, and judgment.** Label all derived quantities (HHI, top-N weight, weighted ratios, deviation, exposure %, checkup score) with their formula and the fields used. Formulas live in `references/checkup-guide.md`.
- **Degrade gracefully when a denominator is missing.** If a per-stock value (e.g. unlock market value, pledge ratio, ROE) is unavailable for some constituents, do not silently drop them: report the covered weight share, mark the uncovered weight, and downgrade the affected metric to a qualitative note. Never present a weighted aggregate as if it covered 100% when it did not.
- **Aggregate, do not itemize.** Report risk as portfolio exposure (e.g. "解禁市值占组合 6.2%，覆盖权重 92%"), and list only the top contributing constituents. For a deep single-stock view, hand the symbol to `a-share-stock-dossier`; for time-triggered per-stock alerts, hand the list to `event-risk-alert`.
- **Source everything.** Each conclusion cites source method, query window, and data date / report period. Financial aggregates state the report period used and avoid mixing single-quarter and cumulative figures.
- **Risk-only action notes.** The action section gives risk reminders and watch items only — never buy/sell instructions. Use restrained wording ("可能提示", "需要关注", "组合在 X 上的暴露偏高").
- End every report with this disclaimer exactly: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`

## portfolio.json Format

Maintain the holdings locally as `portfolio.json`. All fields except `symbol` are optional, but provide `weight` **or** `market_value` so the weighting basis is explicit; if neither is present the skill falls back to equal weight and says so.

```json
{
  "as_of": "2026-06-29",
  "name": "我的核心组合",
  "benchmark": "000300.SH",
  "weight_basis": "weight",
  "cash_weight": 0.05,
  "holdings": [
    { "symbol": "600519.SH", "name": "贵州茅台", "weight": 0.18, "cost": 1680.0 },
    { "symbol": "300750.SZ", "name": "宁德时代", "weight": 0.12 },
    { "symbol": "000001.SZ", "name": "平安银行", "market_value": 52000 }
  ]
}
```

Field notes:
- `weight_basis`: one of `weight` | `market_value` | `equal`. If omitted, infer from which field the holdings carry; if mixed or absent, default to `equal` and state it.
- `weight`: target/actual weight as a fraction or percent; normalize the set to sum to 1. `market_value`: position market value in the same currency unit; weights are `market_value / Σ market_value`.
- `cash_weight` (optional): residual cash not allocated to symbols; subtract it before normalizing equity weights and disclose it.
- `cost` (optional): position cost, carried through for context only; this skill does not compute P&L.
- `benchmark` (optional): comparison index symbol; defaults to `000300.SH`.

## Resource Guide

- `references/checkup-guide.md`: concentration/HHI formulas, weighted-aggregation methods, risk-exposure rollup rules and default thresholds, benchmark-deviation algorithm, checkup-score rubric, report blueprint, and QA checklist.
- `portfolio.json`: example holdings list demonstrating the format above.

## Quality Bar

- Every material claim traces to a Pandadata method, report period / data date, and fetch window.
- Every weighted aggregate states its weight basis and covered weight share; partially covered metrics are flagged, not rounded up to 100%.
- Concentration, deviation, exposure, and score are reproducible from the formulas in `references/checkup-guide.md`.
- Empty or partial API results are disclosed with the method name and queried window, not hidden.
- The action section contains risk reminders only; the final disclaimer appears exactly as required above.
