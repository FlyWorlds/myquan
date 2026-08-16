---
name: investment-decision
description: >-
  "Generate a long-term investment decision report (BUY/NEUTRAL/SELL with
  confidence probability) for any stock given a company name or ticker. Uses
  public financial data (Yahoo Finance, web scraping) and web-sourced news,
  analyst ratings, and industry research. Self-contained — no paid API keys
  required. Produces a professional .docx report. Use when an agent needs to
  produce a long-term stock investment recommendation, evaluate a company
  for potential investment, generate a due-diligence decision report, or
  answer 'should I buy X stock?' on portable agent platforms such as Claude
  Code, OpenClaw, or Codex-style skill systems."
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-investment-decision
  repository_url: https://github.com/quantskills/skill-investment-decision
  project_type: skill
  collection: investment-analysis
  creator: davideliu
  creator_url: https://github.com/davideliu
  maintainer: davideliu
  maintainer_url: https://github.com/davideliu
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-investment-decision
  repository_url: https://github.com/quantskills/skill-investment-decision
  project_type: skill
  collection: investment-analysis
  category: analyst
  tags:
    - investment-decision
    - stock-analysis
    - buy-sell-hold
    - company-report
    - docx-report
    - yahoo-finance
    - financial-analysis
    - valuation
    - sentiment
    - risk-assessment
  platforms:
    - claude-code
    - codex
    - cursor
    - openclaw
  language: zh-en
  status: active
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 输入公司名称或股票代码，基于Yahoo Finance公开数据与网络搜索，输出长期（6-18个月）投资决策报告（买入/中性/卖出+置信度）.docx，含图表与完整数据来源。
  summary_en: Given a company name or ticker, generate a long-term (6-18 month) BUY/NEUTRAL/SELL investment decision report with confidence, charts, and sources in .docx format — self-contained, uses public data.
---

# Investment Decision (Long-Term)

Use this skill to generate a professional **long-term** investment decision report
(6–18 month horizon) for any stock. The agent gathers data from public sources
(Yahoo Finance, web search), scores the company across 6 weighted dimensions,
and outputs a .docx report with a clear BUY / NEUTRAL / SELL recommendation
and confidence level — revealed only at the end.

## Creator, Maintainer, And Scope

- Creator: `davideliu` (`https://github.com/davideliu`).
- Maintainer: `davideliu` for the QuantSkills community.
- Repository: `https://github.com/quantskills/skill-investment-decision`.
- License: GPL-3.0-only.
- Scope: **Long-term** (6–18 month) single-stock investment decision reports.
  Market-agnostic (US, A-share, HK, global). Self-contained — no paid API keys
  required. Does NOT cover short-term trading signals, intraday calls, portfolio
  allocation, or multi-stock comparison.

## Core Workflow

1. **Resolve ticker** — If user gives a company name ("Apple", "腾讯"), use
   web search to find the correct ticker symbol.
2. **Detect language** — Defaults to English (`"en"`). If the user's request
   is in Chinese or specifies a language, set `meta.language` accordingly.
3. **Fetch financial data** — Run:
   `python scripts/fetch_data.py --ticker <TICKER> --output data.json`
   This populates ALL financial fields with real data from Yahoo Finance
   (ROE, ROA, margins, D/E, PE, PB, returns, volume trend, beta, etc.).
   No more N/A values for available metrics.
4. **Fetch qualitative data** — Use web search for: recent news, analyst
   ratings & price targets, industry trends, competitive position, key risks.
5. **Score & complete** — Fill the PENDING fields in the JSON:
   - Score each dimension (1–10) with rationales
   - Set recommendation, confidence, thesis
   - Fill risk_assessment.risks (3–5 items)
   - Fill disclaimer in target language
6. **Validate** — Run `python scripts/validate_report.py --report data.json`.
   Fix any failures and retry up to 5 times.
