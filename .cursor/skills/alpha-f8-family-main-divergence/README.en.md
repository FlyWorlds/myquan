# skill-alpha-f8-family-main-divergence

F8 commodity futures broker-position divergence factor research skill.

The current GitHub repository is `alpha-f8-family-main-divergence`; for
QuantSkills public listing, the recommended repository name is
`skill-alpha-f8-family-main-divergence`.

## What It Does

The factor compares selected retail-style brokers with selected major brokers
using Panda data broker net margin records. It calculates a cross-sectional
score and emits `buy`, `sell` or `hold` labels for research and validation.

This repository is research tooling only. It is not investment advice, does not
promise returns, and is not an official endorsement by QuantSkills, Panda data,
Codex, Claude Code, Cursor, Hermes or OpenClaw.

## Runtime Entries

| Runtime | Entry |
|---|---|
| Codex | `AGENTS.md` |
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursor/rules/skill-alpha-f8-family-main-divergence.mdc` |
| Hermes | `HERMES.md` |
| OpenClaw | `OPENCLAW.md` |

The root `SKILL.md` is the canonical skill entry.

## Structure

```text
SKILL.md
skill.json
AGENTS.md
CLAUDE.md
HERMES.md
OPENCLAW.md
.cursor/rules/skill-alpha-f8-family-main-divergence.mdc
alpha-f8-family-main-divergence/
  SKILL.md
  test.py
  scripts/
  references/
alpha-f8-family-main-divergence-production/
  SKILL.md
  database.parquet
```

## Commands

Run from `alpha-f8-family-main-divergence/`:

```bash
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

`python test.py` uses synthetic data and does not require Panda data
credentials. Live factor, validation and backtest commands require:

| Variable | Required | Notes |
|---|---:|---|
| `PANDA_DATA_USERNAME` | yes | Panda data account name |
| `PANDA_DATA_PASSWORD` | yes | Panda data password |
| `PANDA_DATA_START_DATE` | no | default `2024-01-01` |
| `PANDA_DATA_END_DATE` | no | default `2026-05-28` |
| `PANDA_DATA_UNDERLYING` | no | comma-separated symbols, or `all` |

## License

GPL-3.0-only. See `LICENSE`.
