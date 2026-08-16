---
name: skill-portfolio-pnl-attribution
description: Attribute realized portfolio returns to holdings and sectors, reconcile gross and net P&L to a benchmark, and flag missing or inconsistent inputs. Use when an agent needs daily or periodic portfolio performance attribution from positions, asset returns, benchmark returns, or fee data.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-portfolio-pnl-attribution
  repository_url: https://github.com/quantskills/skill-portfolio-pnl-attribution
  project_type: skill
  collection: portfolio-analysis
  license: GPL-3.0-only
  category: trader-research
  tags: [portfolio, pnl, attribution, performance]
  platforms: [claude-code, codex, cursor, hermes, openclaw]
  language: zh-en
  status: stable
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 将组合已实现收益按证券和行业拆解，并对账费用、基准与输入数据质量。
  summary_en: Auditable realized-return attribution by security and sector with fee and benchmark reconciliation.
---

<!-- qsh-form is optional; this declaration enables a structured run form in quantskillhub. -->
```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "例如：解释本组合本周的收益来源并检查对账差异",
    "required": true
  },
  "fields": [
    {"key": "positions_csv", "type": "text", "label": "持仓 CSV"},
    {"key": "returns_csv", "type": "text", "label": "资产收益 CSV"},
    {"key": "benchmark_csv", "type": "text", "label": "基准 CSV（可选）"},
    {"key": "fees_csv", "type": "text", "label": "费用 CSV（可选）"}
  ],
  "prompt_template": "请处理任务：{{task}}；持仓：{{positions_csv}}；资产收益：{{returns_csv}}；基准：{{benchmark_csv}}；费用：{{fees_csv}}。附件：{{#attachments}}"
}
```

# Portfolio P&L Attribution

Use this skill to turn point-in-time positions and same-date asset returns into an auditable P&L bridge. It separates security contributions, optional sector contributions, benchmark-relative active return, and fees. It does not estimate ex-ante factor risk.

## Core Workflow

1. Read [references/input_contract.md](references/input_contract.md) before calculating anything.
2. Parse dates and reject duplicate `(date, symbol)` positions or returns. Never forward-fill returns across a date boundary.
3. Join positions to same-date asset returns. Stop on missing joins and report the affected keys.
4. Run `scripts/attribute_portfolio.py` and inspect `summary.json`, `daily_attribution.csv`, and `security_attribution.csv`.
5. Reconcile each day: security contributions equal gross return; subtract fees for net return; compare with the benchmark when supplied.
6. Explain large contributors and residuals from the generated tables. Treat the result as research accounting, not an investment recommendation.

## Command

```bash
python scripts/attribute_portfolio.py --positions positions.csv --returns returns.csv \
  --benchmark benchmark.csv --fees fees.csv --output-dir attribution_out
```

Use `--demo --output-dir attribution_out` for a deterministic smoke test. The command writes CSV tables and a machine-readable `summary.json`.

## Output Contract

- `security_attribution.csv`: one row per date and security with weight, return, and contribution.
- `sector_attribution.csv`: sector contribution totals when `sector` is present in positions.
- `daily_attribution.csv`: gross return, fees, net return, benchmark return, and active return by date.
- `summary.json`: row counts, date range, reconciliation errors, cumulative gross/net/active returns, and warnings.

Treat `reconciliation_error` above `1e-10` as a data or rounding defect. If weights do not sum to one, keep the result but surface the daily `weight_sum` warning.

## Boundaries

- Use this skill for realized return accounting from supplied data.
- Do not use it as a replacement for ex-ante risk attribution, portfolio health checks, or allocation optimization.
- Preserve the source data and record the fee convention and return convention in the report.
- Follow [references/source_boundary.md](references/source_boundary.md) for permitted sources.
