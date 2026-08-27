"""天通股份：持有 / 因子1 / 牛熊震荡止盈 — 2025 至今分月对照。

口径（与 strategy1 optimize 行情止盈一致）：
  · 因子1：开盘±3%（天通默认），仅止损，无固定止盈
  · 止盈策略：因子1 + 行情 regime 止盈
        牛市不止盈；震荡 +15% 全清；熊市 +10% 全清；触发=prev_high
  · 牛/熊/震荡：用天通自身收盘构造等权指数（单票=自身）
        bull = 收盘>MA60 且 ROC20>0；bear = 收盘<MA60 且 ROC20<0；其余 sideways
        regime 次日生效（无未来函数）
  · 持有：收盘价买持（月收益=月末收盘/上月末收盘-1）

  python backtest/tiantong_regime_tp_monthly.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy import TIANTONG, run_open_break_backtest  # noqa: E402
from strategy.backtest import metric, monthly_returns_df  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.ls_energy import build_market_regime, regime_by_date  # noqa: E402

OUT = Path(__file__).resolve().parent
START = "20250102"
END = "20260827"
WARM_START = "20240101"  # MA60 / ROC20 预热
CASH = 100_000.0


def _nav_series(result) -> pd.Series:
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return pd.Series(dtype=float)
    if isinstance(eq, pd.DataFrame):
        col = "equity" if "equity" in eq.columns else eq.columns[0]
        s = eq[col]
    else:
        s = eq
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return pd.Series(
        pd.to_numeric(s, errors="coerce").to_numpy(),
        index=idx.normalize(),
    ).dropna()


def _month_rets_from_nav(nav: pd.Series, *, initial_cash: float) -> pd.Series:
    if nav.empty:
        return pd.Series(dtype=float)
    nav = nav.sort_index()
    months = nav.index.to_period("M")
    rows = {}
    for period in sorted(set(months)):
        part = nav[months == period]
        if part.empty:
            continue
        end_v = float(part.iloc[-1])
        prev = nav[months < period]
        base = float(prev.iloc[-1]) if not prev.empty else float(initial_cash)
        rows[str(period)] = (end_v / base - 1.0) * 100.0 if base > 0 else float("nan")
    return pd.Series(rows)


def _hold_month_rets(daily: pd.DataFrame) -> pd.Series:
    """月末收盘 / 上月末收盘 - 1；首月用当月首收。"""
    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if getattr(px["date"].dt, "tz", None) is not None:
        px["date"] = px["date"].dt.tz_localize(None)
    px = px.set_index(px["date"].dt.normalize())["close"].astype(float).sort_index()
    months = px.index.to_period("M")
    rows = {}
    for period in sorted(set(months)):
        part = px[months == period]
        if part.empty:
            continue
        c1 = float(part.iloc[-1])
        prev = px[months < period]
        base = float(prev.iloc[-1]) if not prev.empty else float(part.iloc[0])
        rows[str(period)] = (c1 / base - 1.0) * 100.0 if base > 0 else float("nan")
    return pd.Series(rows)


def _summary(nav: pd.Series, daily: pd.DataFrame, *, label: str) -> dict:
    if nav.empty:
        # buy-hold synthetic nav
        px = daily.copy()
        px["date"] = pd.to_datetime(px["date"])
        if getattr(px["date"].dt, "tz", None) is not None:
            px["date"] = px["date"].dt.tz_localize(None)
        px = px.set_index(px["date"].dt.normalize())["close"].astype(float).sort_index()
        nav = CASH * px / float(px.iloc[0])
    tot = float(nav.iloc[-1] / nav.iloc[0] - 1.0) * 100.0
    peak = nav.cummax()
    mdd = float((1.0 - nav / peak).max()) * 100.0
    rets = nav.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot / 100.0) ** (1.0 / years) - 1.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    return {
        "方案": label,
        "区间收益%": round(tot, 2),
        "年化%": round(ann * 100, 2),
        "最大回撤%": round(mdd, 2),
        "夏普": round(sharpe, 3),
        "起": str(nav.index[0].date()),
        "止": str(nav.index[-1].date()),
    }


def main() -> None:
    cache = TIANTONG.daily_cache
    assert cache is not None
    daily_all = fetch_daily(
        TIANTONG.symbol,
        start=WARM_START,
        end=END,
        cache_path=cache,
        force_refresh=False,
    )
    if daily_all is None or daily_all.empty:
        raise SystemExit("无日线数据")

    # 回测窗
    start_ts = pd.Timestamp(START).tz_localize("Asia/Shanghai")
    end_ts = pd.Timestamp(END).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    daily = daily_all[
        (daily_all["date"] >= start_ts) & (daily_all["date"] < end_ts)
    ].reset_index(drop=True)
    if daily.empty:
        raise SystemExit("回测窗无数据")

    # regime：预热段 + 回测段，用天通自身收盘
    close_panel = (
        daily_all.assign(
            _d=lambda x: pd.to_datetime(x["date"]).dt.tz_localize(None).dt.normalize()
        )
        .set_index("_d")[["close"]]
        .rename(columns={"close": TIANTONG.symbol})
        .astype(float)
        .sort_index()
    )
    regime = build_market_regime(close_panel)
    rmap = regime_by_date(regime)

    actual_end = pd.Timestamp(daily["date"].iloc[-1]).tz_convert("Asia/Shanghai").strftime(
        "%Y%m%d"
    )

    base_kw = dict(
        start_date=START,
        end_date=actual_end,
        initial_cash=CASH,
        threshold_pct=0.03,
        entry_pct=0.03,
        stop_pct=0.03,
        # 单票对照：关闭因子2，只看因子1 / 止盈
        factor2_enabled=False,
    )

    # 1) 因子1 仅止损
    cfg_f1 = replace(TIANTONG, **base_kw, take_profit_levels=None, regime_tp_enabled=False)
    res_f1 = run_open_break_backtest(cfg_f1, daily)
    nav_f1 = _nav_series(res_f1)

    # 2) 牛熊震荡止盈
    cfg_tp = replace(
        TIANTONG,
        **base_kw,
        take_profit_reduce=1.0,
        take_profit_trigger="prev_high",
        regime_tp_enabled=True,
        regime_by_date=rmap,
        regime_tp_bull=(),
        regime_tp_sideways=(0.15,),
        regime_tp_bear=(0.10,),
    )
    res_tp = run_open_break_backtest(cfg_tp, daily)
    nav_tp = _nav_series(res_tp)

    # 月度
    hold_m = _hold_month_rets(daily)
    f1_m = _month_rets_from_nav(nav_f1, initial_cash=CASH)
    tp_m = _month_rets_from_nav(nav_tp, initial_cash=CASH)
    months = sorted(set(hold_m.index) | set(f1_m.index) | set(tp_m.index))

    # 当月主导 regime（交易日众数）
    daily_days = [
        pd.Timestamp(d).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")
        if getattr(pd.Timestamp(d), "tzinfo", None)
        else pd.Timestamp(d).strftime("%Y-%m-%d")
        for d in daily["date"]
    ]
    regime_month = {}
    for m in months:
        days = [d for d in daily_days if d.startswith(m)]
        vals = [rmap.get(d, "sideways") for d in days]
        if vals:
            regime_month[m] = max(set(vals), key=vals.count)
        else:
            regime_month[m] = ""

    rows = []
    for m in months:
        h, f, t = hold_m.get(m), f1_m.get(m), tp_m.get(m)
        rows.append(
            {
                "月份": m,
                "主导regime": regime_month.get(m, ""),
                "持有%": None if pd.isna(h) else round(float(h), 2),
                "因子1%": None if pd.isna(f) else round(float(f), 2),
                "止盈策略%": None if pd.isna(t) else round(float(t), 2),
                "因子1-持有": None
                if pd.isna(h) or pd.isna(f)
                else round(float(f) - float(h), 2),
                "止盈-持有": None
                if pd.isna(h) or pd.isna(t)
                else round(float(t) - float(h), 2),
                "止盈-因子1": None
                if pd.isna(f) or pd.isna(t)
                else round(float(t) - float(f), 2),
            }
        )
    month_df = pd.DataFrame(rows)

    # 累计（几何连乘）
    def cum(col: str) -> list[float | None]:
        out = []
        acc = 1.0
        for v in month_df[col]:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                out.append(None)
                continue
            acc *= 1.0 + float(v) / 100.0
            out.append(round((acc - 1.0) * 100.0, 2))
        return out

    month_df["持有累计%"] = cum("持有%")
    month_df["因子1累计%"] = cum("因子1%")
    month_df["止盈累计%"] = cum("止盈策略%")

    summary = pd.DataFrame(
        [
            _summary(pd.Series(dtype=float), daily, label="持有"),
            {
                **_summary(nav_f1, daily, label="因子1"),
                "成交笔数": float(metric(res_f1.metrics_df, "closed_trade_count")),
                "胜率%": round(float(metric(res_f1.metrics_df, "win_rate")), 2),
            },
            {
                **_summary(nav_tp, daily, label="止盈策略"),
                "成交笔数": float(metric(res_tp.metrics_df, "closed_trade_count")),
                "胜率%": round(float(metric(res_tp.metrics_df, "win_rate")), 2),
            },
        ]
    )

    # regime 日分布
    bt_regimes = [rmap.get(d, "sideways") for d in daily_days]
    reg_counts = pd.Series(bt_regimes).value_counts().to_dict()

    csv_path = OUT / "天通股份_2025_regime_tp_monthly.csv"
    sum_path = OUT / "天通股份_2025_regime_tp_summary.csv"
    meta_path = OUT / "天通股份_2025_regime_tp_meta.json"
    month_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary.to_csv(sum_path, index=False, encoding="utf-8-sig")
    meta = {
        "symbol": TIANTONG.symbol,
        "name": TIANTONG.symbol_name,
        "start": START,
        "end_requested": END,
        "end_actual": actual_end,
        "entry_stop_pct": 3.0,
        "regime_tp": {
            "bull": "不止盈",
            "sideways": "15%全清@prev_high",
            "bear": "10%全清@prev_high",
            "source": "天通自身收盘 MA60+ROC20，次日生效",
        },
        "regime_day_counts": reg_counts,
        "factor2_enabled": False,
        "note": "分月收益=该月末权益(或收盘)/上月末-1；累计为月收益几何连乘。",
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 也导出引擎自带月表（因子1）便于核对
    eng = monthly_returns_df(res_f1, daily, initial_cash=CASH)
    if not eng.empty:
        eng.to_csv(OUT / "天通股份_2025_f1_engine_monthly.csv", index=False, encoding="utf-8-sig")

    print("========== 区间汇总 ==========")
    print(summary.to_string(index=False))
    print("\nregime 日数:", reg_counts)
    print("\n========== 分月对照 ==========")
    print(month_df.to_string(index=False))
    print(f"\nCSV: {csv_path}")
    print(f"汇总: {sum_path}")
    print(f"元数据: {meta_path}")


if __name__ == "__main__":
    main()
