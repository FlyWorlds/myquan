"""中证500∪1000（≈中证1500）因子1 防护/让利扫描。

口径对齐天通分析：
  · 因子1：开盘±2.5%（宇宙默认），阴/小阳后可买，禁双阳，仅止损
  · 区间：2025-01-02 → 最新缓存日
  · 防护比例 = 下跌月几何(策略−持有) / |持有亏损|
  · 让利比例 = 上涨月几何(持有−策略) / 持有盈利
  · 筛选：防护/让利 ≥ 1.3；下跌月≥3 且 上涨月≥3

  python backtest/scan_f1_prot_give_zz.py
"""

from __future__ import annotations

import io
import json
import logging
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import simulate_open_break  # noqa: E402
from backtest.universe_zz500_1000 import (  # noqa: E402
    CACHE_DIR,
    CSINDEX_CONS_URL,
    _to_symbol,
)
from strategy.data import fetch_daily  # noqa: E402

OUT = Path(__file__).resolve().parent / "f1_prot_give_scan"
START = "2025-01-02"
WARM = "2024-01-01"
END = "20260827"
THR = 0.025
CASH = 100_000.0
MIN_DOWN = 3
MIN_UP = 3
RATIO_MIN = 1.3
FETCH_WORKERS = 16
SIM_WORKERS = 8
MIN_BARS = 80

INDEXES = (
    ("000905", "中证500"),
    ("000852", "中证1000"),
)


def _load_index(code: str, label: str) -> pd.DataFrame:
    url = CSINDEX_CONS_URL.format(code=code)
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))
    code_col = next(
        c for c in df.columns if "Constituent Code" in str(c) or "成份券代码" in str(c)
    )
    name_col = next(
        c
        for c in df.columns
        if ("Constituent Name" in str(c) or "成份券名称" in str(c)) and "Eng" not in str(c)
    )
    rows = []
    for _, row in df.iterrows():
        c = str(row[code_col]).zfill(6)
        name = str(row[name_col]).strip()
        if "ST" in name.upper():
            continue
        rows.append(
            {
                "code": c,
                "name": name,
                "symbol": _to_symbol(c),
                "index": label,
            }
        )
    return pd.DataFrame(rows)


def load_universe() -> pd.DataFrame:
    parts = [_load_index(c, lab) for c, lab in INDEXES]
    raw = pd.concat(parts, ignore_index=True)
    # 合并指数标签
    g = (
        raw.groupby(["code", "name", "symbol"], as_index=False)["index"]
        .agg(lambda s: "+".join(sorted(set(s))))
        .sort_values("code")
        .reset_index(drop=True)
    )
    return g


def _geo(vals: list[float]) -> float:
    acc = 1.0
    for v in vals:
        acc *= 1.0 + float(v) / 100.0
    return acc - 1.0


def _month_rets_from_series(dates: pd.DatetimeIndex, values: np.ndarray) -> dict[str, float]:
    s = pd.Series(values, index=pd.DatetimeIndex(dates).normalize())
    s = s[~s.index.duplicated(keep="last")].sort_index()
    months = s.index.to_period("M")
    out: dict[str, float] = {}
    for p in sorted(set(months)):
        part = s[months == p]
        if part.empty:
            continue
        end_v = float(part.iloc[-1])
        prev = s[months < p]
        base = float(prev.iloc[-1]) if not prev.empty else float(part.iloc[0])
        if base <= 0:
            continue
        out[str(p)] = (end_v / base - 1.0) * 100.0
    return out


