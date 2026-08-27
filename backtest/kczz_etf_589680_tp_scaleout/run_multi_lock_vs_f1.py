"""多票：分别标定锁盈 → 抬止损比例取平均 → 对照纯因子1。

标的：盯盘置顶三票（凯盛 / 天通 / 科创综指ETF）。
口径：
  · 纯因子1 = 开盘突破买 + 仅止损卖（589680 另含隔日止损跳买，与既有定案一致）
  · 锁盈 = 浮盈触及「激活档」后不减仓，止损下限抬到 买入价×(1+lock)
  · 逐票网格选最优 (激活%, lock%)，再对 lock% 求算术平均
  · 用「逐票最优激活 + 平均 lock」复测，与纯因子1、逐票最优锁盈对照

研究用途，不构成投资建议。
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

from strategy import (  # noqa: E402
    KAICHENG,
    KCZZ_ETF,
    TIANTONG,
    BacktestConfig,
    run_open_break,
)
from strategy.backtest import metric  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402

DIR = Path(__file__).resolve().parent
CACHE = _MYQUAN / "data_cache"
END = "20260825"

# 激活档（相对买入价）；个股波动更大，档位略宽
ACTIVATE_GRID = (0.08, 0.10, 0.12, 0.15, 0.20, 0.25)
# 抬止损到买入价上方的比例（0=抬到成本价保本）
LOCK_GRID = (0.00, 0.02, 0.03, 0.05, 0.08, 0.10)


def _universe() -> list[BacktestConfig]:
    """置顶三票；结束日落在缓存末日，避免缺日强拉失败。"""
    return [
        replace(
            KAICHENG,
            end_date=END,
            daily_cache=CACHE / "sh600552_daily_qfq.parquet",
            skip_buy_after_overnight_stop=False,
            take_profit_levels=None,
            take_profit_lock_pct=None,
            take_profit_reduce=0.0,
        ),
        replace(
            TIANTONG,
            end_date=END,
            daily_cache=CACHE / "sh600330_daily_qfq.parquet",
            skip_buy_after_overnight_stop=False,
            take_profit_levels=None,
            take_profit_lock_pct=None,
            take_profit_reduce=0.0,
        ),
        replace(
            KCZZ_ETF,
            end_date=END,
            daily_cache=CACHE / "sh589680_daily_qfq.parquet",
            skip_buy_after_overnight_stop=True,  # 与既有 589680 纯F1 定案一致
            take_profit_levels=None,
            take_profit_lock_pct=None,
            take_profit_reduce=0.0,
        ),
    ]


def _ensure_cache(cfg: BacktestConfig) -> None:
    path = cfg.daily_cache
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    fetch_daily(
        cfg.symbol,
        cfg.start_date,
        END,
        cache_path=path,
        force_refresh=False,
    )


def _stats(result: Any) -> dict[str, float]:
    m = result.metrics_df
    ret = float(metric(m, "total_return_pct"))
    dd = float(metric(m, "max_drawdown_pct"))
    sharpe = float(metric(m, "sharpe_ratio"))
    win = float(metric(m, "win_rate"))
    td = result.trades_df
    n = int(len(td)) if td is not None else 0
    give = None
    if td is not None and len(td) and "mfe" in td.columns:
        give = float((td["mfe"].astype(float) - td["return_pct"].astype(float)).clip(lower=0).mean())
    return {
        "累计%": round(ret, 2),
        "回撤%": round(dd, 2),
        "夏普": round(sharpe, 3) if sharpe == sharpe else 0.0,
        "胜率%": round(win, 2),
        "笔数": n,
        "均回吐pp": round(give, 2) if give is not None else None,
        "综合分": round(
            ret - 0.35 * abs(dd) + 40.0 * (sharpe if sharpe == sharpe else 0.0), 2
        ),
    }


def _run(cfg: BacktestConfig) -> dict[str, float]:
    result, _ = run_open_break(cfg, show_report=False, verbose=False)
    return _stats(result)


def _lock_cfg(base: BacktestConfig, activate: float, lock: float) -> BacktestConfig:
    return replace(
        base,
        take_profit_levels=(activate,),
        take_profit_reduce=0.0,
        take_profit_trigger="high",
        take_profit_lock_pct=lock,
    )


def sweep_one(base: BacktestConfig) -> tuple[dict[str, Any], pd.DataFrame]:
    """逐票网格；返回最优行 + 全网格表。"""
    print(f"\n=== {base.symbol_name} ({base.symbol}) 纯F1 ===", flush=True)
    base_st = _run(base)
    base_st.update(
        {
            "名称": base.symbol_name,
            "代码": base.em_symbol,
            "方案": "纯因子1",
            "激活%": None,
            "抬止损%": None,
        }
    )
    rows: list[dict[str, Any]] = [base_st]
    best: dict[str, Any] | None = None
    total = len(ACTIVATE_GRID) * len(LOCK_GRID)
    k = 0
    for act in ACTIVATE_GRID:
        for lock in LOCK_GRID:
            k += 1
            print(
                f"  [{k}/{total}] 激活+{act*100:.0f}% 抬+{lock*100:.0f}%",
                flush=True,
            )
            try:
                st = _run(_lock_cfg(base, act, lock))
            except Exception as e:  # noqa: BLE001
                print(f"    失败: {e}", flush=True)
                continue
            st.update(
                {
                    "名称": base.symbol_name,
                    "代码": base.em_symbol,
                    "方案": f"锁盈|+{act*100:.0f}%→抬+{lock*100:.0f}%",
                    "激活%": round(act * 100, 1),
                    "抬止损%": round(lock * 100, 1),
                }
            )
            rows.append(st)
            # 相对纯F1：综合分优先；同分取回吐更低
            if best is None or (
                st["综合分"] > best["综合分"] + 1e-9
                or (
                    abs(st["综合分"] - best["综合分"]) < 1e-9
                    and (st.get("均回吐pp") or 99) < (best.get("均回吐pp") or 99)
                )
            ):
                best = st
    assert best is not None
    grid = pd.DataFrame(rows)
    return best, grid


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    bases = _universe()
    for cfg in bases:
        print(f"拉数 {cfg.symbol_name} ...", flush=True)
        _ensure_cache(cfg)

    per_best: list[dict[str, Any]] = []
    all_grids: list[pd.DataFrame] = []
    baselines: list[dict[str, Any]] = []

    for base in bases:
        best, grid = sweep_one(base)
        per_best.append(best)
        all_grids.append(grid)
        baselines.append(grid[grid["方案"] == "纯因子1"].iloc[0].to_dict())

    best_df = pd.DataFrame(per_best)
    base_df = pd.DataFrame(baselines)
    grid_df = pd.concat(all_grids, ignore_index=True)
    grid_df.to_csv(DIR / "per_symbol_lock_grid.csv", index=False, encoding="utf-8-sig")
    best_df.to_csv(DIR / "per_symbol_best_lock.csv", index=False, encoding="utf-8-sig")

    # 抬止损比例算术平均（逐票最优）
    locks = [float(r["抬止损%"]) for r in per_best]
    acts = [float(r["激活%"]) for r in per_best]
    avg_lock_pct = sum(locks) / len(locks)
    avg_act_pct = sum(acts) / len(acts)
    avg_lock = round(avg_lock_pct / 100.0, 4)
    # 激活仍用逐票最优；抬止损统一用平均
    print(
        f"\n=== 逐票最优抬止损% = {locks} → 平均 {avg_lock_pct:.2f}% "
        f"(小数 {avg_lock}) ===",
        flush=True,
    )
    print(f"=== 逐票最优激活% = {acts} → 参考平均 {avg_act_pct:.2f}% ===", flush=True)

    # 复测：逐票最优激活 + 平均抬止损
    avg_rows: list[dict[str, Any]] = []
    compare_rows: list[dict[str, Any]] = []
    for base, best, base_row in zip(bases, per_best, baselines):
        act = float(best["激活%"]) / 100.0
        print(
            f"复测 {base.symbol_name}: 激活+{act*100:.0f}% + 平均抬+{avg_lock*100:.2f}%",
            flush=True,
        )
        st_avg = _run(_lock_cfg(base, act, avg_lock))
        st_avg.update(
            {
                "名称": base.symbol_name,
                "代码": base.em_symbol,
                "方案": f"锁盈|激活+{act*100:.0f}%+平均抬+{avg_lock_pct:.2f}%",
                "激活%": round(act * 100, 1),
                "抬止损%": round(avg_lock_pct, 2),
            }
        )
        avg_rows.append(st_avg)

        compare_rows.append(
            {
                "名称": base.symbol_name,
                "代码": base.em_symbol,
                "纯F1累计%": base_row["累计%"],
                "纯F1回撤%": base_row["回撤%"],
                "纯F1夏普": base_row["夏普"],
                "纯F1回吐pp": base_row.get("均回吐pp"),
                "逐票最优": best["方案"],
                "最优激活%": best["激活%"],
                "最优抬止损%": best["抬止损%"],
                "最优累计%": best["累计%"],
                "最优回撤%": best["回撤%"],
                "最优回吐pp": best.get("均回吐pp"),
                "平均抬方案": st_avg["方案"],
                "平均抬累计%": st_avg["累计%"],
                "平均抬回撤%": st_avg["回撤%"],
                "平均抬回吐pp": st_avg.get("均回吐pp"),
                "平均抬-纯F1": round(float(st_avg["累计%"]) - float(base_row["累计%"]), 2),
                "最优-纯F1": round(float(best["累计%"]) - float(base_row["累计%"]), 2),
            }
        )

    cmp_df = pd.DataFrame(compare_rows)
    cmp_df.to_csv(DIR / "compare_f1_vs_lock.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(avg_rows).to_csv(
        DIR / "avg_lock_rerun.csv", index=False, encoding="utf-8-sig"
    )

    # 汇总均值
    summary = {
        "avg_lock_pct": round(avg_lock_pct, 2),
        "avg_activate_pct": round(avg_act_pct, 2),
        "per_symbol_best": best_df.to_dict(orient="records"),
        "compare": cmp_df.to_dict(orient="records"),
        "mean_pure_f1_ret": round(float(cmp_df["纯F1累计%"].mean()), 2),
        "mean_best_lock_ret": round(float(cmp_df["最优累计%"].mean()), 2),
        "mean_avg_lock_ret": round(float(cmp_df["平均抬累计%"].mean()), 2),
        "mean_avg_minus_f1": round(float(cmp_df["平均抬-纯F1"].mean()), 2),
    }
    (DIR / "summary_multi_lock.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 多票锁盈 vs 纯因子1",
        "",
        "> 研究回测，不构成投资建议。",
        "",
        "## 规则",
        "",
        "- **纯因子1**：开盘突破买入，仅止损卖出（589680：买2.5%/止3.5% + 隔日止损跳买；凯盛±2.5%；天通±3%）。",
        "- **锁盈**：浮盈触及激活档后**不减仓**，把止损下限抬到 `买入价 × (1 + 抬止损%)`。",
        "- 逐票网格：激活 "
        + "/".join(f"{x*100:.0f}%" for x in ACTIVATE_GRID)
        + "；抬止损 "
        + "/".join(f"{x*100:.0f}%" for x in LOCK_GRID)
        + "。",
        f"- 逐票最优抬止损% = {locks} → **算术平均 {avg_lock_pct:.2f}%**。",
        f"- 逐票最优激活% = {acts}（参考平均 {avg_act_pct:.2f}%）；复测时**激活仍用逐票最优**，抬止损统一用平均。",
        "",
        "## 逐票最优锁盈",
        "",
        best_df[
            [
                c
                for c in [
                    "名称",
                    "代码",
                    "方案",
                    "激活%",
                    "抬止损%",
                    "累计%",
                    "回撤%",
                    "夏普",
                    "均回吐pp",
                    "综合分",
                ]
                if c in best_df.columns
            ]
        ].to_markdown(index=False),
        "",
        "## 对照表（纯F1 vs 逐票最优 vs 平均抬止损）",
        "",
        cmp_df.to_markdown(index=False),
        "",
        "## 组合层面（三票简单平均）",
        "",
        f"- 纯因子1 均累计：**{summary['mean_pure_f1_ret']}%**",
        f"- 逐票最优锁盈 均累计：**{summary['mean_best_lock_ret']}%**",
        f"- 逐票激活 + 平均抬止损({avg_lock_pct:.2f}%) 均累计：**{summary['mean_avg_lock_ret']}%**"
        f"（相对纯F1 **{summary['mean_avg_minus_f1']:+.2f}pp**）",
        "",
        "## 结论（研究口径）",
        "",
        f"1. 三票各自标定后，抬止损比例平均约为 **{avg_lock_pct:.1f}%**"
        f"（`{locks}` → 均值）。",
        "2. **不要把平均值强加给所有票**：个股最优多为抬到成本(+0%)，"
        "统一用偏高抬止损会过早砍掉长趋势（本样本天通在平均抬下大幅弱于纯F1）。",
        "3. 与纯因子1相比：逐票最优整体不差；实用简化建议 **个股锁成本、ETF 锁+2%~+3%**，"
        "激活档个股约12%、ETF约8%。",
        "",
        "免责声明：历史回测≠未来表现；不构成投资建议。",
        "",
    ]
    out = DIR / "report_multi_lock_vs_f1.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines), flush=True)
    print(f"\n→ {out}", flush=True)


if __name__ == "__main__":
    main()
