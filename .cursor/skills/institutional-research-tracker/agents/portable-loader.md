# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named institutional-research-tracker at:
<INSTITUTIONAL_RESEARCH_TRACKER_SKILL_ROOT>

When the user asks for A-share institutional-research (investor-relations) monitoring, research-heat ranking, most-visited companies, distinct-institution breadth, institution-type mix, or a "who is researching which company" report:
1. Read <INSTITUTIONAL_RESEARCH_TRACKER_SKILL_ROOT>/SKILL.md.
2. For routing, counting/breadth/type definitions, report format, empty-data and field-sparsity handling, or QA, read <INSTITUTIONAL_RESEARCH_TRACKER_SKILL_ROOT>/references/research-playbook.md.
3. Validate generated reports with <INSTITUTIONAL_RESEARCH_TRACKER_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_investor_activity parameters and fields before any real Pandadata call.
5. Separate research frequency (event count) from breadth (distinct institutions); report both. Classify institution type from verbatim source text only; ambiguous or None -> 未披露.
6. Surface field sparsity (None institute/participant) with a rate; never fabricate attendee or institution names. Frame being researched as attention, not a buy signal or endorsement.
7. Preserve source method names, query windows, activity dates, and missing-field notes. Do not invent visits, institutions, participants, counts, credentials, or investment advice.
```
