#!/usr/bin/env python3
"""因子13 变体：当日最快触及「开盘价+2.5%」的 3 只。

规则:
  - 股票池: hs300 / zz500 / zz1000
  - 当日用 1 分钟线找 high 首次 >= open*(1+entry_pct) 的时刻
  - 按触及时间升序取 Top3；按触及价买入；等权约 1/3 仓
  - 保留: 前一日阴/小阳、前两日累计<=5%、一字/涨停不可买、一字跌停不可卖
  - 卖出: 某日收盘/开盘-1 <= -2.5%（T+1，买入次日才可卖）

研究用途，非实盘指令。分钟线按日拉取并缓存。
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ENV_FILE = Path.home() / ".pandadata" / "pandadata.env"

UNIVERSES = {
    "hs300": {"code": "000300", "label": "沪深300", "daily": "panel_hs300_daily.parquet"},
    "zz500": {"code": "000905", "label": "中证500", "daily": "panel_zz500_daily.parquet"},
    "zz1000": {"code": "000852", "label": "中证1000", "daily": "panel_zz1000_daily.parquet"},
}

START = "20200101"
END = pd.Timestamp.today().strftime("%Y%m%d")
ENTRY_PCT = 0.025
EXIT_PCT = 0.025
SMALL_YANG = 0.01
PRIOR_2D = 0.05
TOP_K = 3
POSITION_PCT = 1.0 / TOP_K  # 等权打满约 3 只
LIMIT_TOL = 0.01
ONE_WAY_COST = 0.0
INITIAL_CASH = 1_000_000.0
FREQ = "1m"


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


_panda = None


def _pd():
    global _panda
    if _panda is None:
        import panda_data

        _load_env()
        panda_data.init_token()
        _panda = panda_data
    return _panda


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


def load_daily(universe_key: str) -> pd.DataFrame:
    path = OUT / UNIVERSES[universe_key]["daily"]
    if not path.exists():
        raise FileNotFoundError(
            f"缺少日线缓存 {path}，请先运行: python run_research.py --universe {universe_key}"
        )
    df = pd.read_parquet(path)
    df["date"] = df["date"].astype(str).str.replace("-", "").str[:8]
    if "name" in df.columns:
        df = df.loc[~df["name"].astype(str).str.contains("ST", case=False, na=False)].copy()
    for col in ("open", "high", "low", "close", "limit_up", "limit_down"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def _eligible_daily_mask(g: pd.DataFrame) -> pd.Series:
    """向量化：触及开盘+2.5% + 前日阴/小阳 + 前两日<=5% + 非涨停买不进。"""
    o, h, l, c = g["open"], g["high"], g["low"], g["close"]
    up = g["limit_up"]
    touched = (o > 0) & (h / o - 1.0 >= ENTRY_PCT)
    # 前一日 K
    o1, c1 = o.shift(1), c.shift(1)
    c3 = c.shift(3)
    prev_ok = (c1 < o1) | ((c1 > o1) & (o1 > 0) & (c1 / o1 - 1.0 <= SMALL_YANG))
    prior2_ok = ~( (c3 > 0) & (c1 / c3 - 1.0 > PRIOR_2D) )
    # 开盘/收盘涨停或一字不买（用日线近似；真正买入时还会用触及价）
    block = []
    for i in range(len(g)):
        block.append(
            _limit_up_block(
                float(o.iloc[i]) if np.isfinite(o.iloc[i]) else np.nan,
                float(h.iloc[i]) if np.isfinite(h.iloc[i]) else np.nan,
                float(l.iloc[i]) if np.isfinite(l.iloc[i]) else np.nan,
                float(c.iloc[i]) if np.isfinite(c.iloc[i]) else np.nan,
                float(up.iloc[i]) if np.isfinite(up.iloc[i]) else np.nan,
            )
        )
    not_lu = ~pd.Series(block, index=g.index)
    return touched & prev_ok.fillna(False) & prior2_ok.fillna(False) & not_lu


def first_touch_from_minutes(min_df: pd.DataFrame, day_open: float) -> tuple[str | None, float | None]:
    """返回 (datetime_str, touch_price)。"""
    if min_df is None or min_df.empty or not np.isfinite(day_open) or day_open <= 0:
        return None, None
    target = day_open * (1.0 + ENTRY_PCT)
    m = min_df.sort_values("datetime")
    for _, row in m.iterrows():
        try:
            hi = float(row["high"])
        except (TypeError, ValueError):
            continue
        if not np.isfinite(hi):
            continue
        if hi + 1e-12 >= target:
            return str(row["datetime"]), float(target)
    return None, None


def fetch_minutes_day(symbols: list[str], day: str) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    panda_data = _pd()
    chunks = []
    batch = 40  # 减小批次，降低限流概率
    for i in range(0, len(symbols), batch):
        part_syms = symbols[i : i + batch]
        part = None
        for attempt in range(6):
            try:
                part = panda_data.get_stock_min(
                    symbol=part_syms,
                    start_date=day,
                    end_date=day,
                    fields=["symbol", "date", "datetime", "minute", "open", "high", "low", "close", "volume"],
                    frequency=FREQ,
                )
                break
            except Exception as exc:
                msg = str(exc)
                # 500010: 每分钟请求次数超限
                wait = 15 + attempt * 10
                print(f"  [WARN] min {day} batch{i} try{attempt+1}: {msg[:80]} -> sleep {wait}s")
                time.sleep(wait)
        if part is not None and len(part):
            chunks.append(part)
        time.sleep(1.2)  # 稳态限速
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks, ignore_index=True)
    out["date"] = out["date"].astype(str).str.replace("-", "").str[:8]
    return out


def build_touch_table(
    daily: pd.DataFrame,
    universe_key: str,
    start: str,
    end: str,
    *,
    resume: bool = True,
) -> pd.DataFrame:
    cache = OUT / f"first_touch_{universe_key}_{start}_{end}.parquet"
    done_dates: set[str] = set()
    rows: list[dict] = []
    if resume and cache.exists():
        old = pd.read_parquet(cache)
        if len(old):
            rows = old.to_dict("records")
            done_dates = set(old["date"].astype(str))
            print(f"[resume] {cache.name} rows={len(old)} days={len(done_dates)}")

    daily = daily.loc[(daily["date"] >= start) & (daily["date"] <= end)].copy()
    # 预热需要 shift，用更大窗口算 eligible 再裁
    full = daily.copy()
    elig_parts = []
    for sym, g in full.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        g["eligible"] = _eligible_daily_mask(g)
        elig_parts.append(g)
    full = pd.concat(elig_parts, ignore_index=True)
    full = full.loc[(full["date"] >= start) & (full["date"] <= end) & full["eligible"]].copy()
    print(f"[eligible] days-symbols={len(full)} unique_days={full['date'].nunique()}")

    dates = sorted(full["date"].unique())
    pending = [d for d in dates if d not in done_dates]
    print(f"[pending] {len(pending)}/{len(dates)} days to fetch")
    t0 = time.time()
    for i, day in enumerate(pending, 1):
        day_df = full.loc[full["date"] == day]
        syms = day_df["symbol"].astype(str).tolist()
        opens = day_df.set_index("symbol")["open"].to_dict()
        mins = fetch_minutes_day(syms, day)
        if mins.empty:
            print(f"  {day} no minutes ({i}/{len(pending)})", flush=True)
            continue
        for sym in syms:
            sub = mins.loc[mins["symbol"] == sym]
            ts, px = first_touch_from_minutes(sub, float(opens.get(sym, np.nan)))
            if ts is None:
                continue
            rows.append(
                {
                    "date": day,
                    "symbol": sym,
                    "touch_time": ts,
                    "touch_price": px,
                    "open": float(opens[sym]),
                }
            )
        done_dates.add(day)
        if i % 5 == 0 or i == len(pending):
            touch_mid = pd.DataFrame(rows).drop_duplicates(["date", "symbol"], keep="last")
            touch_mid.to_parquet(cache, index=False)
            print(
                f"  touch progress {i}/{len(pending)} hits={len(touch_mid)} ({time.time()-t0:.0f}s)",
                flush=True,
            )

    touch = pd.DataFrame(rows).drop_duplicates(["date", "symbol"], keep="last")
    if touch.empty:
        raise RuntimeError("无任何首次触及记录，请检查分钟线权限/算力")
    touch.to_parquet(cache, index=False)
    print(f"[write] {cache} rows={len(touch)} days={touch['date'].nunique()}")
    return touch


def daily_picks(touch: pd.DataFrame, k: int = TOP_K) -> pd.DataFrame:
    t = touch.copy()
    t["touch_time"] = pd.to_datetime(t["touch_time"])
    t = t.sort_values(["date", "touch_time", "symbol"])
    picks = t.groupby("date", group_keys=False).head(k).copy()
    picks["rank"] = picks.groupby("date").cumcount() + 1
    return picks


def run_backtest(daily: pd.DataFrame, picks: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    # 日线面板
    wide = {}
    for col in ("open", "high", "low", "close", "limit_up", "limit_down"):
        wide[col] = daily.pivot(index="date", columns="symbol", values=col).sort_index()
    dates = [d for d in wide["close"].index.tolist() if start <= d <= end]
    pick_map = {
        d: g.sort_values("rank")[["symbol", "touch_price", "touch_time"]].to_dict("records")
        for d, g in picks.groupby("date")
    }

    cash = INITIAL_CASH
    # symbol -> {shares, buy_date}
    pos: dict[str, dict] = {}
    equity_rows = []
    trade_rows = []

    def mtm(d: str) -> float:
        eq = cash
        for sym, info in pos.items():
            px = wide["close"].at[d, sym] if sym in wide["close"].columns else np.nan
            if np.isfinite(px):
                eq += info["shares"] * float(px)
        return eq

    for d in dates:
        # 卖出（T+1）
        for sym in list(pos.keys()):
            info = pos[sym]
            if info["buy_date"] >= d:
                continue
            if sym not in wide["open"].columns:
                continue
            o = float(wide["open"].at[d, sym]) if np.isfinite(wide["open"].at[d, sym]) else np.nan
            h = float(wide["high"].at[d, sym]) if np.isfinite(wide["high"].at[d, sym]) else o
            l = float(wide["low"].at[d, sym]) if np.isfinite(wide["low"].at[d, sym]) else o
            c = float(wide["close"].at[d, sym]) if np.isfinite(wide["close"].at[d, sym]) else np.nan
            dn = float(wide["limit_down"].at[d, sym]) if np.isfinite(wide["limit_down"].at[d, sym]) else np.nan
            if not np.isfinite(o) or o <= 0 or not np.isfinite(c):
                continue
            if c / o - 1.0 > -EXIT_PCT:
                continue
            if _limit_down_lock(o, h, l, c, dn):
                continue
            sh = info["shares"]
            cash += sh * c * (1.0 - ONE_WAY_COST)
            trade_rows.append({"date": d, "symbol": sym, "side": "sell", "shares": sh, "price": c})
            pos.pop(sym)

        total = mtm(d)
        # 买入当日最快 TopK（已持仓不加仓；空缺名额才买）
        today_picks = pick_map.get(d, [])
        slots = TOP_K - len(pos)
        if slots > 0 and today_picks:
            bought = 0
            for rec in today_picks:
                if bought >= slots or cash <= 0:
                    break
                sym = rec["symbol"]
                if sym in pos:
                    continue
                px = float(rec["touch_price"])
                if px <= 0:
                    continue
                # 若开盘已涨停则跳过
                o = float(wide["open"].at[d, sym]) if sym in wide["open"].columns and np.isfinite(wide["open"].at[d, sym]) else np.nan
                up = float(wide["limit_up"].at[d, sym]) if sym in wide["limit_up"].columns and np.isfinite(wide["limit_up"].at[d, sym]) else np.nan
                if _at_limit(o, up):
                    continue
                buy_val = min(total * POSITION_PCT, cash)
                qty = int(buy_val // px // 100) * 100
                if qty <= 0:
                    continue
                cost = qty * px * (1.0 + ONE_WAY_COST)
                if cost > cash:
                    continue
                cash -= cost
                pos[sym] = {"shares": qty, "buy_date": d}
                trade_rows.append(
                    {
                        "date": d,
                        "symbol": sym,
                        "side": "buy",
                        "shares": qty,
                        "price": px,
                        "touch_time": str(rec["touch_time"]),
                    }
                )
                bought += 1
                total = mtm(d)

        equity_rows.append({"date": d, "equity": mtm(d), "cash": cash, "n_pos": len(pos)})

    eq = pd.DataFrame(equity_rows).drop_duplicates("date").set_index("date").sort_index()
    trades = pd.DataFrame(trade_rows)
    nav = eq["equity"] / INITIAL_CASH
    ret = nav.pct_change().fillna(0.0)
    dd = nav / nav.cummax() - 1.0
    n = len(nav)
    years = max(n / 252.0, 1e-9)
    end_i = int(dd.values.argmin())
    peak_i = int(nav.iloc[: end_i + 1].values.argmax()) if end_i >= 0 else 0
    summary = {
        "mode": "fastest_touch_top3",
        "universe_key": None,
        "start": dates[0],
        "end": dates[-1],
        "trading_days": n,
        "total_return": float(nav.iloc[-1] - 1.0),
        "ann_return": float(nav.iloc[-1] ** (1.0 / years) - 1.0) if nav.iloc[-1] > 0 else float("nan"),
        "max_drawdown": float(dd.min()),
        "max_dd_peak_date": str(nav.index[peak_i]),
        "max_dd_trough_date": str(nav.index[end_i]),
        "vol_ann": float(ret.std() * np.sqrt(252)) if n > 2 else float("nan"),
        "sharpe": float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else float("nan"),
        "n_trades": int(len(trades)),
        "avg_positions": float(eq["n_pos"].mean()) if len(eq) else 0.0,
        "top_k": TOP_K,
        "entry_pct": ENTRY_PCT,
        "t1": True,
    }
    eq = eq.join(pd.DataFrame({"nav": nav, "drawdown": dd}))
    return eq, trades, summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="hs300", help="hs300,zz500,zz1000")
    p.add_argument("--start", default=START)
    p.add_argument("--end", default=END)
    p.add_argument("--refresh-touch", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    key = args.universe.strip().lower()
    alias = {"000300": "hs300", "000905": "zz500", "000852": "zz1000", "中证500": "zz500", "中证1000": "zz1000", "沪深300": "hs300"}
    key = alias.get(key, key)
    if key not in UNIVERSES:
        raise SystemExit(f"未知股票池 {args.universe}")

    label = UNIVERSES[key]["label"]
    print(f"=== 最快触及开盘+{ENTRY_PCT*100:.1f}% Top{TOP_K} | {label} | {args.start}~{args.end} ===")
    daily = load_daily(key)
    touch_cache = OUT / f"first_touch_{key}_{args.start}_{args.end}.parquet"
    if args.refresh_touch and touch_cache.exists():
        touch_cache.unlink()
        print(f"[refresh] removed {touch_cache.name}")
    touch = build_touch_table(daily, key, args.start, args.end, resume=not args.refresh_touch)
    picks = daily_picks(touch, TOP_K)
    picks_path = OUT / f"picks_fastest3_{key}_{args.start}_{args.end}.csv"
    picks.to_csv(picks_path, index=False)

    eq, trades, summary = run_backtest(daily, picks, args.start, args.end)
    summary["universe_key"] = key
    summary["universe_label"] = label
    summary["universe"] = UNIVERSES[key]["code"]

    tag = f"fastest3_{key}_{args.start}_{args.end}"
    eq.to_csv(OUT / f"equity_{tag}.csv")
    trades.to_csv(OUT / f"trades_{tag}.csv", index=False)
    (OUT / f"summary_{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n========== {label} 最快3只 ==========")
    print(f"区间: {summary['start']} ~ {summary['end']} ({summary['trading_days']} 日)")
    print(f"累计收益: {summary['total_return']*100:.2f}%")
    print(f"年化收益: {summary['ann_return']*100:.2f}%")
    print(f"最大回撤: {summary['max_drawdown']*100:.2f}%")
    print(f"回撤峰谷: {summary['max_dd_peak_date']} → {summary['max_dd_trough_date']}")
    print(f"夏普: {summary['sharpe']:.3f} | 成交: {summary['n_trades']} | 日均持仓: {summary['avg_positions']:.2f}")
    print(f"名单: {picks_path}")
    print("说明: 研究回测；分钟线首次触及；T+1；未计费；不含投资建议。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
