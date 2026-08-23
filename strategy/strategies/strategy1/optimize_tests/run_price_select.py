"""策略1 价格选股：周频冻结 Top5，补置顶票空窗。

不覆盖 bindings。产物在本目录 price_select_* 。

  python strategy/strategies/strategy1/optimize_tests/run_price_select.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from holdingStocks.watch_config import (  # noqa: E402
    WATCHLIST,
    limit_down_pct_of,
    sina_of,
)
from strategy import BacktestConfig  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.costs import stamp_tax_for_code  # noqa: E402
from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.runner import run_open_break_backtest  # noqa: E402
from strategy.s1_price_select import (  # noqa: E402
    panel_price_factors,
    weekly_topk_allowed,
)

OUT = Path(__file__).resolve().parent / "price_select"
DATA_CACHE = _MYQUAN / "data_cache"
UNIV_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
START = "20200101"
END = "20260820"
OOS = pd.Timestamp("2024-01-01")
IS_END = pd.Timestamp("2023-12-31")
CASH = 100_000.0
TOP_K = 5
PINNED = {"sh600552", "sh600330"}
N_TRIALS = 8


def load_daily(symbol: str) -> pd.DataFrame | None:
    paths = [
        UNIV_CACHE / f"{symbol}_daily_qfq.parquet",
        DATA_CACHE / f"{symbol}_daily_qfq.parquet",
    ]
    parts: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty or "date" not in df.columns:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
        else:
            df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        df["symbol"] = symbol
        parts.append(df)
    if not parts:
        return None
    merged = (
        pd.concat(parts, ignore_index=True)
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
    )
    start = pd.Timestamp(START).tz_localize("Asia/Shanghai")
    end = pd.Timestamp(END).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    merged = merged[(merged["date"] >= start) & (merged["date"] < end)]
    if len(merged) < 80:
        return None
    return merged.reset_index(drop=True)


def watch_universe() -> list[dict]:
    rows, seen = [], set()
    for item in list(WATCHLIST):
        code = str(item["code"]).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "symbol": sina_of(code),
                "name": item["name"],
                "entry_pct": float(item.get("entry_pct") or item.get("pct") or DEFAULT_PCT),
                "stop_pct": float(item.get("stop_pct") or item.get("pct") or DEFAULT_PCT),
                "tick": float(item.get("tick") or 0.01),
                "t0": bool(item.get("t0", False)),
                "limit_down_pct": float(
                    item.get("limit_down_pct") or limit_down_pct_of(code)
                ),
                "stamp_tax_rate": stamp_tax_for_code(code),
            }
        )
    return rows


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
        pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize()
    ).dropna().sort_index()


def _buy_days(result) -> set[str]:
    df = getattr(result, "executions_df", None)
    if df is None or getattr(df, "empty", True):
        return set()
    ts_col = next((c for c in ("timestamp", "time", "datetime", "date") if c in df.columns), None)
    side_col = "side" if "side" in df.columns else None
    if ts_col is None or side_col is None:
        return set()
    buys = df[df[side_col].astype(str).str.lower().str.contains("buy")]
    days = pd.to_datetime(buys[ts_col])
    if getattr(days.dt, "tz", None) is not None:
        days = days.dt.tz_localize(None)
    return set(days.dt.strftime("%Y-%m-%d"))


def run_one(meta: dict, daily: pd.DataFrame, allowed: dict[str, bool] | None = None):
    start = max(START, pd.Timestamp(daily["date"].iloc[0]).strftime("%Y%m%d"))
    end = min(END, pd.Timestamp(daily["date"].iloc[-1]).strftime("%Y%m%d"))
    cfg = BacktestConfig(
        symbol=meta["symbol"],
        symbol_name=meta["name"],
        em_symbol=meta["code"],
        threshold_pct=float(meta["entry_pct"]),
        entry_pct=float(meta["entry_pct"]),
        stop_pct=float(meta["stop_pct"]),
        start_date=start,
        end_date=end,
        initial_cash=CASH,
        tick=float(meta["tick"]),
        t0=bool(meta["t0"]),
        limit_down_pct=float(meta["limit_down_pct"]),
        stamp_tax_rate=float(meta["stamp_tax_rate"]),
        energy_allowed_by_date=dict(allowed or {}),
    )
    result = run_open_break_backtest(cfg, daily)
    return {
        "nav": _nav_series(result),
        "buy_days": _buy_days(result),
        "n_trades": float(metric(result.metrics_df, "closed_trade_count")),
        "ret_pct": float(metric(result.metrics_df, "total_return_pct")),
    }


def window_metrics(eq: pd.Series, start=None, end=None) -> dict:
    s = eq.dropna().astype(float).sort_index()
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if len(s) < 5:
        return {"ret_pct": float("nan"), "sharpe": float("nan"), "mdd_pct": float("nan")}
    tot = float(s.iloc[-1] / s.iloc[0] - 1.0)
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    rets = s.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    dd = 1.0 - s / s.cummax()
    return {
        "ret_pct": tot * 100.0,
        "sharpe": sharpe,
        "mdd_pct": float(dd.max()) * 100.0,
        "ann_pct": ann * 100.0,
    }


def active_nav(
    navs: dict[str, pd.Series],
    allowed: dict[str, dict[str, bool]] | None,
    *,
    always: set[str] | None = None,
) -> pd.Series:
    """所选名单等权；无名单日视为现金（收益 0）。"""
    df = pd.concat(navs, axis=1).sort_index().ffill()
    rets = df.pct_change()
    always = {str(x) for x in (always or set())}
    out = []
    for ts, row in rets.iterrows():
        key = pd.Timestamp(ts).strftime("%Y-%m-%d")
        names = []
        if allowed is None:
            names = [c for c in rets.columns if pd.notna(row.get(c))]
        else:
            for c in rets.columns:
                if c in always or bool((allowed.get(c) or {}).get(key, False)):
                    if pd.notna(row.get(c)):
                        names.append(c)
        out.append(float(row[names].mean()) if names else 0.0)
    nav = (1.0 + pd.Series(out, index=rets.index)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def rank_ic(panel: pd.DataFrame, col: str, horizon: int) -> pd.Series:
    df = panel.copy()
    df["_d"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.sort_values(["symbol", "_d"])
    df["fwd"] = df.groupby("symbol")["close"].shift(-horizon) / df["close"] - 1.0
    mkt = df.groupby("_d")["fwd"].transform("mean")
    df["ex"] = df["fwd"] - mkt
    ics = []
    for day, g in df.groupby("_d"):
        g = g.dropna(subset=[col, "ex"])
        if len(g) < 8:
            continue
        ics.append((day, float(g[col].corr(g["ex"], method="spearman"))))
    if not ics:
        return pd.Series(dtype=float)
    s = pd.Series({d: v for d, v in ics})
    return s.dropna()


def ic_stats(s: pd.Series) -> dict:
    if s.empty:
        return {"mean": float("nan"), "ir": float("nan"), "n": 0}
    mu = float(s.mean())
    sd = float(s.std())
    return {"mean": mu, "ir": mu / sd if sd > 1e-12 else float("nan"), "n": int(len(s))}


def buy_coverage(buy_map: dict[str, set[str]], dates: list[str]) -> float:
    if not dates:
        return float("nan")
    hit = 0
    for d in dates:
        if any(d in days for days in buy_map.values()):
            hit += 1
    return hit / len(dates)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metas = {m["symbol"]: m for m in watch_universe()}
    dailies = {}
    for sym, meta in metas.items():
        daily = load_daily(sym)
        if daily is not None:
            dailies[sym] = daily
    metas = {k: v for k, v in metas.items() if k in dailies}
    print(f"universe {len(dailies)}")

    panel = panel_price_factors(dailies)
    ic_rows = []
    for col, label in (
        ("px_near_high", "near_high20"),
        ("px_trend", "trend60"),
        ("px_mom", "mom20"),
        ("px_persist", "persist20"),
        ("px_composite", "composite"),
    ):
        for hz in (5, 20):
            s = rank_ic(panel, col, hz)
            st = ic_stats(s)
            is_s = s[s.index < OOS]
            oos_s = s[s.index >= OOS]
            ic_rows.append(
                {
                    "factor": label,
                    "horizon": hz,
                    "ic": round(st["mean"], 4),
                    "icir": round(st["ir"], 3) if st["ir"] == st["ir"] else None,
                    "n": st["n"],
                    "is_ic": round(float(is_s.mean()), 4) if len(is_s) else None,
                    "oos_ic": round(float(oos_s.mean()), 4) if len(oos_s) else None,
                }
            )
            print(f"  IC {label} {hz}d mean={st['mean']:.4f} IR={st['ir']:.3f}")
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(OUT / "ic.csv", index=False)

    gates = {
        "weekly_near_high": weekly_topk_allowed(panel, value_col="px_near_high", k=TOP_K),
        "weekly_trend": weekly_topk_allowed(panel, value_col="px_trend", k=TOP_K),
        "weekly_mom": weekly_topk_allowed(panel, value_col="px_mom", k=TOP_K),
        "weekly_persist": weekly_topk_allowed(panel, value_col="px_persist", k=TOP_K),
        "weekly_composite": weekly_topk_allowed(panel, value_col="px_composite", k=TOP_K),
        "pinned2_plus_top3": weekly_topk_allowed(
            panel,
            value_col="px_composite",
            always=PINNED,
            extra_k=3,
        ),
    }

    print("baseline always-on ...")
    base = {}
    for sym, daily in dailies.items():
        base[sym] = run_one(metas[sym], daily, allowed=None)

    variants: list[tuple[str, str, dict | None, set[str] | None]] = [
        ("pinned2", "凯盛+天通始终可做", None, PINNED),
        ("watch26", "观察池26只始终可做", None, None),
        ("weekly_near_high", "周频近20日高点 Top5", gates["weekly_near_high"], None),
        ("weekly_trend", "周频站上60日均线 Top5", gates["weekly_trend"], None),
        ("weekly_mom", "周频20日动量 Top5", gates["weekly_mom"], None),
        ("weekly_persist", "周频20日上涨日占比 Top5", gates["weekly_persist"], None),
        ("weekly_composite", "周频综合分 Top5", gates["weekly_composite"], None),
        ("pinned2_plus_top3", "置顶2只 + 综合分 Top3", gates["pinned2_plus_top3"], PINNED),
    ]

    gated_cache: dict[str, dict[str, dict]] = {}
    rows = []
    navs_out = {}
    all_dates = sorted(
        {
            pd.Timestamp(x).tz_localize(None).normalize().strftime("%Y-%m-%d")
            for daily in dailies.values()
            for x in daily["date"]
        }
    )
    oos_dates = [d for d in all_dates if d >= "2024-01-01"]

    for vid, label, gate, always in variants:
        print(f"== {vid} ==")
        if gate is None:
            use = {s: base[s] for s in (always or base)}
        else:
            if vid not in gated_cache:
                gated_cache[vid] = {}
                for sym, daily in dailies.items():
                    gated_cache[vid][sym] = run_one(
                        metas[sym], daily, allowed=gate.get(sym)
                    )
            use = gated_cache[vid]
            if always:
                use = {**use, **{s: base[s] for s in always if s in base}}
        navs = {s: use[s]["nav"] for s in use}
        if gate is None and always is not None:
            combo = active_nav(navs, None, always=always)
        elif gate is None:
            combo = active_nav(navs, None)
        else:
            combo = active_nav(navs, gate, always=always)
        navs_out[vid] = combo
        full = window_metrics(combo)
        is_m = window_metrics(combo, end=IS_END)
        oos = window_metrics(combo, start=OOS)
        buys = {s: use[s]["buy_days"] for s in use}
        if always is not None and gate is None:
            buys = {s: buys[s] for s in always}
        n_trades = sum(use[s]["n_trades"] for s in buys)
        rows.append(
            {
                "id": vid,
                "label": label,
                "full_ret": round(full["ret_pct"], 2),
                "full_sharpe": round(full["sharpe"], 3),
                "full_mdd": round(full["mdd_pct"], 2),
                "is_ret": round(is_m["ret_pct"], 2),
                "is_sharpe": round(is_m["sharpe"], 3),
                "is_mdd": round(is_m["mdd_pct"], 2),
                "oos_ret": round(oos["ret_pct"], 2),
                "oos_sharpe": round(oos["sharpe"], 3),
                "oos_mdd": round(oos["mdd_pct"], 2),
                "n_trades": int(n_trades),
                "buy_day_pct": round(100 * buy_coverage(buys, all_dates), 2),
                "oos_buy_day_pct": round(100 * buy_coverage(buys, oos_dates), 2),
            }
        )

    table = pd.DataFrame(rows)
    table.to_csv(OUT / "combo.csv", index=False)
    print(table.to_string(index=False))

    base_row = table.loc[table["id"] == "pinned2"].iloc[0]
    cand = table[~table["id"].isin(["pinned2", "watch26"])].copy()
    cand = cand[cand["is_mdd"] <= float(base_row["is_mdd"]) + 8.0]
    if cand.empty:
        cand = table[~table["id"].isin(["pinned2", "watch26"])].copy()
    cand = cand.sort_values(["is_sharpe", "is_ret"], ascending=[False, False])
    pick = cand.iloc[0] if len(cand) else base_row
    oos_ok = (
        float(pick["oos_sharpe"]) + 1e-9 >= float(base_row["oos_sharpe"]) - 0.15
        and float(pick["oos_ret"]) >= float(base_row["oos_ret"]) - 40.0
    )
    # 空窗：买点覆盖率要明显高于两票
    cover_ok = float(pick["buy_day_pct"]) >= float(base_row["buy_day_pct"]) + 3.0
    if pick["id"] == "pinned2":
        decision = "keep_pinned2"
    elif oos_ok:
        decision = "adopt_weekly_overlay"
    else:
        decision = "research_only"

    month = {}
    for vid, nav in navs_out.items():
        m = nav.copy()
        m.index = pd.to_datetime(m.index)
        month[vid] = {
            str(k.date())[:7]: float(v)
            for k, v in m.resample("ME").last().dropna().items()
        }
    (OUT / "nav_monthly.json").write_text(
        json.dumps(
            {
                "decision": decision,
                "pick": str(pick["id"]),
                "oos_ok": bool(oos_ok),
                "cover_ok": bool(cover_ok),
                "n_trials": N_TRIALS,
                "nav": month,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# 策略1 价格选股（因子10）",
        "",
        "研究 overlay，不替换默认 bindings。不构成投资建议。",
        "",
        "- 宇宙：盯盘 26 只（置顶凯盛/天通/科创综指 + 拟合池）",
        "- 时点：T 收盘算分，本周最后交易日排名，下一周才允许因子1 新开仓",
        f"- 事先 {N_TRIALS} 组：两票、26 只等权、4 个单因子周频 Top5、综合分、置顶2+Top3",
        "- 样本内 2020-2023，样本外 2024-01-02 起",
        "- 组合：入选名单等权跑策略1 仅止损；未入选日现金",
        "",
        "## Rank IC",
        "",
        ic_df.to_markdown(index=False),
        "",
        "## 组合",
        "",
        table.to_markdown(index=False),
        "",
        f"- 样本内首选：`{pick['id']}`（{pick['label']}）",
        f"- 样本外确认：{'通过' if oos_ok else '未通过'}",
        f"- 买点覆盖是否高于两票：{'是' if cover_ok else '否'}",
        f"- 决策：`{decision}`",
        "",
        "日频动能 Top5 已否。本实验只问周频价格名单能不能补空窗且不明显伤样本外。",
        "",
        "本报告仅供研究参考，不构成投资建议。",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("pick", pick["id"], "oos_ok", oos_ok, "cover_ok", cover_ok, "decision", decision)


if __name__ == "__main__":
    main()
