"""策略列表「单笔收入」= SIGNAL TRADE RETURN（触发价→现价）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_buy_signal import (  # noqa: E402
    enrich_signal_single_return,
    signal_single_return_pct,
    signal_trigger_price,
)
from watch_config import (  # noqa: E402
    is_exit_executable,
    market_phase,
)


class TestSignalSingleReturn(unittest.TestCase):
    def test_huamai_fixture(self) -> None:
        pct = signal_single_return_pct(trigger=17.25, mark=19.03)
        self.assertEqual(pct, round((19.03 / 17.25 - 1.0) * 100.0, 2))
        self.assertAlmostEqual(pct, 10.32, places=2)

    def test_sanxiang_fixture(self) -> None:
        pct = signal_single_return_pct(trigger=47.07, mark=49.82)
        self.assertEqual(pct, round((49.82 / 47.07 - 1.0) * 100.0, 2))
        self.assertAlmostEqual(pct, 5.84, places=2)

    def test_yuandong_fixture(self) -> None:
        pct = signal_single_return_pct(trigger=21.69, mark=23.05)
        self.assertEqual(pct, round((23.05 / 21.69 - 1.0) * 100.0, 2))
        self.assertAlmostEqual(pct, 6.27, places=2)

    def test_untriggered(self) -> None:
        row = {
            "现价": 19.03,
            "开盘": 17.00,
            "买点": 17.25,
            "已触买": "否",
            "持仓状态": "空仓",
            "预警": "将买入",
        }
        enrich_signal_single_return(row)
        self.assertIsNone(row.get("单笔收入%"))
        self.assertIsNone(signal_trigger_price(row))

    def test_triggered_without_holding(self) -> None:
        row = {
            "现价": 19.03,
            "开盘": 16.80,
            "买点": 17.25,
            "已触发因子侧": "买入",
            "已触发因子价": 17.25,
            "已触买": "是",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "已触买·未入槽",
        }
        enrich_signal_single_return(row)
        self.assertEqual(row["单笔收入%"], round((19.03 / 17.25 - 1.0) * 100.0, 2))
        # 开盘价不得冒充触发价
        self.assertEqual(signal_trigger_price(row), 17.25)
        self.assertNotEqual(signal_trigger_price(row), row["开盘"])

    def test_trigger_freeze_quote_update(self) -> None:
        row = {
            "现价": 19.03,
            "已触发因子侧": "买入",
            "已触发因子价": 17.25,
            "已触买": "是",
            "持仓": 0,
            "持仓状态": "待买入",
        }
        enrich_signal_single_return(row)
        a = row["单笔收入%"]
        row["现价"] = 19.50
        enrich_signal_single_return(row)
        b = row["单笔收入%"]
        self.assertEqual(signal_trigger_price(row), 17.25)
        self.assertNotEqual(a, b)
        self.assertEqual(b, round((19.50 / 17.25 - 1.0) * 100.0, 2))

    def test_invalid_trigger_safe_null(self) -> None:
        self.assertIsNone(signal_single_return_pct(trigger=0, mark=10))
        self.assertIsNone(signal_single_return_pct(trigger=-1, mark=10))
        self.assertIsNone(signal_single_return_pct(trigger=None, mark=10))
        self.assertIsNone(signal_single_return_pct(trigger=17.25, mark=None))

    def test_signal_vs_fill_distinct(self) -> None:
        trigger = 17.25
        fill = 17.60
        current = 19.03
        signal_ret = signal_single_return_pct(trigger=trigger, mark=current)
        position_ret = round((current / fill - 1.0) * 100.0, 2)
        self.assertAlmostEqual(signal_ret, 10.32, places=2)
        self.assertAlmostEqual(position_ret, 8.13, places=2)
        self.assertNotEqual(signal_ret, position_ret)
        # 有真实成本时，单笔收入仍用触发价，不用 fill
        row = {
            "现价": current,
            "成本": fill,
            "已触发因子侧": "买入",
            "已触发因子价": trigger,
            "已触买": "是",
            "持仓": 100,
            "持仓状态": "已经买入",
        }
        enrich_signal_single_return(row)
        self.assertEqual(row["单笔收入%"], signal_ret)

    def test_closed_freezes_at_fill(self) -> None:
        row = {
            "现价": 20.0,
            "成交价": 18.0,
            "已触发因子侧": "买入",
            "已触发因子价": 17.25,
            "持仓": 0,
            "已实现": True,
            "持仓状态": "今日平仓",
        }
        enrich_signal_single_return(row)
        self.assertEqual(row["单笔收入%"], round((18.0 / 17.25 - 1.0) * 100.0, 2))
        row["现价"] = 25.0
        enrich_signal_single_return(row)
        self.assertEqual(row["单笔收入%"], round((18.0 / 17.25 - 1.0) * 100.0, 2))

    def test_auction_phase_not_executable(self) -> None:
        import datetime as dt

        t = dt.datetime(2026, 9, 22, 9, 20)
        self.assertEqual(market_phase(t), "auction_locked")
        self.assertFalse(is_exit_executable(t))

    def test_0930_continuous_executable(self) -> None:
        import datetime as dt

        t = dt.datetime(2026, 9, 22, 9, 30)
        self.assertEqual(market_phase(t), "continuous")
        self.assertTrue(is_exit_executable(t))


if __name__ == "__main__":
    unittest.main()
