from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import reg_risk_report  # noqa: E402
from scoring import score_freeze, score_restricted  # noqa: E402


class _PartiallyEmptyDataSource:
    backend = "test"

    def __init__(self, prefer=None):
        self.prefer = prefer

    def shareholder_change(self, symbol, start, end):
        return [{"direction": "增持"}]

    def restricted(self, symbol, start, end):
        return []

    def pledge(self, symbol, start, end):
        return [{"acc_pledge_total_ratio": 0}]

    def placard(self, symbol, start, end):
        return [{"shareholder_name": "测试股东"}]

    def top_holders(self, symbol, start, end):
        return [{"freeze": 0}]

    def daily(self, symbol, start, end):
        return [{"date": end, "name": "测试公司", "trade_status": 0}]


class RegulatoryRiskRegressionTests(unittest.TestCase):
    def test_empty_source_is_reported_as_degraded(self):
        with patch.object(reg_risk_report, "DataSource", _PartiallyEmptyDataSource):
            report = reg_risk_report.build_report(
                ["000001.SZ"],
                lookback=180,
                lookahead=90,
                min_severity="low",
            )

        self.assertEqual(report["degraded_sources"], ["restricted"])

    def test_future_restricted_score_decays_continuously_with_days_to_event(self):
        today = datetime(2026, 7, 29)

        def subscore(days_to: int) -> float:
            row = {"relieve_date": (today + timedelta(days=days_to)).strftime("%Y%m%d")}
            return score_restricted([row], today)[0].subscore

        scores = [subscore(days) for days in (5, 30, 31, 180)]
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[1], scores[2])
        self.assertGreater(scores[2], scores[3])

    def test_nan_freeze_is_not_treated_as_a_judicial_freeze(self):
        rows = [{
            "holder_name": "测试股东",
            "freeze": float("nan"),
            "date": "20260429",
        }]
        self.assertEqual(score_freeze(rows, datetime(2026, 7, 29)), [])

    def test_duplicate_freeze_rows_are_scored_once(self):
        row = {
            "holder_name": "测试股东",
            "freeze": 1_000_000,
            "date": "20260429",
        }
        self.assertEqual(len(score_freeze([row, dict(row)], datetime(2026, 7, 29))), 1)


if __name__ == "__main__":
    unittest.main()
