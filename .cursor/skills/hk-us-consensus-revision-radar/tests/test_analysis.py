import unittest

import numpy as np
import pandas as pd

import scripts.analysis as analysis
from scripts.analysis import (
    build_consensus_states, build_eligibility_funnels, build_quality_summary, build_rankings,
    compute_metrics,
)


class AnalysisTests(unittest.TestCase):
    def test_consensus_state_acceleration_requires_change_gap_strictly_above_threshold(self):
        frame = pd.DataFrame([
            {"symbol": "NEAR", "tp_mean": 101.10, "tp_mean_week": 100.0,
             "tp_mean_1month": 100.05},
            {"symbol": "ACCEL", "tp_mean": 102.10, "tp_mean_week": 100.0,
             "tp_mean_1month": 101.04},
            {"symbol": "DECEL", "tp_mean": 102.10, "tp_mean_week": 101.04,
             "tp_mean_1month": 100.0},
        ])

        rows = build_consensus_states(frame, revision_threshold=0.01).set_index("symbol")
        keys = lambda symbol: {state["key"] for state in rows.at[symbol, "consensus_states"]}

        self.assertNotIn("accelerating_upgrade", keys("NEAR"))
        self.assertNotIn("decelerating_upgrade", keys("NEAR"))
        self.assertIn("accelerating_upgrade", keys("ACCEL"))
        self.assertIn("decelerating_upgrade", keys("DECEL"))

    def test_consensus_states_treat_non_finite_values_as_unavailable(self):
        frame = pd.DataFrame([
            {"symbol": "NONFINITE", "universe_eligible": True, "tp_mean": np.inf,
             "tp_mean_week": 100.0, "tp_mean_1month": np.inf,
             "rec_mean": np.nan, "rec_mean_1month": -np.inf,
             "dispersion": np.inf},
        ])

        result = build_consensus_states(frame, revision_threshold=0.01).iloc[0]

        self.assertEqual(result["consensus_states"], [])
        self.assertTrue(np.isnan(result["dispersion_p75"]))
        self.assertEqual(result["dispersion_sample_count"], 0)

    def test_consensus_states_emit_multiple_labels_with_evidence(self):
        frame = pd.DataFrame([{
            "symbol": "A", "universe_eligible": True, "tp_mean": 110.0,
            "tp_mean_week": 95.0, "tp_mean_1month": 100.0,
            "tp_mean_3month": 90.0, "tp_mean_6month": 100.0,
            "tp_mean_12month": 110.0, "rec_mean": 1.8,
            "rec_mean_1month": 2.2, "dispersion": 0.30,
            "coverage_change_status": "significant",
            "estimates_num": 12, "estimates_num_1month": 10,
            "estimates_change_abs": 2, "estimates_change_ratio": 0.2,
        }])

        result = build_consensus_states(frame, revision_threshold=0.01).iloc[0]
        states = result["consensus_states"]
        keys = {item["key"] for item in states}

        self.assertTrue({
            "sustained_upgrade", "accelerating_upgrade",
            "target_rating_resonance", "high_dispersion_review",
            "coverage_change_review",
        } <= keys)
        self.assertEqual(result["dispersion_p75"], 0.30)
        self.assertEqual(result["dispersion_sample_count"], 1)
        self.assertTrue(all(
            item["label"] and item["explanation"] and item["evidence"]
            and item["disclaimer"] == "状态为规则化研究分类，不改变榜单排序，不构成投资建议。"
            for item in states
        ))
        target_evidence = next(
            item["evidence"] for item in states
            if item["key"] == "accelerating_upgrade"
        )
        self.assertTrue(all({
            "horizon", "current", "historical", "change", "direction", "threshold",
        } <= item.keys() for item in target_evidence))

    def test_consensus_states_respect_boundaries_missing_values_and_conflicts(self):
        frame = pd.DataFrame([
            {"symbol": "FLAT", "universe_eligible": True, "tp_mean": 101.0,
             "tp_mean_week": 100.0, "tp_mean_1month": 100.0,
             "tp_mean_3month": np.nan, "rec_mean": 2.0,
             "rec_mean_1month": 2.0, "dispersion": 0.10},
            {"symbol": "REVERSAL", "universe_eligible": True, "tp_mean": 100.0,
             "tp_mean_week": 110.0, "tp_mean_1month": 90.0,
             "tp_mean_3month": np.nan, "rec_mean": 2.0,
             "rec_mean_1month": 2.4, "dispersion": 0.20},
            {"symbol": "CONFLICT", "universe_eligible": True, "tp_mean": 110.0,
             "tp_mean_week": np.nan, "tp_mean_1month": 100.0,
             "tp_mean_3month": np.nan, "rec_mean": 2.4,
             "rec_mean_1month": 2.0, "dispersion": 0.30},
            {"symbol": "OUTSIDE", "universe_eligible": False, "tp_mean": 100.0,
             "tp_mean_1month": 100.0, "dispersion": 0.90},
            {"symbol": "LOW", "universe_eligible": True, "tp_mean": 100.0,
             "tp_mean_1month": 100.0, "dispersion": 0.15},
        ])

        rows = build_consensus_states(frame, revision_threshold=0.01).set_index("symbol")
        keys = lambda symbol: {item["key"] for item in rows.at[symbol, "consensus_states"]}

        self.assertNotIn("sustained_upgrade", keys("FLAT"))
        self.assertNotIn("accelerating_upgrade", keys("FLAT"))
        self.assertNotIn("trend_reversal", keys("FLAT"))
        self.assertIn("trend_reversal", keys("REVERSAL"))
        self.assertIn("signal_conflict", keys("CONFLICT"))
        self.assertNotIn("target_rating_resonance", keys("CONFLICT"))
        self.assertNotIn("high_dispersion_review", keys("LOW"))
        self.assertEqual(rows.at["LOW", "dispersion_sample_count"], 4)
        self.assertLess(rows.at["LOW", "dispersion_p75"], 0.30)
        self.assertNotIn("high_dispersion_review", keys("OUTSIDE"))

    def test_coverage_change_state_uses_existing_selected_horizon_fields(self):
        frame = pd.DataFrame([{
            "symbol": "COVERAGE", "coverage_change_status": "significant",
            "estimates_num": 12, "estimates_num_1month": 10,
            "estimates_change_abs": 2, "estimates_change_ratio": 0.2,
        }])

        state = next(item for item in build_consensus_states(
            frame, revision_threshold=0.01,
        ).iloc[0]["consensus_states"] if item["key"] == "coverage_change_review")

        self.assertEqual(state["evidence"]["current"], 12)
        self.assertEqual(state["evidence"]["historical"], 10)
        self.assertEqual(state["evidence"]["change"], 2)
        self.assertEqual(state["evidence"]["status"], "significant")

    def test_coverage_change_state_uses_week_selected_horizon(self):
        frame = pd.DataFrame([{
            "symbol": "WEEK_COVERAGE", "estimates_num": 12,
            "estimates_num_week": 10, "estimates_num_1month": 99,
        }])
        metrics = compute_metrics(frame, horizon="week")

        state = next(item for item in build_consensus_states(
            metrics, revision_threshold=0.01, horizon="week",
        ).iloc[0]["consensus_states"] if item["key"] == "coverage_change_review")

        self.assertEqual(state["evidence"]["horizon"], "week")
        self.assertEqual(state["evidence"]["historical"], 10)
        self.assertEqual(state["evidence"]["change"], 2)
        self.assertIn("周度", state["explanation"])
    def test_computes_all_trajectory_metrics_with_safe_missing_values(self):
        frame = pd.DataFrame([
            {
                "symbol": "POSITIVE", "tp_mean": 120.0, "rec_mean": 1.5,
                "tp_mean_week": 100.0, "rec_mean_week": 2.0,
                "tp_mean_1month": 0.0, "rec_mean_1month": 1.0,
                "tp_mean_3month": 120.0, "rec_mean_3month": 1.5,
                "tp_mean_6month": np.nan, "rec_mean_6month": np.nan,
                "tp_mean_12month": 150.0, "rec_mean_12month": 1.0,
            },
        ])

        result = compute_metrics(frame, revision_threshold=0.01).iloc[0]

        self.assertEqual(
            analysis.TRAJECTORY_HORIZONS,
            ("week", "1month", "3month", "6month", "12month"),
        )
        self.assertAlmostEqual(result["tp_revision_week"], 20.0)
        self.assertAlmostEqual(result["rating_change_week"], 0.5)
        self.assertEqual(result["tp_direction_week"], "positive")
        self.assertEqual(result["rating_direction_week"], "positive")
        self.assertTrue(np.isnan(result["tp_revision_1month"]))
        self.assertEqual(result["tp_direction_1month"], "unavailable")
        self.assertEqual(result["tp_direction_3month"], "flat")
        self.assertEqual(result["rating_direction_3month"], "flat")
        self.assertEqual(result["tp_direction_6month"], "unavailable")
        self.assertEqual(result["rating_direction_6month"], "unavailable")
        self.assertAlmostEqual(result["tp_revision_12month"], -20.0)
        self.assertAlmostEqual(result["rating_change_12month"], -0.5)
        self.assertEqual(result["tp_direction_12month"], "negative")
        self.assertEqual(result["rating_direction_12month"], "negative")

    def test_overflowing_target_revision_is_unavailable_and_excluded_from_states(self):
        frame = pd.DataFrame([{
            "symbol": "OVERFLOW",
            "tp_mean": np.finfo(float).max,
            "tp_mean_week": np.finfo(float).tiny,
            "tp_mean_1month": np.finfo(float).tiny,
            "tp_mean_3month": np.finfo(float).tiny,
        }])

        metrics = compute_metrics(frame)
        states = build_consensus_states(
            metrics, revision_threshold=0.01
        ).iloc[0]["consensus_states"]

        self.assertTrue(np.isinf(metrics.iloc[0]["tp_revision_week"]))
        self.assertEqual(metrics.iloc[0]["tp_direction_week"], "unavailable")
        self.assertEqual(states, [])

    def setUp(self):
        self.frame = pd.DataFrame(
            [
                {
                    "market": "hk", "symbol": "0001.HK", "name": "Alpha",
                    "tp_mean": 120.0, "tp_mean_1month": 100.0, "tp_std": 12.0,
                    "close": 80.0, "estimates_num": 8, "recommendations_num": 10,
                    "strong_buy_num": 4, "buy_num": 3, "hold": 2,
                    "sell_num": 1, "strong_sell_num": 0,
                    "rec_mean": 1.8, "rec_mean_1month": 2.2,
                },
                {
                    "market": "hk", "symbol": "0002.HK", "name": "Beta",
                    "tp_mean": 90.0, "tp_mean_1month": 100.0, "tp_std": 18.0,
                    "close": 100.0, "estimates_num": 3, "recommendations_num": 4,
                    "strong_buy_num": 0, "buy_num": 1, "hold": 2,
                    "sell_num": 1, "strong_sell_num": 0,
                    "rec_mean": 3.0, "rec_mean_1month": 2.5,
                },
                {
                    "market": "us", "symbol": "AAA", "name": "Gamma",
                    "tp_mean": 55.0, "tp_mean_1month": 50.0, "tp_std": 11.0,
                    "close": 50.0, "estimates_num": 7, "recommendations_num": 5,
                    "strong_buy_num": 1, "buy_num": 1, "hold": 2,
                    "sell_num": 1, "strong_sell_num": 0,
                    "rec_mean": 2.4, "rec_mean_1month": 2.4,
                },
                {
                    "market": "us", "symbol": "ZERO", "name": "Zero",
                    "tp_mean": 10.0, "tp_mean_1month": 0.0, "tp_std": 1.0,
                    "close": 0.0, "estimates_num": 6, "recommendations_num": 0,
                    "strong_buy_num": 0, "buy_num": 0, "hold": 0,
                    "sell_num": 0, "strong_sell_num": 0,
                    "rec_mean": np.nan, "rec_mean_1month": np.nan,
                },
                {
                    "market": "us", "symbol": "MISS", "name": "Missing",
                    "tp_mean": np.nan, "tp_mean_1month": 20.0, "tp_std": np.nan,
                    "close": 10.0, "estimates_num": np.nan,
                    "recommendations_num": np.nan,
                },
            ]
        )
        self.frame["tp_currency"] = self.frame["market"].map({"hk": "HKD", "us": "USD"})

    def test_computes_documented_metrics(self):
        result = compute_metrics(self.frame, "1month").set_index("symbol")
        self.assertAlmostEqual(result.loc["0001.HK", "tp_revision"], 0.2)
        self.assertAlmostEqual(result.loc["0001.HK", "tp_distance"], 0.5)
        self.assertAlmostEqual(result.loc["0001.HK", "dispersion"], 0.1)
        self.assertAlmostEqual(result.loc["0001.HK", "rating_score"], 1.0)
        self.assertAlmostEqual(result.loc["0001.HK", "rating_change"], 0.4)

    def test_zero_denominators_and_missing_inputs_stay_missing(self):
        result = compute_metrics(self.frame, "1month").set_index("symbol")
        self.assertTrue(np.isnan(result.loc["ZERO", "tp_revision"]))
        self.assertTrue(np.isnan(result.loc["ZERO", "tp_distance"]))
        self.assertTrue(np.isnan(result.loc["ZERO", "rating_score"]))
        self.assertTrue(np.isnan(result.loc["MISS", "tp_revision"]))

    def test_coverage_change_requires_both_absolute_and_relative_thresholds(self):
        frame = pd.DataFrame([
            {"market": "hk", "symbol": "SIG", "estimates_num": 12,
             "estimates_num_1month": 10, "included_estimates_num": 9,
             "included_estimates_num_1month": 7},
            {"market": "hk", "symbol": "ABS_ONLY", "estimates_num": 102,
             "estimates_num_1month": 100},
            {"market": "hk", "symbol": "REL_ONLY", "estimates_num": 3,
             "estimates_num_1month": 2},
            {"market": "hk", "symbol": "ZERO", "estimates_num": 2,
             "estimates_num_1month": 0},
            {"market": "hk", "symbol": "MISS", "estimates_num": 8},
        ])

        rows = compute_metrics(frame, "1month").set_index("symbol")
        self.assertEqual(rows.loc["SIG", "estimates_change_abs"], 2)
        self.assertAlmostEqual(rows.loc["SIG", "estimates_change_ratio"], 0.2)
        self.assertEqual(rows.loc["SIG", "included_estimates_change_abs"], 2)
        self.assertAlmostEqual(
            rows.loc["SIG", "included_estimates_change_ratio"], 2 / 7,
        )
        self.assertEqual(rows.loc["SIG", "coverage_change_status"], "significant")
        self.assertEqual(
            rows.loc["SIG", "coverage_change_note"],
            "目标价均值变化可能受到聚合样本构成变化影响",
        )
        self.assertEqual(rows.loc["ABS_ONLY", "coverage_change_status"], "stable_or_minor")
        self.assertEqual(rows.loc["REL_ONLY", "coverage_change_status"], "stable_or_minor")
        self.assertEqual(rows.loc["ZERO", "coverage_change_status"], "unavailable")
        self.assertTrue(np.isnan(rows.loc["ZERO", "estimates_change_ratio"]))
        self.assertEqual(rows.loc["MISS", "coverage_change_status"], "unavailable")

    def test_coverage_change_overflow_is_unavailable_and_emits_no_review_state(self):
        frame = pd.DataFrame([{
            "market": "hk", "symbol": "OVERFLOW", "universe_eligible": True,
            "tp_mean": 110.0, "tp_mean_1month": 100.0,
            "estimates_num": np.finfo(float).max,
            "estimates_num_1month": np.finfo(float).tiny,
        }])

        metrics = compute_metrics(frame, "1month")
        states = build_consensus_states(
            metrics, revision_threshold=0.01, horizon="1month",
        ).iloc[0]["consensus_states"]

        self.assertTrue(np.isinf(metrics.iloc[0]["estimates_change_ratio"]))
        self.assertEqual(metrics.iloc[0]["coverage_change_status"], "unavailable")
        self.assertNotIn("coverage_change_review", {state["key"] for state in states})

    def test_eligibility_funnels_are_chained_and_match_ranking_pools(self):
        frame = pd.DataFrame([
            {"market": "hk", "symbol": "OUT", "universe_eligible": False,
             "tp_mean": 110, "tp_mean_1month": 100, "estimates_num": 8,
             "rec_mean": 2, "rec_mean_1month": 2.2, "recommendations_num": 8},
            {"market": "hk", "symbol": "NO_CURRENT", "universe_eligible": True,
             "tp_mean": np.nan, "tp_mean_1month": 100, "estimates_num": 8},
            {"market": "hk", "symbol": "NO_HISTORY", "universe_eligible": True,
             "tp_mean": 110, "tp_mean_1month": np.nan, "estimates_num": 8,
             "rec_mean": 2, "rec_mean_1month": np.nan, "recommendations_num": 8},
            {"market": "hk", "symbol": "LOW", "universe_eligible": True,
             "tp_mean": 110, "tp_mean_1month": 100, "estimates_num": 3,
             "rec_mean": 2, "rec_mean_1month": 2.2, "recommendations_num": 3},
            {"market": "hk", "symbol": "VALID", "universe_eligible": True,
             "tp_mean": 110, "tp_mean_1month": 100, "estimates_num": 8,
             "rec_mean": 2, "rec_mean_1month": 2.2, "recommendations_num": 8},
        ])
        metrics = compute_metrics(frame, "1month")
        funnels = build_eligibility_funnels(
            metrics, horizon="1month", min_analysts=5, min_recommendations=5,
        )
        rankings = build_rankings(metrics, min_analysts=5, min_recommendations=5)

        target_counts = [stage["count"] for stage in funnels["target_revision"]]
        rating_counts = [stage["count"] for stage in funnels["rating"]]
        self.assertEqual(target_counts, [5, 4, 3, 2, 1, 1, 1])
        self.assertEqual(rating_counts, [5, 4, 3, 2, 1, 1, 1])
        self.assertTrue(all(a >= b for a, b in zip(target_counts, target_counts[1:])))
        self.assertEqual(
            target_counts[-1],
            len(rankings["hk"]["revision_eligible"]),
        )
        self.assertEqual(rating_counts[-1], len(rankings["hk"]["rating_eligible"]))
        self.assertEqual(
            funnels["target_revision"][-1]["key"], "revision_eligible"
        )
        self.assertEqual(funnels["rating"][-1]["key"], "rating_eligible")
        self.assertIsNone(funnels["target_revision"][0]["retention"])
        self.assertAlmostEqual(funnels["target_revision"][1]["retention"], 4 / 5)

    def test_invalid_horizon_is_rejected(self):
        with self.assertRaises(ValueError):
            compute_metrics(self.frame, "2month")

    def test_rankings_apply_coverage_and_keep_markets_separate(self):
        metrics = compute_metrics(self.frame, "1month")
        rankings = build_rankings(metrics, min_analysts=5, limit=20)
        self.assertEqual(list(rankings["hk"]["upgrades"]["symbol"]), ["0001.HK"])
        self.assertEqual(list(rankings["us"]["upgrades"]["symbol"]), ["AAA"])
        self.assertNotIn("0002.HK", set(rankings["hk"]["eligible"]["symbol"]))

    def test_upgrade_and_downgrade_categories_filter_direction(self):
        frame = self.frame.copy()
        frame.loc[frame["symbol"] == "0002.HK", "estimates_num"] = 6
        metrics = compute_metrics(frame, "1month")
        rankings = build_rankings(metrics, min_analysts=5, limit=20)
        self.assertEqual(list(rankings["hk"]["upgrades"]["symbol"]), ["0001.HK"])
        self.assertEqual(list(rankings["hk"]["downgrades"]["symbol"]), ["0002.HK"])

    def test_ties_use_symbol_for_deterministic_order(self):
        tied = pd.concat(
            [self.frame.iloc[[0]].assign(symbol="ZZZ"), self.frame.iloc[[0]].assign(symbol="AAA")],
            ignore_index=True,
        )
        metrics = compute_metrics(tied, "1month")
        rankings = build_rankings(metrics, min_analysts=5, limit=20)
        self.assertEqual(list(rankings["hk"]["upgrades"]["symbol"]), ["AAA", "ZZZ"])

    def test_quality_summary_reports_missing_and_excluded_rows(self):
        metrics = compute_metrics(self.frame, "1month")
        summary = build_quality_summary(metrics, min_analysts=5)
        self.assertEqual(summary["total_rows"], 5)
        self.assertEqual(summary["eligible_rows"], 3)
        self.assertEqual(summary["excluded_low_coverage"], 1)
        self.assertEqual(summary["missing_coverage"], 1)
        self.assertEqual(summary["missing_target_price"], 1)
        self.assertEqual(summary["name_coverage"], 1.0)
        self.assertEqual(summary["price_coverage"], 0.8)
        self.assertEqual(summary["history_coverage"], 0.6)
        self.assertEqual(summary["recommendation_coverage"], 0.8)
        self.assertEqual(summary["scatter_eligible_rows"], 3)


    def test_rankings_tolerate_missing_target_price_column(self):
        frame = pd.DataFrame([{"market": "hk", "symbol": "MISSING"}])
        rankings = build_rankings(frame, min_analysts=5, limit=20)
        self.assertTrue(rankings["hk"]["eligible"].empty)
        self.assertEqual(
            list(rankings["hk"]["coverage_exclusions"]["symbol"]),
            ["MISSING"],
        )

    def test_quality_separates_missing_and_low_analyst_coverage(self):
        frame = pd.DataFrame([
            {"symbol": "MISSING", "tp_mean": 100.0, "estimates_num": np.nan},
            {"symbol": "LOW", "tp_mean": 100.0, "estimates_num": 3},
        ])
        quality = build_quality_summary(frame, min_analysts=5)
        self.assertEqual(quality["missing_coverage"], 1)
        self.assertEqual(quality["excluded_low_coverage"], 1)
    def test_revision_threshold_classifies_upgrade_flat_downgrade_and_unavailable(self):
        frame = pd.DataFrame(
            [
                {"market": "us", "symbol": "FLAT", "tp_mean": 101.0,
                 "tp_mean_1month": 100.0, "estimates_num": 8,
                 "included_estimates_num": 6},
                {"market": "us", "symbol": "UP", "tp_mean": 101.01,
                 "tp_mean_1month": 100.0, "estimates_num": 8,
                 "included_estimates_num": 8},
                {"market": "us", "symbol": "DOWN", "tp_mean": 98.99,
                 "tp_mean_1month": 100.0, "estimates_num": 8,
                 "included_estimates_num": 4},
                {"market": "us", "symbol": "ZERO", "tp_mean": 10.0,
                 "tp_mean_1month": 0.0, "estimates_num": 8,
                 "included_estimates_num": 4},
            ]
        )
        result = compute_metrics(frame, "1month", revision_threshold=0.01).set_index("symbol")
        self.assertEqual(result.loc["FLAT", "revision_direction"], "flat")
        self.assertEqual(result.loc["UP", "revision_direction"], "upgrade")
        self.assertEqual(result.loc["DOWN", "revision_direction"], "downgrade")
        self.assertEqual(result.loc["ZERO", "revision_direction"], "unavailable")
        self.assertAlmostEqual(result.loc["UP", "tp_revision_abs"], 1.01)
        self.assertAlmostEqual(result.loc["FLAT", "included_ratio"], 0.75)

    def test_rankings_exclude_changes_inside_noise_threshold(self):
        frame = pd.DataFrame(
            [
                {"market": "us", "symbol": "FLAT", "tp_mean": 100.5,
                 "tp_mean_1month": 100.0, "estimates_num": 8},
                {"market": "us", "symbol": "UP", "tp_mean": 102.0,
                 "tp_mean_1month": 100.0, "estimates_num": 8},
            ]
        )
        metrics = compute_metrics(frame, "1month", revision_threshold=0.01)
        rankings = build_rankings(metrics, min_analysts=5, limit=20)
        self.assertEqual(list(rankings["us"]["upgrades"]["symbol"]), ["UP"])

    def test_target_and_recommendation_rankings_use_separate_coverage_thresholds(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "TARGET_ONLY", "universe_eligible": True,
             "tp_mean": 120.0, "tp_mean_1month": 100.0, "estimates_num": 8,
             "rec_mean": 2.0, "rec_mean_1month": 2.5, "recommendations_num": 2},
            {"market": "us", "symbol": "RATING_ONLY", "universe_eligible": True,
             "tp_mean": 120.0, "tp_mean_1month": 100.0, "estimates_num": 2,
             "rec_mean": 2.0, "rec_mean_1month": 2.5, "recommendations_num": 8},
        ])
        metrics = compute_metrics(frame, "1month")
        rankings = build_rankings(
            metrics, min_analysts=5, min_recommendations=5, limit=20
        )

        self.assertEqual(list(rankings["us"]["upgrades"]["symbol"]), ["TARGET_ONLY"])
        self.assertEqual(list(rankings["us"]["rating_changes"]["symbol"]), ["RATING_ONLY"])
        self.assertEqual(list(rankings["us"]["eligible"]["symbol"]), ["TARGET_ONLY"])
        self.assertEqual(list(rankings["us"]["rating_eligible"]["symbol"]), ["RATING_ONLY"])

    def test_non_core_security_is_excluded_from_all_rankings(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "ETF", "universe_eligible": False,
             "tp_mean": 120.0, "tp_mean_1month": 100.0, "estimates_num": 20,
             "rec_mean": 2.0, "rec_mean_1month": 3.0, "recommendations_num": 20},
        ])
        rankings = build_rankings(compute_metrics(frame), min_analysts=5, limit=20)
        self.assertTrue(rankings["us"]["eligible"].empty)
        self.assertTrue(rankings["us"]["rating_eligible"].empty)

    def test_validation_flags_inconsistent_values_without_overwriting_source_data(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "BROKEN", "universe_eligible": True,
             "tp_low": 130.0, "tp_mean": 120.0, "tp_high": 110.0,
             "tp_mean_1month": 100.0, "estimates_num": 5,
             "included_estimates_num": 7, "rec_mean": 6.0,
             "rec_mean_1month": 4.0, "recommendations_num": 10,
             "strong_buy_num": 1, "buy_num": 1, "hold": 1,
             "sell_num": 1, "strong_sell_num": 1, "no_opinion_num": 0},
        ])
        result = compute_metrics(frame).iloc[0]

        self.assertEqual(result["tp_low"], 130.0)
        self.assertEqual(result["included_estimates_num"], 7)
        self.assertFalse(result["target_range_valid"])
        self.assertFalse(result["included_count_valid"])
        self.assertFalse(result["recommendation_count_valid"])
        self.assertFalse(result["recommendation_mean_valid"])
        self.assertEqual(result["validation_status"], "error")
        self.assertIn("target_range_invalid", result["validation_issues"])

    def test_missing_recommendation_buckets_are_unverified_not_zero(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "PARTIAL", "recommendations_num": 0,
             "strong_buy_num": 0, "buy_num": 0, "hold": 0,
             "sell_num": 0, "strong_sell_num": np.nan, "no_opinion_num": 0},
        ])
        result = compute_metrics(frame).iloc[0]
        self.assertTrue(pd.isna(result["recommendation_count_valid"]))
        self.assertTrue(pd.isna(result["recommendation_bucket_sum"]))

    def test_quality_summary_classifies_universe_and_validation_gaps(self):
        frame = pd.DataFrame([
            {"symbol": "GOOD", "universe_eligible": True, "tp_mean": 100.0,
             "estimates_num": 8, "recommendations_num": 8, "rec_mean": 2.0,
             "rating_change": 0.2, "price_valid": True,
             "validation_status": "pass"},
            {"symbol": "ETF", "universe_eligible": False, "tp_mean": 100.0,
             "estimates_num": 8, "recommendations_num": 8, "rec_mean": 2.0,
             "rating_change": 0.2, "price_valid": False,
             "price_missing_reason": "outside_core_universe",
             "validation_status": "unverified"},
            {"symbol": "BAD", "universe_eligible": True, "tp_mean": 100.0,
             "estimates_num": 8, "recommendations_num": 2, "price_valid": False,
             "price_missing_reason": "not_returned_by_api",
             "validation_status": "error"},
        ])
        quality = build_quality_summary(
            frame, min_analysts=5, min_recommendations=5
        )
        self.assertEqual(quality["core_universe_rows"], 2)
        self.assertEqual(quality["excluded_universe_rows"], 1)
        self.assertEqual(quality["rating_eligible_rows"], 1)
        self.assertEqual(quality["excluded_low_recommendation_coverage"], 1)
        self.assertEqual(quality["validation_error_rows"], 1)
        self.assertEqual(quality["price_missing_reasons"]["not_returned_by_api"], 1)

    def test_historical_recommendation_mean_must_be_in_valid_range(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "BAD_HISTORY", "universe_eligible": True,
             "tp_currency": "USD", "rec_mean": 2.0, "rec_mean_1month": 9.0,
             "recommendations_num": 20},
        ])
        metrics = compute_metrics(frame)
        row = metrics.iloc[0]
        self.assertFalse(row["recommendation_history_mean_valid"])
        self.assertIn("recommendation_history_mean_out_of_range", row["validation_issues"])
        rankings = build_rankings(metrics, min_recommendations=5)
        self.assertTrue(rankings["us"]["rating_changes"].empty)

    def test_partially_available_validation_is_not_reported_as_pass(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "PARTIAL", "tp_currency": "USD",
             "tp_mean": 100.0, "tp_low": 90.0, "tp_high": 110.0},
        ])
        row = compute_metrics(frame).iloc[0]
        self.assertEqual(row["validation_status"], "partial")

    def test_price_divergence_requires_verified_market_currency(self):
        frame = pd.DataFrame([
            {"market": "us", "symbol": "USD", "universe_eligible": True,
             "tp_currency": "USD", "tp_mean": 120.0, "close": 100.0,
             "estimates_num": 8},
            {"market": "us", "symbol": "OTHER", "universe_eligible": True,
             "tp_currency": "EUR", "tp_mean": 120.0, "close": 100.0,
             "estimates_num": 8},
        ])
        metrics = compute_metrics(frame).set_index("symbol")
        self.assertAlmostEqual(metrics.loc["USD", "tp_distance"], 0.2)
        self.assertTrue(pd.isna(metrics.loc["OTHER", "tp_distance"]))
        self.assertEqual(metrics.loc["OTHER", "currency_validation_status"], "currency_mismatch")

    def test_build_rankings_keeps_legacy_positional_limit_argument(self):
        metrics = compute_metrics(self.frame)
        positional = build_rankings(metrics, 5, 1)
        self.assertLessEqual(len(positional["hk"]["upgrades"]), 1)
if __name__ == "__main__":
    unittest.main()
