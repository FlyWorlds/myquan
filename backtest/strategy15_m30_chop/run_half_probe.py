"""半仓试探止损：触价出一半 → 30m 站稳接回 / 没站稳清完。

细周期优先 1 分钟（东财约近 5～8 个交易日）；完整震荡窗用 5 分钟补齐触价。
研究用途，非投资建议。

用法::

    PYTHONPATH=. python backtest/strategy15_m30_chop/run_half_probe.py
"""

from __future__ import annotations

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
    simulate_half_probe,
)
from strategy.minute import fetch_minute_1m, fetch_minute_5m, fetch_minute_30m  # noqa: E402
from strategy.open_break import (  # noqa: E402
    TICK_SIZE,
    ceil_to_tick,
    floor_to_tick,
    prev_day_allows_entry,
)

OUT_DIR = Path(__file__).resolve().parent
CACHE_1M = _ROOT / "data_cache" / "sh600330_1m.parquet"
CACHE_5M = _ROOT / "data_cache" / "sh600330_5m.parquet"
CACHE_30M = _ROOT / "data_cache" / "sh600330_30m.parquet"

FULL_START, FULL_END = "2026-08-14", "2026-09-03"
PCT = 0.03
INITIAL = 100_000.0
FEE, SLIP = 0.0015, 0.001


