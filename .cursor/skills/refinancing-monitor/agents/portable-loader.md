# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named refinancing-monitor at:
<REFINANCING_MONITOR_SKILL_ROOT>

When the user asks for A-share equity-refinancing monitoring, private-placement (定增) scans, rights-issue (配股) tracking, dilution ratios, refinancing discount / break-issue (定增破发), refinancing progress, or a refinancing watch report:
1. Read <REFINANCING_MONITOR_SKILL_ROOT>/SKILL.md.
2. For routing, stage/type/dilution definitions, dedup rules, report format, empty-data handling, or QA, read <REFINANCING_MONITOR_SKILL_ROOT>/references/refinancing-playbook.md.
3. Validate generated reports with <REFINANCING_MONITOR_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_stock_private_placement and get_stock_allotment parameters and fields before any real Pandadata call.
5. Keep 定增 and 配股 as separate event streams; deduplicate each across stages before counting; report the latest stage; always distinguish 预案 (planned) from 实施完成 (executed).
6. Compute dilution against a stated share base (get_share_float); compare issue/allotment price to market via get_stock_daily for discount and break-issue; state both as relative observations.
7. Preserve source method names, query windows, announcement dates, stages, and missing-data notes. Do not invent shares, prices, ratios, stages, status, credentials, or investment advice.
```
