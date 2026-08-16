# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named earnings-season-tracker at:
<EARNINGS_SEASON_TRACKER_SKILL_ROOT>

When the user asks for A-share earnings-season scans, performance forecast statistics, forecast-type distribution, beat or miss watchlists, audit-opinion watchlists, industry earnings prosperity, full-market earnings cross-sections, or scheduled earnings-season scans:
1. Read <EARNINGS_SEASON_TRACKER_SKILL_ROOT>/SKILL.md.
2. For scan routing, forecast-type definitions, beat or miss rules, industry aggregation, report format, empty-data handling, or QA, read <EARNINGS_SEASON_TRACKER_SKILL_ROOT>/references/earnings-season-guide.md.
3. Validate generated reports with <EARNINGS_SEASON_TRACKER_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact method parameters and fields before any real Pandadata call.
5. Preserve source method names, query parameters, reporting periods, scan windows, data dates, and missing-data notes.
6. Do not invent data interfaces, credentials, fields, reporting periods, disclosure dates, or investment advice.
```
