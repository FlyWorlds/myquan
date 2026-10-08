"""POST /api/holdings/reset：只走回调，不改真实账本。"""

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

from transport.http import build_watch_request_handler  # noqa: E402


class _Hub:
    def serve_client(self, _conn) -> None:
        return None


def _handler(root: Path, on_reset=None):
    return build_watch_request_handler(
        root=root,
        watch_meta_file=root / "holdings_watch.json",
        watch_ui_dist=root / "dist",
        ws_hub=_Hub(),
        snap_lock=threading.Lock(),
        get_last_snapshot=lambda: None,
        get_strategies_api=lambda: {},
        get_factors_api=lambda: {},
        handle_sectors_api=lambda _p: (404, {"error": "no"}),
        watch_ui_dist_ready=lambda: False,
        on_paper_reset=on_reset,
    )


class TestHoldingsResetHttp(unittest.TestCase):
    def _serve(self, on_reset=None):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        handler = _handler(root, on_reset)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def tearDown(self) -> None:
        if getattr(self, "server", None):
            self.server.shutdown()
            self.server.server_close()
        if getattr(self, "_tmp", None):
            self._tmp.cleanup()

    def test_missing_callback_503(self) -> None:
        base = self._serve(None)
        req = urllib.request.Request(base + "/api/holdings/reset", data=b"", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 503)

    def test_callback_ok(self) -> None:
        called = []

        def _reset():
            called.append(1)
            return {"ok": True, "account_total": 300000}

        base = self._serve(_reset)
        req = urllib.request.Request(base + "/api/holdings/reset", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(resp.status, 200)
        self.assertEqual(called, [1])
        self.assertTrue(body["ok"])
        self.assertEqual(body["account_total"], 300000)


if __name__ == "__main__":
    unittest.main()
