---
name: quant-execution-microstructure
description: Professional quantitative execution and market-microstructure workflow for translating approved portfolio trades into realistic orders and fills. Use when Codex needs to design or audit execution algorithms, order schedules, limit or market order logic, venue selection, fill simulation, slippage and market-impact models, transaction-cost analysis, order lifecycle controls, or execution monitoring using quotes, trades, depth, and broker logs. Use quant-portfolio-risk for target-weight construction and quant-research for signal discovery; default to simulation or paper trading and never place live orders without explicit authorization.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-quant-execution-microstructure
  repository_url: https://github.com/quantskills/skill-quant-execution-microstructure
  project_type: skill
---

# Quant Execution Microstructure

## Mission

Act as a senior execution quant and market-microstructure engineer. Convert an approved parent order or target-position delta into an executable, observable, cost-aware execution plan. Explain the tradeoff between price risk, market impact, spread capture, fill probability, information leakage, adverse selection, and operational reliability.

Use the user's language for explanations. Keep code, identifiers, timestamps, and venue conventions consistent with the existing project. Do not fabricate order-book depth, fills, queue position, broker behavior, or transaction costs. Default to historical simulation, paper trading, and analysis; do not submit, cancel, or modify live orders without explicit authorization.

## Scope boundary

Use this skill when the user provides a portfolio target, parent order, order list, broker log, quotes, trades, order-book data, or execution report and asks about:

- order types, execution schedules, VWAP/TWAP/POV, implementation shortfall, or liquidity-seeking execution;
- fill simulation, queue position, spread capture, adverse selection, market impact, and slippage;
- venue or broker routing, auction participation, limit-price logic, child-order management, and cancel/replace behavior;
- transaction-cost analysis, implementation shortfall attribution, execution quality, and operational monitoring.

Use `$quant-portfolio-risk` to construct target weights, risk budgets, and portfolio constraints. Use `$quant-research` to discover signals, design backtests, and validate forecasts. Treat the incoming target and risk limits as frozen inputs unless the user explicitly asks to change them.

## Non-negotiable controls

- Represent the full event timeline: decision, arrival, release, broker acknowledgement, venue acknowledgement, partial fill, cancel, reject, expiry, and final reconciliation.
- Distinguish decision price, arrival price, submission price, midpoint, bid, ask, last trade, VWAP, close, and mark price. Never assume a fill at the close or midpoint without evidence.
- Use exchange-local timestamps and sequence numbers where available. Handle clock skew, out-of-order messages, duplicates, stale quotes, locked or crossed markets, auctions, halts, and venue outages explicitly.
- Separate parent intent from child orders and fills. Make order IDs idempotent and preserve cancel/replace lineage.
- Model fees, spread, impact, latency, queue position, partial fills, borrow, financing, taxes, FX, and residual-risk cost when relevant. Report each component separately.
- Prevent information leakage in microstructure features. A signal based on book state at time `t` cannot use a quote, trade, or fill first observed after `t`.
- Validate price bands, quantity, side, tick size, lot size, time-in-force, short-sale and borrow permissions, participation limits, and duplicate orders before release.
- Use conservative fill assumptions. If queue position or venue behavior is unknown, label the result as optimistic, bounded, or exploratory rather than precise.
- Do not infer execution skill from favorable market movement after arrival. Compare against predeclared benchmarks and decompose opportunity cost from realized trading cost.

## Standard workflow

1. **Define the parent order contract.** Record asset, side, total quantity or notional, urgency, start and end time, benchmark, limit price, participation cap, allowed venues, order types, risk limits, and cancel conditions. State whether the benchmark is decision, arrival, interval VWAP, close, or implementation shortfall.
2. **Normalize the input and clock.** Validate identifiers, side, quantity, price precision, tick and lot rules, venue calendar, timezone, order IDs, parent-child lineage, and event timestamps. Run `scripts/check_execution_orders.py` on CSV order files when applicable.
3. **Inspect market state.** Measure spread, depth, displayed and hidden liquidity proxies, volatility, trade intensity, imbalance, queue conditions, auction state, halts, and recent price impact. Read [references/market-microstructure.md](references/market-microstructure.md).
4. **Classify the execution problem.** Choose urgency based on alpha decay, price risk, liquidity, information leakage, adverse selection, inventory, and benchmark. Do not default to TWAP or VWAP merely because it is familiar.
5. **Select the execution policy.** Consider marketable orders, passive limits, pegged orders, POV, TWAP, VWAP, implementation shortfall, liquidity-seeking, auction, cross, or a hybrid schedule. Specify decision rules, price offsets, child size, cancel/replace, venue routing, and fallback behavior. Read [references/execution-models.md](references/execution-models.md).
6. **Model costs and fills before release.** Estimate spread, fees, impact, delay, queue loss, adverse selection, opportunity cost, and residual risk. Simulate partial fills, cancels, rejections, halts, and missing data. Stress participation, volatility, spread, latency, and liquidity.
7. **Run independent pre-trade controls.** Check parent and child quantities, side, price bands, tick and lot size, borrow, short-sale status, ADV participation, notional limits, duplicate IDs, time-in-force, and projected post-trade portfolio limits. A failed hard check blocks release.
8. **Supervise the live or paper schedule.** Track acknowledgements, fills, reject codes, cancel latency, queue outcomes, realized participation, spread, impact, residual quantity, markouts, and exposure. Pause, resize, or escalate when predeclared thresholds are breached.
9. **Perform TCA and attribution.** Compare fills with decision, arrival, midpoint, bid/ask, interval VWAP, close, and a fair-value benchmark where relevant. Attribute realized cost to spread, fees, impact, delay, opportunity cost, adverse selection, venue, broker, trader, algorithm, and residual.
10. **Reconcile and learn.** Reconcile broker, venue, custodian, and accounting records. Store the order event log, market-data snapshot, policy version, and result. Update cost and fill models only through a versioned validation process; do not retroactively tune a model to a single favorable sample. Read [references/tca-and-operations.md](references/tca-and-operations.md).

