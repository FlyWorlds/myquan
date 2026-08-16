# A-Share Market Risk Radar

[简体中文](README.md) | English

> This is a QuantSkills community project maintained by GitHub user `cikeqi`. It has not been independently audited, does not represent official QuantSkills certification, and makes no return or production-readiness guarantees.

This skill monitors multidimensional risk in China's A-share market. It scans global macro conditions, margin financing, index valuation, market trends, capital flows, sector rotation, stock-specific events, and technical signals, then produces an explainable red, yellow, green, or unknown risk level.

The project is intended for risk monitoring and research. It does not predict guaranteed returns or replace investment decisions.

## Requirements

Install the Python dependencies:

```text
pandas
numpy
panda_data
```

Provide PandaData credentials through environment variables:

```bash
export PANDADATA_USERNAME="..."
export PANDADATA_PASSWORD="..."
```

Never commit real accounts, passwords, or tokens to code, reports, or this repository.

## Quick Start

Run a complete market scan:

```bash
python3 scripts/full_scan.py --out /tmp/a_share_market_risk.json
```

Add specified stocks to the complete scan:

```bash
python3 scripts/full_scan.py \
  --symbols 603501.SH 688808.SH \
  --out /tmp/a_share_market_risk.json
```

## Focused Scans

```bash
python3 scripts/global_macro.py
python3 scripts/market_radar.py
python3 scripts/capital_flows.py --symbols 603501.SH 688808.SH
python3 scripts/sector_rotation.py
python3 scripts/stock_risk.py 603501.SH
python3 scripts/tech_alert.py 603501.SH 688808.SH
python3 scripts/margin_scan.py --symbols 603501.SH 688808.SH
python3 scripts/unlock_calendar.py --symbols 603501.SH 688808.SH
python3 scripts/expectation_gap.py --symbols 603501.SH 688808.SH
```

## Example Questions

- Scan current A-share market risk and summarize the most important warnings.
- Is the current market high risk, cautionary, or relatively stable? Explain the evidence and data gaps.
- Check whether margin financing, northbound holdings, and market turnover show signs of fragility.
- Analyze current sector rotation, style shifts, and crowding risk.
- Check stock-specific event and technical risk for `603501.SH` and `688808.SH`.
- Identify stocks facing significant restricted-share unlock pressure over the next 30 days.
- Check whether valuation, earnings-expectation, and technical risks are converging for specified stocks.

## Risk Levels

- `RED`: multiple risk dimensions are aligned; reduce exposure and investigate further.
- `YELLOW`: some dimensions are abnormal; control exposure and continue monitoring.
- `GREEN`: no significant convergence is visible in currently covered dimensions; this does not mean future risk is absent.
- `UNKNOWN`: data is insufficient or an interface failed; never treat this as low risk.

## Repository Structure

- `SKILL.md`: triggers, workflow, and risk boundaries.
- `agents/`: runtime entry points for Codex, Cursor, Hermes, OpenClaw, and related environments.
- `scripts/full_scan.py`: complete market-risk scan.
- `scripts/global_macro.py`: global macro scan.
- `scripts/market_radar.py`: A-share market risk radar.
- `scripts/capital_flows.py`: capital-flow analysis.
- `scripts/sector_rotation.py`: sector-rotation analysis.
- `scripts/stock_risk.py`: stock-specific risk checks.
- `scripts/tech_alert.py`: technical risk alerts.
- `scripts/margin_scan.py`: margin-fragility scan.
- `scripts/unlock_calendar.py`: restricted-share unlock checks.
- `scripts/expectation_gap.py`: market-expectation-gap analysis.

## Data Sources, Assumptions, and Limitations

- Data source: quantitative conclusions use PandaData only.
- Key assumption: heuristic thresholds and risk signals can support monitoring, but they do not replace complete historical backtesting and out-of-sample validation.
- Known limitations: index returns are only a proxy for market pressure; interface permissions, update delays, and missing data may produce incomplete results or `UNKNOWN`.
- Risk boundary: outputs are for research and educational use only and are not investment advice, return guarantees, position instructions, or automated trading decisions.

## Maintenance and License

- Maintainer: GitHub user `cikeqi`
- Repository: `quantskills/skill-a-share-market-risk-radar`
- License: [GNU GPL v3.0 only](LICENSE) (`GPL-3.0-only`)
