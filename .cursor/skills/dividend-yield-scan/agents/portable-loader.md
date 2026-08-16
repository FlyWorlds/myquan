# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named dividend-yield-scan at:
<DIVIDEND_YIELD_SCAN_SKILL_ROOT>

When the user asks for A-share high-dividend / dividend-yield scans, 红利策略, dividend-quality analysis, payout continuity, cash-dividend vs 送转, ex-dividend calendars, or a dividend yield ranking:
1. Read <DIVIDEND_YIELD_SCAN_SKILL_ROOT>/SKILL.md.
2. For routing, yield/continuity/cash-vs-送转 definitions, the round_lot pitfall, report format, empty-data handling, or QA, read <DIVIDEND_YIELD_SCAN_SKILL_ROOT>/references/dividend-playbook.md.
3. Validate generated reports with <DIVIDEND_YIELD_SCAN_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_stock_cash_dividend / get_stock_dividend / get_stock_dividend_amount / get_stock_split parameters and fields before any real Pandadata call.
5. Compute per-share cash as div_cash_gross / round_lot (never forget round_lot — it causes a 10x error); dividend yield = trailing DPS / latest close, always stating window + price date + "cash only, 送转 excluded".
6. Separate cash dividends from 送转 (transferred/bonus shares are not cash return); label get_stock_dividend_amount stages (预案 vs 实施); frame yield as backward-looking, not a forecast.
7. Preserve source method names, query windows, dividend dates, and missing-data notes. Do not invent dividends, yields, continuity, payout, credentials, or investment advice.
```
