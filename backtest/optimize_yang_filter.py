"""搜索阳线过滤参数：更高收益，回撤≤40%（尽量≤35%）。"""

from __future__ import annotations

import itertools
import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.run import PRESETS  # noqa: E402
from strategy import KAICHENG, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402

logging.disable(logging.CRITICAL)


def _ann(tot: float, years: float) -> float:
    g = 1.0 + tot / 100.0
    if g <= 0 or years <= 0:
        return float("nan")
    return (g ** (1.0 / years) - 1.0) * 100.0


def _years(daily: pd.DataFrame) -> float:
    d0 = pd.to_datetime(daily["date"].iloc[0])
    d1 = pd.to_datetime(daily["date"].iloc[-1])
    return max((d1 - d0).total_seconds() / 86400.0 / 365.25, 1e-9)


def _label(cfg) -> str:
    parts: list[str] = []
    if cfg.ban_single_yang:
        thr = cfg.single_yang_min_pct
        if thr is None:
            thr = cfg.yang_min_pct
        parts.append(f"单阳≥{thr*100:.1f}%")
    if cfg.ban_double_yang:
        bits = ["双阳"]
        if cfg.yang_min_pct > 0:
            bits.append(f"阳≥{cfg.yang_min_pct*100:.1f}%")
        if cfg.double_yang_second_min_pct is not None:
            bits.append(f"第2≥{cfg.double_yang_second_min_pct*100:.1f}%")
        if cfg.double_yang_combined_min_pct is not None:
            tag = "跨日" if cfg.double_yang_combined_mode == "span" else "和"
            bits.append(f"{tag}≥{cfg.double_yang_combined_min_pct*100:.1f}%")
        parts.append("+".join(bits))
    if not parts:
        parts.append("不禁阳")
    if cfg.prev_entry_mode == "any":
        parts.append("不限前日")
    else:
        parts.append("阴/小阳")
    return "|".join(parts)


def _run_one(base, **kwargs):
    cfg = replace(base, **kwargs)
    r, d = run_open_break(cfg, show_report=False, verbose=False)
    tot = metric(r.metrics_df, "total_return_pct")
    dd = metric(r.metrics_df, "max_drawdown_pct")
    sharpe = metric(r.metrics_df, "sharpe_ratio")
    n = metric(r.metrics_df, "closed_trade_count")
    wr = metric(r.metrics_df, "win_rate")
    y = _years(d)
    c0, c1 = float(d.iloc[0]["close"]), float(d.iloc[-1]["close"])
    bh = (c1 / c0 - 1.0) * 100.0
    return {
        "方案": _label(cfg),
        "累计%": tot,
        "年化%": _ann(tot, y),
        "回撤%": dd,
        "夏普": sharpe,
        "闭环": n,
        "胜率%": wr,
        "超额": tot - bh,
        "ban_double_yang": cfg.ban_double_yang,
        "ban_single_yang": cfg.ban_single_yang,
        "yang_min_pct": cfg.yang_min_pct,
        "second_min": cfg.double_yang_second_min_pct,
        "combined_min": cfg.double_yang_combined_min_pct,
        "combined_mode": cfg.double_yang_combined_mode,
        "single_min": cfg.single_yang_min_pct,
        "prev_mode": cfg.prev_entry_mode,
    }


