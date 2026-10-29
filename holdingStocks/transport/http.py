"""盯盘 HTTP Handler 工厂（逻辑自 index.cmd_watch 内嵌 _Handler 原样迁出）。"""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from transport.websocket import ws_accept_key, ws_pack_text


def build_watch_request_handler(
    *,
    root: Path,
    watch_meta_file: Path,
    watch_ui_dist: Path,
    ws_hub: Any,
    snap_lock: Any,
    get_last_snapshot: Callable[[], Any],
    get_strategies_api: Callable[[], Any],
    get_factors_api: Callable[[], Any],
    handle_strategy16b_api: Callable[[str], tuple[int, Any]] | None = None,
    handle_sectors_api: Callable[[str], tuple[int, Any]],
    watch_ui_dist_ready: Callable[[], bool],
    on_paper_reset: Callable[[], Any] | None = None,
    on_front_rendered: Callable[[], bool] | None = None,
    on_selection_load: Callable[[dict], Any] | None = None,
) -> type[SimpleHTTPRequestHandler]:
    """返回绑定依赖后的 RequestHandler 类（供 ThreadingHTTPServer 使用）。"""

    class WatchRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, fmt: str, *log_args: Any) -> None:
            path = getattr(self, "path", "") or ""
            if watch_meta_file.name in path or path.startswith("/api/"):
                return
            if path.split("?", 1)[0] == "/ws":
                return
            super().log_message(fmt, *log_args)

        def _send_cors_if_dev(self) -> None:
            origin = self.headers.get("Origin", "")
            if origin in ("http://127.0.0.1:3000", "http://localhost:3000"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def do_OPTIONS(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/") or path == f"/{watch_meta_file.name}":
                self.send_response(204)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self._send_cors_if_dev()
                self.end_headers()
                return
            self.send_error(404)

        def end_headers(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/") or path == f"/{watch_meta_file.name}":
                self._send_cors_if_dev()
            if path in (
                f"/{watch_meta_file.name}",
                "/api/snapshot",
                "/api/shadow/status",
            ):
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
            super().end_headers()

        def _send_json(self, data: Any, *, status: int = 200, cache_control: str = "no-store") -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            self.wfile.write(body)

        def _wechat_login(self, *, start: bool = False, test: bool = False) -> None:
            # Authentication QR data is only available to our local UI.
            allowed_hosts = {"127.0.0.1", "localhost", "::1"}
            host = urlparse("http://" + self.headers.get("Host", "")).hostname
            origin = self.headers.get("Origin")
            expected = {f"http://{h}:{self.server.server_port}" for h in ("127.0.0.1", "localhost")}
            expected.update({"http://127.0.0.1:3000", "http://localhost:3000"})
            if (self.client_address[0] not in allowed_hosts or host not in allowed_hosts
                    or (origin and origin not in expected)
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                self._send_json({"error": "local origin required"}, status=403)
                return
            from wechat_login import login
            self._send_json(login.send_test() if test else login.start() if start else login.status())

        @staticmethod
        def _content_type(path: Path) -> str:
            ext = path.suffix.lower()
            return {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".json": "application/json; charset=utf-8",
                ".ico": "image/x-icon",
                ".png": "image/png",
                ".woff2": "font/woff2",
            }.get(ext, "application/octet-stream")

        def _serve_path(self, file_path: Path) -> None:
            if not file_path.is_file():
                self.send_error(404, "Not Found")
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", self._content_type(file_path))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _resolve_ui_file(self, path: str) -> Path | None:
            if not watch_ui_dist_ready():
                return None
            rel = path.split("?", 1)[0].lstrip("/") or "index.html"
            candidate = (watch_ui_dist / rel).resolve()
            try:
                candidate.relative_to(watch_ui_dist.resolve())
            except ValueError:
                return None
            return candidate if candidate.is_file() else None

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == '/api/strategy3/scan':
                from strategy.strategies.strategy3.manual_scan import status
                from strategy3_watch import build_strategy3_payload
                self._send_json(dict(job=status(),payload=build_strategy3_payload()))
                return
            if path == "/api/wechat/login":
                self._wechat_login()
                return
            if path in ("/api/condition-buy/report", "/api/condition-buy/report.csv"):
                from condition_order_report import comparison_report, comparison_csv

                with snap_lock:
                    report = comparison_report(get_last_snapshot())
                if path.endswith(".csv"):
                    if not report["ready"]:
                        self._send_json(report, status=503)
                        return
                    body = comparison_csv(report)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="strategy16-{report["session"]}.csv"')
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._send_json(report)
                return
            if path == "/ws":
                self._handle_ws_upgrade()
                return
            if path == "/api/shadow/status":
                try:
                    from transport.shadow_status import shadow_status_payload

                    self._send_json(shadow_status_payload())
                except Exception as exc:  # noqa: BLE001
                    self._send_json(
                        {"error": "shadow status unavailable", "detail": type(exc).__name__},
                        status=500,
                    )
                return
            if path == "/api/stock/profile":
                qs = parse_qs(urlparse(self.path).query)
                raw = (qs.get("code") or [""])[0]
                try:
                    from stock_profile import _has_valuation, get_stock_profile, normalize_stock_code

                    code = normalize_stock_code(raw)
                    if not code:
                        self._send_json({"error": "invalid code"}, status=400)
                        return
                    profile_data = get_stock_profile(code)
                    cc = (
                        "private, max-age=60"
                        if _has_valuation(profile_data)
                        else "no-cache, no-store, must-revalidate"
                    )
                    self._send_json(
                        profile_data,
                        cache_control=cc,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._send_json(
                        {"error": "profile unavailable", "detail": type(exc).__name__},
                        status=500,
                    )
                return
            if path.startswith("/api/sectors/"):
                status, data = handle_sectors_api(self.path)
                self._send_json(data, status=status)
                return
            if path == "/api/strategy16b/select" and handle_strategy16b_api is not None:
                status, data = handle_strategy16b_api(self.path)
                self._send_json(data, status=status)
                return
            if path == "/api/holdings/returns-calendar" or path.startswith("/api/strategy16b/groups") or path.startswith("/api/strategy16b/replay/"):
                try:
                    from selection_groups import backend, replay_status
                    if path.startswith("/api/strategy16b/replay/"):
                        data = replay_status(path.rsplit("/", 1)[-1])
                    else:
                        endpoint = "returns-calendar" if path.startswith("/api/holdings/") else "selection-groups" + path[len("/api/strategy16b/groups"):]
                        query = urlparse(self.path).query
                        data = backend(endpoint + ("?" + query if query else ""))
                    self._send_json(data)
                except Exception:
                    self._send_json({"error": "数据库读取失败"}, status=503)
                return
            if path == "/api/strategies":
                self._send_json(get_strategies_api())
                return
            if path == "/api/factors":
                self._send_json(get_factors_api())
                return
            if path == "/api/strategy1/backtest":
                try:
                    from strategy1_backtest_service import Strategy1BacktestManager

                    self._send_json(Strategy1BacktestManager.get_status())
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": "backtest status unavailable", "detail": str(exc)}, status=500)
                return
            if path == "/api/trades":
                from trade_ledger import api_trades_payload
                try:
                    status, payload = api_trades_payload(self.path)
                    self._send_json(payload, status=status)
                except Exception:
                    self._send_json({"error": "database trade ledger unavailable"}, status=503)
                return
            if path == "/api/market-radar":
                from market_radar import SERVICE
                self._send_json(SERVICE.get(force=(parse_qs(urlparse(self.path).query).get('refresh') == ['1'])))
                return
            if path == "/api/holdings/state":
                try:
                    from database_holdings import request_state
                    self._send_json(request_state())
                except Exception:
                    self._send_json({"error": "database holdings unavailable"}, status=503)
                return
            if path in ("/api/holdings/history", "/api/holdings/closed"):
                try:
                    import os
                    from urllib.request import urlopen
                    base=os.environ.get("PAPER_BACKEND_URL","http://127.0.0.1:8080").rstrip("/")
                    endpoint="account-snapshots" if path.endswith("history") else "closed"
                    query=urlparse(self.path).query
                    with urlopen(base+"/api/paper/"+endpoint+("?"+query if query else ""),timeout=5) as response:
                        self._send_json(json.load(response))
                except Exception:
                    self._send_json({"error":"account history unavailable"},status=503)
                return
            if path in ("/api/snapshot", f"/{watch_meta_file.name}"):
                with snap_lock:
                    snap = get_last_snapshot()
                if snap is None:
                    try:
                        from database_holdings import database_enabled

                        if database_enabled():
                            from runtime_documents import read_document

                            _rev, snap = read_document("watch_snapshot")
                        elif watch_meta_file.is_file():
                            snap = json.loads(watch_meta_file.read_text(encoding="utf-8"))
                    except (OSError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
                        snap = None
                if snap is None:
                    self._send_json({"error": "snapshot unavailable"}, status=503)
                    return
                self._send_json(snap)
                return
            ui_file = self._resolve_ui_file(path)
            if ui_file is not None:
                self._serve_path(ui_file)
                return
            if watch_ui_dist_ready() and path != f"/{watch_meta_file.name}":
                self._serve_path(watch_ui_dist / "index.html")
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split('?',1)[0]=='/api/strategy3/scan':
                host=urlparse('http://'+self.headers.get('Host','')).hostname
                origin=self.headers.get('Origin')
                allowed={f'http://{h}:{self.server.server_port}' for h in ('localhost','127.0.0.1')}
                allowed.update({'http://localhost:3000','http://127.0.0.1:3000'})
                if self.client_address[0] not in ('127.0.0.1','::1') or host not in ('localhost','127.0.0.1','::1') or (origin and origin not in allowed) or self.headers.get('Sec-Fetch-Site')=='cross-site':
                    self._send_json({'error':'local origin required'},status=403);return
                from strategy.strategies.strategy3.manual_scan import start
                self._send_json(dict(job=start()),status=202)
                return
            if self.path.split("?", 1)[0] == "/api/wechat/test":
                self._wechat_login(test=True)
                return
            if self.path.split("?", 1)[0] == "/api/wechat/login":
                self._wechat_login(start=True)
                return
            if self.path.split("?", 1)[0] == "/api/front-rendered":
                ready = bool(on_front_rendered and on_front_rendered())
                self._send_json({"ready": ready}, status=200 if ready else 503)
                return
            path = self.path.split("?", 1)[0]
            if path in ("/api/strategy16b/groups", "/api/strategy16b/replay", "/api/strategy16b/activate", "/api/strategy16b/groups/default"):
                try:
                    from selection_groups import backend, start_replay
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 1000000:
                        self._send_json({"error": "Invalid request size"}, status=400)
                        return
                    body = json.loads(self.rfile.read(length))
                    if path.endswith("groups/default"):
                        data = backend("selection-groups/default", body)
                    elif path.endswith("activate"):
                        group_id = str(__import__('uuid').UUID(body["groupId"]))
                        data = json.loads(backend("selection-groups/" + group_id)["payload"])
                        if on_selection_load is None:
                            raise ValueError("选股载入不可用")
                        loaded = on_selection_load(data)
                        if isinstance(loaded, dict):
                            data = loaded
                    else:
                        data = backend("selection-groups", body) if path.endswith("groups") else start_replay(str(__import__('uuid').UUID(body["groupId"])))
                    self._send_json(data)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                except Exception:
                    self._send_json({"error": "数据库保存或回测启动失败"}, status=503)
                return
            if path == "/api/strategy1/backtest":
                try:
                    from strategy1_backtest_service import Strategy1BacktestManager

                    self._send_json(Strategy1BacktestManager.trigger_backtest())
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": "backtest trigger failed", "detail": str(exc)}, status=500)
                return
            if path == "/api/holdings/reset":
                if on_paper_reset is None:
                    self._send_json({"error": "reset unavailable"}, status=503)
                    return
                try:
                    self._send_json(on_paper_reset() or {"ok": True})
                except Exception as exc:  # noqa: BLE001
                    self._send_json(
                        {"error": "reset failed", "detail": type(exc).__name__},
                        status=500,
                    )
                return
            self.send_error(404, "Not Found")

        def _handle_ws_upgrade(self) -> None:
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self.send_error(400, "Missing Sec-WebSocket-Key")
                return
            if (self.headers.get("Upgrade") or "").lower() != "websocket":
                self.send_error(400, "Expected Upgrade: websocket")
                return
            accept = ws_accept_key(key)
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            try:
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass
            snap = None
            with snap_lock:
                snap = get_last_snapshot()
            if snap is not None:
                try:
                    self.connection.sendall(
                        ws_pack_text(json.dumps(snap, ensure_ascii=False))
                    )
                except OSError:
                    pass
            self.close_connection = True
            ws_hub.serve_client(self.connection)

    return WatchRequestHandler
