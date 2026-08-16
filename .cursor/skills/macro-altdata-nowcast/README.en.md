[简体中文](README.md) | **English**

# 📡 Macro Alt-Data Nowcast Skill

> **Alternative-data (特色数据) high-frequency industry prosperity nowcasting**: first resolve opaque indicator codes into **name/unit/frequency/source** via `get_macro_detail`, then pull ten alt-data families — **e-commerce · pharma · energy-chemical · autos · appliances · offline retail · hiring · real estate · electronics · new-energy** — compute **YoY/MoM** and trend, and read the **lead over official statistics**, for a single-sector nowcast or a cross-sector prosperity dashboard. Every value carries its indicator code, source interface, and data period; alt data is a **timely sample**, not an official statistic.

> Project status: QUANTSKILLS Community Project (Draft). Created and maintained by [abgyjaguo](https://github.com/abgyjaguo).

## What it is

`macro-altdata-nowcast` is an **Agent Skill** that reads Pandadata's 宏观特色数据 (alternative, high-frequency) series to answer "**which industries are heating up, which are cooling, and do these high-frequency signals lead the official prints**".

The alt series are **minimal and opaque** — only `symbol` (indicator code, e.g. `EC0252098`), `period_date`, `data_value`. **A raw code is meaningless**, so step one is always: **call `get_macro_detail(category=...)` first** to resolve each code to `name/unit/frequency/stat_type/info_source/coverage`, then pull the matching `get_macro_<x>`. `stat_type` governs whether YoY can be computed (**an already-YoY series is not double-differenced**). Alt data is a **timely sample** (one platform's e-commerce GMV, one job board's postings) used to **nowcast** direction and turning points — **not** the official statistic, and it carries sample/coverage bias.

> Data contracts always come from the sibling skill [`pandadata-api`](https://github.com/quantskills/skill-pandadata-api).

## Boundaries (avoid overlap)

| Skill | View | When |
|---|---|---|
| 📡 **macro-altdata-nowcast** (this) | Macro **alternative-data** high-frequency industry nowcast | E-commerce/hiring/real-estate high-frequency reads, which sector is heating, does alt data lead official |
| 🌐 `macro-monitor` | **Official** macro indicators (GDP/CPI/PPI/PMI + standard industry series) | Official macro/industry data (this skill is alt data only) |
| 🌡️ `index-valuation-rotation` | Index PE/PB percentile + industry **price** momentum | Valuation / price rotation (prosperity ≠ price) |
| 🏭 `futures-industrial-profit` | Futures **spot quotes / processing margins** | Commodity-chain data |

## Alt-data model (read before analysis)

- **Resolve the dictionary first**: any code/value must be resolved via `get_macro_detail` to name/unit/frequency before reporting — never surface a raw code.
- **Respect `stat_type`**: an already-YoY/cumulative series is not double-differenced; read it as published.
- **Alt data = sample**: timely but coverage-biased, nowcasts direction/turning points, not an official statistic — state this each time.
- **Frequency varies**: read daily/weekly/monthly from `frequency`; the last 1–2 points are provisional.

## Sectors × interfaces

| Category | Method | Sector |
|---|---|---|
| EC | `get_macro_ec` | e-commerce |
| MD | `get_macro_md` | pharma |
| EH | `get_macro_eh` | energy-chemical |
| AD | `get_macro_ad` | autos |
| HA | `get_macro_ha` | appliances |
| OF | `get_macro_of` | offline retail |
| RB | `get_macro_rb` | hiring |
| RE | `get_macro_re` | real estate |
| ED | `get_macro_ed` | electronics |
| EP | `get_macro_ep` | new-energy |
| — | `get_macro_detail` | indicator dictionary (**call first**) |

## Quick start

```bash
# Claude Code (global)
cp -r skill-pandadata-api          ~/.claude/skills/pandadata-api
cp -r skill-macro-altdata-nowcast  ~/.claude/skills/macro-altdata-nowcast

# Codex (global)
mkdir -p ~/.agents/skills
cp -r skill-pandadata-api          ~/.agents/skills/pandadata-api
cp -r skill-macro-altdata-nowcast  ~/.agents/skills/macro-altdata-nowcast

# Cursor (project)
mkdir -p .cursor/skills
cp -r skill-pandadata-api          .cursor/skills/pandadata-api
cp -r skill-macro-altdata-nowcast  .cursor/skills/macro-altdata-nowcast

# Hermes (global)
mkdir -p ~/.hermes/skills
cp -r skill-pandadata-api          ~/.hermes/skills/pandadata-api
cp -r skill-macro-altdata-nowcast  ~/.hermes/skills/macro-altdata-nowcast

# OpenClaw (global)
mkdir -p ~/.openclaw/skills
cp -r skill-pandadata-api          ~/.openclaw/skills/pandadata-api
cp -r skill-macro-altdata-nowcast  ~/.openclaw/skills/macro-altdata-nowcast
```

Then ask, e.g. "how does the real-estate high-frequency data look, with YoY/MoM and trend?" or "make a cross-sector prosperity comparison for e-commerce, hiring, and autos".

## Core constraints

- Verify the `get_macro_detail` / `get_macro_*` contracts via `pandadata-api` first.
- Call `get_macro_detail(category=<X>)` first to resolve opaque codes (EC/MD/EH/AD/HA/OF/RB/RE/ED/EP) to name/unit/frequency/stat_type/source; never report a raw code or bare `data_value`.
- Respect `stat_type` (do not double-difference already-YoY series); mark frequency and window; flag the provisional tail.
- Label the data as a timely **sample** that nowcasts (≠ official statistic); state the prosperity-scoring convention.
- Frame any lead/lag vs official as an observation; hand official series to `macro-monitor`.
- Report empty dictionaries/series explicitly.

## Disclaimer

This report is generated from public data and rule-based analysis, for research reference only, and does not constitute any investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Maintainer: `abgyjaguo`.
