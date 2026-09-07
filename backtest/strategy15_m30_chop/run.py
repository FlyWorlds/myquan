"""策略十五 · 因子25：天通 30m 震荡减磨损回测（研究）。

对比买入持有 / 纯因子1（日线止损近似）/ 因子25 默认参数。
区间默认 2026-08-14～09-03（震荡段）；同样本调参，勿外推。

用法::

    PYTHONPATH=. python backtest/strategy15_m30_chop/run.py
    PYTHONPATH=. python backtest/strategy15_m30_chop/run.py --refresh

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

from strategy.config import TIANTONG  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.m30_chop import (  # noqa: E402
    M30ChopParams,
    group_bars_by_day,
    simulate_factor1_m30_chop,
)
from strategy.minute import fetch_minute_30m  # noqa: E402
from strategy.open_break import (  # noqa: E402
    TICK_SIZE,
    ceil_to_tick,
    floor_to_tick,
    prev_day_allows_entry,
)

OUT_DIR = Path(__file__).resolve().parent
CACHE_30M = _ROOT / "data_cache" / "sh600330_30m.parquet"

DEFAULT_START = "2026-08-14"
DEFAULT_END = "2026-09-03"
INITIAL = 100_000.0
FEE = 0.0015
SLIP = 0.001
PCT = 0.03


def _load_daily(start: str, end: str) -> pd.DataFrame:
    # 多取一日供前日过滤
    s = pd.Timestamp(start) - pd.Timedelta(days=5)
    e = pd.Timestamp(end) + pd.Timedelta(days=2)
    df = fetch_daily(
        TIANTONG.symbol,
        s.strftime("%Y%m%d"),
        e.strftime("%Y%m%d"),
    )
    df = df.rename(columns={"date": "dt"}).sort_values("dt").reset_index(drop=True)
    df["d"] = pd.to_datetime(df["dt"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    return df


def _can_enter_map(daily: pd.DataFrame) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for i, r in daily.iterrows():
        d = str(r["d"])
        if i == 0:
            out[d] = True
            continue
        prev = daily.iloc[i - 1]
        out[d] = bool(
            prev_day_allows_entry(
                float(prev["open"]),
                float(prev["close"]),
                prev_small_yang_pct=PCT,
                prev_entry_mode="yin_or_small_yang",
            )
        )
    return out


def _pure_f1_daily_approx(daily: pd.DataFrame, start: str, end: str) -> dict:
    """日线近似：开盘突破买、盘中低点触止损即出（无 30m 确认）。含费。"""
    rows = daily[(daily["d"] >= start) & (daily["d"] <= end)].reset_index(drop=True)
    can = _can_enter_map(daily)
    cash = INITIAL
    pos = 0
    avg = 0.0
    buy_day = None
    trades = 0
    for _, r in rows.iterrows():
        d = str(r["d"])
        o, h, lo, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        buy_px = ceil_to_tick(o * (1 + PCT), TICK_SIZE)
        stop_px = floor_to_tick(o * (1 - PCT), TICK_SIZE)
        t1 = pos > 0 and buy_day == d
        if pos > 0 and not t1 and lo <= stop_px + 1e-12:
            cash += stop_px * pos * (1 - FEE - SLIP)
            pos = 0
            avg = 0.0
            buy_day = None
            trades += 1
        if pos == 0 and can.get(d, True) and h + 1e-12 >= buy_px:
            qty = int(cash * 0.95 / buy_px / 100) * 100
            if qty >= 100:
                cash -= buy_px * qty * (1 + FEE + SLIP)
                pos, avg, buy_day = qty, buy_px, d
                trades += 1
    last = float(rows.iloc[-1]["close"])
    first = float(rows.iloc[0]["close"])
    eq = cash + pos * last
    ret = (eq / INITIAL - 1) * 100
    bh = (last / first - 1) * 100
    return {
        "name": "pure_f1_daily_approx",
        "return_pct": round(ret, 2),
        "buy_hold_pct": round(bh, 2),
        "excess_pct": round(ret - bh, 2),
        "trades": trades,
        "end_equity": round(eq, 2),
    }


def run(
    *,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    refresh: bool = False,
) -> dict:
    daily = _load_daily(start, end)
    can = _can_enter_map(daily)
    day_open = {str(r["d"]): float(r["open"]) for _, r in daily.iterrows()}

    m30 = fetch_minute_30m(
        sina_symbol=TIANTONG.symbol,
        em_symbol=TIANTONG.em_symbol,
        cache_path=CACHE_30M,
        refresh=refresh,
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
    )
    bars = group_bars_by_day(m30, start=start, end=end)
    if not bars:
        raise SystemExit(f"无 30m 数据: {start}～{end}")

    params = M30ChopParams()
    sim = simulate_factor1_m30_chop(
        bars_by_day=bars,
        day_open=day_open,
        day_can_enter=can,
        buy_px_fn=lambda o: ceil_to_tick(float(o) * (1 + PCT), TICK_SIZE),
        stop_px_fn=lambda o: floor_to_tick(float(o) * (1 - PCT), TICK_SIZE),
        params=params,
        initial_cash=INITIAL,
        fee=FEE,
        slip=SLIP,
    )
    f1 = _pure_f1_daily_approx(daily, start, end)
    first_c = sim.eod[0]["close"] if sim.eod else 0
    last_c = sim.eod[-1]["close"] if sim.eod else 0
    bh = (last_c / first_c - 1) * 100 if first_c else 0

    summary = {
        "symbol": TIANTONG.symbol,
        "name": TIANTONG.symbol_name,
        "pct": PCT,
        "start": start,
        "end": end,
        "fee_slip": FEE + SLIP,
        "note": "样本内研究；非投资建议；30m 确认止损+trail半仓+止损回补",
        "buy_hold_pct": round(bh, 2),
        "factor25": {
            "return_pct": round(sim.return_pct, 2),
            "excess_vs_bh_pct": round(sim.excess_pct, 2),
            "max_dd_pct": round(sim.max_dd_pct, 2),
            "end_equity": round(sim.end_equity, 2),
            "n_trades": len(sim.trades),
            "params": sim.params,
            "trades": [
                {
                    "date": t.date,
                    "time": t.time,
                    "kind": t.kind,
                    "price": t.price,
                    "qty": t.qty,
                    "reason": t.reason,
                }
                for t in sim.trades
            ],
        },
        "pure_f1_daily_approx": f1,
        "eod": sim.eod,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = _report_md(summary)
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
    return summary


def _report_md(s: dict) -> str:
    f25 = s["factor25"]
    f1 = s["pure_f1_daily_approx"]
    lines = [
        "# 策略十五 · 因子25 30m 震荡减磨损（天通）",
        "",
        "> 研究用途，非投资建议。区间窄、同样本调参。",
        "",
        f"- 标的：{s['name']} `{s['symbol']}`，因子1 ±{s['pct']:.0%}",
        f"- 区间：{s['start']} ～ {s['end']}",
        f"- 成本：佣金+印花近似 + 滑点合计约 {s['fee_slip']:.2%}/边",
        "",
        "## 结果对照",
        "",
        "| 方案 | 收益 | vs 买入持有 | 备注 |",
        "|------|------|-------------|------|",
        f"| 买入持有 | {s['buy_hold_pct']:+.2f}% | 0 | 首末 30m 日收 |",
        f"| 纯因子1（日线触价止损近似） | {f1['return_pct']:+.2f}% | {f1['excess_pct']:+.2f}% | 影线易假破 |",
        f"| **因子25 默认** | **{f25['return_pct']:+.2f}%** | **{f25['excess_vs_bh_pct']:+.2f}%** | "
        f"MDD {f25['max_dd_pct']:.2f}% |",
        "",
        "## 默认参数",
        "",
        "```json",
        json.dumps(f25["params"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 成交",
        "",
    ]
    for t in f25["trades"]:
        lines.append(
            f"- {t['date']} {t['time']} {t['kind']} {t['qty']}@{t['price']} ({t['reason']})"
        )
    lines += [
        "",
        "## 真源",
        "",
        "- `strategy/m30_chop.py` / `strategy/factors/factor25.py`",
        "- CLI：`PYTHONPATH=. python backtest/strategy15_m30_chop/run.py`",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="天通 因子25 30m 回测")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    s = run(start=args.start, end=args.end, refresh=args.refresh)
    f25 = s["factor25"]
    print(
        f"B&H {s['buy_hold_pct']:+.2f}% | F25 {f25['return_pct']:+.2f}% "
        f"(xs {f25['excess_vs_bh_pct']:+.2f}%) | "
        f"F1≈ {s['pure_f1_daily_approx']['return_pct']:+.2f}% | "
        f"→ {OUT_DIR / 'summary.json'}"
    )


if __name__ == "__main__":
    main()
