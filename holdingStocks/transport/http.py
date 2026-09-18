"""盯盘 HTTP Handler 工厂（逻辑自 index.cmd_watch 内嵌 _Handler 原样迁出）。"""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable

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
    handle_sectors_api: Callable[[str], tuple[int, Any]],
    watch_ui_dist_ready: Callable[[], bool],
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
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
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

        def _send_json(self, data: Any, *, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

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
            if path.startswith("/api/sectors/"):
                status, data = handle_sectors_api(self.path)
                self._send_json(data, status=status)
                return
            if path == "/api/strategies":
                self._send_json(get_strategies_api())
                return
            if path == "/api/factors":
                self._send_json(get_factors_api())
                return
            if path == "/api/trades":
                from trade_ledger import api_trades_payload

                status, payload = api_trades_payload(self.path)
                self._send_json(payload, status=status)
                return
            if path in ("/api/snapshot", f"/{watch_meta_file.name}"):
                with snap_lock:
                    snap = get_last_snapshot()
                if snap is None and watch_meta_file.is_file():
                    try:
                        snap = json.loads(
                            watch_meta_file.read_text(encoding="utf-8")
                        )
                    except (OSError, TypeError, ValueError, json.JSONDecodeError):
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
