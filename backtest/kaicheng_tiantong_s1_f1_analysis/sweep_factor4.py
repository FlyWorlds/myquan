"""凯盛+天通：因子4 牛市持股修复扫描 — 找因子1 无超额阶段的临界参数。

用法:
  python backtest/kaicheng_tiantong_s1_f1_analysis/sweep_factor4.py
  python backtest/kaicheng_tiantong_s1_f1_analysis/sweep_factor4.py --quick
"""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from strategy import KAICHENG, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.config import TIANTONG  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
OUT_CSV = OUT_DIR / "factor4_sweep.csv"
OUT_SUMMARY = OUT_DIR / "factor4_sweep_summary.json"
TOTAL_EXCESS_CSV = OUT_DIR / "factor4_total_excess_sweep.csv"
TOTAL_EXCESS_SUMMARY = OUT_DIR / "factor4_total_excess_summary.json"

WEAK_YEARS = (2021, 2023, 2025)
OOS_YEARS = (2023, 2024, 2025, 2026)


def _yearly_returns(result: Any, daily: pd.DataFrame) -> pd.DataFrame:
    eq = result.equity_curve.sort_index()
    if getattr(eq.index, "tz", None) is not None:
        yrs = eq.index.tz_convert("Asia/Shanghai").year
    else:
        yrs = eq.index.year
    rows = []
    for y in sorted(set(yrs)):
        mask = yrs == y
        part = eq[mask]
        if len(part) < 2:
            continue
        s_ret = float(part.iloc[-1] / part.iloc[0] - 1.0) * 100.0
        c0 = float(daily.loc[daily["date"].astype(str).str.startswith(str(y))]["close"].iloc[0])
        c1 = float(daily.loc[daily["date"].astype(str).str.startswith(str(y))]["close"].iloc[-1])
        bh = (c1 / c0 - 1.0) * 100.0
        rows.append({"year": int(y), "strategy_pct": s_ret, "bh_pct": bh, "excess_pct": s_ret - bh})
    return pd.DataFrame(rows)


def _run(
    cfg: Any,
    label: str,
    *,
    factor4: bool = False,
    f4_kind: str = "roc_ma",
    f4_params: dict | None = None,
    bull_entry: bool = False,
    stop_widen_mult: float = 0.0,
) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if factor4:
        kw.update(
            factor4_enabled=True,
            factor4_kind=f4_kind,
            factor4_params=dict(f4_params or {}),
            factor4_bull_entry=bull_entry,
            factor4_stop_widen_mult=float(stop_widen_mult),
        )
    c = replace(cfg, **kw)
    r, d = run_open_break(c, show_report=False, verbose=False)
    m = r.metrics_df
    yr = _yearly_returns(r, d)
    weak = yr[yr["year"].isin(WEAK_YEARS)]
    weak_excess_sum = float(weak["excess_pct"].sum()) if len(weak) else 0.0
    weak_neg = int((weak["excess_pct"] < 0).sum())
    c0 = float(d.iloc[0]["close"])
    c1 = float(d.iloc[-1]["close"])
    bh_tot = (c1 / c0 - 1.0) * 100.0
    strat_tot = float(metric(m, "total_return_pct"))
    row: dict[str, Any] = {
        "标的": cfg.symbol_name,
        "方案": label,
        "factor4": factor4,
        "f4_kind": f4_kind if factor4 else "",
        "f4_params": str(f4_params or {}),
        "bull_entry": bull_entry,
        "stop_widen_mult": float(stop_widen_mult) if factor4 else None,
        "累计策略%": round(strat_tot, 2),
        "累计持有%": round(bh_tot, 2),
        "累计超额%": round(strat_tot - bh_tot, 2),
        "年化收益%": round(float(metric(m, "annualized_return")) * 100.0, 2),
        "最大回撤%": round(float(metric(m, "max_drawdown_pct")), 2),
        "夏普": round(float(metric(m, "sharpe_ratio")), 3),
        "闭环": int(metric(m, "closed_trade_count")),
        "弱年超额合计%": round(weak_excess_sum, 2),
        "弱年负超额年数": weak_neg,
    }
    for y in WEAK_YEARS:
        sub = yr[yr["year"] == y]
        ex = float(sub["excess_pct"].iloc[0]) if len(sub) else None
        row[f"{y}超额%"] = round(ex, 2) if ex is not None else None
    oos = yr[yr["year"].isin(OOS_YEARS)]
    row["样本外超额合计%"] = round(float(oos["excess_pct"].sum()), 2)
    row["样本外正超额年数"] = int((oos["excess_pct"] > 0).sum())
    row["样本外最差年超额%"] = (
        round(float(oos["excess_pct"].min()), 2) if len(oos) else None
    )
    for y in OOS_YEARS:
        sub = yr[yr["year"] == y]
        ex = float(sub["excess_pct"].iloc[0]) if len(sub) else None
        row[f"OOS{y}超额%"] = round(ex, 2) if ex is not None else None
    return row


