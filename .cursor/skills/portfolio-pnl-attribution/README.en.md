<div align="center">
  <h1>Portfolio P&amp;L Attribution</h1>
  <p>Turn realized portfolio performance into an auditable security and sector contribution bridge.</p>
  <p>
    <a href="README.md">简体中文</a>
    ·
    <a href="https://github.com/quantskills/skill-portfolio-pnl-attribution/issues">Report an issue</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/QuantSkills-runnable-2f6fdb?style=flat-square" alt="QuantSkills runnable">
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.10 or newer">
    <img src="https://img.shields.io/badge/license-GPL--3.0-2ea44f?style=flat-square" alt="GPL-3.0 license">
  </p>
</div>

> 📌 **Positioning**: Research accounting for realized returns. It does not estimate ex-ante factor risk or provide investment advice.

## 🧭 Capability Map

| Capability | Result |
| --- | --- |
| Security attribution | Daily weights, asset returns, and contributions |
| Sector attribution | Sector totals when `sector` is supplied |
| Reconciliation | Gross return, fees, net return, and benchmark active return |
| Data quality | Rejects duplicate keys, missing same-date returns, and invalid values |

## ⚡ Quick Start

```bash
pip install -r requirements.txt
python scripts/attribute_portfolio.py --demo --output-dir out
```

Read [`references/input_contract.md`](references/input_contract.md) before real data. A typical run is:

```bash
python scripts/attribute_portfolio.py \
  --positions positions.csv \
  --returns returns.csv \
  --benchmark benchmark.csv \
  --fees fees.csv \
  --output-dir attribution_out
```

## 📥 Inputs and 📤 Outputs

| Dataset | Required columns | Notes |
| --- | --- | --- |
| `positions.csv` | `date,symbol,weight` | Optional `sector` |
| `returns.csv` | `date,symbol,asset_return` | Decimal returns; `0.01` means 1% |
| `benchmark.csv` | `date,benchmark_return` | Optional, one row per date |
| `fees.csv` | `date,fee` | Optional, as a fraction of portfolio value |

Generated artifacts:

- `security_attribution.csv`: security weight, return, and contribution by date.
- `sector_attribution.csv`: sector contribution totals when available.
- `daily_attribution.csv`: gross, fees, net, benchmark, and active returns.
- `summary.json`: coverage, cumulative returns, reconciliation errors, and warnings.

## 🔬 Workflow

```text
Input contract → date/key checks → same-date join → security/sector attribution → reconciliation → interpretation
```

Treat `reconciliation_error > 1e-10` as a data or rounding defect. If daily weights do not sum to one, keep the result and disclose the warning.

## 🧱 Boundaries and Sources

- Use only permitted public or user-provided sources; see [`references/source_boundary.md`](references/source_boundary.md).
- Never forward-fill returns across dates or silently replace missing returns with zero.
- This does not replace a risk model, portfolio health check, or allocation optimizer.

## 📁 Repository Layout

```text
SKILL.md                         # Agent workflow
scripts/attribute_portfolio.py   # Deterministic calculator
references/input_contract.md     # Input schema and constraints
references/source_boundary.md    # Source boundary
agents/openai.yaml               # Agent UI metadata
agents/cursor-rule.mdc           # Cursor runtime entrypoint
agents/portable-loader.md        # Hermes/portable runtime entrypoint
requirements.txt                 # Python dependencies
```

## ✅ Local Validation

```bash
node scripts/validate-qsh-form.mjs SKILL.md
python scripts/attribute_portfolio.py --demo --output-dir out
```

## Disclaimer

This repository organizes research methods only. It is not official, is not affiliated with any covered entity, does not verify performance claims, and does not constitute investment advice.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

## PandaAI / QUANTSKILLS Community

<div align="center">
  <img src="https://raw.githubusercontent.com/quantskills/.github/main/profile/assets/pandaai-community-qr.jpg" alt="PandaAI community QR code" width="220">
  <br>
  <sub>Scan the QR code to join the PandaAI community for QUANTSKILLS skills, agent workflows, and quantitative research practice.</sub>
</div>
