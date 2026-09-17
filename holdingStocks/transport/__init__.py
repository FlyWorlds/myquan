"""盯盘 HTTP / WebSocket transport（从 index 拆出；逻辑尽量原样搬迁）。"""

"""盯盘 HTTP / WebSocket transport（从 index 拆出；逻辑尽量原样搬迁）。"""

from transport.http import build_watch_request_handler

__all__ = ["build_watch_request_handler"]
