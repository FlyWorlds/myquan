# Investment Decision Contract

This document defines the exact contract for investment decision reports generated
by `skill-investment-decision`. Agents must follow this contract when producing
reports.

---

## 1. Input

A company name or stock ticker symbol. The skill is **market-agnostic**:
- US: `AAPL`, `TSLA`, `MSFT`
- A-share: `000001.SZ`, `600000.SH`
- HK: `0700.HK`, `0001.HK`
- Other: any ticker resolvable via web search

The agent resolves the company name to a ticker via web search.

### 1.1 Language

- **Default**: English (`"language": "en"`).
- The user MAY specify a language override (e.g., "用中文写报告" → `"language": "zh"`).
- Supported values: `"en"` (English), `"zh"` (简体中文).
- The `language` field is stored in `meta.language`.
- All section content (headings, descriptions, rationales, thesis) MUST be written
  in the specified language. Field names in JSON remain in English.

### 1.2 Investment Horizon

**This skill produces LONG-TERM investment recommendations** (6–18 month horizon).
This is explicitly stated in the report output. The skill does NOT provide short-term
trading signals, intraday calls, or swing-trade recommendations.

---

## 2. Required Data Sources

This skill is **self-contained** — no external API keys or paid services are required.
All data is gathered via web scraping, public financial APIs, and the agent's web search.

### 2.1 Public Financial Data (Primary)

| Data | Source | Method |
|------|--------|--------|
| Price history (252 days) | Yahoo Finance | Web fetch: `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d` or use `yfinance` library |
| Financial statements (income, balance sheet, cash flow) | Yahoo Finance / public filings | Web fetch or `yfinance.Ticker(ticker).financials` |
| Key metrics (PE, PB, ROE, ROA, margins, D/E) | Yahoo Finance / public financial sites | Web fetch or `yfinance.Ticker(ticker).info` |
| Market cap, industry, sector | Yahoo Finance / company website | Web fetch or `yfinance.Ticker(ticker).info` |
| Historical PE/PB percentile | Self-calculated from price + financial data | Compute from fetched data |
| Earnings forecasts | Public analyst estimates | Web search: `"{company} analyst estimates 2026 earnings"` |

### 2.2 Company & Industry Research (Web Search)

| Data | Purpose | Search Query Pattern |
|------|---------|---------------------|
| Company business description | Overview section | `"{company} business description what does it do"` |
| Recent news (last 30 days) | Sentiment, catalysts | `"{company} news last month"` |
| Analyst ratings & price targets | Consensus comparison | `"{company} analyst rating consensus price target"` |
| Industry trends & position | Sector context | `"{industry} trends 2026 outlook"` |
| Key risks | Risk assessment | `"{company} risks challenges 2026"` |
| Shareholder / insider activity | Ownership signals | `"{company} insider trading institutional ownership"` |

### 2.3 Self-Contained Scripts

The bundled `scripts/` provide helpers for data gathering:
- **No Pandadata dependency** — the agent fetches data directly from public sources.
- The agent may use `yfinance` (free, no API key) for standardized financial data.
- The agent uses its native web search for news, sentiment, and qualitative research.
- All data sources are documented in the report for traceability.

---

## 3. Report Structure (Mandatory Sections)

Every report MUST contain these sections in this exact order.
**The investment decision (BUY/NEUTRAL/SELL) is revealed only at the end (§3.6).**

### 3.1 Company Overview (`company_overview`)
- Business description
- Industry position
- Market cap, listed date, headquarters
- Board/special status

### 3.2 Financial Analysis (`financial_analysis`)
- Revenue & net profit trends (YoY growth, last 8 quarters)
- Profitability: ROE, ROA, gross margin, net margin
- Balance sheet health: debt/equity, current ratio, cash position
- Cash flow quality: operating CF vs net profit
- Earnings forecast vs historical performance

### 3.3 Valuation Analysis (`valuation_analysis`)
- Current PE (TTM), PB
- Historical PE/PB percentile (1yr, 3yr, 5yr)
- Industry-relative valuation
- PEG ratio (if earnings growth available)

### 3.4 Market & Sentiment Analysis (`market_sentiment`)
- Price momentum (1m, 3m, 6m, 12m returns)
- Volume trends
- Margin trading trends
- Northbound/southbound flow trends (if applicable)
- Shareholder count trend (contracting = accumulation, expanding = distribution)
- Recent news sentiment summary (positive/negative catalysts)