def _iter_configs():
    """生成搜索空间（保持前日阴/小阳为主）。"""
    # 1) 核心默认 / 旧任意双阳 / 关闭
    yield dict(
        ban_double_yang=True,
        ban_single_yang=False,
        double_yang_combined_min_pct=0.05,
        double_yang_combined_mode="span",
    )
    yield dict(
        ban_double_yang=True,
        ban_single_yang=False,
        double_yang_combined_min_pct=None,
        double_yang_combined_mode="sum_body",
    )
    yield dict(ban_double_yang=False, ban_single_yang=False)

    # 2) 双阳：第二根阈值门槛（弱第二根排除；相对任意双阳）
    for s in (0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=False,
            double_yang_second_min_pct=s,
            double_yang_combined_min_pct=None,
        )

    # 3) 双阳：跨日幅度（核心族）
    for c in (0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=False,
            double_yang_combined_min_pct=c,
            double_yang_combined_mode="span",
        )

    # 3b) 双阳：实体和
    for c in (0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=False,
            double_yang_combined_min_pct=c,
            double_yang_combined_mode="sum_body",
        )

    # 4) 双阳：计阳最小幅度
    for y in (0.005, 0.01, 0.015, 0.02, 0.025, 0.03):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=False,
            yang_min_pct=y,
            double_yang_combined_min_pct=None,
        )

    # 5) 第二根 × 跨日（精简交叉）
    for s, c in itertools.product((0.01, 0.015, 0.02, 0.025), (0.03, 0.04, 0.05, 0.06)):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=False,
            double_yang_second_min_pct=s,
            double_yang_combined_min_pct=c,
            double_yang_combined_mode="span",
        )

    # 6) 阳最小 × 第二根
    for y, s in itertools.product((0.01, 0.015, 0.02), (0.015, 0.02, 0.025, 0.03)):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=False,
            yang_min_pct=y,
            double_yang_second_min_pct=s,
            double_yang_combined_min_pct=None,
        )

    # 7) 单阳禁买
    for s in (0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05):
        yield dict(
            ban_double_yang=False,
            ban_single_yang=True,
            single_yang_min_pct=s,
        )

    # 8) 单阳 + 双阳（松）
    for s_single, s_second in itertools.product((0.02, 0.025, 0.03), (0.02, 0.025, 0.03)):
        yield dict(
            ban_double_yang=True,
            ban_single_yang=True,
            single_yang_min_pct=s_single,
            double_yang_second_min_pct=s_second,
            double_yang_combined_min_pct=None,
        )

    # 9) 最优候选上再试「不限前日」——在 main 里对 top 补跑


