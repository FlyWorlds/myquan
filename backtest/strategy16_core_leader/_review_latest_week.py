# -*- coding: utf-8 -*-
"""策略十六核心池 · 最近一周 (2026-10-19 至 2026-10-23) 回测与上证指数对比。"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import akshare as ak
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
)
from strategy.pullback_wave_stop import pullback_stop_price

LOOKBACK_START = "20260901"
END_FETCH = "20261026"
START_WEEK = "2026-10-19"
END_WEEK = "2026-10-23"


def get_sh000001_week():
    df = ak.stock_zh_index_daily(symbol="sh000001")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    sub = df[(df["date"] >= "2026-10-16") & (df["date"] <= "2026-10-26")].sort_values("date").reset_index(drop=True)
    return sub


def check_gate_current(prev: pd.Series, prev2: pd.Series | None, entry_pct: float) -> tuple[bool, str]:
    allows = prev_day_allows_entry(
        float(prev["open"]),
        float(prev["close"]),
        prev_small_yang_pct=float(entry_pct),
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


def simulate_week_portfolio(stocks: list[dict[str, Any]], initial_cash: float = 300_000.0, max_slots: int = 3):
    # 统一转换时区
    stock_dfs = {}
    stock_cfg = {}
    for s in stocks:
        df = s["daily"].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        stock_dfs[s["code"]] = df
        stock_cfg[s["code"]] = s

    # 交易日取本周 5 天: 2026-10-19 到 2026-10-23
    calendar = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]

    cash = float(initial_cash)
    positions: dict[str, dict[str, Any]] = {}
    trades = []
    daily_records = []
    last_close_map = {}

    for sess_str in calendar:
        current_day = pd.Timestamp(sess_str)

        # 更新各票收盘
        for code, df in stock_dfs.items():
            day_rows = df[df["date"].dt.normalize() == current_day]
            if not day_rows.empty:
                last_close_map[code] = float(day_rows.iloc[0]["close"])

        # 1. 先卖
        sold_today = set()
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
            pos["peak_high"] = max(pos["peak_high"], h)
            stop_px = pullback_stop_price(pos["peak_high"], pullback_pct=cfg["pullback_pct"], tick=TICK_SIZE)

            if can_sell and l <= stop_px + 1e-12:
                sell_fill = min(o, stop_px) if o <= stop_px else stop_px
                sell_fill *= (1.0 - SLIP)
                proceeds = pos["shares"] * sell_fill
                fee = proceeds * COMMISSION + proceeds * STAMP
                cash += proceeds - fee
                pnl = (sell_fill / pos["buy_px"] - 1.0)
                trades.append({
                    "date": sess_str,
                    "code": code,
                    "name": cfg["name"],
                    "side": "卖出",
                    "buy_day": pos["buy_day"],
                    "buy_px": pos["buy_px"],
                    "sell_px": round(sell_fill, 2),
                    "shares": pos["shares"],
                    "pnl_pct": round(pnl * 100.0, 2),
                    "reason": "峰值回落2.5%止盈/止损",
                })
                del positions[code]
                sold_today.add(code)

        # 2. 扫买
        candidate_buys = []
        for code, cfg in stock_cfg.items():
            if code in positions or code in sold_today:
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
                ok, reason = check_gate_current(prev, prev2, entry_pct=cfg["entry_pct"])
                if ok:
                    candidate_buys.append({
                        "code": code,
                        "name": cfg["name"],
                        "buy_px": open_buy,
                        "entry_pct": cfg["entry_pct"],
                    })

        # 3. 入槽
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
                        "code": code,
                        "name": cand["name"],
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
                        "side": "买入",
                        "buy_px": round(px, 2),
                        "shares": raw,
                        "reason": f"开盘突破+{cand['entry_pct']*100:.1f}%",
                    })

        # 4. 日末收盘统计
        mkt_val_eod = sum(pos["shares"] * float(last_close_map.get(c, pos["buy_px"])) for c, pos in positions.items())
        eq_eod = cash + mkt_val_eod
        daily_records.append({
            "date": sess_str,
            "equity": round(eq_eod, 2),
            "cash": round(cash, 2),
            "market_val": round(mkt_val_eod, 2),
            "hold_count": len(positions),
            "holdings": ",".join(f"{pos['name']}({c})" for c, pos in positions.items()),
        })

    # 周末未平仓浮盈统计
    open_positions = []
    for c, pos in positions.items():
        last_px = float(last_close_map.get(c, pos["buy_px"]))
        float_pnl = (last_px / pos["buy_px"] - 1.0) * 100.0
        open_positions.append({
            "code": c,
            "name": pos["name"],
            "buy_day": pos["buy_day"],
            "buy_px": pos["buy_px"],
            "last_px": last_px,
            "shares": pos["shares"],
            "float_pnl_pct": round(float_pnl, 2),
        })

    tot_ret = (daily_records[-1]["equity"] / initial_cash - 1.0) * 100.0
    eq_series = pd.Series([r["equity"] for r in daily_records])
    peak = eq_series.cummax()
    dd = (eq_series - peak) / peak
    max_dd = abs(float(dd.min())) * 100.0

    return {
        "initial_cash": initial_cash,
        "final_equity": daily_records[-1]["equity"],
        "week_ret_pct": round(tot_ret, 2),
        "week_max_dd_pct": round(max_dd, 2),
        "daily_records": daily_records,
        "trades": trades,
        "open_positions": open_positions,
    }


def main():
    print("=========================================================================")
    print("  最近一周 (2026-10-19 ~ 2026-10-23) 回测：策略十六池 vs 上证指数")
    print("=========================================================================\n")

    # 1. 上证指数
    sh_df = get_sh000001_week()
    p_prev_close = float(sh_df[sh_df["date"] == "2026-10-16"]["close"].iloc[0])
    p_open_mon = float(sh_df[sh_df["date"] == "2026-10-19"]["open"].iloc[0])
    p_close_fri = float(sh_df[sh_df["date"] == "2026-10-23"]["close"].iloc[0])
    p_high_week = float(sh_df[sh_df["date"] >= "2026-10-19"]["high"].max())
    p_low_week = float(sh_df[sh_df["date"] >= "2026-10-19"]["low"].min())

    sh_ret_prev = (p_close_fri / p_prev_close - 1.0) * 100.0
    sh_ret_open = (p_close_fri / p_open_mon - 1.0) * 100.0
    sh_mdd = (p_low_week / p_high_week - 1.0) * 100.0

    print("--- 【一、 上证指数 (sh000001) 最近一周表现】 ---")
    week_sh = sh_df[sh_df["date"] >= "2026-10-19"][["date", "open", "high", "low", "close"]].copy()
    week_sh["日期"] = week_sh["date"].dt.strftime("%Y-%m-%d")
    week_sh["单日涨跌幅%"] = round(week_sh["close"].pct_change() * 100.0, 2)
    week_sh.iloc[0, week_sh.columns.get_loc("单日涨跌幅%")] = round((week_sh.iloc[0]["close"] / p_prev_close - 1.0) * 100.0, 2)
    print(week_sh[["日期", "open", "high", "low", "close", "单日涨跌幅%"]].to_string(index=False))

    print(f"\n上证指数最近一周汇总:")
    print(f"  · 上周五收盘(10-16): {p_prev_close:.2f}")
    print(f"  · 本周一开盘(10-19): {p_open_mon:.2f}  周五收盘(10-23): {p_close_fri:.2f}")
    print(f"  · 本周最高: {p_high_week:.2f}  本周最低: {p_low_week:.2f}")
    print(f"  · 整周涨跌幅(相对上周末收盘): {sh_ret_prev:+.2f}%")
    print(f"  · 本周涨跌幅(周一开盘到周五收盘): {sh_ret_open:+.2f}%")
    print(f"  · 本周最大振幅回撤: {sh_mdd:.2f}%\n")

    # 2. 策略十六池标的
    pool = strategy16_watchlist()
    stocks = []
    bh_rets = []
    for w in pool:
        code = str(w["code"]).zfill(6)
        sina = str(w.get("sina") or ("sh" if code.startswith(("5", "6", "9")) else "sz") + code).lower()
        name = str(w.get("name") or code)
        ep = float(w.get("entry_pct") or 0.025)
        pb = float(w.get("stop_pct") or 0.025)
        daily = fetch_daily(sina, LOOKBACK_START, END_FETCH)
        if daily is None or daily.empty:
            continue
        daily["date"] = pd.to_datetime(daily["date"]).dt.tz_localize(None)
        stocks.append({
            "code": code,
            "name": name,
            "entry_pct": ep,
            "pullback_pct": pb,
            "daily": daily,
        })
        d_sub = daily[(daily["date"] >= "2026-10-16") & (daily["date"] <= "2026-10-23")].sort_values("date")
        if len(d_sub) >= 2:
            c_fri_prev = float(d_sub.iloc[0]["close"])
            c_fri_curr = float(d_sub.iloc[-1]["close"])
            bh_rets.append({"code": code, "name": name, "ret_pct": (c_fri_curr / c_fri_prev - 1.0) * 100.0})

    # 3. 策略十六三槽位组合回测
    port_res = simulate_week_portfolio(stocks, initial_cash=300_000.0, max_slots=3)

    print("--- 【二、 策略十六三槽位组合 最近一周表现】 ---")
    print(f"  · 初始资金: {port_res['initial_cash']:,.0f} 元")
    print(f"  · 周末权益: {port_res['final_equity']:,.2f} 元")
    print(f"  · 本周组合收益率: {port_res['week_ret_pct']:+.2f}%")
    print(f"  · 本周最大回撤: {port_res['week_max_dd_pct']:.2f}%")

    print("\n每日权益记录:")
    print(pd.DataFrame(port_res["daily_records"]).to_string(index=False))

    print("\n本周全部成交明细:")
    if port_res["trades"]:
        print(pd.DataFrame(port_res["trades"]).to_string(index=False))
    else:
        print("  本周无成交")

    print("\n周末(10-23收盘)持仓与浮盈:")
    if port_res["open_positions"]:
        print(pd.DataFrame(port_res["open_positions"]).to_string(index=False))
    else:
        print("  周末无持仓 (空仓)")

    # 4. 池内34只股票买入持有 (Buy & Hold) 表现
    df_bh = pd.DataFrame(bh_rets)
    print("\n--- 【三、 池内34只标的最近一周行情环境 (买入持有)】 ---")
    print(f"  · 标的等权均值涨跌幅: {df_bh['ret_pct'].mean():+.2f}%")
    print(f"  · 标的中位数涨跌幅: {df_bh['ret_pct'].median():+.2f}%")
    print(f"  · 上涨标的数: {(df_bh['ret_pct']>0).sum()} / {len(df_bh)} ({(df_bh['ret_pct']>0).mean()*100:.1f}%)")
    top3 = df_bh.sort_values("ret_pct", ascending=False).head(3)
    bot3 = df_bh.sort_values("ret_pct", ascending=True).head(3)
    print("  · 涨幅 Top3:", "、".join(f"{r['name']}({r['ret_pct']:+.2f}%)" for _, r in top3.iterrows()))
    print("  · 跌幅 Top3:", "、".join(f"{r['name']}({r['ret_pct']:+.2f}%)" for _, r in bot3.iterrows()))

    # 5. 超额差距总结
    alpha = port_res["week_ret_pct"] - sh_ret_prev
    print("\n--- 【四、 相对上证指数的超额差距】 ---")
    print(f"  · 策略十六三槽组合本周收益: {port_res['week_ret_pct']:+.2f}%")
    print(f"  · 上证指数同期涨跌幅: {sh_ret_prev:+.2f}%")
    print(f"  · 策略相对大盘超额收益 (Alpha): {alpha:+.2f} 个百分点")


if __name__ == "__main__":
    main()
