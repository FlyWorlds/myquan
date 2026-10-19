"""sectors 包：板块轮动。"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_rotation_payload",
    "fetch_board_spot",
    "fetch_board_members",
]


def __getattr__(name: str) -> Any:
    if name in ("fetch_board_spot", "fetch_board_members"):
        from . import data

        return getattr(data, name)
    if name == "build_rotation_payload":
        from . import rotation

        return getattr(rotation, name)
    raise AttributeError(name)
