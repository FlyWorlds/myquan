"""策略十六：生产禁当日再买 vs 卖出后仍可走开盘阈值再买。

A) 生产：当日全清后禁再买该票
B) 研究：当日全清后若再触开盘×(1+entry) 允许同日再买（含低开硬保护后反弹再买）

用法：
  PYTHONPATH=. python backtest/strategy16_core_leader/compare_open_rebuy.py --days 7
  PYTHONPATH=. python backtest/strategy16_core_leader/compare_open_rebuy.py --days 7 --all-pool

研究用途，非投资建议。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backtest.strategy1_pool_1m.run import (  # noqa: E402
    BUY_MODE_DEFAULT,
    _daily,
    _load_pool,
    _minutes,
    _sina,
    simulate_portfolio_3slots,
)
from holdingStocks.watch_config import (  # noqa: E402
    DEFAULT_ACCOUNT_TOTAL,
    MAX_BUYS_PER_DAY,
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    load_strategy16_thr_map,
)
from strategy.pullback_wave_stop import DEFAULT_ENTRY_PCT, DEFAULT_PULLBACK_PCT  # noqa: E402

OUT = Path(__file__).resolve().parent


def _summary(port: dict[str, Any], *, label: str) -> dict[str, Any]:
    ps = port.get("summary") or {}
    trades = list(port.get("trades") or [])
    n_rebuy = sum(
        1
        for t in trades
        if t.get("side") == "buy" and t.get("source") == "open_rebuy_after_sell"
    )
    n_buy = sum(1 for t in trades if t.get("side") == "buy")
    n_sell = sum(1 for t in trades if t.get("side") == "sell")
    return {
        "label": label,
        "return_pct": ps.get("return_pct"),
        "max_dd_pct": ps.get("max_dd_pct"),
        "final_equity": ps.get("final_equity"),
        "n_buy": n_buy,
        "n_sell": n_sell,
        "n_open_rebuy": n_rebuy,
        "n_closed": ps.get("n_closed"),
        "avg_closed_pnl_pct": ps.get("avg_closed_pnl_pct"),
        "n_open": ps.get("n_open"),
        "calendar": ps.get("calendar"),
    }


def main(days: int = 7, refresh: bool = False, all_pool: bool = False) -> int:
    entry = float(DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    if not load_strategy16_thr_map():
        import importlib.util

        fit_py = OUT / "fit_thr.py"
        spec = importlib.util.spec_from_file_location("s16_fit_thr", fit_py)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.fit_strategy16_thresholds()

    pool_rows = _load_pool("strategy16")
    n = len(pool_rows)
    stock_payload: list[dict[str, Any]] = []
    mode_s = f"全池等权({n}槽)" if all_pool else "三槽"
    print(f"策略十六 · 开盘阈值同日再买对照 · {n} 只 · {mode_s} · 近 {days} 日 1m")
    for w in pool_rows:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        print(f"· {code} {name} ±{ep*100:.1f}% …", flush=True)
        stock_payload.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": pb,
                "daily": _daily(sina),
                "minutes": _minutes(sina, refresh=refresh, days=int(days), source="auto"),
            }
        )

    if all_pool:
        common = dict(
            days=int(days),
            max_slots=int(n),
            max_buys_per_day=int(n),
            initial_cash=float(DEFAULT_ACCOUNT_TOTAL),
            slot_weight=1.0 / float(n),
            buy_mode=BUY_MODE_DEFAULT,
            allow_f22_rebuy=False,
        )
        stem = "_ALL"
        scope = f"全池 {n} 只等权进场（槽={n}，日最多买={n}，每槽 {100.0/n:.2f}%）"
    else:
        common = dict(
            days=int(days),
            max_slots=int(MAX_PORTFOLIO_SLOTS),
            initial_cash=float(DEFAULT_ACCOUNT_TOTAL),
            slot_weight=float(SLOT_WEIGHT),
            buy_mode=BUY_MODE_DEFAULT,
            allow_f22_rebuy=False,
        )
        stem = ""
        scope = f"三槽；日最多买 {int(MAX_BUYS_PER_DAY)}；每槽约 {SLOT_WEIGHT*100:.0f}%"

    print("\n跑 A：禁再买…", flush=True)
    a = simulate_portfolio_3slots(
        stock_payload, allow_open_rebuy_after_sell=False, **common
    )
    print("跑 B：全清后仍可触开盘阈值再买…", flush=True)
    b = simulate_portfolio_3slots(
        stock_payload, allow_open_rebuy_after_sell=True, **common
    )

    sa = _summary(a, label="禁再买")
    sb = _summary(b, label="开盘阈值同日再买")
    delta = None
    if sa.get("return_pct") is not None and sb.get("return_pct") is not None:
        delta = round(float(sb["return_pct"]) - float(sa["return_pct"]), 2)
    delta_dd = None
    if sa.get("max_dd_pct") is not None and sb.get("max_dd_pct") is not None:
        delta_dd = round(float(sb["max_dd_pct"]) - float(sa["max_dd_pct"]), 2)

    rebuy_trades = [
        t
        for t in (b.get("trades") or [])
        if t.get("side") == "buy" and t.get("source") == "open_rebuy_after_sell"
    ]
    out = {
        "disclaimer": "研究用途，非投资建议。生产盯盘/三槽默认仍禁当日再买。",
        "pool": "strategy16",
        "days": int(days),
        "all_pool": bool(all_pool),
        "scope": scope,
        "a": sa,
        "b": sb,
        "delta_return_pct": delta,
        "delta_max_dd_pct": delta_dd,
        "b_open_rebuy_trades": rebuy_trades,
        "a_trades": a.get("trades") or [],
        "b_trades": b.get("trades") or [],
    }
    out_json = OUT / f"COMPARE_OPEN_REBUY{stem}.json"
    out_md = OUT / f"COMPARE_OPEN_REBUY{stem}.md"
    out_json.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    def _fmt(x: Any) -> str:
        if x is None:
            return "—"
        if isinstance(x, float):
            return f"{x:.2f}"
        return str(x)

    cal = sa.get("calendar") or sb.get("calendar") or []
    lines = [
        f"# 策略十六 · 开盘阈值同日再买对照（{mode_s}）",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 结论口径",
        "",
        "- **A 禁再买**：当日全清（含低开硬保护）后禁再买该票。",
        "- **B 开盘阈值同日再买**：当日全清后若再触 `开盘×(1+entry)` 允许同日再买。",
        f"- {scope}",
        f"- 窗长：近 {days} 交易日 1m；日历：{', '.join(str(x) for x in cal) if cal else '—'}",
        "",
        "## 结果",
        "",
        "| 方案 | 组合收益% | 最大回撤% | 买/卖 | 开盘再买次数 | 已平仓均收益% | 期末持仓 |",
        "|------|-----------|-----------|-------|--------------|---------------|----------|",
        f"| {sa['label']} | {_fmt(sa.get('return_pct'))} | {_fmt(sa.get('max_dd_pct'))} | "
        f"{sa.get('n_buy')}/{sa.get('n_sell')} | {sa.get('n_open_rebuy')} | "
        f"{_fmt(sa.get('avg_closed_pnl_pct'))} | {sa.get('n_open')} |",
        f"| {sb['label']} | {_fmt(sb.get('return_pct'))} | {_fmt(sb.get('max_dd_pct'))} | "
        f"{sb.get('n_buy')}/{sb.get('n_sell')} | {sb.get('n_open_rebuy')} | "
        f"{_fmt(sb.get('avg_closed_pnl_pct'))} | {sb.get('n_open')} |",
        "",
        f"- **B−A 收益差**：{_fmt(delta)} 个百分点",
        f"- **B−A 回撤差**：{_fmt(delta_dd)} 个百分点",
        "",
        "## B 方案开盘再买明细",
        "",
        "| 时间 | 代码 | 名称 | 价 | 股 |",
        "|------|------|------|----|----|",
    ]
    if not rebuy_trades:
        lines.append("| — | — | — | — | 无 |")
    else:
        for t in rebuy_trades:
            lines.append(
                f"| {t.get('ts')} | {t.get('code')} | {t.get('name')} | "
                f"{t.get('px')} | {t.get('shares')} |"
            )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 生产盯盘默认仍禁当日再买；本开关仅研究（`allow_open_rebuy_after_sell`）。",
            "- 与因子22（收盘≥low×1.01）不同：本对照是 **开盘阈值** 再买。",
            "",
            f"产物：`{out_json.name}` / `{out_md.name}`",
            "",
            out["disclaimer"],
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n写入 {out_md}")
    print(
        f"A {sa.get('return_pct')}% / dd {sa.get('max_dd_pct')}%  |  "
        f"B {sb.get('return_pct')}% / dd {sb.get('max_dd_pct')}%  |  "
        f"开盘再买 {sb.get('n_open_rebuy')}  |  Δret={delta}"
    )
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument(
        "--all-pool",
        action="store_true",
        help="全池等权进场（不限三槽；槽=N、日最多买=N）",
    )
    args = ap.parse_args()
    raise SystemExit(
        main(days=int(args.days), refresh=bool(args.refresh), all_pool=bool(args.all_pool))
    )
