"""盯盘 · 因子2（回撤加减仓预警）。

与 strategy.dd_alert / strategy1 bindings 同源。
按账户总资产年内回撤触发加仓/减仓预警；不自动改现金。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from strategy.dd_alert import (
    default_thresholds,
    derive_thresholds,
    drawdown,
    evaluate_alert,
)


def _thresholds():
    try:
        from strategy import get_strategy_bindings

        for b in get_strategy_bindings("strategy1"):
            if b.factor_id == "factor2" and b.enabled:
                return derive_thresholds(
                    hist_max_dd=b.params.get("hist_max_dd"),
                    avg_yearly_max_dd=b.params.get("avg_yearly_max_dd"),
                )
    except Exception:
        pass
    return default_thresholds()


def load_factor2_state(holdings: dict[str, Any]) -> dict[str, Any]:
    raw = holdings.get("factor2")
    if not isinstance(raw, dict):
        return {
            "year": None,
            "peak": None,
            "in_add_zone": False,
            "last_action": "hold",
            "last_label": "",
            "last_session": "",
            "dd_pct": 0.0,
            "equity": None,
        }
    return {
        "year": raw.get("year"),
        "peak": raw.get("peak"),
        "in_add_zone": bool(raw.get("in_add_zone")),
        "last_action": str(raw.get("last_action") or "hold"),
        "last_label": str(raw.get("last_label") or ""),
        "last_session": str(raw.get("last_session") or ""),
        "dd_pct": float(raw.get("dd_pct") or 0.0),
        "equity": raw.get("equity"),
    }


def sync_factor2(
    holdings: dict[str, Any],
    *,
    equity: float | None,
    session: str,
) -> dict[str, Any]:
    """推进因子2预警状态并写回 holdings['factor2']。"""
    th = _thresholds()
    st = load_factor2_state(holdings)
    prev_action = st["last_action"]
    prev_label = st["last_label"]

    if equity is None or float(equity) <= 0:
        th_dict = th.as_dict()
        holdings["factor2"] = {
            "year": st.get("year"),
            "peak": st.get("peak"),
            "in_add_zone": bool(st.get("in_add_zone")),
            "last_action": "hold",
            "last_label": "总资产未登记，因子2待命",
            "last_session": str(session),
            "suggest_amount": 0.0,
            "dd_pct": float(st.get("dd_pct") or 0.0),
            "equity": None,
            "thresholds": th_dict,
            "layers": 0,
        }
        return {
            **st,
            "enabled": True,
            "action": "hold",
            "label": "总资产未登记，因子2待命",
            "suggest_amount": 0.0,
            "alert_changed": False,
            "pushable": False,
            "thresholds": th_dict,
            "levels_label": th.label(),
            "dd_pct": float(st.get("dd_pct") or 0.0),
            "equity": None,
        }

    eq = float(equity)
    year = int(str(session)[:4]) if session and str(session)[:4].isdigit() else None
    peak = st.get("peak")
    in_zone = bool(st.get("in_add_zone"))

    if year is not None and st.get("year") != year:
        peak = eq
        in_zone = False
    if peak is None or float(peak) <= 0:
        peak = eq
    peak = float(peak)
    if eq > peak + 1e-9:
        peak = eq

    sig = evaluate_alert(
        equity=eq, peak=peak, thresholds=th, in_add_zone=in_zone
    )
    action = str(sig["action"])
    label = str(sig["alert"])
    in_zone = bool(sig["in_add_zone"])
    # 回到很浅的回撤则清除加仓区标记
    if float(sig["dd"]) < th.reduce_alert_dd * 0.5:
        in_zone = False

    alert_changed = (action != prev_action) or (
        action != "hold" and label != prev_label
    )
    pushable = action in ("add_alert", "reduce_alert", "near_max") and alert_changed

    saved = {
        "year": year,
        "peak": round(peak, 2),
        "in_add_zone": in_zone,
        "last_action": action,
        "last_label": label,
        "last_session": str(session),
        "suggest_amount": 0.0,
        "dd_pct": round(float(sig["dd_pct"]), 2),
        "equity": round(eq, 2),
        "thresholds": th.as_dict(),
        # 兼容旧字段名，便于 HTML/推送
        "因子2动作": action,
        "layers": 0,
    }
    holdings["factor2"] = saved

    return {
        **saved,
        "enabled": True,
        "action": action,
        "label": label,
        "levels_label": th.label(),
        "alert_changed": alert_changed,
        "pushable": pushable,
        "因子2": label,
        "因子2动作": action,
        "因子2回撤%": saved["dd_pct"],
        "因子2建议额": 0.0,
        "因子2档位": 0,
    }


def _status_thresholds(status: dict[str, Any] | None) -> dict[str, float]:
    raw = (status or {}).get("thresholds")
    if isinstance(raw, dict) and raw:
        return {k: float(v) for k, v in raw.items() if v is not None}
    return _thresholds().as_dict()


def format_factor2_summary(status: dict[str, Any] | None) -> str:
    """盯盘摘要：策略一历史最大回撤 / 年最大回撤均值 / 当前回撤。"""
    th = _status_thresholds(status)
    hist = float(th.get("hist_max_dd") or 0) * 100.0
    yearly = float(th.get("avg_yearly_max_dd") or 0) * 100.0
    add_line = float(th.get("add_alert_dd") or 0) * 100.0
    reduce_line = float(th.get("reduce_alert_dd") or 0) * 100.0
    dd_line = (
        f"策略一 · 历史最大回撤 {hist:.1f}% · "
        f"年最大回撤均值 {yearly:.1f}% · "
    )

    if not status or status.get("equity") is None:
        return (
            f"{dd_line}当前回撤 — "
            f"（总资产未登记；加仓≥{add_line:.0f}% / 减仓≤{reduce_line:.0f}%）"
        )

    act = status.get("action") or status.get("last_action") or "hold"
    tag = {
        "add_alert": "加仓预警",
        "reduce_alert": "减仓预警",
        "near_max": "接近历史最大回撤",
        "hold": "观望",
        "inject": "加仓预警",
        "withdraw": "减仓预警",
    }.get(str(act), str(act))
    cur = float(status.get("dd_pct") or 0)
    return (
        f"{dd_line}当前回撤 {cur:.1f}% "
        f"[{tag}] · 加仓≥{add_line:.0f}% / 减仓≤{reduce_line:.0f}%"
    )


def format_factor2_push(status: dict[str, Any]) -> str:
    act = status.get("action")
    if act in ("add_alert", "inject"):
        tag = "【因子2加仓预警】"
    elif act in ("reduce_alert", "withdraw"):
        tag = "【因子2减仓预警】"
    elif act == "near_max":
        tag = "【因子2接近历史最大回撤】"
    else:
        tag = "【因子2】"
    th = _status_thresholds(status if isinstance(status, dict) else None)
    return "\n".join(
        [
            tag,
            f"{status.get('label') or '-'}",
            f"总资产 {status.get('equity')} · 年内高点 {status.get('peak')}",
            (
                f"历史最大回撤 {float(th.get('hist_max_dd') or 0)*100:.1f}% · "
                f"年最大回撤均值 {float(th.get('avg_yearly_max_dd') or 0)*100:.1f}% · "
                f"当前回撤 {float(status.get('dd_pct') or 0):.1f}%"
            ),
            f"阈值 加仓≥{float(th.get('add_alert_dd') or 0)*100:.0f}% / "
            f"减仓≤{float(th.get('reduce_alert_dd') or 0)*100:.0f}%",
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
    )
