# Munger 5-Dimension Model and Cross-Validation Analysis Tool with Veto

> This repository is a community member project under QUANTSKILLS. It has not been officially reviewed and does not represent official endorsement or certification by QUANTSKILLS.

This project is a QuantSkills analysis tool implementing Charlie Munger's mental model for evaluating A-share (Chinese) listed companies. Through five independent dimensions and a cross-validation mechanism with veto rules, it produces high-confidence candidate pools.

## Five Dimensions

1. **Financial** (fin) - Relative advantages in ROE, gross margin, and operating cash flow
2. **Competition** (comp) - Relative competitive strength within industry
3. **Incentive** (incentive) - Controlling shareholder concentration, management buy/sell, pledges and freezes
4. **Psychology** (psych) - Investor activity and institutional attention
5. **Negative List** (neg) - Audit opinion, management changes, ST/delisting, high pledges, controlling shareholder selling

## Known Data Limitations

Following COMMUNITY_RULES §2 and §8 honesty disclosure principles, this tool has the following data limitations:

1. **No industry median API** - Must calculate industry comparable median manually
2. **Related-party transactions unavailable** - Incentive dimension marked `related_party: data_unavailable`
3. **QA text sentiment analysis unavailable** - Psychology dimension marked `qa_sentiment: not_available`
4. **Litigation data unavailable** - Marked `litigation: data_unavailable`

## Installation and Usage

### Requirements

- Python 3.10+
- panda_data SDK
- Environment variables: PANDA_DATA_USERNAME and PANDA_DATA_PASSWORD

### Quick Start

```bash
cd munger-mental-model/scripts

# Analyze single stock
python analyze.py --symbol 000001.SZ --end-date 20260630

# Screen by industry
python analyze.py --industry L2004001  # Banking sector

# Validate (run pre-flight checks)
PYTHONPATH=. python validate.py

# Run full test suite
PYTHONPATH=. pytest tests/ -v
```

### Environment Variables

```bash
export PANDA_DATA_USERNAME=your_username
export PANDA_DATA_PASSWORD=your_password
export MUNGER_PASS_THRESHOLD=60          # Score threshold, default
export MUNGER_PLEDGE_MAX=0.50            # Pledge ratio limit, default
export MUNGER_IR_MONTHS=12               # Investor activity query range, default
```

## Usage Boundaries and Disclaimer

**This tool is for research and educational use only and does NOT constitute investment advice.**

- No guarantee of returns or profits
- Not an official endorsement or recommendation
- Should not be the sole basis for investment decisions
- Results are for reference only; users must independently evaluate risks

## Output Formats

- **JSON** - Per-stock analysis records (`report_{symbol}.json`)
- **CSV** - High-confidence candidate list (`high_confidence_list.csv`)
- **PNG** - 5-dimension radar chart (`radar_{symbol}.png`)

## License

GNU General Public License v3.0 (GPL-3.0-only)

## Reference

See `munger-mental-model/SKILL.md` for detailed documentation.
