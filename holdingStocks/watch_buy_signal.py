"""买入信号 vs 三槽成交 — 单一口径。

设计：
  · 信号：过门 + 触买点 → 必须预警（哪怕槽满未成交）
  · 成交：空槽自动入三槽 →「已触买·已入槽」
  · 弱信号：价到买点但未过门 →「触买价·未过门」（不入槽、不可执行）

研究用途，非投资建议。
"""

from __future__ import annotations

from typing import Any

# --- 预警文案（真源）---------------------------------------------------------
ALERT_HIT_BUY = "已触买"
ALERT_FILLED = "已触买·已入槽"
ALERT_SLOT_FULL = "已触买·槽满"
ALERT_NOT_SLOTTED = "已触买·未入槽"
ALERT_PRICE_NO_GATE = "触买价·未过门"
ALERT_NEAR_BUY = "将买入"

_EMPTY_ALERTS = frozenset({"", "-", "空仓"})


def alert_text(row: dict[str, Any]) -> str:
    return str(row.get("预警") or row.get("alert") or "").strip()


def gate_ok(row: dict[str, Any]) -> bool | None:
    """过门是否通过。None=未知；兼容 numpy.bool_。"""
    v = row.get("过门OK")
    if v is None:
        return None
    return bool(v)


def price_touched_open_buy(row: dict[str, Any]) -> bool:
    """当日最高是否已触及开盘买点（不论过门）。"""
    try:
        hi = float(row.get("最高") or 0)
        buy = float(row.get("买点") or row.get("买入侧价") or 0)
    except (TypeError, ValueError):
        return False
    return buy > 0 and hi + 1e-12 >= buy


def is_filled_into_slot(row: dict[str, Any]) -> bool:
    """已自动/纸面入三槽（成交侧）。"""
    if int(row.get("持仓") or 0) > 0 and bool(row.get("槽位占用")):
        return True
    return alert_text(row).startswith(ALERT_FILLED)


def is_buy_hit(row: dict[str, Any]) -> bool:
    """有效买入信号（过门触买）：可入槽或应预警。不含「触买价·未过门」。"""
    if str(row.get("已触买") or "") == "是":
        return True
    alert = alert_text(row)
    if alert == ALERT_HIT_BUY or alert.startswith("已触买"):
        return True
    if str(row.get("持仓状态") or "") == "待买入" and str(
        row.get("因子触发") or ""
    ).startswith("已触发"):
        return True
    return False


def is_buy_signal_active(row: dict[str, Any]) -> bool:
    """展示/叠加用：含将买入、近买点、已触买族。"""
    alert = alert_text(row)
    pos = str(row.get("持仓状态") or "")
    return (
        is_buy_hit(row)
        or alert == ALERT_NEAR_BUY
        or "将买" in alert
        or pos == "待买入"
        or bool(row.get("近买点"))
    )


def is_weak_price_buy_alert(row: dict[str, Any]) -> bool:
    return ALERT_PRICE_NO_GATE in alert_text(row) or "触买价" in alert_text(row)


def is_buy_side_alert(row: dict[str, Any]) -> bool:
    """持仓 Tab / 推送：任何买入侧预警（强+弱）。"""
    if is_buy_hit(row) or is_buy_signal_active(row) or is_weak_price_buy_alert(row):
        return True
    alert = alert_text(row)
    return bool(row.get("槽位候选")) and (
        "买" in alert or bool(row.get("近买点"))
    )


def is_actionable_unfilled_buy(row: dict[str, Any]) -> bool:
    """空仓可执行买入信号（槽满仍可执行=信号在，自动单不会再买）。"""
    if int(row.get("持仓") or 0) > 0:
        return False
    if is_filled_into_slot(row):
        return False
    alert = alert_text(row)
    if alert.startswith(ALERT_FILLED):
        return False
    return is_buy_hit(row) and str(row.get("持仓状态") or "") == "待买入"


def _append_note(row: dict[str, Any], tip: str) -> None:
    note = str(row.get("挂单说明") or "")
    if tip and tip not in note:
        row["挂单说明"] = f"{tip}；{note}" if note else tip


