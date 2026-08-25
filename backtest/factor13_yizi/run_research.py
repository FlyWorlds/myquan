#!/usr/bin/env python3
"""因子13 本地研究回测：2020 至今净值与最大回撤。

复现 strategy/factors/facror13.py 规则（含一字板限制）。
股票池可选：沪深300 / 中证500 / 中证1000。

用法:
  python run_research.py                  # 默认三池对比
  python run_research.py --universe zz500
  python run_research.py --universe hs300,zz500,zz1000 --refresh

研究用途，非实盘指令。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ENV_FILE = Path.home() / ".pandadata" / "pandadata.env"

UNIVERSES = {
    "hs300": {"code": "000300", "label": "沪深300", "cache": "panel_hs300_daily.parquet"},
    "zz500": {"code": "000905", "label": "中证500", "cache": "panel_zz500_daily.parquet"},
    "zz1000": {"code": "000852", "label": "中证1000", "cache": "panel_zz1000_daily.parquet"},
}

START = "20200101"
END = pd.Timestamp.today().strftime("%Y%m%d")
WARMUP_DAYS = 80
TOP_N = 10
POSITION_PCT = 0.025
ENTRY_INTRADAY = 0.025
SMALL_YANG = 0.01
PRIOR_2D = 0.05
EXIT_INTRADAY = 0.025
LIMIT_TOL = 0.01
ONE_WAY_COST = 0.0
INITIAL_CASH = 1_000_000.0


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _init_panda():
    import panda_data

    _load_env()
    panda_data.init_token()
    return panda_data


def _at_limit(price: float, lim: float, tol: float = LIMIT_TOL) -> bool:
    if not np.isfinite(price) or not np.isfinite(lim) or price <= 0 or lim <= 0:
        return False
    return abs(float(price) - float(lim)) <= max(tol, 1e-8)


def _limit_up_block(o, h, l, c, up) -> bool:
    if not np.isfinite(up) or up <= 0:
        return False
    open_at = _at_limit(o, up)
    close_at = _at_limit(c, up)
    locked = open_at and close_at and _at_limit(h, up) and _at_limit(l, up)
    return bool(open_at or close_at or locked)


def _limit_down_lock(o, h, l, c, dn) -> bool:
    if not np.isfinite(dn) or dn <= 0:
        return False
    return all(_at_limit(x, dn) for x in (o, h, l, c))


def fetch_panel(universe_key: str, force: bool = False) -> pd.DataFrame:
    meta = UNIVERSES[universe_key]
    cache = OUT / meta["cache"]
    code = meta["code"]
    label = meta["label"]

    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        print(f"[cache] {label} {cache.name} rows={len(df)}")
        return df

    panda_data = _init_panda()
    warm_start = (pd.to_datetime(START) - pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y%m%d")
    chunks = []
    years = list(range(int(warm_start[:4]), int(END[:4]) + 1))
    for y in years:
        s = max(warm_start, f"{y}0101")
        e = min(END, f"{y}1231")
        if s > e:
            continue
        print(f"[fetch] {label} get_stock_daily {s}~{e} indicator={code} ...", flush=True)
        part = panda_data.get_stock_daily(
            symbol=None,
            start_date=s,
            end_date=e,
            fields=[
                "date",
                "symbol",
                "name",
                "open",
                "high",
                "low",
                "close",
                "limit_up",
                "limit_down",
                "trade_status",
            ],
            indicator=code,
            st=False,
        )
        if part is None or len(part) == 0:
            print(f"  empty {s}~{e}")
            continue
        chunks.append(part)
        print(f"  rows={len(part)}")

    if not chunks:
        raise RuntimeError(f"{label} 行情拉取为空，请检查 panda_data 凭证与算力")

    df = pd.concat(chunks, ignore_index=True)
    df["date"] = df["date"].astype(str).str.replace("-", "").str[:8]
    df = df.drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"])
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    print(f"[write] {cache} rows={len(df)}")
    return df


def prepare(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df = df.copy()
    df["date"] = df["date"].astype(str).str.replace("-", "").str[:8]
    if "name" in df.columns:
        st_mask = df["name"].astype(str).str.contains("ST", case=False, na=False)
        df = df.loc[~st_mask].copy()

    for col in ("open", "high", "low", "close", "limit_up", "limit_down"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["momentum"] = df.groupby("symbol")["close"].pct_change(5)
    df = df.dropna(subset=["momentum", "open", "close"])

    def pivot(col: str) -> pd.DataFrame:
        return df.pivot(index="date", columns="symbol", values=col).sort_index()

    return {c: pivot(c) for c in ("open", "high", "low", "close", "limit_up", "limit_down", "momentum")}


def run_backtest(panels: dict[str, pd.DataFrame], universe_key: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    meta = UNIVERSES[universe_key]
    dates = [d for d in panels["close"].index.tolist() if START <= d <= END]
    if not dates:
        raise RuntimeError("回测区间无交易日")

    open_ = panels["open"]
    high = panels["high"]
    low = panels["low"]
    close = panels["close"]
    lim_up = panels["limit_up"]
    lim_dn = panels["limit_down"]
    mom = panels["momentum"]

    cash = INITIAL_CASH
    pos: dict[str, int] = {}
    equity_rows = []
    trade_rows = []

    def mark_to_market(d: str) -> float:
        eq = cash
        for sym, sh in pos.items():
            px = close.at[d, sym] if sym in close.columns else np.nan
            if np.isfinite(px):
                eq += sh * float(px)
        return eq

    for d in dates:
        for sym in list(pos.keys()):
            if sym not in open_.columns:
                continue
            o = float(open_.at[d, sym]) if np.isfinite(open_.at[d, sym]) else np.nan
            h = float(high.at[d, sym]) if np.isfinite(high.at[d, sym]) else o
            l = float(low.at[d, sym]) if np.isfinite(low.at[d, sym]) else o
            c = float(close.at[d, sym]) if np.isfinite(close.at[d, sym]) else np.nan
            dn = float(lim_dn.at[d, sym]) if np.isfinite(lim_dn.at[d, sym]) else np.nan
            if not np.isfinite(o) or o <= 0 or not np.isfinite(c):
                continue
            if c / o - 1.0 > -EXIT_INTRADAY:
                continue
            if _limit_down_lock(o, h, l, c, dn):
                continue
            sh = pos.pop(sym)
            cash += sh * c * (1.0 - ONE_WAY_COST)
            trade_rows.append({"date": d, "symbol": sym, "side": "sell", "shares": sh, "price": c})

        total = mark_to_market(d)
        row = mom.loc[d].dropna()
        if row.empty:
            equity_rows.append({"date": d, "equity": total, "cash": cash, "n_pos": len(pos)})
            continue
        cands = row.sort_values(ascending=False).index.tolist()[:TOP_N]

        di = panels["close"].index.get_loc(d)
        if isinstance(di, slice) or di < 3:
            equity_rows.append({"date": d, "equity": total, "cash": cash, "n_pos": len(pos)})
            continue
        d_p1 = panels["close"].index[di - 1]
        d_p3 = panels["close"].index[di - 3]

        for sym in cands:
            if cash <= 0:
                break
            if sym in pos or sym not in open_.columns:
                continue
            o = float(open_.at[d, sym]) if np.isfinite(open_.at[d, sym]) else np.nan
            h = float(high.at[d, sym]) if np.isfinite(high.at[d, sym]) else o
            l = float(low.at[d, sym]) if np.isfinite(low.at[d, sym]) else o
            c = float(close.at[d, sym]) if np.isfinite(close.at[d, sym]) else np.nan
            up = float(lim_up.at[d, sym]) if np.isfinite(lim_up.at[d, sym]) else np.nan
            if not np.isfinite(o) or o <= 0 or not np.isfinite(c) or c <= 0:
                continue
            if _limit_up_block(o, h, l, c, up):
                continue
            if c / o - 1.0 < ENTRY_INTRADAY:
                continue
            o1 = float(open_.at[d_p1, sym]) if np.isfinite(open_.at[d_p1, sym]) else np.nan
            c1 = float(close.at[d_p1, sym]) if np.isfinite(close.at[d_p1, sym]) else np.nan
            c3 = float(close.at[d_p3, sym]) if np.isfinite(close.at[d_p3, sym]) else np.nan
            if not np.isfinite(o1) or not np.isfinite(c1):
                continue
            if c1 > o1 and (o1 <= 0 or c1 / o1 - 1.0 > SMALL_YANG):
                continue
            if np.isfinite(c3) and c3 > 0 and c1 / c3 - 1.0 > PRIOR_2D:
                continue

            buy_val = min(total * POSITION_PCT, cash)
            qty = int(buy_val // c // 100) * 100
            if qty <= 0:
                continue
            cost = qty * c * (1.0 + ONE_WAY_COST)
            if cost > cash:
                continue
            cash -= cost
            pos[sym] = pos.get(sym, 0) + qty
            trade_rows.append({"date": d, "symbol": sym, "side": "buy", "shares": qty, "price": c})
            total = mark_to_market(d)

        equity_rows.append({"date": d, "equity": mark_to_market(d), "cash": cash, "n_pos": len(pos)})

    eq = pd.DataFrame(equity_rows).drop_duplicates("date").set_index("date").sort_index()
    trades = pd.DataFrame(trade_rows)
    nav = eq["equity"] / INITIAL_CASH
    ret = nav.pct_change().fillna(0.0)
    peak = nav.cummax()
    dd = nav / peak - 1.0
    max_dd = float(dd.min())
    n = len(nav)
    years = max(n / 252.0, 1e-9)
    total_ret = float(nav.iloc[-1] - 1.0)
    ann = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if nav.iloc[-1] > 0 else float("nan")
    vol = float(ret.std() * np.sqrt(252)) if n > 2 else float("nan")
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else float("nan")
    end_i = int(dd.values.argmin())
    peak_i = int(nav.iloc[: end_i + 1].values.argmax()) if end_i >= 0 else 0
    summary = {
        "universe_key": universe_key,
        "universe": meta["code"],
        "universe_label": meta["label"],
        "start": dates[0],
        "end": dates[-1],
        "trading_days": n,
        "total_return": total_ret,
        "ann_return": ann,
        "max_drawdown": max_dd,
        "max_dd_peak_date": str(nav.index[peak_i]),
        "max_dd_trough_date": str(nav.index[end_i]),
        "vol_ann": vol,
        "sharpe": sharpe,
        "final_equity": float(eq["equity"].iloc[-1]),
        "n_trades": int(len(trades)),
        "avg_positions": float(eq["n_pos"].mean()) if len(eq) else 0.0,
        "one_way_cost": ONE_WAY_COST,
        "exclude_limit_board": True,
    }
    eq = eq.join(pd.DataFrame({"nav": nav, "drawdown": dd}))
    return eq, trades, summary


def _print_summary(summary: dict) -> None:
    print(f"\n========== 因子13 | {summary['universe_label']} | 2020至今 ==========")
    print(f"区间: {summary['start']} ~ {summary['end']} ({summary['trading_days']} 日)")
    print(f"累计收益: {summary['total_return']*100:.2f}%")
    print(f"年化收益: {summary['ann_return']*100:.2f}%")
    print(f"最大回撤: {summary['max_drawdown']*100:.2f}%")
    print(f"回撤峰谷: {summary['max_dd_peak_date']} → {summary['max_dd_trough_date']}")
    print(f"波动(年化): {summary['vol_ann']*100:.2f}%")
    print(f"夏普: {summary['sharpe']:.3f}")
    print(f"成交笔数: {summary['n_trades']} | 日均持仓数: {summary['avg_positions']:.2f}")


def run_one(universe_key: str, force: bool = False) -> dict:
    raw = fetch_panel(universe_key, force=force)
    panels = prepare(raw)
    eq, trades, summary = run_backtest(panels, universe_key)
    tag = universe_key
    eq_path = OUT / f"equity_2020_now_{tag}.csv"
    tr_path = OUT / f"trades_2020_now_{tag}.csv"
    sum_path = OUT / f"summary_2020_now_{tag}.json"
    eq.to_csv(eq_path)
    trades.to_csv(tr_path, index=False)
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # 兼容旧文件名（沪深300）
    if universe_key == "hs300":
        eq.to_csv(OUT / "equity_2020_now.csv")
        trades.to_csv(OUT / "trades_2020_now.csv", index=False)
        (OUT / "summary_2020_now.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    _print_summary(summary)
    print(f"输出: {eq_path}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="因子13 多股票池研究回测")
    p.add_argument(
        "--universe",
        default="hs300,zz500,zz1000",
        help="逗号分隔: hs300,zz500,zz1000（或 000300/000905/000852）",
    )
    p.add_argument("--refresh", action="store_true", help="强制重新拉数")
    return p.parse_args(argv)


def _normalize_universe(token: str) -> str:
    t = token.strip().lower()
    alias = {
        "hs300": "hs300",
        "000300": "hs300",
        "沪深300": "hs300",
        "zz500": "zz500",
        "000905": "zz500",
        "中证500": "zz500",
        "zz1000": "zz1000",
        "000852": "zz1000",
        "中证1000": "zz1000",
    }
    if t not in alias:
        raise SystemExit(f"未知股票池 {token!r}，可选: hs300,zz500,zz1000")
    return alias[t]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    keys = [_normalize_universe(x) for x in args.universe.split(",") if x.strip()]
    # 去重保序
    seen = set()
    universes = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            universes.append(k)

    summaries = []
    for key in universes:
        summaries.append(run_one(key, force=args.refresh))

    if len(summaries) > 1:
        cmp_path = OUT / "compare_universes_2020_now.csv"
        rows = []
        for s in summaries:
            rows.append(
                {
                    "股票池": s["universe_label"],
                    "代码": s["universe"],
                    "累计收益%": round(s["total_return"] * 100, 2),
                    "年化%": round(s["ann_return"] * 100, 2),
                    "最大回撤%": round(s["max_drawdown"] * 100, 2),
                    "夏普": round(s["sharpe"], 3),
                    "成交笔数": s["n_trades"],
                    "日均持仓": round(s["avg_positions"], 2),
                }
            )
        cmp = pd.DataFrame(rows)
        cmp.to_csv(cmp_path, index=False)
        print("\n========== 三池对比 ==========")
        print(cmp.to_string(index=False))
        print(f"对比表: {cmp_path}")

    print("说明: 研究回测；收盘成交假设；未计费；不含投资建议。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
