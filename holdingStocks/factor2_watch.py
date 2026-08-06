"""盯盘 · 因子2（回撤阶梯补仓）状态。

与策略一 bindings / dd_topup 同源参数。
按账户总资产年内回撤给出追加/提出建议；不自动改现金，只维护纸面档位并预警。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from strategy.dd_topup import (
    DEFAULT_ADD_PCT,
    DEFAULT_LEVELS,
    add_target,
    desired_layers,
    drawdown,
    levels_label,
    resolve_topup_params,
)


def _binding_params() -> dict[str, Any]:
    try:
        from strategy import get_strategy_bindings

        for b in get_strategy_bindings("strategy1"):
            if b.factor_id == "factor2" and b.enabled:
                return dict(b.params)
    except Exception:
        pass
    return {"add_pct": DEFAULT_ADD_PCT, "levels": DEFAULT_LEVELS}


def load_factor2_state(holdings: dict[str, Any]) -> dict[str, Any]:
    raw = holdings.get("factor2")
    if not isinstance(raw, dict):
        return {
            "year": None,
            "peak": None,
            "stack": [],
            "max_reached": 0,
            "last_action": "hold",
            "last_label": "",
            "last_session": "",
            "suggest_amount": 0.0,
            "dd_pct": 0.0,
            "layers": 0,
            "equity": None,
        }
    stack = raw.get("stack") or []
    if not isinstance(stack, list):
        stack = []
    return {
        "year": raw.get("year"),
        "peak": raw.get("peak"),
        "stack": [float(x) for x in stack],
        "max_reached": int(raw.get("max_reached") or 0),
        "last_action": str(raw.get("last_action") or "hold"),
        "last_label": str(raw.get("last_label") or ""),
        "last_session": str(raw.get("last_session") or ""),
        "suggest_amount": float(raw.get("suggest_amount") or 0.0),
        "dd_pct": float(raw.get("dd_pct") or 0.0),
        "layers": int(raw.get("layers") or len(stack)),
        "equity": raw.get("equity"),
    }


def sync_factor2(
    holdings: dict[str, Any],
    *,
    equity: float | None,
    session: str,
) -> dict[str, Any]:
    """推进因子2纸面状态并写回 holdings['factor2']。"""
    params = _binding_params()
    pct, levels = resolve_topup_params(
        add_pct=params.get("add_pct"),
        levels=params.get("levels"),
    )
    st = load_factor2_state(holdings)
    prev_action = st["last_action"]
    prev_label = st["last_label"]

    if equity is None or float(equity) <= 0:
        return {
            **st,
            "enabled": True,
            "add_pct": pct,
            "levels": levels,
            "levels_label": levels_label(levels),
            "equity": None,
            "action": "hold",
            "label": "总资产未登记，因子2待命",
            "suggest_amount": 0.0,
            "alert_changed": False,
            "pushable": False,
        }

    eq = float(equity)
    year = int(str(session)[:4]) if session and str(session)[:4].isdigit() else None
    stack = list(st["stack"])
    max_reached = int(st["max_reached"] or 0)
    peak = st["peak"]

    if year is not None and st.get("year") != year:
        peak = eq
        max_reached = max(max_reached, len(stack))
    if peak is None or float(peak) <= 0:
        peak = eq
    peak = float(peak)
    if eq > peak + 1e-9:
        peak = eq

    dd = drawdown(eq, peak)
    want_up = add_target(dd, levels)
    if want_up > max_reached:
        max_reached = want_up
    want = desired_layers(dd, max_reached, levels)

    events: list[str] = []
    moved = 0.0
    action = "hold"

    while len(stack) < want_up:
        amt = pct * eq
        stack.append(amt)
        moved += amt
        lv = levels[min(len(stack), len(levels)) - 1]
        events.append(f"回撤≥{lv*100:.0f}%建议追加当前×{pct*100:.0f}%")
        action = "inject"

    while len(stack) > want:
        if want == 0 and dd <= 1e-12 and len(stack) > 1:
            moved = float(sum(stack))
            stack.clear()
            events.append("回撤归0建议全部结清追加")
            action = "withdraw"
            max_reached = 0
            peak = eq
            break
        amt = float(stack.pop())
        moved += amt
        action = "withdraw"
        if dd <= 1e-12:
            events.append("回撤归0建议结清一档")
        elif len(levels) >= 2 and dd <= float(levels[-2]) + 1e-12:
            events.append(f"回撤≤{levels[-2]*100:.0f}%建议减1档")
        else:
            events.append(f"回撤≤{levels[0]*100:.0f}%建议减1档")
        if not stack:
            max_reached = 0
            if dd <= 1e-12:
                peak = eq

    if events:
        label = "；".join(events)
        suggest = float(moved)
    else:
        label = f"维持{len(stack)}档"
        suggest = 0.0
        action = "hold"

    alert_changed = (action != prev_action) or (
        action != "hold" and label != prev_label
    )
    pushable = action in ("inject", "withdraw") and alert_changed

    saved = {
        "year": year,
        "peak": round(peak, 2),
        "stack": [round(float(x), 2) for x in stack],
        "max_reached": int(max_reached),
        "last_action": action,
        "last_label": label,
        "last_session": str(session),
        "suggest_amount": round(suggest, 2),
        "dd_pct": round(dd * 100.0, 2),
        "layers": len(stack),
        "add_pct": pct,
        "levels": list(levels),
        "equity": round(eq, 2),
    }
    holdings["factor2"] = saved

    return {
        **saved,
        "enabled": True,
        "levels_label": levels_label(levels),
        "action": action,
        "label": label,
        "alert_changed": alert_changed,
        "pushable": pushable,
        "levels": levels,
    }


def format_factor2_summary(status: dict[str, Any] | None) -> str:
    if not status or status.get("equity") is None:
        return "因子2: 总资产未登记（先登记现金，按策略一总资产回撤同步）"
    act = status.get("action") or "hold"
    tag = {"inject": "建议追加", "withdraw": "建议提出", "hold": "维持"}.get(
        str(act), str(act)
    )
    return (
        f"因子2[{tag}] 回撤{float(status.get('dd_pct') or 0):.1f}% "
        f"档{status.get('layers', 0)} "
        f"高点{status.get('peak')} "
        f"建议{float(status.get('suggest_amount') or 0):,.0f}元 "
        f"· {status.get('label') or ''} "
        f"· {status.get('levels_label')}+{float(status.get('add_pct') or 0)*100:.0f}%"
    )


def format_factor2_push(status: dict[str, Any]) -> str:
    tag = "【因子2追加】" if status.get("action") == "inject" else "【因子2提出】"
    return "\n".join(
        [
            tag,
            f"策略一 · {status.get('label') or '-'}",
            f"总资产 {status.get('equity')} · 年内高点 {status.get('peak')}",
            f"回撤 {status.get('dd_pct')}% · 在途档位 {status.get('layers')}",
            f"建议金额 {float(status.get('suggest_amount') or 0):,.2f}",
            f"档位 {status.get('levels_label')} / "
            f"每档+{float(status.get('add_pct') or 0)*100:.0f}%",
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
    )
