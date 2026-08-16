# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named buyback-monitor at:
<BUYBACK_MONITOR_SKILL_ROOT>

When the user asks for A-share share-buyback monitoring, repurchase scans, buyback progress, cancellation buybacks, buyback intensity, buyback purpose classification, buyback price bands, or a buyback watch report:
1. Read <BUYBACK_MONITOR_SKILL_ROOT>/SKILL.md.
2. For routing, stage/purpose/intensity definitions, dedup rules, report format, empty-data handling, or QA, read <BUYBACK_MONITOR_SKILL_ROOT>/references/buyback-playbook.md.
3. Validate generated reports with <BUYBACK_MONITOR_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_repurchase parameters and fields before any real Pandadata call.
5. Deduplicate events across procedure stages before counting; report the latest stage; always distinguish 预案 (planned range) from executed amounts.
6. Classify purpose from source signals verbatim (assert 注销 only with write_off_date or explicit cancellation purpose); label ambiguous cases 未分类.
7. Preserve source method names, query windows, announcement dates, stages, and missing-data notes. Do not invent amounts, ratios, stages, purposes, credentials, or investment advice.
```
