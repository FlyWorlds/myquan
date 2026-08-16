# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named hk-us-consensus-radar at:
<HK_US_CONSENSUS_RADAR_SKILL_ROOT>

When the user asks for Hong Kong or US analyst consensus, sell-side ratings, rating distribution, target-price upside, long-term growth expectations, consensus revisions, buy/sell recommendation counts, or a Hong Kong / US analyst-consensus report:
1. Read <HK_US_CONSENSUS_RADAR_SKILL_ROOT>/SKILL.md.
2. For routing, metric definitions, market-split and suffix notes, report format, empty-data handling, or QA, read <HK_US_CONSENSUS_RADAR_SKILL_ROOT>/references/consensus-playbook.md.
3. Validate generated reports with <HK_US_CONSENSUS_RADAR_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact method parameters, fields, and which _week/_month suffixes exist before any real Pandadata call.
5. Use the correct method family per market: HK -> get_stock_recommendation_consensus / get_stock_ncycl_consensus; US -> get_stock_recommendation_estimate / get_stock_ncycl_estimate.
6. State every upside's target-price source and current-price anchor date; report coverage depth beside consensus stats; never mix HK and US without a market/currency label.
7. Present consensus as analyst opinion, not a price forecast or company guidance. Do not invent ratings, target prices, symbols, credentials, or investment advice.
```
