"""Rapid financial health scoring using the unified fina_cache.parquet.

Scores every stock on 5 dimensions against its industry peers, outputs a
ranked CSV. Designed as the first filter before deep-diving into individual
stocks.

Usage:
    python scripts/analyze_quick.py --all              # score all stocks → CSV
    python scripts/analyze_quick.py --stock 600267.SH  # single stock detail
    python scripts/analyze_quick.py --top 20            # strongest 20
    python scripts/analyze_quick.py --worst 20          # weakest 20
    python scripts/analyze_quick.py --industry 医药生物  # filter by L1 industry
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_cache import (
    FINA_CACHE, INDU_CACHE,
    _load_parquet, get_industry_map, get_industry_peers,
    compute_ratios_df, RATIO_LABELS,
)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

# ── Scoring dimensions ──

class Dimension:
    def __init__(self, key: str, ratio_name: str, label: str, weight: float,
                 higher_better: bool, desc: str):
        self.key = key
        self.ratio_name = ratio_name
        self.label = label
        self.weight = weight
        self.higher_better = higher_better
        self.desc = desc

DIMENSIONS = [
    Dimension("profitability", "roe",      "盈利能力",   0.30, True,  "ROE — 股东资本回报率"),
    Dimension("growth",      "yoy_np",    "成长性",     0.25, True,  "归母净利润同比增速"),
    Dimension("scale",       "revenue",   "规模体量",   0.15, True,  "营业收入 — 市场地位"),
    Dimension("efficiency",  "net_margin","盈利效率",   0.15, True,  "净利率 — 收入转化利润能力"),
    Dimension("stability",   "cfo_to_np", "现金流质量", 0.15, True,  "经营现金流/净利润"),
]

# For growth dimension, we compute YoY from the data
def _compute_np_yoy(df: pd.DataFrame) -> pd.Series:
    """Compute q-on-q YoY net profit growth for each stock's latest 2 quarters."""
    results = {}
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("quarter")
        if len(grp) >= 2 and "is_n_income_attr_p" in grp.columns:
            curr = grp["is_n_income_attr_p"].iloc[-1]
            # Find same quarter last year
            latest_q = grp["quarter"].iloc[-1]
            try:
                year = int(latest_q[:4])
                qnum = int(latest_q[5])
                prev_q = f"{year - 1}q{qnum}"
            except (ValueError, IndexError):
                prev_q = None
            prev = grp[grp["quarter"] == prev_q]["is_n_income_attr_p"]
            if not prev.empty:
                prev_v = prev.iloc[0]
                if pd.notna(curr) and pd.notna(prev_v) and float(prev_v) != 0:
                    results[sym] = (float(curr) / float(prev_v) - 1) * 100
    return pd.Series(results)


def _sigmoid(z: float) -> float:
    clamped = max(-6, min(6, z))
    return 100 / (1 + np.exp(-1.5 * clamped))


def score_stock(row: pd.Series, industry_medians: dict, n_peers: int) -> dict:
    dims = {}
    weighted_sum = 0.0

    for d in DIMENSIONS:
        if d.key == "growth":
            val = row.get("_yoy_np")
            med = industry_medians.get("_yoy_np")
        elif d.key == "scale":
            val = row.get(d.ratio_name)  # raw revenue
            med = industry_medians.get(d.ratio_name)
        else:
            val = row.get(d.ratio_name)  # ratio column
            med = industry_medians.get(d.ratio_name)

        if val is None or pd.isna(val) or med is None or pd.isna(med):
            dims[d.key] = {"value": None, "median": med, "score": None, "z": None}
            weighted_sum += 50 * d.weight  # neutral default
            continue

        # z-score: how many median-absolute-deviations from median
        mad = industry_medians.get(f"_mad_{d.ratio_name}", abs(med * 0.02))
        z = (float(val) - float(med)) / float(max(mad, 1e-6))
        if not d.higher_better:
            z = -z
        score = _sigmoid(z)
        dims[d.key] = {"value": float(val), "median": float(med), "score": round(score, 1), "z": round(float(z), 2)}
        weighted_sum += score * d.weight

    composite = round(weighted_sum, 1)
    light = "🟢" if composite >= 65 else ("🟡" if composite >= 40 else "🔴")
    return {"composite": composite, "light": light, "dims": dims}


