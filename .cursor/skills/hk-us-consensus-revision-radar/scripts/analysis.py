"""Deterministic research metrics for consensus revision analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd


TRAJECTORY_HORIZONS = ("week", "1month", "3month", "6month", "12month")
HORIZONS = TRAJECTORY_HORIZONS
RECOMMENDATION_BUCKETS = (
    "strong_buy_num", "buy_num", "hold", "sell_num", "strong_sell_num",
    "no_opinion_num",
)
STATE_DISCLAIMER = "状态为规则化研究分类，不改变榜单排序，不构成投资建议。"


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, np.nan)
    return numerator / denominator


def _state(
    key: str,
    label: str,
    explanation: str,
    evidence: object,
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "explanation": explanation,
        "evidence": evidence,
        "disclaimer": STATE_DISCLAIMER,
    }


def _evidence_number(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(numeric) or not np.isfinite(numeric) else float(numeric)


def _target_evidence(
    row: pd.Series, horizon: str, revision_threshold: float
) -> dict[str, object]:
    current = _evidence_number(row.get("tp_mean"))
    historical = _evidence_number(row.get(f"tp_mean_{horizon}"))
    change = (
        None if current is None or historical is None or historical == 0
        else current / historical - 1
    )
    if change is not None and not np.isfinite(change):
        change = None
    epsilon = 1e-12
    if change is None:
        direction = "unavailable"
    elif change > revision_threshold + epsilon:
        direction = "positive"
    elif change < -revision_threshold - epsilon:
        direction = "negative"
    else:
        direction = "flat"
    return {
        "horizon": horizon,
        "current": current,
        "historical": historical,
        "change": change,
        "direction": direction,
        "threshold": revision_threshold,
    }


def _rating_evidence(
    row: pd.Series, horizon: str, revision_threshold: float
) -> dict[str, object]:
    current = _evidence_number(row.get("rec_mean"))
    historical = _evidence_number(row.get(f"rec_mean_{horizon}"))
    change = None if current is None or historical is None else historical - current
    if change is not None and not np.isfinite(change):
        change = None
    epsilon = 1e-12
    if change is None:
        direction = "unavailable"
    elif change > revision_threshold + epsilon:
        direction = "positive"
    elif change < -revision_threshold - epsilon:
        direction = "negative"
    else:
        direction = "flat"
    return {
        "horizon": horizon,
        "current": current,
        "historical": historical,
        "change": change,
        "direction": direction,
        "threshold": revision_threshold,
        "formula": "历史评级均值 − 当前评级均值",
    }


def build_consensus_states(
    frame: pd.DataFrame,
    revision_threshold: float,
    horizon: str = "1month",
) -> pd.DataFrame:
    """Attach explainable, non-ranking consensus-revision research states."""
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of: {', '.join(HORIZONS)}")
    if not 0 <= revision_threshold <= 1:
        raise ValueError("revision_threshold must be between 0 and 1")

    result = frame.copy()
    universe_eligible = result.get(
        "universe_eligible", pd.Series(False, index=result.index)
    ).fillna(False).astype(bool)
    dispersion = _numeric(result, "dispersion")
    dispersion_sample = dispersion.loc[universe_eligible & np.isfinite(dispersion)]
    dispersion_p75 = (
        float(dispersion_sample.quantile(0.75)) if not dispersion_sample.empty else np.nan
    )
    dispersion_sample_count = int(len(dispersion_sample))
    result["dispersion_p75"] = dispersion_p75
    result["dispersion_sample_count"] = dispersion_sample_count

    all_states: list[list[dict[str, object]]] = []
    for index, row in result.iterrows():
        target = {
            horizon: _target_evidence(row, horizon, revision_threshold)
            for horizon in TRAJECTORY_HORIZONS
        }
        rating = {
            horizon: _rating_evidence(row, horizon, revision_threshold)
            for horizon in TRAJECTORY_HORIZONS
        }
        states: list[dict[str, object]] = []
        positive_short = [
            horizon for horizon in ("week", "1month", "3month")
            if target[horizon]["direction"] == "positive"
        ]
        if len(positive_short) >= 2:
            states.append(_state(
                "sustained_upgrade", "持续上修",
                "周度、1个月和3个月目标价修订中至少两个为正向，显示上修在多个回看期持续出现。",
                [target[horizon] for horizon in positive_short],
            ))

        week_change = target["week"]["change"]
        month_change = target["1month"]["change"]
        both_positive = (
            target["week"]["direction"] == "positive"
            and target["1month"]["direction"] == "positive"
        )
        if both_positive and week_change - month_change > revision_threshold:
            states.append(_state(
                "accelerating_upgrade", "上修加速",
                "周度目标价正向修订幅度严格大于1个月修订幅度，且两者均超过阈值。",
                [target["week"], target["1month"]],
            ))
        if both_positive and month_change - week_change > revision_threshold:
            states.append(_state(
                "decelerating_upgrade", "上修减速",
                "周度目标价仍为正向，但严格小于1个月修订幅度；两者均超过阈值。",
                [target["week"], target["1month"]],
            ))

        weekly_direction = target["week"]["direction"]
        opposing = [
            horizon for horizon in ("1month", "3month", "6month", "12month")
            if weekly_direction in {"positive", "negative"}
            and target[horizon]["direction"] in {"positive", "negative"}
            and target[horizon]["direction"] != weekly_direction
        ]
        if opposing:
            states.append(_state(
                "trend_reversal", "趋势反转待核验",
                "周度目标价方向与至少一个较长回看期方向相反，需要结合数据时点进一步核验。",
                [target["week"]] + [target[horizon] for horizon in opposing],
            ))

        target_month = target["1month"]
        rating_month = rating["1month"]
        if (
            target_month["direction"] == "positive"
            and rating_month["direction"] == "positive"
        ):
            states.append(_state(
                "target_rating_resonance", "目标价与评级共振改善",
                "1个月目标价和评级均为正向；评级变化按“历史评级均值 − 当前评级均值”计算，数值越大代表更积极。",
                [target_month, rating_month],
            ))
        if (
            target_month["direction"] in {"positive", "negative"}
            and rating_month["direction"] in {"positive", "negative"}
            and target_month["direction"] != rating_month["direction"]
        ):
            states.append(_state(
                "signal_conflict", "目标价与评级信号冲突",
                "1个月目标价与评级均有明确方向，但方向相反；评级变化按“历史评级均值 − 当前评级均值”计算。",
                [target_month, rating_month],
            ))

        current_dispersion = _evidence_number(row.get("dispersion"))
        if (
            bool(universe_eligible.loc[index])
            and current_dispersion is not None
            and not pd.isna(dispersion_p75)
            and current_dispersion >= dispersion_p75
        ):
            states.append(_state(
                "high_dispersion_review", "高分歧待核验",
                "当前目标价分歧不低于核心普通股有效样本的第75百分位，需要关注一致预期分布差异。",
                {
                    "current": current_dispersion,
                    "p75": dispersion_p75,
                    "sample_count": dispersion_sample_count,
                },
            ))

        coverage_status = row.get("coverage_change_status")
        coverage_current = _evidence_number(row.get("estimates_num"))
        coverage_historical = _evidence_number(row.get(f"estimates_num_{horizon}"))
        coverage_change = _evidence_number(row.get("estimates_change_abs"))
        coverage_change_ratio = _evidence_number(
            row.get("estimates_change_ratio")
        )
        if coverage_status == "significant" and all(
            value is not None for value in (
                coverage_current,
                coverage_historical,
                coverage_change,
                coverage_change_ratio,
            )
        ):
            horizon_label = {
                "week": "周度",
                "1month": "1个月",
                "3month": "3个月",
                "6month": "6个月",
                "12month": "12个月",
            }[horizon]
            states.append(_state(
                "coverage_change_review", "覆盖变化待核验",
                f"所选{horizon_label}回看期的分析师覆盖变化达到既有显著门槛，目标价均值变化可能受样本构成影响。",
                {
                    "horizon": horizon,
                    "current": coverage_current,
                    "historical": coverage_historical,
                    "change": coverage_change,
                    "change_ratio": coverage_change_ratio,
                    "threshold": {"absolute": 2, "ratio": 0.20},
                    "status": coverage_status,
                },
            ))
        all_states.append(states)

    result["consensus_states"] = all_states
    return result


def compute_metrics(
    frame: pd.DataFrame,
    horizon: str = "1month",
    revision_threshold: float = 0.01,
) -> pd.DataFrame:
    """Return a copy with documented, non-prescriptive consensus metrics."""
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of: {', '.join(HORIZONS)}")
    if not 0 <= revision_threshold <= 1:
        raise ValueError("revision_threshold must be between 0 and 1")

    result = frame.copy()
    tp_mean = _numeric(result, "tp_mean")
    tp_history = _numeric(result, f"tp_mean_{horizon}")
    close = _numeric(result, "close")
    tp_std = _numeric(result, "tp_std")
    estimates = _numeric(result, "estimates_num")
    included_estimates = _numeric(result, "included_estimates_num")
    recommendations = _numeric(result, "recommendations_num")

    result["tp_revision_abs"] = tp_mean - tp_history
    result["tp_revision"] = _safe_ratio(tp_mean, tp_history) - 1
    market_currency = result.get(
        "market", pd.Series(pd.NA, index=result.index, dtype="object")
    ).astype("string").str.lower().map({"hk": "HKD", "us": "USD"})
    target_currency = result.get(
        "tp_currency", pd.Series(pd.NA, index=result.index, dtype="object")
    ).astype("string").str.upper()
    currency_status = np.select(
        [
            target_currency.isna(),
            market_currency.isna(),
            target_currency.eq(market_currency).fillna(False),
        ],
        ["currency_missing", "market_currency_unknown", "verified"],
        default="currency_mismatch",
    )
    result["currency_validation_status"] = currency_status
    result["price_currency_verified"] = pd.Series(currency_status, index=result.index).eq(
        "verified"
    )
    result["tp_distance"] = (_safe_ratio(tp_mean, close) - 1).where(
        result["price_currency_verified"]
    )
    result["dispersion"] = _safe_ratio(tp_std, tp_mean.abs())
    result["included_ratio"] = _safe_ratio(included_estimates, estimates)

    historical_estimates = _numeric(result, f"estimates_num_{horizon}")
    historical_included = _numeric(result, f"included_estimates_num_{horizon}")
    result["estimates_change_abs"] = estimates - historical_estimates
    result["estimates_change_ratio"] = _safe_ratio(
        result["estimates_change_abs"], historical_estimates
    )
    result["included_estimates_change_abs"] = (
        included_estimates - historical_included
    )
    result["included_estimates_change_ratio"] = _safe_ratio(
        result["included_estimates_change_abs"], historical_included
    )
    estimates_change = _numeric(result, "estimates_change_abs")
    estimates_change_ratio = _numeric(result, "estimates_change_ratio")
    coverage_comparable = (
        np.isfinite(estimates) & np.isfinite(historical_estimates)
        & np.isfinite(estimates_change) & np.isfinite(estimates_change_ratio)
        & historical_estimates.ne(0)
    )
    significant_coverage_change = (
        coverage_comparable
        & estimates_change.abs().ge(2)
        & estimates_change_ratio.abs().ge(0.20)
    )
    result["coverage_change_status"] = np.select(
        [significant_coverage_change, coverage_comparable],
        ["significant", "stable_or_minor"],
        default="unavailable",
    )
    result["coverage_change_note"] = pd.Series(
        pd.NA, index=result.index, dtype="object"
    )
    result.loc[significant_coverage_change, "coverage_change_note"] = (
        "目标价均值变化可能受到聚合样本构成变化影响"
    )

    epsilon = 1e-12
    revision = _numeric(result, "tp_revision")
    revision_available = revision.notna() & np.isfinite(revision)
    result["revision_direction"] = np.select(
        [
            revision_available & revision.gt(revision_threshold + epsilon),
            revision_available & revision.lt(-revision_threshold - epsilon),
            revision_available,
        ],
        ["upgrade", "downgrade", "flat"],
        default="unavailable",
    )

    rating_numerator = (
        2 * _numeric(result, "strong_buy_num")
        + _numeric(result, "buy_num")
        - _numeric(result, "sell_num")
        - 2 * _numeric(result, "strong_sell_num")
    )
    result["rating_score"] = _safe_ratio(rating_numerator, recommendations)
    result["rating_change"] = (
        _numeric(result, f"rec_mean_{horizon}") - _numeric(result, "rec_mean")
    )
    rating_change = _numeric(result, "rating_change")
    rating_change_available = rating_change.notna() & np.isfinite(rating_change)
    result["rating_direction"] = np.select(
        [
            rating_change_available & rating_change.gt(0),
            rating_change_available & rating_change.lt(0),
            rating_change_available,
        ],
        ["improved", "weakened", "unchanged"],
        default="unavailable",
    )
    for period in TRAJECTORY_HORIZONS:
        trajectory_tp_history = _numeric(result, f"tp_mean_{period}")
        trajectory_rating_history = _numeric(result, f"rec_mean_{period}")
        tp_revision = (_safe_ratio(tp_mean, trajectory_tp_history) - 1) * 100
        rating_change = trajectory_rating_history - _numeric(result, "rec_mean")
        result[f"tp_revision_{period}"] = tp_revision
        result[f"rating_change_{period}"] = rating_change
        tp_revision_available = tp_revision.notna() & np.isfinite(tp_revision)
        rating_change_available = rating_change.notna() & np.isfinite(rating_change)
        result[f"tp_direction_{period}"] = np.select(
            [
                tp_revision_available
                & tp_revision.gt((revision_threshold + epsilon) * 100),
                tp_revision_available
                & tp_revision.lt(-(revision_threshold + epsilon) * 100),
                tp_revision_available,
            ],
            ["positive", "negative", "flat"],
            default="unavailable",
        )
        result[f"rating_direction_{period}"] = np.select(
            [
                rating_change_available
                & rating_change.gt(revision_threshold + epsilon),
                rating_change_available
                & rating_change.lt(-(revision_threshold + epsilon)),
                rating_change_available,
            ],
            ["positive", "negative", "flat"],
            default="unavailable",
        )
    result["analysis_horizon"] = horizon
    result["revision_threshold"] = revision_threshold
    result = _add_validation_fields(result, horizon)
    return result


def _nullable_check(
    available: pd.Series, condition: pd.Series
) -> pd.Series:
    output = pd.Series(pd.NA, index=available.index, dtype="boolean")
    output.loc[available] = condition.loc[available].astype(bool)
    return output


def _add_validation_fields(frame: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Add row-level validation evidence without changing PandaData source values."""
    result = frame.copy()
    tp_low = _numeric(result, "tp_low")
    tp_mean = _numeric(result, "tp_mean")
    tp_high = _numeric(result, "tp_high")
    target_available = tp_low.notna() & tp_mean.notna() & tp_high.notna()
    result["target_range_valid"] = _nullable_check(
        target_available, tp_low.le(tp_mean) & tp_mean.le(tp_high)
    )

    estimates = _numeric(result, "estimates_num")
    included = _numeric(result, "included_estimates_num")
    included_available = estimates.notna() & included.notna()
    result["included_count_valid"] = _nullable_check(
        included_available,
        included.ge(0) & estimates.ge(0) & included.le(estimates),
    )

    bucket_columns_available = pd.Series(True, index=result.index)
    bucket_values: list[pd.Series] = []
    for column in RECOMMENDATION_BUCKETS:
        values = _numeric(result, column)
        bucket_values.append(values)
        bucket_columns_available &= values.notna()
    recommendation_count = _numeric(result, "recommendations_num")
    bucket_columns_available &= recommendation_count.notna()
    if bucket_values:
        bucket_sum = sum(bucket_values[1:], bucket_values[0])
    else:  # pragma: no cover - constant bucket definition
        bucket_sum = pd.Series(np.nan, index=result.index)
    result["recommendation_bucket_sum"] = bucket_sum.where(bucket_columns_available)
    result["recommendation_count_valid"] = _nullable_check(
        bucket_columns_available,
        bucket_sum.sub(recommendation_count).abs().le(1e-9),
    )

    rec_mean = _numeric(result, "rec_mean")
    result["recommendation_mean_valid"] = _nullable_check(
        rec_mean.notna(), rec_mean.between(1, 5, inclusive="both")
    )
    rec_history_mean = _numeric(result, f"rec_mean_{horizon}")
    result["recommendation_history_mean_valid"] = _nullable_check(
        rec_history_mean.notna(),
        rec_history_mean.between(1, 5, inclusive="both"),
    )

    target_invalid = (
        result["target_range_valid"].eq(False).fillna(False)
        | result["included_count_valid"].eq(False).fillna(False)
    )
    recommendation_invalid = (
        result["recommendation_mean_valid"].eq(False).fillna(False)
        | result["recommendation_history_mean_valid"].eq(False).fillna(False)
    )
    recommendation_warning = result["recommendation_count_valid"].eq(False).fillna(False)
    result["target_validation_valid"] = ~target_invalid
    result["recommendation_validation_valid"] = ~recommendation_invalid

    issues: list[str] = []
    statuses: list[str] = []
    for index in result.index:
        row_issues: list[str] = []
        if result.at[index, "target_range_valid"] is not pd.NA and not bool(
            result.at[index, "target_range_valid"]
        ):
            row_issues.append("target_range_invalid")
        if result.at[index, "included_count_valid"] is not pd.NA and not bool(
            result.at[index, "included_count_valid"]
        ):
            row_issues.append("included_count_exceeds_coverage")
        if result.at[index, "recommendation_count_valid"] is not pd.NA and not bool(
            result.at[index, "recommendation_count_valid"]
        ):
            row_issues.append("recommendation_bucket_count_mismatch")
        if result.at[index, "recommendation_mean_valid"] is not pd.NA and not bool(
            result.at[index, "recommendation_mean_valid"]
        ):
            row_issues.append("recommendation_mean_out_of_range")
        if result.at[index, "recommendation_history_mean_valid"] is not pd.NA and not bool(
            result.at[index, "recommendation_history_mean_valid"]
        ):
            row_issues.append("recommendation_history_mean_out_of_range")
        issues.append(";".join(row_issues))
        if bool(target_invalid.loc[index] or recommendation_invalid.loc[index]):
            statuses.append("error")
        elif bool(recommendation_warning.loc[index]):
            statuses.append("warning")
        elif row_issues:
            statuses.append("warning")
        else:
            checks = [
                result.at[index, column]
                for column in (
                "target_range_valid", "included_count_valid",
                "recommendation_count_valid", "recommendation_mean_valid",
                "recommendation_history_mean_valid",
                )
            ]
            completed = sum(pd.notna(value) for value in checks)
            if completed == 0:
                statuses.append("unverified")
            elif completed < len(checks):
                statuses.append("partial")
            else:
                statuses.append("pass")
    result["validation_issues"] = issues
    result["validation_status"] = statuses
    return result


