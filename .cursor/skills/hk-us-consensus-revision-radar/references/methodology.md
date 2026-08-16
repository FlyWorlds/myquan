# Methodology

## Metrics

For horizon `h` in `week`, `1month`, `3month`, `6month`, or `12month`:

```text
tp_revision_abs_h = tp_mean_current - tp_mean_h
tp_revision_h = tp_mean_current / tp_mean_h - 1
tp_distance = tp_mean_current / latest_close - 1
dispersion = tp_std / abs(tp_mean_current)
included_ratio = included_estimates_num / estimates_num
estimates_change_abs_h = estimates_num_current - estimates_num_h
estimates_change_ratio_h = estimates_change_abs_h / estimates_num_h
included_estimates_change_abs_h = included_estimates_num_current - included_estimates_num_h
included_estimates_change_ratio_h = included_estimates_change_abs_h / included_estimates_num_h
rating_change_h = recommendation_mean_h - recommendation_mean_current
```

For the PandaData recommendation mean, lower is better. Therefore a lower current mean than the selected historical horizon is a positive descriptive change. All figures are aggregate consensus evidence, not individual analyst records, and do not create an investment recommendation.

## Revision direction

The default `revision_threshold` is `0.01` (1%) and is configurable from the CLI.

- upgrade: `tp_revision_h > revision_threshold`;
- downgrade: `tp_revision_h < -revision_threshold`;
- flat: change is inside or exactly on the threshold boundary;
- unavailable: the current or selected-horizon target mean is missing, or the historical mean is zero.

Classification uses full-precision values. Display rounding never determines direction.

## Ranking rules

- Rank HK and US independently.
- Only securities confirmed by PandaData detail data as active ordinary shares enter rankings. Other security types, inactive securities, missing details, and unknown types remain in diagnostics.
- A row is target-price eligible when `tp_mean` is present, `estimates_num >= min_analysts`, and no severe target validation has failed.
- A row is recommendation-change eligible when current and selected-horizon recommendation means are present, `recommendations_num >= min_recommendations`, and the recommendation mean is in the documented 1–5 range.
- Upgrades and downgrades first satisfy the direction threshold, then sort by `tp_revision` descending or ascending.
- High dispersion sorts `dispersion` descending.
- Recommendation change sorts the independent recommendation-eligible set by absolute `rating_change` descending.
- Price-consensus divergence sorts by absolute `tp_distance` descending.
- Ties use `symbol` ascending for deterministic output.
- Missing metrics remain visible in quality counts but do not enter that metric's ranking.

Coverage and price match rate describe data completeness only. They are not confidence scores and must not be used as predictive weights.

## Time semantics and coverage change

`generated_at` is the HTML generation time. `consensus_retrieved_at` is recorded after both consensus calls for a market return. Neither is a target-price business timestamp. The mapped PandaData aggregate responses do not provide a concrete `date`, `as_of`, or `updated_at`, so `consensus_as_of` and `historical_snapshot_as_of` remain unavailable. The horizon suffix is a provider-defined comparison field, not a derived calendar date.

The report labels the current target mean as the PandaData latest available snapshot. A total-estimate coverage change is `significant` only when both `abs(estimates_change_abs_h) >= 2` and `abs(estimates_change_ratio_h) >= 0.20`. Missing or zero historical denominators never produce a ratio. A significant result only warns that the target-price mean may be affected by aggregate sample-composition change; it does not identify analyst entries, exits, or revisions.

## 修订轨迹矩阵与状态

轨迹矩阵固定展示周度、1个月、3个月、6个月、12个月五个回看期。目标价单元格计算当前目标价均值相对各回看期均值的变化；评级单元格使用“历史评级均值 − 当前评级均值”。评级均值越低代表评级更积极（绝对水平）；历史评级均值 − 当前评级均值越大代表评级改善/更积极（变化）。每个单元格必须同时呈现符号、数值和明确方向文字；缺失值显示为 `—`，颜色只作辅助。

状态为规则化研究分类，不改变榜单排序，不是分析师个人修订，也不构成投资建议。八种状态及触发原则为：持续上修（短期三个窗口至少两个正向）；上修加速（周度和1个月均正向，且周度变化 − 1个月变化严格大于 `revision_threshold`）；上修减速（周度和1个月均正向，且1个月变化 − 周度变化严格大于 `revision_threshold`）；趋势反转待核验（周度与任一较长窗口方向相反）；目标价与评级共振改善（1个月目标价和评级均改善）；目标价与评级信号冲突（两者方向相反）；高分歧待核验（分歧不低于有效核心样本 P75）；覆盖变化待核验（覆盖绝对和相对变化同时达到既有阈值）。

状态的 explanation 是自然语言说明，evidence 是可展开的结构化聚合证据。PandaData 聚合数据无法提供精确历史时间戳或个人分析师信息，故不得把这些状态解释为个人分析师的修订行为、发生时间或广度。

## Event context and timeline

