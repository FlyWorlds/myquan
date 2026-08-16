# Hermes Loader

This file is the repository-local Hermes entry point. It is a compatibility instruction, not an organization-wide Hermes schema.

Load the root `SKILL.md` as the authoritative contract for `quant-research-experiment-registry`. Read only the references and schemas needed for the request, then use the deterministic scripts under `scripts/` for scanning, normalization, fingerprinting, manifest construction, and validation.

Default to metadata-only scanning. Require explicit confirmation before executing source code, reproduction commands, external `panda_data` access, or any write. Exclude credentials, tokens, private messages, caches, virtual environments, and unredacted sensitive data from outputs. Treat unavailable collaborators as scoped `not_checked`; MCP is optional read-only transport and is not a runtime dependency. Do not generate or evaluate factors, run a backtest engine, optimize a strategy, or provide investment advice.
