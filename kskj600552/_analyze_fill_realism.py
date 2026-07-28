"""回测 vs 实盘：统计「K 线允许但限价单可能无法成交」的场景."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import akquant as aq
import pandas as pd

_PATH = Path(__file__).with_name("kskj.py")
spec = importlib.util.spec_from_file_location("kskj", _PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def analyze_kline_issues(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in daily.iterrows():
        o, h, low, c = map(float, (r["open"], r["high"], r["low"], r["close"]))
        ep = m.entry_trigger_price(o)
        sp = m.stop_trigger_price(o)
        day = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")

        # 买入：high 触线但限价 buy@ep 可能不成交
        hit_entry_k = h + 1e-12 >= ep
        buy_fill_ok = hit_entry_k and (low <= ep + 1e-12)  # 日内曾到/低于限价买价
        buy_gap_skip = hit_entry_k and o > ep + 1e-12 and low > ep + 1e-12  # 跳空越过买点

        # 止损：low 触线但限价 sell@sp 可能不成交
        hit_stop_k = low <= sp + 1e-12
        stop_fill_ok = hit_stop_k and (h >= sp - 1e-12)  # 日内曾到/高于限价卖价
        stop_gap_skip = hit_stop_k and o < sp - 1e-12 and h < sp - 1e-12  # 跳空跌破止损

        # 阴线@收盘：收盘限价卖
        yin = m.is_yin(o, c)
        yin_fill_ok = yin and h >= c - 1e-12  # 收盘价曾被触及（日线 close 在 [low,high] 内恒成立）
        yin_close_below_stop = yin and low <= sp + 1e-12  # 应走止损而非阴线

        # 同日高低双触（买入日 T+1 不卖，但非持仓日无意义）
        dual_touch = hit_entry_k and hit_stop_k

        rows.append(
            {
                "day": day,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "entry_px": ep,
                "stop_px": sp,
                "hit_entry_k": hit_entry_k,
                "buy_fill_ok": buy_fill_ok,
                "buy_gap_skip": buy_gap_skip,
                "hit_stop_k": hit_stop_k,
                "stop_fill_ok": stop_fill_ok,
                "stop_gap_skip": stop_gap_skip,
                "yin": yin,
                "yin_fill_ok": yin_fill_ok,
                "yin_close_below_stop": yin_close_below_stop,
                "dual_touch": dual_touch,
            }
        )
    return pd.DataFrame(rows)


def match_executions(result: aq.BacktestResult) -> pd.DataFrame:
    ex = result.executions_df.copy()
    ex["ts"] = pd.to_datetime(ex["timestamp"]).dt.tz_convert("Asia/Shanghai")
    ex["day"] = ex["ts"].dt.strftime("%Y-%m-%d")
    ex["side"] = ex["side"].str.lower()
    return ex


def main() -> None:
    daily = m.fetch_daily(m.SYMBOL, m.START_DATE, m.END_DATE)
    k = analyze_kline_issues(daily)

    result = aq.run_backtest(
        data=daily,
        strategy=m.OpenBreak3Strategy,
        symbols=m.SYMBOL,
        initial_cash=m.INITIAL_CASH,
        commission_rate=m.COMMISSION_RATE,
        stamp_tax_rate=m.STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=m.LOT_SIZE,
        fill_policy=m.FILL_CLOSE,
        slippage=m.SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )
    ex = match_executions(result)

    buys = ex[ex["side"] == "buy"][["day", "price"]].rename(columns={"price": "exec_buy_px"})
    sells = ex[ex["side"] == "sell"][["day", "price"]].rename(columns={"price": "exec_sell_px"})

    buy_days = set(buys["day"])
    sell_days = set(sells["day"])

    # 实际买入日中：K 线认为可买但限价可能不成交
    buy_exec = buys.merge(k, on="day", how="left")
    buy_suspect = buy_exec[~buy_exec["buy_fill_ok"].fillna(False)]

    # 实际卖出日分类（用日志 reason 更好，这里用价格近似）
    sell_exec = sells.merge(k, on="day", how="left")
    # 止损卖：exec price 接近 stop_px
    sell_exec["is_stop_sell"] = (
        (sell_exec["exec_sell_px"] - sell_exec["stop_px"]).abs() < 0.02
    )
    stop_sells = sell_exec[sell_exec["is_stop_sell"]]
    yin_sells = sell_exec[~sell_exec["is_stop_sell"]]

    stop_suspect = stop_sells[~stop_sells["stop_fill_ok"].fillna(False)]
    yin_suspect = yin_sells[yin_sells["yin"] & ~yin_sells["yin_fill_ok"].fillna(False)]

    # 买入日 low 也触止损（T+1 不能卖，但回测是否误卖？）
    same_day_bs = ex.groupby("day")["side"].apply(lambda s: set(s)).to_dict()
    same_day_trade = [d for d, sides in same_day_bs.items() if "buy" in sides and "sell" in sides]

    # 买入日 K 线双触
    buy_day_dual = k[k["day"].isin(buy_days) & k["dual_touch"]]

    print("=" * 70)
    print(f"{m.SYMBOL_NAME}  回测成交 realism 分析  {m.START_DATE}~{m.END_DATE}")
    print("=" * 70)

    print("\n【1】买入：high≥触发价 但 限价买@触发价 可能不成交")
    print("  条件：open>触发价 且 low>触发价（跳空高开越过买点，全天未回落到买点）")
    n_hit = int(k["hit_entry_k"].sum())
    n_gap = int(k["buy_gap_skip"].sum())
    print(f"  K 线触买点天数: {n_hit}  其中疑似假成交: {n_gap}")
    if n_gap:
        sub = k[k["buy_gap_skip"]][["day", "open", "high", "low", "entry_px"]]
        print(sub.to_string(index=False))

    print(f"\n  回测实际买入: {len(buys)} 笔")
    print(f"  其中 buy_fill_ok=False（仍被回测买入）: {len(buy_suspect)} 笔")
    if not buy_suspect.empty:
        print(
            buy_suspect[["day", "open", "high", "low", "entry_px", "exec_buy_px"]].to_string(
                index=False
            )
        )

    print("\n【2】止损：low≤触发价 但 限价卖@触发价 可能不成交")
    print("  条件：open<止损价 且 high<止损价（跳空低开跌破止损，全天未反弹到止损价）")
    n_stop = int(k["hit_stop_k"].sum())
    n_stop_gap = int(k["stop_gap_skip"].sum())
    print(f"  K 线触止损天数: {n_stop}  其中疑似假成交: {n_stop_gap}")
    if n_stop_gap:
        sub = k[k["stop_gap_skip"]][["day", "open", "high", "low", "stop_px"]]
        print(sub.head(15).to_string(index=False))

    print(f"\n  回测止损卖: {len(stop_sells)} 笔")
    print(f"  其中 stop_fill_ok=False（仍按触发价成交）: {len(stop_suspect)} 笔")
    if not stop_suspect.empty:
        print(
            stop_suspect[
                ["day", "open", "high", "low", "stop_px", "exec_sell_px"]
            ].to_string(index=False)
        )

    print("\n【3】阴线@收盘价卖")
    print("  日线回测在 bar 结束时挂 limit=close，通常视为可成交（尾盘/集合竞价）")
    print(f"  回测阴线类卖出: {len(yin_sells)} 笔  理论不可成交: {len(yin_suspect)} 笔")
    print("  → 实盘用市价/收盘价委托，一般合理；主要风险是流动性而非价格不可达")

    print("\n【4】T+1 / 同日买卖")
    print(f"  回测同日买+卖: {len(same_day_trade)} 天 → 应为 0（买入日 skip 卖出）")
    if same_day_trade:
        print(f"  !! 异常: {same_day_trade}")
    print(f"  实际买入日且 K 线 high触买+low触止损: {len(buy_day_dual)} 天")
    print("  → 买入日不能卖，需次日再判；策略已 skip，但当日浮亏/浮盈被低估")

    print("\n【5】日线 bar 固有局限（非 akquant 独有）")
    print("  · 同 bar 内 high/low 先后顺序未知：先涨后跌 vs 先跌后涨，影响是否先买后止损")
    print("  · 仅 OHLCV，无分时；所有触价均用 high/low 近似")
    print("  · 无涨跌停/停牌/一字板无法成交过滤")
    print("  · 95% 仓位未校验 volume 能否吃下")
    print("  · 前复权价与实盘委托价可能有细微偏差")

    print("\n【6】止损乐观侧（回测偏有利，你已讨论）")
    stop_sells_m = stop_sells.merge(k[["day", "close", "stop_px"]], on="day")
    if not stop_sells_m.empty:
        better = stop_sells_m[stop_sells_m["close"] > stop_sells_m["stop_px"] + 1e-8]
        worse = stop_sells_m[stop_sells_m["close"] < stop_sells_m["stop_px"] - 1e-8]
        print(f"  止损卖 {len(stop_sells_m)} 笔：收盘>触发价 {len(better)}（实盘或需尾盘卖更差）")
        print(f"                    收盘<触发价 {len(worse)}（实盘条件单难成交→尾盘更差）")

    print("\n【7】总结优先级")
    print("  高：止损@触发价假设必成交（跳空跌破/触线未反弹）→ 用模型1+尾盘兜底")
    print("  中：买入@触发价在极端跳空高开时可能不成交 → 回测或偏多")
    print("  低：阴线@收盘、T+1、滑点/佣金 → 当前处理基本合理")


if __name__ == "__main__":
    main()
