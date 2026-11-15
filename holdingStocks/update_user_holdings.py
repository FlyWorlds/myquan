"""根据用户指令更新当前持仓：
昨日（2026-11-12）买入：
1. 景旺电子 (603228): 成本价 70.91，20%仓位 (800股，成本额 56,728元)
2. 天通股份 (600330): 成本价 18.34，20%仓位 (3300股，成本额 60,522元)
3. 中电鑫龙 (002298): 成本价 8.126，20%仓位 (7300股，成本额 59,319.8元)
同时清空原先持仓（乐山电力 600644、湖南天雁 600698）。
"""
import copy
import sys
import uuid
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_DIR))

from database_holdings import DatabaseHoldingsStore


def main():
    store = DatabaseHoldingsStore({}, path=lambda: "holdings")
    data = store.load(force=True)

    session = "2026-11-12"
    buy_time = "2026-11-12 14:30:00"

    # 1. 清空原持仓中非目标股
    keep_codes = {"603228", "600330", "002298"}
    records = []

    pos_dict = data.setdefault("positions", {})
    for code, p in list(pos_dict.items()):
        if code not in keep_codes and p.get("qty", 0) > 0:
            old_qty = p["qty"]
            old_cost = p.get("cost", 0)
            p["qty"] = 0
            p["available"] = 0
            p["note"] = "手动调出持仓"
            # 记录调出记录
            records.append({
                "id": uuid.uuid4().hex,
                "time": "2026-11-12 14:29:00",
                "session": session,
                "side": "sell",
                "code": code,
                "name": p.get("name", code),
                "market": p.get("market", "上证"),
                "price": old_cost,
                "qty": old_qty,
                "after_qty": 0,
                "amount": round(old_qty * old_cost, 2),
                "cost": old_cost,
                "reason": "手动调出置换",
                "action_kind": "full",
            })

    # 2. 设置三只新持仓
    # 景旺电子 (603228)
    pos_dict["603228"] = {
        "name": "景旺电子",
        "market": "上证",
        "qty": 800,
        "available": 800,  # 昨日买入，今日T+1可卖
        "cost": 70.91,
        "today_cost": 70.91,
        "buy_time": buy_time,
        "tp_stage": 0,
        "last_tp_ts": None,
        "note": "手动买入·昨日买入20%仓位",
        "peak_high": 70.91,
        "peak_high_at": buy_time,
        "stop_noted": False,
        "stop_noted_px": None,
        "stop_noted_session": None,
        "buy_fees_remaining": 0.0,
        "quote_exit_session": session,
        "quote_session_peak": 70.91,
        "quote_cycle_low": 70.91,
        "overnight_peak": 70.91,
        "overnight_peak_session": session,
        "quote_exit_watermark": {
            "cycle": buy_time,
            "time": buy_time,
            "price": 70.91,
            "high": 70.91,
        },
    }
    records.append({
        "id": uuid.uuid4().hex,
        "time": buy_time,
        "session": session,
        "side": "buy",
        "code": "603228",
        "name": "景旺电子",
        "market": "上证",
        "price": 70.91,
        "qty": 800,
        "after_qty": 800,
        "amount": 56728.0,
        "cost": 70.91,
        "reason": "手动录入·昨日买入20%仓位",
    })

    # 天通股份 (600330)
    pos_dict["600330"] = {
        "name": "天通股份",
        "market": "上证",
        "qty": 3300,
        "available": 3300,
        "cost": 18.34,
        "today_cost": 18.34,
        "buy_time": buy_time,
        "tp_stage": 0,
        "last_tp_ts": None,
        "note": "手动买入·昨日买入",
        "peak_high": 18.34,
        "peak_high_at": buy_time,
        "stop_noted": False,
        "stop_noted_px": None,
        "stop_noted_session": None,
        "buy_fees_remaining": 0.0,
        "quote_exit_session": session,
        "quote_session_peak": 18.34,
        "quote_cycle_low": 18.34,
        "overnight_peak": 18.34,
        "overnight_peak_session": session,
        "quote_exit_watermark": {
            "cycle": buy_time,
            "time": buy_time,
            "price": 18.34,
            "high": 18.34,
        },
    }
    records.append({
        "id": uuid.uuid4().hex,
        "time": buy_time,
        "session": session,
        "side": "buy",
        "code": "600330",
        "name": "天通股份",
        "market": "上证",
        "price": 18.34,
        "qty": 3300,
        "after_qty": 3300,
        "amount": 60522.0,
        "cost": 18.34,
        "reason": "手动录入·昨日买入",
    })

    # 中电鑫龙 (002298)
    pos_dict["002298"] = {
        "name": "中电鑫龙",
        "market": "深证",
        "qty": 7300,
        "available": 7300,
        "cost": 8.126,
        "today_cost": 8.126,
        "buy_time": buy_time,
        "tp_stage": 0,
        "last_tp_ts": None,
        "note": "手动买入·昨日买入",
        "peak_high": 8.126,
        "peak_high_at": buy_time,
        "stop_noted": False,
        "stop_noted_px": None,
        "stop_noted_session": None,
        "buy_fees_remaining": 0.0,
        "quote_exit_session": session,
        "quote_session_peak": 8.126,
        "quote_cycle_low": 8.126,
        "overnight_peak": 8.126,
        "overnight_peak_session": session,
        "quote_exit_watermark": {
            "cycle": buy_time,
            "time": buy_time,
            "price": 8.126,
            "high": 8.126,
        },
    }
    records.append({
        "id": uuid.uuid4().hex,
        "time": buy_time,
        "session": session,
        "side": "buy",
        "code": "002298",
        "name": "中电鑫龙",
        "market": "深证",
        "price": 8.126,
        "qty": 7300,
        "after_qty": 7300,
        "amount": 59319.8,
        "cost": 8.126,
        "reason": "手动录入·昨日买入",
    })

    # 3. 资金更新
    total_cost = 56728.0 + 60522.0 + 59319.8
    account_total = 300000.0
    cash = round(account_total - total_cost, 2)
    data["account_total"] = account_total
    data["account_cash"] = cash

    # 4. 确认信息同步
    data["actual_holdings_confirmation"] = {
        "confirmed_at": "2026-11-13 08:35:00",
        "source": "user_confirmation",
        "cash_basis": "ledger_reversal_derived_not_broker_cash",
        "positions": {
            "603228": {"qty": 800, "cost": 70.91, "cost_confirmed_at": "2026-11-13 08:35:00"},
            "600330": {"qty": 3300, "cost": 18.34, "cost_confirmed_at": "2026-11-13 08:35:00"},
            "002298": {"qty": 7300, "cost": 8.126, "cost_confirmed_at": "2026-11-13 08:35:00"},
        },
    }
    data["actual_weight_confirmation"] = {
        "weights": {
            "603228": 18.9,
            "600330": 20.2,
            "002298": 19.8,
        },
        "total_pct": 58.9,
        "unallocated_pct": 41.1,
        "confirmed_at": "2026-11-13 08:35:00",
        "source": "user",
        "basis": "user_reported_not_computed",
    }

    # 5. 执行保存入库
    saved = store.save(data, records=records)
    print("Holdings updated successfully! New revision:", saved.get("revision"))
    active_positions = {
        c: {"name": p["name"], "qty": p["qty"], "available": p["available"], "cost": p["cost"]}
        for c, p in data["positions"].items()
        if p.get("qty", 0) > 0
    }
    print("Active positions now:", active_positions)
    print("Account Cash:", data["account_cash"], "Total:", data["account_total"])


if __name__ == "__main__":
    main()
