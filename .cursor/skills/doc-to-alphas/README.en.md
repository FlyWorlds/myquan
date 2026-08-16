# 🧩 Doc to Alphas

[简体中文](README.md) | **English**

> OHLCV formula contract + toy-data validator. The agent generates alphas from document text with its own LLM, then this skill validates them.

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 What This Is

`skill-doc-to-alphas` is a **self-contained** Agent Skill. It calls no external APIs and depends on no other skills. It provides two things:

1. 📐 **Formula contract** — `references/alpha_ops.md` defines exactly 6 fields and 27 functions that every alpha expression must use.
2. 🧪 **Toy-data validator** — `scripts/generate_alphas.py --alphas <file>` evaluates each expression against synthetic OHLCV data, catching errors instantly.

The agent (Claude Code, Codex, etc.) generates alpha expressions using its own LLM, then runs the validator to confirm correctness.

## 🚀 Quick Start

### Agent workflow

```text
User: Generate 3 alpha factors from this momentum paper: <text>

Agent:
1. Read references/alpha_ops.md for the contract
2. Use your own LLM to generate 3 alphas (JSON array)
3. Save to alphas.json
4. Run: python scripts/generate_alphas.py --alphas alphas.json
5. Report pass/fail results
```

### Direct validator usage

```bash
echo '[{"name":"mom","expression":"returns(close,5)"},{"name":"bad","expression":"vwap * x(close,10)"}]' > /tmp/test.json
python scripts/generate_alphas.py --alphas /tmp/test.json
```

## 📦 Directory Layout

```
skill-doc-to-alphas/
├── SKILL.md                          # Skill entry
├── README.md / README.en.md          # Docs
├── LICENSE                           # GPL-3.0
├── references/
│   ├── alpha_ops.md                  # 📚 Field & function contract
│   └── agent-integration.md          # 🔌 Multi-agent install
├── scripts/
│   ├── formulas.py                   # 📐 Contract Python definitions
│   ├── validation.py                 # 🧪 Validation engine
│   └── generate_alphas.py            # 🔧 CLI validator
└── agents/
    ├── openai.yaml                   # OpenAI/Codex-style entry
    ├── cursor-rule.mdc               # Cursor rule adapter
    └── portable-loader.md            # Claude Code/Hermes/OpenClaw portable loader
```

## ⚠️ Disclaimer

This repository organizes research methods only. Not investment advice.

## 👤 Maintainer

Created and maintained by `abgyjaguo` for the QuantSkills community.

## 📜 License

GPL-3.0. See [LICENSE](LICENSE).
