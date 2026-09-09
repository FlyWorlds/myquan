"""策略十六：生产三槽（禁当日再买） vs 研究开因子22同日再买。

用法：
  PYTHONPATH=. python backtest/strategy16_core_leader/compare_f22.py --days 7

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
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    load_strategy16_thr_map,
)
from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.pullback_wave_stop import DEFAULT_ENTRY_PCT, DEFAULT_PULLBACK_PCT  # noqa: E402

OUT = Path(__file__).resolve().parent


def _summary(port: dict[str, Any], *, label: str) -> dict[str, Any]:
    ps = port.get("summary") or {}
    trades = port.get("trades") or []
    n_f22 = sum(1 for t in trades if t.get("side") == "buy" and t.get("kind") == "factor22")
    n_buy = sum(1 for t in trades if t.get("side") == "buy")
    n_sell = sum(1 for t in trades if t.get("side") == "sell")
    return {
        "label": label,
        "return_pct": ps.get("return_pct"),
        "max_dd_pct": ps.get("max_dd_pct"),
        "end_equity": ps.get("end_equity"),
        "n_buy": n_buy,
        "n_sell": n_sell,
        "n_f22_rebuy": n_f22,
        "n_closed": ps.get("n_closed"),
        "avg_closed_pnl_pct": ps.get("avg_closed_pnl_pct"),
        "n_open": ps.get("n_open"),
        "calendar": ps.get("calendar"),
    }


def main(days: int = 7, refresh: bool = False) -> int:
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
    stock_payload: list[dict[str, Any]] = []
    print(f"策略十六对照 · {len(pool_rows)} 只 · 近 {days} 日 1m")
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

    common = dict(
        days=int(days),
        max_slots=int(MAX_PORTFOLIO_SLOTS),
        initial_cash=float(DEFAULT_ACCOUNT_TOTAL),
        slot_weight=float(SLOT_WEIGHT),
        buy_mode=BUY_MODE_DEFAULT,
    )
    print("\n跑 A：生产口径（当日卖出禁再买，factor22 不生效）…", flush=True)
    a = simulate_portfolio_3slots(stock_payload, allow_f22_rebuy=False, **common)
    print("跑 B：研究口径（日末收盘≥low×1.01 允许同日再买）…", flush=True)
    b = simulate_portfolio_3slots(stock_payload, allow_f22_rebuy=True, **common)

    sa, sb = _summary(a, label="无F22/禁再买(生产)"), _summary(b, label="开F22同日再买(研究)")
    out = {
        "disclaimer": "研究用途，非投资建议。生产盯盘/三槽默认仍禁当日再买。",
        "pool": "strategy16",
        "days": int(days),
        "a": sa,
        "b": sb,
        "delta_return_pct": None
        if sa.get("return_pct") is None or sb.get("return_pct") is None
        else round(float(sb["return_pct"]) - float(sa["return_pct"]), 4),
        "a_trades": a.get("trades") or [],
        "b_trades": b.get("trades") or [],
    }
    out_json = OUT / "COMPARE_F22.json"
    out_md = OUT / "COMPARE_F22.md"
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _fmt(x: Any) -> str:
        if x is None:
            return "—"
        if isinstance(x, float):
            return f"{x:.2f}"
        return str(x)

    lines = [
        "# 策略十六 · 因子22 同日再买对照",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 结论口径",
        "",
        "- **生产默认（A）**：当日止损/卖出后 **禁再买**；bindings 虽挂 factor22，**三槽成交路径不生效**。",
        "- **研究对照（B）**：当日卖出后，若收盘 ≥ 当日最低 × 1.01，允许 14:57 同日再买（因子22）。",
        f"- 窗长：近 {days} 交易日 1m；池=因子27核心龙头 + 天通/凯盛；三槽；买=开盘阈值。",
        "",
        "## 结果",
        "",
        "| 方案 | 组合收益% | 最大回撤% | 买/卖 | F22再买次数 | 已平仓均收益% | 期末持仓 |",
        "|------|-----------|-----------|-------|-------------|---------------|----------|",
        f"| {sa['label']} | {_fmt(sa.get('return_pct'))} | {_fmt(sa.get('max_dd_pct'))} | "
        f"{sa.get('n_buy')}/{sa.get('n_sell')} | {sa.get('n_f22_rebuy')} | "
        f"{_fmt(sa.get('avg_closed_pnl_pct'))} | {sa.get('n_open')} |",
        f"| {sb['label']} | {_fmt(sb.get('return_pct'))} | {_fmt(sb.get('max_dd_pct'))} | "
        f"{sb.get('n_buy')}/{sb.get('n_sell')} | {sb.get('n_f22_rebuy')} | "
        f"{_fmt(sb.get('avg_closed_pnl_pct'))} | {sb.get('n_open')} |",
        "",
        f"- **B−A 收益差**：{_fmt(out.get('delta_return_pct'))} 个百分点",
        "",
        "## 说明",
        "",
        "- 盯盘与 `run.py --pool strategy16` 默认对齐 **方案 A**。",
        "- 若要让 factor22 真正改交易，需改三槽「当日禁再买」规则；当前仅作研究对照。",
        "",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n写入 {out_md}")
    print(f"A 收益 {sa.get('return_pct')}%  |  B 收益 {sb.get('return_pct')}%  |  F22再买 {sb.get('n_f22_rebuy')}")
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    raise SystemExit(main(days=int(args.days), refresh=bool(args.refresh)))
