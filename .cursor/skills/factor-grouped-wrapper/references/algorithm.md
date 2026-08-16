# Grouped Wrapper Algorithm

## Candidate evaluation

For each factor tuple, fit the same LightGBM configuration on the training period using equal-date sample weights. Predict the validation period and always calculate daily cross-sectional Pearson IC and Spearman RankIC against the aligned forward return. With `primary_metric: mean_ic`, rank candidates by mean Pearson IC without invoking FactorBacktest. With `primary_metric: sharpe`, write validation predictions, invoke the public FactorBacktest CLI with the configured trading rules and costs, and rank candidates by annualized Sharpe calculated from `hedged_unrealized_pnl.pct_change()`. Use Pearson IC, ICIR, mean RankIC, RankICIR, fewer factors, and the lexical factor tuple as deterministic tie-break evidence. Hash the sorted factors with the mode-specific evaluator version, data cache, and result-affecting configuration so identical factor sets reuse one immutable result within a mode but never across IC and Sharpe modes. Evaluate independent candidates within one greedy iteration with up to `runtime.candidate_workers`; preserve specification order before deterministic ranking. Run independent seed paths with up to `runtime.seed_workers`, but keep dependent iterations inside each path sequential. Optional `runtime.preload_features` loads the eligible train and validation feature union once and gives each candidate only its selected columns.

## Fixed balanced groups

Build groups once per seed and stage. Separate factors by configured source prefixes, deterministically shuffle each source with the stage seed, and place factors into the currently smallest groups. Group sizes therefore differ by at most one and Alpha101/Alpha191 sources are spread across groups. Do not rerandomize groups after an accepted step; intersect the original stage groups with the current factor set.

Default stages:

1. `coarse`: 12 balanced groups.
2. `refine`: groups of at most 10 factors.
3. `singleton`: one factor per group, entered only when the current pool has at most 30 factors unless explicitly configured otherwise.

## Backward elimination

Start with all eligible seed factors. At each iteration evaluate `current - group` for every non-empty active group. Accept only the highest-ranked candidate when `candidate[primary_metric] - baseline[primary_metric] >= min_delta`. Continue within a stage after acceptance. Move to the next finer stage when no group improves. Stop when the final stage has no accepted removal.

## Forward inclusion

When a Backward result exists, use its best completed path as the single pool A selection; otherwise use original A. Start every Forward seed from this same factor tuple and vary only the grouping of the optional external pool B. At each iteration evaluate `current + group`, accept the best improving group, and remove it from the remaining external groups. Stop when no group passes the same acceptance rule. Omit this phase when no external bank is configured.

## Multiple paths and consensus

Run independent deterministic backward paths for every configured seed. Choose pool A by the configured primary metric, then tie-break by Pearson IC, ICIR, mean RankIC, RankICIR, fewer factors, and the lexical factor tuple. Run deterministic forward paths from that fixed pool A and choose the final path with the same ranking. In standalone Forward mode, use original A as the common starting pool. Persist every path separately and record survival frequency as evidence rather than an automatic consensus rule.

## Stage outputs

- `pool_a_selection.json`: input, selected, and removed pool A factors plus the best backward metrics.
- `pool_b_expansion.json`: fixed pool A, pool B candidates, added and rejected factors, and before/after metrics.
- `final_factor_pool.json`: selected pool A factors, added pool B factors, and the exact final factor tuple.
- `development_checkpoint.json`: latest internal path summary used for diagnostics and resume support.

## OOS seal and validation boundary

Validation FactorBacktest results may influence selection only when `primary_metric: sharpe`; they never authorize OOS access. `freeze` records original A and every completed stage result before OOS access. Combined runs freeze `original_a`, `backward_a_star`, and `forward_final`; single-mode runs freeze the baseline plus that mode result. `evaluate-oos` verifies fingerprints, builds one cache for the factor union, refits one LightGBM model per snapshot on train plus validation, and invokes FactorBacktest once per snapshot. Persist each snapshot under `oos/<name>/` so an interrupted aggregate run can reuse completed snapshots. Write the final comparison to `oos_comparison.json`.
