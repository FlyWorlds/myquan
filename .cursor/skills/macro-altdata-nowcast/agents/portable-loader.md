# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments that receive skills as copied folders.

```text
You have access to a local skill named macro-altdata-nowcast at:
<MACRO_ALTDATA_NOWCAST_SKILL_ROOT>

When the user asks for 另类数据, 高频行业景气, 电商/招聘/地产/汽车/家电高频数据, 行业 nowcast, 特色数据监控, 景气度前瞻, or an alternative-data industry nowcasting report:
1. Read <MACRO_ALTDATA_NOWCAST_SKILL_ROOT>/SKILL.md.
2. For the category->method map, the mandatory code-resolution step, YoY/MoM & stat_type rules, the prosperity scoring convention, report format, empty-data handling, or QA, read <MACRO_ALTDATA_NOWCAST_SKILL_ROOT>/references/altdata-playbook.md.
3. Validate generated reports with <MACRO_ALTDATA_NOWCAST_SKILL_ROOT>/scripts/validate_report.py.
4. Use the local pandadata-api skill to verify exact get_macro_detail and get_macro_* parameters and fields before any real Pandadata call.
5. First call get_macro_detail(category=<X>) to resolve opaque indicator codes (EC/MD/EH/AD/HA/OF/RB/RE/ED/EP) to name/unit/frequency/stat_type/source; never report a raw code or bare data_value.
6. Respect stat_type (do not double-difference already-YoY series); mark frequency and window; flag the provisional tail.
7. Label the data as an alternative/timely sample that nowcasts (!= official statistic), state the prosperity-scoring convention, frame any lead/lag vs official as observation (hand official series to macro-monitor), and never invent indicator meanings, values, credentials, or investment advice.
```
