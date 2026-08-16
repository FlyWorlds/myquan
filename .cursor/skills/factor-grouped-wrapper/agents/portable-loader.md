# Portable Loader Prompt

Use this prompt with Hermes, OpenClaw, Claude Code fallback loading, or other Agent platforms that do not natively discover `SKILL.md` folders. Codex uses `SKILL.md` plus `agents/openai.yaml`; Cursor uses `agents/cursor-rule.mdc`.

```text
You can access a local Skill named factor-grouped-wrapper at:

<FACTOR_GROUPED_WRAPPER_SKILL_ROOT>

When a request matches the description in its SKILL.md:

1. Read <FACTOR_GROUPED_WRAPPER_SKILL_ROOT>/SKILL.md first.
2. Follow its workflow and integrity rules exactly.
3. Read only the needed files under references/.
4. Run the bundled scripts from the Skill root.
5. Preserve documented configuration names, CLI commands, output fields, fingerprints, data boundaries, and OOS seal.
6. Do not invent unsupported models, label horizons, data adapters, metrics, or output fields. Seed-path and within-iteration concurrency are configured by `runtime.seed_workers` and `runtime.candidate_workers`.
7. Treat validation IC or Sharpe evidence and OOS backtests as quantitative research evidence, not investment advice, guaranteed returns, or production validation.
```

## Entrypoint

```bash
python scripts/run_factor_grouped_wrapper.py --config <config-yaml> <command>
```

Supported commands:

```text
validate
prepare-cache
search-backward [--run-dir <run-dir>]
search-forward [--run-dir <run-dir>]
freeze --run-dir <run-dir>
evaluate-oos --run-dir <run-dir> [--force] [--report]
```

Backward and Forward are independent modes. In a combined run, pass the Backward run directory to Forward. All Forward seeds then start from the one selected pool A result.

## Required References

- Read `references/input_schema.md` when preparing data or configuration.
- Read `references/algorithm.md` when explaining or changing grouping and search behavior.
- Read `references/output_contract.md` before consuming result files.
- Read `references/factor-backtest-integration.md` before Sharpe-primary search or OOS evaluation.
- Read `references/source_boundary.md` and `references/validation_notes.md` before publishing or interpreting research outputs.

## Boundaries

Version 1 supports CPU LightGBM, `execution_lag=1`, `horizon=1`, optional independent seed-path and within-iteration candidate concurrency, and optional in-memory feature preloading. Search uses validation prediction metrics by default; `primary_metric: sharpe` invokes FactorBacktest only on validation predictions. OOS evaluation requires a frozen selection and invokes the external FactorBacktest CLI once per snapshot.
