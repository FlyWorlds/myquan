"""对比策略1 三槽 1m：峰值回落阈值 vs 浮盈回落一半止盈。

用法：
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/compare_exits.py
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/compare_exits.py --days 7

研究用途，非投资建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import (  # noqa: E402
    DEFAULT_ACCOUNT_TOTAL,
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    strategy_watchlist,
)
from strategy.pullback_wave_stop import DEFAULT_ENTRY_PCT, DEFAULT_PULLBACK_PCT  # noqa: E402

from backtest.strategy1_pool_1m.run import (  # noqa: E402
    _daily,
    _em,
    _minutes,
    _sina,
    simulate_portfolio_3slots,
)

OUT = Path(__file__).resolve().parent


MODES = (
    (
        "peak_pct",
        "峰值回落阈值",
        "卖价=floor(当日分时最高×(1−阈值))，默认 2.5%（因子26）",
    ),
    (
        "half_gain",
        "浮盈回落一半",
        "卖价=floor(成本+0.5×(持仓最高−成本))；未浮盈时用成本×(1−阈值)保护",
    ),
)


def _load_stocks(*, refresh: bool) -> list[dict]:
    entry = float(DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    stocks: list[dict] = []
    for w in strategy_watchlist():
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        sp = float(w.get("stop_pct") or w.get("pct") or pb)
        print(f"· {code} {name} …", flush=True)
        stocks.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": sp,
                "daily": _daily(sina),
                "minutes": _minutes(sina, refresh=refresh),
            }
        )
    return stocks


def _summarize(port: dict, label: str, desc: str) -> dict:
    s = dict(port.get("summary") or {})
    trades = list(port.get("trades") or [])
    sells = [t for t in trades if t.get("side") == "sell"]
    wins = [t for t in sells if (t.get("pnl_pct") or 0) > 0]
    losses = [t for t in sells if (t.get("pnl_pct") or 0) <= 0]
    reasons: dict[str, int] = {}
    for t in sells:
        r = str(t.get("exit_reason") or "peak_pct")
        reasons[r] = reasons.get(r, 0) + 1
    eq = list(port.get("equity") or [])
    max_dd = 0.0
    peak = None
    for e in eq:
        v = float(e.get("equity") or 0)
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            max_dd = min(max_dd, v / peak - 1.0)
    return {
        "mode": s.get("exit_mode"),
        "label": label,
        "desc": desc,
        "return_pct": s.get("return_pct"),
        "final_equity": s.get("final_equity"),
        "n_buys": s.get("n_buys"),
        "n_sells": s.get("n_sells"),
        "n_closed": s.get("n_closed"),
        "avg_closed_pnl_pct": s.get("avg_closed_pnl_pct"),
        "win_rate_pct": round(len(wins) / len(sells) * 100.0, 1) if sells else None,
        "avg_win_pct": round(sum(float(t["pnl_pct"]) for t in wins) / len(wins) * 100, 2)
        if wins
        else None,
        "avg_loss_pct": round(
            sum(float(t["pnl_pct"]) for t in losses) / len(losses) * 100, 2
        )
        if losses
        else None,
        "max_dd_pct": round(max_dd * 100.0, 2),
        "n_open": s.get("n_open"),
        "exit_reasons": reasons,
        "equity": eq,
        "trades": trades,
        "open_positions": port.get("open_positions") or [],
    }


def run(*, days: int = 7, refresh: bool = False, max_slots: int = MAX_PORTFOLIO_SLOTS) -> dict:
    print(f"加载定盘池 1m（refresh={refresh}）…")
    stocks = _load_stocks(refresh=refresh)
    rows = []
    payloads = {}
    for mode, label, desc in MODES:
        print(f"\n=== {label} ({mode}) ===", flush=True)
        port = simulate_portfolio_3slots(
            stocks,
            days=int(days),
            max_slots=int(max_slots),
            initial_cash=float(DEFAULT_ACCOUNT_TOTAL),
            slot_weight=float(SLOT_WEIGHT),
            exit_mode=mode,
        )
        row = _summarize(port, label, desc)
        rows.append(row)
        payloads[mode] = row
        print(
            f"  收益 {row['return_pct']}%  胜率 {row['win_rate_pct']}%  "
            f"均盈 {row['avg_win_pct']}% / 均亏 {row['avg_loss_pct']}%  "
            f"回撤 {row['max_dd_pct']}%  卖出原因 {row['exit_reasons']}"
        )

    # 结论
    a, b = payloads["peak_pct"], payloads["half_gain"]
    better = None
    if a["return_pct"] is not None and b["return_pct"] is not None:
        if float(b["return_pct"]) > float(a["return_pct"]) + 0.05:
            better = "half_gain"
        elif float(a["return_pct"]) > float(b["return_pct"]) + 0.05:
            better = "peak_pct"
        else:
            better = "tie"

    out = {
        "window_days": int(days),
        "max_slots": int(max_slots),
        "better_by_return": better,
        "modes": [
            {k: v for k, v in r.items() if k not in ("equity", "trades", "open_positions")}
            for r in rows
        ],
        "disclaimer": "研究用途，非投资建议；近7日样本极短，结论不可外推。",
    }

    out_json = OUT / "exit_compare.json"
    out_md = OUT / "EXIT_COMPARE.md"
    out_json.write_text(
        json.dumps(
            {
                **out,
                "details": {
                    m: {
                        "summary": {k: v for k, v in payloads[m].items() if k != "trades"},
                        "trades": payloads[m]["trades"],
                    }
                    for m in payloads
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    lines = [
        "# 策略1 三槽 · 出场对比：峰值回落阈值 vs 浮盈回落一半",
        "",
        "> 研究用途，非投资建议。近 7 日 1m，样本极短。",
        "",
        "## 规则对照",
        "",
        "| 模式 | 含义 |",
        "|------|------|",
    ]
    for mode, label, desc in MODES:
        lines.append(f"| `{mode}` · {label} | {desc} |")
    lines.extend(
        [
            "",
            f"- 共同：定盘池、先触发先买、最多 {max_slots} 槽、T+1、每槽约 {SLOT_WEIGHT*100:.0f}%",
            f"- 窗长：近 {days} 个有 1m 的交易日",
            "",
            "## 结果",
            "",
            "| 模式 | 累计% | 胜率% | 均盈% | 均亏% | 回撤% | 买/卖 | 期末持仓 | 卖出原因 |",
            "|------|-------|-------|-------|-------|-------|-------|----------|----------|",
        ]
    )
    for r in rows:
        lines.append(
            f"| {r['label']} | {r['return_pct']} | {r['win_rate_pct']} | "
            f"{r['avg_win_pct']} | {r['avg_loss_pct']} | {r['max_dd_pct']} | "
            f"{r['n_buys']}/{r['n_sells']} | {r['n_open']} | {r['exit_reasons']} |"
        )

    lines.extend(["", "## 日末权益对照", ""])
    # merge equity
    eq_map: dict[str, dict[str, float]] = {}
    for mode, _, _ in MODES:
        for e in payloads[mode].get("equity") or []:
            d = str(e.get("date"))
            eq_map.setdefault(d, {})[mode] = float(e.get("ret_pct") or 0)
    lines += [
        "| 日期 | 峰值回落累计% | 浮盈一半累计% | 差额(一半−峰值) |",
        "|------|---------------|---------------|-----------------|",
    ]
    for d in sorted(eq_map):
        p = eq_map[d].get("peak_pct")
        h = eq_map[d].get("half_gain")
        diff = None if p is None or h is None else round(h - p, 2)
        lines.append(f"| {d} | {p} | {h} | {diff} |")

    verdict = {
        "peak_pct": "本窗 **峰值回落阈值** 更好（累计收益更高）。",
        "half_gain": "本窗 **浮盈回落一半** 更好（累计收益更高）。",
        "tie": "本窗两者累计收益接近。",
        None: "无法判定。",
    }[better]

    lines.extend(
        [
            "",
            "## 结论（仅本窗）",
            "",
            verdict,
            "",
            "- 峰值回落阈值：跟**价格峰值**按固定百分比收；小行情也会较早兑现/止损，趋势段容易被洗。",
            "- 浮盈回落一半：跟**浮盈幅度**成比例放宽；大赚时给回吐空间更大，小浮盈时止盈更紧；未浮盈仍靠成本回撤保护。",
            "- 历史长窗（策略1 优化报告）倾向「让盈利单跑、勿过早全清止盈」；本 7 日窗只能当盘感对照，不能改默认。",
            "",
            f"产物：`{out_json.name}`",
            "",
            out["disclaimer"],
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n写入 {out_md}")
    print(f"判定：{better} — {verdict}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="策略1 出场对比")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max-slots", type=int, default=MAX_PORTFOLIO_SLOTS)
    args = ap.parse_args()
    run(days=int(args.days), refresh=bool(args.refresh), max_slots=int(args.max_slots))


if __name__ == "__main__":
    main()
