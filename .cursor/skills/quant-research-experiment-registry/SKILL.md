---
name: quant-research-experiment-registry
description: "Register existing quantitative research experiments with reproducibility, data-lineage, result-conflict, and lookahead-risk checks. Use when an agent needs to scan an existing research directory, confirm experiment assets, record PandaData queries and snapshots, compare reproduction runs, or produce a handoff-ready experiment manifest. Do not use this skill to mine factors, evaluate strategies, replace data APIs, or give investment advice."
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-quant-research-experiment-registry
  repository_url: https://github.com/quantskills/skill-quant-research-experiment-registry
  project_type: skill
  collection: research-audit
  license: GPL-3.0
  category: tooling
  tags: [experiment-registry, reproducibility, data-lineage, lookahead-audit, research-handoff]
  platforms: [claude-code, codex, openclaw, cursor, hermes]
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires: []
  summary_zh: 登记量化研究实验并审计数据、环境、结果与可复现性
  summary_en: Register quantitative experiments and audit data, environment, results, and reproducibility
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "扫描实验目录并生成可复现性登记",
    "required": true
  },
  "fields": [
    {"key": "experiment_directory", "type": "text", "label": "实验目录"},
    {"key": "operation_mode", "type": "select", "label": "操作模式", "options": [
      {"value": "scan_and_register", "label": "扫描并登记"},
      {"value": "reproduce", "label": "复现实验"},
      {"value": "update_registration", "label": "更新登记"}
    ]},
    {"key": "allow_execute", "type": "select", "label": "执行命令", "options": [
      {"value": "false", "label": "不允许"},
      {"value": "true", "label": "确认后允许"}
    ]},
    {"key": "allow_pandadata", "type": "select", "label": "调用 PandaData", "options": [
      {"value": "false", "label": "不允许"},
      {"value": "true", "label": "确认后允许"}
    ]},
    {"key": "report_language", "type": "select", "label": "报告语言", "options": [
      {"value": "zh-CN", "label": "中文"},
      {"value": "en-US", "label": "English"},
      {"value": "bilingual", "label": "双语"}
    ]}
  ],
  "prompt_template": "{{task}}；目录：{{experiment_directory}}；模式：{{operation_mode}}；允许执行：{{allow_execute}}；允许调用 PandaData：{{allow_pandadata}}；报告语言：{{report_language}}；附件：{{#attachments}}"
}
```

# Quant Research Experiment Registry

## Scope

This skill scans an existing research directory without executing source code by default. It identifies candidate assets, requires confirmation of the formal configuration, normalizes declared PandaData queries, records reproducibility evidence, and produces `manifest.json` plus a Markdown handoff report.

## Use When

Use this skill when the user asks to:

- register an existing quantitative research experiment;
- audit whether a research run can be reproduced;
- record data snapshots, code versions, dependencies, and result artifacts;
- compare an original run with a confirmed reproduction run;
- preserve evidence and decisions for team handoff.

## Do Not Use When

Do not use this skill to:

- discover or evaluate alpha factors;
- run a backtest or optimize a portfolio;
- replace `panda_data` API documentation or data retrieval skills;
- declare a strategy profitable or suitable for trading;
- accuse an issuer of fraud from an inconsistency alone.

## Operating Modes

- `scan_and_register`: scan an existing directory, confirm assets/configuration, and build a manifest.
- `reproduce`: select a documented command, confirm execution, and run only in an isolated output directory.
- `update_registration`: compare the current directory with a prior manifest and create a new version only after confirmation.

## Required Workflow

1. Scan metadata first; exclude caches, credentials, and virtual environments.
2. Analyze candidate text and data schemas without executing code.
3. Group candidates by code, configuration, data, results, commands, and definitions.
4. Confirm the formal configuration. Without one, produce only a `scan_draft`.
5. Normalize single, multiple, or file-based `panda_data` queries into `queries[]`.
6. Prefer PandaData-compatible metadata and snapshots when the experiment uses PandaData; MCP is an optional read-only transport, not a required runtime dependency.
7. Use declared configuration queries as the source of the experiment fingerprint; report code/config conflicts.
8. Record query and content fingerprints. Treat missing availability metadata as `not_checked`.
9. Extract structured metrics first; use Markdown and logs only as supplementary evidence. Never silently choose conflicting values.
10. If optional collaborating skills or MCP are available and authorized, record their normalized evidence; otherwise preserve `not_checked` without blocking local registration.
11. Before writing, show the target path and files. Never overwrite prior manifests automatically.

## Reproduction Boundary

Execution is opt-in. Candidate commands must be identified from project documentation or configuration and selected by the user. Confirmed commands run in an isolated `.quant-experiment/runs/<run_id>/` directory. External data access is limited to explicitly declared services. If the external data is unavailable or its snapshot differs, reproduction is `failed`, not a successful reproduction on substitute data.

## Output Contract

Produce, when writing is authorized:

- `.quant-experiment/manifest.json`;
- `.quant-experiment/reproducibility-report.md`;
- `.quant-experiment/decisions.jsonl`.

Core manifest fields are schema-validated. Project-specific fields belong under `extensions`. Overall reproducibility is separate from this repository's `validation_level` and must be one of `verified`, `partial`, `blocked`, or `failed`.

## Collaboration Contract

`skill-pandadata-api` supplies API contracts and query execution conventions. `skill-numerical-leak-check` may supply specialized leakage evidence. This skill records and orchestrates those results; it does not copy their implementation. A missing dependency requires an explicit per-check downgrade decision. Conflicting dependency and local findings remain unresolved until human review.

## Research Boundary

Use public sources or user-provided data only. Research records are not investment advice. Do not include credentials, tokens, private messages, or unredacted sensitive data in manifests, reports, snapshots, or fixtures.

## Local Commands

```bash
python scripts/scan_experiment.py path/to/experiment
python scripts/normalize_config.py path/to/config.yaml
python scripts/build_manifest.py --scan scan.json --config normalized.json --out manifest.json
python scripts/validate_manifest.py examples/manifest.example.json
python -m unittest discover -s tests -v
node scripts/validate-qsh-form.mjs SKILL.md
```
