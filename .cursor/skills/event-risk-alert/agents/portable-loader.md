# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named event-risk-alert at:
<EVENT_RISK_ALERT_SKILL_ROOT>

When the user asks to monitor A-share holding risks, restricted-share unlocks, equity pledges, shareholder increase/decrease plans, ST or delisting-risk status changes, earnings forecast risk, audit-opinion risk, shareholder-count changes, daily or weekly event-risk scans, risk alert reports, or scheduled event-risk automation:
1. Read <EVENT_RISK_ALERT_SKILL_ROOT>/SKILL.md.
2. For multi-category scans, recurring monitors, state-file design, or report formatting, read <EVENT_RISK_ALERT_SKILL_ROOT>/references/event-risk-alert-guide.md.
3. Validate any watchlist JSON with <EVENT_RISK_ALERT_SKILL_ROOT>/scripts/validate_watchlist.py before scanning.
4. Use the local pandadata-api skill to verify exact method parameters and fields before any real Pandadata call.
5. Preserve source method names, query parameters, data dates, event dates, severity rules, and stale-data notes.
6. Do not invent data interfaces, credentials, fields, disclosure dates, event dates, or trading advice.
```
