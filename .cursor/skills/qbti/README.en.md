# 🧬 QBTI — Quant Behavior Type Indicator

[简体中文](README.md) | **English**

> Get a QBTI for your investing personality: a five-part quiz learns your temperament, a fixed rule table translates it into factor directions and strategy parameters, and the QuantSkills factor libraries and backtest pipeline do the heavy lifting — all explained in plain language. (Yes, the shareable personality-test feeling — but backed by an auditable deterministic rule table, not vibes.)

![type](https://img.shields.io/badge/type-agent--skill-blue)
![category](https://img.shields.io/badge/category-trader--research-orange)
![pipeline](https://img.shields.io/badge/pipeline-quiz_·_translate_·_evaluate_·_backtest_·_explain-brightgreen)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 What is this

`qbti` (**Q**uant **B**ehavior **T**ype **I**ndicator, formerly "Quant for Normal People") is a portable agent skill for **non-professional users**. It does not assume you know what IC, Sharpe ratio, or a factor is — it starts by getting to know you across five personality-quiz-style dimensions. The metaphors below are examples: the agent adapts the framing to whatever you care about (pets, football, gaming, cooking — anything), while the answers always land on a fixed closed enum:

- 😱 **Loss reaction**: your account drops 8% in a day — can you sleep? → risk tolerance, position cap
- 🐕 **Involvement**: a corgi you walk daily, or a succulent you water monthly? → attention level, rebalance cadence
- 📺 **Strategy taste**: chase the hit show, dig for hidden gems, or rewatch reliable classics? → factor-family affinity (momentum / mean-reversion / low-volatility / reversal)
- 🍚 **Universe style**: only dishes you know, anything on the menu, or "I have dietary restrictions"? → sector preferences and exclusions
- ⏳ **Time horizon**: when is this money's "reconsider date"? → holding period, turnover tolerance

**Framings are free; enums are fixed** — that is the hard contract between the conversation layer and the mapping layer (`references/question_bank.md`).

Answers are then translated into parameters by a **fixed, auditable mapping table** (`references/preference_mapping.yaml`) — deterministic, not LLM improvisation: the same answers always produce the same translation. The result is handed to the org's pre-built factor libraries for candidate selection and to `skill-backtest` for a standard-protocol historical backtest, and every chart is explained with the five-block plain-language template (what question does this answer / how to read it / what we see / what it means / data source).

**This skill translates; it never recommends.** It maps "who you are" to "what the parameters should look like" — it does not make investment decisions for you.

## 🧭 How it differs from sibling skills

| Skill | For people who... | Does |
| --- | --- | --- |
| **This skill** | don't yet know what they want | elicits preferences via a quiz, translates them into parameters |
| [`skill-ssquant-trader-generator`](https://github.com/quantskills/skill-ssquant-trader-generator) | already have a strategy idea | parses your stated idea into a futures AI trader |
| [`skill-stock-screener`](https://github.com/quantskills/skill-stock-screener) | have concrete screening criteria | translates criteria into data queries |
| [`skill-portfolio-checkup`](https://github.com/quantskills/skill-portfolio-checkup) | already hold a portfolio | health-checks the existing portfolio |

## 🚀 Quick Start

```bash
# Claude Code (global)
cp -r skill-qbti ~/.claude/skills/qbti
```

Trigger examples:

```text
I know nothing about quant but want a strategy that fits my temperament
Build me a stock strategy a normal person can understand
I'm a complete beginner — walk me into quant investing
```

Run the deterministic translation directly — [uv](https://docs.astral.sh/uv/) recommended (plain `python` works too; the script is pure stdlib with no dependencies and no network access):

```bash
uv run scripts/derive_profile.py \
  --answers examples/sample_run/sample_answers.json \
  --out examples/sample_run/
```

This produces `profile.json` (durable preference profile) and `strategy_brief.json` (pipeline handoff parameters). See [`examples/sample_run/`](examples/sample_run/).

## 📐 Core Constraints

| Constraint | Meaning |
| --- | --- |
| 🔒 Translate, never recommend | "We translated your answers into parameters", never "we recommend this strategy"; no buy/sell instructions, ever |
| 📋 Rule-table driven | All preference→parameter mapping comes from a fixed table — auditable, reproducible |
| 🛡️ Conservative-only adjustments | Adjustments may only move parameters toward more conservative, never more aggressive |
| 🔍 Defaults disclosed | Refused questions take documented defaults, recorded in `defaults_used` and read back to the user |
| 📉 Backtest ≠ forecast | All figures are historical simulation under the standard `skill-backtest` protocol, always shown with assumptions |
| 🎓 Research/education only | No promised returns, no safety claims, not investment advice |

## ⚠️ Disclaimer

> **Important Disclaimer**
>
> This skill (`skill-qbti`) collects your investing preferences and psychological tendencies through a lighthearted quiz, then uses a **fixed rule table** to translate those preferences into executable factor directions, position sizing, and rebalancing parameters. This is a parameter-translation tool — it is **not investment advice, not an advisory service, and does not constitute any form of personalized investment recommendation**.
>
> All content produced by this skill is based on public data and rule-based analysis, provided **for research and educational purposes only**, and **does not constitute investment advice** or a basis for any securities transaction. Any historical backtest figures referenced come from skills such as `skill-backtest` running historical simulations under stated assumptions (T+1 execution, fixed transaction costs, limit-up/suspension handling) — they **do not represent future performance and carry no promise or guarantee of return**.
>
> This skill is contributed by an independent community developer. It is **unofficial and not affiliated with** any brokerage, fund manager, or regulatory body, and does not represent the official position of the quantskills organization or the Pandadata data source.
>
> Investing carries risk. Please fully understand your own risk tolerance and consult a qualified professional investment advisor before making any investment decision. The author(s) and contributors of this skill accept no liability for any direct or indirect losses arising from its use.

## 📜 License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).

## 🐼 PandaAI / QUANTSKILLS Community

<div align="center">
  <img src="https://raw.githubusercontent.com/quantskills/.github/main/profile/assets/pandaai-community-qr.jpg" alt="PandaAI community QR code" width="220">
  <br>
  <sub>Scan the QR code to join the PandaAI community for QUANTSKILLS skills, agent workflows, and quantitative research practice.</sub>
</div>
