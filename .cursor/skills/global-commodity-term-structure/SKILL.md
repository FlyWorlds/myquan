---
name: global-commodity-term-structure
description: "Analyze overseas/international commodity futures term structure - contango vs backwardation, roll yield, calendar and inter-commodity spreads, and inventory context - using public data. Use when a user asks to study overseas futures curves, roll cost, WTI/Brent/gold/copper term structure, or cross-commodity spreads for research."
license: GPL-3.0-only
quantSkills:
  organization: https://github.com/quantskills
  organization_url: https://github.com/quantskills
  repository: quantskills/skill-global-commodity-term-structure
  repository_url: https://github.com/quantskills/skill-global-commodity-term-structure
  project_type: skill
  collection: global-commodity-term-structure
  license: GPL-3.0
  category: analyst            # trader-research / factor / data-api / replication / monitor / analyst / tooling
  tags: [commodities,futures,term-structure,roll-yield,overseas]                  # lowercase-hyphenated, 1-10 items
  platforms: [claude-code, codex, openclaw, cursor]        # claude-code / codex / openclaw / cursor / workbuddy
  language: zh-en
  status: draft                     # draft / active / stable / deprecated
  validation_level: listed          # listed / runnable / verified (community three-level scheme)
  maintainer_type: community        # official / community
  creator: abgyjaguo
  maintainer: abgyjaguo
  requires: []                      # dependent sibling skill-* / agent-* repository names
  summary_zh: "用公开数据研究海外商品期货期限结构：contango/backwardation、展期收益、跨期与跨品种价差、库存背景。"      # 8-120 chars
  summary_en: "Research overseas commodity futures term structure, roll yield, and cross-commodity spreads from public data."      # 8-200 chars
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "补充交易所、合约月份、跨品种价差或库存背景要求（可选）"
  },
  "fields": [
    {
      "key": "variety",
      "label": "海外商品品种",
      "type": "text",
      "required": true,
      "placeholder": "例如 WTI、Brent、黄金、铜、天然气"
    },
    {
      "key": "date",
      "label": "参考日期",
      "type": "date",
      "default": ""
    },
    {
      "key": "focus",
      "label": "分析重点",
      "type": "select",
      "default": "full",
      "options": [
        { "value": "full", "label": "完整期限结构" },
        { "value": "roll_yield", "label": "展期收益" },
        { "value": "calendar_spread", "label": "跨期价差" },
        { "value": "intercommodity", "label": "跨品种价差" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}使用公开网页数据研究 {{variety}} 的海外期货期限结构{{#date}}，参考日期 {{date}}{{/date}}；未指定日期时用最新可得报价日。分析重点为 {{focus}}；至少使用两个真实挂牌月份，区分结算价与最新价，计算曲线斜率、展期收益和相关价差，并补充可得的库存背景。每个数字标注来源和日期，不得虚构或插值缺失月份，强调期限结构反映 carry 而非价格方向，输出中文报告。"
}
```

# Global Commodity Term Structure

Use this skill to build and read the **term structure of overseas / international
commodity futures** (WTI, Brent, gold, silver, copper, natural gas, and similar
CME/COMEX/NYMEX/ICE/LME contracts) from **public web data only**, and to describe
carry — contango vs backwardation, curve slope, roll yield, calendar spreads, and
inter-commodity spreads — with inventory context. The output is a factual research
note about the shape of the curve. Term structure describes **carry, not price
direction**; it is never a buy/sell signal.

This skill fills a specific gap: Pandadata has **no overseas futures coverage** (its
coverage doc says use Yahoo/stooq/public-exchange data for foreign contracts), so this
skill deliberately does **not** call Pandadata. It is also distinct from the
China-only futures skills (`futures-deepview-analyst`, `futures-industrial-profit`,
`futures-cross-variety-corr`), which read domestic exchange/DeepView data. This one is
**overseas commodities from public sources**.

## Data Access

All data is **public web content**, fetched through the repository's own web tooling
(the agent's browser / fetch / search capability). No API keys, no paid feeds, no
Pandadata. See `references/data-sources.md` for exact venues and the symbol map, and
`references/source_boundary.md` for what may and may not be read.

## Core Workflow

1. **Scope the request.** Confirm the commodity (or a pair for a spread), the venue,
   and the reference date. Read `references/source_boundary.md` and
   `references/data-sources.md` before fetching anything.
2. **Pick the variety and its symbol.** Map the user's commodity to a public symbol
   from the table in `references/data-sources.md` (e.g. crude = `CL=F`/`BZ=F`, gold =
   `GC=F`, copper = `HG=F`, natural gas = `NG=F`). Record the venue, currency, and
   contract unit — they differ per exchange.
3. **Pull the futures curve (≥ 2 real contract months).** Retrieve settlement (or, if
   settlement is unavailable, last-trade) prices for several sequential listed
   contract months (M1, M2, M3, …). A curve needs at least two **real** listed months.
   **Never fabricate a month or interpolate a missing one into the curve.** Label each
   price as settlement vs last-trade and record its as-of date.
4. **Classify the structure and compute the slope.** Compare near vs far:
   - far > near ⇒ **contango** (upward-sloping, positive carry cost);
   - far < near ⇒ **backwardation** (downward-sloping);
   - mixed ⇒ note the humped/kinked shape and where it flips.
   Compute the annualized slope between the front two (or front and a stated deferred)
   months: `slope_annualized = (P_far / P_near - 1) / (Δmonths / 12)`. Report it as a
   percentage and state which two contracts it used.
5. **Estimate roll yield.** For a long position rolling from the front contract to the
   next, the per-roll cost/gain is approximately `(P_near - P_far) / P_near` (positive
   = positive roll yield under backwardation, negative = roll drag under contango).
   Annualize using the months between the two contracts. State that this is an
   **approximation of carry**, sensitive to the roll convention, not a realized return.
6. **Compute calendar spreads.** For the listed months, report absolute spreads
   (`P_near - P_far`) for the front pairs (e.g. M1–M2, M2–M3). Note the currency/unit.
7. **Compute inter-commodity spreads (when relevant).** Common public examples:
   - **Brent–WTI** spread (`BZ=F - CL=F`), a location/quality spread;
   - a simplified **crack** proxy (e.g. RBOB or heating-oil vs crude) — clearly label
     it as a rough proxy, not a refinery-grade 3-2-1 crack;
   - **gold/silver ratio** (`GC=F / SI=F`);
   - **gold–copper** or other cross-commodity ratios on request.
   State the formula and units for every spread.
8. **Add inventory / fundamental context (qualitative).** Where a public inventory
   series exists, add it as background only: EIA weekly petroleum stocks for crude /
   products, LME warehouse stocks for base metals. Note the report date and that
   inventory context is directional color, not a model input.
9. **Write the factual report** per the Output Contract, with every number carrying a
   source label and an as-of date, plus the boundary block.

## Output Contract

Produce a single Markdown report (default `outputs/term-structure-<symbol>-<date>.md`,
saved locally, not committed) containing, in order:

1. **标题 / Title** — commodity, venue, and report date.
2. **数据来源与日期 / Data Sources & Date** — every venue and symbol used, each price
   labelled settlement vs last-trade with its as-of date.
3. **期限结构 / Term Structure** — the curve table (contract month → price), the
   contango/backwardation classification, and the annualized slope (stating which two
   contracts).
4. **展期收益 / Roll Yield** — the per-roll and annualized estimate, with the roll
   convention stated.
5. **价差 / Spreads** — calendar spreads and any inter-commodity spreads, each with its
   formula and units.
6. **库存背景 / Inventory Context** — qualitative, with the report date (or "无公开可用
   数据 / no public data used" if omitted).
7. **边界 / Boundaries** — including the exact line below.

Run `python scripts/validate_report.py <report.md>` to check the report has all
required sections and source/date labels before delivering.

## Data Sources

Summary (full detail and the symbol map live in `references/data-sources.md`):

- **Exchange settlement pages** — CME / COMEX / NYMEX / ICE / LME public settlement and
  product pages.
- **Yahoo Finance** continuous / front-month symbols (`CL=F`, `BZ=F`, `GC=F`, `SI=F`,
  `HG=F`, `NG=F`, …) and, where listed, individual contract months.
- **stooq** public futures quotes as a cross-check / fallback.
- **Public inventory** — EIA (petroleum) and LME warehouse stocks.

## References

- `references/methodology.md` — curve construction, slope, roll-yield and spread math,
  classification rules, pitfalls, and graceful-degradation notes.
- `references/data-sources.md` — exact venues, the commodity→symbol map, unit/currency
  notes, and settlement-vs-last-trade guidance.
- `references/source_boundary.md` — what data this skill may and may not read.

## Boundaries

- Overseas commodities, **public web data only**; no Pandadata, no paid feeds, no API
  keys.
- **A curve needs ≥ 2 real listed contract months.** Never fabricate or interpolate a
  month; if only one price is available, say so and stop — do not invent a structure.
- **Continuous-contract splicing distorts levels** (roll gaps). When a continuous
  series is used, state the roll convention and treat spliced history as approximate.
- Distinguish **settlement vs last-trade**, and respect **per-exchange currency and
  unit differences**; never mix units silently.
- Inventory context is qualitative background, not a forecasting input.
- Term structure describes **carry, not a price signal**; research and educational
  tooling only, not official, certified, or verified.
- 不构成任何投资建议 / does not constitute investment advice.
