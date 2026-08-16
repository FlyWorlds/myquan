# Market Microstructure Reference

Use this reference when working with quotes, trades, order books, venue events, or intraday execution data.

## Contents

- [Event data contract](#event-data-contract)
- [Book and quote measures](#book-and-quote-measures)
- [Trade classification](#trade-classification)
- [Auctions and interruptions](#auctions-and-interruptions)
- [Venue and data quality](#venue-and-data-quality)

## Event data contract

Preserve raw messages and define a normalized event schema:

| Field | Requirement |
| --- | --- |
| event timestamp | exchange or venue time with timezone and precision |
| receive timestamp | local or gateway time for latency analysis |
| sequence | venue sequence or deterministic ordering key |
| asset and venue | stable identifiers, venue code, and instrument status |
| event type | quote, trade, add, modify, cancel, auction, halt, resume, reject |
| price and quantity | tick and lot conventions; units and currency |
| side | bid, ask, aggressor side, order side, or explicitly unknown |
| order ID | retain only when the venue exposes it; do not infer identity casually |

Document whether updates are full snapshots, incremental messages, conflated feeds, or vendor bars. Apply events in sequence; a book reconstructed from out-of-order deltas is not valid for queue or depth analysis.

## Book and quote measures

For a valid two-sided quote:

```text
mid = (bid + ask) / 2
quoted_spread = ask - bid
relative_spread = (ask - bid) / mid
microprice = (ask * bid_size + bid * ask_size) / (bid_size + ask_size)
```

Check positive prices, `bid <= ask` except during explicitly flagged locked or crossed states, nonnegative sizes, and stale-quote age. State whether prices are displayed, consolidated, venue-specific, odd-lot, auction, or derived.

Useful diagnostics include top-of-book spread, depth by level, cumulative depth within basis-point bands, order-book imbalance, replenishment, cancellation rate, trade intensity, volatility, and realized impact. Do not treat any one metric as executable liquidity.

For a buy order, ask-side depth and ask-side queue matter first; for a sell, bid-side depth and bid-side queue matter first. When the book is empty, stale, locked, crossed, halted, or auction-only, use a documented fallback rather than silently substituting the last trade.

## Trade classification

Keep observed trade price and inferred aggressor side separate. Lee-Ready, tick, quote, and bulk-volume rules have different assumptions and failure modes. Record the classifier, quote synchronization tolerance, unknown-rate, and treatment of trades outside the spread.

Effective spread for a trade can be expressed as:

```text
effective_spread_bps = 2 * side_sign * (trade_price - midpoint) / midpoint * 10000
```

Use a consistent `side_sign` convention and report whether the midpoint is from the same venue, a consolidated book, or a matched quote. Realized spread and markout require a future reference midpoint; ensure the reference is available and not contaminated by later events.

## Auctions and interruptions

Model opening and closing auctions separately from continuous trading. Record indicative price, imbalance, matched quantity, uncross time, and auction eligibility. Halts, resumes, limit-up or limit-down bands, volatility interruptions, and venue outages change fill probability and price risk; they are state transitions, not missing data.

If an order spans an interruption, define whether it persists, cancels, reprices, or requires re-approval. Do not compare an auction fill with a continuous-market fill without identifying the benchmark and liquidity regime.

## Venue and data quality

For multi-venue markets, distinguish direct feeds, consolidated feeds, SIP or vendor latency, and local timestamps. Measure clock skew and feed latency. Validate sequence gaps, duplicate messages, crossed consolidated books, stale venue quotes, symbol mappings, tick-size changes, and currency or contract changes.

Use a data-quality report with row counts, event counts by type, missingness, unknown side rate, timestamp latency distribution, sequence gaps, stale duration, spread outliers, and coverage by venue and regime. If only OHLCV data is available, do not claim queue-level, venue-level, or order-book-level execution accuracy.

