"""凯盛科技分档止盈参数搜索（2020→今）。

规则骨架：
  · 首次止盈起点：15% 或 20%
  · 之后每 +5% 再减仓一次
  · 每次减「初始仓」固定比例
  · 余仓仍开盘-2.5%止损全清；下次买入全仓
"""

from __future__ import annotations

import itertools
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import KAICHENG, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402

# 降噪：只看汇总
warnings.filterwarnings("ignore")
logging.disable(logging.INFO)


def _levels(start: float, step: float, n: int) -> tuple[float, ...]:
    return tuple(round(start + i * step, 4) for i in range(n))


def _run_one(cfg) -> dict:
    result, _ = run_open_break(cfg, show_report=False, verbose=False)
    m = result.metrics_df
    ret = metric(m, "total_return_pct")
    pnl = metric(m, "total_pnl")
    dd = metric(m, "max_drawdown_pct")
    sharpe = metric(m, "sharpe_ratio")
    closed = metric(m, "closed_trade_count")
    win = metric(m, "win_rate")
    # 简单综合分：收益优先，回撤惩罚，夏普加权
    score = ret - 0.35 * abs(dd) + 40.0 * (sharpe if sharpe == sharpe else 0.0)
    return {
        "累计收益%": ret,
        "总盈亏": pnl,
        "最大回撤%": dd,
        "夏普": sharpe,
        "闭环笔数": closed,
        "胜率%": win,
        "综合分": score,
        "期末权益": 100_000.0 + pnl,
    }


def main() -> None:
    base = replace(KAICHENG, start_date="20200101")
    print("先跑基准：仅止损 …")
    base_stats = _run_one(base)
    base_stats.update(
        {
            "起点%": 0,
            "档数": 0,
            "每档减仓%": 0,
            "止盈档": "-",
            "方案": "仅止损",
        }
    )

    starts = (0.15, 0.20)
    reduces = (0.10, 0.15, 0.20, 0.25, 0.30)
    n_levels_list = (1, 2, 3, 4, 5, 6)
    step = 0.05

    rows: list[dict] = [base_stats]
    combos = list(itertools.product(starts, reduces, n_levels_list))
    print(f"搜索 {len(combos)} 组止盈参数 …")
    for i, (start, reduce, n) in enumerate(combos, 1):
        # 减仓累计不超过 90%（至少留约 10% 给止损）
        if reduce * n > 0.90 + 1e-12:
            continue
        levels = _levels(start, step, n)
        cfg = replace(
            base,
            take_profit_levels=levels,
            take_profit_reduce=reduce,
        )
        lv_txt = "/".join(f"{x*100:.0f}" for x in levels)
        print(
            f"[{i}/{len(combos)}] 起点{start*100:.0f}% 减{reduce*100:.0f}% "
            f"×{n}档 ({lv_txt})",
            flush=True,
        )
        try:
            st = _run_one(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"  失败: {e}")
            continue
        st.update(
            {
                "起点%": start * 100,
                "档数": n,
                "每档减仓%": reduce * 100,
                "止盈档": lv_txt,
                "方案": f"TP{lv_txt}@减{reduce*100:.0f}%",
            }
        )
        rows.append(st)

    df = pd.DataFrame(rows)
    out = Path(__file__).resolve().parent / "optimize_kaicheng_tp.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    base_ret = float(base_stats["累计收益%"])
    df["相对仅止损收益差"] = df["累计收益%"] - base_ret

    # 排名：1) 综合分 2) 纯收益
    by_score = df.sort_values("综合分", ascending=False)
    by_ret = df.sort_values("累计收益%", ascending=False)
    # 不劣于仅止损收益、回撤不明显变差的候选
    decent = df[
        (df["累计收益%"] >= base_ret - 1e-9)
        | (
            (df["累计收益%"] >= base_ret - 50)
            & (df["最大回撤%"].abs() <= abs(base_ret) * 0 + abs(float(base_stats["最大回撤%"])) + 1)
        )
    ]

    print("\n========== 基准：仅止损 ==========")
    print(
        f"收益 {base_ret:.2f}% | 回撤 {base_stats['最大回撤%']:.2f}% | "
        f"夏普 {base_stats['夏普']:.4f} | 胜率 {base_stats['胜率%']:.2f}%"
    )

    print("\n========== Top10（综合分=收益-0.35*|回撤|+40*夏普）==========")
    cols = [
        "方案",
        "起点%",
        "每档减仓%",
        "档数",
        "止盈档",
        "累计收益%",
        "相对仅止损收益差",
        "最大回撤%",
        "夏普",
        "胜率%",
        "综合分",
    ]
    print(by_score[cols].head(10).to_string(index=False))

    print("\n========== Top10（纯累计收益）==========")
    print(by_ret[cols].head(10).to_string(index=False))

    # 推荐：综合分最高，且相对基准说明
    best = by_score.iloc[0]
    best_ret = by_ret.iloc[0]
    print("\n========== 建议 ==========")
    print(
        f"综合最优: {best['方案']} | 收益 {best['累计收益%']:.2f}% "
        f"(相对仅止损 {best['相对仅止损收益差']:+.2f}) | "
        f"回撤 {best['最大回撤%']:.2f}% | 夏普 {best['夏普']:.4f}"
    )
    print(
        f"收益最高: {best_ret['方案']} | 收益 {best_ret['累计收益%']:.2f}% "
        f"(相对仅止损 {best_ret['相对仅止损收益差']:+.2f})"
    )
    # 若有收益≥仅止损的止盈方案
    beat = df[df["方案"] != "仅止损"].sort_values("累计收益%", ascending=False)
    beat = beat[beat["累计收益%"] >= base_ret - 1e-9]
    if beat.empty:
        print("结论: 在该网格内，没有任何分档止盈的累计收益超过「仅止损」。")
        # 给出「伤害最小」的止盈（收益差最小的负值里最好的，或综合分最高的止盈）
        tp_only = df[df["方案"] != "仅止损"].sort_values("累计收益%", ascending=False)
        mild = tp_only.iloc[0]
        print(
            f"伤害最小(收益最高止盈): {mild['方案']} | "
            f"收益 {mild['累计收益%']:.2f}% ({mild['相对仅止损收益差']:+.2f}) | "
            f"回撤 {mild['最大回撤%']:.2f}% | 夏普 {mild['夏普']:.4f} | "
            f"胜率 {mild['胜率%']:.2f}%"
        )
        # 也给一个：夏普更好或回撤更好且收益损失<80pct 的
        alt = tp_only[
            (tp_only["相对仅止损收益差"] > -80)
            & (
                (tp_only["夏普"] >= float(base_stats["夏普"]))
                | (tp_only["最大回撤%"].abs() <= abs(float(base_stats["最大回撤%"])) + 0.5)
            )
        ].sort_values("综合分", ascending=False)
        if not alt.empty:
            a = alt.iloc[0]
            print(
                f"折中候选(损失<80pct且夏普/回撤不差): {a['方案']} | "
                f"收益 {a['累计收益%']:.2f}% ({a['相对仅止损收益差']:+.2f}) | "
                f"回撤 {a['最大回撤%']:.2f}% | 夏普 {a['夏普']:.4f}"
            )
    else:
        b = beat.iloc[0]
        print(
            f"结论: 存在不低于仅止损的止盈: {b['方案']} | 收益 {b['累计收益%']:.2f}%"
        )

    print(f"\n明细已写入: {out}")


if __name__ == "__main__":
    main()
