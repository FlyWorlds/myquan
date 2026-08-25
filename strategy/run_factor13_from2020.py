"""因子13·qy_blend：2015–fit 熊特征选股 → 2020 起槽位回测总收益。

  · 日线回补至 2015（本地原缓存约从 2018 起）
  · 年/季面板 thr=±2.5%，覆盖 2015–2026
  · 每年末用 fit_start=2015…fit_end 选 Top5 → 次年交易
  · 5 槽等权，等止损再换

  python strategy/run_factor13_from2020.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_SCRIPT = str(Path(__file__).resolve().parent)
if _SCRIPT in sys.path:
    sys.path.remove(_SCRIPT)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import (  # noqa: E402
    _metrics_from_equity,
    simulate_open_break,
)
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402
from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.factor13_bear_shield import select_top  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)

OUT = _MYQUAN / "backtest" / "factor13_from2020"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
PANEL_Y = OUT / "year_panel_2015.parquet"
PANEL_Q = OUT / "quarter_panel_2015.parquet"

FIT_START = 2015
THR = 0.025
TOP_K = 5
N_SLOTS = 5
INITIAL_CASH = 500_000.0
TARGET_PCT = 0.95
LOT = 100
BT_START = "20200101"
BT_END = "20260825"
MIN_BARS_Y = 80
MIN_BARS_Q = 35
WORKERS = 8
FETCH_WORKERS = 12
SELECT_PARAMS = {"rule": "qy_blend", "top_k": TOP_K, "fit_start_year": FIT_START, "thr": THR}


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def mainboard_symbols() -> list[str]:
    out = []
    for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet")):
        sym = fp.name.replace("_daily_qfq.parquet", "")
        if _is_mainboard(sym):
            out.append(sym)
    return out


def _needs_backfill(symbol: str) -> bool:
    p = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return True
    d = pd.to_datetime(pd.read_parquet(p, columns=["date"])["date"]).dt.tz_localize(None)
    return bool(d.min() > pd.Timestamp("2015-06-30"))


def _backfill_one(symbol: str) -> tuple[str, str]:
    try:
        fetch_daily(
            symbol,
            "20150101",
            BT_END,
            cache_path=UNIV_CACHE / f"{symbol}_daily_qfq.parquet",
        )
        return symbol, "ok"
    except Exception as exc:  # noqa: BLE001
        return symbol, f"err:{exc}"


def backfill_to_2015(symbols: list[str]) -> None:
    todo = [s for s in symbols if _needs_backfill(s)]
    print(f"日线回补 2015：需更新 {len(todo)}/{len(symbols)}")
    if not todo:
        return
    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = [ex.submit(_backfill_one, s) for s in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            sym, st = fut.result()
            if st == "ok":
                ok += 1
            else:
                err += 1
                if err <= 5:
                    print(f"  fail {sym} {st}")
            if i % 50 == 0 or i == len(todo):
                print(f"  fetch {i}/{len(todo)} ok={ok} err={err} ({time.time()-t0:.0f}s)")


def load_daily_from(symbol: str, start: str = "20150101") -> pd.DataFrame | None:
    cache = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not cache.exists():
        return None
    d = pd.read_parquet(cache).copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[d["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    return d if len(d) else None


def _count_trades(holding: np.ndarray) -> int:
    if len(holding) < 2:
        return 0
    return int(np.sum(np.diff(holding.astype(int)) > 0))


def process_symbol_panels(task: dict) -> list[dict]:
    symbol = task["symbol"]
    name = task["name"]
    daily = load_daily_from(symbol, "20150101")
    if daily is None or len(daily) < MIN_BARS_Y:
        return []
    dates = pd.DatetimeIndex(daily["date"])
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    rows: list[dict] = []
    mainboard = 1 if _is_mainboard(symbol) else 0

    def one_window(mask: np.ndarray, period: str, kind: str, min_bars: int) -> None:
        idx = np.where(mask)[0]
        if len(idx) < min_bars:
            return
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        c_y = c[i0:i1]
        # 窗口内独立模拟，避免跨期持仓泄漏
        eq_w, hold_w = simulate_open_break(o[i0:i1], h[i0:i1], l[i0:i1], c[i0:i1], thr=THR)
        met = _metrics_from_equity(eq_w, c_y)
        mdd = float(met["max_drawdown_pct"])
        bh_dd = float(met["bh_max_drawdown_pct"])
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "kind": kind,
                "period": period,
                "year": int(str(period)[:4]),
                "n_bars": int(len(eq_w)),
                "mainboard": mainboard,
                "thr": THR,
                "ret": float(met["total_return_pct"]),
                "sharpe": float(met["sharpe_ratio"]),
                "mdd": mdd,
                "bh": float(met["bh_return_pct"]),
                "bh_dd": bh_dd,
                "excess": float(met["excess_return_pct"]),
                "dd_improve": float(met["dd_improve_pct"]),
                "trades": float(_count_trades(hold_w)),
            }
        )

    for y in range(FIT_START, 2027):
        one_window(dates.year == y, str(y), "year", MIN_BARS_Y)
    periods = dates.to_period("Q")
    for p in sorted(set(periods)):
        if p.year < FIT_START:
            continue
        one_window(periods == p, str(p), "quarter", MIN_BARS_Q)
    return rows


def build_panels(force: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    OUT.mkdir(parents=True, exist_ok=True)
    if PANEL_Y.exists() and PANEL_Q.exists() and not force:
        print(f"加载 {PANEL_Y.name} / {PANEL_Q.name}")
        return pd.read_parquet(PANEL_Y), pd.read_parquet(PANEL_Q)

    name_map = _name_map()
    tasks = [{"symbol": s, "name": name_map.get(s, "")} for s in mainboard_symbols()]
    print(f"构建 2015–2026 年/季面板 × {len(tasks)} …")
    rows: list[dict] = []
    t0 = time.time()
    # 线程池：避免 ProcessPool + mini_racer 崩溃
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process_symbol_panels, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                rows.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
                print("panel err", exc)
            if done % 100 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} rows={len(rows)} ({time.time()-t0:.0f}s)")
    df = pd.DataFrame(rows)
    y = df[df["kind"] == "year"].copy()
    q = df[df["kind"] == "quarter"].copy()
    y.to_parquet(PANEL_Y, index=False)
    q.to_parquet(PANEL_Q, index=False)
    print(f"年面板 {y.shape} 季面板 {q.shape}")
    return y, q


def build_targets(year_panel: pd.DataFrame, q_panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # fit_end 2019 → 交易 2020 … fit_end 2025 → 交易 2026
    for fit_y in range(2019, 2026):
        picks = select_top(
            year_panel,
            fit_end_year=fit_y,
            params=SELECT_PARAMS,
            quarter_panel=q_panel,
        )
        if picks.empty:
            print(f"  fit={fit_y}: 空名单，放宽季熊门槛再试")
            picks = select_top(
                year_panel,
                fit_end_year=fit_y,
                params={**SELECT_PARAMS, "min_q_obear": 2, "min_q_ex": 0.0, "min_obear": 1},
                quarter_panel=q_panel,
            )
        if picks.empty:
            print(f"  fit={fit_y}: 仍空")
            continue
        trade_from = f"{fit_y + 1}-01-01"
        for i, r in picks.iterrows():
            rows.append(
                {
                    "fit_end_year": fit_y,
                    "trade_from": trade_from,
                    "rank": int(i) + 1,
                    "symbol": str(r["symbol"]).lower(),
                    "name": str(r.get("name", "")),
                    "score": float(r.get("score", np.nan)),
                    "n_obear": int(r.get("n_obear", 0)),
                    "obear_ex": float(r.get("obear_ex", np.nan)),
                    "q_n_obear": int(r.get("q_n_obear", 0)),
                    "q_obear_ex": float(r.get("q_obear_ex", np.nan)),
                }
            )
        print(
            f"  {trade_from}: "
            + "、".join(picks["name"].astype(str).tolist())
        )
    return pd.DataFrame(rows)


@dataclass
class Slot:
    cash: float
    symbol: str | None = None
    shares: float = 0.0
    buy_i: int = -1
    entry_px: float = 0.0


@dataclass
class PathData:
    dates: pd.DatetimeIndex
    date_to_i: dict
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray


def load_paths(symbols: list[str]) -> dict[str, PathData]:
    out: dict[str, PathData] = {}
    for sym in symbols:
        daily = load_daily_from(sym, "20190101")
        if daily is None or len(daily) < 80:
            continue
        dates = pd.DatetimeIndex(daily["date"]).normalize()
        out[sym] = PathData(
            dates=dates,
            date_to_i={pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)},
            o=daily["open"].to_numpy(float),
            h=daily["high"].to_numpy(float),
            l=daily["low"].to_numpy(float),
            c=daily["close"].to_numpy(float),
        )
    return out


def _calendar(paths: dict[str, PathData], start: str, end: str) -> pd.DatetimeIndex:
    all_dates: set = set()
    for p in paths.values():
        all_dates.update(p.dates.tolist())
    cal = pd.DatetimeIndex(sorted(all_dates)).normalize()
    return cal[(cal >= pd.Timestamp(start)) & (cal <= pd.Timestamp(end))]


def _nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 2:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    ret = float(nav.iloc[-1] / nav.iloc[0] - 1) * 100
    dd = float((nav / nav.cummax() - 1).min() * 100)
    r = nav.pct_change().dropna()
    sh = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 1e-12 else np.nan
    return {"ret": ret, "mdd": abs(dd), "sharpe": sh}


def yearly_slice(eq: pd.Series) -> pd.DataFrame:
    rows = []
    for y, g in eq.groupby(eq.index.year):
        nav = g / float(g.iloc[0])
        st = _nav_stats(nav)
        rows.append({"year": int(y), **st})
    return pd.DataFrame(rows)


def run_slots(targets: pd.DataFrame, paths: dict[str, PathData]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    by_from: dict[str, list[str]] = {}
    for tf, g in targets.groupby("trade_from"):
        by_from[str(tf)] = g.sort_values("rank")["symbol"].tolist()

    cal = _calendar(paths, BT_START, BT_END)
    slots = [Slot(cash=INITIAL_CASH / N_SLOTS) for _ in range(N_SLOTS)]
    target: list[str] = []
    equity_rows, events = [], []

    prior = [tf for tf in by_from if tf <= "2020-01-01"]
    if prior:
        target = by_from[max(prior)]
    elif by_from:
        target = by_from[min(by_from)]

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        key = dt.strftime("%Y-%m-%d")
        month_days = cal[cal.to_period("M") == dt.to_period("M")]
        if len(month_days) and dt == month_days[0]:
            tf_cands = [tf for tf in by_from if tf[:7] == dt.strftime("%Y-%m")]
            if tf_cands:
                target = by_from[min(tf_cands)]

        target_syms = set(target)

        for si, slot in enumerate(slots):
            if not slot.symbol or slot.shares <= 0:
                continue
            path = paths.get(slot.symbol)
            if path is None:
                continue
            j = path.date_to_i.get(dt)
            if j is None:
                continue
            oi, hi, li, ci = float(path.o[j]), float(path.h[j]), float(path.l[j]), float(path.c[j])
            if oi <= 0:
                continue
            stop_px = stop_trigger_price(oi, stop_pct=THR, tick=TICK_SIZE)
            if j > slot.buy_i and li <= stop_px + 1e-12:
                prev_c = float(path.c[j - 1]) if j > 0 else ci
                lim = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=0.10,
                    tick=TICK_SIZE,
                )
                if not bool(lim["locked"]):
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px) * (1.0 - SLIP)
                    proceeds = slot.shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    events.append(
                        {"date": key, "slot": si, "side": "sell_stop", "symbol": slot.symbol, "px": sell_px, "shares": slot.shares}
                    )
                    slot.shares = 0.0
                    slot.symbol = None
                    slot.buy_i = -1
                    slot.entry_px = 0.0

        held = {s.symbol for s in slots if s.symbol and s.shares > 0}
        for slot in slots:
            if slot.shares <= 0 and slot.symbol and slot.symbol not in target_syms:
                slot.symbol = None
        pending = {s.symbol for s in slots if s.symbol and s.shares <= 0}

        for si, slot in enumerate(slots):
            if slot.shares > 0:
                continue
            if slot.symbol is None:
                assign = None
                for sym in target:
                    if sym in held or sym in pending or sym not in paths:
                        continue
                    if any(s.symbol == sym for s in slots if s is not slot):
                        continue
                    assign = sym
                    break
                if assign is None:
                    continue
                slot.symbol = assign
                pending.add(assign)
                events.append({"date": key, "slot": si, "side": "assign", "symbol": assign, "px": np.nan, "shares": 0.0})

            path = paths.get(slot.symbol)
            if path is None:
                continue
            j = path.date_to_i.get(dt)
            if j is None or j < 1:
                continue
            oi, hi, li, ci = float(path.o[j]), float(path.h[j]), float(path.l[j]), float(path.c[j])
            po, pc = float(path.o[j - 1]), float(path.c[j - 1])
            if oi <= 0:
                continue
            buy_px = entry_trigger_price(oi, entry_pct=THR, tick=TICK_SIZE)
            allows = prev_day_allows_entry(po, pc, prev_small_yang_pct=THR, prev_entry_mode="yin_or_small_yang")
            blocked = False
            if j >= 2:
                blocked = should_block_entry_by_yang(
                    float(path.o[j - 2]),
                    float(path.c[j - 2]),
                    po,
                    pc,
                    tick=TICK_SIZE,
                    ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                    ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                    double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                    double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                )
            if allows and (not blocked) and (hi + 1e-12 >= buy_px) and slot.cash > 0:
                px = buy_px * (1.0 + SLIP)
                budget = slot.cash * TARGET_PCT
                raw = math.floor(budget / (px * LOT)) * LOT
                if raw >= LOT:
                    cost = raw * px
                    fee = cost * COMMISSION
                    if cost + fee <= slot.cash:
                        slot.cash -= cost + fee
                        slot.shares = float(raw)
                        slot.entry_px = px
                        slot.buy_i = j
                        held.add(slot.symbol)
                        events.append(
                            {"date": key, "slot": si, "side": "buy", "symbol": slot.symbol, "px": px, "shares": slot.shares}
                        )

        total = 0.0
        n_held = 0
        for slot in slots:
            if slot.symbol and slot.shares > 0:
                path = paths.get(slot.symbol)
                j = path.date_to_i.get(dt) if path else None
                if path is not None and j is not None:
                    total += slot.cash + slot.shares * float(path.c[j])
                else:
                    total += slot.cash + slot.shares * slot.entry_px
                n_held += 1
            else:
                total += slot.cash
        equity_rows.append({"date": dt, "equity": total, "n_held": n_held})

    eq = pd.DataFrame(equity_rows).set_index("date").sort_index()
    ev = pd.DataFrame(events)
    st = _nav_stats(eq["equity"] / float(eq["equity"].iloc[0]))
    st["n_buys"] = int((ev["side"] == "buy").sum()) if len(ev) else 0
    st["n_stops"] = int((ev["side"] == "sell_stop").sum()) if len(ev) else 0
    st["avg_held"] = float(eq["n_held"].mean()) if len(eq) else 0.0
    return eq, ev, st


def fixed_ew_stitch(targets: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """分年目标池票内独立模拟后等权，再按年拼接（研究口径）。"""
    yearly_rows = []
    pieces = []
    for tf, g in targets.groupby("trade_from"):
        y = int(str(tf)[:4])
        start, end = f"{y}0101", (BT_END if y >= 2026 else f"{y}1231")
        navs = {}
        for _, r in g.sort_values("rank").iterrows():
            sym = str(r["symbol"])
            daily = load_daily_from(sym, "20190101")
            if daily is None:
                continue
            dates = pd.DatetimeIndex(daily["date"]).normalize()
            eq, _ = simulate_open_break(
                daily["open"].to_numpy(float),
                daily["high"].to_numpy(float),
                daily["low"].to_numpy(float),
                daily["close"].to_numpy(float),
                thr=THR,
            )
            s = pd.Series(eq, index=dates)
            s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
            if len(s) < 5:
                continue
            navs[sym] = s / float(s.iloc[0])
        if not navs:
            continue
        df = pd.concat(navs, axis=1).sort_index().ffill()
        port = (1 + df.pct_change().mean(axis=1).fillna(0)).cumprod()
        port.iloc[0] = 1.0
        st = _nav_stats(port)
        yearly_rows.append({"year": y, **st, "names": "、".join(g.sort_values("rank")["name"].tolist())})
        # 拼接到总净值：乘上一年末水平
        if not pieces:
            pieces.append(port)
        else:
            level = float(pieces[-1].iloc[-1])
            pieces.append(port * level)
    full = pd.concat(pieces).sort_index()
    full = full[~full.index.duplicated(keep="last")]
    return full, pd.DataFrame(yearly_rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    syms = mainboard_symbols()
    print(f"主板池 {len(syms)}")
    backfill_to_2015(syms)

    year_panel, q_panel = build_panels(force=False)
    print("\n=== 年频选股（2015→fit_end 熊特征）===")
    targets = build_targets(year_panel, q_panel)
    targets.to_csv(OUT / "targets_year.csv", index=False, float_format="%.4f")

    pick_syms = sorted(targets["symbol"].unique())
    print(f"\n加载交易路径 {len(pick_syms)}")
    paths = load_paths(pick_syms)
    print(f"  ok={len(paths)}")

    print("\n=== 槽位回测 2020→今 ===")
    eq, ev, st = run_slots(targets, paths)
    eq.to_csv(OUT / "nav_slot.csv")
    ev.to_csv(OUT / "events_slot.csv", index=False)
    ydf = yearly_slice(eq["equity"])
    ydf.to_csv(OUT / "yearly_slot.csv", index=False, float_format="%.4f")
    print(f"  全段={st['ret']:+.1f}% mdd={st['mdd']:.1f}% sh={st['sharpe']:.2f} buys={st['n_buys']}")
    print("  ", ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ydf.itertuples()))

    print("\n=== 研究等权（票内独立·年拼）===")
    ew, ewy = fixed_ew_stitch(targets)
    ew.to_csv(OUT / "nav_ew_stitch.csv")
    ewy.to_csv(OUT / "yearly_ew.csv", index=False, float_format="%.4f")
    ste = _nav_stats(ew / float(ew.iloc[0]))
    print(f"  全段={ste['ret']:+.1f}% mdd={ste['mdd']:.1f}% sh={ste['sharpe']:.2f}")
    print("  ", ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ewy.itertuples()))

    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>2020起总收益</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border:1px solid #ddd;padding:6px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}} .kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
</style></head><body>
<h1>qy_blend · 2015熊特征选股 · 2020起回测</h1>
<p>阈值 ±2.5%；年更 Top5；槽位等止损再换。选股窗 fit_start={FIT_START}。</p>
<div class=kpi>
<div><b>槽位总收益</b><br>{st['ret']:+.1f}%</div>
<div><b>最大回撤</b><br>{st['mdd']:.1f}%</div>
<div><b>夏普</b><br>{st['sharpe']:.2f}</div>
<div><b>研究等权总收益</b><br>{ste['ret']:+.1f}%</div>
</div>
<h2>分年目标池</h2>
{targets.round(3).to_html(index=False)}
<h2>槽位分年</h2>
{ydf.round(2).to_html(index=False)}
<h2>研究等权分年</h2>
{ewy.round(2).to_html(index=False)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "meta.json").write_text(
        json.dumps(
            {
                "fit_start": FIT_START,
                "bt": {"start": BT_START, "end": BT_END},
                "thr": THR,
                "slot": st,
                "ew": ste,
                "params": SELECT_PARAMS,
            },
            ensure_ascii=False,
            indent=2,
            default=float,
        ),
        encoding="utf-8",
    )
    print(f"\n→ {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
