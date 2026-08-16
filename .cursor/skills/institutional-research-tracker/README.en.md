[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

# 🔍 Institutional Research Tracker Skill

> An A-share **institutional-research (investor-relations) activity monitor**: rank the **most-visited companies** by research-event count, measure **distinct-institution breadth**, classify **participant institution types** from source text, roll activity up **by industry**, and build a **single-name research timeline** — for the whole market over a window or one company. Every figure is traced to `get_investor_activity` and an activity date.

## What it is

`institutional-research-tracker` is an **Agent Skill** that scans A-share `get_investor_activity` around **research events** and answers "**which companies are researched most, how many institutions participate, of what type, and which industries draw the most research**".

`get_investor_activity` returns **one row per research event**, and fields are often sparse (the sample returns `participant=None`, `institute=None`). The skill treats None as 未披露 (undisclosed) and **never fabricates names**; it reports **frequency** (event count) and **breadth** (distinct institutions) as **separate** metrics; and it classifies institution type only from **verbatim** `institute` / `investor_or_analyst_detail` text.

> **Being researched is attention — not a buy signal, not an endorsement.** Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 🔍 **institutional-research-tracker** (this) | **Institutional attention / research heat** (who visited) | Research-heat ranking, most-researched companies, one name's research timeline |
| 🧠 `smart-money-profiler` | 龙虎榜 seat identity, northbound behavior, capital consensus (money that actually **traded**) | Who is buying/selling (researched ≠ bought) |
| 📅 `earnings-season-tracker` / 📈 `market-daily-review` | Earnings / daily whole-market | Different event families; research-hot names can cross-check |
| 🩺 `a-share-stock-dossier` | Single-name deep due diligence | Full company dossier |

## Research activity model (read before analysis)

- **Frequency ≠ breadth** — "researched 12 times" (event count) and "12 distinct institutions" are different metrics; report both.
- **Institution type** — classify only from verbatim `institute` / `investor_or_analyst_detail` (公募/券商/保险/私募/外资); no match or None → 未披露.
- **Field sparsity** — report the undisclosed rate; compute breadth on the disclosed subset only; never impute a name.

## Report sections × interfaces

| Section | Methods | Answers |
|---|---|---|
| Activity overview | `get_investor_activity` | Research events in window; distinct companies visited |
| Heat ranking | `get_investor_activity` (count by `symbol`) | Most-researched companies (frequency) |
| Institution breadth | `get_investor_activity` (distinct `institute`) | Companies drawing the most distinct institutions |
| Type mix | `get_investor_activity` (`institute`, detail) | 公募/券商/保险/私募/外资 mix from source text |
| Industry distribution | `get_stock_industry` + above | Which industries are researched most |
| Single-name timeline | `get_investor_activity` (one `symbol`) | One company's research cadence and participants |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api                   ~/.claude/skills/pandadata-api
cp -r skill-institutional-research-tracker  ~/.claude/skills/institutional-research-tracker
```

Then ask, e.g. "scan the last 30 days of A-share institutional research with a heat ranking and type mix" or "who researched 000001.SZ recently — give me a timeline".

## Core constraints

- Verify the `get_investor_activity` contract via `pandadata-api` first.
- Report frequency (event count) and breadth (distinct institutions) as separate metrics.
- Classify institution type from verbatim source text only; ambiguous / None → 未披露; no fabricated names.
- Surface field sparsity with a rate; compute breadth on the disclosed subset only.
- Frame being researched as attention, not a buy signal or endorsement.
- Report empty results explicitly; a scan is a snapshot — label the window and date.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
