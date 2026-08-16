# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named concept-rotation-monitor at:
<CONCEPT_ROTATION_MONITOR_SKILL_ROOT>

When the user asks for A-share concept/theme rotation, 概念轮动, 题材轮动, 概念热度, 板块轮动, 概念动量排名, 新概念, or concept constituents:
1. Read <CONCEPT_ROTATION_MONITOR_SKILL_ROOT>/SKILL.md.
2. For routing, the bottom-up aggregation formulas, weighting/breadth definitions, the membership-snapshot rule, report format, empty-data handling, or QA, read <CONCEPT_ROTATION_MONITOR_SKILL_ROOT>/references/concept-rotation-playbook.md.
3. Validate generated reports with <CONCEPT_ROTATION_MONITOR_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_concept_list, get_concept_constituents, and get_stock_daily parameters and fields before any real Pandadata call.
5. Build concept momentum bottom-up from constituent returns; name the weighting (等权 median/mean) and window; there is no official concept price index.
6. Snapshot constituent membership with an explicit date (no lookahead on today's membership); report breadth beside momentum; use short−long spread for the rotation read.
7. Flag concept overlap / non-additivity and newly-formed concepts. Preserve source methods, windows, snapshot dates, constituent counts, and drop counts. Do not invent concepts, constituents, returns, credentials, or investment advice.
```
