# Portable Loader Prompt

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does
not natively discover `SKILL.md` folders. If the runtime supports native skill
folders, install the full folder unchanged and load `SKILL.md` directly.

```text
You have access to a local skill named doc-to-alphas at:
<DOC_TO_ALPHAS_SKILL_ROOT>

This is a self-contained skill — no API keys or other skills required.

When the user asks to generate alpha factors from document text:
1. Read <DOC_TO_ALPHAS_SKILL_ROOT>/SKILL.md.
2. Read <DOC_TO_ALPHAS_SKILL_ROOT>/references/alpha_ops.md for the contract.
3. Use your own LLM to generate N alpha expressions following that contract.
   Each alpha must have: name, expression, description, rationale.
   Output as a JSON array.
4. Save the alphas to a JSON file.
5. Validate:
   python <DOC_TO_ALPHAS_SKILL_ROOT>/scripts/generate_alphas.py --alphas <file>
6. Report which alphas passed and which failed.
```

Runtime placement notes:

- Codex: keep the folder under a Codex skill path and invoke `$doc-to-alphas`.
- Claude Code: keep the folder under a Claude skill path and invoke `$doc-to-alphas`.
- Cursor: copy this folder to `.cursor/skills/doc-to-alphas` and enable
  `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount the folder as a local skill root or paste the loader
  prompt above with the real path.
