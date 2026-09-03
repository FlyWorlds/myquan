"""板块轮动缓存：交易日列与历史列的合并规则。

硬约束（防止再出现「表头停在昨天 / 重载把 20 日写成 1 日」）：
1. dates[0] 必须是当日 session 标签（最新列在最左）。
2. 当日短结果（仅 1 列）只能覆盖/插入今日列，不得整表替换已有历史。
3. session 字段与 dates[0] 必须同时等于当日，缓存才算新鲜。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

KIND = "概念"


def today_ymd(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def session_label(session: str) -> str:
    s = str(session or "").strip()
    if len(s) >= 10 and s[4] == "-":
        return f"{s[5:7]}月{s[8:10]}日"
    return s


def kind_block(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload or not isinstance(payload, dict):
        return {}
    block = (payload.get("kinds") or {}).get(KIND) or {}
    return block if isinstance(block, dict) else {}


def date_columns(payload: dict[str, Any] | None) -> list[str]:
    dates = kind_block(payload).get("dates") or []
    return [str(x) for x in dates]


def payload_has_today_column(
    payload: dict[str, Any] | None,
    *,
    today: str | None = None,
) -> bool:
    today = today or today_ymd()
    dates = date_columns(payload)
    return bool(dates) and dates[0] == session_label(today)


def today_column_nonempty(payload: dict[str, Any] | None) -> bool:
    by = kind_block(payload).get("by_metric") or {}
    for block in by.values():
        if not isinstance(block, dict):
            continue
        cols = block.get("top") or []
        if cols and cols[0]:
            return True
    return False


def payload_session_fresh(
    payload: dict[str, Any] | None,
    *,
    today: str | None = None,
) -> bool:
    """可直接返回缓存：session、最左列都是当日，且今日列已有排名。"""
    today = today or today_ymd()
    if not payload:
        return False
    session = str(payload.get("session") or "").strip()[:10]
    if session != today:
        return False
    return payload_has_today_column(payload, today=today) and today_column_nonempty(payload)


def _metric_cols(block: dict[str, Any], side: str) -> list[list[Any]]:
    raw = block.get(side) or []
    if not isinstance(raw, list):
        return []
    return [list(col or []) if isinstance(col, list) else [] for col in raw]


def _empty_today_shell(template: dict[str, Any], today: str) -> dict[str, Any]:
    metrics = list(template.get("metrics") or [])
    if not metrics:
        hist_by = kind_block(template).get("by_metric") or {}
        metrics = list(hist_by.keys())
    by_metric = {m: {"top": [[]], "bottom": [[]]} for m in metrics}
    return {
        "session": today,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics,
        "source": template.get("source"),
        "top_n": template.get("top_n"),
        "days": template.get("days"),
        "kinds": {
            KIND: {
                "dates": [session_label(today)],
                "by_metric": by_metric,
                "members": {},
                "board_count": 0,
                "fund_note": kind_block(template).get("fund_note"),
            }
        },
    }


def splice_today_onto_hist(
    hist: dict[str, Any] | None,
    today_payload: dict[str, Any] | None,
    *,
    days: int = 20,
    today: str | None = None,
) -> dict[str, Any] | None:
    """用 today_payload 的最左列覆盖/插入今日，其余日期列来自 hist。"""
    if not today_payload or not kind_block(today_payload):
        return hist
    today_s = (today or str(today_payload.get("session") or today_ymd()))[:10]
    if not payload_has_today_column(today_payload, today=today_s):
        return hist
    if not hist or not kind_block(hist):
        return today_payload

    label = session_label(today_s)
    hist_kind = kind_block(hist)
    today_kind = kind_block(today_payload)
    hist_dates = date_columns(hist)
    rest_dates = [d for d in hist_dates if d != label]
    new_dates = [label, *rest_dates][: max(1, int(days))]

    metrics = list(today_payload.get("metrics") or hist.get("metrics") or [])
    hist_by = hist_kind.get("by_metric") or {}
    today_by = today_kind.get("by_metric") or {}
    if not metrics:
        metrics = list(dict.fromkeys([*today_by.keys(), *hist_by.keys()]))

    by_metric: dict[str, Any] = {}
    for metric in metrics:
        hblock = hist_by.get(metric) or {}
        tblock = today_by.get(metric) or {}
        old_top = _metric_cols(hblock, "top")
        old_bot = _metric_cols(hblock, "bottom")
        new_top = _metric_cols(tblock, "top")
        new_bot = _metric_cols(tblock, "bottom")
        today_top = list(new_top[0] if new_top else [])
        today_bot = list(new_bot[0] if new_bot else [])
        mapped_top = {
            d: old_top[i]
            for i, d in enumerate(hist_dates)
            if i < len(old_top) and d != label
        }
        mapped_bot = {
            d: old_bot[i]
            for i, d in enumerate(hist_dates)
            if i < len(old_bot) and d != label
        }
        tops = [today_top]
        bottoms = [today_bot]
        for d in new_dates[1:]:
            tops.append(list(mapped_top.get(d) or []))
            bottoms.append(list(mapped_bot.get(d) or []))
        by_metric[metric] = {"top": tops, "bottom": bottoms}

    members = dict(hist_kind.get("members") or {})
    members.update(today_kind.get("members") or {})

    out = dict(hist)
    out["updated_at"] = str(
        today_payload.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    out["session"] = today_s
    out["source"] = today_payload.get("source") or hist.get("source")
    out["top_n"] = today_payload.get("top_n") or hist.get("top_n")
    out["days"] = days
    out["metrics"] = metrics
    kind = dict(hist_kind)
    kind["dates"] = new_dates
    kind["by_metric"] = by_metric
    kind["members"] = members
    kind["board_count"] = today_kind.get("board_count") or hist_kind.get("board_count")
    if today_kind.get("fund_note"):
        kind["fund_note"] = today_kind.get("fund_note")
    kinds = dict(hist.get("kinds") or {})
    kinds[KIND] = kind
    out["kinds"] = kinds
    return out


def ensure_today_column(
    payload: dict[str, Any] | None,
    *,
    today: str | None = None,
    days: int = 20,
) -> dict[str, Any] | None:
    """没有今日列时插入空的今日列，避免把昨天当成最左列。"""
    today_s = today or today_ymd()
    if not payload:
        return None
    if payload_has_today_column(payload, today=today_s):
        out = dict(payload)
        out["session"] = today_s
        return out
    return splice_today_onto_hist(
        payload,
        _empty_today_shell(payload, today_s),
        days=days,
        today=today_s,
    )


def resolve_rotation_payload(
    *,
    fresh: dict[str, Any] | None,
    disk: dict[str, Any] | None,
    today: str | None = None,
    days: int = 20,
) -> dict[str, Any] | None:
    """合并新拉结果与磁盘历史。短结果不得覆盖长历史。"""
    today_s = today or today_ymd()
    fresh_n = len(date_columns(fresh))
    disk_n = len(date_columns(disk))
    if (
        fresh
        and payload_has_today_column(fresh, today=today_s)
        and fresh_n >= max(disk_n, 5)
    ):
        return fresh
    if fresh and payload_has_today_column(fresh, today=today_s):
        merged = splice_today_onto_hist(disk, fresh, days=days, today=today_s)
        return merged or fresh
    base = disk if disk_n >= fresh_n else fresh
    return ensure_today_column(base, today=today_s, days=days)
