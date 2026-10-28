# -*- coding: utf-8 -*-
"""策略十六核心池 · 2025年至今日线回测：大阳线过门条件对比。

对照三组：
  1. 现行（当前）：大阳线 = 各票 entry_pct（2.0% / 2.5% / 3.0%，默认 2.5%）
  2. 大阳线 = 3%（前日实体涨幅 ≥ 3% 不过门，< 3% 过门）
  3. 大阳线 = 5%（前日实体涨幅 ≥ 5% 不过门，< 5% 过门）

双阳跨日 ≥ 5% 禁买规则在三组中均保持一致。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import strategy16_watchlist
from strategy.costs import (
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.data import fetch_daily
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    is_t1_buy_day,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)
from strategy.pullback_wave_stop import pullback_stop_price

LOOKBACK_START = "20241201"
END_FETCH = "20261026"


def check_gate(
    prev: pd.Series,
    prev2: pd.Series | None,
    *,
    dayang_pct: float,
) -> tuple[bool, str]:
    """判断过门条件。dayang_pct 为界定大阳线的阈值。"""
    allows = prev_day_allows_entry(
        float(prev["open"]),
        float(prev["close"]),
        prev_small_yang_pct=float(dayang_pct),
        prev_entry_mode="yin_or_small_yang",
    )
    if not allows:
        return False, "前日大阳"
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


def simulate_single_stock(
    daily: pd.DataFrame,
    *,
    entry_pct: float,
    pullback_pct: float,
    dayang_pct: float,
    start_date: str = "2025-01-01",
    end_date: str = "2026-10-26",
    sell_mode: str = "pullback",
) -> dict[str, Any]:
    """个股独立日线回放（全额复利，含费用）：计算各票的纯信号表现。"""
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)

    ws = pd.Timestamp(start_date)
    we = pd.Timestamp(end_date)

    cash = 100_000.0
    shares = 0
    buy_px = 0.0
    buy_day = None
    peak_high = 0.0

    trades = []
    blocked_hits = 0
    open_hits = 0
    daily_equity = []

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

        # 1. 卖出处理
        if shares > 0:
            sess = str(day.date())
            bt = str(buy_day.date()) if buy_day is not None else None
            can_sell = not is_t1_buy_day(bt, sess)
            hit_exit = False
            sell_fill = 0.0
            exit_reason = ""

            if sell_mode == "pullback":
                peak_high = max(peak_high, h)
                stop_px = pullback_stop_price(peak_high, pullback_pct=pullback_pct, tick=TICK_SIZE)
                if can_sell and l <= stop_px + 1e-12:
                    hit_exit = True
                    sell_fill = min(o, stop_px) if o <= stop_px else stop_px
                    exit_reason = "峰值回落止盈/止损"
            else:
                stop_px = stop_trigger_price(o, stop_pct=entry_pct, tick=TICK_SIZE)
                if can_sell and l <= stop_px + 1e-12:
                    hit_exit = True
                    sell_fill = stop_px
                    exit_reason = "开盘止损"

            if hit_exit:
                sell_fill *= 1.0 - SLIP
                proceeds = shares * sell_fill
                fee = proceeds * COMMISSION + proceeds * STAMP
                cash += proceeds - fee
                pnl = (sell_fill / buy_px - 1.0) if buy_px > 0 else 0.0
                trades.append({
                    "buy_day": str(buy_day.date()),
                    "sell_day": str(day.date()),
                    "buy_px": buy_px,
                    "sell_px": sell_fill,
                    "shares": shares,
                    "pnl_pct": pnl,
                    "reason": exit_reason,
                })
                shares = 0
                buy_day = None
                buy_px = 0.0
                peak_high = 0.0

        # 2. 买入处理（若空仓且在回测窗口内）
        if shares == 0 and in_win:
            open_buy = entry_trigger_price(o, entry_pct=entry_pct, tick=TICK_SIZE)
            hit_open = h + 1e-12 >= open_buy
            if hit_open:
                open_hits += 1
                ok, reason = check_gate(prev, prev2, dayang_pct=dayang_pct)
                if not ok:
                    blocked_hits += 1
                else:
                    px = open_buy * (1.0 + SLIP)
                    target_cash = cash * 0.95
                    raw = math.floor(target_cash / (px * 100)) * 100
                    if raw >= 100:
                        outlay = raw * px
                        fee = outlay * COMMISSION
                        if outlay + fee <= cash:
                            cash -= outlay + fee
                            shares = raw
                            buy_px = px
                            buy_day = day
                            peak_high = h

        if in_win:
            mkt_val = shares * c
            daily_equity.append(cash + mkt_val)

    if shares > 0:
        last_c = float(df.iloc[-1]["close"]) * (1.0 - SLIP)
        proceeds = shares * last_c
        fee = proceeds * COMMISSION + proceeds * STAMP
        cash += proceeds - fee
        trades.append({
            "buy_day": str(buy_day.date()),
            "sell_day": str(df.iloc[-1]["date"].date()),
            "buy_px": buy_px,
            "sell_px": last_c,
            "shares": shares,
            "pnl_pct": (last_c / buy_px - 1.0),
            "reason": "期末平仓",
        })

    total_return_pct = (cash / 100_000.0 - 1.0) * 100.0
    wins = [t for t in trades if t["pnl_pct"] > 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    avg_trade_pct = (sum(t["pnl_pct"] for t in trades) / len(trades) * 100.0) if trades else 0.0

    eq_series = pd.Series(daily_equity)
    if not eq_series.empty:
        peak = eq_series.cummax()
        dd = (eq_series - peak) / peak
        max_dd = abs(float(dd.min())) * 100.0
    else:
        max_dd = 0.0

    return {
        "total_return_pct": round(total_return_pct, 2),
        "trade_count": len(trades),
        "win_rate": round(win_rate, 2),
        "avg_trade_pct": round(avg_trade_pct, 2),
        "max_dd_pct": round(max_dd, 2),
        "open_hits": open_hits,
        "blocked_hits": blocked_hits,
        "trades": trades,
    }


def simulate_portfolio_3slots(
    stocks: list[dict[str, Any]],
    dayang_mode: str,  # "current", "3pct", "5pct"
    start_date: str = "2025-01-01",
    end_date: str = "2026-10-26",
    initial_cash: float = 300_000.0,
    max_slots: int = 3,
    sell_mode: str = "pullback",
) -> dict[str, Any]:
    """三槽组合回测（先平再买，每日最多买3，每槽约1/3资金）。"""
    all_dates = set()
    stock_dfs = {}
    stock_cfg = {}
    last_close_map = {}

    for s in stocks:
        df = s["daily"].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        code = s["code"]
        stock_dfs[code] = df
        stock_cfg[code] = s
        valid_dates = df[(df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))]["date"]
        all_dates.update(valid_dates.dt.normalize())

    calendar = sorted(list(all_dates))

    cash = float(initial_cash)
    positions: dict[str, dict[str, Any]] = {}
    trades = []
    equity_curve = []
    total_blocked = 0
    total_hits = 0

    for current_day in calendar:
        sess_str = current_day.strftime("%Y-%m-%d")

        # 更新当日收盘缓存
        for code, df in stock_dfs.items():
            day_rows = df[df["date"].dt.normalize() == current_day]
            if not day_rows.empty:
                last_close_map[code] = float(day_rows.iloc[0]["close"])

        # 1. 先处理现有持仓的卖出
        sold_codes_today = set()
        for code in list(positions.keys()):
            pos = positions[code]
            df = stock_dfs[code]
            cfg = stock_cfg[code]
            day_rows = df[df["date"].dt.normalize() == current_day]
            if day_rows.empty:
                continue
            row = day_rows.iloc[0]
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

            can_sell = not is_t1_buy_day(pos["buy_day"], sess_str)
            hit_exit = False
            sell_fill = 0.0
            exit_reason = ""

            if sell_mode == "pullback":
                pos["peak_high"] = max(pos["peak_high"], h)
                stop_px = pullback_stop_price(pos["peak_high"], pullback_pct=cfg["pullback_pct"], tick=TICK_SIZE)
                if can_sell and l <= stop_px + 1e-12:
                    hit_exit = True
                    sell_fill = min(o, stop_px) if o <= stop_px else stop_px
                    exit_reason = "峰值回落止盈/止损"
            else:
                stop_px = stop_trigger_price(o, stop_pct=cfg["entry_pct"], tick=TICK_SIZE)
                if can_sell and l <= stop_px + 1e-12:
                    hit_exit = True
                    sell_fill = stop_px
                    exit_reason = "开盘止损"

            if hit_exit:
                sell_fill *= 1.0 - SLIP
                proceeds = pos["shares"] * sell_fill
                fee = proceeds * COMMISSION + proceeds * STAMP
                cash += proceeds - fee
                pnl = (sell_fill / pos["buy_px"] - 1.0)
                trades.append({
                    "date": sess_str,
                    "code": code,
                    "name": cfg["name"],
                    "side": "sell",
                    "buy_day": pos["buy_day"],
                    "buy_px": pos["buy_px"],
                    "sell_px": sell_fill,
                    "shares": pos["shares"],
                    "pnl_pct": pnl,
                    "reason": exit_reason,
                })
                del positions[code]
                sold_codes_today.add(code)

        # 2. 扫描今日候选买入
        candidate_buys = []
        for code, cfg in stock_cfg.items():
            if code in positions or code in sold_codes_today:
                continue
            df = stock_dfs[code]
            idxs = df[df["date"].dt.normalize() == current_day].index
            if len(idxs) == 0:
                continue
            i = idxs[0]
            if i < 1:
                continue
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            prev2 = df.iloc[i - 2] if i >= 2 else None
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            if o <= 0:
                continue

            open_buy = entry_trigger_price(o, entry_pct=cfg["entry_pct"], tick=TICK_SIZE)
            if h + 1e-12 >= open_buy:
                total_hits += 1
                if dayang_mode == "current":
                    d_pct = cfg["entry_pct"]
                elif dayang_mode == "3pct":
                    d_pct = 0.03
                else:
                    d_pct = 0.05

                ok, reason = check_gate(prev, prev2, dayang_pct=d_pct)
                if ok:
                    candidate_buys.append({
                        "code": code,
                        "name": cfg["name"],
                        "buy_px": open_buy,
                        "entry_pct": cfg["entry_pct"],
                    })
                else:
                    total_blocked += 1

        # 3. 入槽买入
        buys_today = 0
        for cand in candidate_buys:
            if len(positions) >= max_slots or buys_today >= max_slots:
                break
            code = cand["code"]
            px = cand["buy_px"] * (1.0 + SLIP)
            mkt_val = sum(pos["shares"] * float(last_close_map.get(c, pos["buy_px"])) for c, pos in positions.items())
            eq_now = cash + mkt_val
            slot_budget = eq_now / max_slots
            budget = min(cash * 0.95, slot_budget)
            raw = math.floor(budget / (px * 100)) * 100
            if raw >= 100:
                outlay = raw * px
                fee = outlay * COMMISSION
                if outlay + fee <= cash:
                    cash -= outlay + fee
                    positions[code] = {
                        "buy_day": sess_str,
                        "buy_px": px,
                        "shares": raw,
                        "peak_high": px,
                    }
                    buys_today += 1
                    trades.append({
                        "date": sess_str,
                        "code": code,
                        "name": cand["name"],
                        "side": "buy",
                        "buy_px": px,
                        "shares": raw,
                    })

        # 4. 统计当日收盘权益
        mkt_val_eod = 0.0
        for c, pos in positions.items():
            close_px = float(last_close_map.get(c, pos["buy_px"]))
            mkt_val_eod += pos["shares"] * close_px
        total_eod = cash + mkt_val_eod
        equity_curve.append({"date": sess_str, "equity": total_eod})

    eq_df = pd.DataFrame(equity_curve)
    tot_ret = (eq_df["equity"].iloc[-1] / initial_cash - 1.0) * 100.0 if not eq_df.empty else 0.0
    peak = eq_df["equity"].cummax()
    dd = (eq_df["equity"] - peak) / peak
    max_dd = abs(float(dd.min())) * 100.0 if not dd.empty else 0.0

    sells = [t for t in trades if t["side"] == "sell"]
    wins = [t for t in sells if t["pnl_pct"] > 0]
    wr = (len(wins) / len(sells) * 100.0) if sells else 0.0
    avg_pnl = (sum(t["pnl_pct"] for t in sells) / len(sells) * 100.0) if sells else 0.0

    return {
        "total_return_pct": round(tot_ret, 2),
        "max_dd_pct": round(max_dd, 2),
        "total_trades": len(sells),
        "win_rate": round(wr, 2),
        "avg_trade_pct": round(avg_pnl, 2),
        "total_hits": total_hits,
        "total_blocked": total_blocked,
        "final_equity": round(eq_df["equity"].iloc[-1], 2) if not eq_df.empty else initial_cash,
        "trades": trades,
        "equity_curve": eq_df,
    }


def run_period(stocks: list[dict], start_date: str, end_date: str, period_label: str):
    print(f"\n=======================================================")
    print(f"  回测区间: {period_label} ({start_date} → {end_date})")
    print(f"=======================================================")

    modes = [
        ("现行大阳(个股阈值2%~3%)", "current"),
        ("大阳线门槛=3%", "3pct"),
        ("大阳线门槛=5%", "5pct"),
    ]

    # 1. 单票独立等权统计
    single_results = {m[1]: [] for m in modes}
    for s in stocks:
        daily = s["daily"]
        ep = s["entry_pct"]
        pb = s["pullback_pct"]

        for label, m_key in modes:
            if m_key == "current":
                d_pct = ep
            elif m_key == "3pct":
                d_pct = 0.03
            else:
                d_pct = 0.05
            res = simulate_single_stock(daily, entry_pct=ep, pullback_pct=pb, dayang_pct=d_pct, start_date=start_date, end_date=end_date)
            res["code"] = s["code"]
            res["name"] = s["name"]
            res["entry_pct"] = ep
            single_results[m_key].append(res)

    print("\n--- 【维度一：个股独立等权回测】 ---")
    summary_rows = []
    for label, m_key in modes:
        df_res = pd.DataFrame(single_results[m_key])
        mean_ret = df_res["total_return_pct"].mean()
        med_ret = df_res["total_return_pct"].median()
        pos_count = (df_res["total_return_pct"] > 0).sum()
        total_buys = df_res["trade_count"].sum()
        mean_wr = df_res["win_rate"].mean()
        mean_mdd = df_res["max_dd_pct"].mean()
        tot_hits = df_res["open_hits"].sum()
        tot_blk = df_res["blocked_hits"].sum()

        summary_rows.append({
            "方案": label,
            "等权均值收益%": round(mean_ret, 2),
            "中位数收益%": round(med_ret, 2),
            "正收益标的数": f"{pos_count}/{len(df_res)} ({pos_count/len(df_res)*100:.1f}%)",
            "总交易次数": int(total_buys),
            "平均胜率%": round(mean_wr, 2),
            "平均最大回撤%": round(mean_mdd, 2),
            "大阳拦截次数": int(tot_blk),
        })
    print(pd.DataFrame(summary_rows).to_string(index=False))

    # 2. 三槽位组合回测统计
    print("\n--- 【维度二：三槽位组合回测（先平再买，每日最多买3）】 ---")
    port_summary_rows = []
    for label, m_key in modes:
        pres = simulate_portfolio_3slots(stocks, dayang_mode=m_key, start_date=start_date, end_date=end_date, initial_cash=300_000.0, max_slots=3)
        port_summary_rows.append({
            "方案": label,
            "组合总收益%": pres["total_return_pct"],
            "期末权益(30w起)": f"{pres['final_equity']:,.0f}",
            "组合最大回撤%": pres["max_dd_pct"],
            "总平仓次数": pres["total_trades"],
            "胜率%": pres["win_rate"],
            "单笔均收益%": pres["avg_trade_pct"],
            "组合大阳拦截数": pres["total_blocked"],
        })
    print(pd.DataFrame(port_summary_rows).to_string(index=False))

    return single_results


def main():
    pool = strategy16_watchlist()
    stocks = []
    for w in pool:
        code = str(w["code"]).zfill(6)
        sina = str(w.get("sina") or ("sh" if code.startswith(("5", "6", "9")) else "sz") + code).lower()
        name = str(w.get("name") or code)
        ep = float(w.get("entry_pct") or 0.025)
        pb = float(w.get("stop_pct") or 0.025)
        daily = fetch_daily(sina, LOOKBACK_START, END_FETCH)
        if daily is None or daily.empty:
            continue
        stocks.append({
            "code": code,
            "name": name,
            "sina": sina,
            "entry_pct": ep,
            "pullback_pct": pb,
            "daily": daily,
        })

    # 分别运行：全周期 (2025-01-01 -> 2026-10-26)、2025全年、2026至今
    full_res = run_period(stocks, "2025-01-01", "2026-10-26", "2025年~至今 全周期")
    run_period(stocks, "2025-01-01", "2025-12-31", "2025年 全年")
    run_period(stocks, "2026-01-01", "2026-10-26", "2026年 至今")

    # 导出全周期逐票明细对比
    cur_df = pd.DataFrame(full_res["current"])[["code", "name", "entry_pct", "total_return_pct", "trade_count", "blocked_hits"]]
    p3_df = pd.DataFrame(full_res["3pct"])[["code", "name", "total_return_pct", "trade_count", "blocked_hits"]]
    p5_df = pd.DataFrame(full_res["5pct"])[["code", "name", "total_return_pct", "trade_count", "blocked_hits"]]

    merged = cur_df.merge(p3_df, on=["code", "name"], suffixes=("_现行", "_3pct")).merge(p5_df, on=["code", "name"])
    merged = merged.rename(columns={
        "total_return_pct": "total_return_pct_5pct",
        "trade_count": "trade_count_5pct",
        "blocked_hits": "blocked_hits_5pct",
    })
    merged["收益差_3pct减现行"] = merged["total_return_pct_3pct"] - merged["total_return_pct_现行"]
    merged["收益差_5pct减现行"] = merged["total_return_pct_5pct"] - merged["total_return_pct_现行"]

    out_csv = _ROOT / "backtest" / "strategy16_core_leader" / "dayang_compare_2025_2026.csv"
    merged.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n逐票明细已保存至: {out_csv}")

    print("\n--- 收益改善最明显的 Top 3 标的（放宽到5% vs 现行） ---")
    top_gain = merged.sort_values("收益差_5pct减现行", ascending=False).head(3)
    print(top_gain[["code", "name", "entry_pct", "total_return_pct_现行", "total_return_pct_5pct", "收益差_5pct减现行"]].to_string(index=False))

    print("\n--- 收益劣化最严重的 Top 3 标的（放宽到5% vs 现行） ---")
    top_loss = merged.sort_values("收益差_5pct减现行", ascending=True).head(3)
    print(top_loss[["code", "name", "entry_pct", "total_return_pct_现行", "total_return_pct_5pct", "收益差_5pct减现行"]].to_string(index=False))


if __name__ == "__main__":
    main()
