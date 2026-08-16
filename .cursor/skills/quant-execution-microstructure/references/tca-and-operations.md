# Transaction-Cost Analysis and Execution Operations

Use this reference for execution-quality reporting, broker or venue comparison, and operational control.

## Contents

- [Benchmark contract](#benchmark-contract)
- [TCA attribution](#tca-attribution)
- [Markouts and adverse selection](#markouts-and-adverse-selection)
- [Operational state](#operational-state)
- [Monitoring and incidents](#monitoring-and-incidents)
- [Audit package](#audit-package)

## Benchmark contract

Predeclare benchmark price, timestamp, side convention, quantity window, and inclusion rules. Common benchmarks include decision price, arrival price, interval VWAP, interval TWAP, midpoint, bid or ask, close, and a fair-value or alpha-adjusted benchmark.

Do not compare two algorithms with different arrival prices or order urgency and call the difference execution skill. Stratify results by asset, side, order size, participation, volatility, spread, liquidity, venue, time of day, and market regime.

For an order with signed side `s` where buy is `+1` and sell is `-1`:

```text
implementation_shortfall = s * (fill_price - benchmark_price) * filled_quantity
shortfall_bps = implementation_shortfall / benchmark_notional * 10000
```

Define how fees, rebates, FX, unfilled quantity, and opportunity cost enter the equation. Keep raw and adjusted versions so a report can reconcile to broker and accounting records.

## TCA attribution

Report both currency and basis points for:

- explicit fees, commissions, taxes, and exchange or broker charges;
- spread paid or captured relative to midpoint and quoted market;
- market impact during and after the order;
- delay between decision, arrival, release, and fill;
- opportunity cost for unfilled or late quantity;
- adverse selection and short-horizon markout;
- venue, broker, algorithm, trader, signal, and time-of-day effects;
- residual or unexplained cost.

Reconcile:

```text
total_cost = explicit + spread + impact + delay + opportunity + residual
```

The exact decomposition depends on the benchmark. Label terms that are not uniquely identifiable rather than assigning causal precision that the data cannot support.

## Markouts and adverse selection

Compute signed markouts from the fill price to future midpoint or executable prices at several horizons, such as seconds, minutes, and end of interval. Separate passive fills from aggressive fills, and control for side, spread, volatility, and market movement.

Negative passive markouts can indicate adverse selection; positive aggressive markouts may indicate price risk or favorable information, but neither proves causality. Preserve the reference quote, quote age, venue, and event-time alignment used for each markout.

## Operational state

Model parent and child order states explicitly:

```text
created -> validated -> released -> acknowledged -> partially_filled
        -> canceled / rejected / expired / filled / reconciled
```

Persist state transitions with event timestamp, receive timestamp, sequence, source, idempotency key, quantity remaining, and reason code. Make retries safe. Reconcile order state across strategy, OMS, broker, venue, custodian, and accounting systems.

Define ownership and escalation for missing acknowledgements, rejected orders, duplicate fills, cancel failures, stale orders, orphaned children, symbol changes, corporate actions, and broker or venue disconnects.

## Monitoring and incidents

Monitor order release latency, acknowledgement latency, cancel latency, fill rate, reject rate, duplicate rate, residual quantity, participation, spread, impact, markout, cost versus benchmark, and data freshness. Track distributions and change points, not only averages.

Use amber and red thresholds with actions. Examples:

- abnormal spread or volatility: reduce aggression, widen price protection, or pause;
- rising reject or cancel latency: stop new releases and escalate to operations;
- participation or impact breach: resize, extend schedule, or require approval;
- unexplained fill or position mismatch: block retries and reconcile;
- stale or crossed feed: suspend decisions dependent on that feed;
- loss of independent risk or venue state: enter documented safe mode.

## Audit package

Archive parent intent, target delta, child orders, raw and normalized events, market-data snapshot or identifiers, policy and cost-model versions, benchmarks, fills, cancels, rejects, TCA outputs, approvals, exceptions, and final reconciliation. Store enough metadata to reproduce the decision without overwriting the source event log.

When updating execution models, use time-split calibration, out-of-sample checks, stress tests, and a rollback plan. Track failed experiments and vendor or venue changes. A lower average cost that increases tail cost, information leakage, or operational risk is not automatically an improvement.