def _rank(
    frame: pd.DataFrame,
    column: str,
    ascending: bool,
    limit: int,
    absolute: bool = False,
) -> pd.DataFrame:
    if column not in frame.columns:
        return frame.iloc[0:0].copy().reset_index(drop=True)
    ranked = frame.loc[frame[column].notna()].copy()
    ranked["_rank_value"] = ranked[column].abs() if absolute else ranked[column]
    ranked = ranked.sort_values(
        ["_rank_value", "symbol"],
        ascending=[ascending, True],
        kind="mergesort",
    )
    return ranked.drop(columns="_rank_value").head(limit).reset_index(drop=True)


def build_rankings(
    frame: pd.DataFrame,
    min_analysts: int = 5,
    limit: int = 20,
    min_recommendations: int = 5,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Build separate HK/US research views after the coverage threshold."""
    if min_analysts < 1:
        raise ValueError("min_analysts must be at least 1")
    if min_recommendations < 1:
        raise ValueError("min_recommendations must be at least 1")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    output: dict[str, dict[str, pd.DataFrame]] = {}
    markets = sorted(set(frame.get("market", pd.Series(dtype=str)).dropna().astype(str)))
    for market in markets:
        market_frame = frame.loc[frame["market"] == market].copy()
        universe_eligible = market_frame.get(
            "universe_eligible", pd.Series(True, index=market_frame.index)
        ).fillna(False).astype(bool)
        target_validation = market_frame.get(
            "target_validation_valid", pd.Series(True, index=market_frame.index)
        ).fillna(True).astype(bool)
        recommendation_validation = market_frame.get(
            "recommendation_validation_valid", pd.Series(True, index=market_frame.index)
        ).fillna(True).astype(bool)
        coverage = _numeric(market_frame, "estimates_num")
        tp_mean = _numeric(market_frame, "tp_mean")
        eligible_mask = (
            universe_eligible & target_validation
            & tp_mean.notna() & coverage.ge(min_analysts)
        )
        eligible = market_frame.loc[eligible_mask].sort_values("symbol").reset_index(drop=True)
        exclusions = market_frame.loc[~eligible_mask]
        recommendation_coverage = _numeric(market_frame, "recommendations_num")
        rating_mask = (
            universe_eligible & recommendation_validation
            & recommendation_coverage.ge(min_recommendations)
            & _numeric(market_frame, "rec_mean").notna()
            & _numeric(market_frame, "rating_change").notna()
        )
        rating_eligible = market_frame.loc[rating_mask].sort_values("symbol").reset_index(drop=True)
        revision_mask = eligible_mask & _numeric(market_frame, "tp_revision").notna()
        revision_eligible = market_frame.loc[revision_mask].sort_values(
            "symbol"
        ).reset_index(drop=True)

        revision_direction = revision_eligible.get(
            "revision_direction",
            pd.Series(pd.NA, index=revision_eligible.index, dtype="object"),
        )
        output[market] = {
            "eligible": eligible,
            "revision_eligible": revision_eligible,
            "upgrades": _rank(
                revision_eligible.loc[revision_direction.eq("upgrade")],
                "tp_revision", False, limit,
            ),
            "downgrades": _rank(
                revision_eligible.loc[revision_direction.eq("downgrade")],
                "tp_revision", True, limit,
            ),
            "high_dispersion": _rank(eligible, "dispersion", False, limit),
            "rating_eligible": rating_eligible,
            "rating_changes": _rank(
                rating_eligible, "rating_change", False, limit, absolute=True
            ),
            "price_consensus_divergence": _rank(
                eligible, "tp_distance", False, limit, absolute=True
            ),
            "coverage_exclusions": exclusions.sort_values("symbol").reset_index(drop=True),
            "universe_exclusions": market_frame.loc[~universe_eligible].sort_values(
                "symbol"
            ).reset_index(drop=True),
        }
    return output


def _funnel_records(stages: list[tuple[str, str, pd.Series]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    previous_count: int | None = None
    for key, label, mask in stages:
        count = int(mask.fillna(False).astype(bool).sum())
        retention = (
            count / previous_count
            if previous_count is not None and previous_count > 0
            else None
        )
        records.append({
            "key": key,
            "label": label,
            "count": count,
            "retention": retention,
        })
        previous_count = count
    return records


def build_eligibility_funnels(
    frame: pd.DataFrame,
    horizon: str = "1month",
    min_analysts: int = 5,
    min_recommendations: int = 5,
) -> dict[str, list[dict[str, object]]]:
    """Build chained, auditable eligibility stages for one market payload."""
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of: {', '.join(HORIZONS)}")
    if min_analysts < 1 or min_recommendations < 1:
        raise ValueError("coverage thresholds must be at least 1")

    all_rows = pd.Series(True, index=frame.index, dtype=bool)
    core = all_rows & frame.get(
        "universe_eligible", pd.Series(True, index=frame.index)
    ).fillna(False).astype(bool)

    target_current = core & _numeric(frame, "tp_mean").notna()
    target_history = (
        target_current
        & _numeric(frame, f"tp_mean_{horizon}").notna()
        & _numeric(frame, f"tp_mean_{horizon}").ne(0)
    )
    target_coverage = target_history & _numeric(frame, "estimates_num").ge(
        min_analysts
    )
    target_validation = target_coverage & frame.get(
        "target_validation_valid", pd.Series(True, index=frame.index)
    ).fillna(True).astype(bool)
    target_eligible = target_validation & _numeric(frame, "tp_revision").notna()

    rating_current = core & _numeric(frame, "rec_mean").notna()
    rating_history = rating_current & _numeric(
        frame, f"rec_mean_{horizon}"
    ).notna()
    rating_coverage = rating_history & _numeric(
        frame, "recommendations_num"
    ).ge(min_recommendations)
    rating_validation = rating_coverage & frame.get(
        "recommendation_validation_valid", pd.Series(True, index=frame.index)
    ).fillna(True).astype(bool)
    rating_eligible = rating_validation & _numeric(frame, "rating_change").notna()

    return {
        "target_revision": _funnel_records([
            ("total", "全部记录", all_rows),
            ("core_universe", "核心普通股", core),
            ("current_target", "有当前目标价均值", target_current),
            ("historical_target", f"有 {horizon} 回看快照", target_history),
            ("target_coverage", f"目标价覆盖 ≥ {min_analysts}", target_coverage),
            ("target_validation", "通过目标价一致性校验", target_validation),
            ("revision_eligible", "修订榜可排名", target_eligible),
        ]),
        "rating": _funnel_records([
            ("total", "全部记录", all_rows),
            ("core_universe", "核心普通股", core),
            ("current_rating", "有当前推荐均值", rating_current),
            ("historical_rating", f"有 {horizon} 回看快照", rating_history),
            ("rating_coverage", f"评级覆盖 ≥ {min_recommendations}", rating_coverage),
            ("rating_validation", "通过评级一致性校验", rating_validation),
            ("rating_eligible", "评级榜可排名", rating_eligible),
        ]),
    }


def _coverage(present: pd.Series, total: int) -> float | None:
    return float(present.sum() / total) if total else None


def build_quality_summary(
    frame: pd.DataFrame,
    min_analysts: int = 5,
    min_recommendations: int = 5,
) -> dict[str, object]:
    total = int(len(frame))
    tp_present = frame.get("tp_mean", pd.Series(np.nan, index=frame.index)).notna()
    coverage = _numeric(frame, "estimates_num")
    coverage_missing = coverage.isna()
    coverage_low = coverage.notna() & coverage.lt(min_analysts)
    universe_eligible = frame.get(
        "universe_eligible", pd.Series(True, index=frame.index)
    ).fillna(False).astype(bool)
    target_validation = frame.get(
        "target_validation_valid", pd.Series(True, index=frame.index)
    ).fillna(True).astype(bool)
    eligible = universe_eligible & target_validation & tp_present & coverage.ge(min_analysts)
    name_present = frame.get("name", pd.Series(pd.NA, index=frame.index)).notna()
    price_present = _numeric(frame, "close").gt(0)
    history_present = frame.get(
        "tp_revision", pd.Series(np.nan, index=frame.index)
    ).notna()
    recommendation_present = frame.get(
        "recommendations_num", pd.Series(np.nan, index=frame.index)
    ).notna()
    recommendation_coverage = _numeric(frame, "recommendations_num")
    recommendation_coverage_missing = recommendation_coverage.isna()
    recommendation_coverage_low = (
        recommendation_coverage.notna()
        & recommendation_coverage.lt(min_recommendations)
    )
    recommendation_validation = frame.get(
        "recommendation_validation_valid", pd.Series(True, index=frame.index)
    ).fillna(True).astype(bool)
    rating_eligible = (
        universe_eligible & recommendation_validation
        & recommendation_coverage.ge(min_recommendations)
        & _numeric(frame, "rec_mean").notna()
        & _numeric(frame, "rating_change").notna()
    )
    distance_present = frame.get(
        "tp_distance", pd.Series(np.nan, index=frame.index)
    ).notna()
    scatter_eligible = history_present & distance_present
    reason_values = frame.get(
        "price_missing_reason", pd.Series(pd.NA, index=frame.index)
    ).dropna().astype(str).value_counts()
    price_missing_reasons = {str(key): int(value) for key, value in reason_values.items()}
    exclusion_values = frame.get(
        "universe_exclusion_reason", pd.Series(pd.NA, index=frame.index)
    ).dropna().astype(str).value_counts()
    universe_exclusion_reasons = {
        str(key): int(value) for key, value in exclusion_values.items()
    }
    validation_status = frame.get(
        "validation_status", pd.Series("unverified", index=frame.index)
    ).fillna("unverified").astype(str)
    currency_status = frame.get(
        "currency_validation_status", pd.Series("currency_missing", index=frame.index)
    ).fillna("currency_missing").astype(str)
    return {
        "total_rows": total,
        "core_universe_rows": int(universe_eligible.sum()),
        "excluded_universe_rows": int((~universe_eligible).sum()),
        "eligible_rows": int(eligible.sum()),
        "rating_eligible_rows": int(rating_eligible.sum()),
        "missing_recommendation_coverage": int(recommendation_coverage_missing.sum()),
        "excluded_low_recommendation_coverage": int(
            recommendation_coverage_low.sum()
        ),
        "missing_coverage": int(coverage_missing.sum()),
        "excluded_low_coverage": int((tp_present & coverage_low).sum()),
        "missing_name": int((~name_present).sum()),
        "missing_target_price": int((~tp_present).sum()),
        "missing_price": int((~price_present).sum()),
        "missing_history": int((~history_present).sum()),
        "missing_recommendation": int((~recommendation_present).sum()),
        "scatter_eligible_rows": int(scatter_eligible.sum()),
        "validation_error_rows": int(validation_status.eq("error").sum()),
        "validation_warning_rows": int(validation_status.eq("warning").sum()),
        "validation_unverified_rows": int(validation_status.eq("unverified").sum()),
        "validation_partial_rows": int(validation_status.eq("partial").sum()),
        "currency_verified_rows": int(currency_status.eq("verified").sum()),
        "currency_mismatch_rows": int(currency_status.eq("currency_mismatch").sum()),
        "currency_unverified_rows": int((~currency_status.eq("verified")).sum()),
        "price_missing_reasons": price_missing_reasons,
        "universe_exclusion_reasons": universe_exclusion_reasons,
        "name_coverage": _coverage(name_present, total),
        "price_coverage": _coverage(price_present, total),
        "history_coverage": _coverage(history_present, total),
        "recommendation_coverage": _coverage(recommendation_present, total),
        "scatter_coverage": _coverage(scatter_eligible, total),
    }
