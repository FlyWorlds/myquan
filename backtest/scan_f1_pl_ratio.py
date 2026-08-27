"""盈亏比（配对口径）全量统计。

定义（逐笔闭环）：
  · 策略收益% = 本笔买价→卖价（含滑点/佣金/印花税后的净收益）
  · 持有收益% = 上笔卖出日收盘 → 本笔卖出日收盘
      （首笔：回测窗首日收盘 → 本笔卖出日收盘）
  · 盈亏比 = 平均盈利% / |平均亏损%|（对上述收益序列分别统计）

先算天通(±3%)、凯盛(±2.5%)；再扫沪深300∪中证500∪1000，
每票试 ±2/2.5/3%，取策略盈亏比最高档，输出前30。

  python backtest/scan_f1_pl_ratio.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)
from backtest.universe_zz500_1000 import CACHE_DIR  # noqa: E402

OUT = Path(__file__).resolve().parent / "f1_pl_ratio_scan"
START = "2025-01-02"
END = "20260827"
THRESHOLDS = (0.02, 0.025, 0.03)
CASH = 100_000.0
TARGET_PCT = 0.95
LOT = 100
MIN_TRADES = 8
SIM_WORKERS = 8
MIN_BARS = 80

PINNED = (
    {"code": "600330", "name": "天通股份", "symbol": "sh600330", "thr": 0.03},
    {"code": "600552", "name": "凯盛科技", "symbol": "sh600552", "thr": 0.025},
)


def simulate_trades(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    dates: pd.DatetimeIndex,
    *,
    thr: float,
    initial_cash: float = CASH,
) -> pd.DataFrame:
    """返回闭环交易表：buy/sell 价量与策略净收益%。"""
    n = len(o)
    cash = float(initial_cash)
    shares = 0.0
    entry_px = 0.0
    buy_i = -1
    buy_cost_net = 0.0
    tick = TICK_SIZE
    rows: list[dict] = []

    for i in range(n):
        oi, hi, li, ci = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        if oi <= 0 or ci <= 0:
            continue
        buy_px = entry_trigger_price(oi, entry_pct=thr, tick=tick)
        stop_px = stop_trigger_price(oi, stop_pct=thr, tick=tick)

        if shares > 0:
            if i > buy_i and li <= stop_px + 1e-12:
                prev_c = float(c[i - 1]) if i > 0 else ci
                lim = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=0.10,
                    tick=tick,
                )
                if not bool(lim["locked"]):
                    sell_px = float(
                        lim["limit_px"] if bool(lim["opened"]) else stop_px
                    )
                    sell_px *= 1.0 - SLIP
                    proceeds = shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    net = proceeds - fee
                    cash += net
                    strat_ret = net / buy_cost_net - 1.0 if buy_cost_net > 0 else float("nan")
                    rows.append(
                        {
                            "buy_i": buy_i,
                            "sell_i": i,
                            "buy_date": str(dates[buy_i].date()),
                            "sell_date": str(dates[i].date()),
                            "buy_px": entry_px,
                            "sell_px": sell_px,
                            "sell_close": ci,
                            "shares": shares,
                            "strat_ret": strat_ret,
                        }
                    )
                    shares = 0.0
                    entry_px = 0.0
                    buy_i = -1
                    buy_cost_net = 0.0
        else:
            if i >= 1:
                po, pc = float(o[i - 1]), float(c[i - 1])
                allows = prev_day_allows_entry(
                    po, pc, prev_small_yang_pct=thr, prev_entry_mode="yin_or_small_yang"
                )
                blocked = False
                if i >= 2:
                    blocked = should_block_entry_by_yang(
                        float(o[i - 2]),
                        float(c[i - 2]),
                        po,
                        pc,
                        tick=tick,
                        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                    )
                if allows and (not blocked) and (hi + 1e-12 >= buy_px):
                    px = buy_px * (1.0 + SLIP)
                    budget = cash * TARGET_PCT
                    raw = math.floor(budget / (px * LOT)) * LOT
                    if raw >= LOT:
                        cost = raw * px
                        fee = cost * COMMISSION
                        if cost + fee <= cash:
                            cash -= cost + fee
                            shares = float(raw)
                            entry_px = px
                            buy_i = i
                            buy_cost_net = cost + fee

    return pd.DataFrame(rows)


def attach_hold_rets(trades: pd.DataFrame, closes: np.ndarray) -> pd.DataFrame:
    """持有收益：上笔卖收盘→本笔卖收盘；首笔用回测窗首日收盘。"""
    if trades is None or trades.empty:
        return trades
    t = trades.copy()
    hold = []
    prev_sell_close = float(closes[0])
    for _, row in t.iterrows():
        sc = float(row["sell_close"])
        base = prev_sell_close
        hold.append(sc / base - 1.0 if base > 0 else float("nan"))
        prev_sell_close = sc
    t["hold_ret"] = hold
    return t


def pl_stats(rets: pd.Series) -> dict:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if r.empty:
        return {
            "n": 0,
            "win_rate": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "pl_ratio": None,
            "profit_factor": None,
            "sum_pct": None,
            "avg_pct": None,
        }
    wins = r[r > 0]
    losses = r[r < 0]
    flats = r[r == 0]
    aw = float(wins.mean()) if len(wins) else float("nan")
    al = float(losses.mean()) if len(losses) else float("nan")
    pl = abs(aw / al) if len(wins) and len(losses) and al == al and al != 0 else None
    sw = float(wins.sum()) if len(wins) else 0.0
    sl = float(losses.sum()) if len(losses) else 0.0
    pf = (sw / abs(sl)) if sl < 0 else (None if sw <= 0 else float("inf"))
    return {
        "n": int(len(r)),
        "n_win": int(len(wins)),
        "n_loss": int(len(losses)),
        "n_flat": int(len(flats)),
        "win_rate": round(float((r > 0).mean()) * 100, 2),
        "avg_win_pct": round(aw * 100, 3) if aw == aw else None,
        "avg_loss_pct": round(al * 100, 3) if al == al else None,
        "pl_ratio": round(pl, 3) if pl is not None else None,
        "profit_factor": round(pf, 3) if pf is not None and pf != float("inf") else pf,
        "sum_pct": round(float(r.sum()) * 100, 2),
        "avg_pct": round(float(r.mean()) * 100, 3),
    }


def load_bt_daily(symbol: str) -> pd.DataFrame | None:
    path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    if not path.exists():
        return None
    d = pd.read_parquet(path).copy()
    d["date"] = pd.to_datetime(d["date"])
    if getattr(d["date"].dt, "tz", None) is not None:
        d["date"] = d["date"].dt.tz_localize(None)
    d["date"] = d["date"].dt.normalize()
    for col in ("open", "high", "low", "close"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    start = pd.Timestamp(START)
    end = pd.Timestamp(f"{END[:4]}-{END[4:6]}-{END[6:8]}")
    bt = d[(d["date"] >= start) & (d["date"] <= end)].reset_index(drop=True)
    if len(bt) < MIN_BARS:
        return None
    return bt


def analyze_symbol(symbol: str, thr: float) -> dict | None:
    bt = load_bt_daily(symbol)
    if bt is None:
        return None
    dates = pd.DatetimeIndex(bt["date"])
    o = bt["open"].to_numpy(float)
    h = bt["high"].to_numpy(float)
    l = bt["low"].to_numpy(float)
    c = bt["close"].to_numpy(float)
    trades = simulate_trades(o, h, l, c, dates, thr=thr)
    if trades.empty or len(trades) < MIN_TRADES:
        return {
            "ok": 0,
            "error": f"trades={len(trades)}",
            "n_trades": int(len(trades)),
            "thr_pct": round(thr * 100, 1),
        }
    trades = attach_hold_rets(trades, c)
    ss = pl_stats(trades["strat_ret"])
    hs = pl_stats(trades["hold_ret"])
    # 配对：策略相对持有的超额序列
    excess = trades["strat_ret"] - trades["hold_ret"]
    es = pl_stats(excess)
    return {
        "ok": 1,
        "error": "",
        "thr_pct": round(thr * 100, 1),
        "n_trades": int(len(trades)),
        "strat_pl_ratio": ss["pl_ratio"],
        "strat_win_rate": ss["win_rate"],
        "strat_avg_win_pct": ss["avg_win_pct"],
        "strat_avg_loss_pct": ss["avg_loss_pct"],
        "strat_profit_factor": ss["profit_factor"],
        "strat_sum_pct": ss["sum_pct"],
        "hold_pl_ratio": hs["pl_ratio"],
        "hold_win_rate": hs["win_rate"],
        "hold_avg_win_pct": hs["avg_win_pct"],
        "hold_avg_loss_pct": hs["avg_loss_pct"],
        "hold_profit_factor": hs["profit_factor"],
        "hold_sum_pct": hs["sum_pct"],
        "excess_pl_ratio": es["pl_ratio"],
        "excess_win_rate": es["win_rate"],
        "excess_sum_pct": es["sum_pct"],
        "pl_ratio_edge": (
            round(ss["pl_ratio"] - hs["pl_ratio"], 3)
            if ss["pl_ratio"] is not None and hs["pl_ratio"] is not None
            else None
        ),
        "trades": trades,
    }


def _worker(payload: dict) -> dict:
    base = {
        "code": str(payload["code"]).zfill(6),
        "name": payload["name"],
        "symbol": payload["symbol"],
        "index": payload.get("index", ""),
    }
    best = None
    detail_rows = []
    for thr in payload.get("thresholds", THRESHOLDS):
        try:
            r = analyze_symbol(payload["symbol"], thr)
        except Exception as exc:  # noqa: BLE001
            detail_rows.append({**base, "ok": 0, "error": str(exc)[:160], "thr_pct": thr * 100})
            continue
        if r is None:
            detail_rows.append({**base, "ok": 0, "error": "no_data", "thr_pct": thr * 100})
            continue
        row = {**base, **{k: v for k, v in r.items() if k != "trades"}}
        detail_rows.append(row)
        if r.get("ok") == 1 and r.get("strat_pl_ratio") is not None:
            if best is None or r["strat_pl_ratio"] > best["strat_pl_ratio"]:
                best = row
    return {"detail": detail_rows, "best": best}


def run_pinned() -> pd.DataFrame:
    rows = []
    trade_frames = []
    for p in PINNED:
        r = analyze_symbol(p["symbol"], p["thr"])
        assert r and r["ok"] == 1, p
        rows.append(
            {
                "code": p["code"],
                "name": p["name"],
                "symbol": p["symbol"],
                "thr_pct": round(p["thr"] * 100, 1),
                **{k: v for k, v in r.items() if k != "trades"},
            }
        )
        t = r["trades"].copy()
        t.insert(0, "name", p["name"])
        t.insert(0, "code", p["code"])
        t["thr_pct"] = round(p["thr"] * 100, 1)
        t["strat_ret_pct"] = (t["strat_ret"] * 100).round(3)
        t["hold_ret_pct"] = (t["hold_ret"] * 100).round(3)
        trade_frames.append(t)
        print(f"\n=== {p['name']} ±{p['thr']*100:g}% ===")
        print(
            f"闭环{r['n_trades']}  策略盈亏比={r['strat_pl_ratio']}  "
            f"持有盈亏比={r['hold_pl_ratio']}  差额={r['pl_ratio_edge']}"
        )
        print(
            f"策略 胜率{r['strat_win_rate']}% 均盈{r['strat_avg_win_pct']}% "
            f"均亏{r['strat_avg_loss_pct']}% 利润因子{r['strat_profit_factor']}"
        )
        print(
            f"持有 胜率{r['hold_win_rate']}% 均盈{r['hold_avg_win_pct']}% "
            f"均亏{r['hold_avg_loss_pct']}% 利润因子{r['hold_profit_factor']}"
        )
        print(t[["buy_date", "sell_date", "strat_ret_pct", "hold_ret_pct"]].tail(8).to_string(index=False))
    summary = pd.DataFrame(rows)
    trades_all = pd.concat(trade_frames, ignore_index=True)
    summary.to_csv(OUT / "pinned_summary.csv", index=False, encoding="utf-8-sig")
    trades_all.to_csv(OUT / "pinned_trades.csv", index=False, encoding="utf-8-sig")
    return summary


def run_universe() -> None:
    univ_path = (
        Path(__file__).resolve().parent / "f1_prot_give_scan" / "universe_hs300_zz500_1000.csv"
    )
    if not univ_path.exists():
        # fallback merge
        a = Path(__file__).resolve().parent / "f1_prot_give_scan" / "universe.csv"
        b = Path(__file__).resolve().parent / "f1_prot_give_scan" / "universe_hs300.csv"
        parts = []
        if a.exists():
            parts.append(pd.read_csv(a, dtype={"code": str}))
        if b.exists():
            parts.append(pd.read_csv(b, dtype={"code": str}))
        raw = pd.concat(parts, ignore_index=True)
        raw["code"] = raw["code"].str.zfill(6)
        univ = (
            raw.groupby(["code", "name", "symbol"], as_index=False)["index"]
            .agg(lambda s: "+".join(sorted(set(map(str, s)))))
            .sort_values("code")
            .reset_index(drop=True)
        )
    else:
        univ = pd.read_csv(univ_path, dtype={"code": str})
        univ["code"] = univ["code"].str.zfill(6)

    payloads = [
        {
            "code": r["code"],
            "name": r["name"],
            "symbol": r["symbol"],
            "index": r["index"],
            "thresholds": THRESHOLDS,
        }
        for _, r in univ.iterrows()
    ]
    print(f"\n扫描宇宙 {len(payloads)} 只 × {len(THRESHOLDS)} 阈值…")
    detail: list[dict] = []
    bests: list[dict] = []
    with ProcessPoolExecutor(max_workers=SIM_WORKERS) as ex:
        futs = [ex.submit(_worker, p) for p in payloads]
        for i, fut in enumerate(as_completed(futs), 1):
            out = fut.result()
            detail.extend(out["detail"])
            if out["best"] is not None:
                bests.append(out["best"])
            if i % 100 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}")

    det = pd.DataFrame(detail)
    det.to_csv(OUT / "universe_detail.csv", index=False, encoding="utf-8-sig")
    best = pd.DataFrame(bests)
    if best.empty:
        print("无有效最优结果")
        return
    best = best.sort_values("strat_pl_ratio", ascending=False).reset_index(drop=True)
    best.to_csv(OUT / "universe_best.csv", index=False, encoding="utf-8-sig")
    top30 = best.head(30).copy()
    top30.to_csv(OUT / "universe_top30_strat_pl_ratio.csv", index=False, encoding="utf-8-sig")

    print("\n========== Top30 策略盈亏比 ==========")
    cols = [
        "code",
        "name",
        "index",
        "thr_pct",
        "n_trades",
        "strat_pl_ratio",
        "hold_pl_ratio",
        "pl_ratio_edge",
        "strat_win_rate",
        "hold_win_rate",
        "strat_sum_pct",
        "hold_sum_pct",
    ]
    print(top30[cols].to_string(index=False))

    meta = {
        "start": START,
        "end": END,
        "min_trades": MIN_TRADES,
        "thresholds": list(THRESHOLDS),
        "n_universe": int(len(univ)),
        "n_best": int(len(best)),
        "definition": {
            "strat": "本笔买→卖净收益%",
            "hold": "上笔卖收盘→本笔卖收盘%",
            "pl_ratio": "均盈%/|均亏%|",
            "rank": "每票最优阈值按 strat_pl_ratio",
        },
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # report
    lines = [
        "# 因子1 盈亏比全量统计（配对口径）",
        "",
        "- 策略 = 本笔买→卖净收益；持有 = 上笔卖收盘→本笔卖收盘（首笔用窗首收）",
        "- 盈亏比 = 平均盈利% / |平均亏损%|",
        f"- 区间 {START} → {END}；闭环≥{MIN_TRADES}；宇宙每票试 ±2/2.5/3% 取策略盈亏比最大",
        "",
        "## 天通 / 凯盛",
        "",
    ]
    pin = pd.read_csv(OUT / "pinned_summary.csv")
    lines.append("| 标的 | 阈值% | 闭环 | 策略盈亏比 | 持有盈亏比 | 差额 | 策略胜率% | 持有胜率% |")
    lines.append("|------|-------|------|------------|------------|------|-----------|-----------|")
    for _, r in pin.iterrows():
        lines.append(
            f"| {r['name']} | {r['thr_pct']} | {r['n_trades']} | {r['strat_pl_ratio']} | "
            f"{r['hold_pl_ratio']} | {r['pl_ratio_edge']} | {r['strat_win_rate']} | {r['hold_win_rate']} |"
        )
    lines += ["", "## 宇宙 Top30（策略盈亏比）", ""]
    lines.append(
        "| 代码 | 名称 | 指数 | 阈值% | 闭环 | 策略盈亏比 | 持有盈亏比 | 差额 |"
    )
    lines.append("|------|------|------|-------|------|------------|------------|------|")
    for _, r in top30.iterrows():
        lines.append(
            f"| {r['code']} | {r['name']} | {r['index']} | {r['thr_pct']} | {r['n_trades']} | "
            f"{r['strat_pl_ratio']} | {r['hold_pl_ratio']} | {r['pl_ratio_edge']} |"
        )
    lines += ["", "仅供研究参考，不构成投资建议。", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("先算天通 / 凯盛…")
    run_pinned()
    run_universe()
    print(f"\n产物: {OUT}")


if __name__ == "__main__":
    main()
