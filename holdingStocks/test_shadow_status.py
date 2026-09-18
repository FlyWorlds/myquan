"""Read-only GET /api/shadow/status: telemetry only, no mutation."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from transport.http import build_watch_request_handler
from transport.shadow_status import shadow_status_payload
import strategy.exit_rules.shadow as shadow


class _Hub:
    def serve_client(self, _conn) -> None:
        return None


def _handler(root: Path):
    meta = root / "holdings_watch.json"
    return build_watch_request_handler(
        root=root,
        watch_meta_file=meta,
        watch_ui_dist=root / "dist",
        ws_hub=_Hub(),
        snap_lock=threading.Lock(),
        get_last_snapshot=lambda: None,
        get_strategies_api=lambda: {},
        get_factors_api=lambda: {},
        handle_sectors_api=lambda _p: (404, {"error": "no"}),
        watch_ui_dist_ready=lambda: False,
    )


class TestShadowStatusPayload(unittest.TestCase):
    def setUp(self) -> None:
        self._use = shadow.USE_UNIFIED_EXIT_ENGINE
        self._sh = shadow.SHADOW_UNIFIED_EXIT_ENGINE
        shadow.clear_shadow_buffer()

    def tearDown(self) -> None:
        shadow.USE_UNIFIED_EXIT_ENGINE = self._use
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = self._sh
        shadow.clear_shadow_buffer()

    def test_payload_reads_flags_and_empty_buffers(self) -> None:
        shadow.USE_UNIFIED_EXIT_ENGINE = False
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = False
        payload = shadow_status_payload()
        self.assertFalse(payload["enabled"])
        self.assertFalse(payload["use_unified"])
        self.assertEqual(payload["buffer_size"], 0)
        self.assertEqual(payload["error_count"], 0)
        self.assertIsNone(payload["last_record"])
        self.assertIsNone(payload["last_error"])
        self.assertEqual(payload["metrics"], {})

    def test_payload_does_not_clear_or_bump(self) -> None:
        shadow.emit_shadow_record({"hello": "world"})
        shadow._note_shadow_error("unit", RuntimeError("x"))
        before_m = dict(shadow.get_shadow_metrics())
        before_b = shadow.get_shadow_buffer()
        before_e = shadow.get_shadow_errors()
        payload = shadow_status_payload()
        self.assertEqual(payload["buffer_size"], 1)
        self.assertEqual(payload["error_count"], 1)
        self.assertEqual(payload["last_record"]["hello"], "world")
        self.assertIn("RuntimeError", payload["last_error"]["error"])
        payload["last_record"]["hello"] = "mutated"
        self.assertEqual(shadow.get_shadow_metrics(), before_m)
        self.assertEqual(shadow.get_shadow_buffer(), before_b)
        self.assertEqual(shadow.get_shadow_errors(), before_e)

    def test_payload_exposes_failover_metric_not_compare_error(self) -> None:
        shadow._note_shadow_error("compare_or_log", RuntimeError("c"))
        payload = shadow_status_payload()
        self.assertGreaterEqual(payload["metrics"].get("shadow_errors", 0), 1)
        self.assertEqual(payload["metrics"].get("primary_failover_to_legacy", 0), 0)
        shadow._note_shadow_error(
            "unified_engine", RuntimeError("u"), primary_failover=True
        )
        payload = shadow_status_payload()
        self.assertEqual(payload["metrics"].get("primary_failover_to_legacy"), 1)
        self.assertGreaterEqual(payload["error_count"], 2)
        self.assertEqual(payload["last_error"].get("primary"), "unified")
        self.assertEqual(payload["last_error"].get("fallback"), "legacy")


class TestShadowStatusHttp(unittest.TestCase):
    def setUp(self) -> None:
        self._use = shadow.USE_UNIFIED_EXIT_ENGINE
        self._sh = shadow.SHADOW_UNIFIED_EXIT_ENGINE
        shadow.clear_shadow_buffer()
        shadow.USE_UNIFIED_EXIT_ENGINE = False
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = True
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        handler = _handler(root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        shadow.USE_UNIFIED_EXIT_ENGINE = self._use
        shadow.SHADOW_UNIFIED_EXIT_ENGINE = self._sh
        shadow.clear_shadow_buffer()
        self._tmp.cleanup()

    def _get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=3) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8")) if exc.fp else {}
            return exc.code, body

    def test_get_returns_status(self) -> None:
        shadow.emit_shadow_record({"symbol": "600552", "legacy_action": "HOLD"})
        status, body = self._get("/api/shadow/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["enabled"])
        self.assertFalse(body["use_unified"])
        self.assertEqual(body["buffer_size"], 1)
        self.assertEqual(body["last_record"]["symbol"], "600552")
        self.assertNotIn("records", body)
        self.assertLess(body["buffer_size"], 5000)

    def test_get_does_not_mutate_shadow_state(self) -> None:
        shadow.emit_shadow_record({"n": 1})
        shadow._note_shadow_error("http", RuntimeError("e"))
        before_m = dict(shadow.get_shadow_metrics())
        before_b = list(shadow.get_shadow_buffer())
        before_e = list(shadow.get_shadow_errors())
        clear_calls: list[int] = []
        orig_clear = shadow.clear_shadow_buffer

        def tracked_clear() -> None:
            clear_calls.append(1)
            orig_clear()

        shadow.clear_shadow_buffer = tracked_clear  # type: ignore[method-assign]
        try:
            status, _body = self._get("/api/shadow/status")
        finally:
            shadow.clear_shadow_buffer = orig_clear  # type: ignore[method-assign]
        self.assertEqual(status, 200)
        self.assertEqual(clear_calls, [])
        self.assertEqual(shadow.get_shadow_metrics(), before_m)
        self.assertEqual(shadow.get_shadow_buffer(), before_b)
        self.assertEqual(shadow.get_shadow_errors(), before_e)

    def test_post_is_not_supported(self) -> None:
        req = urllib.request.Request(self.base + "/api/shadow/status", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertIn(ctx.exception.code, (404, 501))

    def test_getter_exception_fails_request_only(self) -> None:
        orig = shadow.get_shadow_metrics

        def boom() -> dict:
            raise RuntimeError("metrics down")

        shadow.get_shadow_metrics = boom  # type: ignore[method-assign]
        try:
            status, body = self._get("/api/shadow/status")
            self.assertEqual(status, 500)
            self.assertEqual(body.get("error"), "shadow status unavailable")
        finally:
            shadow.get_shadow_metrics = orig  # type: ignore[method-assign]
        snap_status, _snap = self._get("/api/snapshot")
        self.assertEqual(snap_status, 503)
        status, body = self._get("/api/shadow/status")
        self.assertEqual(status, 200)
        self.assertIn("metrics", body)

    def test_flags_untouched(self) -> None:
        use = shadow.USE_UNIFIED_EXIT_ENGINE
        sh = shadow.SHADOW_UNIFIED_EXIT_ENGINE
        self._get("/api/shadow/status")
        self.assertEqual(shadow.USE_UNIFIED_EXIT_ENGINE, use)
        self.assertEqual(shadow.SHADOW_UNIFIED_EXIT_ENGINE, sh)


if __name__ == "__main__":
    unittest.main()