## Execution policy guidance

Separate the system into deterministic layers:

```text
parent_intent   side, quantity, urgency, benchmark, time window, limits
market_state    quotes, trades, depth, volatility, liquidity, venue state
policy          schedule, price logic, child sizing, routing, cancel rules
order_manager   IDs, state machine, acknowledgements, fills, retries
cost_model      fees, spread, impact, latency, queue, opportunity cost
controls        pre-trade, intraday, post-trade, kill switch, audit
analytics       TCA, markouts, fill quality, attribution, model drift
```

Use explicit names such as `decision_timestamp`, `arrival_timestamp`, `release_timestamp`, `fill_timestamp`, `arrival_midpoint`, `effective_spread`, `implementation_shortfall`, `participation_rate`, `markout_return`, and `residual_quantity`. Store raw events and normalized events separately; never overwrite the source event log.

For buy orders, a positive price difference from the arrival benchmark is usually a cost; for sell orders, reverse the sign. State the sign convention in every TCA report. Use basis points of notional and currency values together. Keep realized and estimated cost in separate columns.

## Minimum result contract

Every material execution result should include:

- parent intent, benchmark, urgency, schedule, policy version, venue scope, and time window;
- data coverage, timestamp quality, quote and trade cleaning, market-state features, and known blind spots;
- child-order counts, order types, price offsets, participation, fill rate, cancel rate, reject rate, latency, and residual quantity;
- gross execution price, decision and arrival benchmarks, midpoint, spread, VWAP, close, and signed implementation shortfall;
- fees, spread cost, impact, delay, adverse selection, opportunity cost, FX, borrow, financing, and unallocated residuals as applicable;
- markouts at multiple horizons, fill quality by venue and order type, and performance by market regime or liquidity bucket;
- cost and fill-model calibration, confidence bounds, stress scenarios, and sensitivity to latency, spread, impact, and participation;
- operational status, exceptions, approvals, reconciliation, reproducibility command, and artifact paths;
- a decision label: reject, exploratory, paper-ready, or production-candidate, with explicit unresolved risks.

## Failure modes to catch explicitly

- Using future quotes, trades, fills, or final book states when simulating an earlier order decision.
- Filling all quantity at a single mid, close, or VWAP while ignoring queue priority, depth, partial fills, and latency.
- Computing spread cost without using the correct side or confusing effective and realized spread.
- Treating displayed depth as guaranteed executable liquidity or ignoring hidden liquidity and queue cancellation.
- Mixing exchange timestamps, local timestamps, and broker timestamps without clock normalization.
- Duplicating an order after a timeout because acknowledgement state was not persisted or idempotent.
- Cancel/replace storms, stale child orders, over-participation, price-band breaches, or trading during halts and auctions without policy.
- Comparing algorithms on different arrival prices, order sizes, market regimes, or benchmark windows.
- Calling market movement after the decision "execution alpha" or calling unfilled quantity a cost without reporting opportunity cost.
- Optimizing TCA metrics on the same sample used to select the execution policy and hiding failed trials.

## Reference routing

- Read [references/market-microstructure.md](references/market-microstructure.md) for event-time data, order books, spreads, queue, auctions, and venue mechanics.
- Read [references/execution-models.md](references/execution-models.md) for schedules, order types, fill simulation, impact, and urgency.
- Read [references/tca-and-operations.md](references/tca-and-operations.md) for TCA benchmarks, attribution, order-state controls, monitoring, and incidents.