def build_scores_df() -> pd.DataFrame:
    """Score all stocks in the cache, return ranked DataFrame."""
    df = _load_parquet(FINA_CACHE)
    indu = _load_parquet(INDU_CACHE)
    if df.empty:
        print("缓存为空。请先构建数据缓存：", file=sys.stderr)
        print("  python scripts/build_cache.py --universe 000300.SH --quarters 8", file=sys.stderr)
        print("  （需要 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD 环境变量）", file=sys.stderr)
        return pd.DataFrame()

    df = compute_ratios_df(df)
    ind_map = get_industry_map(indu)
    df["l1_name"] = df["symbol"].map(lambda s: ind_map.get(s, {}).get("l1_name", "未知"))

    # Compute YoY growth
    yoy = _compute_np_yoy(df)
    df["_yoy_np"] = df["symbol"].map(yoy)

    # Latest quarter with enough stocks (>=50% of max coverage)
    quarter_counts = df["quarter"].value_counts()
    max_coverage = quarter_counts.max()
    valid_quarters = quarter_counts[quarter_counts >= max_coverage * 0.5].index.tolist()
    latest_q = max(valid_quarters)
    latest = df[df["quarter"] == latest_q].copy()
    print(f"[info] scoring {len(latest)} stocks from {latest_q}", file=sys.stderr)

    # Pre-compute industry stats
    industries = latest["l1_name"].unique()
    ind_stats = {}
    for ind_name in industries:
        peers = latest[latest["l1_name"] == ind_name]
        medians = {}
        for d in DIMENSIONS:
            col = d.ratio_name if d.key != "growth" else "_yoy_np"
            if col in peers.columns:
                vals = peers[col].dropna()
                if len(vals) > 0:
                    median = float(vals.median())
                    mad = float((vals - median).abs().median())
                    medians[col] = median
                    medians[f"_mad_{col}"] = mad if mad > 0 else abs(median * 0.02)
        ind_stats[ind_name] = medians

    # Score
    rows = []
    for _, row in latest.iterrows():
        sym = row["symbol"]
        ind_name = row.get("l1_name", "未知")
        n_peers = max(0, len(get_industry_peers(indu, ind_name)) - 1)
        result = score_stock(row, ind_stats.get(ind_name, {}), n_peers)

        entry = {
            "symbol": sym, "l1_name": ind_name, "quarter": latest_q,
            "composite": result["composite"], "light": result["light"],
            "revenue": row.get("is_revenue"),
        }
        for d in DIMENSIONS:
            ds = result["dims"].get(d.key, {})
            entry[f"{d.key}_score"] = ds.get("score")
            entry[f"{d.key}_z"] = ds.get("z")
            entry[f"{d.key}_val"] = ds.get("value")
            entry[f"{d.key}_med"] = ds.get("median")
        rows.append(entry)

    scores = pd.DataFrame(rows).sort_values("composite", ascending=False).reset_index(drop=True)
    scores["rank"] = range(1, len(scores) + 1)
    return scores


