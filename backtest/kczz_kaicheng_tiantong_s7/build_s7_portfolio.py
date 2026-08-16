"""策略七三票等权组合：凯盛 + 天通 + 科创综指ETF(589680)。

口径：
  · 策略七 · 因子1 + 因子4（mode=per_symbol 逐票 F4）
  · 凯盛 ±2.5%；天通 ±3%；科创综指 买2.5%/止3.5% · T+1
  · 独立本金各 10 万；组合=已上市标的间动态等权
  · 平权持有=同权收盘价合成

用法：
  python backtest/kczz_kaicheng_tiantong_s7/build_s7_portfolio.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from strategy.backtest import metric, monthly_returns_df  # noqa: E402
from strategy.strategies.strategy7 import run_strategy7_universe  # noqa: E402

DIR = Path(__file__).resolve().parent
CASH = 100_000.0


def _prepare_eq_close(result: Any, daily: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eq = result.equity_curve.sort_index()
    if getattr(eq.index, "tz", None) is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq.index = eq.index.normalize()
    eq = eq.groupby(eq.index).last()

    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    else:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai")
    close = px.set_index("date")["close"].astype(float).sort_index()
    close.index = close.index.normalize()
    close = close.resample("D").last().ffill()
    eq = eq.reindex(close.index).ffill()
    return eq, close


def _monthly_rows(
    result: Any,
    daily: pd.DataFrame,
    *,
    label: str,
    initial_cash: float,
) -> pd.DataFrame:
    m = monthly_returns_df(result, daily, initial_cash=initial_cash)
    eq, _ = _prepare_eq_close(result, daily)
    rows = []
    for _, r in m.iterrows():
        month = str(r["月份"])
        period = pd.Period(month, freq="M")
        eq_m = eq[eq.index.to_period("M") == period]
        mdd = float("nan")
        if not eq_m.empty:
            peak = eq_m.cummax()
            mdd = float((eq_m / peak - 1.0).min() * 100.0)
        strat = float(r["策略收益%"])
        bh = float(r["持有收益%"])
        rows.append(
            {
                "月份": month,
                "标的": label,
                "策略%": round(strat, 2),
                "平权持有%": round(bh, 2),
                "超额%": round(strat - bh, 2),
                "月末权益": round(float(eq_m.iloc[-1]), 2) if not eq_m.empty else None,
                "月内回撤%": round(mdd, 2) if mdd == mdd else None,
            }
        )
    return pd.DataFrame(rows)


def _yearly_rows(
    result: Any,
    daily: pd.DataFrame,
    *,
    label: str,
    initial_cash: float,
) -> pd.DataFrame:
    eq, close = _prepare_eq_close(result, daily)
    years = sorted(set(eq.index.year) | set(close.index.year))
    rows = []
    for y in years:
        eq_y = eq[eq.index.year == y]
        px_y = close[close.index.year == y]
        if eq_y.empty:
            continue
        prev_eq = eq[eq.index.year < y]
        base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else initial_cash
        strat = (float(eq_y.iloc[-1]) / base_eq - 1.0) * 100.0
        prev_px = close[close.index.year < y]
        base_px = float(prev_px.iloc[-1]) if not prev_px.empty else float(px_y.iloc[0])
        bh = (float(px_y.iloc[-1]) / base_px - 1.0) * 100.0
        peak = eq_y.cummax()
        mdd = float((eq_y / peak - 1.0).min() * 100.0)
        closed = 0
        td = getattr(result, "trades_df", None)
        if td is not None and not td.empty:
            col = next(
                (
                    c
                    for c in ("exit_time", "close_time", "end_time", "timestamp")
                    if c in td.columns
                ),
                None,
            )
            if col:
                cts = pd.to_datetime(td[col])
                if getattr(cts.dt, "tz", None) is not None:
                    cts = cts.dt.tz_convert("Asia/Shanghai")
                closed = int((cts.dt.year == y).sum())
        rows.append(
            {
                "年份": int(y),
                "标的": label,
                "策略%": round(strat, 2),
                "平权持有%": round(bh, 2),
                "超额%": round(strat - bh, 2),
                "年内回撤%": round(mdd, 2),
                "闭环笔数": closed,
            }
        )
    return pd.DataFrame(rows)


def _rolling12m(eq: pd.Series, close: pd.Series, *, label: str) -> pd.DataFrame:
    df = pd.DataFrame({"eq": eq, "close": close}).dropna()
    if len(df) <= 252:
        return pd.DataFrame()
    rows = []
    for i in range(252, len(df)):
        sl = df.iloc[i - 252 : i + 1]
        s_ret = (sl["eq"].iloc[-1] / sl["eq"].iloc[0] - 1.0) * 100.0
        h_ret = (sl["close"].iloc[-1] / sl["close"].iloc[0] - 1.0) * 100.0
        rows.append(
            {
                "日期": sl.index[-1].strftime("%Y-%m-%d"),
                "滚动12M策略%": round(s_ret, 2),
                "滚动12M持有%": round(h_ret, 2),
                "滚动12M超额%": round(s_ret - h_ret, 2),
                "标的": label,
            }
        )
    return pd.DataFrame(rows)


def _dynamic_equal_port(
    legs: list[tuple[str, pd.Series, pd.Series]],
    *,
    cash: float,
) -> tuple[pd.Series, pd.Series]:
    """已上市标的间动态等权：缺失腿不参与平均（ETF 上市前=两票 50/50）。"""
    idx = legs[0][1].index
    for _, eq, _ in legs[1:]:
        idx = idx.union(eq.index)
    idx = idx.sort_values()

    port_parts: list[pd.Series] = []
    bh_parts: list[pd.Series] = []
    for _, eq, close in legs:
        e = eq.reindex(idx)
        c = close.reindex(idx).ffill()
        # 归一：首个有效日 = cash
        first = e.first_valid_index()
        if first is None:
            continue
        e = e.ffill()
        e_norm = e / float(e.loc[first]) * cash
        # 上市前为 NaN，不参与平均
        mask = e.index >= first
        e_norm = e_norm.where(mask)
        c0 = float(c.loc[first])
        c_norm = (c / c0 * cash).where(mask)
        port_parts.append(e_norm)
        bh_parts.append(c_norm)

    pe = pd.concat(port_parts, axis=1)
    pb = pd.concat(bh_parts, axis=1)
    port = pe.mean(axis=1, skipna=True)
    bh = pb.mean(axis=1, skipna=True)
    return port.dropna(), bh.reindex(port.index).ffill()


def _port_monthly(port: pd.Series, bh: pd.Series) -> pd.DataFrame:
    months = sorted(set(port.index.to_period("M").astype(str)))
    rows = []
    for month in months:
        period = pd.Period(month, freq="M")
        eq_m = port[port.index.to_period("M") == period]
        bh_m = bh[bh.index.to_period("M") == period]
        if eq_m.empty:
            continue
        prev_eq = port[port.index.to_period("M") < period]
        base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else float(eq_m.iloc[0])
        strat = (float(eq_m.iloc[-1]) / base_eq - 1.0) * 100.0
        prev_bh = bh[bh.index.to_period("M") < period]
        base_bh = float(prev_bh.iloc[-1]) if not prev_bh.empty else float(bh_m.iloc[0])
        hold = (float(bh_m.iloc[-1]) / base_bh - 1.0) * 100.0 if len(bh_m) else float("nan")
        peak = eq_m.cummax()
        mdd = float((eq_m / peak - 1.0).min() * 100.0)
        rows.append(
            {
                "月份": month,
                "标的": "组合",
                "策略%": round(strat, 2),
                "平权持有%": round(hold, 2),
                "超额%": round(strat - hold, 2),
                "月末权益": round(float(eq_m.iloc[-1]), 2),
                "月内回撤%": round(mdd, 2),
            }
        )
    return pd.DataFrame(rows)


def _port_yearly(port: pd.Series, bh: pd.Series) -> pd.DataFrame:
    years = sorted(set(port.index.year))
    rows = []
    for y in years:
        eq_y = port[port.index.year == y]
        bh_y = bh[bh.index.year == y]
        if eq_y.empty:
            continue
        prev = port[port.index.year < y]
        base = float(prev.iloc[-1]) if not prev.empty else float(eq_y.iloc[0])
        strat = (float(eq_y.iloc[-1]) / base - 1.0) * 100.0
        prev_b = bh[bh.index.year < y]
        base_b = float(prev_b.iloc[-1]) if not prev_b.empty else float(bh_y.iloc[0])
        hold = (float(bh_y.iloc[-1]) / base_b - 1.0) * 100.0
        mdd = float((eq_y / eq_y.cummax() - 1.0).min() * 100.0)
        rows.append(
            {
                "年份": int(y),
                "标的": "组合",
                "策略%": round(strat, 2),
                "平权持有%": round(hold, 2),
                "超额%": round(strat - hold, 2),
                "年内回撤%": round(mdd, 2),
                "闭环笔数": None,
            }
        )
    return pd.DataFrame(rows)


def _summary_block(
    *,
    strat_tot: float,
    bh_tot: float,
    monthly: pd.DataFrame,
    yearly: pd.DataFrame,
    rolling: pd.DataFrame,
) -> dict[str, Any]:
    m = monthly
    win = float((m["超额%"] > 0).mean() * 100.0) if len(m) else 0.0
    yr = {int(r["年份"]): float(r["超额%"]) for _, r in yearly.iterrows()}
    roll_last = float(rolling["滚动12M超额%"].iloc[-1]) if len(rolling) else None
    return {
        "累计策略%": round(strat_tot, 2),
        "累计平权%": round(bh_tot, 2),
        "累计超额%": round(strat_tot - bh_tot, 2),
        "超额月胜率%": round(win, 1),
        "月均超额%": round(float(m["超额%"].mean()), 2) if len(m) else 0.0,
        "年超额均值%": round(float(pd.Series(list(yr.values())).mean()), 2) if yr else 0.0,
        "2021超额%": round(yr.get(2021, 0.0), 2),
        "2024超额%": round(yr.get(2024, 0.0), 2),
        "2025超额%": round(yr.get(2025, 0.0), 2),
        "2026YTD超额%": round(yr.get(2026, 0.0), 2),
        "滚动12M最新超额%": round(roll_last, 2) if roll_last is not None else None,
    }


def _norm_from_monthly(m: pd.DataFrame) -> tuple[list[str], list[float], list[float]]:
    eq, bh = CASH, CASH
    dates, s, h = [], [], []
    for _, r in m.sort_values("月份").iterrows():
        eq *= 1 + float(r["策略%"]) / 100
        bh *= 1 + float(r["平权持有%"]) / 100
        dates.append(str(r["月份"]))
        s.append(round(eq, 2))
        h.append(round(bh, 2))
    return dates, s, h


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    print("=== 策略七 · 凯盛+天通+科创综指 · per_symbol ===")
    legs_raw = run_strategy7_universe(mode="per_symbol", verbose=False, show_report=False)

    leg_monthly: list[pd.DataFrame] = []
    leg_yearly: list[pd.DataFrame] = []
    leg_roll: list[pd.DataFrame] = []
    prepared: list[tuple[str, Any, pd.DataFrame, pd.Series, pd.Series]] = []
    leg_summary: dict[str, Any] = {}

    for cfg, result, daily in legs_raw:
        label = cfg.symbol_name
        print(
            f"  {label}: entry={cfg.resolved_entry_pct()*100:.1f}% "
            f"stop={cfg.resolved_stop_pct()*100:.1f}% "
            f"F4={cfg.factor4_kind}/{cfg.factor4_params} widen={cfg.factor4_stop_widen_mult}"
        )
        eq, close = _prepare_eq_close(result, daily)
        prepared.append((label, result, daily, eq, close))
        mm = _monthly_rows(result, daily, label=label, initial_cash=CASH)
        yy = _yearly_rows(result, daily, label=label, initial_cash=CASH)
        rr = _rolling12m(eq, close, label=label)
        leg_monthly.append(mm)
        leg_yearly.append(yy)
        if not rr.empty:
            leg_roll.append(rr)
        strat = float(metric(result.metrics_df, "total_return_pct"))
        bh = (float(close.dropna().iloc[-1]) / float(close.dropna().iloc[0]) - 1.0) * 100.0
        leg_summary[label] = _summary_block(
            strat_tot=strat,
            bh_tot=bh,
            monthly=mm,
            yearly=yy,
            rolling=rr,
        )

    port_eq, port_bh = _dynamic_equal_port(
        [(lab, eq, cl) for lab, _, _, eq, cl in prepared],
        cash=CASH,
    )
    mp = _port_monthly(port_eq, port_bh)
    yp = _port_yearly(port_eq, port_bh)
    rp = _rolling12m(port_eq, port_bh, label="组合")

    monthly = pd.concat([mp] + leg_monthly, ignore_index=True)
    yearly = pd.concat([yp] + leg_yearly, ignore_index=True)
    rolling = pd.concat(([rp] if not rp.empty else []) + leg_roll, ignore_index=True)

    monthly.to_csv(DIR / "monthly_excess_s7.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(DIR / "yearly_decay_s7.csv", index=False, encoding="utf-8-sig")
    if not rolling.empty:
        rolling.to_csv(DIR / "rolling12m_excess_s7.csv", index=False, encoding="utf-8-sig")

    s_tot = (float(port_eq.iloc[-1]) / float(port_eq.iloc[0]) - 1.0) * 100.0
    b_tot = (float(port_bh.iloc[-1]) / float(port_bh.iloc[0]) - 1.0) * 100.0
    port_sum = _summary_block(
        strat_tot=s_tot, bh_tot=b_tot, monthly=mp, yearly=yp, rolling=rp
    )

    t0 = str(port_eq.index[0].date())
    t1 = str(port_eq.index[-1].date())
    summary = {
        "区间": f"{t0} → {t1}",
        "口径": (
            "策略七·因子1+因子4(per_symbol)；"
            "凯盛2.5%/天通3%/科创综指买2.5止3.5·T+1；"
            "已上市标的动态等权"
        ),
        "组合": port_sum,
        **leg_summary,
    }
    (DIR / "summary_s7.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # canvas payload
    eq_dates, eq_s, eq_h = _norm_from_monthly(mp)
    by_label = {lab: m for lab, m in zip([p[0] for p in prepared], leg_monthly)}
    payload = {
        "meta": summary,
        "equity_cats": eq_dates,
        "equity_port": eq_s,
        "equity_bh": eq_h,
        "month_cats": mp["月份"].astype(str).tolist(),
        "month_excess_port": mp["超额%"].astype(float).tolist(),
        "month_strat_port": mp["策略%"].astype(float).tolist(),
        "month_bh_port": mp["平权持有%"].astype(float).tolist(),
        "year_rows": yp.to_dict(orient="records"),
        "recent_rows": mp.tail(18).to_dict(orient="records"),
        "legs": {
            lab: {
                "month_cats": by_label[lab]["月份"].astype(str).tolist(),
                "month_excess": by_label[lab]["超额%"].astype(float).tolist(),
                "month_strat": by_label[lab]["策略%"].astype(float).tolist(),
                "month_bh": by_label[lab]["平权持有%"].astype(float).tolist(),
            }
            for lab in by_label
        },
    }
    (DIR / "_canvas_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    print("\n组合摘要:")
    print(json.dumps(port_sum, ensure_ascii=False, indent=2))
    print(f"\n产出: {DIR}")
    print(mp.tail(12).to_string(index=False))


if __name__ == "__main__":
    main()
