"""sectors 包：板块轮动。"""

from .data import fetch_board_members, fetch_board_spot
from .rotation import build_rotation_payload

__all__ = [
    "build_rotation_payload",
    "fetch_board_spot",
    "fetch_board_members",
]
