"""滚动年夏普选股：过去252日策略夏普 → 年末/季末 TopK → 下期交易。

  python strategy/run_factor13_roll_sharpe.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_SCRIPT = str(Path(__file__).resolve().parent)
if _SCRIPT in sys.path:
    sys.path.remove(_SCRIPT)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import load_daily, simulate_open_break  # noqa: E402
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402
from strategy.run_factor13_top10_quarterly import (  # noqa: E402
    OOS_END,
    OOS_START,
    THR,
    backtest_symbol,
    equal_weight,
    nav_stats,
)

OUT = _MYQUAN / "backtest" / "factor13_roll_sharpe"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
WORKERS = 8
WIN = 252
SEEDS = {"sh600330", "sh600552"}


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _sharpe(eq: np.ndarray) -> float:
    if len(eq) < 60 or eq[0] <= 0:
        return float("nan")
    rets = np.diff(eq) / eq[:-1]
    rets = rets[np.isfinite(rets)]
    if len(rets) < 40:
        return float("nan")
    sd = float(np.std(rets, ddof=1))
    if sd < 1e-12:
        return 0.0
    return float(np.mean(rets) / sd * math.sqrt(242))


def _mdd(eq: np.ndarray) -> float:
    peak = np.maximum.accumulate(eq)
    return float(-(eq / peak - 1).min()) * 100


def process(task: dict) -> list[dict]:
    """只在年末/季末计算过去252日滚动夏普，避免逐日全量。"""
    symbol = task["symbol"]
    name = task["name"]
    daily = load_daily(symbol)
    if daily is None or len(daily) < WIN + 40:
        return []
    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    eq, _ = simulate_open_break(o, h, l, c, thr=THR, initial_cash=100_000.0)
    df = pd.DataFrame({"date": dates, "eq": eq})
    df["year"] = df["date"].dt.year
    df["q"] = df["date"].dt.to_period("Q")
    rows: list[dict] = []

    def add_snap(i: int, kind: str, period: str) -> None:
        if i < WIN - 1:
            return
        seg = eq[i - WIN + 1 : i + 1]
        if seg[0] <= 0:
            return
        segn = seg / seg[0]
        sh = _sharpe(segn)
        if not np.isfinite(sh):
            return
        d = dates[i]
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "kind": kind,
                "period": period,
                "date": str(d.date()),
                "roll_sharpe": float(sh),
                "roll_mdd": float(_mdd(segn)),
                "roll_ret": float((segn[-1] / segn[0] - 1) * 100),
            }
        )

    for _, g in df.groupby("year"):
        add_snap(int(g.index[-1]), "year", str(int(g["year"].iloc[-1])))
    for q, g in df.groupby("q"):
        add_snap(int(g.index[-1]), "quarter", str(q))
    return rows


def build_snapshots(force: bool = False) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "roll_sharpe_snapshots.parquet"
    if cache.exists() and not force:
        print(f"加载 {cache}")
        return pd.read_parquet(cache)

    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    name_map = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    name_map.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    tasks = []
    for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet")):
        sym = fp.name.replace("_daily_qfq.parquet", "")
        if _is_mainboard(sym):
            tasks.append({"symbol": sym, "name": name_map.get(sym, "")})

    print(f"计算滚动年夏普 {len(tasks)}")
    snap_rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                snap_rows.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
                print("err", exc)
            if done % 100 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} ({time.time() - t0:.0f}s) snaps={len(snap_rows)}")
    snap = pd.DataFrame(snap_rows)
    # 同年/季可能因年末=季末重复，去重
    snap = snap.drop_duplicates(subset=["symbol", "kind", "period"], keep="last")
    snap.to_parquet(cache, index=False)
    print(f"snapshots {snap.shape} → {cache}")
    return snap


def pick(
    period_df: pd.DataFrame,
    k: int,
    sh_lo: float = 0.8,
    sh_hi: float = 2.5,
    mdd_lo: float | None = None,
    mdd_hi: float | None = None,
) -> pd.DataFrame:
    g = period_df.dropna(subset=["roll_sharpe"]).copy()
    g = g[(g["roll_sharpe"] >= sh_lo) & (g["roll_sharpe"] <= sh_hi)]
    if mdd_lo is not None:
        g = g[g["roll_mdd"] >= mdd_lo]
    if mdd_hi is not None:
        g = g[g["roll_mdd"] <= mdd_hi]
    return g.sort_values("roll_sharpe", ascending=False).head(k)


def run_port(symbols: list[str], start: str, end: str, name_map: dict) -> tuple[dict, float, list]:
    navs = {}
    rows = []
    for sym in symbols:
        res = backtest_symbol(sym, name_map.get(sym, sym), start, end)
        if not res.get("ok"):
            continue
        navs[sym] = res["nav"]
        rows.append(res)
    st = nav_stats(equal_weight(navs)) if navs else {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    med = float(np.median([r["ret"] for r in rows])) if rows else float("nan")
    return st, med, rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    snap = build_snapshots(force=False)
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    name_map = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    name_map.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})

    cfgs = [
        dict(name="rollSh_Top5_[0.8,2.5]", k=5, sh_lo=0.8, sh_hi=2.5),
        dict(name="rollSh_Top8_[0.8,2.5]", k=8, sh_lo=0.8, sh_hi=2.5),
        dict(name="rollSh_Top5_[1.0,2.2]", k=5, sh_lo=1.0, sh_hi=2.2),
        dict(name="rollSh_Top3_[1.0,2.2]", k=3, sh_lo=1.0, sh_hi=2.2),
        dict(name="rollSh_Top5_[1.0,2.2]_mdd18_35", k=5, sh_lo=1.0, sh_hi=2.2, mdd_lo=18, mdd_hi=35),
        dict(name="rollSh_Top5_[1.2,2.0]", k=5, sh_lo=1.2, sh_hi=2.0),
    ]

    year_wf = []
    print("\n=== 年度：滚动年夏普选股 ===")
    for cfg in cfgs:
        for y in range(2020, 2026):
            sub = snap[(snap["kind"] == "year") & (snap["period"] == str(y))]
            picks = pick(
                sub,
                cfg["k"],
                cfg["sh_lo"],
                cfg["sh_hi"],
                cfg.get("mdd_lo"),
                cfg.get("mdd_hi"),
            )
            start = f"{y + 1}0101"
            end = OOS_END if y + 1 >= 2026 else f"{y + 1}1231"
            if start > OOS_END:
                continue
            st, med, rows = run_port(picks["symbol"].tolist(), start, end, name_map)
            syms = [r["symbol"] for r in rows]
            year_wf.append(
                {
                    **{k: v for k, v in cfg.items() if k != "name"},
                    "name": cfg["name"],
                    "fit": y,
                    "oos": y + 1,
                    "n": len(syms),
                    "ret": st["ret"],
                    "med": med,
                    "mdd": st["mdd"],
                    "sharpe": st["sharpe"],
                    "symbols": ",".join(syms),
                }
            )
            if y == 2025:
                names = "、".join(name_map.get(s, s) for s in syms)
                print(
                    f"{cfg['name']}: N={len(syms)} 等权={st['ret']:+.1f}% "
                    f"中位={med:+.1f}% 回撤={st['mdd']:.1f}% | {names}"
                )

    yw = pd.DataFrame(year_wf)
    yw.to_csv(OUT / "yearly_walkforward.csv", index=False, float_format="%.4f")

    print("\n=== 调参窗均值 vs 盲测2026 ===")
    summary_rows = []
    for name, g in yw.groupby("name"):
        train = g[g["oos"] <= 2025]
        blind = g[g["oos"] == 2026]
        br = float(blind["ret"].iloc[0]) if len(blind) else float("nan")
        bm = float(blind["med"].iloc[0]) if len(blind) else float("nan")
        summary_rows.append(
            {
                "name": name,
                "train_avg_ret": float(train["ret"].mean()),
                "train_avg_med": float(train["med"].mean()),
                "blind_ret": br,
                "blind_med": bm,
                "blind_mdd": float(blind["mdd"].iloc[0]) if len(blind) else float("nan"),
                "blind_n": int(blind["n"].iloc[0]) if len(blind) else 0,
                "blind_symbols": str(blind["symbols"].iloc[0]) if len(blind) else "",
            }
        )
        print(
            f"{name:40s} train均={train['ret'].mean():+6.1f}%  "
            f"盲测={br:+6.1f}% 中位={bm:+6.1f}%"
        )
    pd.DataFrame(summary_rows).to_csv(OUT / "summary.csv", index=False, float_format="%.4f")

    # 季度
    print("\n=== 季度滚动夏普 Top5 [1.0,2.2] ===")
    qrecs = []
    qnavs = []
    for per in sorted(snap[snap["kind"] == "quarter"]["period"].unique()):
        p = pd.Period(per, freq="Q")
        if p.year < 2025:
            continue
        nxt = p + 1
        start = nxt.start_time.strftime("%Y%m%d")
        end = min(nxt.end_time.strftime("%Y%m%d"), OOS_END)
        if start > OOS_END or end < "20260101":
            continue
        sub = snap[(snap["kind"] == "quarter") & (snap["period"] == per)]
        picks = pick(sub, 5, 1.0, 2.2)
        st, med, rows = run_port(picks["symbol"].tolist(), start, end, name_map)
        qrecs.append(
            {
                "select": per,
                "hold": f"{start}-{end}",
                "n": len(rows),
                "ret": st["ret"],
                "med": med,
                "mdd": st["mdd"],
                "symbols": ",".join(r["symbol"] for r in rows),
            }
        )
        print(f"  {per}→{start}-{end} N={len(rows)} 等权={st['ret']:+.1f}% 中位={med:+.1f}%")
        if rows:
            qnavs.append(equal_weight({r["symbol"]: r["nav"] for r in rows}))

    stitched = None
    for qnav in qnavs:
        r = qnav.pct_change().fillna(0.0)
        if stitched is None:
            stitched = (1.0 + r).cumprod()
            stitched.iloc[0] = 1.0
        else:
            base = float(stitched.iloc[-1])
            seg = (1.0 + r).cumprod() * base
            seg = seg[seg.index > stitched.index[-1]]
            stitched = pd.concat([stitched, seg])
    qst = nav_stats(stitched) if stitched is not None else {}
    print(f"季度拼接2026: {qst.get('ret', float('nan')):+.1f}% 回撤{qst.get('mdd', float('nan')):.1f}%")
    pd.DataFrame(qrecs).to_csv(OUT / "quarterly_walkforward.csv", index=False, float_format="%.4f")

    # 种子+卫星
    print("\n=== 对照：种子 + 滚动夏普卫星 ===")
    sub25 = snap[(snap["kind"] == "year") & (snap["period"] == "2025")]
    sat = [
        s
        for s in pick(sub25, 8, 1.0, 2.2)["symbol"].tolist()
        if s not in SEEDS
    ][:3]
    for label, syms in [
        ("仅滚动夏普Top5", pick(sub25, 5, 1.0, 2.2)["symbol"].tolist()),
        ("种子+夏普卫星3", list(SEEDS) + sat),
        ("仅种子", list(SEEDS)),
    ]:
        st, med, rows = run_port(syms, OOS_START, OOS_END, name_map)
        print(f"{label:16s} N={len(rows)} 等权={st['ret']:+.1f}% 中位={med:+.1f}% 回撤={st['mdd']:.1f}%")

    best = max(summary_rows, key=lambda x: x["blind_ret"] if np.isfinite(x["blind_ret"]) else -999)
    rows_html = "".join(
        f"<tr><td>{r['name']}</td><td>{r['blind_n']}</td><td>{r['blind_ret']:.1f}</td>"
        f"<td>{r['blind_med']:.1f}</td><td>{r['blind_mdd']:.1f}</td>"
        f"<td>{r['train_avg_ret']:.1f}</td></tr>"
        for r in sorted(summary_rows, key=lambda x: -x["blind_ret"])
    )
    q_html = "".join(
        f"<tr><td>{r['select']}</td><td>{r['hold']}</td><td>{r['ret']:.1f}</td>"
        f"<td>{r['med']:.1f}</td><td>{r['mdd']:.1f}</td></tr>"
        for r in qrecs
    )
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>
<title>滚动年夏普选股</title>
<style>
body{{font-family:PingFang SC,Helvetica,sans-serif;background:#0f1115;color:#e8eaed;padding:28px}}
.wrap{{max-width:980px;margin:0 auto}}.meta{{color:#9aa3b2}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:14px;margin:14px 0}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
th,td{{padding:7px;border-bottom:1px solid #2a2f3a;text-align:right}}
th:first-child,td:first-child{{text-align:left}} th{{color:#9aa3b2}}
.v{{font-size:1.45rem;font-weight:650;color:#3dd68c}}
.callout{{border-left:3px solid #3d8bfd;padding:10px 14px;background:#171a21}}
</style></head><body><div class="wrap">
<h1>滚动年夏普选股（策略1）</h1>
<p class="meta">过去252日开盘突破净值夏普 → 选股；下一年/下一季交易 · ±2.5% · 非投资建议</p>
<div class="callout"><b>人话：</b>看谁过去一年「做策略1」又稳又赚（夏普高但不极端），下一年继续做它。</div>
<div class="card"><div class="v">2026最佳盲测 {best['blind_ret']:.1f}%</div>
<p class="meta">{best['name']} · 中位 {best['blind_med']:.1f}% · 回撤 {best['blind_mdd']:.1f}%</p></div>
<div class="card"><h3>年度方案 · 2026盲测</h3>
<table><thead><tr><th>方案</th><th>N</th><th>等权%</th><th>中位%</th><th>回撤%</th><th>调参窗均%</th></tr></thead>
<tbody>{rows_html}</tbody></table></div>
<div class="card"><h3>季度滚动 Top5</h3>
<p class="meta">拼接 {qst.get('ret', float('nan')):.1f}% / 回撤 {qst.get('mdd', float('nan')):.1f}%</p>
<table><thead><tr><th>选股季</th><th>持有</th><th>等权%</th><th>中位%</th><th>回撤%</th></tr></thead>
<tbody>{q_html}</tbody></table></div>
</div></body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "meta.json").write_text(
        json.dumps(
            {"best": best, "quarterly": qst, "summary": summary_rows},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n报告 → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
