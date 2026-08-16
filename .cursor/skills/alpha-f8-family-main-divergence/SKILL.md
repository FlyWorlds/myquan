---
name: skill-alpha-f8-family-main-divergence
description: Use when researching or validating the F8 commodity futures broker-position divergence factor in a local Panda data environment.
license: GPL-3.0-only
tags: [quant, alpha, futures, factor-research]
runtime:
  codex: AGENTS.md
  claude_code: CLAUDE.md
  cursor: .cursor/rules/skill-alpha-f8-family-main-divergence.mdc
  hermes: HERMES.md
  openclaw: OPENCLAW.md
---

# F8 Family Main Divergence

This skill describes the F8 commodity futures factor research workflow. It uses
Panda data broker net margin, dominant contract and daily futures data to compute
a cross-sectional divergence score between selected retail-style brokers and
selected major brokers.

## Runtime Entry

- Codex: read `AGENTS.md`, then this `SKILL.md`.
- Claude Code: read `CLAUDE.md`, then this `SKILL.md`.
- Cursor: load `.cursor/rules/skill-alpha-f8-family-main-divergence.mdc`.
- Hermes: read `HERMES.md`, then this `SKILL.md`.
- OpenClaw: read `OPENCLAW.md`, then this `SKILL.md`.

## Skill Contents

- Development skill: `alpha-f8-family-main-divergence/SKILL.md`
- Production-read skill: `alpha-f8-family-main-divergence-production/SKILL.md`
- Data guide: `alpha-f8-family-main-divergence/references/data_guide.md`
- Offline smoke test: `alpha-f8-family-main-divergence/test.py`

## Required Commands

Run from `alpha-f8-family-main-divergence/`:

```bash
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

`python test.py` uses synthetic data and does not require Panda data
credentials. The other commands require `PANDA_DATA_USERNAME` and
`PANDA_DATA_PASSWORD`.

## Boundaries

This repository is research and tooling material. It is not investment advice,
does not promise returns, and is not an official endorsement by QuantSkills,
Panda data, Codex, Claude Code, Cursor, Hermes or OpenClaw.

The recommended public repository name is
`skill-alpha-f8-family-main-divergence`.
