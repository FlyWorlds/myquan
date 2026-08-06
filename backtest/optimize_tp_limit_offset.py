"""挂单偏移止盈：档位激活后挂「档位+2%」，摸到挂单价才减仓。

网格搜索凯盛+天通（2020→今），相对仅止损找最优。
"""

from __future__ import annotations

import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import KAICHENG, BacktestConfig, run_open_break
from strategy.backtest import metric

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

TIANTONG = BacktestConfig(
    symbol="sh600330",
    symbol_name="天通股份",
    em_symbol="600330",
    threshold_pct=0.025,
    start_date="20200101",
    daily_cache=_MYQUAN / "data_cache" / "sh600330_daily_qfq.parquet",
)

OFFSET = 0.02


def _levels(start: float, step: float, n: int) -> tuple[float, ...]:
    return tuple(round(start + i * step, 4) for i in range(n))


def _stats(result) -> dict:
    m = result.metrics_df
    ret = metric(m, "total_return_pct")
    dd = metric(m, "max_drawdown_pct")
    sharpe = metric(m, "sharpe_ratio")
    return {
        "累计收益%": ret,
        "最大回撤%": dd,
        "夏普": sharpe,
        "胜率%": metric(m, "win_rate"),
        "总盈亏": metric(m, "total_pnl"),
        "综合分": ret - 0.35 * abs(dd) + 40.0 * (sharpe if sharpe == sharpe else 0.0),
    }


def _cfgs() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = [("仅止损", {})]
    # 主网格：挂+2%，减仓比例与起点/档数
    for start in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45):
        for reduce in (0.05, 0.10, 0.15, 0.20):
            for n in (1, 2, 3, 4, 5, 6, 7, 8):
                if reduce * n > 0.90 + 1e-12:
                    continue
                lv = _levels(start, 0.05, n)
                hang = "/".join(f"{(x+OFFSET)*100:.0f}" for x in lv)
                name = (
                    f"档{'/'.join(f'{x*100:.0f}' for x in lv)}"
                    f"→挂{hang}@减{reduce*100:.0f}%"
                )
                out.append(
                    (
                        name,
                        {
                            "take_profit_levels": lv,
                            "take_profit_reduce": reduce,
                            "take_profit_trigger": "high",
                            "take_profit_limit_offset": OFFSET,
                            "take_profit_lock_pct": None,
                        },
                    )
                )
    # 对照：同档无偏移（摸到档位即按档位价减）
    for start, reduce, n in (
        (0.15, 0.10, 3),
        (0.20, 0.10, 1),
        (0.40, 0.10, 3),
        (0.45, 0.10, 2),
    ):
        lv = _levels(start, 0.05, n)
        name = f"对照无偏移|{'/'.join(f'{x*100:.0f}' for x in lv)}@减{reduce*100:.0f}%"
        out.append(
            (
                name,
                {
                    "take_profit_levels": lv,
                    "take_profit_reduce": reduce,
                    "take_profit_trigger": "high",
                    "take_profit_limit_offset": 0.0,
                    "take_profit_lock_pct": None,
                },
            )
        )
    seen: set[str] = set()
    uniq = []
    for name, kw in out:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, kw))
    return uniq


def _run_symbol(base: BacktestConfig, configs: list[tuple[str, dict]]) -> pd.DataFrame:
    rows = []
    print(f"\n===== {base.symbol_name} · {len(configs)} 组 =====")
    for i, (name, kw) in enumerate(configs, 1):
        print(f"  [{i}/{len(configs)}] {name}", flush=True)
        try:
            r, _ = run_open_break(replace(base, **kw), show_report=False, verbose=False)
            st = _stats(r)
        except Exception as e:  # noqa: BLE001
            print(f"    FAIL {e}")
            continue
        st["方案"] = name
        rows.append(st)
    df = pd.DataFrame(rows)
    base_ret = float(df.loc[df["方案"] == "仅止损", "累计收益%"].iloc[0])
    df["相对仅止损"] = df["累计收益%"] - base_ret
    return df


