# Audit Opinion Scanner — Multi-dimensional Financial Analysis System

Covering audit opinion scanning (post-fact), 25 financial statement items, 15 derived ratios, industry classification benchmarking, 5-dimension rapid scoring, 8-section deep analysis, **⭐ XGBoost audit risk ex-ante prediction**, and composite risk detection. From risk screening to prediction to valuation to AI interpretation — a single pipeline.

## ⚠️ Disclaimer

- **Research & Educational Use Only**: This skill is a quantitative financial analysis research tool and does NOT constitute investment advice, financial advice, or trading recommendations of any kind.
- **Data Accuracy**: Financial data is sourced from panda_data and may contain errors, omissions, or delays. Always verify against official filings (annual reports, CSRC announcements) before making decisions.
- **No Guaranteed Outcomes**: Financial analysis scores and risk ratings are quantitative heuristics, not predictions. A high score does not guarantee future performance; a red flag does not guarantee losses.
- **Audit Opinion Lag**: Audit opinions reflect historical financial conditions and may not capture emerging risks. Non-standard opinions are trailing indicators, not leading ones.

## Directory Structure

```
├── SKILL.md                                ← Skill specification (v3.0)
├── README.md                               ← Chinese README
├── README.en.md                            ← This file
├── LICENSE                                 ← GPL-3.0
├── INSTALL.md                              ← Multi-platform install guide
├── requirements.txt                        ← pandas, xgboost, scikit-learn, pytest
├── data/                                   ← Local cache (parquet + JSON model)
│   ├── fina_cache.parquet                  ← 1300 stocks × 20 qtrs × (25 items + 15 ratios)
│   ├── fina_industry.parquet               ← 5,514 stocks × 31 Shenwan L1 industries
│   └── audit_predictor.json               ← XGBoost model (45 features, AUC 0.788)
├── scripts/
│   ├── scan.py                             ← Step 1: Audit opinion scanner
│   ├── build_cache.py                      ← Step 2: Local cache builder
│   ├── analyze_quick.py                    ← Step 3: 5-dim batch scoring (1300 stocks)
│   ├── analyze_stock.py                    ← Step 4: Single-stock 8-section deep report
│   ├── predict.py                          ← Step 5: ⭐ ML audit risk ex-ante prediction
│   ├── data.py / universe.py / rules.py / report.py
├── output/                                 ← Generated CSV reports + predictions
├── references/
│   └── need_used_api.md                    ← 5 panda_data API contracts
└── tests/                                  ← 120 unit tests
```

## Quick Start

```bash
# 0. Install dependencies
pip install -r requirements.txt

# 1. Build local cache (requires panda_data credentials, CSI1000 ~36s)
python scripts/build_cache.py --universe 000852.SH --quarters 20

# 2. Audit opinion scan
python scripts/scan.py --quarter 2025q4

# 3. Batch financial health scoring (1300 stocks, pure local, <1s)
python scripts/analyze_quick.py --all

# 4. Single-stock deep analysis
python scripts/analyze_stock.py 600519.SH

# 5. ⭐ ML audit risk prediction (train + predict)
python scripts/predict.py --train --backtest   # Train model + backtest
python scripts/predict.py --predict             # Predict for latest quarter
python scripts/predict.py --stock 600267.SH     # Single stock + risk drivers

# 6. Run tests
pytest tests/ -v
```

## Core Design

1. **6-Step Pipeline**: Audit scan → Local cache → Batch scoring → Deep analysis → ⭐ ML prediction → AI interpretation. Steps 3-6 are pure local reads with zero API calls.

2. **Two-Tier Caching**: 25 curated fields from 320+ general-ledger columns. 15 derived ratios computed on load (ROE, DuPont decomposition, cash flow quality). 20-quarter coverage across CSI1000.

3. **Industry-Normalized Scoring**: Every metric compared against same-industry peers using MAD-based z-scores.

4. **8-Section Deep Report**: Core financials → Profitability decomposition → DuPont → Balance sheet health → Cash flow quality → Growth trajectory → Industry percentiles → 12 automated risk checks.

5. **⭐ Dual-Mode Risk Detection**: Step 1 rule-based post-fact screening + Step 5 XGBoost ex-ante prediction (AUC 0.788, 45 features, 53 positive samples).

6. **Agent-Ready Data Products**: CSV and Parquet outputs with stable schemas. Other agents consume data via `pd.read_csv()` or `pd.read_parquet()`.

## Supported Runtimes

| Platform | Install Guide |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Any Python 3.10+ runtime | `INSTALL.md` § Standalone |
| Agent consumption | `INSTALL.md` § Data Products |

## Data Coverage

| Dimension | Scope |
|---|---|
| Stocks | 1,300 (CSI300 + CSI1000), expandable to full A-share |
| Quarters | 20 trailing (2021q3–2026q2) |
| Financial Fields | 25 curated (income stmt, balance sheet, cash flow) |
| Derived Ratios | 15 (ROE, ROA, margins, leverage, turnover, cash flow quality) |
| Industries | 31 Shenwan L1, 5,514 stocks classified |
| Audit Opinion Types | 10 (from unqualified to disclaimer of opinion) |
| ML Model | XGBoost (45 features, AUC 0.788, 53 positive / 3,652 training pairs) |

## Limitations

| Limitation | Detail |
|---|---|
| CSI1000 coverage (1,300 stocks) | Expand via `--universe` for full market (5,000+) |
| Limited ML training samples | 53 non-standard positives; AUC 0.788 valid but not high-precision |
| No LLM API integration | AI interpretation via current conversation context |
| No audit PDF/full-text analysis | Structured `opinion` field only |
| No real-time data support | Point-in-time analysis only |
| Financial sector prediction uncertain | Banks/insurers have special financial structures |
