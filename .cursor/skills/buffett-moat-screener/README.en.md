# Buffett Moat Screener Skill

[简体中文](README.md) | **English**

> A reproducible A-share and U.S. equity research workflow inspired by long-term, quality-first investing. It produces traceable research rankings, portfolio-review states, annual holding records, and retrospective diagnostics from Panda Data.

**Project status:** QuantSkills Community Project. This repository is not official, certified, verified, endorsed, or guaranteed by QuantSkills.

**Creator / Maintainer:** [`dijia702`](https://github.com/dijia702)

## Overview

`skill-buffett-moat-screener` is a hybrid research skill. Its Q44 BUILD component performs the calculations and materializes reusable results, while the repository defines the research method, review workflow, evidence boundaries, and runtime adapters.

It supports four related tasks:

1. **Research ranking:** apply continuous quality and valuation scores to a point-in-time universe and label companies as research candidates, watchlist items, manual-review cases, or rejected observations.
2. **Portfolio review:** maintain holdings, cash weights, and evidence-based transition reasons. A healthy existing holding is not removed only because its annual rank falls or its valuation rises.
3. **Retrospective diagnostics:** keep strict point-in-time CSI 300 evidence separate from fixed-roster A-share and U.S. diagnostics.
4. **Reusable delivery:** produce structured Parquet and JSON data plus a self-contained HTML report with holdings, changes, and annual holding records.

The project does not create brokerage orders. Its outputs are research artifacts, not personalized investment advice or promises of future performance.

## Data Source and Method

Live calculations use authorized Panda Data access for financial statements, prices, index constituents, industries, audit opinions, and trading calendars. Callers may also pass documented structured Python data through the stable BUILD interface.

The standard A-share score uses continuous anchors rather than mandatory cutoffs:

| Dimension | Weight | Default anchors |
|---|---:|---|
| Return on capital | 30% | Ten-year average ROE: 5% = 0, 18% = 100 |
| Moat | 25% | Five-year gross margin: 10% = 0, 50% = 100, with a volatility penalty |
| Asset intensity | 15% | Five-year CapEx / attributable net profit: 10% = 100, 60% = 0 |
| Operating resilience | 15% | Five-year operating margin: 2% = 0, 25% = 100 |
| Valuation discipline | 15% | Current PE: 10x = 100, 40x = 0 |

Missing observations do not receive an automatic neutral score. Banks report gross margin as `N/A`; their score is redistributed across applicable ROE, ROA, ROA-floor/PB, and PE evidence.

## Evidence Scope

| Period | Research universe | Limitation |
|---|---|---|
| 2010-2016 | Fixed 18-company A-share roster | Survivor-biased diagnostic; not historical point-in-time CSI 300 selection |
| 2017-2026 | Point-in-time CSI 300 constituents | Uses constituents visible on each signal date; financial coverage may still vary |
| 2015-2026 | Fixed U.S. research roster | Not a historical S&P 500 or Berkshire portfolio reconstruction; price returns exclude cash dividends |

Historical results are quantitative retrospective diagnostics. They do not demonstrate future performance or strategy safety.

## Quick Start

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the offline demo without credentials, network access, or order creation:

```bash
python scripts/demo.py --open
```

The demo writes:

```text
output/
├── demo_result.json
└── demo_report.html
```

Call the stable BUILD entry point:

```python
from scripts.build import run

result = run(
    {"as_of_date": "20260724", "index_symbol": "000300.SH"},
    config={"selection_mode": "soft", "soft_review_top": 50},
)
```

The production result is stored in `生产产物/数据库.parquet`. See [SKILL.md](SKILL.md) for the complete input/output contract and [references/api_guide.md](references/api_guide.md) for Panda Data field mappings.

## Runtime Adapters

| Runtime | Entry point |
|---|---|
| Claude Code | Load the repository root `SKILL.md` as a skill folder |
| Codex / OpenAI-compatible agents | `agents/openai.yaml` |
| Cursor | `agents/cursor-rule.mdc` |
| Hermes | `agents/portable-loader.md` |
| OpenClaw | `agents/portable-loader.md` |

All adapters delegate to the same root `SKILL.md`; they do not duplicate scoring or trading logic.

## Credentials and Security

Live mode reads `PANDA_DATA_USERNAME`, `PANDA_DATA_PASSWORD`, and optional `PANDA_DATA_BASE_URL` from environment variables. Never commit credentials, API keys, tokens, cookies, private datasets, or generated logs containing sensitive values.

```powershell
$env:PANDA_DATA_USERNAME = "your-account"
$env:PANDA_DATA_PASSWORD = "your-password"
python scripts/demo.py --live --as-of-date 20260724
```

## Assumptions and Known Limitations

- Point-in-time CSI 300 coverage is only claimed from the first date verified through the available Panda Data interface.
- Fixed rosters have survivor and selection bias and cannot represent historical index membership.
- Financial publication dates, missing fields, suspensions, liquidity, and market-status coverage can reduce usable observations.
- Backtests use documented next-period execution and transaction-cost assumptions; they are not live trading records.
- The U.S. diagnostic uses a fixed research roster and price returns without cash dividends when dividend data is unavailable.
- The skill never generates orders and should not be used as a substitute for independent due diligence or professional advice.

## Validation

```bash
python scripts/test.py
python scripts/demo.py
```

Contributions should preserve point-in-time integrity, stable BUILD interfaces, credential isolation, and the research-only boundary. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the GNU General Public License v3.0, SPDX identifier `GPL-3.0-only`. See [LICENSE](LICENSE).
