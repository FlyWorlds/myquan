# Quant Execution Microstructure

This skill turns approved portfolio trades into executable, observable, and cost-aware execution plans. It covers order design, market microstructure, fill simulation, transaction-cost analysis, execution controls, and post-trade monitoring.

## When to Use

Use it for execution algorithms, VWAP/TWAP/POV schedules, order types, venue routing, limit-price logic, fill quality, slippage, market impact, queue position, implementation shortfall, and execution monitoring.

Use `quant-portfolio-risk` for target-weight construction and portfolio constraints. Use `quant-research` for signal discovery, backtest design, and statistical validation. Treat incoming targets and risk limits as frozen inputs unless explicitly asked to change them.

## Contents

- `SKILL.md`: authoritative workflow, controls, result contract, and reference routing.
- `README.md`: Chinese-first project documentation.
- `references/`: market-microstructure, execution-model, and TCA guidance.
- `scripts/`: validation utilities for execution-order data.
- `agents/`: Codex, Cursor, Hermes, and OpenClaw runtime adapters.
- `CLAUDE.md`: Claude Code runtime adapter.

## Operating Defaults

- Keep decision, arrival, release, acknowledgement, fill, cancel, reject, and reconciliation events distinct.
- Report spread, fees, impact, latency, queue loss, adverse selection, opportunity cost, and residual risk separately when applicable.
- Use conservative or bounded assumptions when queue position or venue behavior is unknown.
- Prefer historical simulation, paper trading, and analysis.
- Do not submit, cancel, or modify live orders without explicit authorization.
- This project is not investment advice, does not promise returns, and is not an official QUANTSKILLS endorsement.

## License and Provenance

Licensed under GPL-3.0-only. Upstream organization: QuantSkills. Repository: `skill-quant-execution-microstructure`. Final listing, recommendation, and official recognition remain subject to maintainer review.
