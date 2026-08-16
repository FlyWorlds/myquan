# Data Sources — Public Venues & Symbol Map

All data used by this skill is **public web content**, fetched through the repository's
own web tooling (the agent's browser / fetch / search capability). There are **no API
keys, no paid feeds, and no Pandadata calls** — Pandadata has no overseas futures
coverage, so foreign contracts are read from the public venues below.

## Venues

| Venue | What it provides | Notes |
| --- | --- | --- |
| **CME / NYMEX / COMEX** (cmegroup.com) | Official settlement and product/curve pages for crude (WTI `CL`), natural gas (`NG`), gold (`GC`), silver (`SI`), COMEX copper (`HG`), RBOB (`RB`), heating oil (`HO`) | Settlement prices are the authoritative end-of-session marks; deferred months may be thin |
| **ICE** (ice.com) | Brent (`B`/`BZ`), gasoil, and other ICE-listed energy contracts | Separate exchange; own settlement schedule |
| **LME** (lme.com) | Base-metal prices and **warehouse stock** reports (copper, aluminium, …) | Metals quoted in USD/tonne; distinct from COMEX USD/lb |
| **Yahoo Finance** (finance.yahoo.com) | Continuous front-month futures symbols and, where listed, individual contract months | Easy multi-symbol pulls; `=F` symbols are **continuous** (see pitfall) |
| **stooq** (stooq.com) | Public futures quotes | Cross-check / fallback source |
| **EIA** (eia.gov) | Weekly petroleum status: crude, gasoline, distillate stocks | Public inventory context for oil products |

## Commodity → symbol map (Yahoo Finance front-month)

| Commodity | Symbol | Quote unit | Primary venue |
| --- | --- | --- | --- |
| WTI crude | `CL=F` | USD / barrel | NYMEX |
| Brent crude | `BZ=F` | USD / barrel | ICE |
| Natural gas | `NG=F` | USD / MMBtu | NYMEX |
| RBOB gasoline | `RB=F` | USD / gallon | NYMEX |
| Heating oil | `HO=F` | USD / gallon | NYMEX |
| Gold | `GC=F` | USD / troy oz | COMEX |
| Silver | `SI=F` | USD / troy oz | COMEX |
| Copper | `HG=F` | USD / pound | COMEX |
| LME copper | (LME page) | USD / tonne | LME |

For discrete contract months, Yahoo and the exchange product pages list month-coded
symbols (month letter + year, e.g. `CLU26` for Sep-2026 WTI). Prefer discrete listed
months for building a *current* curve; use the continuous `=F` symbol only for context
or when discrete months are unavailable.

## Settlement vs last-trade

- **Settlement** — the exchange's official daily closing mark. Prefer it for curve
  work; it is consistent across months and is what the exchange publishes on its
  settlement page.
- **Last-trade** — the most recent transaction price. Use only when settlement is
  unavailable (e.g. intraday, or a thin deferred month with no settlement yet). Label
  every price with which one it is and its as-of date.

## Unit & currency cautions

- Energy: WTI/Brent in **USD/bbl**; gas in **USD/MMBtu**; RBOB/heating oil in
  **USD/gal** (×42 to reach USD/bbl for crack proxies).
- Metals: gold/silver in **USD/oz**; COMEX copper in **USD/lb**; **LME** metals in
  **USD/tonne** — do not compare COMEX and LME copper without converting.
- Always show the conversion factor when you convert, and never mix units within one
  spread or curve.

## Continuous-contract caveat

Yahoo `=F` symbols are **continuous front-month** series: at each roll the level steps
by the calendar spread, so spliced history does **not** represent a single contract's
price path. State the roll convention and treat spliced levels as approximate. See
`references/methodology.md` §9 for the full pitfall list.

## Access boundary

Read only public pages (see `references/source_boundary.md`). Do not scrape paywalled
or member-only data, do not submit credentials, and cite the venue and as-of date for
every number that reaches the report.
