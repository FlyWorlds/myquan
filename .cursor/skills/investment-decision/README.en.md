# 🧩 Investment Decision

**English** | [简体中文](README.md)

> Given a company name or ticker, output a professional long-term investment decision report (.docx) with BUY/NEUTRAL/SELL recommendation and confidence probability — powered by public financial data (Yahoo Finance) + web research. Default English, Chinese supported. Self-contained — no paid API required.

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 What Is This

`skill-investment-decision` is an AI-agent skill for generating **long-term**
(6–18 month) single-stock investment decision reports. Given any company name
or ticker (US, A-share, HK, global), the agent:

1. Fetches price history, financials, and key metrics via Yahoo Finance (free);
2. Gathers news, analyst ratings, industry trends, and risks via web search;
3. Scores the company across 6 weighted dimensions (Financial Health, Growth,
   Valuation, Momentum & Sentiment, Industry Position, Risk Profile);
4. Outputs a clear **Long-Term BUY / NEUTRAL / SELL** recommendation with
   confidence probability;
5. Produces a formatted .docx professional report.

**Self-contained** — no Pandadata or paid API keys required. Uses only public
data sources.

## 🚀 Quick Start

### Agent Workflow

```text
User: Analyze Microsoft for a long-term investment decision

Agent:
1. Ticker → MSFT (web search), language → en (default)
2. Yahoo Finance: price history (252d), financials, key metrics (PE, PB, ROE, etc.)
3. Web search: recent news, analyst ratings, industry trends, key risks
4. Score across 6 dimensions using the decision framework
5. Generate report.json (English), investment_horizon: "long-term"
6. Validate: python scripts/validate_report.py --report report.json
7. Generate docx:
   python scripts/generate_report.py --report report.json \
     --output MSFT_investment_decision_20260622.docx
8. Report: "MSFT — Long-Term BUY (82% confidence). Decision at end of report."
```

### Direct Tool Usage

```bash
# Step 1: Fetch financial data
python scripts/fetch_data.py --ticker MSFT --output data.json

# Step 2: Agent fills qualitative parts (risks, scores, thesis)

# Step 3: Validate report
python scripts/validate_report.py --report data.json

# Step 4: Generate .docx report
python scripts/generate_report.py --report data.json --output output.docx [--language zh]
```

## 📦 Directory Structure

```
skill-investment-decision/
├── SKILL.md                          # Entry point (YAML declaration + agent instructions)
├── README.md / README.en.md          # Documentation
├── LICENSE                           # GPL-3.0
├── .gitignore
├── requirements.txt                  # yfinance, python-docx, pandas, numpy, pyyaml, matplotlib
├── references/
│   ├── decision-contract.md          # 📚 Report contract, scoring, data sources, validation rules
│   └── agent-integration.md          # 🔌 Multi-agent install & smoke test
├── scripts/
│   ├── fetch_data.py                 # 📊 Yahoo Finance data fetcher (pre-populates all fields)
│   ├── validate_report.py            # 🧪 Report validator (13 rules)
│   └── generate_report.py            # 📄 .docx generator (charts, tables, references)
└── agents/
    ├── openai.yaml                   # OpenAI/Codex adapter
    ├── cursor-rule.mdc               # Cursor rule adapter
    └── portable-loader.md            # Generic agent loader
```

## ⚠️ Disclaimer

This repository is for research methodology organization only. It does NOT
constitute any investment advice. Investment involves risk; decisions should
be made with caution.

## 👤 Maintainer

Created and maintained by `davideliu` (QuantSkills community).

## 📜 License

GPL-3.0. See [LICENSE](LICENSE).
