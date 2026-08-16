# A-Share Oversold Rebound

[简体中文](README.md) | English

> This is a QuantSkills community project maintained by GitHub user `cikeqi`. It has not been independently audited, does not represent official QuantSkills certification, and makes no return or production-readiness guarantees.

This standalone skill studies short-term oversold-rebound conditions in China's A-share market using PandaData only. It first evaluates whether the broader market supports a rebound over the next 1–10 trading days, then screens constituents of the CSI 300, CSI 500, or CSI 1000. The default universe is the CSI 300.

## Files

- `SKILL.md`: trigger description, workflow, and hard rules.
- `scripts/oversold_rebound.py`: main program.
- `scripts/pandadata_source.py`: PandaData authentication, calls, and provenance.
- `scripts/indicators.py`: RSI, MACD, Bollinger Band, ATR, price, and volume indicators.
- `scripts/scoring.py`: five-dimension market scoring, stage classification, and candidate scoring.
- `references/`: methodology and data contract.
- `tests/`: checks for point-in-time integrity, N/A weighting, evidence levels, and veto conditions.

## Credentials

Set environment variables:

```bash
export PANDA_USERNAME='your-account'
export PANDA_PASSWORD='your-password'
```

Or configure `~/.pandadata/pandadata.env`:

```text
PANDA_USERNAME=your-account
PANDA_PASSWORD=your-password
```

Never commit real accounts, passwords, or tokens to this repository.

## Quick Start

Probe available interfaces:

```bash
python3.11 scripts/oversold_rebound.py --probe-only
```

Evaluate the market and screen CSI 300 constituents:

```bash
python3.11 scripts/oversold_rebound.py --universe csi300 --top-n 20
```

Switch the universe:

```bash
python3.11 scripts/oversold_rebound.py --universe csi500 --top-n 20
python3.11 scripts/oversold_rebound.py --universe csi1000 --top-n 20
```

The script retrieves the latest index-constituent snapshot available on or before the analysis date through PandaData `get_index_weights`. The universes therefore contain approximately 300, 500, or 1,000 stocks rather than only the example symbols.

Override the universe with specified stocks:

```bash
python3.11 scripts/oversold_rebound.py \
  --symbols 000001.SZ 600519.SH 300750.SZ \
  --top-n 10
```

Run a point-in-time analysis:

```bash
python3.11 scripts/oversold_rebound.py \
  --as-of 20250115 \
  --universe csi500
```

Default outputs:

- `/tmp/oversold_rebound.json`
- `/tmp/oversold_rebound.md`

## Example Questions

- Determine whether the market is near a sentiment extreme and identify 20 oversold-rebound candidates from the CSI 300.
- Screen the CSI 500 for deeply sold-off stocks that are beginning to stabilize.
- Check whether the CSI 1000 currently offers rebound conditions and list the 30 highest-scoring candidates.
- After a major selloff, evaluate the market stage before screening the CSI 300.
- As of January 15, 2025, scan the CSI 1000 using only information available at that time.
- Evaluate short-term rebound conditions for `000001.SZ`, `600519.SH`, and `300750.SZ` only.

## Market Dimensions and Stages

The market assessment covers five dimensions:

1. Market sentiment and breadth.
2. Broad-market turnover and fund-flow proxies.
3. Financing, northbound holdings, and institutional activity.
4. Index drawdown, technical repair, volume exhaustion, and stabilization patterns.
5. Explicit state-linked shareholder evidence, with ETF or index behavior treated only as proxy evidence.

The result must use one of five stages:

- `Panic acceleration`: breadth, price, and volume conditions are still deteriorating.
- `Sentiment extreme`: severe oversold conditions exist without enough stabilization evidence.
- `Stabilization attempt`: losses are narrowing, selling pressure is fading, or bottoming patterns are emerging.
- `Rebound confirmation`: at least two of breadth, broad-index trend, and fund conditions improve together.
- `Rebound exhaustion`: the rebound is becoming overheated or showing price-volume and breadth divergence.

## Candidate Output

Each candidate includes:

- Total score from 0–100 and data-coverage ratio.
- Scores for oversold intensity, selling-pressure exhaustion, stabilization confirmation, fund recovery, and sector alignment.
- Observation window of `1–3`, `3–5`, or `5–10` trading days.
- Selection evidence, counter-evidence, and invalidation conditions.
- Market-gate status and explicit rejection reasons where applicable.

## Tests

```bash
python3.11 -m unittest discover -s tests -v
```

## Data Sources, Assumptions, and Limitations

- Data source: PandaData only; see `references/` for interfaces, fields, and calculation boundaries.
- Key assumptions: close-based market and technical signals can be observed no earlier than the next trading day; index constituents use the latest snapshot available on or before the analysis date.
- Known limitations: technical oversold conditions do not guarantee a rebound; ETF, index, and turnover behavior are proxy evidence only; missing indicators remain N/A and scores are normalized across available weights.
- Risk boundary: outputs are for research and educational use only and are not investment advice, return guarantees, stock recommendations, or automated trading instructions.

## Maintenance and License

- Maintainer: GitHub user `cikeqi`
- Repository: `quantskills/skill-oversold-rebound`
- License: [GNU GPL v3.0 only](LICENSE) (`GPL-3.0-only`)
