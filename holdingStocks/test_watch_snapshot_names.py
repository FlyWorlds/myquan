import unittest
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import watch_snapshot


class TestWatchSnapshotNames(unittest.TestCase):
    def test_fill_stock_names_replaces_code_like_names(self) -> None:
        rows = [
            {"代码": "600330", "名称": "600330"},
            {"代码": "000049", "名称": "sz000049"},
            {"代码": "002636", "名称": "SYN002636"},
            {"代码": "600552", "名称": "凯盛科技"},
        ]
        with mock.patch(
            "stock_names.lookup_names_for_codes",
            return_value={
                "600330": "天通股份",
                "000049": "德赛电池",
                "002636": "金安国纪",
            },
        ) as lookup:
            out = watch_snapshot._fill_stock_names(rows)

        lookup.assert_called_once()
        self.assertEqual(out[0]["名称"], "天通股份")
        self.assertEqual(out[1]["名称"], "德赛电池")
        self.assertEqual(out[2]["名称"], "金安国纪")
        self.assertEqual(out[3]["名称"], "凯盛科技")

    def test_factors_and_strategies_api_payloads(self) -> None:
        import index

        factors_data = index._load_watch_factors_api()
        self.assertIn("categories", factors_data)
        self.assertIn("factors", factors_data)
        self.assertGreater(len(factors_data["factors"]), 20)

        strategies_data = index._load_watch_strategy_tabs()
        self.assertGreater(len(strategies_data), 5)
        strat_ids = [s["id"] for s in strategies_data]
        self.assertIn("strategy1", strat_ids)
        self.assertIn("strategy16b", strat_ids)
        self.assertIn("strategy35", strat_ids)


if __name__ == "__main__":
    unittest.main()