def _print_single(symbol: str):
    scores = build_scores_df()
    if scores.empty:
        return
    row = scores[scores["symbol"] == symbol]
    if row.empty:
        print(f"No data for {symbol}")
        return
    row = row.iloc[0]

    n_peers = 0
    indu = _load_parquet(INDU_CACHE)
    if not indu.empty:
        peers = get_industry_peers(indu, row.get("l1_name", ""))
        n_peers = max(0, len(peers) - 1)

    print(f"\n  {symbol}  ·  {row.get('l1_name', '')}  ({n_peers} 同行)  ·  {row['quarter']}")
    print(f"  综合评分: {row['composite']:.0f}/100  {row['light']}\n")
    print(f"  {'维度':<12} {'本公司':>14} {'行业中位':>14} {'Z-Score':>8} {'评分':>6}  {'':10}")
    print(f"  {'─' * 70}")
    for d in DIMENSIONS:
        val = row.get(f"{d.key}_val")
        med = row.get(f"{d.key}_med")
        z = row.get(f"{d.key}_z")
        s = row.get(f"{d.key}_score")

        fmt_v = f"{val:.1f}%" if val is not None and d.key != "scale" and d.key != "stability" else (
            f"{val:,.1f}" if val is not None and d.key == "scale" else (
                f"{val:.2f}" if val is not None else "N/A"
            )
        )
        fmt_med = f"{med:.1f}%" if med is not None and d.key != "scale" and d.key != "stability" else (
            f"{med:,.1f}" if med is not None and d.key == "scale" else (
                f"{med:.2f}" if med is not None else "—"
            )
        )
        z_str = f"{z:+.1f}" if z is not None else "—"
        s_str = f"{s:.0f}" if s is not None else "—"
        bar = "█" * max(0, int((s or 0) / 10)) + "░" * max(0, 10 - int((s or 0) / 10)) if s is not None else ""

        print(f"  {d.label:<12} {fmt_v:>14} {fmt_med:>14} {z_str:>8} {s_str:>6}  {bar}")

    # Red flags
    print(f"\n  ── 风险提示 ──")
    flags = [f"  ⚠️ {d.label}评分偏低 ({row.get(f'{d.key}_score', 0):.0f}/100)" for d in DIMENSIONS
             if row.get(f"{d.key}_score") is not None and row[f"{d.key}_score"] < 30]
    if not flags:
        print(f"  ✅ 五项指标均无明显风险信号")
    else:
        for f in flags:
            print(f)
    print()


def _print_ranking(subset: pd.DataFrame):
    print(f"\n  {'排名':>4} {'代码':<12} {'行业':<12} {'评分':>6} {'ROE':>8} {'净利率':>8} {'现金流/NP':>8}")
    print(f"  {'─' * 65}")
    for _, row in subset.iterrows():
        roe = f"{row.get('profitability_val', 0):.1f}%" if pd.notna(row.get('profitability_val')) else "N/A"
        nm = f"{row.get('efficiency_val', 0):.1f}%" if pd.notna(row.get('efficiency_val')) else "N/A"
        cf = f"{row.get('stability_val', 0):.2f}" if pd.notna(row.get('stability_val')) else "N/A"
        print(f"  {row.get('rank',''):>4} {row['symbol']:<12} {row.get('l1_name',''):<12} "
              f"{row['composite']:>5.0f} {row['light']} {roe:>8} {nm:>8} {cf:>8}")


def main() -> int:
    p = argparse.ArgumentParser(description="Rapid financial health scoring")
    p.add_argument("--stock", default=None)
    p.add_argument("--top", type=int, default=0)
    p.add_argument("--worst", type=int, default=0)
    p.add_argument("--industry", default=None)
    p.add_argument("--all", action="store_true", help="Score all and save CSV")
    args = p.parse_args()

    if args.stock:
        _print_single(args.stock)
        return 0

    scores = build_scores_df()
    if scores.empty:
        return 1

    if args.industry:
        scores = scores[scores["l1_name"] == args.industry]

    # Summaries
    red = (scores["composite"] < 40).sum()
    yellow = ((scores["composite"] >= 40) & (scores["composite"] < 65)).sum()
    green = (scores["composite"] >= 65).sum()
    print(f"\n  🟢 {green}  🟡 {yellow}  🔴 {red}  (共 {len(scores)} 只)  "
          f"均值 {scores['composite'].mean():.1f}  中位 {scores['composite'].median():.1f}", file=sys.stderr)

    if args.top:
        _print_ranking(scores.head(args.top))
    if args.worst:
        _print_ranking(scores.tail(args.worst).sort_values("composite"))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"health_scores_{scores['quarter'].iloc[0] if 'quarter' in scores.columns else 'latest'}.csv"
    scores.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[ok] {csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
