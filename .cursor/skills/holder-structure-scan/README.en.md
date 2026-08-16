[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 🧩 Holder Structure Scan Skill

> An A-share **shareholder-structure & chip-concentration scan**: track the **holder-count (户数) trend** and **average holding per account**, the **top-holder concentration** (前十大合计占比, flow vs total caliber, never mixed), and the **free-float share** (自由流通占比), to judge whether chips are **concentrating** or **dispersing** across disclosure periods — for a single name or a small watchlist. Every figure carries its source interface, disclosure period, and caliber, with the disclosure-frequency/lag caveat stated.

## What it is

`holder-structure-scan` is an **Agent Skill** centered on **registered ownership structure**, answering "**are chips concentrating or dispersing, is holder count rising or falling, how tightly do the top holders hold, and how small is the actually-tradable free float**".

Three interfaces, three angles — all are **periodic disclosure (usually quarterly) and lag the period-end**, not daily: `get_holder_count` (户数 / 户均持股 — fewer holders + rising average usually = concentrating); `get_top_holders` (top-N concentration, `flow` vs `total` caliber, **never mixed**); `get_share_float` (`free_circulation/total` free-float share — a smaller float means the same flow moves price more). The signal is the **direction of change across periods**, not any single snapshot; a controlling/state-owned **locked** concentration is distinguished from tradable free-float concentration.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 🧩 **holder-structure-scan** (this) | **Registered structure / chip concentration** (multi-period trend) | Is this name concentrating, holder-count change, top-holder trend, free-float size |
| 🔎 `stock-screener` | Whole-market natural-language **filter** | Screen the market by a holder condition |
| 🧠 `smart-money-profiler` | 龙虎榜 / northbound / margin **daily trading seats** | Daily "smart money" board (this reads registered structure) |
| 🚨 `event-risk-alert` | Per-name **risk events** (unlocks/pledges/reductions) | Event-level alerts |
| 🩺 `a-share-stock-dossier` | Single-name full dossier (ownership is one sub-section) | Full company checkup |

## Shareholder-structure model (read before analysis)

- **Holder-count trend**: `holders` change + `avg_holders` direction, keyed on `end_date`.
- **Top-holder concentration**: Σ top-N `hold_percent_*`, **pick one caliber and label it** (flow `hold_percent_float` / total `hold_percent_total`), never mixed.
- **Free-float share**: `free_circulation / total`, denominator stated; smaller = more price-sensitive.
- **Direction read**: holders↓ + average↑ + top-N↑ ⇒ concentrating; reverse ⇒ dispersing; conflicting signals ⇒ stable/mixed (no forced verdict).

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Holder-count trend | `get_holder_count` | Rising/falling count; average-holding direction |
| Top-holder concentration | `get_top_holders` | Top-N combined ratio (caliber labeled) and its change |
| Free-float share | `get_share_float` | How large the tradable float is |
| Concentration direction | all three | Concentrating / dispersing / stable |
| Top-holder pledge/freeze | `get_top_holders` (`pledge`, `freeze`) | Pledge/freeze risk flag among top holders |
| Industry context (optional) | `get_stock_industry` | Peer context for a watchlist |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api         ~/.claude/skills/pandadata-api
cp -r skill-holder-structure-scan ~/.claude/skills/holder-structure-scan
```

Then ask, e.g. "over the last few periods, is 000001.SZ concentrating or dispersing — give me the holder-count trend and top-10 ratio" or "compare the top-holder concentration of these names under the flow caliber".

## Core constraints

- Verify the three interface contracts via `pandadata-api` first.
- Always label the top-holder caliber (flow `hold_percent_float` vs total `hold_percent_total`); never mix calibers in one comparison.
- Read trend across several periods keyed on `end_date`; state disclosure frequency and lag; a single snapshot is not a live position.
- Distinguish locked (controlling/state-owned/limited-sale) concentration from free-float concentration.
- Surface top-holder pledge/freeze as a risk flag.
- Report empty results explicitly; label the period.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
