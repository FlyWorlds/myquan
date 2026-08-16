# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named holder-structure-scan at:
<HOLDER_STRUCTURE_SCAN_SKILL_ROOT>

When the user asks for A-share shareholder structure, 股东户数 trend, 筹码集中度 (chip concentration), 户均持股, 前十大股东占比, free-float share, or whether chips are concentrating/dispersing:
1. Read <HOLDER_STRUCTURE_SCAN_SKILL_ROOT>/SKILL.md.
2. For routing, the three-interface field model, concentration/trend definitions, caliber rules, report format, empty-data handling, or QA, read <HOLDER_STRUCTURE_SCAN_SKILL_ROOT>/references/holder-structure-playbook.md.
3. Validate generated reports with <HOLDER_STRUCTURE_SCAN_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_holder_count, get_top_holders, and get_share_float parameters and fields before any real Pandadata call.
5. Always label the top-holder concentration caliber (流通口径 hold_percent_float vs 总股本口径 hold_percent_total) and never mix calibers in one comparison.
6. Read trend across several periods keyed on end_date; state disclosure frequency and lag; never present one snapshot as a live position.
7. Distinguish locked (控股/国资/限售) concentration from free-float concentration; surface top-holder pledge/freeze as a risk flag. Do not invent counts, ratios, trends, credentials, or investment advice.
```
