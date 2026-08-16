# Source Boundary

This skill reads **public** overseas/global macro data plus what the user provides. It never
ships or requires private credentials of its own; any Pandadata access goes through the
`pandadata-api` skill, which owns its own credentials.

Allowed sources:

- Public FRED / central-bank series (`DGS2`, `DGS10`, `T10Y2Y`, `DFII10`, `DTWEXBGS`, and
  equivalents)
- Public central-bank policy pages (Fed / ECB / BoJ / BoE) — rate level and stance, as facts
- Public FX references (ECB euro reference rates, public exchange-rate hosts)
- Pandadata `get_macro_gb` (delegated to `pandadata-api`)
- User-provided exports, notes, or watchlists

Not allowed unless the user has rights and explicitly provides them:

- Paywalled or subscription-only market data feeds
- Private or member-only research
- Any credential, token, or private dataset committed into this repo
