# Portable Loader Prompt

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does
not natively discover `SKILL.md` folders.

```text
You have access to a local skill named skill-investment-decision at:
<<SKILL_INVESTMENT_DECISION_ROOT>>

When the user asks to analyze a company, generate a long-term investment
recommendation, evaluate a stock for buying/selling, or produce a decision report:

1. Read <<SKILL_INVESTMENT_DECISION_ROOT>>/SKILL.md.
2. Read <<SKILL_INVESTMENT_DECISION_ROOT>>/references/decision-contract.md.
3. Resolve the company name/ticker via web search.
4. Fetch financial data from Yahoo Finance (yfinance or direct web fetch): price history (252d), financials, key metrics.
5. Web-search for recent news, analyst ratings, industry trends, and key risks.
6. Score across 6 weighted dimensions using the framework in contract §3.6.
7. Generate report JSON matching the schema in contract §8. Set `"investment_horizon": "long-term"`.
8. Validate: python <<SKILL_INVESTMENT_DECISION_ROOT>>/scripts/validate_report.py --report <report.json>
   Retry up to 5 times if validation fails.
9. Generate docx: python <<SKILL_INVESTMENT_DECISION_ROOT>>/scripts/generate_report.py --report <report.json> --output <ticker>_investment_decision_<YYYYMMDD>.docx
10. Present long-term recommendation, confidence %, and key reasons. Attach the .docx file.
```

Runtime placement notes:
- Codex: keep under a Codex skill path, invoke `$skill-investment-decision`.
- Claude Code: keep under a Claude skill path, invoke `$skill-investment-decision`.
- Cursor: copy to `.cursor/skills/skill-investment-decision`, enable `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount as local skill root or paste loader prompt with real path.
