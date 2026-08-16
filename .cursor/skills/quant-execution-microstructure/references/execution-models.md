# Execution Models

Use this reference to select an execution policy and define realistic simulation assumptions.

## Contents

- [Urgency](#urgency)
- [Execution archetypes](#execution-archetypes)
- [Impact and fill models](#impact-and-fill-models)
- [Simulation protocol](#simulation-protocol)
- [Order types and safeguards](#order-types-and-safeguards)

## Urgency

Set urgency from alpha decay, price volatility, order size, liquidity, spread, information leakage, benchmark risk, and risk limits. A faster schedule usually raises impact and spread cost while reducing opportunity cost; a slower schedule usually does the opposite. Quantify this tradeoff with a cost-risk frontier rather than a single chosen schedule.

Use a frozen parent order and compare policies on the same decision time, quantity, eligible universe, benchmark, market state, and cost conventions. Never select a policy from one favorable day.

## Execution archetypes

- **Marketable:** prioritize completion; use only with explicit price bands, quantity limits, and gap controls.
- **Passive limit or pegged:** seek spread capture; model queue, cancellations, adverse selection, and non-fill risk.
- **TWAP:** distribute quantity by clock time; use only when time-uniform liquidity and urgency assumptions are defensible.
- **VWAP:** follow a volume curve; estimate curve uncertainty and avoid treating historical volume as guaranteed future volume.
- **POV:** participate at a target share of observed volume; cap participation and handle low-volume or zero-volume periods.
- **Implementation shortfall:** trade quickly when price risk and alpha decay dominate; calibrate risk aversion and impact.
- **Liquidity-seeking or hybrid:** switch between passive, midpoint, and aggressive tactics based on book, spread, and fill signals; make state transitions auditable.
- **Auction or cross:** use when the venue and benchmark support it; model eligibility, imbalance, uncross price, and residual quantity.

Choose a policy from the mandate and data, not from naming convention. A schedule is incomplete without child sizing, price logic, routing, time-in-force, cancel/replace, fallback, and stop conditions.

## Impact and fill models

At minimum, separate:

```text
explicit_cost = fees + commissions + taxes + venue charges
spread_cost   = execution price relative to bid/ask or midpoint
impact_cost   = price movement attributable to the order
delay_cost    = market movement between decision, arrival, and release
opportunity   = cost of quantity not filled or filled after the benchmark window
```

For a buy, higher execution price relative to the benchmark is generally a cost; reverse the sign for a sell. State whether costs are in currency, basis points of notional, or return units.

Use model families appropriate to data quality:

- bar-level: spread proxies, participation, volatility-scaled impact, and conservative fill bands;
- quote and trade: effective spread, short-horizon markout, signed flow, and latency;
- depth and order events: queue position, level depletion, replenishment, cancel hazard, and partial fills.

Do not estimate queue position from displayed size alone when order identity is unavailable. Calibrate parameters on a time-split sample, preserve uncertainty bounds, and stress impact and fill probability.

## Simulation protocol

Replay historical market events in causal order. At each decision:

1. observe only data available by the decision timestamp;
2. create or update the parent state;
3. submit child orders with a modeled gateway and venue delay;
4. match against subsequent eligible events using price-time and order-type rules;
5. apply cancels, rejects, halts, auctions, partial fills, fees, and position state;
6. record every event and compute benchmarks from the correct information set.

Test edge cases: empty book, crossed market, stale feed, sequence gap, zero volume, sudden gap, trading halt, price limit, rejected order, duplicate acknowledgement, partial fill, canceled remainder, and end-of-session residual. A simulator that silently skips these states will overstate execution quality.

## Order types and safeguards

Validate tick size, lot size, minimum notional, price bands, side, time-in-force, short-sale permission, borrow, venue eligibility, and maximum child notional. Treat market, limit, stop, stop-limit, peg, iceberg, and auction instructions as different state machines.

Persist order state transitions and idempotency keys. A timeout is not proof of rejection; query or reconcile before retrying. Bound cancel/replace frequency. Define safe behavior for stale orders, venue disconnects, abnormal spread, halt, and risk-limit changes.