### 3.5 Risk Assessment (`risk_assessment`)
- Key risk factors (3–5 items)
- Each risk rated: Low / Medium / High
- Mitigating factors for each risk

### 3.6 Investment Decision (`recommendation`)
**This is where the Long-Term BUY / NEUTRAL / SELL decision is revealed — at the END of the report.**

- **Horizon**: Long-Term (6–18 months). This is NOT a short-term trading signal.
- Scoring table with weighted dimensions:

| Dimension | Weight | Score (1–10) | Rationale |
|-----------|--------|-------------|-----------|
| Financial Health | 20% | | |
| Growth | 20% | | |
| Valuation | 20% | | |
| Momentum & Sentiment | 15% | | |
| Industry Position | 10% | | |
| Risk Profile | 15% | | |

- **Total weighted score** → mapped to recommendation:
  - **≥ 7.5**: BUY (confidence = score / 10)
  - **5.0 – 7.4**: NEUTRAL
  - **< 5.0**: SELL (confidence = (10 - score) / 10)
- Confidence probability expressed as e.g., "BUY with 82% confidence"
- Brief thesis paragraph summarizing the key drivers behind the decision

### 3.7 Disclaimer (`disclaimer`)
- English: "This report is for research methodology purposes only and does not constitute any investment advice. Investment involves risk; decisions should be made with caution."
- Chinese: "本报告仅作研究方法层面的整理与展示，不构成任何投资建议。投资有风险，决策须谨慎。"

---

## 4. Output Format

The final output is a **`.docx` file** with:

- Title page: company name, ticker, market, date — **no recommendation shown on the title page** (it is revealed at the end)
- Section headings as described in §3, in the exact order specified
- Tables with formatted data
- The BUY/NEUTRAL/SELL decision and confidence are revealed in §3.6 (Investment Decision), the final substantive section before the disclaimer
- Color coding: green (BUY), amber (NEUTRAL), red (SELL) — used only in §3.6
- File naming: `{ticker}_investment_decision_{YYYYMMDD}.docx`

The agent generates the content as a structured JSON following this contract,
then runs `scripts/generate_report.py` to produce the .docx.

---

## 5. Agent Workflow Steps

1. **Resolve ticker**: If user gives a company name, use web search to find the correct ticker.
2. **Detect language**: Check user's request for language preference. Default: `"en"` (English).
3. **Fetch financial data** — Run: `python scripts/fetch_data.py --ticker <TICKER> --output data.json`
   This populates ALL financial fields with real data from Yahoo Finance:
   - Company overview (name, industry, market cap, headquarters, description)
   - Financial analysis (ROE, ROA, margins, D/E, revenue/profit trends, CF quality)
   - Valuation analysis (PE, PB, PE percentiles, PEG)
   - Market sentiment (returns 1M/3M/6M/12M, volume trend, beta, short%, institutional %)
   - Meta (ticker, company name, market, data sources)
4. **Fetch qualitative data** — Use web search for:
   - Recent news and sentiment → fill `market_sentiment.news_sentiment`
   - Analyst ratings and price targets
   - Industry trends and competitive position → inform scores
   - Key risks and challenges → fill `risk_assessment.risks`
5. **Score & complete** — Fill the PENDING fields in the JSON:
   - Score each dimension (1–10) with rationales in `recommendation.scores`
   - Fill `recommendation.total_score`, `.recommendation`, `.confidence`, `.thesis`
   - Fill `disclaimer` in the target language
   - Fill `risk_assessment.risks` (3–5 items with level and mitigation)
6. **Validate** — Run `python scripts/validate_report.py --report data.json`.
   Fix any failures and retry up to 5 times.
7. **Generate docx** — Run `python scripts/generate_report.py --report data.json --output <output.docx> [--language en|zh]`
8. **Deliver** — Present the Long-Term recommendation, confidence, key reasons. Attach the .docx.

---

## 6. Validation Rules

The validator (`scripts/validate_report.py`) checks:

| Rule | Description | Severity |
|------|-------------|----------|
| R1 | All 8 mandatory sections present (§3.1–§3.7 + meta) | FAIL |
| R2 | Recommendation is one of: BUY, NEUTRAL, SELL | FAIL |
| R3 | Confidence is a float between 0.0 and 1.0 | FAIL |
| R4 | Weighted score sum ≈ 100% (±1%) | WARN |
| R5 | Individual dimension scores are 1–10 | FAIL |
| R6 | At least 3 risk factors listed | WARN |
| R7 | Disclaimer section present and non-empty | FAIL |
| R8 | Financial data dates are not in the future | FAIL |
| R9 | Recommendation matches score mapping in §3.6 | FAIL |
| R10 | Report JSON is valid JSON and parses correctly | FAIL |
| R11 | `meta.language` is one of: "en", "zh" | FAIL |
| R12 | `meta.investment_horizon` is "long-term" | FAIL |
| R13 | Critical fields (ROE, ROA, margins, D/E, PB, returns) populated; PE relaxed for unprofitable | FAIL |

