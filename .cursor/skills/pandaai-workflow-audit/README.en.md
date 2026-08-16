# PandaAI Workflow File Audit

Review PandaAI workflow JSON files like code review. The skill checks graph integrity, strategy and factor code, data timing, research flexibility, backtest assumptions, and validation evidence, then reports severity-ranked defects with evidence, impact, and actionable fixes.

## What it detects

- dangling links, duplicate node IDs, cycles, and normalized/LiteGraph mismatches;
- Python syntax errors, negative shifts, and possible same-bar signal/execution leakage;
- hard-coded universes, excessive tunable decisions, and unknown trial counts;
- short or single backtest windows;
- zero costs or slippage and missing cost stress tests;
- implicit external data and unseeded randomness;
- missing run outputs, returns, trades, or trial matrices.

The tool never executes embedded workflow code. It also never translates missing evidence into a claim that a workflow is not overfit.

## Input

Supported inputs:

1. JSON exported by the PandaAI editor;
2. a saved `GET /api/workflow/query` JSON response;
3. an API envelope with the workflow under `data`.

The reviewer primarily uses `nodes`, `links`, and `static_input_data`, with `litegraph` as a compatibility and consistency source.

## Usage

```powershell
uv run scripts/audit_workflow.py workflow.json --json-out audit.json --markdown-out audit.md
```

Plain Python is also supported:

```powershell
python scripts/audit_workflow.py workflow.json --format markdown
```

Python 3.10+ is required. The script uses only the standard library and needs no network access.

## Output semantics

Every finding includes severity, a concrete defect, verifiable evidence, research impact, and an actionable improvement.

When the export contains no usable run results, the assessment remains:

```json
{
  "verdict": "insufficient-evidence",
  "overfit_risk": "unassessable",
  "evidence_level": "static-only"
}
```

This means the statistical question cannot yet be answered; it is not a pass.

## QuantSkills integration

This skill owns PandaAI workflow parsing and research review. Once periodic returns, all tried variants, and an honest trial count are available, `skill-backtest-overfit` can provide DSR, PBO, and related statistical tests. This project does not fabricate or duplicate those statistics.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Disclaimer

Research and education only; not investment advice. See `references/disclaimer_template.md` for the required full wording.

This is an independent, unofficial community contribution. It is not affiliated with PandaAI, PandaData, or any financial institution and does not represent the official position of the QuantSkills organization.

## License

GPL-3.0-only.
