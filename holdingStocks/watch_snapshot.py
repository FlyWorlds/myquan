"""盯盘 JSON 快照（WatchSnapshot v1）— 供 Vue 前端 / WebSocket 使用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


SNAPSHOT_VERSION = 1


def _row_json(row: dict[str, Any]) -> dict[str, Any]:
    """collect_rows 行 → JSON 可序列化 dict（保留中文键，与现有逻辑一致）。"""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k == "bg_class":
            out["bgClass"] = v
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _index_json(ix: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": ix.get("code"),
        "name": ix.get("name"),
        "market": ix.get("market"),
        "price": ix.get("price"),
        "chgPoints": ix.get("chg_points"),
        "chgPct": ix.get("chg_pct"),
        "error": ix.get("error"),
    }


def filter_portfolio_holdings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """持仓 Tab：实仓 + 当日已结算 + 置顶跟踪票（PORTFOLIO_PINNED_WATCHLIST）。"""
    from watch_config import PORTFOLIO_PINNED_WATCHLIST, code_key

    pinned_order = {code_key(w["code"]): i for i, w in enumerate(PORTFOLIO_PINNED_WATCHLIST)}
    picked: list[dict[str, Any]] = []
    for r in rows:
        if r.get("error"):
            continue
        c = code_key(str(r.get("代码") or ""))
        qty = int(r.get("持仓") or 0)
        if qty > 0 or bool(r.get("已实现")) or c in pinned_order:
            picked.append(r)

    def _sort_key(r: dict[str, Any]) -> tuple[int, int]:
        c = code_key(str(r.get("代码") or ""))
        qty = int(r.get("持仓") or 0)
        tier = 0 if qty > 0 else (1 if bool(r.get("已实现")) else 2)
        return (tier, pinned_order.get(c, 9999))

    return sorted(picked, key=_sort_key)


def build_watch_snapshot(
    *,
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]],
    account: dict[str, Any],
    meta: dict[str, Any],
    strategies: list[dict[str, Any]] | None = None,
    strategy3: dict[str, Any] | None = None,
    strategy8: dict[str, Any] | None = None,
    sectors: dict[str, Any] | None = None,
    refresh_sec: int = 5,
) -> dict[str, Any]:
    """构建 WatchSnapshot v1。"""
    holdings = [_row_json(r) for r in filter_portfolio_holdings(rows)]
    strategy1_rows = [
        _row_json(r)
        for r in rows
        if not r.get("error")
    ]
    return {
        "v": SNAPSHOT_VERSION,
        "type": "snapshot",
        "ts": int(datetime.now().timestamp() * 1000),
        "updatedAt": meta.get("clock") or "",
        "clock": meta.get("clock") or "",
        "phase": meta.get("phase") or "",
        "phaseKey": meta.get("phaseKey") or "",
        "refreshSec": int(refresh_sec),
        "strategy": {
            "id": meta.get("strategyId") or "",
            "name": meta.get("strategyName") or "",
            "factorsLabel": meta.get("factorsLabel") or "",
        },
        "account": account,
        "indices": [_index_json(ix) for ix in indices],
        "holdings": holdings,
        "strategy1": strategy1_rows,
        "strategy3": strategy3 or {},
        "strategy8": strategy8 or {},
        "sectors": sectors or {},
        "strategies": strategies or [],
    }
