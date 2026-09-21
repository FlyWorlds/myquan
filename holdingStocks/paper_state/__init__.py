"""Remote Paper Trading State — Phase R1.

生产路径（R3+）：
  holdingStocks logic → PaperStatePort → PostgresPaperStateAdapter

本阶段（R1）：
  · 接口 + LocalJson 适配器 + Postgres skeleton + schema
  · 迁移 dry-run
  · 单测（内存 / local JSON）
  · **不**切换生产 backend、不写真实 remote、不改业务语义
"""

from __future__ import annotations

from paper_state.errors import (
    DuplicateExecutionError,
    LeaseConflictError,
    PaperStateError,
    RemoteUnavailableError,
    StateConflictError,
    StaleWriterError,
)
from paper_state.models import (
    AccountSnapshot,
    DailyState,
    PaperTrade,
    PositionRecord,
    WriterLease,
)
from paper_state.port import PaperStatePort, create_paper_state_port

__all__ = [
    "AccountSnapshot",
    "DailyState",
    "DuplicateExecutionError",
    "LeaseConflictError",
    "PaperStateError",
    "PaperStatePort",
    "PaperTrade",
    "PositionRecord",
    "RemoteUnavailableError",
    "StateConflictError",
    "StaleWriterError",
    "WriterLease",
    "create_paper_state_port",
]
