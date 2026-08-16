# Agent Integration — skill-investment-decision

Install, load, and smoke-test `skill-investment-decision` across agent runtimes.
**Keep the whole skill folder** — it depends on `references/` and `scripts/`.

**No external API keys required.** Uses Yahoo Finance (free) + web search.

---

## Universal Smoke Test

From the skill root directory:

```bash
# 1. Verify dependencies
python -c "
from docx import Document
import pandas, numpy, yaml
try:
    import yfinance
    print('yfinance available')
except ImportError:
    print('yfinance not installed (optional, web fetch works too)')
print('Dependencies OK')
"

# 2. Verify validator works
echo '{"meta":{"ticker":"TEST","company_name":"Test Corp","market":"us","language":"en","investment_horizon":"long-term","report_date":"2026-06-22","data_period_end":"2026-06-20"},"company_overview":{"business_description":"test","industry":"Tech","listed_date":"2020-01-01","headquarters":"NYC","special_status":"Normal"},"financial_analysis":{"revenue_trend":"Growing","net_profit_trend":"Stable","roe":0.15,"roa":0.06,"gross_margin":0.45,"net_margin":0.18,"debt_to_equity":0.8,"operating_cf_quality":"Strong"},"valuation_analysis":{"pe_ttm":22.0,"pb":4.5,"pe_percentile_1yr":0.62,"pe_percentile_3yr":0.55,"pe_percentile_5yr":0.50,"industry_pe_median":25.0,"peg_ratio":1.2},"market_sentiment":{"return_1m":0.03,"return_3m":0.10,"return_6m":0.15,"return_12m":0.30,"volume_trend":"Increasing","margin_trend":"N/A","connect_flow":"N/A","shareholder_trend":"N/A","news_sentiment":"Positive"},"risk_assessment":{"risks":[{"factor":"Risk 1","level":"Medium","mitigation":"Mit 1"},{"factor":"Risk 2","level":"Low","mitigation":"Mit 2"},{"factor":"Risk 3","level":"High","mitigation":"Mit 3"}]},"recommendation":{"scores":{"financial_health":{"score":8,"rationale":"t"},"growth":{"score":8,"rationale":"t"},"valuation":{"score":6,"rationale":"t"},"momentum_sentiment":{"score":7,"rationale":"t"},"industry_position":{"score":8,"rationale":"t"},"risk_profile":{"score":7,"rationale":"t"}},"total_score":7.3,"recommendation":"NEUTRAL","confidence":0.73,"thesis":"Test thesis"},"disclaimer":"This report is for research methodology purposes only and does not constitute any investment advice."}' > /tmp/smoke_invest.json

python scripts/validate_report.py --report /tmp/smoke_invest.json
```

**Expected**: `Validation PASSED`

---

## How This Skill Works (Agent-Native)

1. **You** (the agent) read `SKILL.md` and `references/decision-contract.md`.
2. **You** run `scripts/fetch_data.py --ticker <TICKER> --output data.json` to get all financial data from Yahoo Finance.
3. **You** use web search for news, analyst ratings, industry trends, and risks.
4. **You** fill the qualitative sections (risks, scores, thesis, disclaimer) in the JSON.
5. **You** run `scripts/validate_report.py --report data.json` to check correctness.
6. **You** run `scripts/generate_report.py --report data.json --output <file.docx>` to produce the final report.
7. **You** deliver the recommendation and .docx to the user.

---

## Claude Code

```bash
mkdir -p ~/.claude/skills
rsync -a --exclude '__pycache__' ./ ~/.claude/skills/skill-investment-decision/
```

Use: `Analyze 000001.SZ using $skill-investment-decision and give me a BUY/SELL recommendation.`

---

## Codex

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
rsync -a --exclude '__pycache__' ./ "${CODEX_HOME:-$HOME/.codex}/skills/skill-investment-decision/"
```

Use: `Use $skill-investment-decision to evaluate AAPL.NB.`

---

## OpenClaw

```bash
mkdir -p ~/.openclaw/skills
rsync -a --exclude '__pycache__' ./ ~/.openclaw/skills/skill-investment-decision/
```

---

## Cursor

```bash
mkdir -p .cursor/skills .cursor/rules
rsync -a --exclude '__pycache__' ./ .cursor/skills/skill-investment-decision/
```

Then create `.cursor/rules/investment-decision.mdc` from `agents/cursor-rule.mdc`.