def main() -> None:
    configs = _cfgs()
    print(f"规则: 档位T激活后挂T+2%；high≥挂单价才减初始仓；余仓开盘-2.5%止损")
    print(f"共 {len(configs)} 组")

    df_kc = _run_symbol(replace(KAICHENG, start_date="20200101"), configs)
    df_tt = _run_symbol(replace(TIANTONG, start_date="20200101"), configs)

    out = Path(__file__).resolve().parent
    df_kc.assign(标的="凯盛").to_csv(
        out / "optimize_tp_offset_kaicheng.csv", index=False, encoding="utf-8-sig"
    )
    df_tt.assign(标的="天通").to_csv(
        out / "optimize_tp_offset_tiantong.csv", index=False, encoding="utf-8-sig"
    )

    m = df_kc[["方案", "累计收益%", "相对仅止损", "最大回撤%", "夏普", "胜率%", "综合分"]].rename(
        columns=lambda c: c if c == "方案" else f"凯盛_{c}"
    ).merge(
        df_tt[["方案", "累计收益%", "相对仅止损", "最大回撤%", "夏普", "胜率%", "综合分"]].rename(
            columns=lambda c: c if c == "方案" else f"天通_{c}"
        ),
        on="方案",
        how="inner",
    )
    m["最差相对差"] = m[["凯盛_相对仅止损", "天通_相对仅止损"]].min(axis=1)
    m["平均相对差"] = m[["凯盛_相对仅止损", "天通_相对仅止损"]].mean(axis=1)
    m["两票都更高"] = (m["凯盛_相对仅止损"] > 0) & (m["天通_相对仅止损"] > 0)
    m.to_csv(out / "optimize_tp_offset_joint.csv", index=False, encoding="utf-8-sig")

    def show(title: str, df: pd.DataFrame, n: int = 12) -> None:
        cols = [
            "方案",
            "凯盛_累计收益%",
            "凯盛_相对仅止损",
            "天通_累计收益%",
            "天通_相对仅止损",
            "最差相对差",
            "平均相对差",
        ]
        print(f"\n========== {title} ==========")
        if df.empty:
            print("（无）")
            return
        print(df[cols].head(n).to_string(index=False))

    print("\n========== 基准 ==========")
    for label, df in (("凯盛", df_kc), ("天通", df_tt)):
        r = df[df["方案"] == "仅止损"].iloc[0]
        print(
            f"{label}: {r['累计收益%']:.2f}% | 回撤 {r['最大回撤%']:.2f}% | "
            f"夏普 {r['夏普']:.4f}"
        )

    beat = m[m["两票都更高"]].sort_values(
        ["最差相对差", "平均相对差"], ascending=False
    )
    show("两票都跑赢仅止损", beat)
    show("联合最优(最差相对差)", m.sort_values("最差相对差", ascending=False))
    show("平均相对差 Top", m.sort_values("平均相对差", ascending=False))

    print("\n========== 各票 Top8 ==========")
    for label, df in (("凯盛", df_kc), ("天通", df_tt)):
        print(f"\n-- {label} --")
        print(
            df.sort_values("累计收益%", ascending=False)[
                ["方案", "累计收益%", "相对仅止损", "最大回撤%", "夏普"]
            ]
            .head(8)
            .to_string(index=False)
        )

    print("\n========== 最优建议 ==========")
    if not beat.empty:
        b = beat.iloc[0]
        print(
            f"两票共用最优: {b['方案']}\n"
            f"  凯盛 {b['凯盛_累计收益%']:.2f}% ({b['凯盛_相对仅止损']:+.2f}) "
            f"夏普 {b['凯盛_夏普']:.4f}\n"
            f"  天通 {b['天通_累计收益%']:.2f}% ({b['天通_相对仅止损']:+.2f}) "
            f"夏普 {b['天通_夏普']:.4f}"
        )
    else:
        b = m.sort_values("最差相对差", ascending=False).iloc[0]
        print("无两票同时更高方案；次优(伤害最小):")
        print(
            f"  {b['方案']}\n"
            f"  凯盛 {b['凯盛_相对仅止损']:+.2f} | 天通 {b['天通_相对仅止损']:+.2f}"
        )
    # 用户关心的 15 起每5点减10% 挂+2
    focus = m[m["方案"].str.startswith("档15/") | (m["方案"] == "档15→挂17@减10%")]
    focus2 = m[m["方案"].str.contains(r"档15.*@减10%", regex=True)]
    print("\n========== 焦点：15起步长5 减10% 挂+2 ==========")
    sub = m[m["方案"].str.match(r"档15(/[0-9]+)*→挂.*@减10%$")]
    if not sub.empty:
        print(
            sub.sort_values("平均相对差", ascending=False)[
                [
                    "方案",
                    "凯盛_累计收益%",
                    "凯盛_相对仅止损",
                    "天通_累计收益%",
                    "天通_相对仅止损",
                ]
            ]
            .head(10)
            .to_string(index=False)
        )
    print(f"\n明细: {out / 'optimize_tp_offset_joint.csv'}")


if __name__ == "__main__":
    main()
