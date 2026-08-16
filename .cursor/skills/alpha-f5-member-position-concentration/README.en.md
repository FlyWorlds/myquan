# skill-alpha-f5-member-position-concentration

F5 commodity futures member-position concentration factor research skill.

The current GitHub repository is `alpha-f5-member-position-concentration`; for
QuantSkills public listing, the recommended repository name is
`skill-alpha-f5-member-position-concentration`.

## What It Does

The factor measures top-5 long and short member concentration using Panda data
broker net margin records. It calculates a combined level and delta signal and
emits `buy`, `sell` or `hold` labels for research and validation.

This repository is research tooling only. It is not investment advice, does not
promise returns, and is not an official endorsement by QuantSkills, Panda data,
Codex, Claude Code, Cursor, Hermes or OpenClaw.

## Runtime Entries

| Runtime | Entry |
|---|---|
| Codex | `AGENTS.md` |
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursor/rules/skill-alpha-f5-member-position-concentration.mdc` |
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
.cursor/rules/skill-alpha-f5-member-position-concentration.mdc
alpha-f5-member-position-concentration/
  SKILL.md
  scripts/
  references/
alpha-f5-member-position-concentration-production/
  SKILL.md
  database.parquet
```

## Commands

Run from `alpha-f5-member-position-concentration/`:

```bash
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

Live factor, validation and backtest commands require:

| Variable | Required | Notes |
|---|---:|---|
| `PANDA_DATA_USERNAME` | yes | Panda data account name |
| `PANDA_DATA_PASSWORD` | yes | Panda data password |
| `PANDA_DATA_START_DATE` | no | format `YYYY-MM-DD` |
| `PANDA_DATA_END_DATE` | no | format `YYYY-MM-DD` |
| `PANDA_DATA_UNDERLYING` | no | comma-separated symbols |

## License

GPL-3.0-only. See `LICENSE`.
