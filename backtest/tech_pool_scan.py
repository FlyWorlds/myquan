"""科技池扫描：半导体 / 半导体设备 / 光通信 / AI服务器硬件（仅沪深主板）。

成分来源：同花顺行业/概念（东财不可用时回退 THS）。
剔除：创业板(300/301)、科创板(688/689)、北交所、ST。
策略1 三段回测 + 胜率/相对盈亏比/超额/回撤 四维打分。

  python3 backtest/tech_pool_scan.py
  python3 backtest/tech_pool_scan.py --cache-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest import ai_s1_s11_periods as s11_mod  # noqa: E402
from backtest.ai_s1_s11_periods import (  # noqa: E402
    FIT_END,
    FIT_START,
    FULL_START,
    MIN_TRADES,
    OOS_START,
    VAL_END,
    VAL_START,
    _fmt,
    _is_bj,
    _is_chinext_or_star,
    _to_symbol,
    build_scored_pool,
    run_one,
)
from strategy.data import fetch_daily  # noqa: E402
from sectors.ths import fetch_ths_board_members  # noqa: E402

OUT_DIR = _MYQUAN / "backtest" / "tech_pool_scan"
CACHE_DIR = _MYQUAN / "data_cache" / "tech_pool"
UNIVERSE_CSV = OUT_DIR / "universe_tech_mainboard.csv"

# 回测模块共用行情目录
s11_mod.CACHE_DIR = CACHE_DIR

# 板块映射（同花顺口径；半导体设备无独立板块，用设备链概念代理）
SECTOR_BOARDS: dict[str, list[tuple[str, str]]] = {
    "半导体": [("行业", "半导体")],
    "半导体设备": [
        ("概念", "光刻机"),
        ("概念", "光刻胶"),
        ("概念", "先进封装"),
    ],
    "光通信": [
        ("概念", "光纤概念"),
        ("概念", "F5G概念"),
        ("概念", "共封装光学(CPO)"),
    ],
    "AI服务器硬件": [
        ("概念", "液冷服务器"),
        ("概念", "数据中心(AIDC)"),
        ("概念", "铜缆高速连接"),
        ("概念", "PCB概念"),
    ],
}

FETCH_WORKERS = 10
RUN_WORKERS = 8


def _today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def fetch_sector_members(kind: str, name: str) -> pd.DataFrame:
    df = fetch_ths_board_members(kind, name, limit=500)
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "code": df["纯代码"].astype(str).str.zfill(6),
            "name": df["名称"].astype(str),
            "board_kind": kind,
            "board_name": name,
        }
    )
    return out


def build_universe() -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for sector, boards in SECTOR_BOARDS.items():
        for kind, name in boards:
            print(f"  拉取 {sector} ← {kind}/{name} …")
            part = fetch_sector_members(kind, name)
            if part.empty:
                print(f"    空：{kind}/{name}")
                continue
            part["sector"] = sector
            rows.append(part)
            print(f"    {len(part)} 只")
    if not rows:
        raise RuntimeError("未拉到任何成分股")
    raw = pd.concat(rows, ignore_index=True)
    # 合并板块标签
    agg = (
        raw.groupby(["code", "name"], as_index=False)
        .agg(
            sectors=("sector", lambda s: "|".join(sorted(set(s)))),
            boards=("board_name", lambda s: "|".join(sorted(set(s)))),
            n_boards=("board_name", "nunique"),
        )
    )
    agg = agg[~agg["name"].str.upper().str.contains("ST", na=False)].copy()
    agg = agg[~agg["code"].map(_is_chinext_or_star)].copy()
    agg = agg[~agg["code"].map(_is_bj)].copy()
    agg["symbol"] = agg["code"].map(_to_symbol)
    agg = agg.dropna(subset=["symbol"]).drop_duplicates("code").reset_index(drop=True)
    return agg


def fetch_one(symbol: str, end: str, *, cache_only: bool = False) -> tuple[str, str]:
    cache = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    if cache.exists():
        return symbol, "ok"
    if cache_only:
        return symbol, "no_cache"
    try:
        df = fetch_daily(symbol, FULL_START, end, cache_path=cache)
        return symbol, "ok" if df is not None and not df.empty else "empty"
    except Exception as e:  # noqa: BLE001
        return symbol, f"{type(e).__name__}: {e}"


def load_daily(symbol: str) -> pd.DataFrame | None:
    p = CACHE_DIR / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if getattr(df["date"].dt, "tz", None) is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    return df


def run_one_cached(row: dict, oos_end: str) -> dict:
    out = run_one(row, oos_end, do_s11=False)
    out["sectors"] = row.get("sectors", "")
    out["boards"] = row.get("boards", "")
    return out


def sector_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """按板块标签拆分汇总（一票多板块则各计一次）。"""
    rows = []
    for sector in SECTOR_BOARDS:
        sub = scored[scored["sectors"].str.contains(sector, na=False)].copy()
        if sub.empty:
            continue
        rows.append(
            {
                "sector": sector,
                "n": len(sub),
                "oos_excess_med": float(sub["oos_s1_excess"].median()),
                "oos_rel_pl_med": float(sub["oos_s1_pl_ratio_vs_bh"].median()),
                "oos_win_med": float(sub["oos_s1_win_rate"].median()),
                "oos_mdd_med": float(sub["oos_s1_mdd"].median()),
                "oos_excess_pos_pct": float((sub["oos_s1_excess"] > 0).mean() * 100),
            }
        )
    return pd.DataFrame(rows)


def build_report(
    univ: pd.DataFrame,
    df: pd.DataFrame,
    scored: pd.DataFrame,
    sec_sum: pd.DataFrame,
    oos_end: str,
    *,
    cache_note: str,
) -> str:
    ok_n = int(df["ok"].sum())
    lines = [
        "# 科技池 · 策略1 扫描（沪深主板，非科创/创业）",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 区间：FIT {FIT_START}–{FIT_END} | VAL {VAL_START}–{VAL_END} | OOS {OOS_START}–{oos_end}",
        f"- 有效回测：{ok_n}/{len(univ)} | 行情：{cache_note}",
        "",
        "## 板块映射（同花顺）",
        "",
        "| 用户板块 | 同花顺来源 |",
        "|---|---|",
    ]
    for sector, boards in SECTOR_BOARDS.items():
        src = "；".join(f"{k}:{n}" for k, n in boards)
        lines.append(f"| {sector} | {src} |")

    lines += [
        "",
        "## 分板块中位（样本外）",
        "",
        "| 板块 | 只数 | 超额%中位 | 相对盈亏比中位 | 胜率%中位 | 回撤%中位 | 超额>0占比 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in sec_sum.iterrows():
        lines.append(
            f"| {r['sector']} | {int(r['n'])} | {_fmt(r['oos_excess_med'])} | "
            f"{_fmt(r['oos_rel_pl_med'])} | {_fmt(r['oos_win_med'], 1)} | "
            f"{_fmt(r['oos_mdd_med'])} | {_fmt(r['oos_excess_pos_pct'], 1)}% |"
        )

    lines += [
        "",
        "## 全池 Top5（稳健分 · 相对盈亏比口径）",
        "",
        "| 名次 | 代码 | 名称 | 板块 | thr% | 稳健分 | OOS分 | 胜率% | 相对盈亏比 | 超额% | 回撤% |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(scored.head(5).itertuples(index=False), 1):
        lines.append(
            f"| {i} | {str(r.code).zfill(6)} | {r.name} | {r.sectors} | "
            f"{_fmt(float(r.thr)*100,1)} | {_fmt(r.score_blend,3)} | {_fmt(r.score_oos,3)} | "
            f"{_fmt(r.oos_s1_win_rate,1)} | {_fmt(r.oos_s1_pl_ratio_vs_bh)} | "
            f"{_fmt(r.oos_s1_excess)} | {_fmt(r.oos_s1_mdd)} |"
        )

    lines += [
        "",
        "## 全池 Top20（样本外超额）",
        "",
        "| 名次 | 代码 | 名称 | 板块 | thr% | OOS超额% | 相对盈亏比 | 胜率% | 回撤% |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    top20 = scored.sort_values("oos_s1_excess", ascending=False).head(20)
    for i, r in enumerate(top20.itertuples(index=False), 1):
        lines.append(
            f"| {i} | {str(r.code).zfill(6)} | {r.name} | {r.sectors} | "
            f"{_fmt(float(r.thr)*100,1)} | {_fmt(r.oos_s1_excess)} | "
            f"{_fmt(r.oos_s1_pl_ratio_vs_bh)} | {_fmt(r.oos_s1_win_rate,1)} | {_fmt(r.oos_s1_mdd)} |"
        )

    lines += [
        "",
        "## 说明",
        "",
        "- 半导体设备：同花顺无独立板块，用光刻机/光刻胶/先进封装概念代理设备链。",
        "- 一票可属多板块；分板块统计有重复计数。",
        "- 当前成分回测历史存在幸存者偏差。",
        "",
        "本报告仅供研究参考，不构成任何投资建议。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-only", action="store_true")
    ap.add_argument("--workers", type=int, default=RUN_WORKERS)
    args = ap.parse_args()

    oos_end = _today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("构建科技池成分 …")
    univ = build_universe()
    univ.to_csv(UNIVERSE_CSV, index=False, encoding="utf-8-sig")
    print(f"主板科技池 {len(univ)} 只 → {UNIVERSE_CSV}")

    print("拉取/缓存日线 …")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futs = {
            pool.submit(fetch_one, str(r.symbol), oos_end, cache_only=args.cache_only): r.symbol
            for r in univ.itertuples(index=False)
        }
        ok_cache = 0
        for i, fut in enumerate(as_completed(futs), 1):
            sym, st = fut.result()
            if st == "ok":
                ok_cache += 1
            if i % 30 == 0 or i == len(futs):
                print(f"  行情 {i}/{len(futs)} cache_ok={ok_cache} {time.time()-t0:.0f}s")

    rows: list[dict] = []
    tasks = univ.to_dict(orient="records")
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(run_one_cached, t, oos_end) for t in tasks]
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            if i % 25 == 0 or i == len(futs):
                ok_n = sum(1 for x in rows if x.get("ok"))
                print(f"  回测 {i}/{len(futs)} ok={ok_n} {time.time()-t1:.0f}s")

    df = pd.DataFrame(rows)
    df["code"] = df["code"].astype(str).str.zfill(6)
    ok = df[df["ok"] == 1].copy()
    scored = build_scored_pool(ok)

    sec_sum = sector_summary(scored) if len(scored) else pd.DataFrame()
    cache_note = "仅本地缓存" if args.cache_only else "联网补齐+缓存"

    df.to_csv(OUT_DIR / "all_metrics.csv", index=False, encoding="utf-8-sig")
    if len(scored):
        scored.to_csv(OUT_DIR / "all_scored.csv", index=False, encoding="utf-8-sig")
        scored.head(5).to_csv(OUT_DIR / "top5_score_blend.csv", index=False, encoding="utf-8-sig")
        sec_sum.to_csv(OUT_DIR / "sector_summary.csv", index=False, encoding="utf-8-sig")

    report = build_report(univ, df, scored, sec_sum, oos_end, cache_note=cache_note)
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
    (OUT_DIR / "run_meta.json").write_text(
        json.dumps(
            {
                "universe_n": len(univ),
                "ok_n": int(ok.shape[0]),
                "oos_end": oos_end,
                "sectors": SECTOR_BOARDS,
                "cache_dir": str(CACHE_DIR),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n" + report)
    print(f"\n写入 {OUT_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
