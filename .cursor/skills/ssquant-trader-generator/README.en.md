# 🏭 SSQuant Trader Generator (ssquant-trader-generator)

[简体中文](README.md) | **English**

> Say your idea once, get an AI trader you can reload anytime.

<p align="center">
  <img alt="role" src="https://img.shields.io/badge/role-AI%20trader%20factory-brightgreen">
  <img alt="ssquant" src="https://img.shields.io/badge/SSQuant-%3E%3D0.4.6-blue">
  <img alt="engine" src="https://img.shields.io/badge/engine-ssquant--ai--trader-orange">
  <img alt="platforms" src="https://img.shields.io/badge/platforms-Hermes%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor-7c3aed">
  <img alt="license" src="https://img.shields.io/badge/license-GPLv3-blue">
</p>

---

## 📖 Introduction

**`ssquant-trader-generator`** is the **"factory"** for AI traders.

Its core responsibility is not just executing a one-off trading task, but turning a user's natural-language trading idea into a **permanent, reusable, dedicated Skill file**.

## 🎯 Goal

Let the user state an idea once and receive an AI-trader tool that can be invoked anytime in the future.

## 🔄 Workflow

```mermaid
flowchart LR
    A["💬 User's trading idea<br/>in natural language"] --> B["1️⃣ Parse<br/>extract trading logic"]
    B --> C{"2️⃣ Classify mode"}
    C -->|crisp rules| D["Fully-auto"]
    C -->|fuzzy rules| E["Semi-auto"]
    D --> F["3️⃣ Deploy<br/>delegate to ssquant-ai-trader<br/>env setup · codegen · SIMNOW connect"]
    E --> F
    F --> G["4️⃣ Solidify (core feature)<br/>call skill_manage to create a standalone Skill<br/>e.g. rb-ma-cross-trader"]
    G --> H["♻️ One-line reload next time<br/>'load my-trader'"]

    style A fill:#e3f2fd,stroke:#1976d2
    style F fill:#fff3e0,stroke:#f57c00
    style G fill:#f3e5f5,stroke:#7b1fa2
    style H fill:#e8f5e9,stroke:#388e3c
```

1.  **Parse**: receive the user's natural-language description and extract the trading logic.
2.  **Classify**: decide fully-auto vs semi-auto mode and assign tasks.
3.  **Deploy**: delegate to `ssquant-ai-trader` for environment setup, code generation, and SIMNOW connection.
4.  **Solidify (core feature)**: call `skill_manage` to create the trader's standalone Skill file (e.g. `rb-ma-cross-trader`), making it a persistent part of the system.

## 🤝 Relationship with `ssquant-ai-trader`

| Role | Responsibility |
|---|---|
| 🏭 **`ssquant-trader-generator`** (factory, this repo) | High-level intent understanding, task orchestration, **persistent Skill generation** |
| ⚙️ [`ssquant-ai-trader`](https://github.com/quantskills/skill-ssquant-ai-trader) (engine) | Low-level code generation, data fetching, trade execution, monitoring & notifications |

## ✨ Features

1.  **Persistence**: generated Skill files are saved in the skills directory; loading one next time restores the trader immediately.
2.  **Platform-adaptive**: whether running on Hermes, Claude Code, or Cursor, it automatically finds the correct path to save the Skill.
3.  **Version pinning**: requires SSQuant `>= 0.4.6` so generated strategies stay compatible with the latest features.

## 📂 Directory Layout

```text
ssquant-trader-generator/
└── SKILL.md          # Core instruction file (read by the Agent)
```

## 🚀 Usage Example

**User**: "Turn this trading idea into an automated trader that I can reload anytime."

**AI (with this Skill loaded)**:

1.  Calls the Generator to parse the rules.
2.  Delegates to `ssquant-ai-trader` to deploy the strategy on SIMNOW.
3.  **Auto-generates** `skills/quant-trading/my-trader/SKILL.md`.
4.  Tells the user: "✅ Trader created! Next time just say 'load my-trader'."

## ⚠️ Disclaimer

Traders produced by this skill deploy to the SIMNOW **paper-trading** environment only. Nothing here constitutes live-trading investment advice.

## 📄 License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).

## 🐼 PandaAI / QUANTSKILLS Community

<div align="center">
  <img src="https://raw.githubusercontent.com/quantskills/.github/main/profile/assets/pandaai-community-qr.jpg" alt="PandaAI community QR code" width="220">
  <br>
  <sub>Scan the QR code to join the PandaAI community for QUANTSKILLS skills, agent workflows, and quantitative research practice.</sub>
</div>
