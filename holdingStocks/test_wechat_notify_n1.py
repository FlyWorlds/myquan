"""Notification Phase N1：预警/成交微信语义与去重（不碰 Decision/Shadow）。"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import wechat_notify as wn


def _row(**kw):
    base = {
        "代码": "600330",
        "名称": "天通股份",
        "现价": 12.34,
        "价位小数": 2,
        "持仓": 0,
        "预警": "",
        "持仓状态": "空仓",
        "已触买": "否",
        "已触止损": "否",
        "过门OK": True,
    }
    base.update(kw)
    return base


class TestWechatNotifyN1(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state = Path(self._tmpdir.name) / "wechat_alert_state.json"
        self._prev_state = wn.STATE_FILE
        wn.STATE_FILE = self._state
        wn.set_watch_wechat_enabled(True)
        self._cfg = {"enabled": True, "cooldown_sec": 60, "target": "test"}
        self._sent: list[str] = []

        def _fake_send(message: str, *, config=None, retries=None):
            self._sent.append(str(message))
            return True, "ok"

        self._send_patch = patch.object(wn, "send_text", side_effect=_fake_send)
        self._send_patch.start()

    def tearDown(self) -> None:
        self._send_patch.stop()
        wn.set_watch_wechat_enabled(None)
        wn.STATE_FILE = self._prev_state
        self._tmpdir.cleanup()

    def test_near_buy_is_strategy_alert(self) -> None:
        info = wn.classify_stock_alert(_row(预警="将买入", 近买点=True, 持仓状态="待买入"))
        self.assertIsNotNone(info)
        self.assertEqual(info["type"], "将买入")
        msg = wn.format_alert_message(_row(预警="将买入", 近买点=True, 持仓状态="待买入"))
        self.assertIn("【策略预警】", msg)
        self.assertIn("将买入", msg)
        wn.notify_watch_rows(
            [_row(预警="将买入", 近买点=True, 持仓状态="待买入")],
            config=self._cfg,
        )
        self.assertEqual(len(self._sent), 1)
        self.assertIn("【策略预警】", self._sent[0])

    def test_unfilled_buy_signal_is_strategy_alert(self) -> None:
        row = _row(
            预警="已触买·未入槽",
            已触买="是",
            持仓状态="待买入",
            因子触发="已触发",
        )
        info = wn.classify_stock_alert(row)
        self.assertEqual(info["status"], "已触买但尚未实际成交")
        self.assertNotIn("模拟买入", wn.format_alert_message(row))

    def test_actual_buy_fill_not_rescanned(self) -> None:
        fill_ok = wn.notify_trade_fill(
            side="buy",
            code="600330",
            name="天通股份",
            price=12.34,
            qty=1000,
            after_qty=1000,
            before_qty=0,
            strategy_id="strategy16",
            config=self._cfg,
        )
        self.assertTrue(fill_ok)
        filled = _row(
            持仓=1000,
            槽位占用=True,
            预警="已触买·已入槽",
            已触买="是",
            持仓状态="已经买入",
        )
        self.assertIsNone(wn.classify_stock_alert(filled))
        wn.notify_watch_rows([filled], config=self._cfg)
        self.assertEqual(len(self._sent), 1)
        self.assertIn("【模拟买入】", self._sent[0])
        self.assertNotIn("【策略预警】", self._sent[0])

    def test_working_stop_sell_fill(self) -> None:
        ok = wn.notify_trade_fill(
            side="sell",
            code="600330",
            name="天通股份",
            price=11.0,
            qty=400,
            before_qty=400,
            after_qty=0,
            action_kind="full",
            exit_kind="last",
            config=self._cfg,
        )
        self.assertTrue(ok)
        self.assertEqual(len(self._sent), 1)
        msg = self._sent[0]
        self.assertIn("【模拟卖出】", msg)
        self.assertIn("原因：WORKING_STOP", msg)
        self.assertIn("仓位：400 → 0", msg)
        self.assertIn("成交类型：全仓", msg)

    def test_open_protect_sell_fill(self) -> None:
        wn.notify_trade_fill(
            side="sell",
            code="600330",
            name="天通股份",
            price=10.5,
            qty=400,
            before_qty=400,
            after_qty=0,
            action_kind="full",
            exit_kind="open_protect",
            config=self._cfg,
        )
        self.assertIn("原因：OPEN_PROTECT", self._sent[0])

    def test_path_sell_fill(self) -> None:
        wn.notify_trade_fill(
            side="sell",
            code="600330",
            name="天通股份",
            price=10.8,
            qty=400,
            before_qty=400,
            after_qty=0,
            action_kind="full",
            exit_kind="path",
            config=self._cfg,
        )
        self.assertIn("原因：PATH", self._sent[0])

    def test_partial_sell_fill_after_qty(self) -> None:
        wn.notify_trade_fill(
            side="sell",
            code="600330",
            name="天通股份",
            price=11.2,
            qty=200,
            before_qty=400,
            after_qty=200,
            action_kind="half",
            exit_kind="path",
            quantity_ratio=0.5,
            config=self._cfg,
        )
        msg = self._sent[0]
        self.assertIn("【模拟卖出】", msg)
        self.assertIn("成交类型：半仓", msg)
        self.assertIn("仓位：400 → 200", msg)
        self.assertIn("原因：PATH", msg)
        self.assertIn("quantity_ratio：0.5000", msg)
        realized = _row(
            持仓=200,
            已实现=True,
            预警="半仓止盈",
            已触止损="是",
            持仓状态="已经买入",
        )
        self.assertIsNone(wn.classify_stock_alert(realized))
        wn.notify_watch_rows([realized], config=self._cfg)
        self.assertEqual(len(self._sent), 1)

    def test_t1_block_is_alert_not_sell(self) -> None:
        row = _row(
            持仓=1000,
            预警="持有·T+1·止损已记",
            已触止损="是",
            持仓状态="已经买入",
            可用=0,
        )
        info = wn.classify_stock_alert(row)
        self.assertEqual(info["type"], "T1_BLOCK")
        msg = wn.format_alert_message(row)
        self.assertIn("【策略预警】", msg)
        self.assertIn("T+1 暂不可卖", msg)
        self.assertIn("原因：T1_BLOCK", msg)
        self.assertNotIn("【模拟卖出】", msg)
        wn.notify_watch_rows([row], config=self._cfg)
        self.assertEqual(len(self._sent), 1)
        self.assertNotIn("【模拟卖出】", self._sent[0])

    def test_shadow_evaluation_zero_notifications(self) -> None:
        from strategy.exit_rules import shadow as shadow_mod

        src = Path(inspect.getfile(shadow_mod)).read_text(encoding="utf-8")
        self.assertNotIn("wechat", src.lower())
        self.assertNotIn("notify_trade_fill", src)
        self.assertNotIn("notify_watch_rows", src)
        legacy = {
            "hit": True,
            "hit_show": True,
            "fill_px": 10.0,
            "kind": "last",
            "action_kind": "full",
            "stop_kind": "",
            "reason": "last",
            "open_bell": False,
        }
        kw = {
            "qty": 400,
            "sellable": 400,
            "t1_today": False,
            "last": 10.0,
            "open_px": 10.2,
            "prev_close": 10.3,
            "cost": 10.5,
            "peak_high": 10.8,
            "working_stop": 10.2,
            "path_hit": False,
            "path_fill_px": 0.0,
            "signal_ok": True,
            "symbol": "600330",
            "session": "2026-09-18",
        }
        before = len(self._sent)
        out = shadow_mod.maybe_shadow_and_select(legacy, paper_kwargs=kw)
        self.assertEqual(len(self._sent), before)
        self.assertIsInstance(out, dict)

    def test_no_wechat_covers_alert_and_fill(self) -> None:
        wn.set_watch_wechat_enabled(False)
        alert_row = _row(预警="将买入", 近买点=True, 持仓状态="待买入")
        self.assertEqual(wn.notify_watch_rows([alert_row], config=self._cfg), [])
        buy_ok = wn.notify_trade_fill(
            side="buy",
            code="600330",
            name="天通股份",
            price=12.34,
            qty=1000,
            config=self._cfg,
        )
        sell_ok = wn.notify_trade_fill(
            side="sell",
            code="600330",
            name="天通股份",
            price=11.0,
            qty=200,
            action_kind="half",
            exit_kind="path",
            before_qty=400,
            after_qty=200,
            config=self._cfg,
        )
        self.assertFalse(buy_ok)
        self.assertFalse(sell_ok)
        self.assertEqual(self._sent, [])

    def test_strategy1_overlay_not_in_default_alert_scope(self) -> None:
        overlay = _row(代码="000001", 名称="平安银行", 预警="将买入", 近买点=True)
        default = _row(预警="将买入", 近买点=True)
        with patch.object(
            wn,
            "in_default_strategy_alert_scope",
            side_effect=lambda code: str(code) == "600330",
        ):
            rows = wn.filter_default_strategy_alert_rows([overlay, default])
        codes = {str(r.get("代码")) for r in rows}
        self.assertIn("600330", codes)
        self.assertNotIn("000001", codes)

    def test_sell_fill_still_sends_outside_default_pool(self) -> None:
        """实仓 SELL 不因离开 strategy16 池而禁止成交微信。"""
        with patch.object(wn, "in_default_strategy_alert_scope", return_value=False):
            ok = wn.notify_trade_fill(
                side="sell",
                code="000001",
                name="平安银行",
                price=11.0,
                qty=100,
                before_qty=100,
                after_qty=0,
                exit_kind="last",
                config=self._cfg,
            )
        self.assertTrue(ok)
        self.assertEqual(len(self._sent), 1)
        self.assertIn("【模拟卖出】", self._sent[0])
        self.assertIn("WORKING_STOP", self._sent[0])

    def test_slot_full_unfilled_is_alert(self) -> None:
        row = _row(
            预警="已触买·槽满",
            已触买="是",
            持仓状态="待买入",
            因子触发="已触发",
        )
        info = wn.classify_stock_alert(row)
        self.assertEqual(info["status"], "槽满")
        self.assertIn("【策略预警】", wn.format_alert_message(row))

    def test_map_reason_codes_from_exit_kind_only(self) -> None:
        self.assertEqual(wn.map_fill_reason_code(exit_kind="last"), "WORKING_STOP")
        self.assertEqual(wn.map_fill_reason_code(exit_kind="open_protect"), "OPEN_PROTECT")
        self.assertEqual(wn.map_fill_reason_code(exit_kind="path"), "PATH")
        self.assertEqual(wn.map_fill_reason_code(exit_kind="eod_reserve"), "EOD_RESERVE")
        self.assertEqual(wn.map_fill_reason_code(action_kind="half"), "HALF")


class TestApplyFillPassesExitKind(unittest.TestCase):
    def setUp(self) -> None:
        import index as idx

        self.idx = idx
        self.data = {
            "updated_at": None,
            "account_total": 300000.0,
            "account_cash": 200000.0,
            "positions": {
                "600000": {
                    "name": "测试",
                    "market": "上证",
                    "qty": 400,
                    "available": 400,
                    "cost": 10.0,
                    "buy_time": "2026-09-11 09:35:00",
                    "today_cost": None,
                    "tp_stage": 0,
                    "last_tp_ts": None,
                    "note": "",
                    "peak_high": 10.0,
                }
            },
            "realized_today": {},
            "closed_today": {},
        }
        self.calls: list[dict] = []
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        self._remember = idx.remember_factor_trigger
        idx.load_holdings = lambda: self.data
        idx.save_holdings = self._save_holdings
        idx.append_trade = lambda *_a, **_k: None
        idx.remember_factor_trigger = lambda *_a, **_k: None

        def _capture(**kw):
            self.calls.append(kw)
            return True

        self._notify = patch("wechat_notify.notify_trade_fill", side_effect=_capture)
        self._notify.start()

    def _save_holdings(self, data: dict) -> None:
        self.data = data

    def tearDown(self) -> None:
        self._notify.stop()
        self.idx.load_holdings = self._load
        self.idx.save_holdings = self._save
        self.idx.append_trade = self._append
        self.idx.remember_factor_trigger = self._remember

    def test_apply_stop_fill_forwards_exit_kind_and_qty(self) -> None:
        rec = self.idx.apply_stop_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            stop_px=11.0,
            qty=400,
            cost=10.0,
            session="2026-09-12",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            action_kind="full",
            stop_kind="",
            exit_kind="open_protect",
        )
        self.assertEqual(int(rec.get("after_qty") if rec.get("after_qty") is not None else -1), 0)
        self.assertEqual(len(self.calls), 1)
        kw = self.calls[0]
        self.assertEqual(kw.get("exit_kind"), "open_protect")
        self.assertEqual(kw.get("before_qty"), 400)
        self.assertEqual(kw.get("after_qty"), 0)
        self.assertEqual(int(self.data["positions"]["600000"]["qty"]), 0)

    def test_no_wechat_does_not_change_execution(self) -> None:
        wn.set_watch_wechat_enabled(False)
        try:
            rec = self.idx.apply_stop_fill(
                code="600000",
                meta={"name": "测试", "market": "上证"},
                stop_px=11.0,
                qty=400,
                cost=10.0,
                session="2026-09-12",
                buy_time="2026-09-11 09:35:00",
                prev_close=10.2,
                open_px=10.3,
                px_digits=2,
                action_kind="half",
                stop_kind="ladder_half_10",
                exit_kind="path",
            )
        finally:
            wn.set_watch_wechat_enabled(None)
        self.assertEqual(int(rec.get("after_qty") or 0), 200)
        self.assertEqual(int(self.data["positions"]["600000"]["qty"]), 200)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
