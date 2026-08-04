"""OpenBreak 因子1 T+1：回撤仓位阈值 (dd_half_pct / dd_full_pct) 网格搜索优化。

默认仅优化 凯盛科技(KAICHENG)；可用 --all 兼跑建滔积层板(HK1888)：
  1. 每个标的仅一次性拉取日线（+ 分钟线用于 945 proxy），构建 gap945 map，
     后续每组参数只重跑回测本身，不重复下载数据。
  2. 网格：dd_half_pct ∈ {0.10,0.12,...,0.40}（step 0.02），
     dd_full_pct ∈ {0.05,0.08,...,dd_half-0.02}（step ≈0.03），
     并强制 0 < dd_full_pct < dd_half_pct。
  3. 始终包含 baseline（enable_dd_sizing=False）与当前默认 20/15。
  4. 若粗网格最优点落在搜索边界，自动在其附近 ±0.03（step 0.01）做局部细化。
  5. 排序：主排序按夏普；同分按 calmar → 累计收益 → 回撤（越小越好）tie-break。
     另外分别列出 Top5(按 calmar) / Top5(按累计收益)。
  6. 结果落盘 huice/optimize_dd_{symbol_name}.csv；
     并为 最优(夏普) 与 最优(calmar，若与夏普不同) 生成对比 HTML 报告。

t0=False（T+1），start_date=20200101。
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.disable(logging.CRITICAL)

from strategy.backtest import metric  # noqa: E402
from strategy.config import HK1888, KAICHENG, BacktestConfig  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.runner import build_gap_map, load_minute, run_open_break_backtest  # noqa: E402

ROOT = Path(__file__).resolve().parent

METRIC_KEYS = (
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "calmar_ratio",
    "end_market_value",
    "closed_trade_count",
)

SHOW_COLS = [
    "tag",
    "dd_half_pct",
    "dd_full_pct",
    "sharpe_ratio",
    "calmar_ratio",
    "total_return_pct",
    "max_drawdown_pct",
    "end_market_value",
    "closed_trade_count",
]

HALF_LO, HALF_HI, HALF_STEP = 0.10, 0.40, 0.02
FULL_LO, FULL_STEP, FULL_MARGIN = 0.05, 0.03, 0.02
PRINT_EVERY = 20


def build_grid(
    half_lo: float = HALF_LO,
    half_hi: float = HALF_HI,
    half_step: float = HALF_STEP,
    full_lo: float = FULL_LO,
    full_step: float = FULL_STEP,
    full_margin: float = FULL_MARGIN,
) -> list[tuple[float, float]]:
    """生成 (dd_half, dd_full) 网格，约束 0 < dd_full < dd_half。"""
    combos: list[tuple[float, float]] = []
    half = half_lo
    while half <= half_hi + 1e-9:
        full_max = round(half - full_margin, 4)
        full = full_lo
        while full <= full_max + 1e-9:
            combos.append((round(half, 4), round(full, 4)))
            full = round(full + full_step, 4)
        half = round(half + half_step, 4)
    return combos


def _metrics(result) -> dict[str, float]:
    m = result.metrics_df
    return {k: (metric(m, k) if k in m.index else float("nan")) for k in METRIC_KEYS}


def _run_plan(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
    gap_map: dict,
    plan: list[tuple[str, bool, float, float]],
    *,
    label: str,
) -> pd.DataFrame:
    rows: list[dict] = []
    t_start = time.time()
    for i, (tag, dd_on, h, f) in enumerate(plan, 1):
        c = replace(cfg, enable_dd_sizing=dd_on, dd_half_pct=h, dd_full_pct=f)
        result = run_open_break_backtest(c, daily, gap_map=gap_map)
        met = _metrics(result)
        rows.append(
            {
                "tag": tag,
                "enable_dd_sizing": dd_on,
                "dd_half_pct": h,
                "dd_full_pct": f,
                **met,
            }
        )
        if i % PRINT_EVERY == 0 or i == len(plan):
            elapsed = time.time() - t_start
            print(
                f"  [{label}] [{i}/{len(plan)}] 完成 "
                f"({elapsed:.1f}s, {elapsed / i:.2f}s/run)",
                flush=True,
            )
    return pd.DataFrame(rows)


def rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        by=["sharpe_ratio", "calmar_ratio", "total_return_pct", "max_drawdown_pct"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)


def _on_boundary(h: float, f: float) -> bool:
    return (
        abs(h - HALF_LO) < 1e-6
        or abs(h - HALF_HI) < 1e-6
        or abs(f - FULL_LO) < 1e-6
        or abs(f - (h - FULL_MARGIN)) < 1e-6
    )


def refine_grid(h: float, f: float, *, step: float = 0.01, span: float = 0.03) -> list[tuple[float, float]]:
    """在 (h, f) 附近 ±span（step）做局部细化，仍需满足 0<full<half。"""
    combos: set[tuple[float, float]] = set()
    n = round(span / step)
    for dh in range(-n, n + 1):
        for df_ in range(-n, n + 1):
            hh = round(h + dh * step, 4)
            ff = round(f + df_ * step, 4)
            if hh <= 0 or ff <= 0 or ff >= hh:
                continue
            combos.add((hh, ff))
    return sorted(combos)


def optimize_symbol(preset: BacktestConfig) -> dict:
    cfg = replace(
        preset,
        start_date="20200101",
        t0=False,
        report_path=None,
    )
    print(f"\n===== {cfg.symbol_name} ({cfg.symbol}) 数据加载 =====", flush=True)

    t0 = time.time()
    daily = fetch_daily(cfg.symbol, cfg.start_date, cfg.end_date)
    print(
        f"  日线: {len(daily)} 行，区间 {daily['date'].iloc[0]} → "
        f"{daily['date'].iloc[-1]} ({time.time() - t0:.1f}s)",
        flush=True,
    )

    minute = pd.DataFrame()
    if cfg.enable_gap945:
        t0 = time.time()
        try:
            minute = load_minute(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  分钟线拉取失败（将用 proxy 近似）: {exc}", flush=True)
            minute = pd.DataFrame()
        print(f"  分钟线: {len(minute)} 行 ({time.time() - t0:.1f}s)", flush=True)

    t0 = time.time()
    gap_map = build_gap_map(cfg, daily, minute)
    print(f"  gap945 map: {len(gap_map)} 天 ({time.time() - t0:.1f}s)", flush=True)

    grid = build_grid()
    plan: list[tuple[str, bool, float, float]] = [
        ("baseline_无回撤仓位", False, 0.20, 0.15),
        ("默认20-15", True, 0.20, 0.15),
    ]
    for h, f in grid:
        plan.append((f"h{h:.2f}_f{f:.2f}", True, h, f))
    print(f"  粗网格共 {len(plan)} 组参数（含baseline+默认20/15）", flush=True)

    coarse_df = _run_plan(cfg, daily, gap_map, plan, label="粗网格")

    ranked = rank(coarse_df)
    dd_rows = coarse_df[coarse_df["enable_dd_sizing"]]
    best_sharpe_coarse = ranked.iloc[0]
    best_calmar_coarse = dd_rows.sort_values("calmar_ratio", ascending=False).iloc[0]

    refine_candidates: dict[tuple[float, float], None] = {}
    for row in (best_sharpe_coarse, best_calmar_coarse):
        h, f = float(row["dd_half_pct"]), float(row["dd_full_pct"])
        if _on_boundary(h, f):
            for hh, ff in refine_grid(h, f):
                refine_candidates[(hh, ff)] = None

    all_df = coarse_df
    if refine_candidates:
        exist = {
            (round(r.dd_half_pct, 4), round(r.dd_full_pct, 4))
            for r in coarse_df.itertuples()
            if r.enable_dd_sizing
        }
        refine_plan = [
            (f"细化h{h:.2f}_f{f:.2f}", True, h, f)
            for (h, f) in sorted(refine_candidates)
            if (h, f) not in exist
        ]
        if refine_plan:
            print(
                f"  最优点落在网格边界，局部细化 {len(refine_plan)} 组参数 …",
                flush=True,
            )
            refine_df = _run_plan(cfg, daily, gap_map, refine_plan, label="细化")
            all_df = pd.concat([coarse_df, refine_df], ignore_index=True)

    all_df = all_df.drop_duplicates(subset=["enable_dd_sizing", "dd_half_pct", "dd_full_pct"]).reset_index(
        drop=True
    )

    csv_path = ROOT / f"optimize_dd_{cfg.symbol_name}.csv"
    all_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  结果CSV: {csv_path} （共 {len(all_df)} 行）", flush=True)

    final_ranked = rank(all_df)
    dd_rows_final = all_df[all_df["enable_dd_sizing"]]
    best_sharpe = final_ranked.iloc[0]
    best_calmar = dd_rows_final.sort_values("calmar_ratio", ascending=False).iloc[0]
    top5_return = dd_rows_final.sort_values("total_return_pct", ascending=False).head(5)

    baseline = all_df[~all_df["enable_dd_sizing"]].iloc[0]
    default2015 = all_df[
        all_df["enable_dd_sizing"]
        & (all_df["dd_half_pct"].round(2) == 0.20)
        & (all_df["dd_full_pct"].round(2) == 0.15)
    ].iloc[0]

    print(f"\n========== {cfg.symbol_name} Top10（按夏普排序） ==========")
    print(
        final_ranked[SHOW_COLS].head(10).to_string(
            index=False, float_format=lambda x: f"{x:.4f}"
        )
    )
    print(f"\n---- {cfg.symbol_name} Top5（按 Calmar） ----")
    print(
        dd_rows_final.sort_values("calmar_ratio", ascending=False)
        .head(5)[SHOW_COLS]
        .to_string(index=False, float_format=lambda x: f"{x:.4f}")
    )
    print(f"\n---- {cfg.symbol_name} Top5（按累计收益） ----")
    print(top5_return[SHOW_COLS].to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print(f"\n>>> {cfg.symbol_name} 无回撤仓位: "
          f"夏普={baseline['sharpe_ratio']:.4f} calmar={baseline['calmar_ratio']:.4f} "
          f"收益%={baseline['total_return_pct']:.2f} 回撤%={baseline['max_drawdown_pct']:.2f}")
    print(f">>> {cfg.symbol_name} 默认20/15: "
          f"夏普={default2015['sharpe_ratio']:.4f} calmar={default2015['calmar_ratio']:.4f} "
          f"收益%={default2015['total_return_pct']:.2f} 回撤%={default2015['max_drawdown_pct']:.2f}")
    print(f">>> {cfg.symbol_name} 最优(夏普) half={best_sharpe['dd_half_pct']:.2f} "
          f"full={best_sharpe['dd_full_pct']:.2f}: 夏普={best_sharpe['sharpe_ratio']:.4f} "
          f"calmar={best_sharpe['calmar_ratio']:.4f} 收益%={best_sharpe['total_return_pct']:.2f} "
          f"回撤%={best_sharpe['max_drawdown_pct']:.2f}")
    print(f">>> {cfg.symbol_name} 最优(Calmar) half={best_calmar['dd_half_pct']:.2f} "
          f"full={best_calmar['dd_full_pct']:.2f}: 夏普={best_calmar['sharpe_ratio']:.4f} "
          f"calmar={best_calmar['calmar_ratio']:.4f} 收益%={best_calmar['total_return_pct']:.2f} "
          f"回撤%={best_calmar['max_drawdown_pct']:.2f}")

    return {
        "cfg": cfg,
        "daily": daily,
        "gap_map": gap_map,
        "df": all_df,
        "baseline": baseline,
        "default": default2015,
        "best_sharpe": best_sharpe,
        "best_calmar": best_calmar,
        "csv_path": csv_path,
    }


def make_compare_report(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
    gap_map: dict,
    *,
    dd_on: bool,
    dd_half: float,
    dd_full: float,
    tag: str,
) -> tuple[Path, dict]:
    report_path = ROOT / f"{cfg.symbol_name}_因子1_T1_DD优化_{tag}_report.html"
    c = replace(
        cfg,
        enable_dd_sizing=dd_on,
        dd_half_pct=dd_half,
        dd_full_pct=dd_full,
        report_path=report_path,
    )
    result = run_open_break_backtest(c, daily, gap_map=gap_map)
    result.viz.report(
        title=f"{c.symbol_name} {c.report_title_suffix()}",
        filename=str(report_path),
        show=False,
        market_data=daily,
        plot_symbol=c.symbol,
        curve_freq="D",
    )
    m = result.metrics_df
    row = {
        "方案": tag,
        "累计收益%": metric(m, "total_return_pct"),
        "最大回撤%": metric(m, "max_drawdown_pct"),
        "夏普": metric(m, "sharpe_ratio"),
        "Calmar": metric(m, "calmar_ratio"),
        "胜率%": metric(m, "win_rate"),
        "闭环": metric(m, "closed_trade_count"),
        "期末市值": metric(m, "end_market_value"),
        "成交笔数": len(result.executions_df),
    }
    print(f"  报告: {report_path}", flush=True)
    return report_path, row


def final_compare(res: dict) -> list[dict]:
    cfg, daily, gap_map = res["cfg"], res["daily"], res["gap_map"]
    print(f"\n===== {cfg.symbol_name} 最终对比报告 =====", flush=True)

    variants: list[tuple[str, bool, float, float]] = [
        ("无回撤仓位", False, 0.20, 0.15),
        (
            f"最优夏普_{res['best_sharpe']['dd_half_pct']:.2f}-{res['best_sharpe']['dd_full_pct']:.2f}",
            True,
            float(res["best_sharpe"]["dd_half_pct"]),
            float(res["best_sharpe"]["dd_full_pct"]),
        ),
    ]
    bs_key = (
        round(float(res["best_sharpe"]["dd_half_pct"]), 4),
        round(float(res["best_sharpe"]["dd_full_pct"]), 4),
    )
    bc_key = (
        round(float(res["best_calmar"]["dd_half_pct"]), 4),
        round(float(res["best_calmar"]["dd_full_pct"]), 4),
    )
    if bc_key != bs_key:
        variants.append(
            (
                f"最优Calmar_{res['best_calmar']['dd_half_pct']:.2f}-{res['best_calmar']['dd_full_pct']:.2f}",
                True,
                float(res["best_calmar"]["dd_half_pct"]),
                float(res["best_calmar"]["dd_full_pct"]),
            )
        )

    rows: list[dict] = []
    for tag, dd_on, h, f in variants:
        _, row = make_compare_report(cfg, daily, gap_map, dd_on=dd_on, dd_half=h, dd_full=f, tag=tag)
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"\n========== {cfg.symbol_name} 最终对比表 ==========")
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    return rows


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="回撤仓位阈值网格搜索（默认仅凯盛科技）")
    parser.add_argument(
        "--all",
        action="store_true",
        help="同时优化建滔积层板(HK1888)",
    )
    args = parser.parse_args()
    presets = (KAICHENG, HK1888) if args.all else (KAICHENG,)

    all_results: dict[str, dict] = {}
    for preset in presets:
        res = optimize_symbol(preset)
        final_compare(res)
        all_results[preset.symbol_name] = res

    print("\n\n================= 汇总：最优阈值 =================")
    for name, res in all_results.items():
        bs, bc = res["best_sharpe"], res["best_calmar"]
        same = (
            round(float(bs["dd_half_pct"]), 4) == round(float(bc["dd_half_pct"]), 4)
            and round(float(bs["dd_full_pct"]), 4) == round(float(bc["dd_full_pct"]), 4)
        )
        print(
            f"{name}: 最优(夏普) half={bs['dd_half_pct']:.2f} full={bs['dd_full_pct']:.2f} "
            f"(夏普={bs['sharpe_ratio']:.4f}, calmar={bs['calmar_ratio']:.4f}, "
            f"收益%={bs['total_return_pct']:.2f}, 回撤%={bs['max_drawdown_pct']:.2f})"
        )
        if not same:
            print(
                f"{name}: 最优(Calmar) half={bc['dd_half_pct']:.2f} full={bc['dd_full_pct']:.2f} "
                f"(夏普={bc['sharpe_ratio']:.4f}, calmar={bc['calmar_ratio']:.4f}, "
                f"收益%={bc['total_return_pct']:.2f}, 回撤%={bc['max_drawdown_pct']:.2f})"
            )
        print(f"  CSV: {res['csv_path']}")


if __name__ == "__main__":
    main()
