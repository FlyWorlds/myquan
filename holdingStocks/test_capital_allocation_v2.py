"""Paper Portfolio Capital Allocation V2。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import index as idx  # noqa: E402
from watch_config import (  # noqa: E402
    ALLOW_NEGATIVE_CASH_FOR_BUY,
    ALLOW_PYRAMIDING,
    MAX_NEW_SYMBOLS_PER_SESSION,
    MAX_POSITION_SYMBOLS,
    MAX_POSITION_WEIGHT,
    capital_buy_qty,
    target_position_notional,
)


def _book(
    *,
    cash: float = 300000.0,
    total: float = 300000.0,
    positions: dict | None = None,
) -> dict:
    return {
        "updated_at": None,
        "account_total": total,
        "account_cash": cash,
        "account_total_open": total,
        "account_total_open_session": "2026-09-22",
        "paper_equity_base": 300000.0,
        "paper_pnl_start": "2026-09-09",
        "positions": positions or {},
        "realized_today": {},
        "closed_today": {},
        "daily_settlements": {},
        "portfolio_pool": [],
        "slot_queue": {"session": "2026-09-22", "freed_at": []},
        "factor2": {
            "equity": total,
            "dd_pct": 0.0,
            "action": "hold",
            "thresholds": {
                "hist_max_dd": 0.26,
                "avg_yearly_max_dd": 0.19,
                "add_alert_dd": 0.20,
                "reduce_alert_dd": 0.10,
            },
        },
    }


class TestCapitalAllocationV2(unittest.TestCase):
    def setUp(self) -> None:
        self.book = _book()
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        self._trades: list[dict] = []
        idx.load_holdings = lambda: self.book
        idx.save_holdings = self._save_book
        idx.append_trade = self._append_trade
        self._wx = __import__("wechat_notify")
        self._wx_flag = self._wx._WATCH_WECHAT_ENABLED
        self._wx.set_watch_wechat_enabled(False)

    def _save_book(self, data: dict) -> None:
        self.book = data

    def _append_trade(self, rec: dict) -> None:
        self._trades.append(dict(rec))

    def tearDown(self) -> None:
        idx.load_holdings = self._load
        idx.save_holdings = self._save
        idx.append_trade = self._append
        self._wx._WATCH_WECHAT_ENABLED = self._wx_flag

    def test_config_source_of_truth(self) -> None:
        self.assertEqual(MAX_NEW_SYMBOLS_PER_SESSION, 2)
        self.assertEqual(MAX_POSITION_WEIGHT, 0.20)
        self.assertEqual(MAX_POSITION_SYMBOLS, 5)
        self.assertIs(ALLOW_NEGATIVE_CASH_FOR_BUY, False)
        self.assertIs(ALLOW_PYRAMIDING, False)

    def test_twenty_percent_entry_cap(self) -> None:
        self.assertEqual(target_position_notional(300000.0), 60000.0)
        qty, reason = capital_buy_qty(
            price=10.0, equity=300000.0, cash=300000.0
        )
        self.assertIsNone(reason)
        self.assertEqual(qty, 6000)
        self.assertLessEqual(qty * 10.0, 60000.0 + 1e-9)

    def test_monday_two_buys(self) -> None:
        idx.apply_paper_slot_buy(
            code="000001",
            meta={"name": "A", "market": "深证"},
            price=10.0,
            qty=6000,
            buy_time="2026-09-22 09:40:00",
        )
        idx.apply_paper_slot_buy(
            code="000002",
            meta={"name": "B", "market": "深证"},
            price=10.0,
            qty=6000,
            buy_time="2026-09-22 10:10:00",
        )
        self.assertEqual(self.book["positions"]["000001"]["qty"], 6000)
        self.assertEqual(self.book["positions"]["000002"]["qty"], 6000)
        self.assertEqual(self.book["account_cash"], 180000.0)
        self.assertLessEqual(6000 * 10.0, 60000.0)

    def test_monday_third_buy_block_via_quota(self) -> None:
        text = "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-09-22 09:40:00",
                        "side": "buy",
                        "code": "000001",
                        "session": "2026-09-22",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-09-22 10:10:00",
                        "side": "buy",
                        "code": "000002",
                        "session": "2026-09-22",
                    }
                ),
            ]
        )
        codes = idx.today_new_symbol_codes("2026-09-22", text=text)
        self.assertEqual(codes, ["000001", "000002"])
        self.assertEqual(len(codes), MAX_NEW_SYMBOLS_PER_SESSION)
        # 第三只：额度满
        self.assertGreaterEqual(len(codes), 2)

    def test_same_day_restart_rebuilds_quota(self) -> None:
        text = "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-09-22 09:40:00",
                        "side": "buy",
                        "code": "600000",
                        "note": "槽位触买(自动)",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-09-22 10:10:00",
                        "side": "buy",
                        "code": "600001",
                        "note": "槽位触买(自动)",
                    }
                ),
            ]
        )
        self.assertEqual(
            idx.today_slot_buy_count("2026-09-22", text=text), 2
        )
        left = MAX_NEW_SYMBOLS_PER_SESSION - idx.today_slot_buy_count(
            "2026-09-22", text=text
        )
        self.assertEqual(left, 0)

    def test_same_day_sell_does_not_restore_quota(self) -> None:
        text = "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-09-22 09:40:00",
                        "side": "buy",
                        "code": "000001",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-09-22 10:00:00",
                        "side": "buy",
                        "code": "000002",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-09-22 11:00:00",
                        "side": "sell",
                        "code": "000001",
                    }
                ),
            ]
        )
        self.assertEqual(
            idx.today_new_symbol_codes("2026-09-22", text=text),
            ["000001", "000002"],
        )

    def test_tuesday_quota_reset(self) -> None:
        text = "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-09-22 09:40:00",
                        "side": "buy",
                        "code": "000001",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-09-22 10:00:00",
                        "side": "buy",
                        "code": "000002",
                    }
                ),
            ]
        )
        self.assertEqual(idx.today_slot_buy_count("2026-09-22", text=text), 2)
        self.assertEqual(idx.today_slot_buy_count("2026-09-23", text=text), 0)

    def test_friday_monday_session(self) -> None:
        text = "\n".join(
            [
                json.dumps(
                    {
                        "time": "2026-09-18 09:40:00",
                        "side": "buy",
                        "code": "000001",
                    }
                ),
                json.dumps(
                    {
                        "time": "2026-09-18 10:00:00",
                        "side": "buy",
                        "code": "000002",
                    }
                ),
            ]
        )
        # 周末不新增额度（周五已用完）；周一 session 独立
        self.assertEqual(idx.today_slot_buy_count("2026-09-18", text=text), 2)
        self.assertEqual(idx.today_slot_buy_count("2026-09-19", text=text), 0)
        self.assertEqual(idx.today_slot_buy_count("2026-09-20", text=text), 0)
        self.assertEqual(idx.today_slot_buy_count("2026-09-21", text=text), 0)

    def test_five_position_limit(self) -> None:
        from watch_config import free_buy_slot_count

        h = {
            "positions": {
                f"60000{i}": {"qty": 100} for i in range(5)
            }
        }
        self.assertEqual(free_buy_slot_count(h, reserve_for_close=False), 0)

    def test_insufficient_cash_shrink(self) -> None:
        qty, reason = capital_buy_qty(
            price=10.0, equity=300000.0, cash=2500.0
        )
        self.assertIsNone(reason)
        self.assertEqual(qty, 200)  # 缩量到可买一手以上，仍 ≤20%
        self.assertLessEqual(qty * 10.0, 2500.0 + 1e-9)

    def test_insufficient_cash_block(self) -> None:
        qty, reason = capital_buy_qty(
            price=10.0, equity=300000.0, cash=50.0
        )
        self.assertEqual(qty, 0)
        self.assertEqual(reason, "INSUFFICIENT_CASH")

    def test_negative_cash_block(self) -> None:
        qty, reason = capital_buy_qty(
            price=10.0, equity=300000.0, cash=-100.0
        )
        self.assertEqual(qty, 0)
        self.assertEqual(reason, "NEGATIVE_CASH")
        self.book["account_cash"] = -20.0
        with self.assertRaises(ValueError) as ctx2:
            idx.apply_paper_slot_buy(
                code="600001",
                meta={"name": "测试2", "market": "上证"},
                price=3.0,
                qty=10,
                buy_time="2026-09-22 09:36:00",
            )
        self.assertIn("NEGATIVE_CASH", str(ctx2.exception))
        self.assertEqual(self.book["account_cash"], -20.0)

    def test_existing_position_no_pyramid(self) -> None:
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 100,
            "cost": 10.0,
            "available": 0,
            "buy_time": "2026-09-21 09:35:00",
        }
        self.book["account_cash"] = 300000.0
        before = self.book["account_cash"]
        pos = idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            price=11.0,
            qty=100,
            buy_time="2026-09-22 09:35:00",
        )
        self.assertEqual(int(pos["qty"]), 100)
        self.assertEqual(self.book["account_cash"], before)
        self.assertEqual(len(self._trades), 0)

    def test_price_appreciation_no_rebalance(self) -> None:
        """买入后涨到 >20% 不强制减仓（本轮不做再平衡）。"""
        idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            price=10.0,
            qty=6000,
            buy_time="2026-09-22 09:35:00",
        )
        # 现价涨到 12 → 名义 72000 / 权益约 312000 ≈ 23%
        mv = 12.0 * 6000
        equity = float(self.book["account_cash"]) + mv
        weight = mv / equity
        self.assertGreater(weight, MAX_POSITION_WEIGHT)
        self.assertEqual(self.book["positions"]["600000"]["qty"], 6000)

    def test_apply_blocks_insufficient_cash(self) -> None:
        self.book["account_cash"] = 100.0
        with self.assertRaises(ValueError) as ctx:
            idx.apply_paper_slot_buy(
                code="600000",
                meta={"name": "测试", "market": "上证"},
                price=12.0,
                qty=10,
                buy_time="2026-09-22 09:35:00",
            )
        self.assertIn("INSUFFICIENT_CASH", str(ctx.exception))
        self.assertEqual(self.book["account_cash"], 100.0)
        self.assertEqual(int(self.book["positions"].get("600000", {}).get("qty") or 0), 0)


if __name__ == "__main__":
    unittest.main()