7. **Generate docx** — Run `python scripts/generate_report.py --report data.json --output <file.docx> [--language en|zh]`.
   The Long-Term BUY/NEUTRAL/SELL decision appears only at the end.
8. **Deliver** — Present the long-term recommendation, confidence, and key
   rationale to the user, and attach the .docx file.

## Output Contract

Produce:
- `{ticker}_report_{YYYYMMDD}.json` — Structured report data
- `{ticker}_investment_decision_{YYYYMMDD}.docx` — Formatted report with:
  - Clean title page (company name, ticker, market, date — NO spoiler)
  - Explicit **Long-Term (6–18 month)** horizon labeling
  - Sections in build-up order: Company Overview → Financial Analysis →
    Valuation Analysis → Market & Sentiment → Risk Assessment →
    **Long-Term Investment Decision** (BUY/NEUTRAL/SELL revealed HERE) →
    Disclaimer
  - Color-coded decision (green/amber/red) in the final section only
  - Fully i18n: all headings and labels in the target language
  - Data source traceability in meta

## Calling Pattern

```bash
# Step 1: Fetch all financial data from Yahoo Finance
python scripts/fetch_data.py --ticker MSFT --output data.json

# Step 2: Agent fills qualitative sections in data.json (risks, scores, thesis, disclaimer)

# Step 3: Validate the completed report
python scripts/validate_report.py --report data.json

# Step 4: Generate .docx (English default, --language zh for Chinese)
python scripts/generate_report.py --report data.json --output MSFT_decision.docx [--language zh]
```

## Agent Prompt Template

When the user asks to analyze a company, generate an investment decision, or
evaluate whether to buy a stock, use this prompt:

```
You are a professional equity investment analyst specializing in LONG-TERM
(6–18 month) recommendations. The user wants an investment decision report
for {ticker_or_name}.

FOLLOW THIS EXACT WORKFLOW:

Step 1: Resolve ticker via web search if only a name was given.

Step 2: Detect language (default "en", use "zh" if user writes in Chinese).

Step 3: Run the bundled data fetcher — this pre-populates ALL financial
        fields with real data from Yahoo Finance — NO N/A values:
        python scripts/fetch_data.py --ticker <TICKER> --output report.json

Step 4: Web search for qualitative data:
        - Recent news (last 30 days) → fill market_sentiment.news_sentiment
        - Analyst ratings & consensus
        - Industry trends & competitive position
        - Key risk factors → fill risk_assessment.risks (3–5 items)

Step 5: Score each dimension (1–10) with rationale in recommendation.scores.
        Fill recommendation.total_score, .recommendation, .confidence, .thesis.
        Fill disclaimer in the target language.

Step 6: Validate: python scripts/validate_report.py --report report.json
        If it fails, fix issues and retry (up to 5 attempts).

Step 7: Generate .docx:
        python scripts/generate_report.py --report report.json
          --output <TICKER>_investment_decision_<YYYYMMDD>.docx
          [--language en|zh]

Step 8: Present the Long-Term recommendation, confidence %, and key reasons.
        Attach the .docx.
```

## Cross-Agent Use

- Claude Code / Codex: load via `SKILL.md`.
- Cursor: use `agents/cursor-rule.mdc`.
- Hermes / OpenClaw: use `agents/portable-loader.md`.
- OpenAI-style: read `agents/openai.yaml`.

## Reference Files

- `references/decision-contract.md` — Full report schema, scoring framework,
  data source requirements, validation rules, and example JSON.
- `references/agent-integration.md` — Install and smoke-test instructions
  for all agent platforms.
- `scripts/fetch_data.py` — Fetches all financial data from Yahoo Finance
  (price history, fundamentals, valuation, returns, charts data). Pre-populates
  the report JSON with real data — no N/A values.
- `scripts/validate_report.py` — Validates report JSON against the contract
  (13 rules, R1–R13).
- `scripts/generate_report.py` — Converts validated report JSON into a
  formatted .docx file with charts, tables, and references.
