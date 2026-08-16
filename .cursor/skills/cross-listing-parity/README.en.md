# Cross Listing Parity

[简体中文](README.md) | **English**

> Community status: Draft · Creator/Maintainer: [`abgyjaguo`](https://github.com/abgyjaguo)

`cross-listing-parity` is a QuantSkills skill for A/H premium and China ADR parity monitoring. It helps agents produce factual cross-market reports with clear data dates, FX rates, share ratios, mapping versions, and limitation notes.

Maintainer: `abgyjaguo`. This skill is for research and educational workflows only and does not provide personalized investment advice.

## Use Cases

- Produce an A/H premium snapshot.
- Monitor China ADR discount or premium versus Hong Kong or A-share references.
- Flag unusual parity expansion or convergence.
- Maintain A/H and ADR pair mapping files.
- Document USD/HKD/CNY conversion assumptions.

## Data Interfaces

Pandadata method names, parameter names, and fields must be checked against `skills/pandadata-api/references/api-docs.md`. This skill uses these documented methods:

| Need | Method |
| --- | --- |
| A-share daily prices | `get_stock_daily` |
| A-share tradable list | `get_trade_list` |
| Hong Kong daily prices | `get_hk_daily` |
| U.S. ADR daily prices | `get_us_daily` |
| Hong Kong security details | `get_hk_detail` |
| U.S. security details | `get_us_detail` |

USD/HKD/CNY FX rates are required. If no verified Pandadata FX interface is available in the user environment, the user must provide the rates, and the report must state the source and date.

## Mapping Files

The built-in pair files live under `references/pairs/`:

- `a-h-pairs.csv`
- `adr-pairs.csv`

Users may extend the files, but they must keep the headers and the `ratio` field. The ratio should be checked against company disclosures, ADR depositary ratios, splits, and listing status.

## Report Requirements

Reports should be written in Chinese unless the user requests otherwise. They must include absolute dates, data source notes, market data dates, T+1 or snapshot labels, FX assumptions, mapping version notes, and a final non-advice disclaimer.

Required sections:

- Summary
- A/H premium
- ADR parity
- Anomaly, extreme, or convergence notes
- Data notes
- Disclaimer

Historical percentiles should only be reported when the user provides a rolling dataset or the agent has a validated local cache. The first version defaults to a same-day snapshot.

## Validation

Run the bundled validator after writing a report:

```bash
python scripts/validate_report.py path/to/report.md
```

The validator checks structure and mandatory disclosures. It does not verify calculations.

## Runtime Compatibility

- Codex uses the root `SKILL.md` and `agents/openai.yaml`.
- Cursor uses the root `SKILL.md` and `agents/cursor-rule.mdc`.
- Claude Code, Hermes, and OpenClaw read the root `SKILL.md`; use `agents/portable-loader.md` when native discovery is unavailable.

## License

This project is licensed under the GNU General Public License v3.0, SPDX `GPL-3.0-only`.
