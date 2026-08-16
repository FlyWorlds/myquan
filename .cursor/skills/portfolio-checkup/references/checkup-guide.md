# Portfolio Checkup Guide

Read this guide when generating or revising a portfolio checkup. It is a compact operating manual: weight conventions, concentration math, aggregation rules, risk-exposure thresholds, benchmark deviation, the checkup score, the report blueprint, and a QA checklist. It does not replace the exact Pandadata API documentation — confirm every method's parameters and fields through the `pandadata-api` skill first.

## Default Scope

- Input: a holdings list of A-share common stocks in `XXXXXX.SH` / `XXXXXX.SZ` format, each with a weight or market value, ideally maintained in `portfolio.json`.
- Benchmark: `000300.SH` (沪深300) unless the user names another index.
- Financial window: latest available reports across roughly three fiscal years.
- Price window: latest one year for range return / correlation, unless the user requests another window.
- Event window: next twelve months for restricted-share unlocks; latest available announcements for reductions, pledges, and ST changes.
- Output: Chinese Markdown unless the user requests HTML, Word, or PDF.

## Weight Basis (decide once, use everywhere)

The portfolio is `N` symbols with weights `w_i`. Resolve `w_i` in this order and state which path was used:

1. **User `weight`** — use the given weights. If they are percents, divide by 100. Normalize so `Σ w_i = 1` over the equity sleeve.
2. **User `market_value`** — `w_i = MV_i / Σ MV_j`.
3. **Equal weight fallback** — `w_i = 1 / N`. Use only when neither field exists; label it clearly.

Rules:
- If `cash_weight` is present, hold it aside and normalize equity weights over the remaining `1 - cash_weight`; disclose the cash sleeve and note it dilutes every equity exposure metric.
- If some symbols cannot be priced or mapped, compute aggregates over the **covered weight** `W_cov = Σ_{covered} w_i` and report `W_cov` next to every weighted figure. Never present a partial aggregate as full coverage.
- The same `w_i` basis must feed concentration, weighted valuation/quality, risk exposure, and benchmark deviation. Do not switch bases mid-report.

## Concentration & HHI

Compute from the resolved `w_i` (equity sleeve, normalized to 1):

- **Top-N weight**: `TopN = Σ of the N largest w_i` (report Top1, Top3, Top5, Top10).
- **Effective number of holdings**: `N_eff = 1 / Σ w_i²` — a diversification readout (higher = more diversified).
- **Herfindahl–Hirschman Index (HHI)**: `HHI = Σ w_i²`, with `w_i` as fractions so `HHI ∈ (0, 1]`. Equivalently `HHI = 1 / N_eff`. If you prefer the 0–10000 convention, use percent weights and `HHI = Σ (w_i×100)²`; state which scale you used.
- **Industry HHI**: aggregate `w_i` into industry buckets `W_k = Σ_{i∈k} w_i` (industry from `get_stock_industry`, default level `L1`), then `HHI_ind = Σ W_k²`.
- **Concept exposure**: for each concept of interest, `W_concept = Σ_{i in concept} w_i` using `get_concept_constituents`; a stock may sit in several concepts, so concept weights can overlap and need not sum to 1 — say so.

Default concentration bands (override on request; these describe structure, not a verdict):

| Metric | Diversified | Moderate | Concentrated |
|---|---|---|---|
| HHI (fraction scale) | `< 0.10` | `0.10 – 0.18` | `> 0.18` |
| Top5 weight | `< 40%` | `40% – 60%` | `> 60%` |
| Largest industry weight | `< 25%` | `25% – 40%` | `> 40%` |

## Weighted Valuation & Financial Quality

- **Benchmark valuation reference**: pull the benchmark index PE/PB from `get_index_indicator` (fields `pe_ttm`, `pe_lyr`, `pb_lf`, `pb_ttm`) for the latest available date. This is the comparison baseline; state its data date.
- **Per-stock fundamentals**: pull from `get_fina_reports` (specify `start_quarter`/`end_quarter` or `date`; set `is_latest=True` for the latest disclosed figures) and forward guidance from `get_fina_forecast`. The financial-field set is large — request only the fields you need via `fields` and confirm names against the Pandadata field download referenced in `api-docs.md`.
- **Derived per-stock metrics** (label each with formula + fields, compute only when numerator and denominator exist):
  - Revenue YoY, net-profit YoY (same report period across years).
  - Gross margin, net margin, ROE / ROA when the required fields exist.
  - Asset-liability ratio (leverage).
