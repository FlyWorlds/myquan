# -*- coding: utf-8 -*-
"""微信会话失效自动恢复 / pending 队列 / 不阻塞盯盘（A–I）。"""

from __future__ import annotations

import importlib
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def _alias_holdingstocks(*names: str) -> None:
    for name in names:
        mod = importlib.import_module(f"holdingStocks.{name}")
        sys.modules.setdefault(name, mod)


_alias_holdingstocks("watch_buy_signal")
from holdingStocks import wechat_notify as wn

sys.modules.setdefault("wechat_notify", wn)


PREPARE_FAIL = "OutboundDeliveryError: sendMessage ret=-2 errmsg=prepare failed"
TLS_FAIL = "Error: TLS fetch failed / gateway not reachable"


class TestWechatSessionRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._state = Path(self._tmpdir.name) / "wechat_alert_state.json"
        self._prev_state = wn.STATE_FILE
        wn.STATE_FILE = self._state
        wn.set_watch_wechat_enabled(True)
        wn.set_async_delivery(True)
        wn.reset_wechat_delivery_state_for_tests()
        self._cfg = {
            "enabled": True,
            "cooldown_sec": 60,
            "target": "u@wx",
            "account": "acct",
            "send_retries": 3,
            "send_retry_backoff_sec": 0.05,
            "alert_storm_cooldown_sec": 45,
            "pending_queue_max": 80,
            "wait_inbound_sec": 2.0,
            "recover_poll_sec": 0.15,
            "flush_interval_sec": 0.05,
            "session_action_log_sec": 300,
        }
        self._calls: list[str] = []
        self._send_results: list[tuple[bool, str]] = []

    def tearDown(self) -> None:
        wn.stop_wechat_delivery_worker(join_timeout=1.0)
        wn.reset_wechat_delivery_state_for_tests()
        wn.set_async_delivery(True)
        wn.set_watch_wechat_enabled(None)
        wn.STATE_FILE = self._prev_state
        self._tmpdir.cleanup()

    def _fake_once(self, message: str, *, cfg=None):
        self._calls.append(str(message))
        if self._send_results:
            return self._send_results.pop(0)
        return True, "ok"

    # A
    def test_a_normal_send_success(self) -> None:
        with patch.object(wn, "_send_text_once", side_effect=self._fake_once):
            ok, detail = wn.send_text("hello", config=self._cfg, retries=1)
        self.assertTrue(ok)
        self.assertEqual(len(self._calls), 1)
        st = wn.get_wechat_channel_state()
        self.assertTrue(st["healthy"])
        self.assertFalse(st["session_invalid"])

    # B
    def test_b_transient_then_success(self) -> None:
        self._send_results = [(False, TLS_FAIL), (True, "ok")]
        with patch.object(wn, "_send_text_once", side_effect=self._fake_once):
            ok, _ = wn.send_text("hello", config=self._cfg, retries=3)
        self.assertTrue(ok)
        self.assertEqual(len(self._calls), 2)

    # C
    def test_c_prepare_failed_no_useless_retries(self) -> None:
        self._send_results = [(False, PREPARE_FAIL), (False, PREPARE_FAIL), (False, PREPARE_FAIL)]
        with patch.object(wn, "_send_text_once", side_effect=self._fake_once):
            ok, detail = wn.send_text("hello", config=self._cfg, retries=3)
        self.assertFalse(ok)
        self.assertEqual(wn.classify_send_error(detail), wn.ERR_SESSION_INVALID)
        # 立即返回，不应空转 3 次
        self.assertEqual(len(self._calls), 1)
        st = wn.get_wechat_channel_state()
        self.assertTrue(st["session_invalid"])
        self.assertFalse(st["healthy"])

    # D
    def test_d_session_invalid_20_alerts_nonblocking(self) -> None:
        wn._mark_session_invalid(detail=PREPARE_FAIL)
        # 不启动 worker，只测入队延迟
        t0 = time.perf_counter()
        for i in range(20):
            wn.enqueue_notification(
                message=f"将止损 {i}",
                dedupe_key=f"600330|alert|将止损|{i}",  # 不同 key 但同 type 会合并
                code="600330",
                alert_type="将止损",
                is_fill=False,
                summary="将止损",
                config=self._cfg,
            )
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.5)
        st = wn.get_wechat_channel_state()
        # 同 code+type 只留 1 条
        self.assertEqual(st["pending_notification_count"], 1)

    # E + F
    def test_e_f_inbound_refresh_recovers_and_flushes(self) -> None:
        wn._mark_session_invalid(detail=PREPARE_FAIL)
        wn._channel_state.token_mtime_at_invalid = 1000.0
        wn.enqueue_notification(
            message="alert-1",
            dedupe_key="k1",
            code="600234",
            alert_type="将止损",
            config=self._cfg,
            bypass_storm=True,
        )
        wn.enqueue_notification(
            message="fill-1",
            dedupe_key="f1",
            code="600234",
            alert_type="模拟买入",
            is_fill=True,
            config=self._cfg,
            bypass_storm=True,
        )
        # recover: first polls no refresh, then mtime advances, probe ok
        mtimes = [1000.0, 1000.0, 2000.0]
        probe_done = {"n": 0}

        def _mtime(*, config=None):
            if mtimes:
                return mtimes.pop(0)
            return 2000.0

        def _direct(message, *, config=None, retries=None):
            probe_done["n"] += 1
            self._calls.append(message)
            return True, "ok"

        with patch.object(wn, "_context_token_mtime", side_effect=_mtime):
            with patch.object(wn, "_send_text_direct", side_effect=_direct):
                ok, _ = wn.recover_wechat_session(
                    config=self._cfg,
                    wait_sec=2.0,
                    probe_message="probe",
                )
                self.assertTrue(ok)
                n = wn._flush_pending_queue(config=self._cfg, send_fn=_direct)
        self.assertGreaterEqual(n, 2)
        st = wn.get_wechat_channel_state()
        self.assertTrue(st["healthy"])
        self.assertFalse(st["session_invalid"])
        self.assertEqual(st["pending_notification_count"], 0)

    # G
    def test_g_flush_prepare_failed_repauses(self) -> None:
        wn._mark_send_success()
        wn.enqueue_notification(
            message="a",
            dedupe_key="a1",
            code="1",
            alert_type="将止损",
            config=self._cfg,
            bypass_storm=True,
        )
        wn.enqueue_notification(
            message="b",
            dedupe_key="b1",
            code="2",
            alert_type="将止损",
            config=self._cfg,
            bypass_storm=True,
        )

        results = [(True, "ok"), (False, PREPARE_FAIL)]

        def _direct(message, *, config=None, retries=None):
            self._calls.append(message)
            return results.pop(0)

        n = wn._flush_pending_queue(config=self._cfg, send_fn=_direct)
        self.assertEqual(n, 1)
        st = wn.get_wechat_channel_state()
        self.assertTrue(st["session_invalid"])
        self.assertGreaterEqual(st["pending_notification_count"], 1)

    # H
    def test_h_same_alert_no_storm(self) -> None:
        for _ in range(5):
            wn.enqueue_notification(
                message="将止损",
                dedupe_key="600330|将止损",
                code="600330",
                alert_type="将止损",
                config=self._cfg,
            )
        self.assertEqual(wn.get_wechat_channel_state()["pending_notification_count"], 1)
        # 冷却期内新 key 同 type 也不堆
        for i in range(5):
            wn.enqueue_notification(
                message=f"将止损 {i}",
                dedupe_key=f"600330|将止损|{i}",
                code="600330",
                alert_type="将止损",
                config=self._cfg,
            )
        self.assertEqual(wn.get_wechat_channel_state()["pending_notification_count"], 1)

    # I
    def test_i_wechat_down_trade_path_ok(self) -> None:
        """模拟 notify_trade_fill 在 session invalid 时不抛、不阻塞。"""
        wn._mark_session_invalid(detail=PREPARE_FAIL)
        self._send_results = [(False, PREPARE_FAIL)]

        def slow_send(message, *, config=None, retries=None):
            time.sleep(0.3)
            return False, PREPARE_FAIL

        t0 = time.perf_counter()
        with patch.object(wn, "send_text", side_effect=slow_send):
            # async：应几乎立刻返回
            ok = wn.notify_trade_fill(
                side="buy",
                code="600234",
                name="科新发展",
                price=22.0,
                qty=100,
                after_qty=100,
                before_qty=0,
                strategy_id="strategy16",
                config=self._cfg,
            )
        elapsed = time.perf_counter() - t0
        self.assertTrue(ok)  # 入队成功
        self.assertLess(elapsed, 0.2)
        st = wn.get_wechat_channel_state()
        self.assertGreaterEqual(st["pending_notification_count"], 1)

    def test_classify_errors(self) -> None:
        self.assertEqual(wn.classify_send_error(PREPARE_FAIL), wn.ERR_SESSION_INVALID)
        self.assertEqual(wn.classify_send_error(TLS_FAIL), wn.ERR_TRANSIENT)
        self.assertEqual(wn.classify_send_error("permission denied"), wn.ERR_OTHER)

    def test_worker_thread_recovers(self) -> None:
        """E 的异步 worker 版：入队后 worker 检测到 mtime 刷新并 flush。"""
        wn._mark_session_invalid(detail=PREPARE_FAIL)
        wn._channel_state.token_mtime_at_invalid = 100.0
        wn.enqueue_notification(
            message="pending-alert",
            dedupe_key="p1",
            code="000021",
            alert_type="将止损",
            config=self._cfg,
            bypass_storm=True,
        )
        refreshed = {"v": False}

        def _mtime(*, config=None):
            return 200.0 if refreshed["v"] else 100.0

        def _once(message, *, cfg=None):
            self._calls.append(message)
            return True, "Sent via openclaw-weixin"

        with patch.object(wn, "_context_token_mtime", side_effect=_mtime):
            with patch.object(wn, "_send_text_once", side_effect=_once):
                with patch.dict(wn._DEFAULT_CONFIG, self._cfg, clear=False):
                    # load_config merges file; force via patch load_config
                    with patch.object(wn, "load_config", return_value=dict(self._cfg)):
                        wn.start_wechat_delivery_worker()
                        time.sleep(0.3)
                        refreshed["v"] = True
                        deadline = time.time() + 3.0
                        while time.time() < deadline:
                            st = wn.get_wechat_channel_state()
                            if st["healthy"] and st["pending_notification_count"] == 0:
                                break
                            time.sleep(0.1)
        st = wn.get_wechat_channel_state()
        self.assertTrue(st["healthy"], st)
        self.assertEqual(st["pending_notification_count"], 0)
        self.assertGreaterEqual(len(self._calls), 1)


if __name__ == "__main__":
    unittest.main()
