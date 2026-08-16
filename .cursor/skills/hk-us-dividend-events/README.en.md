# HK-US Dividend Events Skill

[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

`hk-us-dividend-events` is an Agent Skill for generating Hong Kong and U.S. stock dividend event reports from Pandadata. It covers upcoming ex-dividend calendars, recent payouts, TTM dividend yield ranking, currency buckets, and simplified DRIP illustrations.

Maintainer: abgyjaguo  
Project type: QuantSkills skill  
License: GPL-3.0-only

## What It Does

- Builds HK or U.S. Dividend calendar reports for upcoming 30/60/90 day ex-dividend events.
- Summarizes recent payout records with publish date, execution date, per-share amount, and currency.
- Computes trailing 12 month cash dividends and ranks TTM dividend yield by currency bucket.
- Shows a simplified DRIP reinvestment example, excluding tax, fees, minimum lot size, and FX effects.
- Degrades gracefully when data calls fail or fields are missing, with clear notes in the data section.

## Data Interfaces

This skill only uses methods documented in Pandadata:

| Market | Dividend events | Price data | Details |
| --- | --- | --- | --- |
| HK | `get_stock_dividend_event` | `get_hk_daily` | `get_hk_detail` |
| U.S. | `get_stock_dividend_activity` | `get_us_daily` | `get_us_detail` |

Parameter and field names must follow `pandadata-api/references/api-docs.md`. Use the singular `symbol` parameter.

## Report Layout

Reports should include:

1. Title: HK/U.S. stock + dividend/Dividend + event/Calendar
2. Summary
3. Upcoming ex-dividend events
4. Recent payouts
5. High dividend/Yield ranking
6. DRIP
7. Data notes
8. Disclaimer

## Example Prompts

```text
Use hk-us-dividend-events to generate a HK/U.S. dividend calendar for the 60 days starting 2026-07-07.
```

```text
Review AAPL and 0005.HK payouts over the trailing 12 months and add a simplified DRIP illustration.
```

## Validation

After writing a report, run:

```bash
python scripts/validate_report.py path/to/report.md
```

The validator checks required sections, data source, data date, T+1/snapshot notes, and the investment-advice disclaimer.

## Runtime Compatibility

- Codex uses the root `SKILL.md` and `agents/openai.yaml`.
- Cursor uses the root `SKILL.md` and `agents/cursor-rule.mdc`.
- Claude Code, Hermes, and OpenClaw read the root `SKILL.md`; use `agents/portable-loader.md` when native discovery is unavailable.

## Limits

- The skill does not provide trading instructions or personalized investment advice.
- TTM uses trailing 12 month cash dividend sums only, without extrapolation.
- HKD/USD/CNY and other currencies are shown in separate buckets.
- DRIP is an arithmetic illustration only and excludes tax, fees, minimum lot size, FX conversion, and account rules.

## License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
