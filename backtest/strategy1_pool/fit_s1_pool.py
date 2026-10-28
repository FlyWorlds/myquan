# -*- coding: utf-8 -*-
"""
策略一 (援军战法) 个股开盘阈值与选股池生成：
与策略十六 (fit_thr.py / picks_quarter.json) 算法与结构完全保持一致。
2026 至今日线开盘突破 {2%, 2.5%, 3%} 夏普择优。
输出：
  1. backtest/strategy1_pool/thr_2026.json
  2. backtest/strategy1_pool/picks_pool.json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import (
    strategy1_watchlist,
    code_key,
    sina_of,
)
from strategy.costs import (
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)

OUT_DIR = Path(__file__).resolve().parent
THR_PATH = OUT_DIR / "thr_2026.json"
PICKS_PATH = OUT_DIR / "picks_pool.json"
CANDIDATES = (0.02, 0.025, 0.03)
FIT_START = "20260101"
DEFAULT_THR = float(DEFAULT_PCT)
TARGET_PCT = 0.95
LOT = 100


def simulate_open_break(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    *,
    thr: float,
    initial_cash: float = 100_000.0,
) -> tuple[np.ndarray, np.ndarray]:
    n = len(o)
    equity = np.empty(n, dtype=np.float64)
    holding_arr = np.zeros(n, dtype=np.int8)
    cash = float(initial_cash)
    shares = 0.0
    prev_holding = False
    peak_high = 0.0

    for i in range(n):
        open_i, high_i, low_i, close_i = o[i], h[i], l[i], c[i]
        limit_down = limit_down_state(
            prev_close=c[i - 1] if i > 0 else open_i,
            open_px=open_i,
            high_px=high_i,
            low_px=low_i,
            close_px=close_i,
            tick=TICK_SIZE,
        )
        stop_locked = bool(limit_down["locked"])
        stop_price = stop_trigger_price(open_i, stop_pct=thr, tick=TICK_SIZE)
        entry_price = entry_trigger_price(open_i, entry_pct=thr, tick=TICK_SIZE)

        if prev_holding:
            peak_high = max(peak_high, high_i)

        sold_today = False
        if prev_holding and not stop_locked and low_i <= stop_price + 1e-12:
            fill = min(open_i, stop_price) if open_i <= stop_price else stop_price
            exec_px = fill * (1.0 - SLIP)
            gross = shares * exec_px
            net = gross * (1.0 - COMMISSION - STAMP)
            cash += net
            shares = 0.0
            prev_holding = False
            sold_today = True

        gate_pass = False
        if i >= 1:
            gate_pass = prev_day_allows_entry(
                o[i - 1],
                c[i - 1],
                prev_small_yang_pct=thr,
                prev_entry_mode="yin_or_small_yang",
            )
        if gate_pass and i >= 2:
            blocked = should_block_entry_by_yang(
                o[i - 2],
                c[i - 2],
                o[i - 1],
                c[i - 1],
                ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
            )
            if blocked:
                gate_pass = False

        if (not prev_holding) and (not sold_today) and gate_pass:
            if high_i >= entry_price - 1e-12:
                fill = max(open_i, entry_price)
                exec_px = fill * (1.0 + SLIP)
                budget = cash * TARGET_PCT
                buy_shares = math.floor(budget / (exec_px * LOT)) * LOT
                if buy_shares > 0:
                    gross = buy_shares * exec_px
                    fee = gross * COMMISSION
                    cash -= (gross + fee)
                    shares = float(buy_shares)
                    prev_holding = True
                    peak_high = max(high_i, exec_px)

        pos_val = shares * close_i
        equity[i] = cash + pos_val
        holding_arr[i] = 1 if shares > 0 else 0

    return equity, holding_arr


def annual_sharpe(equity: np.ndarray, trading_days: int = 250) -> float:
    if len(equity) < 2:
        return 0.0
    rets = np.diff(equity) / equity[:-1]
    std = float(np.std(rets))
    if std < 1e-12:
        return 0.0
    return float(np.mean(rets) / std * np.sqrt(trading_days))


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) < 2:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    dds = (equity - peaks) / peaks
    return float(abs(np.min(dds)))


def count_trades(holding: np.ndarray) -> int:
    if len(holding) < 2:
        return 0
    return int(np.sum((holding[1:] == 1) & (holding[:-1] == 0)))


def fit_one(df: pd.DataFrame, code: str) -> dict[str, Any]:
    sub = df[df["date"] >= pd.Timestamp(FIT_START)].copy().sort_values("date").reset_index(drop=True)
    if len(sub) < 20:
        return {
            "thr": DEFAULT_THR,
            "ok": False,
            "reason": f"bars < 20 ({len(sub)})",
            "grid": [],
        }

    o = sub["open"].to_numpy(dtype=np.float64)
    h = sub["high"].to_numpy(dtype=np.float64)
    l = sub["low"].to_numpy(dtype=np.float64)
    c = sub["close"].to_numpy(dtype=np.float64)

    benchmark_ret = (c[-1] / c[0] - 1.0) if c[0] > 0 else 0.0

    grid = []
    for cand in CANDIDATES:
        eq, hld = simulate_open_break(o, h, l, c, thr=cand)
        ret = (eq[-1] / eq[0] - 1.0)
        sh = annual_sharpe(eq)
        mdd = max_drawdown(eq)
        n_tr = count_trades(hld)
        grid.append({
            "thr": cand,
            "ok": True,
            "n_trades": n_tr,
            "sharpe": round(sh, 4),
            "ret_pct": round(ret * 100.0, 2),
            "mdd_pct": round(mdd * 100.0, 2),
            "excess_pct": round((ret - benchmark_ret) * 100.0, 2),
        })

    # 夏普最高，并列看收益，再靠近 2.5%
    def sort_key(item: dict[str, Any]):
        return (
            item["sharpe"],
            item["ret_pct"],
            -abs(item["thr"] - DEFAULT_THR),
        )

    best = max(grid, key=sort_key)
    return {
        "thr": best["thr"],
        "ok": True,
        "n_trades": best["n_trades"],
        "sharpe": best["sharpe"],
        "ret_pct": best["ret_pct"],
        "mdd_pct": best["mdd_pct"],
        "excess_pct": best["excess_pct"],
        "fallback": False,
        "grid": grid,
        "n_bars": len(sub),
    }


# 股票与行业概念映射（参考通达信与市场主流标签）
STOCK_CONCEPTS = {
    "000581": ("威孚高科", "汽车零部件 / 氢能源"),
    "002015": ("协鑫能科", "换电概念 / 虚拟电厂"),
    "002065": ("东华软件", "人工智能 / 华为算力"),
    "002093": ("国脉科技", "物联网 / 6G概念"),
    "002104": ("恒宝股份", "数字货币 / 数据安全"),
    "002152": ("广电运通", "数字货币 / 智慧金融"),
    "002273": ("水晶光电", "CPO概念 / 光学光电子"),
    "002636": ("金安国纪", "PCB概念 / 覆铜板"),
    "002779": ("中坚科技", "机器人概念 / 园林机械"),
    "002922": ("伊戈尔", "充电桩 / 高压快充"),
    "002929": ("润建股份", "算力租赁 / 通信网络"),
    "600301": ("华锡有色", "小金属 / 锡锑资源"),
    "600330": ("天通股份", "磁性材料 / 蓝宝石"),
    "600338": ("西藏珠峰", "锂电池 / 铅锌矿"),
    "600353": ("旭光电子", "氮化铝 / 电子陶瓷"),
    "600552": ("凯盛科技", "UTG玻璃 / 柔性屏"),
    "600967": ("内蒙一机", "军工装备 / 坦克装甲"),
    "601020": ("华钰矿业", "小金属 / 锑矿黄金"),
    "601068": ("中铝国际", "中字头 / 工程建设"),
    "601208": ("东材科技", "光刻胶 / 复合铜箔"),
    "601519": ("大智慧", "互联网金融 / 券商IT"),
    "601609": ("金田股份", "铜缆高速连接 / 铜加工"),
    "603301": ("振德医疗", "医疗器械 / 养老概念"),
    "603920": ("世运电路", "PCB概念 / 汽车电子"),
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    w_list = strategy1_watchlist()
    print(f"开始拟合策略一股票池: {len(w_list)} 只标的...")

    thrs_result = {}
    picks_list = []

    for idx, item in enumerate(w_list, 1):
        code = item["code"]
        name = item.get("name") or STOCK_CONCEPTS.get(code, ("", ""))[0]
        sina = item["sina"]
        concept = STOCK_CONCEPTS.get(code, ("", "主板核心池"))[1]

        cache_p = _ROOT / "data_cache" / f"{sina}_daily_qfq.parquet"
        if not cache_p.is_file():
            print(f"缺失缓存: {sina}")
            continue

        df = pd.read_parquet(cache_p)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        res = fit_one(df, code)
        res["name"] = name
        thrs_result[code] = res

        # 选股产物条目（与 picks_quarter.json 的字段和结构完全对齐）
        picks_list.append({
            "rank": idx,
            "code": code,
            "symbol": code,
            "name": name,
            "concept": concept,
            "theme": concept,
            "price": float(df.iloc[-1]["close"]) if not df.empty else None,
            "chg_pct": round(float(res.get("ret_pct", 0.0)), 2),
            "amount": None,
            "thr": res["thr"],
            "sharpe": res.get("sharpe", 0.0),
            "category": "自选" if item.get("pool_src") == "self" else "策略池",
            "pool_src": item.get("pool_src") or "strategy1_pool",
        })

    # 1. 保存 thr_2026.json
    thr_dist = {}
    for r in thrs_result.values():
        t_str = f"{r['thr']*100:.1f}"
        thr_dist[t_str] = thr_dist.get(t_str, 0) + 1

    thr_payload = {
        "as_of": str(datetime.now().date()),
        "fit_start": FIT_START,
        "fit_end": str(datetime.now().date()),
        "rule": "日线开盘突破；买/止损同 thr；{2%,2.5%,3%} 夏普最高，并列看收益，再靠近 2.5%",
        "candidates": list(CANDIDATES),
        "default_thr": DEFAULT_THR,
        "n_pool": len(thrs_result),
        "thr_dist": thr_dist,
        "disclaimer": "研究用途，与策略十六算法保持100%同源对齐。",
        "thrs": thrs_result,
    }

    with open(THR_PATH, "w", encoding="utf-8") as f:
        json.dump(thr_payload, f, ensure_ascii=False, indent=2)
    print(f"已生成策略一夏普择优阈值表: {THR_PATH} (分布: {thr_dist})")

    # 2. 保存 picks_pool.json（与 picks_quarter.json 格式对齐）
    picks_payload = {
        "horizon": "rolling_3m",
        "label": "2026 援军战法定盘池",
        "as_of": str(datetime.now().date()),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "strategy1_quality_band_factor13a_16",
        "n_picks": len(picks_list),
        "target_pool": len(picks_list),
        "note": f"援军战法 2026 定盘池（{len(picks_list)} 只）· 算法与策略十六对齐",
        "picks": picks_list,
    }

    with open(PICKS_PATH, "w", encoding="utf-8") as f:
        json.dump(picks_payload, f, ensure_ascii=False, indent=2)
    print(f"已生成策略一标准化选股产物: {PICKS_PATH}")


if __name__ == "__main__":
    main()
