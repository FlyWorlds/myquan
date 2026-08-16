# Audit rules

## Severity

- `critical`: the graph is invalid, code cannot parse, or visible code directly uses future observations. Fix before interpreting any result.
- `high`: a defect can materially invalidate research credibility, such as likely timing leakage, hard-coded post-selected universe, missing run evidence, or unknown trial history.
- `medium`: a realistic fragility that requires a sensitivity test or clearer evidence, such as zero slippage, one validation configuration, or implicit data loading.
- `low`: maintainability or auditability weakness that may hide failures but does not independently invalidate the research.
- `info`: important context or missing proof that is not itself a defect.

Severity measures research impact, not implementation effort.

Findings in the `evidence` category never count toward `static_risk`. They describe missing artifacts, which `verdict` and `evidence_level` already express; `static_risk` measures only defects verifiable inside the file. Format-inherent facts that hold for every export (for example, unknown total trial count) are `info` context, not defects.

## Finding format

Every finding must contain:

1. **Defect**: one falsifiable statement.
2. **Evidence**: node, field, value, connection, or code line.
3. **Impact**: how it could distort execution or research credibility.
4. **Optimization**: a concrete change or experiment.

Avoid findings such as "可能过拟合，请注意" without evidence or a next action.

## Static versus empirical claims

Static review may conclude:

- negative shift directly exposes future data;
- graph references are broken;
- code has many configurable decisions;
- a stock universe is hard-coded;
- costs, time windows, and factor settings are fragile;
- required validation evidence is absent.

Static review must not conclude:

- a strategy has a specific probability of being overfit;
- future returns will be positive or negative;
- a high Sharpe survives multiple testing;
- a factor is stable across unseen regimes.

Those claims need empirical artifacts.

## Minimum empirical artifacts

For a single-run performance review, request:

- periodic net returns;
- benchmark and excess returns where relevant;
- positions, turnover, and trade records;
- the exact workflow snapshot used for that run;
- data and cost assumptions.

For statistical overfitting review, additionally request:

- honest total trial count;
- preferably the `T × N` return matrix for all variants;
- development, validation, and sealed test boundaries;
- a research ledger including failed and discarded variants.

Historical workflow versions provide only a lower bound on the trial count.

## Optimization patterns

Match the fix to the defect:

- Timing risk → lag the signal, use next-bar execution, and add a timestamp-alignment test.
- Many tunables → parameter-neighborhood analysis, component ablation, experiment ledger, sealed final test.
- Hard-coded universe → document point-in-time formation rules and include delisted or unavailable names.
- Short or single window → chronological out-of-sample and walk-forward validation across regimes.
- Zero friction → nonzero base case plus several cost and slippage stress levels.
- Implicit data → explicit upstream data node, snapshot hash, retrieval time, adjustment method, and source.
- Missing output → attach run output before discussing performance statistics.
- Missing trial history → mark overfit risk unassessable; never substitute a guessed number.

## Verdict semantics

- `insufficient-evidence`: required artifacts are absent. This does not mean pass or fail.
- `highly-fragile`: visible critical defects make the reported research unreliable.
- `fragile`: multiple material weaknesses remain.
- `mixed`: no decisive invalidation, but important weaknesses remain.
- `credible-under-tested-conditions`: tested checks passed under explicitly bounded conditions. Never shorten this to "credible" or "safe".

