# -*- coding: utf-8 -*-
"""策略16池 · 2026-09 日线个股回测：当前大阳 vs 前2日合计>5% 大阳。

仅研究对照，不改生产代码、不提交、无组合槽位。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from holdingStocks.watch_config import strategy16_watchlist  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    is_t1_buy_day,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    yang_ret_pct,
)
from strategy.pullback_wave_stop import pullback_stop_price  # noqa: E402

SEP_START = "2026-09-01"
SEP_END = "2026-09-22"
LOOKBACK_START = "20260801"
TWO_DAY_SUM_THR = 0.05  # 前2日开收涨幅合计 > 5% → 新大阳不过门


def _sina(code: str) -> str:
    c = str(code).zfill(6)
    return ("sh" if c.startswith(("5", "6", "9")) else "sz") + c


def gate_current_dayang(prev, prev2, entry_pct: float) -> tuple[bool, str]:
    """现行：阴/小阳过门；前日阳且涨幅≥entry_pct → 大阳不过门；另保留双阳禁买。"""
    allows = prev_day_allows_entry(
        float(prev["open"]),
        float(prev["close"]),
        prev_small_yang_pct=float(entry_pct),
        prev_entry_mode="yin_or_small_yang",
    )
    if not allows:
        return False, "单日大阳"
    if prev2 is None:
        return True, "过门"
    blocked = should_block_entry_by_yang(
        float(prev2["open"]),
        float(prev2["close"]),
        float(prev["open"]),
        float(prev["close"]),
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    )
    if blocked:
        return False, "双阳≥5%"
    return True, "过门"


def gate_twoday_sum(prev, prev2, entry_pct: float) -> tuple[bool, str]:
    """新大阳：前2日各自开→收涨幅之和 > 5% 则不过门；双阳规则与现行相同。"""
    del entry_pct
    if prev2 is None:
        # 缺前2日时退回仅看前日是否暴涨（保守：用单日>5%）
        r1 = yang_ret_pct(float(prev["open"]), float(prev["close"]))
        if r1 == r1 and r1 > TWO_DAY_SUM_THR:
            return False, "单日>5%(缺prev2)"
    else:
        r2 = yang_ret_pct(float(prev2["open"]), float(prev2["close"]))
        r1 = yang_ret_pct(float(prev["open"]), float(prev["close"]))
        if r2 == r2 and r1 == r1 and (r2 + r1) > TWO_DAY_SUM_THR + 1e-12:
            return False, f"前2日合计{(r2+r1)*100:.1f}%>5%"
    if prev2 is None:
        return True, "过门"
    blocked = should_block_entry_by_yang(
        float(prev2["open"]),
        float(prev2["close"]),
        float(prev["open"]),
        float(prev["close"]),
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    )
    if blocked:
        return False, "双阳≥5%"
    return True, "过门"


def simulate_one(
    daily: pd.DataFrame,
    *,
    entry_pct: float,
    pullback_pct: float,
    gate_fn,
    window_start: str,
    window_end: str,
) -> dict:
    """个股独立日线回放（无槽）：开盘阈值买；T+1；卖=当日高点回落 pullback（因子26日线简化）。"""
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df = df.reset_index(drop=True)
    ws = pd.Timestamp(window_start)
    we = pd.Timestamp(window_end)

    holding = False
    buy_day = None
    buy_px = None
    trades: list[dict] = []
    blocked_hits = 0  # 价格触买点但不过门
    open_hits = 0

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2] if i >= 2 else None
        day = pd.Timestamp(row["date"]).normalize()
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if o <= 0:
            continue
        in_win = ws <= day <= we

        if holding:
            sess = str(day.date())
            bt = str(buy_day.date()) if buy_day is not None else None
            stop_px = pullback_stop_price(h, pullback_pct=pullback_pct, tick=TICK_SIZE)
            if not is_t1_buy_day(bt, sess) and l <= stop_px + 1e-12:
                if in_win or (buy_day is not None and ws <= buy_day <= we):
                    # 窗口内开仓的卖出，或窗口内卖出
                    if buy_day is not None and buy_day >= ws:
                        pnl = stop_px / float(buy_px) - 1.0 if buy_px else 0.0
                        trades.append(
                            {
                                "side": "sell",
                                "day": str(day.date()),
                                "px": round(stop_px, 4),
                                "buy_day": str(buy_day.date()),
                                "buy_px": buy_px,
                                "pnl": round(pnl, 4),
                            }
                        )
                holding = False
                buy_day = None
                buy_px = None
            elif day == we and holding and buy_day is not None and buy_day >= ws:
                # 窗口末日仍持：按收盘平仓记账（研究用）
                pnl = c / float(buy_px) - 1.0
                trades.append(
                    {
                        "side": "mark",
                        "day": str(day.date()),
                        "px": round(c, 4),
                        "buy_day": str(buy_day.date()),
                        "buy_px": buy_px,
                        "pnl": round(pnl, 4),
                    }
                )
            continue

        if not in_win:
            continue

        open_buy = entry_trigger_price(o, entry_pct=entry_pct, tick=TICK_SIZE)
        hit_open = h + 1e-12 >= open_buy
        if not hit_open:
            continue
        open_hits += 1
        ok, reason = gate_fn(prev, prev2, entry_pct)
        if not ok:
            blocked_hits += 1
            continue
        buy_px = open_buy
        buy_day = day
        holding = True
        trades.append(
            {
                "side": "buy",
                "day": str(day.date()),
                "px": round(buy_px, 4),
                "gate": reason,
            }
        )

    sells = [t for t in trades if t["side"] in ("sell", "mark") and t.get("pnl") is not None]
    buys = [t for t in trades if t["side"] == "buy"]
    # 复利：连乘 (1+pnl)
    eq = 1.0
    for t in sells:
        eq *= 1.0 + float(t["pnl"])
    return {
        "n_buy": len(buys),
        "n_exit": len(sells),
        "open_hits": open_hits,
        "blocked_hits": blocked_hits,
        "ret_pct": round((eq - 1.0) * 100.0, 2),
        "avg_trade_pct": round(
            sum(float(t["pnl"]) for t in sells) / len(sells) * 100.0, 2
        )
        if sells
        else None,
        "holding_eod": holding,
        "trades": trades,
    }


def main() -> None:
    pool = strategy16_watchlist()
    print(
        f"策略16池 {len(pool)} 只 · 窗口 {SEP_START}→{SEP_END} · "
        f"日线个股独立（无槽）· 对比：现行单日大阳 vs 前2日合计>{TWO_DAY_SUM_THR*100:.0f}%"
    )
    rows_a: list[dict] = []
    rows_b: list[dict] = []

    for w in pool:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        ep = float(w.get("entry_pct") or w.get("pct") or 0.025)
        pb = 0.025  # 策略16卖侧硬保护/回落默认口径
        sina = str(w.get("sina") or _sina(code)).lower()
        print(f"· {code} {name} ±{ep*100:.1f}% …", flush=True)
        try:
            daily = fetch_daily(sina, LOOKBACK_START, SEP_END.replace("-", ""))
        except Exception as e:  # noqa: BLE001
            print(f"  日线失败: {e}")
            continue
        if daily is None or getattr(daily, "empty", True):
            print("  无日线")
            continue
        a = simulate_one(
            daily,
            entry_pct=ep,
            pullback_pct=pb,
            gate_fn=gate_current_dayang,
            window_start=SEP_START,
            window_end=SEP_END,
        )
        b = simulate_one(
            daily,
            entry_pct=ep,
            pullback_pct=pb,
            gate_fn=gate_twoday_sum,
            window_start=SEP_START,
            window_end=SEP_END,
        )
        rows_a.append({"code": code, "name": name, "entry_pct": ep, **{k: a[k] for k in a if k != "trades"}})
        rows_b.append({"code": code, "name": name, "entry_pct": ep, **{k: b[k] for k in b if k != "trades"}})
        print(
            f"  现行: 买{a['n_buy']}/出{a['n_exit']} 收益{a['ret_pct']}% "
            f"触买{a['open_hits']} 被挡{a['blocked_hits']} | "
            f"新定义: 买{b['n_buy']}/出{b['n_exit']} 收益{b['ret_pct']}% "
            f"触买{b['open_hits']} 被挡{b['blocked_hits']}"
        )

    da = pd.DataFrame(rows_a)
    db = pd.DataFrame(rows_b)
    out_dir = _ROOT / "backtest" / "strategy16_core_leader"
    out_dir.mkdir(parents=True, exist_ok=True)
    path_a = out_dir / "_tmp_sep_dayang_current.csv"
    path_b = out_dir / "_tmp_sep_dayang_2dsum5.csv"
    da.to_csv(path_a, index=False, encoding="utf-8-sig")
    db.to_csv(path_b, index=False, encoding="utf-8-sig")

    def _summ(df: pd.DataFrame, label: str) -> None:
        if df.empty:
            print(f"\n{label}: 无数据")
            return
        eq = float(df["ret_pct"].mean())
        med = float(df["ret_pct"].median())
        buys = int(df["n_buy"].sum())
        exits = int(df["n_exit"].sum())
        blocked = int(df["blocked_hits"].sum())
        hits = int(df["open_hits"].sum())
        pos = int((df["ret_pct"] > 0).sum())
        print(f"\n=== {label} ===")
        print(f"等权收益均值: {eq:.2f}%  中位数: {med:.2f}%")
        print(f"正收益票数: {pos}/{len(df)}")
        print(f"买入合计: {buys}  平仓/记帐合计: {exits}")
        print(f"触达买点次数: {hits}  因大阳/过滤被挡: {blocked}")

    _summ(da, "现行大阳（前日阳且≥个股阈值，另保留双阳span≥5%）")
    _summ(db, "新大阳（前2日开→收涨幅合计>5%，另保留双阳span≥5%）")

    # 逐票对比
    merge = da.merge(db, on=["code", "name"], suffixes=("_cur", "_new"))
    merge["d_ret"] = merge["ret_pct_new"] - merge["ret_pct_cur"]
    merge["d_buy"] = merge["n_buy_new"] - merge["n_buy_cur"]
    merge["d_block"] = merge["blocked_hits_new"] - merge["blocked_hits_cur"]
    path_c = out_dir / "_tmp_sep_dayang_compare.csv"
    merge.to_csv(path_c, index=False, encoding="utf-8-sig")
    print(f"\n写入:\n  {path_a}\n  {path_b}\n  {path_c}")
    print("\n收益差(新−现) Top/Bottom 5:")
    show = merge.sort_values("d_ret", ascending=False)[
        ["code", "name", "ret_pct_cur", "ret_pct_new", "d_ret", "n_buy_cur", "n_buy_new", "blocked_hits_cur", "blocked_hits_new"]
    ]
    print(show.head(5).to_string(index=False))
    print("---")
    print(show.tail(5).to_string(index=False))
    print(
        f"\n等权收益差(新−现): {merge['d_ret'].mean():.2f}%  "
        f"买入次数差: {int(merge['d_buy'].sum())}  "
        f"被挡次数差: {int(merge['d_block'].sum())}"
    )
    print("\n研究用途，非投资建议；日线简化成交（非1m path）；未计费/滑点/槽位。")


if __name__ == "__main__":
    main()
