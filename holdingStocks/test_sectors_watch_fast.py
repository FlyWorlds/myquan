from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sectors_watch as sw  # noqa: E402


class TestSectorsWatchFastPath(unittest.TestCase):
    def setUp(self) -> None:
        sw._last_spot = {}
        sw._last_spot_ts = 0.0
        sw._last_member_stats = {}
        sw._last_member_stats_ts = 0.0
        sw._last_main_flow = {}
        sw._last_main_flow_ts = 0.0
        sw._last_payload = {}
        sw._last_deep_attempt_ts = 0.0
        sw._last_member_stats_attempt_ts = 0.0
        sw._tick = 0
        sw.set_focus_concept(None)

    def test_first_payload_uses_sina_fast_source_without_deep_scan(self) -> None:
        fast = {
            "测试概念": {
                "code": "gn_test",
                "name": "测试概念",
                "涨跌幅": 1.2,
                "close": 12.3,
                "资金": 100000000.0,
                "资金口径": "新浪板块成交额",
            }
        }

        with (
            patch.object(sw, "fetch_sina_concept_spot_fast", return_value=fast),
            patch.object(sw, "fetch_concept_index_spot_live") as deep,
            patch.object(sw, "fetch_member_quotes_sina") as quotes,
            patch.object(sw, "_write_fast_cache"),
        ):
            payload = sw.build_sectors_live_payload()

        self.assertEqual(payload["source"], "新浪板块摘要")
        self.assertIn("测试概念", payload["conceptToday"])
        self.assertEqual(payload["conceptToday"]["测试概念"]["涨跌幅"], 1.2)
        deep.assert_not_called()
        quotes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