def _analyze_one(payload: dict) -> dict:
    symbol = payload["symbol"]
    name = payload["name"]
    code = payload["code"]
    index = payload["index"]
    path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    try:
        if not path.exists():
            return {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "ok": 0,
                "error": "no_cache",
            }
        df = pd.read_parquet(path)
        if df is None or df.empty:
            return {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "ok": 0,
                "error": "empty",
            }
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        if getattr(d["date"].dt, "tz", None) is not None:
            d["date"] = d["date"].dt.tz_localize(None)
        d["date"] = d["date"].dt.normalize()
        for col in ("open", "high", "low", "close"):
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
        start = pd.Timestamp(START)
        end = pd.Timestamp(str(END)[:4] + "-" + str(END)[4:6] + "-" + str(END)[6:8])
        # 回测窗
        bt = d[(d["date"] >= start) & (d["date"] <= end)].reset_index(drop=True)
        if len(bt) < MIN_BARS:
            return {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "ok": 0,
                "error": f"bars={len(bt)}",
            }

        o = bt["open"].to_numpy(float)
        h = bt["high"].to_numpy(float)
        l = bt["low"].to_numpy(float)
        c = bt["close"].to_numpy(float)
        eq, _ = simulate_open_break(o, h, l, c, thr=THR, initial_cash=CASH)
        hold_nav = CASH * c / float(c[0])
        dates = pd.DatetimeIndex(bt["date"])

        hold_m = _month_rets_from_series(dates, hold_nav)
        f1_m = _month_rets_from_series(dates, eq)
        months = sorted(set(hold_m) & set(f1_m))
        down_h, down_f, up_h, up_f = [], [], [], []
        for m in months:
            hv, fv = hold_m[m], f1_m[m]
            if hv < 0:
                down_h.append(hv)
                down_f.append(fv)
            else:
                up_h.append(hv)
                up_f.append(fv)

        n_down, n_up = len(down_h), len(up_h)
        if n_down < MIN_DOWN or n_up < MIN_UP:
            return {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "ok": 0,
                "error": f"months_down={n_down}_up={n_up}",
                "n_down": n_down,
                "n_up": n_up,
            }

        g_hd, g_fd = _geo(down_h), _geo(down_f)
        g_hu, g_fu = _geo(up_h), _geo(up_f)
        if abs(g_hd) < 1e-9:
            return {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "ok": 0,
                "error": "hold_down_geo~0",
            }
        prot = (g_fd - g_hd) / abs(g_hd)
        # 让利：上涨月策略少赚；若策略反而多赚，让利记 0，比例记为大数
        if g_hu <= 1e-12:
            return {
                "code": code,
                "name": name,
                "symbol": symbol,
                "index": index,
                "ok": 0,
                "error": "hold_up_geo~0",
            }
        give = (g_hu - g_fu) / g_hu
        if give <= 1e-6:
            # 上涨月未让利（甚至超额）→ 比值视为通过且很大
            ratio = 99.0 if prot > 0 else 0.0
            give_out = max(give, 0.0)
        else:
            ratio = prot / give
            give_out = give

        f1_tot = float(eq[-1] / eq[0] - 1.0) * 100.0
        bh_tot = float(c[-1] / c[0] - 1.0) * 100.0
        peak = np.maximum.accumulate(eq)
        mdd = float((1.0 - eq / peak).max()) * 100.0
        bh_peak = np.maximum.accumulate(c)
        bh_mdd = float((1.0 - c / bh_peak).max()) * 100.0

        return {
            "code": code,
            "name": name,
            "symbol": symbol,
            "index": index,
            "ok": 1,
            "error": "",
            "prot": round(prot, 4),
            "give": round(give_out, 4),
            "ratio": round(ratio, 4),
            "n_down": n_down,
            "n_up": n_up,
            "down_hold_geo_pct": round(g_hd * 100, 2),
            "down_f1_geo_pct": round(g_fd * 100, 2),
            "up_hold_geo_pct": round(g_hu * 100, 2),
            "up_f1_geo_pct": round(g_fu * 100, 2),
            "f1_ret_pct": round(f1_tot, 2),
            "bh_ret_pct": round(bh_tot, 2),
            "excess_pct": round(f1_tot - bh_tot, 2),
            "f1_mdd_pct": round(mdd, 2),
            "bh_mdd_pct": round(bh_mdd, 2),
            "n_bars": int(len(bt)),
            "end": str(dates[-1].date()),
            "pass_1_3": int(ratio >= RATIO_MIN and prot > 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "code": code,
            "name": name,
            "symbol": symbol,
            "index": index,
            "ok": 0,
            "error": str(exc)[:200],
        }


def _fetch_one(row: dict) -> tuple[str, bool, str]:
    symbol = row["symbol"]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    try:
        fetch_daily(
            symbol,
            start=WARM.replace("-", ""),
            end=END,
            cache_path=path,
            force_refresh=False,
        )
        return symbol, path.exists(), ""
    except Exception as exc:  # noqa: BLE001
        return symbol, False, str(exc)[:120]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("加载中证500/1000成分…")
    univ = load_universe()
    univ.to_csv(OUT / "universe.csv", index=False, encoding="utf-8-sig")
    print(f"宇宙 {len(univ)} 只（500∪1000 去重，剔名称含ST）")

    # 拉取日线
    rows = univ.to_dict("records")
    need = [r for r in rows if not (CACHE_DIR / f"{r['symbol']}_daily_qfq.parquet").exists()]
    print(f"需拉取/补齐日线: {len(need)} / {len(rows)}")
    ok_fetch = 0
    if need:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
            futs = [ex.submit(_fetch_one, r) for r in need]
            for i, fut in enumerate(as_completed(futs), 1):
                sym, ok, err = fut.result()
                if ok:
                    ok_fetch += 1
                if i % 50 == 0 or i == len(futs):
                    print(f"  fetch {i}/{len(futs)} ok_cum≈{ok_fetch}")
    print(f"拉取完成 +{ok_fetch}，缓存目录 {CACHE_DIR}")

    # 模拟
    print("扫描因子1 防护/让利…")
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=SIM_WORKERS) as ex:
        futs = [ex.submit(_analyze_one, r) for r in rows]
        for i, fut in enumerate(as_completed(futs), 1):
            results.append(fut.result())
            if i % 100 == 0 or i == len(futs):
                print(f"  sim {i}/{len(futs)}")

    res = pd.DataFrame(results)
    res.to_csv(OUT / "all_results.csv", index=False, encoding="utf-8-sig")
    ok = res[res["ok"] == 1].copy()
    hits = ok[(ok["pass_1_3"] == 1)].sort_values("ratio", ascending=False)
    hits.to_csv(OUT / "hits_ratio_ge_1_3.csv", index=False, encoding="utf-8-sig")

    # 也要求超额>0 的更干净子集
    hits2 = hits[hits["excess_pct"] > 0].copy()
    hits2.to_csv(OUT / "hits_ratio_ge_1_3_excess_pos.csv", index=False, encoding="utf-8-sig")

    meta = {
        "universe": "CSI500∪CSI1000 (≈中证1500中小盘并集)",
        "n_universe": int(len(univ)),
        "n_ok": int(len(ok)),
        "n_fail": int((res["ok"] == 0).sum()),
        "thr": THR,
        "start": START,
        "end": END,
        "min_down_months": MIN_DOWN,
        "min_up_months": MIN_UP,
        "ratio_min": RATIO_MIN,
        "n_hits": int(len(hits)),
        "n_hits_excess_pos": int(len(hits2)),
        "elapsed_sec": round(time.time() - t0, 1),
        "note": "当前成分幸存者偏差；轻量 simulate_open_break，非 akquant 引擎。",
    }
    (OUT / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n========== 汇总 ==========")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\n达标 ratio≥{RATIO_MIN}: {len(hits)} 只")
    if len(hits):
        cols = [
            "code",
            "name",
            "index",
            "prot",
            "give",
            "ratio",
            "excess_pct",
            "f1_ret_pct",
            "bh_ret_pct",
            "n_down",
            "n_up",
        ]
        print(hits[cols].head(40).to_string(index=False))
        if len(hits) > 40:
            print(f"… 其余 {len(hits)-40} 只见 hits_ratio_ge_1_3.csv")
    print(f"\n产物目录: {OUT}")


if __name__ == "__main__":
    main()
