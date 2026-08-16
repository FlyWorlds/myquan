---
name: concept-rotation-monitor
description: Rank and track A-share concept/theme (概念题材) rotation with the Pandadata
  get_concept_list and get_concept_constituents interfaces, aggregating each concept's
  constituent daily returns from get_stock_daily into a concept-level momentum and
  breadth ranking, detecting newly-formed concepts, and reading short-vs-long-window
  momentum to see which themes are heating up or cooling down. Use when the user asks
  for 概念轮动, 题材轮动, 概念热度, 板块轮动, 概念动量排名, 题材涨幅榜, 新概念, 概念成分股, or an A-share
  concept-rotation monitor report.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-concept-rotation-monitor
  repository_url: https://github.com/quantskills/skill-concept-rotation-monitor
  project_type: skill
  collection: concept-rotation-monitor
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - concept
  - theme-rotation
  - momentum
  - breadth
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
  summary_zh: A股概念题材热度轮动监控：把每个概念的成分股日涨跌用 get_stock_daily 聚合成概念级动量与广度排名、识别新成立概念、比较短/长窗口动量看题材升温还是降温，明确等权口径、成分时点、概念重叠与滞后。
  summary_en: A-share concept/theme rotation monitor that aggregates each concept's constituent
    daily returns into concept-level momentum and breadth rankings, detects newly-formed
    concepts, and compares short-vs-long-window momentum to see which themes are heating
    up or cooling down.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Concept Rotation Monitor

Use this skill to **rank and track A-share concept/theme (概念题材) rotation**: aggregate each concept's **constituent daily returns** (from `get_stock_daily`) into a concept-level **momentum** and **breadth** ranking, detect **newly-formed concepts** (via inclusion dates), and compare **short-window vs long-window momentum** to see which themes are heating up or cooling down. Prefer Pandadata as the data source, keep every figure traceable to `get_concept_list` / `get_concept_constituents` / `get_stock_daily` and a date, and never invent concepts, constituents, returns, or rankings.

## Scope And Positioning (read first to avoid overlap)

This skill is the **concept/theme rotation** view. It is deliberately distinct from its siblings:

