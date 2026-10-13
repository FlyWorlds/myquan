from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

HS = Path(__file__).resolve().parent
if str(HS) not in sys.path:
    sys.path.insert(0, str(HS))
import index


class TestStrategy16BDynamicPool(unittest.TestCase):
    def tearDown(self) -> None:
        index._set_strategy16b_dynamic({}, {"picks": []})

    def test_dynamic_pool_enters_scan_and_snapshot_rows(self) -> None:
        payload = {
            "picks": [
                {
                    "code": "600000",
                    "name": "测试票",
                    "concept": "测试概念",
                    "price": 10,
                    "chg_pct": 3.21,
                }
            ]
        }
        index._set_strategy16b_dynamic({"horizon_months": 1}, payload)

        watchlist = index._strategy16b_watchlist()
        self.assertEqual([w["code"] for w in watchlist], ["600000"])
        self.assertEqual(watchlist[0]["universe"], "strategy16b")
        self.assertEqual(watchlist[0]["池来源"], "条件选股")

        with mock.patch.object(index, "_strategy16b_quote_map", return_value={}):
            rows = index._strategy16b_rows_from_rows(
                [
                    {
                        "代码": "600000",
                        "名称": "测试票",
                        "现价": 10.5,
                        "池来源": "因子27",
                        "pool_src": "factor27",
                    }
                ]
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool_src"], "strategy16b")
        self.assertEqual(rows[0]["池来源"], "条件选股")
        self.assertEqual(rows[0]["concept"], "测试概念")
        self.assertEqual(rows[0]["当日涨幅"], 3.21)
        self.assertEqual(rows[0]["_day_chg_source"], "strategy16b_select")

    def test_dynamic_pool_fills_missing_day_change_from_selected_quote(self) -> None:
        payload = {
            "picks": [
                {
                    "code": "600001",
                    "name": "补涨跌票",
                    "concept": "测试概念",
                    "price": 20.0,
                    "chg_pct": -2.5,
                }
            ]
        }
        index._set_strategy16b_dynamic({"horizon_months": 1}, payload)

        with mock.patch.object(index, "_strategy16b_quote_map", return_value={}):
            rows = index._strategy16b_rows_from_rows(
                [
                    {
                        "代码": "600001",
                        "名称": "补涨跌票",
                        "现价": 19.5,
                        "当日涨幅": 0.0,
                        "昨收": None,
                    }
                ]
            )

        self.assertEqual(rows[0]["当日涨幅"], -2.5)
        self.assertEqual(rows[0]["_day_chg_source"], "strategy16b_select")
        self.assertAlmostEqual(rows[0]["昨收"], 20.0, places=2)

    def test_dynamic_pool_overrides_zero_day_change_from_batch_quote(self) -> None:
        payload = {
            "picks": [
                {
                    "code": "600002",
                    "name": "批量行情票",
                    "concept": "测试概念",
                    "price": 10.0,
                }
            ]
        }
        index._set_strategy16b_dynamic({"horizon_months": 1}, payload)

        with mock.patch.object(
            index,
            "_strategy16b_quote_map",
            return_value={
                "600002": {
                    "session": "2026-10-13",
                    "open": 9.5,
                    "high": 10.2,
                    "low": 9.4,
                    "last": 10.0,
                    "prev_close": 9.0,
                    "day_chg_pct": 11.111,
                    "last_ts": "2026-10-13 15:35:45",
                }
            },
        ):
            rows = index._strategy16b_rows_from_rows(
                [
                    {
                        "代码": "600002",
                        "名称": "批量行情票",
                        "交易日": "2026-10-14",
                        "现价": 9.0,
                        "昨收": 9.0,
                        "当日涨幅": 0.0,
                    }
                ]
            )

        self.assertEqual(rows[0]["当日涨幅"], 11.11)
        self.assertEqual(rows[0]["_day_chg_source"], "strategy16b_sina_batch")
        self.assertEqual(rows[0]["交易日"], "2026-10-13")
        self.assertEqual(rows[0]["现价"], 10.0)
        self.assertEqual(rows[0]["昨收"], 9.0)

    def test_dynamic_pool_enters_full_scan_even_when_not_strategy16(self) -> None:
        payload = {
            "picks": [
                {
                    "code": "600004",
                    "name": "动态独有票",
                    "concept": "动态概念",
                    "price": 10,
                }
            ]
        }
        index._set_strategy16b_dynamic({"horizon_months": 1}, payload)

        rows = index._scan_watchlist({"positions": {}}, full=True)
        by_code = {str(row.get("code") or ""): row for row in rows}
        self.assertIn("600004", by_code)
        self.assertEqual(by_code["600004"]["universe"], "strategy16b")
        self.assertEqual(by_code["600004"]["池来源"], "条件选股")


if __name__ == "__main__":
    unittest.main()
