# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders.

```text
You have access to a local skill named qbti at:
<QBTI_SKILL_ROOT>

When the user request matches this skill's SKILL.md description:
1. Read <QBTI_SKILL_ROOT>/SKILL.md.
2. Follow the workflow and guardrails in that file exactly, including the
   "wrapping free, enums fixed" contract: quiz wording may adapt to the user,
   but every recorded answer must land on the closed enums, and classifications
   must be confirmed with the user before recording.
3. Load referenced files under <QBTI_SKILL_ROOT>/references/ only when needed.
4. Derive the profile only through scripts/derive_profile.py; never hand-craft
   profile.json or strategy_brief.json values.
5. Show the disclaimer from references/disclaimer_template.md verbatim; QBTI
   output is a translation of preferences, never investment advice.
```
