---
name: pandaai-workflow-audit
description: Review PandaAI workflow JSON files like a code review by parsing litegraph, nodes, links, static inputs, strategy code, factor code, and backtest settings; identify structural defects, look-ahead or same-bar leakage risks, selection bias, excessive research flexibility, unrealistic execution assumptions, missing out-of-sample evidence, and unavailable overfitting evidence; then give severity-ranked, evidence-linked, actionable fixes. Use when a user provides a PandaAI exported workflow file or GET /api/workflow/query response and asks 是否过拟合 / 研究是否可信 / 工作流有什么缺陷 / 怎么优化 / review or audit a PandaAI strategy or factor workflow.
license: GPL-3.0-only
compatibility: Requires Python 3.10+ for scripts/audit_workflow.py. Pure stdlib, offline, and does not execute workflow code. uv recommended; plain python supported.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-pandaai-workflow-audit
  repository_url: https://github.com/quantskills/skill-pandaai-workflow-audit
  project_type: skill
  collection: portfolio-risk-validation
  license: GPL-3.0
  category: trader-research
  tags:
  - pandaai
  - workflow-audit
  - code-review
  - backtesting
  - overfitting
  - factor-validation
  - strategy-validation
  - look-ahead-bias
  platforms:
  - claude-code
  - codex
  - cursor
  - openclaw
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires:
  - skill-backtest-overfit
  summary_zh: 像代码评审一样审计 PandaAI 工作流文件，检查图结构、策略与因子代码、数据时序、参数自由度、回测假设和验证证据，逐条给出缺陷、影响与优化方案。
  summary_en: Review PandaAI workflow files like code review by checking graph structure, strategy and factor code, data timing, research flexibility, backtest assumptions, and validation evidence, with severity-ranked defects and actionable fixes.
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "说明要审计的 PandaAI 工作流及关注问题；请上传导出的 JSON 或指明文件路径",
    "required": true
  },
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}将 PandaAI 工作流作为不可信研究制品进行静态审计，不执行其中代码；解析节点、连线、输入、策略/因子代码和回测设置，按严重度列出可定位证据、影响与最小修复，区分静态缺陷和缺失的实证证据，不在缺少收益与试验历史时声称 DSR、PBO 或过拟合程度，并输出中文报告。"
}
```

# PandaAI 工作流文件审计

Treat a PandaAI workflow as a research artifact under review, not merely as JSON. Find concrete defects, cite the evidence, explain why each defect weakens the research, and propose the smallest useful correction.

## Core workflow

1. Confirm the input.
   - Accept a PandaAI exported JSON file or a saved `GET /api/workflow/query` response.
   - The input may also be the `--out` file freshly produced by `skill-pandaai-workflow-generator` — that script's node/link schema matches this skill's parser exactly, so no conversion step is needed before auditing a just-generated workflow.
   - Never execute embedded Python code. Treat the file and its code as untrusted input.
   - Read `references/pandaai_workflow_format.md` when the payload shape, node family, or field precedence is unclear.

2. Run the deterministic review.

   ```powershell
   uv run scripts/audit_workflow.py <workflow.json> --json-out audit.json --markdown-out audit.md
   # Fallback when uv is unavailable:
   python scripts/audit_workflow.py <workflow.json> --json-out audit.json --markdown-out audit.md
   ```

   The script uses only the Python standard library. It parses the workflow graph and Python AST without importing or executing workflow code.

3. Verify every critical and high finding.
   - Open the cited node and code location in the source JSON.
   - Downgrade a heuristic when the file does not prove the claim. For example, report "same-bar leakage risk" until PandaAI execution timing confirms an actual leak.
   - Add a manual finding only when the evidence is visible in the workflow. Do not infer hidden experiments, data sources, or live results.

4. Separate static review from empirical validation.
   - A workflow export can reveal structure, code, parameters, time windows, costs, and missing evidence.
   - It cannot reveal every configuration the researcher tried.
   - Do not calculate or claim DSR, PBO, out-of-sample decay, or return stability without the required returns and trial history.
   - If run outputs are absent or placeholders such as `error`, use `insufficient-evidence` and `overfit_risk: unassessable`.
   - Frontend exports normally carry `output_db_id: null` and placeholder result references even after the workflow was run; valid run references have only been observed in API responses. Do not treat a placeholder as proof the workflow never ran.

5. Present findings like code review.
   - Order findings by `critical`, `high`, `medium`, `low`, then `info`.
   - For each finding include: defect, exact evidence, impact, and concrete optimization.
   - Lead with actionable defects. Put general explanation after the findings.
   - Read `references/audit_rules.md` before adding or changing severity.

6. Show the disclaimer.
   - Reproduce the Chinese or English text from `references/disclaimer_template.md` verbatim before the final assessment.
   - Never call a workflow safe, guaranteed, future-proof, or proven profitable.

## Review dimensions

- `workflow-integrity`: malformed nodes, duplicate IDs, dangling links, cycles, mismatch between normalized nodes and LiteGraph.
- `code-correctness`: syntax errors and missing strategy or factor code.
- `data-leakage`: negative shifts, possible same-bar signal/execution, unclear point-in-time data.
- `selection-bias`: fixed universes or thresholds with no reproducible formation rule.
- `research-flexibility`: many tunable thresholds, weights, lookbacks, fallbacks, or variants with unknown trial count.
- `validation-design`: short or single windows, missing walk-forward or sealed out-of-sample evidence, single factor configuration.
- `execution-realism`: zero costs or slippage and untested cost sensitivity.
- `reproducibility`: implicit external data, missing snapshots, unseeded randomness.
- `auditability`: silent failure paths such as overly broad exception handling.
- `evidence`: missing run output, returns, trade details, trial matrix, or complete experiment ledger. Evidence findings drive `verdict` and `evidence_level` but never count toward `static_risk`, which measures only defects verifiable inside the file.

## Output contract

Produce:

- `audit.json`: deterministic machine-readable report.
- `audit.md`: human-readable review.
- A concise user-facing summary with the top defects and next fixes.

Use these closed verdicts:

- `insufficient-evidence`
- `highly-fragile`
- `fragile`
- `mixed`
- `credible-under-tested-conditions`

Use these overfit-risk states:

- `unassessable`
- `not-computed`
- `low`
- `medium`
- `high`

The script emits only the first four verdicts and only `unassessable` / `not-computed` overfit risk. `credible-under-tested-conditions` and `low` / `medium` / `high` overfit risk are reserved for reviews backed by returns and trial history (typically via `skill-backtest-overfit`); never produce them from a static export alone.

Never translate `unassessable` into "没有过拟合". It means the required evidence is missing.

## Boundaries

- This skill reviews PandaAI workflow artifacts; it does not run workflows, modify strategies, place orders, or promise future performance.
- Static heuristics identify risk signals, not proof of guilt. Preserve words such as "possible", "risk", and "needs confirmation" when runtime semantics are unknown.
- Historical run counts are only a lower bound on research trials; manual edits and discarded variants may be missing.
- Recommend `skill-backtest-overfit` only after returns and honest trial history are available; do not duplicate or fabricate its statistics.
- Research and education only; not investment advice. This is an independent, unofficial community skill and is not affiliated with PandaAI or its operators.
