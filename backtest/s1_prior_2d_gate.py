"""策略一拟合池：前两日累计 > X% 禁买的阈值扫描，对照现行。

A 现行：前日阴/小阳 + 禁双阳跨日≥5%（个股阈值沿用 watch_config）。
B(X)：A 全部保留，再禁 close[T-1]/close[T-3]-1 > X。
  · 默认网格扫固定 X
  · --mode 2x：X = 2 × 该票买入阈值（收盘相对收盘累计）
  · --mode span2x：关掉双阳；禁前两根 K 跨日 ≥ 2×阈值
        跨日 = 昨日收盘 / 前前日开盘 - 1（不论阴阳）

样本内 2020–2024；样本外 2025→今 对照现行。
研究用途，不改生产默认。

  python backtest/s1_prior_2d_gate.py
  python backtest/s1_prior_2d_gate.py --mode 2x
  python backtest/s1_prior_2d_gate.py --mode span2x
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
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
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.runner import run_open_break_backtest  # noqa: E402

OUT = Path(__file__).resolve().parent / "s1_prior_2d_gate"
DATA_CACHE = _MYQUAN / "data_cache"
UNIV_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
WARMUP = "20191201"
START = "20200101"
IS_END = "20241231"
OOS_START = "20250101"
CASH = 100_000.0
# None = 现行（不加这条）
X_GRID: tuple[float | None, ...] = (
    None,
    0.03,
    0.04,
    0.05,
    0.06,
    0.07,
    0.08,
    0.10,
    0.12,
    0.15,
)


def _ymd(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Shanghai") if str(t.tzinfo) != "Asia/Shanghai" else t
        t = t.tz_localize(None)
    return pd.Timestamp(t).strftime("%Y-%m-%d")


def _x_label(x: float | None) -> str:
    return "现行" if x is None else f"{x * 100:.0f}%"


def _stock_variants(mode: str, entry_pct: float) -> list[tuple[str, float | None]]:
    if mode == "2x":
        return [("现行", None), ("2倍阈值", 2.0 * float(entry_pct))]
    if mode == "span2x":
        return [("现行", None), ("两根跨日2x", 2.0 * float(entry_pct))]
    return [(_x_label(x), x) for x in X_GRID]


def watch_universe() -> list[dict]:
    rows = []
    seen: set[str] = set()
    for item in list(WATCHLIST):
        code = str(item["code"]).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "symbol": str(item.get("sina") or sina_of(code)),
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


def load_daily(symbol: str, start: str, end: str) -> pd.DataFrame | None:
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
    merged = pd.DataFrame()
    if parts:
        merged = (
            pd.concat(parts, ignore_index=True)
            .sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
        )
    start_ts = pd.Timestamp(start, tz="Asia/Shanghai")
    end_ts = pd.Timestamp(end, tz="Asia/Shanghai") + pd.Timedelta(days=1)
    if not merged.empty:
        merged = merged[(merged["date"] >= start_ts) & (merged["date"] < end_ts)]
    need_fetch = merged.empty or len(merged) < 80
    if not need_fetch:
        first = pd.Timestamp(merged["date"].iloc[0]).tz_convert("Asia/Shanghai")
        if first > start_ts + pd.Timedelta(days=400):
            need_fetch = True
    if need_fetch:
        try:
            fetched = fetch_daily(
                symbol,
                start,
                end,
                cache_path=DATA_CACHE / f"{symbol}_daily_qfq.parquet",
            )
            if fetched is not None and not fetched.empty:
                merged = fetched
        except Exception:
            if merged.empty:
                return None
    if merged is None or merged.empty or len(merged) < 60:
        return None
    return merged.reset_index(drop=True)


def prior_2d_rets(daily: pd.DataFrame) -> dict[str, float]:
    closes = daily["close"].to_numpy(dtype=float)
    dates = [_ymd(d) for d in daily["date"]]
    out: dict[str, float] = {}
    for i, day in enumerate(dates):
        if i < 3:
            out[day] = float("nan")
            continue
        c3 = float(closes[i - 3])
        if c3 <= 0:
            out[day] = float("nan")
            continue
        out[day] = float(closes[i - 1]) / c3 - 1.0
    return out


def allowed_map(rets: dict[str, float], x: float | None) -> dict[str, bool] | None:
    if x is None:
        return None
    return {d: (r != r or r <= float(x) + 1e-12) for d, r in rets.items()}


def two_bar_span(daily: pd.DataFrame) -> dict[str, float]:
    """前两根 K 跨日：昨日收 / 前前日开 - 1。缺两根时为 nan。"""
    opens = daily["open"].to_numpy(dtype=float)
    closes = daily["close"].to_numpy(dtype=float)
    dates = [_ymd(d) for d in daily["date"]]
    out: dict[str, float] = {}
    for i, day in enumerate(dates):
        if i < 2:
            out[day] = float("nan")
            continue
        o0 = float(opens[i - 2])
        if o0 <= 0:
            out[day] = float("nan")
            continue
        out[day] = float(closes[i - 1]) / o0 - 1.0
    return out


def make_cfg(meta: dict, daily: pd.DataFrame, **kw) -> BacktestConfig:
    start = max(START, pd.Timestamp(daily["date"].iloc[0]).strftime("%Y%m%d"))
    end = pd.Timestamp(daily["date"].iloc[-1]).strftime("%Y%m%d")
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
        daily_cache=DATA_CACHE / f"{meta['symbol']}_daily_qfq.parquet",
        report_path=None,
    )
    return replace(cfg, **kw) if kw else cfg


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
    return s.dropna()


def _n_buys(result, start: str | None = None, end: str | None = None) -> int:
    ed = getattr(result, "executions_df", None)
    if ed is None or ed.empty or "timestamp" not in ed.columns:
        return 0
    side = ed["side"].astype(str).str.lower()
    buys = ed.loc[side.str.contains("buy")].copy()
    if buys.empty:
        return 0
    ts = pd.to_datetime(buys["timestamp"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    ts = ts.dt.normalize()
    if start:
        ts = ts[ts >= pd.Timestamp(start)]
    if end:
        ts = ts[ts <= pd.Timestamp(end)]
    return int(ts.shape[0])


def nav_stats(nav: pd.Series) -> dict:
    if nav is None or len(nav) < 5:
        return {
            "ret_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "ann_pct": float("nan"),
        }
    s = nav.sort_index().astype(float)
    tot = float(s.iloc[-1] / s.iloc[0] - 1.0)
    rets = s.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    ann = float((1.0 + tot) ** (252 / max(len(rets), 1)) - 1.0) if tot > -1 else float("nan")
    sharpe = float((rets.mean() * 252) / vol) if vol > 1e-12 else 0.0
    dd = 1.0 - s / s.cummax()
    return {
        "ret_pct": tot * 100.0,
        "sharpe": sharpe,
        "mdd_pct": float(dd.max()) * 100.0,
        "ann_pct": ann * 100.0 if ann == ann else float("nan"),
    }


def slice_nav(nav: pd.Series, start: str, end: str | None = None) -> pd.Series:
    s = nav.sort_index()
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end) if end else s.index.max()
    out = s[(s.index >= lo) & (s.index <= hi)]
    return out


def ew_nav(navs: dict[str, pd.Series]) -> pd.Series:
    if not navs:
        return pd.Series(dtype=float)
    df = pd.concat(navs, axis=1).sort_index().ffill()
    df = df.dropna(how="all")
    first = df.apply(lambda col: col.dropna().iloc[0] if col.notna().any() else np.nan)
    norm = df.divide(first)
    return norm.mean(axis=1).dropna()


def run_one(cfg: BacktestConfig, daily: pd.DataFrame):
    result = run_open_break_backtest(cfg, daily)
    m = result.metrics_df
    return {
        "ret_pct": float(metric(m, "total_return_pct")),
        "sharpe": float(metric(m, "sharpe_ratio")),
        "mdd_pct": float(metric(m, "max_drawdown_pct")),
        "n_trades": float(metric(m, "closed_trade_count")),
        "end_mv": float(metric(m, "end_market_value")),
        "nav": _nav_series(result),
        "result": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="策略一前两日累计禁买对照")
    parser.add_argument(
        "--mode",
        choices=("grid", "2x", "span2x"),
        default="grid",
        help="grid=固定累计X；2x=累计>2×阈值；span2x=关掉双阳、禁两根K跨日≥2×阈值",
    )
    args = parser.parse_args()
    mode = str(args.mode)

    OUT.mkdir(parents=True, exist_ok=True)
    univ = watch_universe()
    end = pd.Timestamp.today().strftime("%Y%m%d")
    print(f"策略一拟合池 {len(univ)} 只 · 日线 {WARMUP}→{end}")
    print(f"IS {START}–{IS_END}；OOS {OOS_START}→今 对照现行")
    if mode == "span2x":
        print(
            "B=阴/小阳保留、关掉双阳；禁前两根K跨日 "
            "昨日收/前前日开-1 ≥ 2×该票阈值"
        )
    elif mode == "2x":
        print("B=现行过门 + 前两日累计 > 2×该票阈值 禁买（2.5%→5%，3%→6%，2%→4%）")
    else:
        print("B(X)=现行过门 + 前两日累计 close[T-1]/close[T-3]-1 > X 禁买")
    print("研究回测，非投资建议。\n")

    dailies: dict[str, pd.DataFrame] = {}
    rets_map: dict[str, dict[str, float]] = {}
    span_map: dict[str, dict[str, float]] = {}
    metas = {m["symbol"]: m for m in univ}
    for meta in univ:
        daily = load_daily(meta["symbol"], WARMUP, end)
        if daily is None:
            print(f"  skip {meta['name']} {meta['symbol']} 无日线")
            continue
        cut = pd.Timestamp("2020-01-01", tz="Asia/Shanghai")
        bt = daily.loc[daily["date"] >= cut].reset_index(drop=True)
        if len(bt) < 60:
            print(f"  skip {meta['name']} {meta['symbol']} bars={len(bt)}")
            continue
        dailies[meta["symbol"]] = bt
        rets_map[meta["symbol"]] = prior_2d_rets(daily)
        span_map[meta["symbol"]] = two_bar_span(daily)
        extra = ""
        if mode in ("2x", "span2x"):
            extra = f" → 2X={meta['entry_pct']*200:g}%"
        print(
            f"  {meta['name']} {meta['symbol']}  "
            f"{_ymd(bt['date'].iloc[0])}→{_ymd(bt['date'].iloc[-1])}  n={len(bt)}  "
            f"±{meta['entry_pct']*100:g}%{extra}"
        )

    symbols = list(dailies)
    n_var = 2 if mode in ("2x", "span2x") else len(X_GRID)
    print(f"\n可回测 {len(symbols)} 只 × {n_var} 档 = {len(symbols)*n_var} 次\n")

    labels = [lab for lab, _ in _stock_variants(mode, 0.025)]
    store: dict[str, dict[str, dict]] = {lab: {} for lab in labels}

    for i, sym in enumerate(symbols, 1):
        meta = metas[sym]
        daily = dailies[sym]
        print(f"[{i}/{len(symbols)}] {meta['name']}")
        src = span_map[sym] if mode == "span2x" else rets_map[sym]
        for lab, x in _stock_variants(mode, float(meta["entry_pct"])):
            gate = allowed_map(src, x)
            kw: dict = {}
            if gate is not None:
                kw["energy_allowed_by_date"] = dict(gate)
            if mode == "span2x" and lab != "现行":
                kw["ban_double_yang"] = False
            cfg = make_cfg(meta, daily, **kw)
            store[lab][sym] = run_one(cfg, daily)

    rows = []
    combo_rows = []
    per_x_navs: dict[str, dict[str, pd.Series]] = {}
    for lab in labels:
        navs = {s: store[lab][s]["nav"] for s in symbols if s in store[lab]}
        per_x_navs[lab] = navs
        ew_full = ew_nav(navs)
        ew_is = slice_nav(ew_full, "2020-01-01", "2024-12-31")
        ew_oos = slice_nav(ew_full, "2025-01-01")
        st_full = nav_stats(ew_full)
        st_is = nav_stats(ew_is)
        st_oos = nav_stats(ew_oos)
        n_is = int(np.nanmean([_n_buys(store[lab][s]["result"], "2020-01-01", "2024-12-31") for s in navs]))
        n_oos = int(np.nanmean([_n_buys(store[lab][s]["result"], "2025-01-01") for s in navs]))
        combo_rows.append(
            {
                "X": lab,
                "IS收益%": round(st_is["ret_pct"], 2),
                "IS夏普": round(st_is["sharpe"], 4),
                "IS回撤%": round(st_is["mdd_pct"], 2),
                "OOS收益%": round(st_oos["ret_pct"], 2),
                "OOS夏普": round(st_oos["sharpe"], 4),
                "OOS回撤%": round(st_oos["mdd_pct"], 2),
                "全样本收益%": round(st_full["ret_pct"], 2),
                "全样本夏普": round(st_full["sharpe"], 4),
                "全样本回撤%": round(st_full["mdd_pct"], 2),
                "IS均买入": n_is,
                "OOS均买入": n_oos,
                "n_stocks": len(navs),
            }
        )
        for s in symbols:
            if s not in store[lab]:
                continue
            nav = store[lab][s]["nav"]
            st_i = nav_stats(slice_nav(nav, "2020-01-01", "2024-12-31"))
            st_o = nav_stats(slice_nav(nav, "2025-01-01"))
            rows.append(
                {
                    "X": lab,
                    "symbol": s,
                    "name": metas[s]["name"],
                    "entry_pct": metas[s]["entry_pct"],
                    "x_used": (
                        None
                        if lab == "现行"
                        else (
                            2.0 * float(metas[s]["entry_pct"])
                            if lab in ("2倍阈值", "两根跨日2x")
                            else float(str(lab).replace("%", "")) / 100.0
                        )
                    ),
                    "IS收益%": st_i["ret_pct"],
                    "IS夏普": st_i["sharpe"],
                    "IS回撤%": st_i["mdd_pct"],
                    "OOS收益%": st_o["ret_pct"],
                    "OOS夏普": st_o["sharpe"],
                    "OOS回撤%": st_o["mdd_pct"],
                    "全样本收益%": store[lab][s]["ret_pct"],
                    "全样本夏普": store[lab][s]["sharpe"],
                    "全样本回撤%": store[lab][s]["mdd_pct"],
                    "全样本闭环": store[lab][s]["n_trades"],
                    "IS买入": _n_buys(store[lab][s]["result"], "2020-01-01", "2024-12-31"),
                    "OOS买入": _n_buys(store[lab][s]["result"], "2025-01-01"),
                }
            )

    combo = pd.DataFrame(combo_rows)
    per = pd.DataFrame(rows)
    combo_name = {
        "2x": "combo_2x.csv",
        "span2x": "combo_span2x.csv",
    }.get(mode, "combo_by_x.csv")
    per_name = {
        "2x": "per_stock_2x.csv",
        "span2x": "per_stock_span2x.csv",
    }.get(mode, "per_stock.csv")
    sum_name = {
        "2x": "summary_2x.json",
        "span2x": "summary_span2x.json",
    }.get(mode, "summary.json")
    combo.to_csv(OUT / combo_name, index=False, encoding="utf-8-sig")
    per.to_csv(OUT / per_name, index=False, encoding="utf-8-sig")

    cur = combo[combo["X"] == "现行"].iloc[0]
    cur_is = per[per["X"] == "现行"].set_index("symbol")
    beat_is = {}
    beat_oos = {}
    for lab in combo["X"]:
        if lab == "现行":
            continue
        g = per[per["X"] == lab].set_index("symbol")
        beat_is[lab] = int((g["IS夏普"] > cur_is["IS夏普"]).sum())
        beat_oos[lab] = int((g["OOS夏普"] > cur_is.reindex(g.index)["OOS夏普"]).sum())

    print("\n========== 等权组合（独立账户净值平均，不每日再平衡）==========")
    print(combo.to_string(index=False))

    if mode in ("2x", "span2x"):
        alt_lab = "两根跨日2x" if mode == "span2x" else "2倍阈值"
        alt = combo[combo["X"] == alt_lab].iloc[0]
        print(
            f"\n{alt_lab} vs 现行：IS 收益 {alt['IS收益%'] - cur['IS收益%']:+.2f} pct / "
            f"夏普 {alt['IS夏普'] - cur['IS夏普']:+.4f}；"
            f"OOS 收益 {alt['OOS收益%'] - cur['OOS收益%']:+.2f} pct / "
            f"夏普 {alt['OOS夏普'] - cur['OOS夏普']:+.4f} / "
            f"回撤 {alt['OOS回撤%'] - cur['OOS回撤%']:+.2f} pct。"
            f"IS 个股夏普优于现行 {beat_is.get(alt_lab, 0)}/{len(symbols)}；"
            f"OOS {beat_oos.get(alt_lab, 0)}/{len(symbols)}。"
        )
        better = alt_lab if alt["OOS收益%"] > cur["OOS收益%"] else "现行"
        print(f"OOS 累计收益更优: {better}。研究用途，非投资建议。")
        rec = {
            "mode": mode,
            "rule": (
                "span=prev_close/prev2_open-1 >= 2*entry_pct; no double-yang"
                if mode == "span2x"
                else "prior_2d close[T-1]/close[T-3]-1 > 2*entry_pct"
            ),
            "universe": [metas[s]["name"] for s in symbols],
            "n": len(symbols),
            "current": cur.to_dict(),
            "alt": alt.to_dict(),
            "beat_is": beat_is,
            "beat_oos": beat_oos,
            "disclaimer": "研究回测，非投资建议。未改生产默认。",
        }
    else:
        scored = combo.copy()
        scored["_xnum"] = scored["X"].map(
            lambda v: 99.0 if v == "现行" else float(str(v).replace("%", ""))
        )
        scored = scored.sort_values(["IS夏普", "_xnum"], ascending=[False, False])
        best_row = scored.iloc[0]
        best_lab = str(best_row["X"])
        print(
            f"\n样本内所选 X = {best_lab}"
            f"（IS夏普 {best_row['IS夏普']:.4f} vs 现行 {cur['IS夏普']:.4f}）"
        )
        if best_lab != "现行":
            print(
                f"样本外 {best_lab}: 收益 {best_row['OOS收益%']:.2f}% / 夏普 {best_row['OOS夏普']:.4f} / "
                f"回撤 {best_row['OOS回撤%']:.2f}%  vs 现行 "
                f"{cur['OOS收益%']:.2f}% / {cur['OOS夏普']:.4f} / {cur['OOS回撤%']:.2f}%"
            )
            print(
                f"IS 个股夏普优于现行: {beat_is.get(best_lab, 0)}/{len(symbols)}；"
                f"OOS: {beat_oos.get(best_lab, 0)}/{len(symbols)}"
            )
        else:
            print("样本内最优是现行（不加前两日累计过滤）。")
        if "5%" in set(combo["X"]):
            r5 = combo[combo["X"] == "5%"].iloc[0]
            print(
                f"\n参考 5%: IS夏普 {r5['IS夏普']:.4f}（现行 {cur['IS夏普']:.4f}）；"
                f"OOS收益 {r5['OOS收益%']:.2f}% vs 现行 {cur['OOS收益%']:.2f}%"
            )
        rec = {
            "mode": "grid",
            "universe": [metas[s]["name"] for s in symbols],
            "n": len(symbols),
            "x_grid": [_x_label(x) for x in X_GRID],
            "pick_rule": "max IS equal-weight Sharpe; tie → larger X",
            "picked_x": best_lab,
            "current": cur.to_dict(),
            "picked": best_row.drop(labels=["_xnum"], errors="ignore").to_dict(),
            "beat_is": beat_is,
            "beat_oos": beat_oos,
            "disclaimer": "研究回测，非投资建议。未改生产默认。",
        }

    (OUT / sum_name).write_text(
        json.dumps(rec, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n产物: {OUT / combo_name}")
    print("研究用途，非投资建议。未改策略一默认过门。")


if __name__ == "__main__":
    main()
