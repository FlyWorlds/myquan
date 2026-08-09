"""凯盛+天通：扩展止盈设计，对比仅止损，寻找能否更高收益。

设计族：
  A 轻减仓：更高起点(20~45)，每+5%，减5%/10%，1~3档；触发 high/close
  B 锁盈抬止损：触及档位后不减仓，把止损抬到买入价×(1+lock)
  C 轻减+锁盈 组合
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

from strategy import KAICHENG, BacktestConfig, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402

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


def _levels(start: float, step: float, n: int) -> tuple[float, ...]:
    return tuple(round(start + i * step, 4) for i in range(n))


def _stats(result) -> dict:
    m = result.metrics_df
    ret = metric(m, "total_return_pct")
    dd = metric(m, "max_drawdown_pct")
    sharpe = metric(m, "sharpe_ratio")
    win = metric(m, "win_rate")
    return {
        "累计收益%": ret,
        "最大回撤%": dd,
        "夏普": sharpe,
        "胜率%": win,
        "总盈亏": metric(m, "total_pnl"),
        "综合分": ret - 0.35 * abs(dd) + 40.0 * (sharpe if sharpe == sharpe else 0.0),
    }


def _cfgs() -> list[tuple[str, dict]]:
    """返回 (方案名, replace kwargs)。"""
    out: list[tuple[str, dict]] = [("仅止损", {})]
    step = 0.05

    # A: 轻减仓
    for trig in ("high", "close"):
        for start in (0.20, 0.25, 0.30, 0.35, 0.40, 0.45):
            for reduce in (0.05, 0.10):
                for n in (1, 2, 3):
                    if reduce * n > 0.35:
                        continue
                    lv = _levels(start, step, n)
                    name = (
                        f"减仓{trig}|{ '/'.join(f'{x*100:.0f}' for x in lv)}"
                        f"@减{reduce*100:.0f}%"
                    )
                    out.append(
                        (
                            name,
                            {
                                "take_profit_levels": lv,
                                "take_profit_reduce": reduce,
                                "take_profit_trigger": trig,
                                "take_profit_lock_pct": None,
                            },
                        )
                    )

    # B: 只锁盈抬止损（不减仓）
    for trig in ("high", "close"):
        for activate in (0.15, 0.20, 0.25, 0.30, 0.35):
            for lock in (0.0, 0.05, 0.10, 0.15):
                # lock=0 → 抬到成本价保本
                name = f"锁盈{trig}|触{activate*100:.0f}%→锁{lock*100:.0f}%"
                out.append(
                    (
                        name,
                        {
                            "take_profit_levels": (activate,),
                            "take_profit_reduce": 0.0,
                            "take_profit_trigger": trig,
                            "take_profit_lock_pct": lock,
                        },
                    )
                )

    # C: 轻减 + 锁盈（精选）
    for trig in ("high", "close"):
        for start, reduce, lock in (
            (0.20, 0.10, 0.05),
            (0.25, 0.10, 0.05),
            (0.25, 0.10, 0.10),
            (0.30, 0.10, 0.10),
            (0.30, 0.05, 0.05),
            (0.35, 0.10, 0.10),
            (0.20, 0.05, 0.0),
            (0.25, 0.05, 0.05),
        ):
            lv = (start,)
            name = (
                f"组合{trig}|{start*100:.0f}%减{reduce*100:.0f}%+锁{lock*100:.0f}%"
            )
            out.append(
                (
                    name,
                    {
                        "take_profit_levels": lv,
                        "take_profit_reduce": reduce,
                        "take_profit_trigger": trig,
                        "take_profit_lock_pct": lock,
                    },
                )
            )

    # 去重
    seen: set[str] = set()
    uniq: list[tuple[str, dict]] = []
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
        cfg = replace(base, **kw)
        print(f"  [{i}/{len(configs)}] {name}", flush=True)
        try:
            result, _ = run_open_break(cfg, show_report=False, verbose=False)
            st = _stats(result)
        except Exception as e:  # noqa: BLE001
            print(f"    FAIL {e}")
            continue
        st["方案"] = name
        st["标的"] = base.symbol_name
        rows.append(st)
    df = pd.DataFrame(rows)
    base_ret = float(df.loc[df["方案"] == "仅止损", "累计收益%"].iloc[0])
    df["相对仅止损"] = df["累计收益%"] - base_ret
    return df


def main() -> None:
    configs = _cfgs()
    print(f"共 {len(configs)} 组参数（含仅止损）")

    kc = replace(KAICHENG, start_date="20200101")
    tt = replace(TIANTONG, start_date="20200101")
    df_kc = _run_symbol(kc, configs)
    df_tt = _run_symbol(tt, configs)

    out = Path(__file__).resolve().parent
    df_all = pd.concat([df_kc, df_tt], ignore_index=True)
    df_all.to_csv(out / "compare_tp_beat_all.csv", index=False, encoding="utf-8-sig")

    keys = ["方案"]
    a = df_kc.rename(
        columns={
            c: f"凯盛_{c}"
            for c in df_kc.columns
            if c not in keys
        }
    )
    b = df_tt.rename(
        columns={
            c: f"天通_{c}"
            for c in df_tt.columns
            if c not in keys
        }
    )
    # 清理重复标的列
    a = a[[c for c in a.columns if not c.startswith("凯盛_标的")]]
    b = b[[c for c in b.columns if not c.startswith("天通_标的")]]
    m = a.merge(b, on="方案", how="inner")
    m["最差相对差"] = m[["凯盛_相对仅止损", "天通_相对仅止损"]].min(axis=1)
    m["平均相对差"] = m[["凯盛_相对仅止损", "天通_相对仅止损"]].mean(axis=1)
    m["两票都更高"] = (m["凯盛_相对仅止损"] > 0) & (m["天通_相对仅止损"] > 0)
    m["任一更高"] = (m["凯盛_相对仅止损"] > 0) | (m["天通_相对仅止损"] > 0)
    m.to_csv(out / "compare_tp_beat_joint.csv", index=False, encoding="utf-8-sig")

    def show(title: str, df: pd.DataFrame, n: int = 10) -> None:
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
        print(df[cols].head(n).to_string(index=False))

    print("\n========== 基准 ==========")
    for label, df in (("凯盛", df_kc), ("天通", df_tt)):
        r = df[df["方案"] == "仅止损"].iloc[0]
        print(
            f"{label}: {r['累计收益%']:.2f}% | 回撤 {r['最大回撤%']:.2f}% | "
            f"夏普 {r['夏普']:.4f}"
        )

    beat_both = m[m["两票都更高"]].sort_values("平均相对差", ascending=False)
    beat_any = m[m["任一更高"]].sort_values("平均相对差", ascending=False)
    show("两票都跑赢仅止损", beat_both if not beat_both.empty else m.head(0))
    if beat_both.empty:
        print("（无）")
    show("至少一票跑赢（按平均相对差）", beat_any)
    show("联合伤害最小（最差相对差）", m.sort_values("最差相对差", ascending=False))

    print("\n========== 各票收益 Top5（含仅止损）==========")
    for label, df in (("凯盛", df_kc), ("天通", df_tt)):
        print(f"\n-- {label} --")
        print(
            df.sort_values("累计收益%", ascending=False)[
                ["方案", "累计收益%", "相对仅止损", "最大回撤%", "夏普"]
            ]
            .head(5)
            .to_string(index=False)
        )

    print("\n========== 结论 ==========")
    if not beat_both.empty:
        b0 = beat_both.iloc[0]
        print(
            f"存在两票都更高的方案: {b0['方案']} | "
            f"凯盛 {b0['凯盛_相对仅止损']:+.2f} | 天通 {b0['天通_相对仅止损']:+.2f}"
        )
    else:
        print("扩展网格内：没有方案能在凯盛+天通上同时超过仅止损。")
        best = m.sort_values("最差相对差", ascending=False).iloc[0]
        print(
            f"两票共用次优(伤害最小): {best['方案']} | "
            f"凯盛 {best['凯盛_相对仅止损']:+.2f} | 天通 {best['天通_相对仅止损']:+.2f}"
        )
        # 单票能否打赢
        for label, col in (("凯盛", "凯盛_相对仅止损"), ("天通", "天通_相对仅止损")):
            sub = m[m[col] > 0].sort_values(col, ascending=False)
            if sub.empty:
                print(f"{label}: 无止盈方案超过仅止损")
            else:
                s = sub.iloc[0]
                print(
                    f"{label}最佳止盈: {s['方案']} | 相对 {s[col]:+.2f} | "
                    f"另一票相对 {s['天通_相对仅止损' if label=='凯盛' else '凯盛_相对仅止损']:+.2f}"
                )

    print(f"\n明细: {out / 'compare_tp_beat_joint.csv'}")


if __name__ == "__main__":
    main()
