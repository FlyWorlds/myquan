"""pool_1m 末日持仓种子：回放成交、对齐本周产物。"""

from __future__ import annotations

import unittest

from seed_from_pool_1m import (
    DEFAULT_POOL_DIR,
    DEFAULT_TAG,
    OpenLot,
    build_holdings,
    reconstruct_open_lots,
    resolve_artifacts,
    seed_holdings,
)


class TestReconstructOpenLots(unittest.TestCase):
    def test_half_then_clear_not_open(self) -> None:
        lots = reconstruct_open_lots(
            [
                {
                    "side": "buy",
                    "code": "002636",
                    "name": "金安国纪",
                    "px": 70.21,
                    "shares": 1300,
                    "ts": "2026-09-10 09:33:00",
                },
                {
                    "side": "sell",
                    "code": "002636",
                    "px": 77.23,
                    "shares": 600,
                    "ts": "2026-09-11 09:39:00",
                    "exit_reason": "ladder_half_10",
                },
                {
                    "side": "sell",
                    "code": "002636",
                    "px": 76.15,
                    "shares": 700,
                    "ts": "2026-09-11 09:45:00",
                    "exit_reason": "peak_pullback_clear",
                },
            ]
        )
        self.assertEqual(lots, {})

    def test_half_remain_keeps_stage(self) -> None:
        lots = reconstruct_open_lots(
            [
                {
                    "side": "buy",
                    "code": "000070",
                    "name": "特发信息",
                    "px": 16.29,
                    "shares": 6000,
                    "ts": "2026-09-11 09:31:00",
                },
                {
                    "side": "sell",
                    "code": "000070",
                    "px": 17.92,
                    "shares": 3000,
                    "ts": "2026-09-11 10:00:00",
                    "exit_reason": "ladder_half_10",
                },
            ]
        )
        lot = lots["000070"]
        self.assertEqual(lot.qty, 3000)
        self.assertEqual(lot.tp_stage, 1)
        self.assertEqual(lot.last_tp_ts, "2026-09-11 10:00:00")
        self.assertEqual(lot.cost, 16.29)

    def test_rebuy_after_full_exit(self) -> None:
        lots = reconstruct_open_lots(
            [
                {
                    "side": "buy",
                    "code": "000021",
                    "name": "深科技",
                    "px": 35.88,
                    "shares": 2500,
                    "ts": "2026-09-08 10:34:00",
                },
                {
                    "side": "sell",
                    "code": "000021",
                    "px": 34.98,
                    "shares": 2500,
                    "ts": "2026-09-09 11:22:00",
                    "exit_reason": "t1_peak_trail",
                },
                {
                    "side": "buy",
                    "code": "000021",
                    "name": "深科技",
                    "px": 36.35,
                    "shares": 2600,
                    "ts": "2026-09-10 09:31:00",
                },
            ]
        )
        lot = lots["000021"]
        self.assertEqual(lot.qty, 2600)
        self.assertEqual(lot.cost, 36.35)
        self.assertEqual(lot.buy_time, "2026-09-10 09:31:00")
        self.assertEqual(lot.tp_stage, 0)


class TestBuildHoldings(unittest.TestCase):
    def test_last_day_buy_is_t1_locked(self) -> None:
        lot = OpenLot(
            code="000070",
            name="特发信息",
            qty=6000,
            cost=16.29,
            buy_time="2026-09-11 09:31:00",
            orig_qty=6000,
            last_px=17.16,
        )
        data = build_holdings(
            lots={"000070": lot},
            last_session="2026-09-11",
            cash=35538.14,
            equity=336593.14,
            prev_equity=334863.33,
            initial_cash=300000.0,
            tag="_week202609",
            artifact="backtest/strategy16_core_leader/pool_1m_7d__week202609.json",
        )
        pos = data["positions"]["000070"]
        self.assertEqual(pos["qty"], 6000)
        self.assertEqual(pos["available"], 0)
        self.assertEqual(pos["today_cost"], 16.29)
        self.assertEqual(pos["peak_high"], 17.16)
        self.assertEqual(pos["tp_stage"], 0)
        self.assertEqual(data["portfolio_pool"], ["000070"])
        self.assertEqual(data["account_cash"], 35538.14)
        self.assertEqual(data["account_total_open_session"], "2026-09-11")

    def test_overnight_lot_is_sellable(self) -> None:
        lot = OpenLot(
            code="600869",
            name="远东股份",
            qty=4100,
            cost=23.78,
            buy_time="2026-09-10 09:45:00",
            orig_qty=4100,
            last_px=25.35,
        )
        data = build_holdings(
            lots={"600869": lot},
            last_session="2026-09-11",
            cash=1.0,
            equity=2.0,
            prev_equity=1.5,
            initial_cash=300000.0,
            tag="_x",
            artifact="x.json",
        )
        pos = data["positions"]["600869"]
        self.assertEqual(pos["available"], 4100)
        self.assertIsNone(pos["today_cost"])


class TestWeek202609Artifacts(unittest.TestCase):
    def test_seed_matches_week_open_slots(self) -> None:
        paths = resolve_artifacts(pool_dir=DEFAULT_POOL_DIR, tag=DEFAULT_TAG)
        self.assertTrue(paths["json"].is_file())
        data = seed_holdings(tag=DEFAULT_TAG, dry_run=True)
        self.assertEqual(data["seed_source"]["asof"], "2026-09-11")
        self.assertEqual(data["portfolio_pool"], ["000070", "600234", "600869"])
        self.assertEqual(data["account_total"], 336593.14)
        self.assertEqual(data["account_cash"], 35538.14)
        self.assertEqual(data["account_total_open"], 334863.33)
        a = data["positions"]["000070"]
        self.assertEqual(a["qty"], 6000)
        self.assertEqual(a["cost"], 16.29)
        self.assertEqual(a["buy_time"], "2026-09-11 09:31:00")
        self.assertEqual(a["available"], 0)
        self.assertEqual(a["peak_high"], 17.16)
        b = data["positions"]["600234"]
        self.assertEqual(b["qty"], 4400)
        self.assertEqual(b["cost"], 22.04)
        self.assertEqual(b["available"], 0)
        self.assertEqual(b["peak_high"], 22.04)
        c = data["positions"]["600869"]
        self.assertEqual(c["qty"], 4100)
        self.assertEqual(c["cost"], 23.78)
        self.assertEqual(c["buy_time"], "2026-09-11 09:45:00")
        self.assertEqual(c["peak_high"], 25.35)
        gold = data["positions"]["002636"]
        self.assertEqual(int(gold.get("qty") or 0), 0)


if __name__ == "__main__":
    unittest.main()
