---
name: skill-alpha-f5-member-position-concentration
description: Use when researching or validating the F5 commodity futures member-position concentration factor in a local Panda data environment.
license: GPL-3.0-only
tags: [quant, alpha, futures, factor-research]
runtime:
  codex: AGENTS.md
  claude_code: CLAUDE.md
  cursor: .cursor/rules/skill-alpha-f5-member-position-concentration.mdc
  hermes: HERMES.md
  openclaw: OPENCLAW.md
---

# F5 Member Position Concentration

This skill describes the F5 commodity futures factor research workflow. It uses
Panda data broker net margin, dominant contract and daily futures data to
compute a cross-sectional concentration signal from the top long and short
members.

## Runtime Entry

- Codex: read `AGENTS.md`, then this `SKILL.md`.
- Claude Code: read `CLAUDE.md`, then this `SKILL.md`.
- Cursor: load `.cursor/rules/skill-alpha-f5-member-position-concentration.mdc`.
- Hermes: read `HERMES.md`, then this `SKILL.md`.
- OpenClaw: read `OPENCLAW.md`, then this `SKILL.md`.

## Skill Contents

- Development skill: `alpha-f5-member-position-concentration/SKILL.md`
- Production-read skill: `alpha-f5-member-position-concentration-production/SKILL.md`
- Data guide: `alpha-f5-member-position-concentration/references/data_guide.md`

## Required Commands

Run from `alpha-f5-member-position-concentration/`:

```bash
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

These commands require `PANDA_DATA_USERNAME` and `PANDA_DATA_PASSWORD`.

## Boundaries

This repository is research and tooling material. It is not investment advice,
does not promise returns, and is not an official endorsement by QuantSkills,
Panda data, Codex, Claude Code, Cursor, Hermes or OpenClaw.

The recommended public repository name is
`skill-alpha-f5-member-position-concentration`.
