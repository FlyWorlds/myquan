"""盯盘 JSON 快照（WatchSnapshot v1）— 供 Vue 前端 / WebSocket 使用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


SNAPSHOT_VERSION = 1


def _row_json(row: dict[str, Any]) -> dict[str, Any]:
    """collect_rows 行 → JSON 可序列化 dict（保留中文键，与现有逻辑一致）。"""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if str(k).startswith("_"):
            continue
        if k == "bg_class":
            out["bgClass"] = v
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _strip_holdings_pnl(row: dict[str, Any]) -> dict[str, Any]:
    """策略 Tab 用：去掉持仓口径浮盈/结算金额，仅保留信号与策略收益%。"""
    out = _row_json(row)
    for k in ("浮盈", "浮盈%", "盈亏状态", "盈亏说明", "策略收益", "市值", "成本额", "当日基数"):
        out.pop(k, None)
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


def _is_today_alert_row(row: dict[str, Any]) -> bool:
    """当日预警（买入/卖出接近或已触、槽位候选等）— 仅展示，不登记持仓。"""
    if row.get("error"):
        return False
    if int(row.get("持仓") or 0) > 0:
        return False
    if bool(row.get("已实现")):
        return False
    if bool(row.get("槽位候选")):
        return True
    alert = str(row.get("预警") or "").strip()
    pos = str(row.get("持仓状态") or "")
    if alert in ("已触买", "将买入", "已触止损") or alert.startswith("已触"):
        return True
    if "将买入" in alert or "将卖出" in alert or "近买入" in alert:
        return True
    if pos in ("待买入", "待卖出"):
        return True
    if bool(row.get("近买点")) or bool(row.get("近止损")):
        return True
    if bool(row.get("可执行")):
        return True
    hit = str(row.get("因子触发") or "")
    if hit.startswith("已触发") or hit == "接近":
        return True
    return False


def filter_portfolio_holdings(
    rows: list[dict[str, Any]],
    portfolio_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """持仓 Tab：实仓/当日留痕 + 当日预警票（预警仅展示，不登记 qty/成本）。

    排序：实仓置顶（最多 MAX_PORTFOLIO_SLOTS=3）→ 当日留痕 → 预警/候选 → 其余。
    """
    from watch_config import MAX_PORTFOLIO_SLOTS, code_key, portfolio_pool_codes

    if portfolio_codes is None:
        try:
            from index import load_holdings

            portfolio_codes = set(portfolio_pool_codes(load_holdings()))
        except Exception:  # noqa: BLE001
            portfolio_codes = set()

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        if r.get("error"):
            continue
        c = code_key(str(r.get("代码") or ""))
        in_pool = c in portfolio_codes
        alert_only = (not in_pool) and _is_today_alert_row(r)
        if not in_pool and not alert_only:
            continue
        if c in seen:
            continue
        seen.add(c)
        out = dict(r)
        if alert_only:
            out["当日预警"] = True
            out["持仓"] = 0
            # 不展示持仓口径浮盈（未登记）
            out["浮盈"] = None
            out["浮盈%"] = None
            out["盈亏状态"] = None
            out["盈亏说明"] = "当日预警·未登记持仓"
            out["市值"] = None
            out["成本额"] = None
            out["仓位%"] = None
        else:
            out.setdefault("当日预警", False)
        picked.append(out)

    def _pos_rank(pos: str) -> int:
        # 待卖出最前，再已经买入/持有，其余靠后
        if pos == "待卖出":
            return 0
        if pos in ("已经买入", "持有", "持有·T+1"):
            return 1
        if pos == "策略持有":
            return 2
        if pos in ("已止损", "当日禁买"):
            return 3
        return 4

    def _sort_key(r: dict[str, Any]) -> tuple[int, int, float, str]:
        qty = int(r.get("持仓") or 0)
        pos = str(r.get("持仓状态") or "")
        if qty > 0 or bool(r.get("槽位占用")):
            tier = 0
        elif bool(r.get("已实现")):
            tier = 1
        elif bool(r.get("当日预警")) or bool(r.get("槽位候选")) or pos == "待买入":
            tier = 2
        else:
            tier = 3
        try:
            dist = float(r.get("距买点%") if r.get("距买点%") is not None else 9_999.0)
        except (TypeError, ValueError):
            dist = 9_999.0
        return (tier, _pos_rank(pos), dist, str(r.get("代码") or ""))

    ordered = sorted(picked, key=_sort_key)
    # 实仓前 N 只标置顶（三槽）
    pinned = 0
    max_pin = int(MAX_PORTFOLIO_SLOTS)
    for r in ordered:
        qty = int(r.get("持仓") or 0)
        if qty > 0 and pinned < max_pin:
            r["置顶"] = True
            pinned += 1
        else:
            r["置顶"] = False
    return ordered


def build_watch_snapshot(
    *,
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]],
    account: dict[str, Any],
    meta: dict[str, Any],
    strategies: list[dict[str, Any]] | None = None,
    strategy3: dict[str, Any] | None = None,
    strategy8: dict[str, Any] | None = None,
    strategy15: dict[str, Any] | None = None,
    sectors: dict[str, Any] | None = None,
    refresh_sec: int = 5,
    portfolio_codes: set[str] | None = None,
    strategy_codes: set[str] | None = None,
) -> dict[str, Any]:
    """构建 WatchSnapshot v1。"""
    from watch_config import code_key, strategy_watchlist_codes

    if strategy_codes is None:
        strategy_codes = strategy_watchlist_codes()
    holdings = [
        _row_json(r)
        for r in filter_portfolio_holdings(rows, portfolio_codes=portfolio_codes)
    ]
    strategy1_rows = [
        _strip_holdings_pnl(r)
        for r in rows
        if not r.get("error") and code_key(str(r.get("代码") or "")) in strategy_codes
    ]
    slot_meta = None
    for r in rows:
        if isinstance(r.get("_slot_meta"), dict):
            slot_meta = r["_slot_meta"]
            break
    if slot_meta is None:
        try:
            from watch_config import slot_meta as _sm
            from index import load_holdings

            slot_meta = _sm(load_holdings())
        except Exception:  # noqa: BLE001
            slot_meta = {"max": 3, "weight": 0.3, "occupied": [], "occupiedCount": 0, "free": 3}
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
        "slotMeta": slot_meta,
        "indices": [_index_json(ix) for ix in indices],
        "holdings": holdings,
        "strategy1": strategy1_rows,
        "strategy3": strategy3 or {},
        "strategy8": strategy8 or {},
        "strategy15": strategy15 or {},
        "sectors": sectors or {},
        "strategies": strategies or [],
    }
