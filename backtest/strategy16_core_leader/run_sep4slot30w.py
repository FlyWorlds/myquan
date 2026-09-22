# -*- coding: utf-8 -*-
"""策略16 · 9月窗口 · 30万 · 四槽组合回测（一次性）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from backtest.strategy1_pool_1m import run as r  # noqa: E402
from holdingStocks.watch_config import DEFAULT_ACCOUNT_TOTAL  # noqa: E402
from strategy.pullback_wave_stop import DEFAULT_ENTRY_PCT, DEFAULT_PULLBACK_PCT  # noqa: E402

OUT = _ROOT / "backtest" / "strategy16_core_leader"
TAG = "_sep4slot30w"
DAYS = 20  # 覆盖 9 月可用 1m（缓存优先，不强制 refresh，避免 ak 冲掉更长窗）
MAX_SLOTS = 4
INITIAL = float(DEFAULT_ACCOUNT_TOTAL)  # 300_000
SLOT_W = 0.25  # 四槽等权
MAX_BUYS = 4  # 可开满四槽


def main() -> None:
    pool_rows = r._load_pool(r.POOL_STRATEGY16)
    entry = float(DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    stock_payload: list[dict] = []
    print(
        f"策略16 {len(pool_rows)} 只 · days={DAYS} · cash={INITIAL:,.0f} · "
        f"slots={MAX_SLOTS} · weight={SLOT_W} · max_buys/day={MAX_BUYS}",
        flush=True,
    )
    for w in pool_rows:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or r._sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        print(f"· {code} {name} ±{ep*100:.1f}% …", flush=True)
        daily = r._daily(sina)
        # refresh=False：保留本地更长 1m；ak 仅在缺缓存时补
        mins = r._minutes(sina, refresh=False, days=int(DAYS), source="ak")
        stock_payload.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": pb,
                "daily": daily,
                "minutes": mins,
            }
        )

    print("\n组合四槽回放…", flush=True)
    port = r.simulate_portfolio_3slots(
        stock_payload,
        days=int(DAYS),
        max_slots=MAX_SLOTS,
        initial_cash=INITIAL,
        slot_weight=SLOT_W,
        max_buys_per_day=MAX_BUYS,
        buy_mode=r.BUY_MODE_DEFAULT,
    )
    ps = port.get("summary") or {}
    cal = ps.get("calendar") or []
    print(
        f"\n日历 ({len(cal)}): {cal[0] if cal else '—'} → {cal[-1] if cal else '—'}",
        flush=True,
    )
    print(
        f"期末权益 {ps.get('final_equity')}  收益 {ps.get('return_pct')}%  "
        f"最大回撤 {ps.get('max_dd_pct')}%  "
        f"买{ps.get('n_buys')}/卖{ps.get('n_sells')}  期末持仓{ps.get('n_open')}",
        flush=True,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    trades = list(port.get("trades") or [])
    equity = list(port.get("equity") or [])
    pd.DataFrame(trades).to_csv(OUT / f"portfolio_trades{TAG}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(equity).to_csv(OUT / f"portfolio_equity{TAG}.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# 策略十六 · 9月窗口 · 30万 · 四槽 1m 组合回测",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 参数",
        "",
        f"- 初始资金：**{INITIAL:,.0f}**",
        f"- 物理槽：**{MAX_SLOTS}**；单槽权重 **{SLOT_W*100:.0f}%**；当日最多买 **{MAX_BUYS}**",
        f"- 窗长：近 {DAYS} 交易日可用 1m；实际日历 **{len(cal)}** 日"
        + (f"（{cal[0]} → {cal[-1]}）" if cal else ""),
        "- 选股：因子27 核心龙头 ∪ 公共自选；买卖=因子26（开盘阈值买）",
        "- 数据：本地 1m 缓存 + akshare 刷新；未用 Pandadata 长窗",
        "",
        "## 四槽组合摘要",
        "",
        f"- 期末权益：{ps.get('final_equity')}（**{ps.get('return_pct')}%**）",
        f"- 最大回撤：{ps.get('max_dd_pct')}%",
        f"- 买入 {ps.get('n_buys')} / 卖出 {ps.get('n_sells')} / 已平仓 {ps.get('n_closed')}（均收益 {ps.get('avg_closed_pnl_pct')}%）",
        f"- 期末持仓：{ps.get('n_open')} 只",
        f"- 槽满跳过：{ps.get('n_skipped_or_queued')}",
        "",
        "## 日末权益",
        "",
        "| 日期 | 权益 | 现金 | 持仓数 | 持仓 | 累计% |",
        "|------|------|------|--------|------|-------|",
    ]
    for e in equity:
        lines.append(
            f"| {e.get('date')} | {e.get('equity')} | {e.get('cash')} | "
            f"{e.get('n_pos')} | {e.get('codes') or '—'} | {e.get('ret_pct')} |"
        )
    if port.get("open_positions"):
        lines.extend(
            [
                "",
                "## 期末未平仓",
                "",
                "| 代码 | 名称 | 买日 | 买价 | 现价 | 浮盈% |",
                "|------|------|------|------|------|-------|",
            ]
        )
        for p in port["open_positions"]:
            pp = p.get("pnl_pct")
            lines.append(
                f"| {p['code']} | {p['name']} | {p['buy_day']} | {p['buy_px']} | "
                f"{p['last_px']} | {'' if pp is None else round(pp * 100, 2)} |"
            )
    lines.extend(["", "研究用途，非投资建议。", ""])
    md = OUT / f"REPORT{TAG}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "tag": TAG,
        "initial_cash": INITIAL,
        "max_slots": MAX_SLOTS,
        "slot_weight": SLOT_W,
        "max_buys_per_day": MAX_BUYS,
        "days_requested": DAYS,
        "calendar": cal,
        "portfolio": ps,
    }
    (OUT / f"portfolio_summary{TAG}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"写入 {md}", flush=True)


if __name__ == "__main__":
    main()
