# Portable Loader Prompt

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does not natively discover `SKILL.md` folders. If the runtime supports native skill folders, install the full folder unchanged and load `SKILL.md` directly.

```text
You have access to a local skill named stock-screener at:
<STOCK_SCREENER_SKILL_ROOT>

When the user asks for 选股, 筛选股票, 找出满足条件的A股, 财务/分红/股东/资金面过滤, or natural-language stock screening:
1. Read <STOCK_SCREENER_SKILL_ROOT>/SKILL.md.
2. For multi-condition screens, also read <STOCK_SCREENER_SKILL_ROOT>/references/screener-guide.md.
3. Use the local pandadata-api skill to verify exact panda_data method parameters and fields before any real API call.
4. Normalize the user's criteria into atomic filters with metric, operator, threshold, time window, date basis, methods, and missing-data policy.
5. Keep the screening date explicit and avoid look-ahead bias by excluding rows disclosed after that date.
6. Execute filters layer by layer, recording method names, parameters, data dates, report periods, row counts, and missing-data notes.
7. Generate Chinese output by default with a screening funnel, final evidence table, reproducibility notes, and the required non-investment-advice disclaimer.
8. Do not invent methods, fields, credentials, factor definitions, or unsupported screening rules.
```

Runtime placement notes:

- Codex: keep the folder under a Codex skill path and invoke `$stock-screener`.
- Claude Code: keep the folder under a Claude skill path and invoke `$stock-screener`.
- Cursor: copy this folder to `.cursor/skills/stock-screener` and enable `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount the folder as a local skill root or paste the loader prompt above with the real path.