---

## 7. Retry Loop (Auto-Correction)

If validation fails, the agent receives diagnostic output from the validator.
The agent then fixes the issues and re-validates — up to 5 attempts.

```text
Validation failed (attempt 1/5):
  FAIL R2: recommendation is "HOLD" — must be BUY, NEUTRAL, or SELL
  WARN R4: sum of weights = 97%, expected 100%

Agent: fixes → re-validates → passes → generates docx
```

---

## 8. Example — Minimum Viable Report JSON (English)

```json
{
  "meta": {
    "ticker": "MSFT",
    "company_name": "Microsoft Corporation",
    "market": "us",
    "language": "en",
    "investment_horizon": "long-term",
    "report_date": "2026-06-22",
    "data_period_end": "2026-06-20",
    "data_sources": {
      "price_data": "Yahoo Finance (yfinance)",
      "financials": "Yahoo Finance / public filings",
      "news_sentiment": "Web search",
      "analyst_ratings": "Web search"
    }
  },
  "company_overview": {
    "business_description": "National joint-stock commercial bank",
    "industry": "Banking",
    "market_cap": null,
    "listed_date": "1991-04-03",
    "headquarters": "Shenzhen",
    "special_status": "Normal"
  },
  "financial_analysis": {
    "revenue_trend": "Stable growth",
    "net_profit_trend": "Flat",
    "roe": 0.11,
    "roa": 0.0085,
    "gross_margin": null,
    "net_margin": 0.28,
    "debt_to_equity": null,
    "operating_cf_quality": "Good — operating cash flow exceeds net profit"
  },
  "valuation_analysis": {
    "pe_ttm": 5.2,
    "pb": 0.65,
    "pe_percentile_1yr": 0.55,
    "pe_percentile_3yr": 0.48,
    "pe_percentile_5yr": 0.42,
    "industry_pe_median": 5.8,
    "peg_ratio": null
  },
  "market_sentiment": {
    "return_1m": 0.02,
    "return_3m": 0.05,
    "return_6m": -0.03,
    "return_12m": 0.12,
    "volume_trend": "Stable",
    "margin_trend": "Margin balance slightly increasing",
    "connect_flow": "Sustained northbound inflow",
    "shareholder_trend": "Contracting — accumulation signal",
    "news_sentiment": "Neutral to slightly positive"
  },
  "risk_assessment": {
    "risks": [
      {"factor": "NIM compression continues", "level": "Medium", "mitigation": "Retail banking shift boosts non-interest income"},
      {"factor": "Real estate exposure risk", "level": "Medium", "mitigation": "NPL ratio under control; ample provisions"},
      {"factor": "Macroeconomic headwinds", "level": "Low", "mitigation": "Banking sector is counter-cyclical to some extent"},
      {"factor": "Regulatory policy changes", "level": "Low", "mitigation": "CAR meets regulatory requirements"}
    ]
  },
  "recommendation": {
    "scores": {
      "financial_health": {"score": 7, "rationale": "Stable ROE, good asset quality"},
      "growth": {"score": 6, "rationale": "Low-single-digit revenue and profit growth"},
      "valuation": {"score": 6, "rationale": "PE/PB near historical median, fair vs industry"},
      "momentum_sentiment": {"score": 6, "rationale": "Northbound inflow but limited near-term momentum"},
      "industry_position": {"score": 7, "rationale": "Tier-1 joint-stock bank"},
      "risk_profile": {"score": 7, "rationale": "Manageable risks, adequate provisions"}
    },
    "total_score": 6.45,
    "recommendation": "NEUTRAL",
    "confidence": 0.65,
    "thesis": "Ping An Bank has solid fundamentals and is well-positioned within the joint-stock banking sector. However, current valuation sits near historical medians with limited upside catalyst. Risk factors are manageable but NIM compression and real estate exposure warrant monitoring. NEUTRAL with 65% confidence."
  },
  "disclaimer": "This report is for research methodology purposes only and does not constitute any investment advice. Investment involves risk; decisions should be made with caution."
}
```
