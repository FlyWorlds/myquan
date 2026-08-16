# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named hk-us-quote-scan at:
<HK_US_QUOTE_SCAN_SKILL_ROOT>

When the user asks for Hong Kong or US equity quotes, adjusted returns, liquidity, price-volume valuation, industry-relative position, HK/US baskets, cross-market comparison, or a Hong Kong / US quote-and-valuation report:
1. Read <HK_US_QUOTE_SCAN_SKILL_ROOT>/SKILL.md.
2. For routing, metric definitions, HK/US symbol and schema notes, report format, empty-data handling, or QA, read <HK_US_QUOTE_SCAN_SKILL_ROOT>/references/scan-playbook.md.
3. Validate generated reports with <HK_US_QUOTE_SCAN_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact method parameters and fields before any real Pandadata call; HK and US response schemas differ.
5. Preserve source method names, query parameters, markets, currencies, data dates, and missing-data notes.
6. Never mix HK and US figures without a market/currency label, never net returns across currencies, and use adjusted prices for multi-day returns spanning ex-rights events.
7. Do not invent data interfaces, credentials, fields, symbols, prices, or investment advice.
```
