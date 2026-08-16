# Agent Integration — skill-doc-to-alphas

Install, load, and smoke-test `skill-doc-to-alphas` across agent runtimes.
**Keep the whole skill folder** — it depends on `references/` and `scripts/`.

---

## Universal Smoke Test

Validation-only — confirms the toy-data engine and formula contract work.
From the skill root directory:

```bash
# 1. Verify formula contract
python -c "
import sys; sys.path.insert(0, 'scripts')
from formulas import ALLOWED_FIELDS, ALLOWED_FUNCTIONS
assert len(ALLOWED_FIELDS) == 6 and len(ALLOWED_FUNCTIONS) == 27
print('Contract OK')
"

# 2. Verify validator
echo '[{"name":"mom","expression":"returns(close,5)"},{"name":"bad","expression":"vwap * x(close,10)"}]' > /tmp/smoke.json
python scripts/generate_alphas.py --alphas /tmp/smoke.json
```

**Expected**: 6 fields, 27 functions, 1 passed, 1 failed.

---

## How This Skill Works (Agent-Native)

This skill does **not** call any external API. Instead:

1. **You** (the agent) read `SKILL.md` and `references/alpha_ops.md` for the contract.
2. **You** use your own LLM to generate alpha expressions in JSON format.
3. **You** save the alphas to a JSON file.
4. **You** run `scripts/generate_alphas.py --alphas <file>` to validate them.
5. **You** report pass/fail to the user.

The only dependencies are `numpy` and `pandas` — already present in any data-science Python environment.

---

## Claude Code

```bash
mkdir -p ~/.claude/skills
rsync -a --exclude '__pycache__' ./ ~/.claude/skills/skill-doc-to-alphas/
```

Use: `Generate 3 alphas from this text using $skill-doc-to-alphas: <text>`

---

## Codex

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
rsync -a --exclude '__pycache__' ./ "${CODEX_HOME:-$HOME/.codex}/skills/skill-doc-to-alphas/"
```

Use: `Use $skill-doc-to-alphas to generate 3 alphas from: <text>`

---

## OpenClaw

```bash
mkdir -p ~/.openclaw/skills
rsync -a --exclude '__pycache__' ./ ~/.openclaw/skills/skill-doc-to-alphas/
```

---

## Cursor

```bash
mkdir -p .cursor/skills .cursor/rules
rsync -a --exclude '__pycache__' ./ .cursor/skills/skill-doc-to-alphas/
```

Create `.cursor/rules/skill-doc-to-alphas.mdc`:

```text
---
description: skill-doc-to-alphas — alpha generation from documents with contract + validator
globs: **/*
alwaysApply: false
---

When asked to generate alpha factors from a document:
1. Read skills/skill-doc-to-alphas/references/alpha_ops.md for the contract.
2. Generate alphas with your own LLM following that contract.
3. Save to a JSON file and validate:
   python skills/skill-doc-to-alphas/scripts/generate_alphas.py --alphas <file>
```

---

## Without Native SKILL.md Discovery

Attach `agents/portable-loader.md` as context, then use the same prompts.