- Event discovery uses a configurable announcement search window: `announcement_query_start = event_reference_date - event_discovery_days`, `announcement_query_end = event_reference_date + event_future_days`.
- Event display uses a configurable view window: `event_window_start = event_reference_date - event_past_days`, `event_window_end = event_reference_date + event_future_days`.
- Exact defaults are `730-day` for discovery and `30/30` for display past/future.
- Dividend/split interfaces use `publish_date` for discovery and `excute_date` for status/effective period representation.
- Other event types use `info_date` for discovery and `start_date` / `end_date` for effective period representation.
- The dedupe key is `market-symbol-category-event_type-start_date-end_date-title`; adjacent-date conflict checks are performed only on valid events with the same market, symbol, and `event_type`, where distinct titles occur within one calendar day.
- Event module status is chained from interface diagnostics and can be `available`, `partial`, `unavailable`, `empty`, or `disabled`.
- Records returned by the event APIs but falling outside the display window are counted in diagnostics and omitted from display. Events outside the announcement query window cannot be discovered by these APIs and therefore cannot be counted downstream; this is the explicit early-discovery limitation.
- Event status does not alter ranking eligibility (does not affect ranking).

## Eligibility funnels

Funnel stages are chained masks, not independent counts. The target-revision funnel is: all records, core universe, current target mean, nonzero historical target mean, minimum target coverage, target validation, and revision-ranking eligibility. Its final count equals `revision_eligible`, the pool used by upgrade and downgrade rankings. High-dispersion and price-divergence rankings intentionally remain on the broader current-target `eligible` pool because they do not require a historical target mean.

The rating funnel is: all records, core universe, current recommendation mean, historical recommendation mean, minimum recommendation coverage, recommendation validation, and rating-ranking eligibility. Its final count equals `rating_eligible`. Each stage reports retention versus the immediately preceding stage; retention is unavailable when the preceding count is zero.

## Assumptions and parameters

- Default horizon: `1month`.
- Default minimum target-price coverage: `5`.
- Default minimum recommendation coverage: `5`.
- Default `revision_threshold`: `0.01`.
- Default ranking length: `20`.
- Latest close means the most recent row returned in the selected daily query window.
- No currency conversion is applied.
- Each symbol is treated as a separate security identifier.

## Core universe and validation

The core universe uses PandaData security-detail evidence. `status == 1` and an asset category containing `Ordinary Share` are both required. Explicit non-ordinary categories are classified conservatively; a missing or unrecognized category is not guessed to be an ordinary share.

Validation never modifies source values:

- `target_range_valid`: when all three values exist, require `tp_low <= tp_mean <= tp_high`;
- `included_count_valid`: when both values exist, require nonnegative counts and `included_estimates_num <= estimates_num`;
- `recommendation_count_valid`: only when all six recommendation buckets and `recommendations_num` exist, compare their sum with the reported total;
- `recommendation_mean_valid`: when present, require the aggregate mean to be in the PandaData 1–5 recommendation range;
- `currency_validation_status`: because the daily interfaces do not return a currency field, the workflow verifies comparability only when the target currency matches the market's standard quote currency (`HKD` for HK, `USD` for US). Missing, unknown, or mismatched currency is not converted and cannot enter the price-divergence ranking. Nonstandard currency counters therefore remain conservatively excluded.

An invalid target range or included-count relationship excludes the row from target-price rankings. An out-of-range current or selected-horizon recommendation mean excludes it from recommendation-change ranking. A recommendation bucket-count mismatch is a warning and does not overwrite any count because provider definitions can differ. Rows with no available checks are `unverified`; rows with only some checks available are `partial`, never a synthetic pass or zero.

## Price validity and fallback

A valid price has a returned date and a numeric close greater than zero. The latest-date query is followed by a 14-calendar-day query for every symbol without a valid close, even when the aggregate match rate is above 90%. The latest valid returned close is selected. A symbol absent from both query responses is `not_returned_by_api`; a returned row without a valid dated positive close is `invalid_or_nonpositive`; missing prices outside the core universe are `outside_core_universe`. The workflow does not infer `no_recent_trade` without direct trading evidence. No zero fill, forward fill, or external-vendor substitution is used.

## Known limitations and risk boundary

Consensus data may be delayed, revised, sparse, or subject to contributor-selection bias. Consensus timestamps and price dates may not align. Security type and status depend on PandaData detail coverage. The method ignores corporate actions, FX, liquidity, costs, taxes, and execution constraints. It has no backtest or demonstrated predictive performance.

The mapped PandaData endpoints provide aggregate consensus. They do not expose individual analyst or broker revision events, so revision breadth, event timing, contributor accuracy, and analyst-level attribution are unavailable. The report must say this explicitly rather than estimating them from aggregate fields. Security identity is displayed as `name · symbol`; a missing name is a disclosed data-quality gap.

The output is only a research and education aid. It is not a factor return claim, trading system, investment recommendation, or guarantee.
