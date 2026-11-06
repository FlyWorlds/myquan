"""Resend missed fills and reset today's sent signals cache after fixing context token.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "holdingStocks"))

from wechat_notify import (
    _load_state,
    _save_state,
    format_buy_fill_message,
    send_text,
)

# 1. 补发海量数据买入通知
msg_603138 = format_buy_fill_message(
    code="603138",
    name="海量数据",
    price=15.17,
    qty=4000,
    strategy_id="strategy1",
    target_px=15.17,
    last_px=14.89,
)
print("正在补发海量数据买入通知...")
ok1, detail1 = send_text(msg_603138)
print(f"海量数据推送结果: ok={ok1}, detail={detail1}")

# 2. 补发视源股份真实持仓买入确认通知
msg_002841 = (
    "【实盘买入确认】\n"
    "等级：P1 重要\n"
    "股票：002841 视源股份\n"
    "成交价：42.10\n"
    "成交数量：1400 股\n"
    "成交金额：58940.00 元\n"
    "保护止损：41.04 元\n"
    "状态：已同步权威纸面账本与置顶持仓"
)
print("正在补发视源股份实盘买入确认通知...")
ok2, detail2 = send_text(msg_002841)
print(f"视源股份推送结果: ok={ok2}, detail={detail2}")

# 3. 清理今天 2026-11-06 因之前 token 缺失而假成功的 signal 去重键
state = _load_state()
sent = state.get("sent", {})
keys_to_remove = [k for k in sent if "2026-11-06" in k]
for k in keys_to_remove:
    sent.pop(k, None)

first_alerts = state.get("first_alerts", {})
first_alerts.pop("2026-11-06", None)

state["sent"] = sent
state["first_alerts"] = first_alerts
_save_state(state)
print(f"已清理今日假成功缓存键 {len(keys_to_remove)} 个，策略触买信号已恢复同步推送！")
