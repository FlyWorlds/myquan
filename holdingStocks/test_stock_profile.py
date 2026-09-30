"""个股 hover 画像：板块反查、关联关系、HTTP 路由。"""

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
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from stock_profile import (  # noqa: E402
    _related_from_boards,
    em_f10_code,
    get_stock_profile,
    normalize_stock_code,
)
from transport.http import build_watch_request_handler  # noqa: E402


FAKE_INDEX = {
    "行业": {"光学光电子": ["002273", "002036", "000586"]},
    "概念": {
        "AR概念": ["002273", "000977", "002475"],
        "消费电子": ["002273", "002415"],
        "光学产业链上游": ["002273", "300433"],
        "车载下游应用": ["002273", "002920"],
    },
}


class TestNormalize(unittest.TestCase):
    def test_digits_and_prefix(self) -> None:
        self.assertEqual(normalize_stock_code("sz002273"), "002273")
        self.assertEqual(normalize_stock_code("SH600519"), "600519")
        self.assertEqual(normalize_stock_code("273"), "")
        self.assertEqual(em_f10_code("002273"), "SZ002273")
        self.assertEqual(em_f10_code("600519"), "SH600519")


class TestRelatedAndProfile(unittest.TestCase):
    def test_related_labels_include_board_and_chain_role(self) -> None:
        names = {
            "002036": "联创电子",
            "000977": "浪潮信息",
            "300433": "蓝思科技",
            "002920": "德赛西威",
        }
        boards = {
            "行业": ["光学光电子"],
            "概念": ["光学产业链上游", "车载下游应用", "AR概念"],
        }
        rows = _related_from_boards("002273", boards, FAKE_INDEX, names, limit=12)
        self.assertTrue(rows)
        relations = {r["relation"] for r in rows}
        self.assertTrue(any(x.startswith("同") for x in relations))
        self.assertTrue(any(r.get("role") == "上游" for r in rows))
        self.assertTrue(any(r.get("role") == "下游" for r in rows))
        self.assertTrue(all(r["code"] != "002273" for r in rows))

    def test_profile_uses_injected_sources(self) -> None:
        survey = {
            "name": "水晶光电",
            "full_name": "浙江水晶光电科技股份有限公司",
            "market": "深交所主板A股",
            "industry": "光学光电子",
            "csrc_industry": "制造业-电子设备",
            "region": "浙江",
            "registered_capital": "13.91亿",
            "list_date": "2008-09-19",
            "summary": "光学器件。",
            "business_scope": "电子元器件制造",
        }
        quote = {
            "name": "水晶光电",
            "price": 24.43,
            "chg_pct": 3.91,
            "market_cap_yi": 339.73,
            "float_cap_yi": 333.73,
            "pe": 32.4,
            "pe_ttm": 28.4,
            "pb": 3.37,
        }
        payload = get_stock_profile(
            "002273",
            fetch_survey=lambda _c: survey,
            fetch_quote=lambda _c: quote,
            fetch_themes=lambda _c: [{"name": "AR概念", "desc": ""}],
            members_index=FAKE_INDEX,
            use_cache=False,
        )
        self.assertEqual(payload["code"], "002273")
        self.assertEqual(payload["name"], "水晶光电")
        self.assertEqual(payload["valuation"]["market_cap_yi"], 339.73)
        self.assertIn("光学光电子", payload["boards"]["industry"])
        self.assertTrue(payload["related"])
        self.assertEqual(payload["chain"]["note"], "电子元器件制造")
        self.assertTrue(payload["chain"]["upstream"] or payload["chain"]["downstream"])


class _Hub:
    def serve_client(self, _conn) -> None:
        return None


class TestStockProfileHttp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        handler = build_watch_request_handler(
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
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def _get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=3) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8")) if e.fp else {}
            return e.code, body

    def test_missing_code_400(self) -> None:
        status, body = self._get("/api/stock/profile")
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "invalid code")

    def test_ok_uses_aggregator(self) -> None:
        fake = {"code": "002273", "name": "水晶光电", "related": []}
        with patch("stock_profile.get_stock_profile", return_value=fake):
            status, body = self._get("/api/stock/profile?code=sz002273")
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "水晶光电")


if __name__ == "__main__":
    unittest.main()
