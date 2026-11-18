# -*- coding: utf-8 -*-
import unittest
from datetime import datetime
from strategy.pullback_wave_stop import working_stop_price
from watch_config import is_auction_result


class TestAuctionOpenSellSide(unittest.TestCase):
    def test_603206_jiahuan_open_peak_upgrade(self):
        """嘉环科技实测场景：成本 13.62，昨收/历史峰值 14.66，今开 15.04。

        - 历史峰值 14.66 时：盈亏 +7.64% (中赚)，卖出侧为 14.39 (中赚波动回落)。
        - 09:25 开盘价 15.04 出炉后：盈亏 +10.43% (大赚)，峰值应升至 15.04，
          卖出侧应即时更新为 14.73，卖出原因应即时升级为「大赚后峰值回落」。
        """
        cost = 13.62
        old_peak = 14.66
        open_px = 15.04
        vol20 = 0.036

        # 旧峰值
        old_kind, old_stop = working_stop_price(
            cost_px=cost, peak_high=old_peak, vol20_daily=vol20, tick=0.01
        )
        self.assertEqual(old_kind, "vol_giveback")
        self.assertEqual(old_stop, 14.39)

        # 9:25 开盘价抬升峰值后
        new_kind, new_stop = working_stop_price(
            cost_px=cost,
            peak_high=open_px,
            session_peak=open_px,
            day_open=open_px,
            vol20_daily=vol20,
            tick=0.01,
        )
        self.assertEqual(new_kind, "peak_pullback")
        self.assertEqual(new_stop, 14.73)

    def test_sync_snapshot_hwm_at_0925(self):
        """测试 09:25:15 集合竞价确立时，_sync_snapshot_hwm_locked 能即时抬升峰值并刷新卖出侧。"""
        from index import _sync_snapshot_hwm_locked

        code = "603206"
        sess = datetime.now().strftime("%Y-%m-%d")
        snap = {
            "holdings": [
                {
                    "代码": code,
                    "成本": 13.62,
                    "持仓": 4200,
                    "持仓最高": 14.66,
                    "卖出侧价": 14.39,
                    "卖出原因": "中赚波动回落",
                    "价位小数": 2,
                    "最高": 15.04,
                }
            ]
        }
        mock_quote = {
            "open": 15.04,
            "last": 15.04,
            "high": 15.04,
            "low": 15.04,
            "prev_close": 14.66,
            "session": sess,
            "last_ts": f"{sess} 09:25:15",
        }

        # 构造内存 positions 数据
        import index
        original_load = index.load_holdings
        original_save = index.save_holdings
        mock_holdings_db = {
            "positions": {
                code: {
                    "qty": 4200,
                    "cost": 13.62,
                    "buy_time": "2026-11-16 10:30:00",
                    "peak_high": 14.66,
                    "peak_high_at": "2026-11-17 14:30:00",
                }
            }
        }
        try:
            index.load_holdings = lambda: mock_holdings_db
            index.save_holdings = lambda d: mock_holdings_db.update(d)

            changed = _sync_snapshot_hwm_locked(
                snap,
                get_quote=lambda s: mock_quote,
                sina_of=lambda c: f"sh{c}",
            )
            self.assertTrue(changed)
            # 验证数据库持仓峰值已更新
            pos = mock_holdings_db["positions"][code]
            self.assertEqual(pos["peak_high"], 15.04)
            # 验证快照行卖出侧价格已即时更新为 14.73 与大赚后峰值回落
            r = snap["holdings"][0]
            self.assertEqual(r["持仓最高"], 15.04)
            self.assertEqual(r["卖出侧价"], 14.73)
            self.assertEqual(r["卖出原因"], "大赚后峰值回落")
            self.assertEqual(r["stop_kind"], "peak_pullback")
        finally:
            index.load_holdings = original_load
            index.save_holdings = original_save

    def test_virtual_auction_before_0925_cannot_raise_peak(self):
        """09:15:00~09:24:59 虚假竞价申报不得抬升峰值。"""
        from index import _sync_snapshot_hwm_locked
        import index

        code = "603206"
        sess = datetime.now().strftime("%Y-%m-%d")
        snap = {
            "holdings": [
                {
                    "代码": code,
                    "成本": 13.62,
                    "持仓": 4200,
                    "持仓最高": 14.66,
                    "卖出侧价": 14.39,
                    "卖出原因": "中赚波动回落",
                    "价位小数": 2,
                }
            ]
        }
        mock_quote = {
            "open": 16.00,
            "last": 16.00,
            "high": 16.00,
            "session": sess,
            "last_ts": f"{sess} 09:18:00",
        }
        mock_holdings_db = {
            "positions": {
                code: {
                    "qty": 4200,
                    "cost": 13.62,
                    "buy_time": "2026-11-16 10:30:00",
                    "peak_high": 14.66,
                    "peak_high_at": "2026-11-17 14:30:00",
                }
            }
        }
        original_load = index.load_holdings
        original_save = index.save_holdings
        try:
            index.load_holdings = lambda: mock_holdings_db
            index.save_holdings = lambda d: mock_holdings_db.update(d)

            _sync_snapshot_hwm_locked(
                snap,
                get_quote=lambda s: mock_quote,
                sina_of=lambda c: f"sh{c}",
            )
            pos = mock_holdings_db["positions"][code]
            # 09:18 虚假申报绝对不应抬升 HWM
            self.assertEqual(pos["peak_high"], 14.66)
        finally:
            index.load_holdings = original_load
            index.save_holdings = original_save

    def test_lower_open_does_not_reduce_peak(self):
        """09:25 开盘价若低于历史峰值，峰值维持高水位不降。"""
        from index import _sync_snapshot_hwm_locked
        import index

        code = "603206"
        sess = datetime.now().strftime("%Y-%m-%d")
        snap = {
            "holdings": [
                {
                    "代码": code,
                    "成本": 13.62,
                    "持仓": 4200,
                    "持仓最高": 14.66,
                    "卖出侧价": 14.39,
                    "卖出原因": "中赚波动回落",
                    "价位小数": 2,
                }
            ]
        }
        mock_quote = {
            "open": 14.20,
            "last": 14.20,
            "high": 14.20,
            "session": sess,
            "last_ts": f"{sess} 09:25:30",
        }
        mock_holdings_db = {
            "positions": {
                code: {
                    "qty": 4200,
                    "cost": 13.62,
                    "buy_time": "2026-11-16 10:30:00",
                    "peak_high": 14.66,
                    "peak_high_at": "2026-11-17 14:30:00",
                }
            }
        }
        original_load = index.load_holdings
        original_save = index.save_holdings
        try:
            index.load_holdings = lambda: mock_holdings_db
            index.save_holdings = lambda d: mock_holdings_db.update(d)

            _sync_snapshot_hwm_locked(
                snap,
                get_quote=lambda s: mock_quote,
                sina_of=lambda c: f"sh{c}",
            )
            pos = mock_holdings_db["positions"][code]
            self.assertEqual(pos["peak_high"], 14.66)
        finally:
            index.load_holdings = original_load
            index.save_holdings = original_save


if __name__ == "__main__":
    unittest.main()
