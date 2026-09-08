# -*- coding: utf-8 -*-
"""从最新 portfolio_trades 重生成 TRADE_LEDGER.md。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
tr = pd.read_csv(DIR / "portfolio_trades.csv")
eq = pd.read_csv(DIR / "portfolio_equity.csv")


def pad(c) -> str:
    try:
        return str(int(float(c))).zfill(6)
    except Exception:
        return str(c)


tr["code"] = tr["code"].map(pad)

REASON = {
    "attack": "攻击波买",
    "open": "开盘突破买",
    "noted_gap_open": "止损已记·低开按开盘卖",
    "noted_open_dump": "止损已记·高开再下杀1%卖",
    "half_gain": "浮盈回落一半止盈",
    "hard_from_cost": "成本硬保护",
    "eod_reserve_slot": "尾盘空槽·强制卖最弱可卖仓",
}

open_buys: dict[str, list] = {}
rows_out: list[dict] = []
for _, r in tr.iterrows():
    code = r["code"]
    side = r["side"]
    note = ""
    match = ""
    pnl = ""
    if side == "buy":
        kind = str(r.get("kind") or "buy")
        note = REASON.get(kind, kind)
        if str(r.get("source")) == "queue_fill":
            note += "（排队补仓）"
        open_buys.setdefault(code, []).append(r)
    else:
        er = str(r.get("exit_reason") or "")
        note = REASON.get(er, er or "卖出")
        if pd.notna(r.get("pnl_pct")):
            pnl = f"{float(r['pnl_pct']) * 100:.2f}%"
        if open_buys.get(code):
            b = open_buys[code].pop(0)
            match = f"{b['ts']} @{b['px']}"
    rows_out.append(
        {
            "n": len(rows_out) + 1,
            "ts": str(r["ts"]),
            "side": side,
            "code": code,
            "name": str(r["name"]),
            "px": float(r["px"]),
            "shares": int(r["shares"]),
            "pnl": pnl,
            "match": match,
            "note": note,
            "slots": int(r["slots_after"]) if pd.notna(r.get("slots_after")) else "",
        }
    )

n_pool = 24  # 移出科森后
lines = [
    "# 交割单注释 · 定盘池（已剔科森）",
    "",
    "> 研究用途，非投资建议。规则：盘中可持3、日最多买2、尾盘空1（隔夜最多2）；当日止损/已记卖出禁再买。",
    "",
    "## 摘要",
    "",
    f"- 池：{n_pool} 只（已移出科森 603626）",
    "- 窗：2026-08-31～09-08（7 个交易日）",
    f"- 买 {(tr.side == 'buy').sum()} / 卖 {(tr.side == 'sell').sum()}；"
    f"期末权益 {eq.iloc[-1].equity:,.0f}（{eq.iloc[-1].ret_pct}%）",
    f"- 日末持仓均 ≤{int(eq['n_pos'].max())}；无同日卖后再买",
    "",
    "## 标签速查",
    "",
    "| 标签 | 含义 |",
    "|------|------|",
]
for k, v in REASON.items():
    lines.append(f"| `{k}` | {v} |")
lines += [
    "",
    "## 交割明细（时间序）",
    "",
    "| # | 时间 | 方向 | 代码 | 名称 | 价 | 股 | 槽后 | 盈亏% | 对应买入 | 逻辑 |",
    "|---|------|------|------|------|----|----|------|-------|----------|------|",
]
for x in rows_out:
    lines.append(
        f"| {x['n']} | {x['ts']} | {x['side']} | {x['code']} | {x['name']} | "
        f"{x['px']} | {x['shares']} | {x['slots']} | {x['pnl']} | {x['match']} | {x['note']} |"
    )
lines += [
    "",
    "## 日末持仓",
    "",
    "| 日期 | 权益 | 持仓数 | 持仓 | 累计% |",
    "|------|------|--------|------|-------|",
]
for _, e in eq.iterrows():
    lines.append(
        f"| {e['date']} | {e['equity']:,.0f} | {int(e['n_pos'])} | {e['codes']} | {e['ret_pct']} |"
    )
lines += ["", "研究用途，非投资建议。"]
(DIR / "TRADE_LEDGER.md").write_text("\n".join(lines), encoding="utf-8")
print("ok", len(rows_out), "ret", eq.iloc[-1].ret_pct)
