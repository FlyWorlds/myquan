"""策略1 凯盛+天通：减摩擦变体，按 2020-2023 选、2024+ 确认。

不覆盖 bindings。产物在本目录 better_*.csv / better_report.md。

  python strategy/strategies/strategy1/optimize_tests/run_better.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import fee_rules_text  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.config import (  # noqa: E402
    KAICHENG,
    TIANTONG,
    resolve_factor4_repair,
)
from strategy.runner import (  # noqa: E402
    prepare_factor4,
    run_open_break_backtest,
)

OUT = Path(__file__).resolve().parent
START = "20200101"
END = "20260820"
OOS_START = pd.Timestamp("2024-01-01")
IS_END = pd.Timestamp("2023-12-31")
CASH = 100_000.0
N_TRIALS = 9


def load_daily(path: Path, symbol: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    else:
        df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["symbol"] = symbol
    start = pd.Timestamp(START).tz_localize("Asia/Shanghai")
    end = pd.Timestamp(END).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df["date"] >= start) & (df["date"] < end)]
    return (
        df[["date", "open", "high", "low", "close", "volume", "symbol"]]
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )


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
    s = pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize())
    return s.dropna().sort_index()


def _window_metrics(eq: pd.Series, start=None, end=None) -> dict:
    s = eq.dropna().astype(float).sort_index()
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if len(s) < 5:
        return {
            "ret_pct": float("nan"),
            "ann_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "n_days": 0,
        }
    tot = float(s.iloc[-1] / s.iloc[0] - 1.0)
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    rets = s.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    dd = 1.0 - s / s.cummax()
    return {
        "ret_pct": tot * 100.0,
        "ann_pct": ann * 100.0,
        "sharpe": sharpe,
        "mdd_pct": float(dd.max()) * 100.0,
        "n_days": int(len(s)),
    }


def _bh_nav(daily: pd.DataFrame) -> pd.Series:
    d = daily.copy()
    idx = pd.to_datetime(d["date"])
    if getattr(idx.dt, "tz", None) is not None:
        idx = idx.dt.tz_localize(None)
    idx = pd.DatetimeIndex(idx).normalize()
    c = pd.Series(pd.to_numeric(d["close"], errors="coerce").to_numpy(), index=idx)
    c = c.dropna().sort_index()
    return c / float(c.iloc[0])


def _combo_nav(nav_k: pd.Series, nav_t: pd.Series) -> pd.Series:
    idx = nav_k.index.intersection(nav_t.index)
    k = nav_k.reindex(idx).ffill()
    t = nav_t.reindex(idx).ffill()
    k = k / float(k.iloc[0])
    t = t / float(t.iloc[0])
    return 0.5 * k + 0.5 * t


def _n_trades(result, start=None, end=None) -> int:
    df = getattr(result, "executions_df", None)
    if df is None or getattr(df, "empty", True):
        m = result.metrics_df
        n = metric(m, "closed_trade_count")
        return int(n) if n == n else 0
    ts_col = next((c for c in ("timestamp", "time", "datetime", "date") if c in df.columns), None)
    side_col = "side" if "side" in df.columns else None
    if ts_col is None or side_col is None:
        return int(metric(result.metrics_df, "closed_trade_count") or 0)
    sells = df[df[side_col].astype(str).str.lower().str.contains("sell")].copy()
    sells["_d"] = pd.to_datetime(sells[ts_col])
    if getattr(sells["_d"].dt, "tz", None) is not None:
        sells["_d"] = sells["_d"].dt.tz_localize(None)
    sells["_d"] = sells["_d"].dt.normalize()
    if start is not None:
        sells = sells[sells["_d"] >= pd.Timestamp(start)]
    if end is not None:
        sells = sells[sells["_d"] <= pd.Timestamp(end)]
    return int(len(sells))


def patch_cfg(base, variant: str):
    cfg = replace(base, start_date=START, end_date=END, initial_cash=CASH)
    if variant == "baseline":
        return cfg
    if variant == "skip_ovn":
        return replace(cfg, skip_buy_after_overnight_stop=True)
    if variant == "skip_consec2":
        return replace(cfg, skip_buy_after_consec_stops=2)
    if variant == "skip_ovn_consec2":
        return replace(
            cfg,
            skip_buy_after_overnight_stop=True,
            skip_buy_after_consec_stops=2,
        )
    if variant == "stop_widen":
        if str(cfg.symbol).lower() == "sh600552":
            return replace(cfg, entry_pct=0.025, stop_pct=0.035, threshold_pct=0.025)
        return replace(cfg, entry_pct=0.03, stop_pct=0.04, threshold_pct=0.03)
    if variant == "f4_repair":
        return resolve_factor4_repair(cfg)
    if variant == "f4_skip_ovn":
        return replace(resolve_factor4_repair(cfg), skip_buy_after_overnight_stop=True)
    if variant == "skip_ovn_widen":
        cfg = patch_cfg(base, "stop_widen")
        return replace(cfg, skip_buy_after_overnight_stop=True)
    if variant == "tp20_prev_high":
        return replace(
            cfg,
            take_profit_levels=(0.20,),
            take_profit_reduce=1.0,
            take_profit_trigger="prev_high",
        )
    raise KeyError(variant)


VARIANTS = [
    ("baseline", "仅止损（当前默认）"),
    ("skip_ovn", "隔日止损跳买"),
    ("skip_consec2", "连续2次止损跳买"),
    ("skip_ovn_consec2", "隔日跳买 + 连止2次跳买"),
    ("stop_widen", "止损略放宽（凯盛3.5%/天通4.0%）"),
    ("f4_repair", "牛市止损放宽（既有F4参数）"),
    ("f4_skip_ovn", "F4 + 隔日跳买"),
    ("skip_ovn_widen", "隔日跳买 + 止损略放宽"),
    ("tp20_prev_high", "对照：20%昨高次日开盘全清"),
]


def run_one(cfg, daily):
    prepare_factor4(cfg, daily)
    result = run_open_break_backtest(cfg, daily)
    nav = _nav_series(result)
    m = result.metrics_df
    return {
        "result": result,
        "nav": nav,
        "ret_pct": float(metric(m, "total_return_pct")),
        "sharpe": float(metric(m, "sharpe_ratio")),
        "mdd_pct": float(metric(m, "max_drawdown_pct")),
        "win_rate": float(metric(m, "win_rate")),
        "n_trades": _n_trades(result),
        "n_trades_is": _n_trades(result, end=IS_END),
        "n_trades_oos": _n_trades(result, start=OOS_START),
    }


def yearly_excess(port: pd.Series, bh: pd.Series) -> pd.DataFrame:
    def year_end(s: pd.Series) -> pd.Series:
        return s.groupby(s.index.year).apply(lambda x: float(x.iloc[-1]))

    pe, be = year_end(port), year_end(bh.reindex(port.index).ffill())
    prev_p, prev_b = float(port.iloc[0]), float(bh.reindex(port.index).ffill().iloc[0])
    rows = []
    for yr in sorted(int(x) for x in pe.index):
        p1, b1 = float(pe.loc[yr]), float(be.loc[yr])
        rs, rb = p1 / prev_p - 1.0, b1 / prev_b - 1.0
        rows.append(
            {
                "year": yr,
                "strat_pct": round(rs * 100, 2),
                "bh_pct": round(rb * 100, 2),
                "excess_pct": round((rs - rb) * 100, 2),
            }
        )
        prev_p, prev_b = p1, b1
    return pd.DataFrame(rows)


def main() -> None:
    daily_k = load_daily(KAICHENG.daily_cache, KAICHENG.symbol)
    daily_t = load_daily(TIANTONG.daily_cache, TIANTONG.symbol)
    bh = _combo_nav(_bh_nav(daily_k), _bh_nav(daily_t))

    rows = []
    navs: dict[str, pd.Series] = {}
    yearly_map: dict[str, pd.DataFrame] = {}

    for vid, label in VARIANTS:
        print(f"== {vid} ==")
        rk = run_one(patch_cfg(KAICHENG, vid), daily_k)
        rt = run_one(patch_cfg(TIANTONG, vid), daily_t)
        combo = _combo_nav(rk["nav"], rt["nav"])
        navs[vid] = combo
        full = _window_metrics(combo)
        is_m = _window_metrics(combo, end=IS_END)
        oos = _window_metrics(combo, start=OOS_START)
        bh_full = _window_metrics(bh.reindex(combo.index).ffill())
        bh_is = _window_metrics(bh.reindex(combo.index).ffill(), end=IS_END)
        bh_oos = _window_metrics(bh.reindex(combo.index).ffill(), start=OOS_START)
        ydf = yearly_excess(combo, bh)
        yearly_map[vid] = ydf
        rows.append(
            {
                "id": vid,
                "label": label,
                "full_ret": round(full["ret_pct"], 2),
                "full_ann": round(full["ann_pct"], 2),
                "full_sharpe": round(full["sharpe"], 3),
                "full_mdd": round(full["mdd_pct"], 2),
                "full_excess": round(full["ret_pct"] - bh_full["ret_pct"], 2),
                "is_ret": round(is_m["ret_pct"], 2),
                "is_sharpe": round(is_m["sharpe"], 3),
                "is_mdd": round(is_m["mdd_pct"], 2),
                "is_excess": round(is_m["ret_pct"] - bh_is["ret_pct"], 2),
                "oos_ret": round(oos["ret_pct"], 2),
                "oos_sharpe": round(oos["sharpe"], 3),
                "oos_mdd": round(oos["mdd_pct"], 2),
                "oos_excess": round(oos["ret_pct"] - bh_oos["ret_pct"], 2),
                "kc_ret": round(rk["ret_pct"], 2),
                "kc_sharpe": round(rk["sharpe"], 3),
                "kc_mdd": round(rk["mdd_pct"], 2),
                "kc_trades": rk["n_trades"],
                "tt_ret": round(rt["ret_pct"], 2),
                "tt_sharpe": round(rt["sharpe"], 3),
                "tt_mdd": round(rt["mdd_pct"], 2),
                "tt_trades": rt["n_trades"],
                "combo_trades": rk["n_trades"] + rt["n_trades"],
                "combo_trades_is": rk["n_trades_is"] + rt["n_trades_is"],
                "combo_trades_oos": rk["n_trades_oos"] + rt["n_trades_oos"],
                "kc_win": round(
                    rk["win_rate"] * 100.0 if rk["win_rate"] <= 1.0 else rk["win_rate"],
                    1,
                ),
                "tt_win": round(
                    rt["win_rate"] * 100.0 if rt["win_rate"] <= 1.0 else rt["win_rate"],
                    1,
                ),
            }
        )

    table = pd.DataFrame(rows)
    baseline = table.loc[table["id"] == "baseline"].iloc[0]
    # IS 选择：夏普优先，回撤不超过基准 +3pp，交易更少作平手
    cand = table[table["is_mdd"] <= float(baseline["is_mdd"]) + 3.0].copy()
    if cand.empty:
        cand = table.copy()
    cand = cand.sort_values(
        ["is_sharpe", "is_excess", "combo_trades_is"],
        ascending=[False, False, True],
    )
    pick = cand.iloc[0]
    pick_oos_ok = (
        float(pick["oos_sharpe"]) + 1e-9 >= float(baseline["oos_sharpe"]) - 0.08
        and float(pick["oos_excess"]) >= float(baseline["oos_excess"]) - 15.0
    )
    decision = "replace_optional" if pick_oos_ok and pick["id"] != "baseline" else "keep_baseline"
    if pick["id"] == "baseline":
        decision = "keep_baseline"

    table.to_csv(OUT / "better_combo.csv", index=False)
    yearly_all = []
    for vid, ydf in yearly_map.items():
        tmp = ydf.copy()
        tmp.insert(0, "id", vid)
        yearly_all.append(tmp)
    pd.concat(yearly_all, ignore_index=True).to_csv(OUT / "better_yearly.csv", index=False)

    month_nav = {}
    for vid, nav in navs.items():
        m = nav.copy()
        m.index = pd.to_datetime(m.index)
        month_nav[vid] = (
            m.resample("ME").last().dropna().round(4).to_dict()
        )
    # json can't dump Timestamp keys
    month_nav_out = {
        vid: {str(k.date())[:7]: float(v) for k, v in d.items()}
        for vid, d in month_nav.items()
    }
    (OUT / "better_nav_monthly.json").write_text(
        json.dumps(
            {
                "decision": decision,
                "pick": pick["id"],
                "n_trials": N_TRIALS,
                "is": "2020-01-02~2023-12-31",
                "oos": "2024-01-02~2026-08-20",
                "nav": month_nav_out,
                "bh": {
                    str(k.date())[:7]: float(v)
                    for k, v in bh.resample("ME").last().dropna().items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# 策略1 凯盛+天通 减摩擦优化",
        "",
        "研究回测，不构成投资建议。默认 bindings 未改。",
        "",
        f"- 区间：日线缓存 {daily_k['date'].iloc[0].date()} ~ {daily_k['date'].iloc[-1].date()}",
        "- 样本内选择：2020-01-02 ~ 2023-12-31",
        "- 样本外确认：2024-01-02 ~ 2026-08-20",
        f"- 试验次数：{N_TRIALS}（事先列出，未在样本外再搜）",
        "- 组合：两票独立账户各 10 万，0.5+0.5 归一合成",
        f"- 成本：{fee_rules_text()}",
        "- 交易：开盘突破限价买、T+1、默认仅止损；变体只改跳买/止损宽度/F4/对照止盈",
        "",
        "## 组合表",
        "",
        table.to_markdown(index=False),
        "",
        "## 选择规则",
        "",
        "在样本内最大回撤不超过基准 +3 个百分点的变体里，按样本内组合夏普、再按样本内超额排序。",
        "样本外只做确认：夏普不低于基准 -0.08，超额不低于基准 -15pp。",
        "",
        f"- 样本内首选：`{pick['id']}`（{pick['label']}）",
        f"- 样本外确认：{'通过' if pick_oos_ok else '未通过'}",
        f"- 决策：`{decision}`",
        "",
        "F4 参数此前扫过含 2025 的弱年，样本外 2025 对 F4 变体有污染；若 F4 入选，只作候选不替换默认。",
        "",
        "## 分年超额（首选 vs 基准）",
        "",
        "基准：",
        yearly_map["baseline"].to_markdown(index=False),
        "",
        f"首选 {pick['id']}：",
        yearly_map[str(pick['id'])].to_markdown(index=False),
        "",
        "本报告仅供研究参考，不构成投资建议。",
    ]
    (OUT / "better_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(table.to_string(index=False))
    print("pick", pick["id"], "oos_ok", pick_oos_ok, "decision", decision)


if __name__ == "__main__":
    main()
