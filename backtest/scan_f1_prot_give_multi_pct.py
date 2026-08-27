"""因子1 防护/让利 · 多阈值扫描（±2% / ±2.5% / ±3%）。

覆盖：沪深300 ∪ 中证500 ∪ 中证1000（当前成分并集）。
每只票三档阈值同跑，取 ratio 最大且样本合格的一档；再筛 ratio≥1.3。

  python backtest/scan_f1_prot_give_multi_pct.py
"""

from __future__ import annotations

import io
import json
import logging
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from backtest.universe_zz500_1000 import CACHE_DIR, CSINDEX_CONS_URL, _to_symbol  # noqa: E402

OUT = Path(__file__).resolve().parent / "f1_prot_give_scan"
START = "2025-01-02"
END = "20260827"
THRESHOLDS = (0.02, 0.025, 0.03)
CASH = 100_000.0
MIN_DOWN = 3
MIN_UP = 3
RATIO_MIN = 1.3
SIM_WORKERS = 8
MIN_BARS = 80

INDEXES = (
    ("000300", "沪深300"),
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
        rows.append({"code": c, "name": name, "symbol": _to_symbol(c), "index": label})
    return pd.DataFrame(rows)


def load_universe() -> pd.DataFrame:
    parts = [_load_index(c, lab) for c, lab in INDEXES]
    raw = pd.concat(parts, ignore_index=True)
    return (
        raw.groupby(["code", "name", "symbol"], as_index=False)["index"]
        .agg(lambda s: "+".join(sorted(set(s))))
        .sort_values("code")
        .reset_index(drop=True)
    )


def _geo(vals: list[float]) -> float:
    acc = 1.0
    for v in vals:
        acc *= 1.0 + float(v) / 100.0
    return acc - 1.0


def _month_rets(dates: pd.DatetimeIndex, values: np.ndarray) -> dict[str, float]:
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


def _metrics_for_thr(
    dates: pd.DatetimeIndex,
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    thr: float,
) -> dict | None:
    eq, _ = simulate_open_break(o, h, l, c, thr=thr, initial_cash=CASH)
    hold_nav = CASH * c / float(c[0])
    hold_m = _month_rets(dates, hold_nav)
    f1_m = _month_rets(dates, eq)
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
        return None
    g_hd, g_fd = _geo(down_h), _geo(down_f)
    g_hu, g_fu = _geo(up_h), _geo(up_f)
    if abs(g_hd) < 1e-9 or g_hu <= 1e-12:
        return None
    prot = (g_fd - g_hd) / abs(g_hd)
    give = (g_hu - g_fu) / g_hu
    if give <= 1e-6:
        ratio = 99.0 if prot > 0 else 0.0
        give_out = max(give, 0.0)
    else:
        ratio = prot / give
        give_out = give
    f1_tot = float(eq[-1] / eq[0] - 1.0) * 100.0
    bh_tot = float(c[-1] / c[0] - 1.0) * 100.0
    peak = np.maximum.accumulate(eq)
    mdd = float((1.0 - eq / peak).max()) * 100.0
    return {
        "thr_pct": round(thr * 100, 1),
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
        "pass_1_3": int(ratio >= RATIO_MIN and prot > 0),
    }


def _analyze_one(payload: dict) -> list[dict]:
    symbol = payload["symbol"]
    path = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    base = {
        "code": str(payload["code"]).zfill(6),
        "name": payload["name"],
        "symbol": symbol,
        "index": payload["index"],
    }
    if not path.exists():
        return [{**base, "ok": 0, "error": "no_cache", "thr_pct": None}]
    try:
        df = pd.read_parquet(path)
        d = df.copy()
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
            return [{**base, "ok": 0, "error": f"bars={len(bt)}", "thr_pct": None}]
        o = bt["open"].to_numpy(float)
        h = bt["high"].to_numpy(float)
        l = bt["low"].to_numpy(float)
        c = bt["close"].to_numpy(float)
        dates = pd.DatetimeIndex(bt["date"])
        rows = []
        for thr in THRESHOLDS:
            m = _metrics_for_thr(dates, o, h, l, c, thr)
            if m is None:
                rows.append(
                    {
                        **base,
                        "ok": 0,
                        "error": "months_insufficient",
                        "thr_pct": round(thr * 100, 1),
                    }
                )
            else:
                rows.append({**base, "ok": 1, "error": "", **m, "n_bars": int(len(bt))})
        return rows
    except Exception as exc:  # noqa: BLE001
        return [{**base, "ok": 0, "error": str(exc)[:200], "thr_pct": None}]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("加载沪深300+中证500+中证1000…")
    univ = load_universe()
    univ.to_csv(OUT / "universe_hs300_zz500_1000.csv", index=False, encoding="utf-8-sig")
    print(f"并集 {len(univ)} 只")
    print(univ["index"].value_counts().to_string())

    rows = univ.to_dict("records")
    detail: list[dict] = []
    print("多阈值扫描…")
    with ProcessPoolExecutor(max_workers=SIM_WORKERS) as ex:
        futs = [ex.submit(_analyze_one, r) for r in rows]
        for i, fut in enumerate(as_completed(futs), 1):
            detail.extend(fut.result())
            if i % 100 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}")

    det = pd.DataFrame(detail)
    det["code"] = det["code"].astype(str).str.zfill(6)
    det.to_csv(OUT / "multi_pct_detail.csv", index=False, encoding="utf-8-sig")

    ok = det[det["ok"] == 1].copy()
    # 每只票取 ratio 最大的阈值
    best_idx = ok.groupby("code")["ratio"].idxmax()
    best = ok.loc[best_idx].sort_values("ratio", ascending=False).reset_index(drop=True)
    best.to_csv(OUT / "multi_pct_best.csv", index=False, encoding="utf-8-sig")

    hits = best[best["pass_1_3"] == 1].copy()
    hits.to_csv(OUT / "multi_pct_hits_ratio_ge_1_3.csv", index=False, encoding="utf-8-sig")
    clean = hits[(hits["give"] >= 0.05) & (hits["excess_pct"] > 0)].copy()
    clean.to_csv(
        OUT / "multi_pct_hits_ratio_ge_1_3_give_ge5pct.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 分阈值统计
    thr_stats = []
    for thr in THRESHOLDS:
        sub = ok[ok["thr_pct"] == round(thr * 100, 1)]
        h = sub[sub["pass_1_3"] == 1]
        c = h[(h["give"] >= 0.05) & (h["excess_pct"] > 0)]
        thr_stats.append(
            {
                "thr_pct": round(thr * 100, 1),
                "n_ok": int(len(sub)),
                "n_hits": int(len(h)),
                "n_clean": int(len(c)),
                "median_ratio": round(float(sub["ratio"].median()), 3) if len(sub) else None,
            }
        )
    thr_df = pd.DataFrame(thr_stats)
    thr_df.to_csv(OUT / "multi_pct_thr_stats.csv", index=False, encoding="utf-8-sig")

    # 最优阈值分布
    thr_pick = (
        best["thr_pct"].value_counts().rename_axis("thr_pct").reset_index(name="n_best")
    )
    hit_pick = (
        hits["thr_pct"].value_counts().rename_axis("thr_pct").reset_index(name="n_hits_best")
        if len(hits)
        else pd.DataFrame(columns=["thr_pct", "n_hits_best"])
    )

    meta = {
        "universe": "CSI300∪CSI500∪CSI1000",
        "n_universe": int(len(univ)),
        "thresholds": list(THRESHOLDS),
        "n_ok_rows": int(len(ok)),
        "n_best": int(len(best)),
        "n_hits_best": int(len(hits)),
        "n_clean_best": int(len(clean)),
        "thr_stats": thr_stats,
        "best_thr_dist": thr_pick.to_dict("records"),
        "hits_best_thr_dist": hit_pick.to_dict("records"),
        "elapsed_sec": round(time.time() - t0, 1),
        "note": "每票取三档中 ratio 最大者；轻量 simulate；当前成分幸存者偏差。",
    }
    (OUT / "multi_pct_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # report section
    lines = [
        "",
        "---",
        "",
        "# 多阈值调参（±2 / ±2.5 / ±3）",
        "",
        f"- 宇宙并集 {len(univ)} 只；每票三档，取 **ratio 最大** 一档",
        f"- 最优档 ratio≥1.3：**{len(hits)}**；干净（give≥5%且超额>0）：**{len(clean)}**",
        "",
        "## 分阈值命中数（该档本身≥1.3）",
        "",
        "| 阈值% | 有效 | 命中 | 干净 | 中位ratio |",
        "|-------|------|------|------|-----------|",
    ]
    for r in thr_stats:
        lines.append(
            f"| {r['thr_pct']} | {r['n_ok']} | {r['n_hits']} | {r['n_clean']} | {r['median_ratio']} |"
        )
    lines += [
        "",
        "## 干净 Top30（最优阈值）",
        "",
        "| 代码 | 名称 | 指数 | 最优阈值% | 防护 | 让利 | 比值 | 超额% |",
        "|------|------|------|-----------|------|------|------|-------|",
    ]
    cols_show = clean.head(30)
    for _, r in cols_show.iterrows():
        lines.append(
            f"| {r['code']} | {r['name']} | {r['index']} | {r['thr_pct']} | "
            f"{r['prot']:.1%} | {r['give']:.1%} | {r['ratio']:.2f} | {r['excess_pct']:.1f} |"
        )
    # 天通
    tt = best[best["code"] == "600330"]
    if len(tt):
        r = tt.iloc[0]
        lines += [
            "",
            f"- 天通股份最优：±{r['thr_pct']}%  ratio={r['ratio']:.2f}  "
            f"prot={r['prot']:.1%} give={r['give']:.1%} excess={r['excess_pct']:.1f}%",
        ]
    lines += ["", "文件：`multi_pct_hits_ratio_ge_1_3_give_ge5pct.csv`", ""]
    rep = OUT / "report.md"
    text = rep.read_text(encoding="utf-8") if rep.exists() else ""
    if "多阈值调参" not in text:
        rep.write_text(text.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    else:
        # replace from heading
        i = text.find("# 多阈值调参")
        if i >= 0:
            # find previous --- or start
            pre = text[:i].rstrip()
            rep.write_text(pre + "\n" + "\n".join(lines), encoding="utf-8")

    print("\n========== 分阈值 ==========")
    print(thr_df.to_string(index=False))
    print("\n最优档命中阈值分布:")
    print(hit_pick.to_string(index=False) if len(hit_pick) else "(无)")
    print(f"\n达标(最优) {len(hits)}  干净 {len(clean)}")
    if len(clean):
        print(
            clean[
                [
                    "code",
                    "name",
                    "index",
                    "thr_pct",
                    "prot",
                    "give",
                    "ratio",
                    "excess_pct",
                ]
            ]
            .head(25)
            .to_string(index=False)
        )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
