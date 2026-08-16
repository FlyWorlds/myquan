[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 🔥 Concept Rotation Monitor Skill

> An A-share **concept/theme (概念题材) rotation monitor**: aggregate each concept's **constituent daily returns** (via `get_stock_daily`) into concept-level **momentum** and **breadth** rankings, detect **newly-formed concepts**, and compare **short-vs-long-window momentum** to see which themes are **heating up** or **cooling down** — for a whole-market leaderboard or a single-concept drill. Every figure carries its source interface, constituent-membership snapshot date, and aggregation caliber.

## What it is

`concept-rotation-monitor` is an **Agent Skill** centered on **concepts/themes**, answering "**which themes are heating up, is the move broad or led by a few names, which are rotating out, and are new concepts emerging**".

**There is no official concept price index** — the concept signal is always built **bottom-up** from constituent daily returns: `get_concept_list` (concept universe + new-concept detection by inclusion date) → `get_concept_constituents` (membership **as of a snapshot date**, avoiding lookahead from today's membership) → `get_stock_daily` (constituent window returns). **Momentum** = equal-weight aggregate of constituent returns (default **median** for robustness, or equal-weight mean — caliber and window stated); **breadth** = share of constituents up (broad move vs a few runners); **rotation signal** = short-window minus long-window momentum (short ≫ long = heating/rotating in, short ≪ long = cooling/rotating out). A stock sits in many concepts, so concept momenta are correlated and **non-additive**.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 🔥 **concept-rotation-monitor** (this) | **Concept/theme rotation** (multi-window momentum time-series) | Which themes are heating up, concept momentum ranking, rotate-in/out, new concepts |
| 📈 `market-daily-review` | Daily whole-market review (one hot-concepts section) | One-day end-of-day review |
| 🔎 `stock-screener` | Natural-language **stock filter** (concept as a condition) | Filter stocks inside a theme by fundamentals |
| 📊 `index-valuation-rotation` | Standard **industry/index** valuation percentile + industry momentum | Industry valuation thermometer (industry vs theme — complementary) |

## Concept-rotation model (read before analysis)

- **Momentum**: equal-weight median/mean of constituent window returns (default median), caliber and window stated; no official concept index.
- **Membership snapshot**: pass `date=` to `get_concept_constituents` to use period-correct membership, avoiding lookahead/survivorship.
- **Breadth**: share of constituents up; high momentum + low breadth = a few runners.
- **Rotation signal**: short-window (e.g. 5D) minus long-window (e.g. 20D) momentum.
- **Concept overlap**: a stock belongs to many concepts; momenta are correlated and non-additive; a hot leader lifts every concept it is in.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Concept landscape | `get_concept_list` | Concept count, constituent-count spread, new concepts |
| Momentum ranking | `get_concept_constituents` + `get_stock_daily` | Which concepts lead by window momentum |
| Breadth comparison | `get_stock_daily` (per constituent) | Broad move vs a few runners |
| Rotation signal | short vs long window momentum | Accelerating in / decelerating out |
| New-concept radar | `get_concept_list` (`date`) | Recently formed concepts (little history — flag) |
| Concept constituents | `get_concept_constituents` | The constituent list behind a concept (snapshot-dated) |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api            ~/.claude/skills/pandadata-api
cp -r skill-concept-rotation-monitor ~/.claude/skills/concept-rotation-monitor
```

Then ask, e.g. "which concept themes are heating up over the last 5 days — give me momentum ranking and breadth" or "show the short-minus-long rotation signal for the most-populated concepts".

## Core constraints

- Verify the three interface contracts via `pandadata-api` first.
- Build concept momentum bottom-up; name the weighting (equal-weight median/mean) and window; there is no official concept price index.
- Snapshot constituent membership with an explicit `date` — no lookahead on today's membership.
- Report breadth beside momentum; use the short−long spread for the rotation read.
- Flag concept overlap / non-additivity and newly-formed concepts.
- Report empty results / insufficient samples explicitly; label the window and snapshot date.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