def _daily(start: str, end: str) -> pd.DataFrame:
    s = pd.Timestamp(start) - pd.Timedelta(days=5)
    e = pd.Timestamp(end) + pd.Timedelta(days=2)
    df = fetch_daily(TIANTONG.symbol, s.strftime("%Y%m%d"), e.strftime("%Y%m%d"))
    df = df.rename(columns={"date": "dt"}).sort_values("dt").reset_index(drop=True)
    df["d"] = pd.to_datetime(df["dt"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    return df


def _can_enter(daily: pd.DataFrame) -> dict[str, bool]:
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


def _pack(sim, *, label: str, fine: str, start: str, end: str) -> dict:
    return {
        "label": label,
        "fine_period": fine,
        "start": start,
        "end": end,
        "return_pct": round(sim.return_pct, 2),
        "buy_hold_pct": round(sim.buy_hold_pct, 2),
        "excess_pct": round(sim.excess_pct, 2),
        "max_dd_pct": round(sim.max_dd_pct, 2),
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
    }


def _run_window(
    *,
    fine_df: pd.DataFrame,
    m30_df: pd.DataFrame,
    daily: pd.DataFrame,
    start: str,
    end: str,
    fine_name: str,
) -> tuple[dict, dict]:
    can = _can_enter(daily)
    day_open = {str(r["d"]): float(r["open"]) for _, r in daily.iterrows()}
    fine = group_bars_by_day(fine_df, start=start, end=end)
    m30 = group_bars_by_day(m30_df, start=start, end=end)
    buy_fn = lambda o: ceil_to_tick(float(o) * (1 + PCT), TICK_SIZE)
    stop_fn = lambda o: floor_to_tick(float(o) * (1 - PCT), TICK_SIZE)
    params = M30ChopParams()

    half = simulate_half_probe(
        fine_bars_by_day=fine,
        m30_bars_by_day=m30,
        day_open=day_open,
        day_can_enter=can,
        buy_px_fn=buy_fn,
        stop_px_fn=stop_fn,
        params=params,
        initial_cash=INITIAL,
        fee=FEE,
        slip=SLIP,
    )
    # 对照：同窗 30m 确认止损模式
    conf = simulate_factor1_m30_chop(
        bars_by_day=m30,
        day_open=day_open,
        day_can_enter=can,
        buy_px_fn=buy_fn,
        stop_px_fn=stop_fn,
        params=params,
        initial_cash=INITIAL,
        fee=FEE,
        slip=SLIP,
    )
    return (
        _pack(half, label="half_probe", fine=fine_name, start=start, end=end),
        _pack(conf, label="confirm2_m30", fine="30m", start=start, end=end),
    )


def main() -> None:
    daily = _daily(FULL_START, FULL_END)
    m30 = fetch_minute_30m(
        sina_symbol=TIANTONG.symbol,
        em_symbol=TIANTONG.em_symbol,
        cache_path=CACHE_30M,
        start_date=FULL_START.replace("-", ""),
        end_date=FULL_END.replace("-", ""),
    )
    m5 = fetch_minute_5m(
        sina_symbol=TIANTONG.symbol,
        em_symbol=TIANTONG.em_symbol,
        cache_path=CACHE_5M,
        start_date=FULL_START.replace("-", ""),
        end_date=FULL_END.replace("-", ""),
    )
    m1 = fetch_minute_1m(
        sina_symbol=TIANTONG.symbol,
        em_symbol=TIANTONG.em_symbol,
        cache_path=CACHE_1M,
        start_date=FULL_START.replace("-", ""),
        end_date=FULL_END.replace("-", ""),
    )

    results = []
    notes = [
        "半仓试探：细周期触日线止损→卖一半；其后连续2根30m收盘>止损→接回半仓；"
        "连续2根30m收盘≤止损→剩余清完。含费+滑点。研究样本内，非投资建议。",
        "1分钟线来源东财/新浪，通常仅近数日；完整窗用5分钟触价。",
    ]

    # 全窗 5m
    h5, c5 = _run_window(
        fine_df=m5, m30_df=m30, daily=daily, start=FULL_START, end=FULL_END, fine_name="5m"
    )
    results.extend([h5, c5])

    # 1m 覆盖窗
    if m1 is not None and not m1.empty:
        ts = pd.to_datetime(m1["ts"])
        if getattr(ts.dt, "tz", None) is not None:
            local = ts.dt.tz_convert("Asia/Shanghai")
        else:
            local = ts.dt.tz_localize("Asia/Shanghai")
        dmin = local.min().strftime("%Y-%m-%d")
        dmax = local.max().strftime("%Y-%m-%d")
        start1 = max(FULL_START, dmin)
        end1 = min(FULL_END, dmax)
        notes.append(f"真1分钟覆盖：{start1}～{end1}（共 {len(m1)} 根）")
        h1, c1 = _run_window(
            fine_df=m1, m30_df=m30, daily=daily, start=start1, end=end1, fine_name="1m"
        )
        results.extend([h1, c1])
    else:
        notes.append("未能拉取1分钟线")

    summary = {
        "symbol": TIANTONG.symbol,
        "name": TIANTONG.symbol_name,
        "pct": PCT,
        "notes": notes,
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "half_probe_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 半仓试探止损（1m/5m 触价 + 30m 裁决）",
        "",
        "> 研究用途，非投资建议。",
        "",
    ]
    for n in notes:
        lines.append(f"- {n}")
    lines += ["", "| 方案 | 细周期 | 区间 | 收益 | vs B&H | 成交数 |", "|------|--------|------|------|--------|--------|"]
    for r in results:
        lines.append(
            f"| {r['label']} | {r['fine_period']} | {r['start']}～{r['end']} | "
            f"{r['return_pct']:+.2f}% | {r['excess_pct']:+.2f}% | {r['n_trades']} |"
        )
    lines += ["", "## 成交明细（半仓试探）", ""]
    for r in results:
        if r["label"] != "half_probe":
            continue
        lines.append(f"### {r['fine_period']} · {r['start']}～{r['end']}")
        for t in r["trades"]:
            lines.append(
                f"- {t['date']} {t['time']} {t['kind']} {t['qty']}@{t['price']} ({t['reason']})"
            )
        lines.append("")
    (OUT_DIR / "half_probe_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"→ {path}")
    for r in results:
        print(
            f"{r['label']:14s} {r['fine_period']:3s} {r['start']}～{r['end']} "
            f"ret={r['return_pct']:+.2f}% xs={r['excess_pct']:+.2f}% n={r['n_trades']}"
        )


if __name__ == "__main__":
    main()
