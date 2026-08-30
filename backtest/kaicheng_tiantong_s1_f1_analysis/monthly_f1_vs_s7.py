"""凯盛+天通：因子1 vs 策略七(因子1+4) 月度收益对比。

口径：
  · 凯盛 threshold=2.5%，天通=3.0%（不变）
  · F1：纯因子1 开盘突破
  · S7：策略七 per_symbol（非牛市仅F1；牛市启动F4放宽止损）
  · 组合 = 两票独立半仓等权（0.5×归一权益）
"""

from __future__ import annotations

import json
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

from strategy import KAICHENG, TIANTONG, run_open_break  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.config import resolve_factor4_repair  # noqa: E402
from strategy.strategies.strategy3 import run_strategy3  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
OUT_MONTHLY = OUT_DIR / "monthly_f1_vs_s7.csv"
OUT_YEARLY = OUT_DIR / "yearly_f1_vs_s7.csv"
OUT_SUMMARY = OUT_DIR / "monthly_f1_vs_s7_summary.json"


def _to_naive(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if getattr(idx, "tz", None) is not None:
        return idx.tz_convert("Asia/Shanghai").tz_localize(None)
    return idx


def _equity_series(result: Any) -> pd.Series:
    eq = result.equity_curve.sort_index().astype(float)
    eq.index = _to_naive(eq.index)
    return eq


def _bh_equity(daily: pd.DataFrame, initial: float = 100_000.0) -> pd.Series:
    d = daily.copy()
    dates = pd.to_datetime(d["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    close = d["close"].astype(float).to_numpy()
    eq = initial * (close / close[0])
    s = pd.Series(eq, index=pd.DatetimeIndex(dates), name="bh")
    return s.sort_index()


def _month_returns(eq: pd.Series) -> pd.Series:
    m = eq.resample("ME").last().dropna()
    # first partial month: use first equity as base
    first = eq.iloc[0]
    rets = m.pct_change()
    if len(m):
        rets.iloc[0] = float(m.iloc[0] / first - 1.0)
    rets.index = rets.index.strftime("%Y-%m")
    return rets * 100.0


def _year_returns(eq: pd.Series) -> pd.Series:
    y = eq.groupby(eq.index.year).apply(lambda x: float(x.iloc[-1]))
    first = float(eq.iloc[0])
    out = {}
    prev = first
    for yr in sorted(y.index):
        cur = float(y.loc[yr])
        out[int(yr)] = (cur / prev - 1.0) * 100.0
        prev = cur
    return pd.Series(out)


def _align_half(eq_a: pd.Series, eq_b: pd.Series) -> pd.Series:
    a = eq_a / float(eq_a.iloc[0])
    b = eq_b / float(eq_b.iloc[0])
    idx = a.index.intersection(b.index)
    return 0.5 * a.loc[idx] + 0.5 * b.loc[idx]


def _run_f1(cfg: Any) -> tuple[Any, pd.DataFrame]:
    c = replace(cfg, factor4_enabled=False)
    return run_open_break(c, show_report=False, verbose=False)


def _run_s7(cfg: Any) -> tuple[Any, pd.DataFrame]:
    return run_strategy3(cfg, mode="per_symbol", verbose=False)


def _pack(label: str, mode: str, result: Any, daily: pd.DataFrame) -> dict[str, Any]:
    eq = _equity_series(result)
    bh = _bh_equity(daily)
    m = result.metrics_df
    tot = float(metric(m, "total_return_pct"))
    bh_tot = float(bh.iloc[-1] / bh.iloc[0] - 1.0) * 100.0
    return {
        "标的": label,
        "模式": mode,
        "equity": eq,
        "bh": bh,
        "累计策略%": round(tot, 2),
        "累计持有%": round(bh_tot, 2),
        "累计超额%": round(tot - bh_tot, 2),
        "年化%": round(float(metric(m, "annualized_return")) * 100.0, 2),
        "最大回撤%": round(float(metric(m, "max_drawdown_pct")), 2),
        "夏普": round(float(metric(m, "sharpe_ratio")), 3),
        "闭环": int(metric(m, "closed_trade_count")),
        "月度策略%": _month_returns(eq),
        "月度持有%": _month_returns(bh),
        "年度策略%": _year_returns(eq),
        "年度持有%": _year_returns(bh),
    }


def main() -> None:
    bases = [
        ("凯盛科技", KAICHENG),
        ("天通股份", replace(TIANTONG)),
    ]
    packs: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for label, cfg in bases:
        print(f"run F1 {label} ...")
        r1, d1 = _run_f1(cfg)
        p1 = _pack(label, "F1", r1, d1)
        packs.append(p1)
        by_key[(label, "F1")] = p1

        print(f"run S7 F1+F4 {label} ...")
        r7, d7 = _run_s7(cfg)
        p7 = _pack(label, "S7_F1F4", r7, d7)
        packs.append(p7)
        by_key[(label, "S7_F1F4")] = p7

        # sanity: thresholds unchanged
        c7 = resolve_factor4_repair(cfg)
        assert abs(float(c7.threshold_pct) - float(cfg.threshold_pct)) < 1e-12
        assert bool(c7.factor4_enabled)

    # portfolio
    for mode in ("F1", "S7_F1F4"):
        pk = by_key[("凯盛科技", mode)]
        pt = by_key[("天通股份", mode)]
        peq = _align_half(pk["equity"], pt["equity"])
        pbh = _align_half(pk["bh"], pt["bh"])
        tot = float(peq.iloc[-1] / peq.iloc[0] - 1.0) * 100.0
        bh_tot = float(pbh.iloc[-1] / pbh.iloc[0] - 1.0) * 100.0
        peak = peq.cummax()
        mdd = float((1.0 - peq / peak).max()) * 100.0
        packs.append(
            {
                "标的": "组合",
                "模式": mode,
                "equity": peq,
                "bh": pbh,
                "累计策略%": round(tot, 2),
                "累计持有%": round(bh_tot, 2),
                "累计超额%": round(tot - bh_tot, 2),
                "年化%": None,
                "最大回撤%": round(mdd, 2),
                "夏普": None,
                "闭环": None,
                "月度策略%": _month_returns(peq),
                "月度持有%": _month_returns(pbh),
                "年度策略%": _year_returns(peq),
                "年度持有%": _year_returns(pbh),
            }
        )

    # monthly table
    months = sorted(
        {
            m
            for p in packs
            for m in p["月度策略%"].index
        }
    )
    monthly_rows: list[dict[str, Any]] = []
    for month in months:
        for p in packs:
            s = float(p["月度策略%"].get(month, 0.0))
            h = float(p["月度持有%"].get(month, 0.0))
            monthly_rows.append(
                {
                    "月份": month,
                    "标的": p["标的"],
                    "模式": p["模式"],
                    "策略%": round(s, 2),
                    "平权持有%": round(h, 2),
                    "超额%": round(s - h, 2),
                }
            )
    monthly = pd.DataFrame(monthly_rows)
    monthly.to_csv(OUT_MONTHLY, index=False, encoding="utf-8-sig")

    # yearly table
    years = sorted(
        {
            int(y)
            for p in packs
            for y in p["年度策略%"].index
        }
    )
    yearly_rows: list[dict[str, Any]] = []
    for yr in years:
        for p in packs:
            s = float(p["年度策略%"].get(yr, 0.0))
            h = float(p["年度持有%"].get(yr, 0.0))
            yearly_rows.append(
                {
                    "年份": yr,
                    "标的": p["标的"],
                    "模式": p["模式"],
                    "策略%": round(s, 2),
                    "平权持有%": round(h, 2),
                    "超额%": round(s - h, 2),
                }
            )
    yearly = pd.DataFrame(yearly_rows)
    yearly.to_csv(OUT_YEARLY, index=False, encoding="utf-8-sig")

    # summary
    summary: dict[str, Any] = {
        "口径": {
            "凯盛阈值": "2.5%",
            "天通阈值": "3.0%",
            "S7": "per_symbol；非牛市仅F1，牛市F4放宽止损",
            "组合": "独立半仓等权",
        },
        "总览": [],
        "月度胜率": {},
        "月度均值": {},
    }
    for p in packs:
        summary["总览"].append(
            {
                "标的": p["标的"],
                "模式": p["模式"],
                "累计策略%": p["累计策略%"],
                "累计持有%": p["累计持有%"],
                "累计超额%": p["累计超额%"],
                "最大回撤%": p["最大回撤%"],
                "夏普": p["夏普"],
                "闭环": p["闭环"],
            }
        )
        sub = monthly[(monthly["标的"] == p["标的"]) & (monthly["模式"] == p["模式"])]
        summary["月度胜率"][f"{p['标的']}|{p['模式']}"] = {
            "正收益月占比%": round(float((sub["策略%"] > 0).mean() * 100), 1),
            "正超额月占比%": round(float((sub["超额%"] > 0).mean() * 100), 1),
            "月均策略%": round(float(sub["策略%"].mean()), 2),
            "月均超额%": round(float(sub["超额%"].mean()), 2),
            "最差月策略%": round(float(sub["策略%"].min()), 2),
            "最好月策略%": round(float(sub["策略%"].max()), 2),
        }

    # delta F1 -> S7 for portfolio/symbols
    deltas = []
    for name in ("组合", "凯盛科技", "天通股份"):
        f1 = next(x for x in summary["总览"] if x["标的"] == name and x["模式"] == "F1")
        s7 = next(
            x for x in summary["总览"] if x["标的"] == name and x["模式"] == "S7_F1F4"
        )
        deltas.append(
            {
                "标的": name,
                "累计超额Δ%": round(float(s7["累计超额%"]) - float(f1["累计超额%"]), 2),
                "最大回撤Δ%": round(
                    float(s7["最大回撤%"]) - float(f1["最大回撤%"]), 2
                ),
            }
        )
    summary["S7相对F1"] = deltas

    OUT_SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"写入 {OUT_MONTHLY}")
    print(f"写入 {OUT_YEARLY}")
    print(f"写入 {OUT_SUMMARY}")
    for row in summary["总览"]:
        print(
            f"{row['标的']:4s} {row['模式']:8s} "
            f"超额={row['累计超额%']:+.2f}% 回撤={row['最大回撤%']:.2f}%"
        )


if __name__ == "__main__":
    main()
