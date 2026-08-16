---
name: global-macro-rates-fx-lab
description: "Study global macro, rates, and FX regime - DM central-bank policy, sovereign yield curves, real rates, DXY and major currency pairs - from public FRED/central-bank data and Pandadata international macro. Use when a user asks about overseas rates, the yield curve, USD or major FX trends, or the global macro regime for research."
license: GPL-3.0-only
quantSkills:
  organization: https://github.com/quantskills
  organization_url: https://github.com/quantskills
  repository: quantskills/skill-global-macro-rates-fx-lab
  repository_url: https://github.com/quantskills/skill-global-macro-rates-fx-lab
  project_type: skill
  collection: global-macro-rates-fx-lab
  license: GPL-3.0
  category: analyst            # trader-research / factor / data-api / replication / monitor / analyst / tooling
  tags: [macro,rates,fx,yield-curve,overseas]                  # lowercase-hyphenated, 1-10 items
  platforms: [claude-code, codex, openclaw, cursor]        # claude-code / codex / openclaw / cursor / workbuddy
  language: zh-en
  status: draft                     # draft / active / stable / deprecated
  validation_level: listed          # listed / runnable / verified (community three-level scheme)
  maintainer_type: community        # official / community
  creator: abgyjaguo
  maintainer: abgyjaguo
  requires: [skill-pandadata-api]   # dependent sibling skill-* / agent-* repository names
  summary_zh: "用公开 FRED/央行数据与 Pandadata 国际宏观研究全球利率、外汇与宏观周期。"      # 8-120 chars
  summary_en: "Study global rates, FX, and macro regime from public FRED/central-bank data and Pandadata international macro."      # 8-200 chars
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "补充关注的央行、收益率期限、货币对、事件或比较要求"
  },
  "fields": [
    {
      "key": "region",
      "label": "区域范围",
      "type": "select",
      "default": "global",
      "options": [
        { "value": "global", "label": "全球主要发达市场" },
        { "value": "us", "label": "美国" },
        { "value": "eurozone", "label": "欧元区" },
        { "value": "japan", "label": "日本" },
        { "value": "uk", "label": "英国" }
      ]
    },
    {
      "key": "focus",
      "label": "研究重点",
      "type": "select",
      "default": "rates_fx",
      "options": [
        { "value": "rates_fx", "label": "利率与外汇" },
        { "value": "rates", "label": "政策利率与收益率曲线" },
        { "value": "fx", "label": "美元与主要货币对" }
      ]
    },
    {
      "key": "horizon",
      "label": "回看窗口",
      "type": "select",
      "default": "3m",
      "options": [
        { "value": "1m", "label": "近1个月" },
        { "value": "3m", "label": "近3个月" },
        { "value": "1y", "label": "近1年" },
        { "value": "3y", "label": "近3年" }
      ]
    },
    {
      "key": "date",
      "label": "截至日期",
      "type": "date",
      "help": "留空由前端使用今天"
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请研究 {{region}} 的全球宏观、利率与外汇状态，重点为 {{focus}}，回看 {{horizon}}{{#date}}、截至 {{date}}{{/date}}；逐项标注公开序列 ID、单位、观察日与数据版本，分析政策利率、2年/10年收益率、2s10s、实际利率、贸易加权美元及主要货币对的一致性与背离，输出中文报告。"
}
```

# Global Macro Rates FX Lab

Use this skill to build a factual, sourced read of the **overseas / global** macro-rates-FX
regime: developed-market (DM) central-bank policy, sovereign yield curves and their slope,
real rates, the trade-weighted US dollar (DXY-style), and the major currency pairs
(EURUSD / USDJPY / GBPUSD). Data comes from **public FRED / central-bank series and public FX
references**, plus **Pandadata international macro** (`get_macro_gb`) delegated to the
`pandadata-api` skill. Every number stays traceable to a named series and observation date.
This is a description of the regime, never a trade call.

**Scope boundary — read this first.** This skill is **overseas / global** rates + FX from
public sources. It is deliberately different from two sibling skills, and you must not silently
substitute one for another:

- `macro-monitor` — Pandadata macro/industry, **China-focused** domestic aggregates and calendar.
- `macro-altdata-nowcast` — **China alt-data** nowcasting.
- **this skill** — DM/global rate complex + USD/major FX from public FRED/central-bank/FX data,
  with `get_macro_gb` as the only Pandadata surface.

## Core Rules

- **Delegate every Pandadata call to the `pandadata-api` skill.** The only method this skill
  uses is `get_macro_gb` (宏观行业·国际宏观). Do not invent other method names, symbols, or
  response fields. Its contract is `get_macro_gb(symbol=None, start_date="YYYYMMDD",
  end_date="YYYYMMDD", fields=None)` returning `symbol / period_date / data_value`.
- **Cite the exact public series id** for every FRED/central-bank/FX number (e.g. `DGS2`,
  `DGS10`, `T10Y2Y`, `DFII10`, `DTWEXBGS`) plus the observation date. Never paste an unlabelled
  number.
- **Note the vintage.** FRED series lag and revise; daily rate series can be a day or more
  behind, and level series are periodically re-based. State the as-of / vintage date and flag
  when the latest print may still revise.
- **Units are load-bearing.** Yields and policy rates are in **percent**; curve spreads may be
  quoted in **percentage points or basis points** — state which and never mix them. FX pairs
  follow market quoting convention (EURUSD and GBPUSD are USD-per-unit; USDJPY is JPY-per-USD),
  so a "stronger dollar" moves EURUSD/GBPUSD **down** but USDJPY **up**.
- **An inversion is an observation, not a forecast.** Report `2s10s < 0` as a factual state of
  the curve; do not translate it into a recession call or a trade.
- **Separate fact from inference.** State observed levels and changes first, then label any
  regime read as interpretation with its confidence and any contradicting evidence.
- Default to Chinese Markdown; produce an HTML/dashboard artifact only when the user asks.

## Workflow

1. **Scope the request.** Confirm it is overseas/global rates or FX (not China domestic — route
   those to `macro-monitor`). Fix the region set (US always; add EUR-area / Japan / UK as asked),
   the lookback window, and whether the user wants the rate complex, FX, or both.
2. **Assemble the DM rate complex.** For each region gather: the policy rate (from the
   central-bank policy page / FRED policy series), the 2y and 10y sovereign yield, the **2s10s
   slope** (10y − 2y), and the **real rate** (e.g. `DFII10` for the US 10y TIPS real yield).
   For the US pull `DGS2`, `DGS10`, `T10Y2Y`, `DFII10`. Record level, recent change, and vintage.
3. **Read USD and the major pairs.** Take the broad trade-weighted dollar (`DTWEXBGS`) as the DXY
   proxy, then EURUSD / USDJPY / GBPUSD from public FX references (ECB reference rates or a public
   exchange-rate host). Report each pair's level, direction over the window, and consistency with
   the dollar index — applying the quoting-convention rule above.
4. **Add the Pandadata international-macro layer.** Delegate to `pandadata-api` to call
   `get_macro_gb` for the relevant international indicators over the same window, aligning
   `period_date` with the public-series dates. Keep raw `symbol` codes and mark any value you
   compute (e.g. a change) as a calculated value.
5. **Form a factual regime read.** Synthesize: is the curve steepening or flattening / inverted;
   are real rates rising or falling; is the dollar broadly firm or soft; do the major pairs and
   DXY agree; where do the public series and `get_macro_gb` confirm or contradict each other.
   Frame everything as a regime observation with confidence, never as a directional call.
6. **Emit the output contract** below, then run `scripts/validate_report.py` on the produced
   report to confirm required sections and source/date labels are present.

## Output Contract

Produce a Chinese Markdown regime brief containing, in order:

1. **概览 / Regime summary** — 2–4 factual sentences on the rate + FX regime, each tied to a series.
2. **利率综合体 / Rate complex table** — per region: policy rate, 2y, 10y, 2s10s slope (unit
   stated), real rate, each with series id, latest value, change, and as-of/vintage date.
3. **美元与主要货币对 / USD & major pairs table** — DXY proxy + EURUSD / USDJPY / GBPUSD with
   level, window change, quoting convention, and source.
4. **国际宏观（Pandadata）/ International macro** — `get_macro_gb` indicators with `symbol`,
   `period_date`, `data_value`, marking computed values.
5. **区域一致性与背离 / Consistency & divergences** — where evidence agrees or conflicts.
6. **数据来源与时效 / Sources & vintage appendix** — every series id, its provider, and its
   as-of date.
7. A trailing disclaimer line: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`

## Data Sources

- **FRED (public):** `DGS2`, `DGS10`, `T10Y2Y` (2s10s), `DFII10` (10y real / TIPS), `DTWEXBGS`
  (broad trade-weighted USD, DXY proxy).
- **Central-bank policy pages (public):** Federal Reserve, ECB, Bank of Japan, Bank of England
  for the current policy-rate level and stance.
- **Public FX references:** ECB euro reference rates and public exchange-rate hosts for
  EURUSD / USDJPY / GBPUSD.
- **Pandadata `get_macro_gb`** (宏观行业·国际宏观), delegated to the `pandadata-api` skill —
  the only Pandadata method used here.

See `references/data-sources.md` for the full series catalogue and `references/methodology.md`
for the computation and pitfall notes.

## References

- `references/methodology.md` — rate-complex and FX computations, regime read, pitfalls, graceful degradation.
- `references/data-sources.md` — exact series ids, providers, units, frequency, and the `get_macro_gb` contract.
- `references/source_boundary.md` — what data this skill may and may not read.

## Boundaries

- Overseas/global research and workflow tooling only; **not** official, certified, verified, or
  endorsed, and not a China-macro skill (use `macro-monitor` / `macro-altdata-nowcast` for that).
- State data sources, series ids, units, windows, vintage, and known limits for every figure.
- Yield-curve inversion and FX moves are reported as observations, not forecasts or trades.
- 不构成任何投资建议 / does not constitute investment advice.