- **Weighted aggregation**: portfolio metric `X_p = Σ_{i∈cov} (w_i × x_i) / Σ_{i∈cov} w_i`, reported with the covered weight `W_cov`. For PE specifically, prefer the **harmonic / earnings-yield weighting** (`PE_p = 1 / Σ (w_i × E_i/P_i)`) when earnings yields are available, because a simple weighted PE is distorted by loss-makers and very high multiples; if you use simple weighting, say so and exclude or flag negative-PE names.
- **Quality picture**: report the weighted distribution (e.g. weight share with ROE above/below a threshold, weight share with positive vs negative net-profit YoY, weight share with leverage above a threshold) rather than a single blended number when the spread is wide.
- **Forecast-warning share**: from `get_fina_forecast`, `W_warn = Σ w_i` over constituents whose `forecast_type` indicates loss/first-loss/continued-loss/sharp-downward. Report as a portfolio exposure percent with the covered weight.

## Portfolio Risk Exposure Aggregation

The defining capability: convert per-stock event signals into **portfolio exposure percentages**, not per-stock alerts. For each risk, identify the affected constituents, sum their `w_i`, and report the exposure share plus the covered weight and the top contributing names.

| Risk | Method & key fields | Portfolio exposure metric |
|---|---|---|
| Upcoming unlocks | `get_restricted_list` (`relieve_date`, `relieve_shares`, `actual_relieve_shares`, `shareholder_type`) | `W_unlock(window) = Σ w_i` for constituents with an unlock inside the window (default next 90 days). When estimating unlock market value, multiply `actual_relieve_shares × close` (`get_stock_daily`) and express it as a share of the constituent's own market value and of the portfolio; label all market-value figures as estimates. |
| High pledge | `get_stock_pledge` per symbol (`acc_pledge_total_ratio`, `acc_pledged_hold_ratio`, `shareholder_type`, `is_released`) | `W_pledge_high = Σ w_i` for constituents whose latest non-released `acc_pledge_total_ratio` ≥ threshold. Use `get_stock_pledge_stat` only as a market backdrop (it has no symbol and is exchange/registry-level). |
| Reduction plans | `get_stock_shareholder_change` (`direction`, `progress`, `ratio_up_limit`, `shareholder_type`, `begin_date`/`end_date`) | `W_reduce = Σ w_i` for constituents with an active/announced 减持 plan (filter `direction` = 减持 and a non-completed `progress`). Note plan size via `ratio_up_limit` and whether a controller/insider is reducing. |
| ST / delisting risk | `get_stock_status_change` (`type`, `description`, `change_date`) | `W_st = Σ w_i` for constituents currently flagged ST/*ST/退市风险警示 (latest status; an撤销 row clears it). |

Default exposure thresholds (override on request; degrade to qualitative when the denominator is missing):

| Level | Trigger (portfolio exposure) |
|---|---|
| High | `W_unlock(90d)` ≥ 15% of portfolio, or any single constituent with weight ≥ 5% unlocking > 10% of its float inside 90 days. |
| High | `W_pledge_high` ≥ 15% (constituents with `acc_pledge_total_ratio` ≥ 50%). |
| High | `W_st` > 0 (any ST/退市风险 weight in the book). |
| High | `W_reduce` overlaps with `W_warn` on the same names (减持计划 + 业绩预告下修). |
| Medium | `W_unlock(90d)` 5%–15%, or `W_pledge_high` 5%–15% (pledge band 30%–50%), or `W_reduce` ≥ 10%. |
| Low | Isolated small exposure (< 5% weight, stale date, or missing denominator) — record in the appendix rather than the headline risk list. |

State the per-stock threshold (e.g. pledge ≥ 50%) and the resulting portfolio weight share together, and name the top contributors. Combined exposures are named explicitly, e.g. `解禁聚集 + 高质押重叠`, `减持计划 + 业绩预告下修`.

## Benchmark Deviation

- **Benchmark industry weights**: get the benchmark constituents and weights from `get_index_weights(index_symbol=<benchmark>, fields=["index_symbol","stock_symbol","date","weight"])` for the latest available date, then map each constituent to its industry via `get_stock_industry` (default `L1`) and sum to industry weights `B_k`. Report the benchmark weight date and the coverage of the weight field (it can be sparse).
- **Portfolio industry weights** `P_k`: from the same `get_stock_industry` mapping over your holdings and resolved `w_i`.
- **Industry deviation**: `Δ_k = P_k − B_k`. Rank the largest over/underweights. A positive `Δ_k` is an overweight, negative an underweight. Express in percentage points.
- **Active share (optional)**: `ActiveShare = ½ Σ_k |P_k − B_k|` at industry level (or at stock level if you map both to stock weights) — a single 0–100% readout of how far the book sits from the benchmark.
- **Range return & correlation**: build a portfolio daily return series as `r_p(t) = Σ w_i × r_i(t)` from `get_stock_daily` closes (per-stock simple returns), and the benchmark return from `get_index_daily` or the benchmark's own series. Report 20/60/120-trading-day cumulative returns for portfolio vs benchmark, and the correlation of daily returns. State the price window and any symbols missing price history (and their excluded weight).
- **Concentration vs benchmark**: contrast portfolio HHI / Top5 with the benchmark's, when benchmark weights are available, to show whether the book is more concentrated than its yardstick.

## Checkup Score (rubric, not a verdict)

Produce a transparent 0–100 score as a **summary readout**, with every sub-score shown so it is reproducible and overridable. Suggested equal-ish weighting (state the weights you used):

| Dimension | Sub-score basis (higher = healthier) |
|---|---|
| Diversification (25) | HHI / Top5 / largest-industry-weight inside the diversified band. |
| Risk exposure (30) | Low `W_unlock` / `W_pledge_high` / `W_reduce` / `W_st`; deduct for each high-level exposure trigger. |
| Valuation (15) | Weighted PE/PB not stretched vs the benchmark reference. |
| Financial quality (20) | Weight share with positive growth and adequate ROE; low `W_warn` and low leverage exposure. |
| Benchmark fit (10) | Moderate active share / industry deviation unless the user wants concentrated tilts. |

Rules: show each sub-score and its driver; if a dimension's data coverage is low, cap or omit that dimension and renormalize the total, stating the cap. The score is a descriptive summary for research, never a buy/sell signal.

## Report Blueprint

Use this chapter order unless the user asks for a custom structure:

1. `摘要与体检评分`: 3–6 bullets — weight basis and coverage, headline concentration, top risk exposures, benchmark stance, data freshness — plus the checkup score with sub-scores.
2. `组合结构与集中度`: top-N weight, HHI / N_eff, industry HHI, with the concentration bands.
3. `行业与概念暴露 / 基准偏离`: portfolio vs benchmark industry weights, largest over/underweights, active share, concept exposures.
4. `估值与财务质量分布`: weighted PE/PB vs benchmark reference, ROE/growth/leverage distribution, forecast-warning weight share, with report periods.
5. `组合风险敞口聚合`: unlock / pledge / reduction / ST exposure percentages, covered weight, top contributors, named combined exposures.
6. `资金面`（optional）: northbound / margin / 龙虎榜 activity summarized across constituents.
7. `行动建议（仅风险提示）`: watch items and exposures to monitor — no buy/sell language.
8. `数据附录`: method-by-method source table with query window, returned rows, latest date / report period, covered weight, and caveats.

## Evidence & Output Requirements

- Include an appendix source table with columns like: `模块`, `来源接口`, `查询窗口`, `返回行数`, `最新日期/报告期`, `覆盖权重`, `备注`.
- Beside every weighted aggregate, show the weight basis and covered weight `W_cov`.
- For each risk exposure, show the per-stock trigger, the summed portfolio weight, and the top contributing constituents with their individual weights.
- Keep empty sections with their heading and a "无数据 + 方法/窗口" note.
- Prefer compact tables over long prose; keep tone analytical and non-promotional.

## Final QA Checklist

- Weight basis is stated once and used consistently; weights (plus any cash) reconcile to 100%.
- Every weighted figure shows its covered weight; partial coverage is flagged, not rounded to full.
- HHI, Top-N, deviation, exposure %, and the score are reproducible from the formulas here.
- `get_stock_pledge` (per symbol) is used for pledge exposure; `get_stock_pledge_stat` is treated as market backdrop only.
- Market-value figures derived from price × shares are labeled as estimates.
- Risk reported as portfolio exposure, with single-stock deep dives delegated to `a-share-stock-dossier` and per-stock time-triggered alerts delegated to `event-risk-alert`.
- Data date / report period appears in each section; empty data is disclosed.
- Action section is risk-only; final disclaimer present exactly as required by `SKILL.md`.