- Unlike `market-daily-review` (daily whole-market review that surfaces the *single day's* hot concepts as one section): this skill builds a **rotation time-series** — momentum over configurable windows, short-vs-long momentum spread, breadth, and new-concept detection across a lookback. If the user wants a one-day end-of-day review, hand off to `market-daily-review`.
- Unlike `stock-screener` (natural-language stock filter that may use concept membership as a *condition*): this skill ranks the **concepts themselves**, not stocks; the output is a theme leaderboard, not a stock shortlist. If the user wants stocks inside a theme filtered by fundamentals, hand off to `stock-screener`.
- Unlike `index-valuation-rotation` (industry/index **valuation** percentile and **industry** momentum): that works on标准行业 indices with valuation percentiles; this works on **market concepts/themes** (英伟达概念, etc.) built bottom-up from constituent returns, without valuation. Complementary lenses — industry vs theme.
- Unlike `portfolio-checkup` / `smart-money-profiler` (which use concept membership incidentally): the concept-rotation signal itself lives here.

## Concept Rotation Model (read before analysis)

There is **no concept price index field** — you build the concept signal **bottom-up** from constituent daily returns. Be explicit about every aggregation choice.

- **Concept universe (`get_concept_list`)** — returns `name` (概念名称) and `date` (概念纳入/成立日期). A recent `date` marks a **newly-formed concept** — flag these; a brand-new concept has little history and its "momentum" is not comparable to a seasoned one.
- **Constituents (`get_concept_constituents`)** — returns `concept`, `concept_stock` (成分股 code), and `date` (股票纳入该概念日期). **Constituent membership is time-varying** — pass a `date` to get the snapshot as of that day; do not use today's membership to compute last month's return (survivorship/lookahead). State the membership snapshot date.
- **Constituent returns (`get_stock_daily`)** — per constituent, compute the window return (e.g. 5D / 20D). Aggregate to the concept:
  - **Momentum** = the concept's aggregate constituent return over the window. Use **median** (robust) or **equal-weight mean**; state which. Equal-weight is the default (a concept has no natural cap weighting); note that a few extreme names can dominate a mean.
  - **Breadth** = share of constituents up over the window (e.g. % with positive return, or % above their own 20D MA). Momentum + breadth together separate a broad theme move from one or two runners.
- **Short vs long momentum** — compare a short window (e.g. 5D) to a long window (e.g. 20D/60D). Short ≫ long ⇒ **heating up / newly rotating in**; short ≪ long ⇒ **cooling / rotating out**. This spread is the rotation signal.
- **Concept overlap** — one stock belongs to many concepts; concept returns are **not independent**. Do not sum them or treat leaders as additive exposure; a hot stock lifts every concept it is in.

## Workflow

1. Resolve the target: a whole-market concept leaderboard, or a specific concept's constituents/timeline. Confirm the momentum windows (default 5D and 20D) and the lookback for new-concept detection.
2. Read `references/concept-rotation-playbook.md` before the first run in a session. Use it for the routing table, the bottom-up aggregation formulas, weighting/breadth definitions, the membership-snapshot rule, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_concept_list` / `get_concept_constituents` / `get_stock_daily` sections in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence:
   - Concept universe & new concepts: `get_concept_list` over the lookback.
   - Constituents as-of the snapshot date: `get_concept_constituents` with an explicit `date`.
   - Constituent daily returns: `get_stock_daily` over the momentum windows for the constituents.
   - Trading calendar: `get_last_trade_date` / `get_trade_cal` to bound windows and count trading days.
5. Compute per concept: window momentum (median / equal-weight mean, stated), breadth, short-vs-long spread, constituent count, and a new-concept flag. Rank concepts: strongest short-window momentum, biggest short−long acceleration (rotating in), biggest deceleration (rotating out), and highest breadth. Keep constituent counts and the membership snapshot date with every concept.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/concept-rotation/<scope>-<date>.md` (e.g. `reports/concept-rotation/market-20260706.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, a missing weighting/aggregation caveat, a missing membership-snapshot/overlap caveat, missing window/date labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 概念全景 | `get_concept_list` | How many concepts; which are newly formed. |
| 动量排名 | `get_concept_constituents` + `get_stock_daily` | Which concepts lead by window momentum. |
| 广度对照 | `get_stock_daily` (per constituent) | Is the move broad (many up) or narrow (a few runners). |
| 轮动信号 | short vs long window momentum | Which themes are accelerating in / decelerating out. |
| 新概念雷达 | `get_concept_list` (`date`) | Recently formed concepts (little history — flag). |
| 概念成分 | `get_concept_constituents` | The constituent list behind a concept (snapshot-dated). |

## Analysis Modes

- **Whole-market leaderboard**: rank all (or the most-populated) concepts by short-window momentum, show breadth beside momentum, and highlight the short−long acceleration/deceleration to read rotation. State the membership snapshot date and weighting.
- **Single-concept drill**: one concept's constituents (as-of date), its momentum & breadth over windows, top contributing names, and whether it is newly formed.
- **Rotation read**: concepts with short ≫ long momentum are "轮入/升温"; short ≪ long are "轮出/降温". Present the spread; do not call tops/bottoms.
- **New-concept caution**: newly-formed concepts (recent `get_concept_list` date) have little history — report them separately and do not rank their momentum against seasoned concepts as if comparable.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always state the aggregation.** Concept momentum is bottom-up and depends on the weighting (等权 median vs mean) and window; name both. There is no official concept price index.
- **Always state the membership snapshot date.** Constituents change over time; computing a past return on today's membership is lookahead. Pass an explicit `date` to `get_concept_constituents` and label it.
- **Flag concept overlap.** A stock sits in many concepts, so concept returns are correlated and non-additive; a hot leader lifts every concept it is in. Do not present concept leaders as independent exposures.
- Separate facts (constituent returns, counts, inclusion dates), derived metrics (concept momentum, breadth, short−long spread, ranks), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window instead of silently omitting a section. If a constituent's daily data is missing, drop it from that concept's aggregate and state how many were dropped.
- Keep the tone factual and structural. Use "题材升温/降温", "广度偏窄由少数个股拉动", "轮入/轮出" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for an automated concept-rotation monitor, create a task that runs on trading days after market close (e.g. after `18:00 Asia/Shanghai`). Make it idempotent: if `reports/concept-rotation/<scope>-<date>.md` exists, regenerate and overwrite. Skip non-trading days.

## Resource Guide

- `references/concept-rotation-playbook.md`: routing table, bottom-up aggregation formulas, weighting/breadth definitions, membership-snapshot rule, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, the aggregation/weighting caveat, the membership-snapshot/overlap caveat, window/date labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_concept_list` / `get_concept_constituents` / `get_stock_daily`, a date, and the momentum window.
- Concept momentum always names its weighting (等权 median/mean) and window; there is no official concept index.
- Constituent membership is snapshot-dated (explicit `date`), avoiding lookahead.
- Concept overlap / non-additivity is stated; leaders are not presented as independent exposures.
- Newly-formed concepts are flagged and not ranked as comparable to seasoned ones.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
