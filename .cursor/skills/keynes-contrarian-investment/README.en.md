# Keynesian Long-Term Expectations and Contrarian Investing Skill

[简体中文](README.md) | English

> This is a QuantSkills community project maintained by GitHub user `cikeqi`. It has not been independently audited, does not represent official QuantSkills certification, and makes no return or production-readiness guarantees.

This skill combines fundamental screening, market-expectation analysis, expectation-state timing, and value-trap checks. It does not predict tomorrow's price movement. Instead, it helps determine whether a company deserves further research, whether expectations appear too optimistic or pessimistic, and which observations would invalidate the thesis.

## Quick Start

```bash
python3.11 scripts/expectation_contrarian.py \
  --symbol 600519.SH \
  --out-json /tmp/keynes_600519.json \
  --out-md /tmp/keynes_600519.md
```

Run against an index universe:

```bash
python3.11 scripts/expectation_contrarian.py --universe csi300 --top-n 20
```

Probe the interfaces and fields available to the current PandaData account:

```bash
python3.11 scripts/expectation_contrarian.py --symbols 600519.SH --probe-only
```

Configure credentials through environment variables, or use `~/.pandadata/pandadata.env`:

```text
PANDA_USERNAME=...
PANDA_PASSWORD=...
```

Never commit real credentials or tokens to the repository.

## Research Logic

Long-term expectations are not precise forecasts. When formal consensus estimates are unavailable, the skill uses historical valuation, company earnings guidance, and market behavior as proxies. It first evaluates the durability of enterprise fundamentals, then analyzes price-implied expectations and margin of safety, and finally reviews positioning, catalysts, and falsification conditions.

A low valuation alone is not sufficient. A company whose earnings and cash flow are deteriorating together will not be selected merely because it looks inexpensive.

## Example Questions

Replace placeholders such as `[company/ticker]`, `[stock A]`, or `[universe]` with the actual target.

### Full single-stock analysis

```text
Use the Keynesian contrarian investing skill to analyze [company/ticker]. Evaluate whether the enterprise-investment thesis is valid, whether market expectations are overly optimistic or pessimistic, whether the current price offers a margin of safety, and provide research gates, catalysts, counter-evidence, and falsification conditions.
```

### Decide whether further research is warranted

```text
Is [company/ticker] genuinely inexpensive, or are its fundamentals deteriorating? Explain whether it is better suited for further research, staged observation, waiting, or avoidance, and provide supporting evidence and falsification conditions.
```

### Assess timing

```text
[Company/ticker] appears to be improving fundamentally. Is this an appropriate point for further research or staged observation? Analyze long-term expectations, market confidence, liquidity, valuation, and the conditions required for expectations to recover. Do not predict short-term price movements.
```

### Check for a value trap

```text
The valuation of [company/ticker] has fallen. Determine whether this reflects excessive pessimism or a value trap. Focus on revenue, net income, operating cash flow, the balance sheet, inventory cycle, industry competition, and audit risk, and distinguish cyclical problems from permanent impairment.
```

### Test for overextended expectations

```text
Analyze whether expectations for [company/ticker] are overextended. Does the current price imply excessive revenue growth, margins, or industry-cycle assumptions? List the three most fragile expectations.
```

### Look for excessive pessimism

```text
Determine whether the market is excessively pessimistic about [company/ticker]. Do not use the price decline itself as evidence; also examine valuation, revenue and earnings, cash flow, the balance sheet, the industry cycle, and evidence of operating improvement.
```

### Define catalysts and falsification conditions

```text
Build a contrarian-investment tracking sheet for [company/ticker]. List the most important fundamental indicators for the next two quarters, signals of expectation repair, known catalysts, and measurable falsification conditions.
```

### Compare multiple stocks

```text
Use the skill to compare [stock A], [stock B], and [stock C]. Evaluate enterprise investment, fundamental durability, consensus proxies, valuation margin of safety, catalysts, and falsification conditions, and distinguish the best company from the stock with the best current risk/reward profile.
```

### Review a portfolio

```text
Run a Keynesian expectation-state review on [holding A], [holding B], and [holding C]. For each stock, report PASS/CAUTION/FAIL, fundamental durability, expectation state, margin of safety, catalysts, and falsification conditions.
```

### Screen a universe

```text
From [CSI 300/CSI 500/CSI 1000/custom universe], identify companies with low market expectations whose fundamentals have not deteriorated in parallel. Do not rank only by P/E; examine cash flow, the balance sheet, margin of safety, catalysts, and value-trap risk.
```

### Historical point-in-time review

```text
Using only information disclosed by [analysis date], analyze [company/ticker] with this skill. Do not use financial reports released after that date. State what could have been concluded at the time, what was unknowable, and which conditions would have falsified the thesis.
```

### Generate a decision card

```text
Create a decision card for [company/ticker] covering enterprise-investment validity, expectation state, price-implied expectations, margin of safety, value-trap veto gates, catalysts, counter-evidence, falsification conditions, PASS/CAUTION/FAIL, and whether the company is better suited for research, staged observation, waiting, or avoidance.
```

## Unsupported Requests

This skill is not intended to answer questions such as:

- Will the stock hit the daily limit tomorrow?
- What will next week's highest price be?
- Which price is guaranteed to be the bottom?
- When will the stock definitely double?
- Which stock guarantees a profit, or what should be bought or sold automatically?

Reframe short-term questions as:

> Are expectations already extreme? Do the fundamentals justify further research? Does the current price offer a margin of safety? What evidence would invalidate the thesis?

## Output

- JSON: indicators, formulas, states, dates, scores, veto gates, proxy limitations, and provenance.
- Markdown: a Chinese-language research report.
- N/A: retained with an explanation when an interface is empty, unsupported, or returns an error.

Run tests with:

```bash
python3.11 -m pytest tests -q
```

## Data Sources, Assumptions, and Limitations

- Data source: PandaData only; see `references/` for interfaces, fields, and source boundaries.
- Key assumption: historical valuation, earnings guidance, and market behavior serve as consensus proxies when formal consensus data is unavailable.
- Known limitations: proxy indicators may be delayed or misleading; missing and unsupported values remain N/A rather than being replaced with zero.
- Risk boundary: outputs are for research and educational use only and are not investment advice, return guarantees, or automated trading instructions.

## Maintenance and License

- Maintainer: GitHub user `cikeqi`
- Repository: `quantskills/skill-keynes-contrarian-investment`
- License: [GNU GPL v3.0 only](LICENSE) (`GPL-3.0-only`)
