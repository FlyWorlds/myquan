# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders, including Claude Code, Hermes, and OpenClaw deployments. Codex uses `agents/openai.yaml`; Cursor uses `agents/cursor-rule.mdc`.

```text
You have access to a local skill named hk-us-dividend-events at:
<HK_US_DIVIDEND_EVENTS_SKILL_ROOT>

When the user request matches this skill's SKILL.md description:
1. Read <HK_US_DIVIDEND_EVENTS_SKILL_ROOT>/SKILL.md.
2. Follow the workflow and guardrails in that file exactly.
3. Load referenced files under <HK_US_DIVIDEND_EVENTS_SKILL_ROOT>/references/ only when needed.
4. Run bundled scripts from the skill root only after reading the relevant instructions.
5. Preserve documented API names, parameters, file paths, formulas, validation limits, and freshness notes.
6. Do not invent data interfaces, credentials, dividend fields, DRIP rules, or runtime behavior that is not supported by the skill files.
```