def annotate_unfilled_buy_signals(
    rows: list[dict[str, Any]],
    slot_meta: dict[str, Any],
    *,
    is_stop_closed: Any | None = None,
    log: Any | None = None,
) -> tuple[int, int]:
    """触买=信号，入槽=成交。返回 (未入槽触买数, 触买价未过门数)。"""
    free_buy = int(slot_meta.get("freeBuy") or slot_meta.get("free") or 0)
    buys_left = int(slot_meta.get("buysLeft") or 0)
    slot_blocked = free_buy <= 0 or buys_left <= 0
    n_hit = 0
    n_gate = 0

    for r in rows:
        if r.get("error"):
            continue
        if int(r.get("持仓") or 0) > 0:
            continue
        alert = alert_text(r)
        if alert.startswith(ALERT_FILLED):
            continue
        pos = str(r.get("持仓状态") or "")
        if is_stop_closed is not None and is_stop_closed(pos):
            continue
        if pos == "当日禁买" or bool(r.get("当日禁买")):
            continue

        if is_buy_hit(r):
            tag = "槽满" if slot_blocked else "未入槽"
            r["已触买"] = "是"
            r["预警"] = ALERT_SLOT_FULL if slot_blocked else ALERT_NOT_SLOTTED
            r["持仓状态"] = "待买入"
            r["因子侧"] = "买入"
            r["近买点"] = True
            r["可执行"] = True
            r["槽位候选"] = True
            r["bg_class"] = "warn-buy"
            r["当日预警"] = True
            buy_px = r.get("买入侧价") or r.get("买点") or r.get("已触发因子价")
            tip = f"买入信号已触发·未入三槽（{tag}）"
            if buy_px is not None:
                try:
                    tip += f"@{float(buy_px):.{int(r.get('价位小数') or 2)}f}"
                except (TypeError, ValueError):
                    pass
            _append_note(r, tip)
            n_hit += 1
            continue

        # 弱信号：价到、未过门
        gok = gate_ok(r)
        if gok is not None and not gok and price_touched_open_buy(r):
            if alert in _EMPTY_ALERTS or "触买价" in alert:
                buy = float(r.get("买点") or r.get("买入侧价") or 0)
                gate = str(r.get("过门") or "未过门")
                r["预警"] = ALERT_PRICE_NO_GATE
                r["持仓状态"] = "空仓"
                r["近买点"] = False
                r["可执行"] = False
                r["槽位候选"] = False
                r["当日预警"] = True
                r["bg_class"] = "warn-buy"
                _append_note(r, f"最高已过买点@{buy:.2f}，但{gate}·不入槽")
                n_gate += 1

    if log is not None and (n_hit or n_gate):
        log(n_hit, n_gate)
    return n_hit, n_gate


def is_today_alert_row(row: dict[str, Any]) -> bool:
    """持仓 Tab「当日预警」行（空仓信号，不含实仓）。"""
    if row.get("error"):
        return False
    if int(row.get("持仓") or 0) > 0:
        return False
    if bool(row.get("已实现")):
        return False
    if bool(row.get("槽位候选")):
        return True
    if bool(row.get("当日预警")):
        return True
    alert = alert_text(row)
    pos = str(row.get("持仓状态") or "")
    if alert in (ALERT_HIT_BUY, ALERT_NEAR_BUY, "已触止损") or alert.startswith("已触"):
        return True
    if "将买入" in alert or "将卖出" in alert or "近买入" in alert:
        return True
    if is_weak_price_buy_alert(row):
        return True
    if pos in ("待买入", "待卖出"):
        return True
    if bool(row.get("近买点")) or bool(row.get("近止损")):
        return True
    if bool(row.get("可执行")):
        return True
    hit = str(row.get("因子触发") or "")
    return hit.startswith("已触发") or hit == "接近"


__all__ = [
    "ALERT_FILLED",
    "ALERT_HIT_BUY",
    "ALERT_NEAR_BUY",
    "ALERT_NOT_SLOTTED",
    "ALERT_PRICE_NO_GATE",
    "ALERT_SLOT_FULL",
    "alert_text",
    "annotate_unfilled_buy_signals",
    "gate_ok",
    "is_actionable_unfilled_buy",
    "is_buy_hit",
    "is_buy_side_alert",
    "is_buy_signal_active",
    "is_filled_into_slot",
    "is_today_alert_row",
    "is_weak_price_buy_alert",
    "price_touched_open_buy",
]
