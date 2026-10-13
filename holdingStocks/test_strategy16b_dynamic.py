from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
                }
            ]
        }
        index._set_strategy16b_dynamic({"horizon_months": 1}, payload)

        watchlist = index._strategy16b_watchlist()
        self.assertEqual([w["code"] for w in watchlist], ["600000"])
        self.assertEqual(watchlist[0]["universe"], "strategy16b")
        self.assertEqual(watchlist[0]["池来源"], "条件选股")

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