def main() -> None:
    base = replace(KAICHENG, start_date="20220101")
    rows: list[dict] = []
    seen: set[str] = set()
    configs = list(_iter_configs())
    print(f"搜索配置数: {len(configs)}（凯盛 2022至今）", flush=True)
    for i, kw in enumerate(configs, 1):
        # 去重标签
        tmp = replace(base, **kw)
        lab = _label(tmp)
        if lab in seen:
            continue
        seen.add(lab)
        row = _run_one(base, **kw)
        rows.append(row)
        if i % 20 == 0 or i == len(configs):
            print(f"  progress {i}/{len(configs)} unique={len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    out = Path(__file__).parent / "optimize_yang_filter_kaicheng.csv"
    df.sort_values("累计%", ascending=False).to_csv(out, index=False, encoding="utf-8-sig")

    # 核心现行：双阳跨日≥5%
    cur = df[df["方案"] == "双阳+跨日≥5.0%|阴/小阳"]
    if cur.empty:
        cur = df[df["方案"].str.contains("跨日≥5", na=False)]
    cur_ret = float(cur.iloc[0]["累计%"]) if not cur.empty else float("nan")
    cur_dd = float(cur.iloc[0]["回撤%"]) if not cur.empty else float("nan")

    ok40 = df[df["回撤%"] <= 40.0 + 1e-9].copy()
    ok35 = df[df["回撤%"] <= 35.0 + 1e-9].copy()

    def _topk(frame: pd.DataFrame, k: int = 10) -> pd.DataFrame:
        if frame.empty:
            return frame
        return frame.sort_values(["累计%", "夏普"], ascending=[False, False]).head(k)

    print("\n========== 凯盛 阳线过滤搜索（2022至今）==========")
    print(f"现行: 累计 {cur_ret:.2f}%  回撤 {cur_dd:.2f}%")
    print(f"可行(回撤≤40): {len(ok40)}/{len(df)}；更优(≤35): {len(ok35)}/{len(df)}")
    print(f"明细: {out}")

    print("\n--- Top10 回撤≤35%（按累计收益）---")
    top35 = _topk(ok35, 10)
    if top35.empty:
        print("(无)")
    else:
        print(
            top35[
                ["方案", "累计%", "年化%", "回撤%", "夏普", "闭环", "胜率%", "超额"]
            ].to_string(index=False, float_format=lambda x: f"{x:.2f}")
        )

    print("\n--- Top10 回撤≤40%（按累计收益）---")
    top40 = _topk(ok40, 10)
    print(
        top40[
            ["方案", "累计%", "年化%", "回撤%", "夏普", "闭环", "胜率%", "超额"]
        ].to_string(index=False, float_format=lambda x: f"{x:.2f}")
    )

    # 相对现行提升且回撤达标
    beat = ok40[ok40["累计%"] > cur_ret + 1e-9].sort_values("累计%", ascending=False)
    print(f"\n--- 相对现行收益更高且回撤≤40: {len(beat)} 个 ---")
    if not beat.empty:
        print(
            beat.head(8)[
                ["方案", "累计%", "年化%", "回撤%", "夏普", "超额"]
            ].to_string(index=False, float_format=lambda x: f"{x:.2f}")
        )

    # 用凯盛 Top3（≤35 优先否则 ≤40）在天通上验证
    cand = top35 if not top35.empty else top40
    picks = cand.head(3)
    # 也带上「不禁阳」与现行
    tt_base = replace(
        PRESETS["tiantong"],
        start_date="20220101",
        daily_cache=_MYQUAN / "data_cache" / "sh600330_daily_qfq.parquet",
    )
    print("\n========== 天通验证（凯盛优选 + 基线）==========")
    verify_cfgs = [
        dict(
            ban_double_yang=True,
            ban_single_yang=False,
            double_yang_combined_min_pct=0.05,
            double_yang_combined_mode="span",
        ),  # 核心现行
        dict(
            ban_double_yang=True,
            ban_single_yang=False,
            double_yang_combined_min_pct=None,
        ),  # 旧任意双阳
        dict(ban_double_yang=False, ban_single_yang=False),  # 不禁阳
    ]
    for _, r in picks.iterrows():
        verify_cfgs.append(
            dict(
                ban_double_yang=bool(r["ban_double_yang"]),
                ban_single_yang=bool(r["ban_single_yang"]),
                yang_min_pct=float(r["yang_min_pct"] or 0.0),
                double_yang_second_min_pct=r["second_min"],
                double_yang_combined_min_pct=r["combined_min"],
                double_yang_combined_mode=str(r.get("combined_mode") or "span"),
                single_yang_min_pct=r["single_min"],
                prev_entry_mode=str(r["prev_mode"]),
            )
        )
    # 再补：凯盛最优在不限前日前提下
    if not picks.empty:
        best = picks.iloc[0]
        verify_cfgs.append(
            dict(
                ban_double_yang=bool(best["ban_double_yang"]),
                ban_single_yang=bool(best["ban_single_yang"]),
                yang_min_pct=float(best["yang_min_pct"] or 0.0),
                double_yang_second_min_pct=best["second_min"],
                double_yang_combined_min_pct=best["combined_min"],
                double_yang_combined_mode=str(best.get("combined_mode") or "span"),
                single_yang_min_pct=best["single_min"],
                prev_entry_mode="any",
            )
        )

    vrows = []
    seen_v: set[str] = set()
    for kw in verify_cfgs:
        # NaN -> None
        clean = {}
        for k, v in kw.items():
            if isinstance(v, float) and v != v:
                clean[k] = None
            else:
                clean[k] = v
        lab = _label(replace(tt_base, **clean))
        if lab in seen_v:
            continue
        seen_v.add(lab)
        vrows.append(_run_one(tt_base, **clean))
    vdf = pd.DataFrame(vrows)
    print(
        vdf[["方案", "累计%", "年化%", "回撤%", "夏普", "超额"]].to_string(
            index=False, float_format=lambda x: f"{x:.2f}"
        )
    )

    # 结论
    print("\n========== 结论 ==========")
    if not top35.empty:
        b = top35.iloc[0]
        print(
            f"凯盛推荐(回撤≤35): {b['方案']}\n"
            f"  累计 {b['累计%']:.2f}% / 年化 {b['年化%']:.2f}% / 回撤 {b['回撤%']:.2f}% "
            f"(现行 {cur_ret:.2f}% / {cur_dd:.2f}%)"
        )
    elif not top40.empty:
        b = top40.iloc[0]
        print(
            f"凯盛推荐(回撤≤40): {b['方案']}\n"
            f"  累计 {b['累计%']:.2f}% / 年化 {b['年化%']:.2f}% / 回撤 {b['回撤%']:.2f}%"
        )
    else:
        print("无满足回撤约束的方案")


if __name__ == "__main__":
    main()
