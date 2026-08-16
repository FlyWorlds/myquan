# Portable Loader Prompt

Use this prompt when the host does not automatically discover `SKILL.md` files. Replace `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>` with the absolute repository root before loading.

Load and follow:

1. `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>/SKILL.md` as the authoritative contract.
2. `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>/references/scan-and-confirm.md` for read-only scanning and confirmation boundaries.
3. `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>/references/manifest-contract.md` for required manifest fields and states.
4. `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>/references/data-snapshot-policy.md` and `lookahead-audit-boundary.md` when the experiment contains external data or temporal claims.
5. The relevant deterministic scripts under `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>/scripts/` instead of reimplementing their rules.
6. The schemas under `<QUANT_RESEARCH_EXPERIMENT_REGISTRY_SKILL_ROOT>/schemas/` before validating or writing a manifest.

Default to metadata-only scanning. Ask for explicit confirmation before executing source code, reproduction commands, external `panda_data` access, or any write. Do not include credentials, tokens, private messages, caches, virtual environments, or unredacted sensitive data in outputs. Record missing optional collaborators as scoped `not_checked`; MCP is optional read-only transport and is not a runtime dependency. Do not generate or evaluate factors, run a backtest engine, optimize a strategy, or provide investment advice.
