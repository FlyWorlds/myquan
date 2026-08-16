# Methodology — Overseas Commodity Term Structure

This playbook is the computation reference for the skill. It covers how a curve is
built, how each metric is defined, how structures are classified, the pitfalls to
avoid, and how to degrade gracefully when public data is thin.

## 1. What a term structure is

The term structure (forward curve) of a commodity is the set of futures prices for the
same underlying across successive **listed contract months**: front month M1, then M2,
M3, and so on. Its **shape** describes the market's cost/benefit of holding the
physical vs the future — i.e. **carry**. It is not a forecast of the spot price.

Minimum for a real curve: **two or more real listed contract months**. One price is a
point, not a curve — do not manufacture a second month.

## 2. Inputs

For each contract month collect:

- contract label / expiry month (e.g. 2026-09, "U26"),
- price, explicitly tagged **settlement** or **last-trade**,
- as-of date/time,
- venue, currency, and contract unit (per `references/data-sources.md`).

Prefer **settlement** prices for curve work — they are the exchange's official
end-of-session marks and are consistent across months. Fall back to last-trade only
when settlement is unavailable, and label it as such. Never mix settlement and
last-trade silently within one curve; if you must, flag each row.

## 3. Classification

Compare near vs far along the curve:

- **Contango** — far > near, upward-sloping. Typical when storage/financing cost
  exceeds the convenience yield (ample supply).
- **Backwardation** — far < near, downward-sloping. Typical when the convenience yield
  is high (tight prompt supply).
- **Humped / mixed** — the curve rises then falls (or vice versa). Report where it
  flips (e.g. "backwardated in the front, contango beyond M4").

State the classification on the **front pair** and note any change further out.

## 4. Slope

Annualized slope between two chosen contracts (state which two):

```
slope_annualized = (P_far / P_near - 1) / (Δmonths / 12)
```

where `Δmonths` is the whole-month gap between the two contract expiries. Report as a
percent. Positive ⇒ contango, negative ⇒ backwardation. Default to the front pair
(M1→M2); if you use a deferred contract, say so.

## 5. Roll yield (carry approximation)

For a long holder rolling out of the expiring front contract into the next listed
month, the approximate per-roll return is:

```
roll_yield_per_roll = (P_near - P_far) / P_near
```

- Backwardation (`P_near > P_far`) ⇒ **positive** roll yield (you sell high, buy the
  cheaper deferred).
- Contango (`P_near < P_far`) ⇒ **negative** roll yield ("roll drag").

Annualize by scaling to the number of rolls per year implied by the contract spacing,
e.g. `roll_yield_annualized ≈ roll_yield_per_roll × (12 / Δmonths)`.

Caveats to state every time:
- This is an **approximation of carry**, not a realized P&L. Realized roll cost depends
  on the exact roll dates, execution, and how the curve moves between rolls.
- It is sensitive to the **roll convention** (which day you roll, front-to-M2 vs a
  further deferred). Name the convention you assumed.

## 6. Calendar spreads

Absolute price differences between listed months:

```
cal_spread(i, j) = P_i - P_j        (same commodity, same venue, same unit)
```

Report the front spreads (M1–M2, M2–M3). Keep the sign and the unit. A narrowing
contango or a flip to backwardation in the front spread is worth noting descriptively.

## 7. Inter-commodity spreads

Use only clearly-defined, publicly computable spreads, and state the formula/units:

- **Brent–WTI**: `BZ=F − CL=F` (USD/bbl) — location/quality spread between the two
  crude benchmarks.
- **Crack proxy**: e.g. `RB=F × 42 − CL=F` (RBOB is USD/gal; ×42 to USD/bbl) as a
  **rough** gasoline-crack proxy, or heating oil `HO=F × 42 − CL=F`. Label it a proxy —
  it is **not** a refinery 3-2-1 crack.
- **Gold/silver ratio**: `GC=F / SI=F` (dimensionless; both USD/oz).
- **Gold–copper / other ratios**: define units explicitly (copper `HG=F` is USD/lb, so
  a gold–copper comparison must convert or be stated as a ratio of quoted prices).

Only compute a spread when both legs share a consistent, stated unit basis.

## 8. Inventory context (qualitative)

Add public inventory as **background color only**, with the report date:

- **EIA** weekly petroleum status (crude, gasoline, distillate stocks) for oil products.
- **LME** warehouse stocks for base metals (copper, aluminium, …).

High/rising inventory tends to accompany contango; tight/falling inventory tends to
accompany backwardation — but state this as a general tendency, not a rule, and never
turn it into a model input or a signal.

## 9. Pitfalls (document these in the report when they apply)

1. **Continuous-contract splicing distorts levels.** Symbols like `CL=F` are
   continuous front-month series; at each roll the level jumps by the calendar spread.
   Do not read absolute historical levels off a spliced series as if they were one
   contract. State the roll convention and treat spliced history as approximate; for
   the *current* curve, prefer discrete listed months.
2. **Settlement vs last-trade.** These differ, especially for thin deferred months.
   Prefer settlement; label every price.
3. **Currency and unit differences per exchange.** WTI/Brent USD/bbl, gold/silver
   USD/oz, copper USD/lb (COMEX) vs USD/tonne (LME), natural gas USD/MMBtu. Never mix
   units silently; convert explicitly and show the factor.
4. **A curve needs ≥ 2 real months.** If only the front is available, say so and stop —
   do not invent or interpolate a second point.
5. **Thin/illiquid deferreds.** Far months may be stale or gapped; flag low-liquidity
   quotes rather than treating them as firm.
6. **Term structure is carry, not direction.** Contango/backwardation says nothing
   certain about where spot goes next. Keep the language descriptive.

## 10. Graceful degradation

- Only one contract month available ⇒ report the single price with its label and state
  that a term structure cannot be built; do not fabricate a curve.
- Settlement missing ⇒ use last-trade, labelled, and note reduced reliability.
- One venue unreachable ⇒ cross-check against stooq or the alternate exchange page;
  record which source each number came from.
- Inventory series unavailable ⇒ write "无公开可用数据 / no public data used" in the
  inventory section rather than guessing.
- Unit ambiguity unresolved ⇒ report the raw quoted price with its source and flag the
  unit as unconfirmed instead of forcing a conversion.
