"""凯盛 + 天通：分档止盈网格，找两票都相对合适的参数。

骨架：起点 15%/20%；之后每 +5%；每档减初始仓固定比例；余仓止损全清。
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

from strategy import KAICHENG, BacktestConfig, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

_CACHE = _MYQUAN / "data_cache"
TIANTONG = BacktestConfig(
    symbol="sh600330",
    symbol_name="天通股份",
    em_symbol="600330",
    threshold_pct=0.025,
    start_date="20200101",
    daily_cache=_CACHE / "sh600330_daily_qfq.parquet",
)


def _levels(start: float, step: float, n: int) -> tuple[float, ...]:
    return tuple(round(start + i * step, 4) for i in range(n))


def _run_one(cfg: BacktestConfig) -> dict:
    result, _ = run_open_break(cfg, show_report=False, verbose=False)
    m = result.metrics_df
    ret = metric(m, "total_return_pct")
    pnl = metric(m, "total_pnl")
    dd = metric(m, "max_drawdown_pct")
    sharpe = metric(m, "sharpe_ratio")
    win = metric(m, "win_rate")
    score = ret - 0.35 * abs(dd) + 40.0 * (sharpe if sharpe == sharpe else 0.0)
    return {
        "累计收益%": ret,
        "总盈亏": pnl,
        "最大回撤%": dd,
        "夏普": sharpe,
        "胜率%": win,
        "综合分": score,
    }


def _grid(base: BacktestConfig) -> list[dict]:
    starts = (0.15, 0.20)
    reduces = (0.10, 0.15, 0.20, 0.25, 0.30)
    n_levels_list = (1, 2, 3, 4, 5, 6)
    step = 0.05
    rows: list[dict] = []

    print(f"  基准仅止损 · {base.symbol_name}")
    st0 = _run_one(base)
    st0.update(
        {
            "起点%": 0.0,
            "档数": 0,
            "每档减仓%": 0.0,
            "止盈档": "-",
            "方案": "仅止损",
        }
    )
    rows.append(st0)
    base_ret = float(st0["累计收益%"])

    combos = list(itertools.product(starts, reduces, n_levels_list))
    for i, (start, reduce, n) in enumerate(combos, 1):
        if reduce * n > 0.90 + 1e-12:
            continue
        levels = _levels(start, step, n)
        cfg = replace(base, take_profit_levels=levels, take_profit_reduce=reduce)
        lv_txt = "/".join(f"{x*100:.0f}" for x in levels)
        print(
            f"  [{i}/{len(combos)}] {base.symbol_name} "
            f"起点{start*100:.0f}% 减{reduce*100:.0f}% ×{n} ({lv_txt})",
            flush=True,
        )
        try:
            st = _run_one(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"    失败: {e}")
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
    df["相对仅止损收益差"] = df["累计收益%"] - base_ret
    return df


def main() -> None:
    kc_base = replace(KAICHENG, start_date="20200101")
    tt_base = replace(TIANTONG, start_date="20200101")

    print("===== 凯盛科技 =====")
    df_kc = _grid(kc_base)
    df_kc.insert(0, "标的", "凯盛科技")
    print("\n===== 天通股份 =====")
    df_tt = _grid(tt_base)
    df_tt.insert(0, "标的", "天通股份")

    out_dir = Path(__file__).resolve().parent
    df_all = pd.concat([df_kc, df_tt], ignore_index=True)
    df_all.to_csv(out_dir / "optimize_tp_kaicheng_tiantong_all.csv", index=False, encoding="utf-8-sig")

    # 按方案对齐两票
    keys = ["方案", "起点%", "每档减仓%", "档数", "止盈档"]
    a = df_kc[keys + ["累计收益%", "相对仅止损收益差", "最大回撤%", "夏普", "胜率%", "综合分"]].rename(
        columns=lambda c: c if c in keys else f"凯盛_{c}"
    )
    b = df_tt[keys + ["累计收益%", "相对仅止损收益差", "最大回撤%", "夏普", "胜率%", "综合分"]].rename(
        columns=lambda c: c if c in keys else f"天通_{c}"
    )
    m = a.merge(b, on=keys, how="inner")

    # 联合目标：两票相对仅止损的收益差取更差一侧（maximin）；再看平均差、平均综合分
    m["最差相对差"] = m[["凯盛_相对仅止损收益差", "天通_相对仅止损收益差"]].min(axis=1)
    m["平均相对差"] = m[["凯盛_相对仅止损收益差", "天通_相对仅止损收益差"]].mean(axis=1)
    m["平均综合分"] = m[["凯盛_综合分", "天通_综合分"]].mean(axis=1)
    m["平均收益%"] = m[["凯盛_累计收益%", "天通_累计收益%"]].mean(axis=1)

    m.to_csv(out_dir / "optimize_tp_kaicheng_tiantong_joint.csv", index=False, encoding="utf-8-sig")

    def _show(title: str, df: pd.DataFrame, n: int = 8) -> None:
        cols = [
            "方案",
            "凯盛_累计收益%",
            "凯盛_相对仅止损收益差",
            "天通_累计收益%",
            "天通_相对仅止损收益差",
            "最差相对差",
            "平均相对差",
            "凯盛_夏普",
            "天通_夏普",
        ]
        print(f"\n========== {title} ==========")
        print(df[cols].head(n).to_string(index=False))

    print("\n========== 各票基准（仅止损）==========")
    for name, df in (("凯盛", df_kc), ("天通", df_tt)):
        r = df[df["方案"] == "仅止损"].iloc[0]
        print(
            f"{name}: 收益 {r['累计收益%']:.2f}% | 回撤 {r['最大回撤%']:.2f}% | "
            f"夏普 {r['夏普']:.4f} | 胜率 {r['胜率%']:.2f}%"
        )

    _show("联合 Top（最差相对差↓伤害最小，兼顾两票）", m.sort_values("最差相对差", ascending=False))
    _show("联合 Top（平均相对差）", m.sort_values("平均相对差", ascending=False))
    _show("联合 Top（平均综合分）", m.sort_values("平均综合分", ascending=False))

    # 天通单独 Top
    print("\n========== 天通单独 Top10 收益 ==========")
    cols_tt = ["方案", "累计收益%", "相对仅止损收益差", "最大回撤%", "夏普", "胜率%"]
    print(df_tt.sort_values("累计收益%", ascending=False)[cols_tt].head(10).to_string(index=False))

    best = m.sort_values(
        ["最差相对差", "平均相对差", "平均综合分"], ascending=False
    ).iloc[0]
    print("\n========== 两票共用建议 ==========")
    print(f"方案: {best['方案']}")
    print(
        f"凯盛: 收益 {best['凯盛_累计收益%']:.2f}% "
        f"({best['凯盛_相对仅止损收益差']:+.2f}) 夏普 {best['凯盛_夏普']:.4f}"
    )
    print(
        f"天通: 收益 {best['天通_累计收益%']:.2f}% "
        f"({best['天通_相对仅止损收益差']:+.2f}) 夏普 {best['天通_夏普']:.4f}"
    )
    print(
        f"最差相对差 {best['最差相对差']:+.2f} | 平均相对差 {best['平均相对差']:+.2f}"
    )
    if float(best["最差相对差"]) < -1e-9 and best["方案"] != "仅止损":
        print("说明: 两票上止盈均未跑赢仅止损；上式为「伤害最小」的共用止盈。")
    elif best["方案"] == "仅止损":
        print("说明: 联合最优仍是仅止损（两票都不必加止盈）。")


if __name__ == "__main__":
    main()
