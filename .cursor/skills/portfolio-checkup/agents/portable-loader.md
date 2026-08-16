# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named portfolio-checkup at:
<PORTFOLIO_CHECKUP_SKILL_ROOT>

When the user asks for A-share portfolio checkups, holdings diagnostics, portfolio concentration, HHI concentration, benchmark deviation, portfolio risk exposure, unlock or pledge or reduction aggregation, weighted valuation distribution, or portfolio-level health reports:
1. Read <PORTFOLIO_CHECKUP_SKILL_ROOT>/SKILL.md.
2. For concentration formulas, HHI, weighted aggregation, risk exposure thresholds, benchmark deviation, score logic, report format, or QA, read <PORTFOLIO_CHECKUP_SKILL_ROOT>/references/checkup-guide.md.
3. Use <PORTFOLIO_CHECKUP_SKILL_ROOT>/portfolio.json only as an example holdings-list schema unless the user explicitly wants that sample.
4. Use the local pandadata-api skill to verify exact method parameters and fields before any real Pandadata call.
5. Preserve portfolio weight basis, formulas, source method names, query parameters, data dates, coverage ratios, and missing-data notes.
6. Do not invent holdings, weights, data interfaces, credentials, fields, risk events, or investment advice.
```