def _grid(quick: bool) -> list[tuple[str, str, dict, bool]]:
    jobs: list[tuple[str, str, dict, bool]] = []
    jobs.append(("F1基线", "", {}, False))

    # 仅抑制止损（核心修复）
    for kind, n in [
        ("roc_ma", 40),
        ("roc_ma", 60),
        ("roc_ma", 120),
        ("ma", 60),
        ("ma", 120),
        ("dual_ma", 0),
        ("roc", 60),
    ]:
        if kind == "dual_ma":
            p = {"fast": 10, "slow": 30}
            label = "F1+F4 dual_ma10/30止"
        elif kind == "ma":
            p = {"n": n}
            label = f"F1+F4 ma{n}止"
        elif kind == "roc":
            p = {"n": n}
            label = f"F1+F4 roc{n}止"
        else:
            p = {"n": n, "ma_n": n}
            label = f"F1+F4 roc_ma{n}止"
        jobs.append((label, kind, p, False))

    if not quick:
        for enter in (0.5, 1.0, 1.5, 2.0):
            p = {"n": 120, "enter": enter, "exit": 0.0}
            jobs.append((f"F1+F4 dist_hl120 e{enter}止", "dist_hl", p, False))
        for n in (20, 40):
            jobs.append(
                (
                    f"F1+F4 roc_ma{n}止+开盘建仓",
                    "roc_ma",
                    {"n": n, "ma_n": n},
                    True,
                )
            )

    return jobs


def _total_excess_grid(quick: bool) -> list[tuple[str, str, dict, float]]:
    """累计超额优先：只测试轻量止损放宽，不做牛市强制建仓。"""
    jobs: list[tuple[str, str, dict, float]] = [
        ("F1基线", "", {}, 0.0),
        ("旧策略7统一 roc_ma60 w2", "roc_ma", {"n": 60, "ma_n": 60}, 2.0),
        ("旧策略7凯盛 roc_ma40 暂停", "roc_ma", {"n": 40, "ma_n": 40}, 0.0),
        ("旧策略7天通 roc60 暂停", "roc", {"n": 60}, 0.0),
    ]
    signals: list[tuple[str, dict[str, Any]]] = []
    for n in ((40, 60) if quick else (20, 40, 60, 90, 120)):
        signals.append((f"roc{n}", {"kind": "roc", "n": n}))
    roc_ma_pairs = (
        ((40, 40), (60, 60))
        if quick
        else (
            (20, 20),
            (40, 40),
            (60, 60),
            (90, 90),
            (40, 60),
            (60, 40),
            (60, 90),
            (90, 60),
        )
    )
    for n, ma_n in roc_ma_pairs:
        signals.append(
            (f"roc_ma{n}/{ma_n}", {"kind": "roc_ma", "n": n, "ma_n": ma_n})
        )

    thresholds = (
        ((0.03, 0.0), (0.06, 0.0))
        if quick
        else ((0.0, 0.0), (0.03, 0.0), (0.06, 0.0), (0.10, 0.02))
    )
    widens = (1.25, 1.5) if quick else (1.25, 1.5, 2.0, 3.0)
    for signal_label, spec in signals:
        kind = str(spec["kind"])
        base_params = {k: v for k, v in spec.items() if k != "kind"}
        for enter_raw, exit_raw in thresholds:
            params = {
                **base_params,
                "enter_raw": enter_raw,
                "exit_raw": exit_raw,
            }
            for widen in widens:
                label = (
                    f"F1+F4 {signal_label} "
                    f"e{enter_raw:.2f}/x{exit_raw:.2f} w{widen:g}"
                )
                jobs.append((label, kind, params, widen))
    return jobs


def _write_total_excess_summary(df: pd.DataFrame) -> None:
    import json

    summary: dict[str, Any] = {
        "目标": "逐票累计超额优先",
        "样本外年度": list(OOS_YEARS),
        "组合约束": "两票均保留因子4；非牛市仅因子1，牛市启动因子4放宽止损",
        "选择规则": "在非旧版因子4候选中按全样本累计超额优先选择",
        "标的": {},
    }
    for sym in df["标的"].unique():
        sub = df[df["标的"] == sym].copy()
        base = sub[sub["方案"] == "F1基线"].iloc[0]
        legacy_label = (
            "旧策略7凯盛 roc_ma40 暂停"
            if sym == "凯盛科技"
            else "旧策略7天通 roc60 暂停"
        )
        legacy = sub[sub["方案"] == legacy_label]
        unified = sub[sub["方案"] == "旧策略7统一 roc_ma60 w2"]
        eligible = sub[
            (sub["factor4"] == True)  # noqa: E712
            & (sub["样本外超额合计%"] > float(base["样本外超额合计%"]))
            & (sub["累计超额%"] > float(base["累计超额%"]))
        ].sort_values(["累计超额%", "样本外超额合计%"], ascending=False)
        factor4_candidates = sub[
            (sub["factor4"] == True)  # noqa: E712
            & ~sub["方案"].astype(str).str.startswith("旧策略7")
        ].sort_values(["累计超额%", "样本外超额合计%"], ascending=False)
        selected = factor4_candidates.iloc[0]
        top = sub.sort_values(
            ["累计超额%", "样本外超额合计%"], ascending=False
        ).head(10)
        summary["标的"][sym] = {
            "F1基线": {
                "累计超额%": float(base["累计超额%"]),
                "样本外超额合计%": float(base["样本外超额合计%"]),
                "最大回撤%": float(base["最大回撤%"]),
            },
            "旧策略7逐票": (
                {
                    "方案": legacy_label,
                    "累计超额%": float(legacy.iloc[0]["累计超额%"]),
                    "样本外超额合计%": float(
                        legacy.iloc[0]["样本外超额合计%"]
                    ),
                    "最大回撤%": float(legacy.iloc[0]["最大回撤%"]),
                }
                if len(legacy)
                else None
            ),
            "旧策略7统一": (
                {
                    "累计超额%": float(unified.iloc[0]["累计超额%"]),
                    "样本外超额合计%": float(
                        unified.iloc[0]["样本外超额合计%"]
                    ),
                    "最大回撤%": float(unified.iloc[0]["最大回撤%"]),
                }
                if len(unified)
                else None
            ),
            "通过双重门槛的因子4方案数": int(len(eligible)),
            "最终选择": {
                "方案": str(selected["方案"]),
                "factor4_enabled": bool(selected["factor4"]),
                "f4_kind": (
                    ""
                    if pd.isna(selected["f4_kind"])
                    else str(selected["f4_kind"])
                ),
                "f4_params": str(selected["f4_params"]),
                "stop_widen_mult": (
                    None
                    if pd.isna(selected["stop_widen_mult"])
                    else float(selected["stop_widen_mult"])
                ),
                "累计超额%": float(selected["累计超额%"]),
                "样本外超额合计%": float(selected["样本外超额合计%"]),
                "最大回撤%": float(selected["最大回撤%"]),
            },
            "累计超额前10": top[
                [
                    "方案",
                    "累计超额%",
                    "样本外超额合计%",
                    "最大回撤%",
                    "夏普",
                ]
            ].to_dict("records"),
        }
    TOTAL_EXCESS_SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", help="缩小参数网格")
    p.add_argument(
        "--total-excess",
        action="store_true",
        help="运行逐票累计超额优先的非对称阈值/止损放宽扫描",
    )
    args = p.parse_args()

    bases = [
        ("凯盛", KAICHENG),
        ("天通", replace(TIANTONG)),
    ]
    rows: list[dict[str, Any]] = []
    if args.total_excess:
        for sym_label, base in bases:
            for label, kind, params, widen in _total_excess_grid(args.quick):
                rows.append(
                    _run(
                        base,
                        label,
                        factor4=label != "F1基线",
                        f4_kind=kind or "roc_ma",
                        f4_params=params,
                        stop_widen_mult=widen,
                    )
                )
                print(f"  done {sym_label} {label}")
        df = pd.DataFrame(rows)
        df.to_csv(TOTAL_EXCESS_CSV, index=False, encoding="utf-8-sig")
        _write_total_excess_summary(df)
        print(f"\n写入 {TOTAL_EXCESS_CSV}")
        print(f"写入 {TOTAL_EXCESS_SUMMARY}")
        return

    for sym_label, base in bases:
        for label, kind, params, bull_entry in _grid(args.quick):
            rows.append(
                _run(
                    base,
                    label,
                    factor4=label != "F1基线",
                    f4_kind=kind or "roc_ma",
                    f4_params=params,
                    bull_entry=bull_entry,
                )
            )
            print(f"  done {sym_label} {label}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # 弱年修复：相对同标的 F1 基线，弱年超额合计提升最大
    summary: dict[str, Any] = {"弱年": list(WEAK_YEARS), "标的": {}}
    for sym in df["标的"].unique():
        sub = df[df["标的"] == sym]
        base = sub[sub["方案"] == "F1基线"].iloc[0]
        base_weak = float(base["弱年超额合计%"])
        sub = sub.copy()
        sub["弱年改善%"] = sub["弱年超额合计%"] - base_weak
        best = sub.sort_values("弱年改善%", ascending=False).iloc[0]
        # 临界：弱年负超额年数=0 且 累计超额不低于基线-5pct
        fixed = sub[
            (sub["弱年负超额年数"] == 0)
            & (sub["累计超额%"] >= float(base["累计超额%"]) - 5.0)
        ]
        summary["标的"][sym] = {
            "F1基线弱年超额合计%": base_weak,
            "F1基线2021/2023/2025": {
                y: base.get(f"{y}超额%") for y in WEAK_YEARS
            },
            "最佳弱年修复": {
                "方案": best["方案"],
                "弱年改善%": round(float(best["弱年改善%"]), 2),
                "弱年超额合计%": float(best["弱年超额合计%"]),
                "累计超额%": float(best["累计超额%"]),
                "2021": best.get("2021超额%"),
                "2023": best.get("2023超额%"),
                "2025": best.get("2025超额%"),
            },
            "弱年全转正方案数": int(len(fixed)),
            "临界方案": fixed[["方案", "弱年超额合计%", "累计超额%", "2021超额%", "2023超额%", "2025超额%"]].head(5).to_dict("records"),
        }

    import json

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写入 {OUT_CSV}")
    print(f"写入 {OUT_SUMMARY}")
    for sym, info in summary["标的"].items():
        b = info["最佳弱年修复"]
        print(
            f"\n{sym}: 最佳弱年修复 = {b['方案']} "
            f"(弱年改善 +{b['弱年改善%']}%, 累计超额 {b['累计超额%']}%)"
        )


if __name__ == "__main__":
    main()
