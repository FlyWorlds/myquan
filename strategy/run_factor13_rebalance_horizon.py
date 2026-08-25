"""换股周期对比：目标池按 M/Q/半年/年更新；持仓等策略止损后再换槽。

  python strategy/run_factor13_rebalance_horizon.py

规则：
  · 选股信号：默认 qy_blend Top5（季+年熊盾）
  · 信号刷新：month / quarter / semi / year
  · 资金：K 个独立槽位等权；空仓槽才接入当前目标池中尚未持有的票
  · 持仓中只按开盘突破止损卖出，不因换股名单变化强制平仓
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
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

from backtest.factor1_monthly_top3 import load_daily, simulate_open_break  # noqa: E402
from strategy.costs import (  # noqa: E402
    ENGINE_COMMISSION_RATE as COMMISSION,
    SLIPPAGE_VALUE as SLIP,
    STAMP_TAX_RATE as STAMP,
)
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

OUT = _MYQUAN / "backtest" / "factor13_rebalance_horizon"
YEAR_PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"

THR = 0.025
TOP_K = 5
N_SLOTS = 5
INITIAL_CASH = 500_000.0  # 5 槽 × 10万
TARGET_PCT = 0.95
LOT = 100
BT_START = "20230101"
BT_END = "20260825"
WORKERS = 8


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def _selection_dates(freq: str, start: str, end: str) -> list[pd.Timestamp]:
    """信号日（期末）；次一交易日起用新目标。"""
    idx = pd.period_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="M")
    dates: list[pd.Timestamp] = []
    for p in idx:
        ts = p.to_timestamp(how="end").normalize()
        if freq == "month":
            dates.append(ts)
        elif freq == "quarter":
            if p.month in (3, 6, 9, 12):
                dates.append(ts)
        elif freq == "semi":
            if p.month in (6, 12):
                dates.append(ts)
        elif freq == "year":
            if p.month == 12:
                dates.append(ts)
        else:
            raise ValueError(freq)
    return dates


def _fit_end_year(asof: pd.Timestamp) -> int:
    """年特征：仅用已完整结束的日历年；12/31 当日记入当年。"""
    if asof.month == 12 and asof.day >= 28:
        return int(asof.year)
    return int(asof.year) - 1


def build_targets(
    year_panel: pd.DataFrame,
    q_panel: pd.DataFrame,
    freq: str,
    *,
    top_k: int = TOP_K,
) -> pd.DataFrame:
    """每行：signal_date, trade_from, rank, symbol, name, score"""
    rows = []
    for sig in _selection_dates(freq, "20211201", BT_END):
        fit_y = _fit_end_year(sig)
        if fit_y < 2022:
            continue
        # 季度面板截断到 signal 日所在季及之前
        q = q_panel.copy()
        q = q[q["kind"] == "quarter"] if "kind" in q.columns else q
        q["q"] = pd.PeriodIndex(q["period"].astype(str), freq="Q")
        q_asof = pd.Period(sig, freq="Q")
        q = q[q["q"] <= q_asof]
        picks = select_top(
            year_panel,
            fit_end_year=fit_y,
            params={"rule": "qy_blend", "top_k": top_k},
            quarter_panel=q,
        )
        if picks.empty:
            continue
        # 交易生效：下一自然月月初（由日历对齐到交易日）
        trade_from = (sig + pd.offsets.MonthBegin(1)).normalize()
        for i, r in picks.iterrows():
            rows.append(
                {
                    "freq": freq,
                    "signal_date": sig.strftime("%Y-%m-%d"),
                    "fit_end_year": fit_y,
                    "trade_from": trade_from.strftime("%Y-%m-%d"),
                    "rank": int(i) + 1,
                    "symbol": str(r["symbol"]),
                    "name": str(r.get("name", "")),
                    "score": float(r.get("score", np.nan)),
                }
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


def _load_path_task(symbol: str) -> tuple[str, PathData | None]:
    daily = load_daily(symbol)
    if daily is None or len(daily) < 80:
        return symbol, None
    dates = pd.DatetimeIndex(pd.to_datetime(daily["date"]))
    if getattr(dates, "tz", None) is not None:
        dates = dates.tz_localize(None)
    dates = dates.normalize()
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    # 预跑一次只为对齐；槽位引擎自行按规则买卖
    return symbol, PathData(
        dates=dates,
        date_to_i={pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)},
        o=o,
        h=h,
        l=l,
        c=c,
    )


def load_paths(symbols: list[str]) -> dict[str, PathData]:
    out: dict[str, PathData] = {}
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_load_path_task, s) for s in symbols]
        for fut in as_completed(futs):
            sym, path = fut.result()
            if path is not None:
                out[sym] = path
    return out


def _calendar(paths: dict[str, PathData], start: str, end: str) -> pd.DatetimeIndex:
    # 用出现最多交易日的票作日历近似：并集后 sort
    all_dates = set()
    for p in paths.values():
        all_dates.update(p.dates.tolist())
    cal = pd.DatetimeIndex(sorted(all_dates)).normalize()
    return cal[(cal >= pd.Timestamp(start)) & (cal <= pd.Timestamp(end))]


def run_slot_portfolio(
    targets: pd.DataFrame,
    paths: dict[str, PathData],
    *,
    name_map: dict[str, str],
    n_slots: int = N_SLOTS,
    thr: float = THR,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """目标池按 trade_from 切换；持仓等止损再换。"""
    # trade_from -> ordered symbols
    by_from: dict[str, list[str]] = {}
    for tf, g in targets.groupby("trade_from"):
        by_from[str(tf)] = g.sort_values("rank")["symbol"].tolist()

    cal = _calendar(paths, BT_START, BT_END)
    slot_cash0 = INITIAL_CASH / n_slots
    slots = [Slot(cash=slot_cash0) for _ in range(n_slots)]
    target: list[str] = []
    equity_rows = []
    events = []

    # 初始目标：BT_START 前最近一期
    prior = [tf for tf in by_from if tf <= BT_START]
    if prior:
        target = by_from[max(prior)]
    elif by_from:
        target = by_from[min(by_from)]

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        key = dt.strftime("%Y-%m-%d")
        # 月初对齐：若本月1日不在日历，用本月第一个交易日切换
        month_start = dt.to_period("M").to_timestamp().strftime("%Y-%m-%d")
        if dt == cal[cal.to_period("M") == dt.to_period("M")][0]:
            # 找本月对应的 trade_from（月初）
            tf_candidates = [tf for tf in by_from if tf[:7] == dt.strftime("%Y-%m")]
            if tf_candidates:
                target = by_from[min(tf_candidates)]
            elif month_start in by_from:
                target = by_from[month_start]

        # 1) 止损卖出
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
            stop_px = stop_trigger_price(oi, stop_pct=thr, tick=TICK_SIZE)
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
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                    sell_px *= 1.0 - SLIP
                    proceeds = slot.shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    events.append(
                        {
                            "date": key,
                            "slot": si,
                            "side": "sell_stop",
                            "symbol": slot.symbol,
                            "name": name_map.get(slot.symbol, ""),
                            "px": sell_px,
                            "shares": slot.shares,
                        }
                    )
                    slot.shares = 0.0
                    slot.symbol = None
                    slot.buy_i = -1
                    slot.entry_px = 0.0

        # 2) 空仓槽：若挂着不在目标池的票则清空标记；再分配目标
        held = {s.symbol for s in slots if s.symbol and s.shares > 0}
        for slot in slots:
            if slot.shares <= 0 and slot.symbol and slot.symbol not in target:
                slot.symbol = None
        pending = {s.symbol for s in slots if s.symbol and s.shares <= 0}

        for si, slot in enumerate(slots):
            if slot.shares > 0:
                continue
            if slot.symbol is None:
                assign = None
                for sym in target:
                    if sym in held or sym in pending:
                        continue
                    if any(s.symbol == sym for s in slots if s is not slot):
                        continue
                    if sym not in paths:
                        continue
                    assign = sym
                    break
                if assign is None:
                    continue
                slot.symbol = assign
                pending.add(assign)
                events.append(
                    {
                        "date": key,
                        "slot": si,
                        "side": "assign",
                        "symbol": assign,
                        "name": name_map.get(assign, ""),
                        "px": np.nan,
                        "shares": 0.0,
                    }
                )

            # 尝试按开盘突破买入
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
            buy_px = entry_trigger_price(oi, entry_pct=thr, tick=TICK_SIZE)
            allows = prev_day_allows_entry(
                po, pc, prev_small_yang_pct=thr, prev_entry_mode="yin_or_small_yang"
            )
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
                            {
                                "date": key,
                                "slot": si,
                                "side": "buy",
                                "symbol": slot.symbol,
                                "name": name_map.get(slot.symbol, ""),
                                "px": px,
                                "shares": slot.shares,
                            }
                        )

        # 3) 盯市
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
        equity_rows.append(
            {
                "date": dt,
                "equity": total,
                "n_held": n_held,
                "n_target": len(target),
                "target": ",".join(target),
            }
        )

    eq = pd.DataFrame(equity_rows).set_index("date").sort_index()
    ev = pd.DataFrame(events)
    stats = _nav_stats(eq["equity"] / float(eq["equity"].iloc[0]))
    stats["n_buys"] = int((ev["side"] == "buy").sum()) if len(ev) else 0
    stats["n_stops"] = int((ev["side"] == "sell_stop").sum()) if len(ev) else 0
    stats["n_assigns"] = int((ev["side"] == "assign").sum()) if len(ev) else 0
    # 换股次数：止损后 assign 到不同票
    stats["avg_held"] = float(eq["n_held"].mean()) if len(eq) else 0.0
    return eq, ev, stats


def _nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 2:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    rets = nav.pct_change().dropna()
    tot = (float(nav.iloc[-1]) - 1) * 100
    vol = float(rets.std() * np.sqrt(252)) if len(rets) else 0.0
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    ann = float(nav.iloc[-1]) ** (1 / years) - 1 if float(nav.iloc[-1]) > 0 else 0.0
    return {
        "ret": tot,
        "mdd": float((1 - nav / nav.cummax()).max()) * 100,
        "sharpe": (ann / vol) if vol > 1e-12 else 0.0,
    }


def yearly_slice(eq: pd.Series) -> pd.DataFrame:
    rows = []
    for y, g in eq.groupby(eq.index.year):
        if len(g) < 5:
            continue
        nav = g / float(g.iloc[0])
        st = _nav_stats(nav)
        rows.append({"year": int(y), **st})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    name_map = _name_map()
    year_panel = pd.read_parquet(YEAR_PANEL)
    q_panel = pd.read_parquet(Q_PANEL)

    freqs = ["month", "quarter", "semi", "year"]
    all_targets = []
    print("=== 生成目标池 ===")
    for freq in freqs:
        t0 = time.time()
        tg = build_targets(year_panel, q_panel, freq, top_k=TOP_K)
        tg.to_csv(OUT / f"targets_{freq}.csv", index=False)
        all_targets.append(tg)
        n_chg = 0
        prev = None
        for tf, g in tg.groupby("trade_from"):
            cur = tuple(g.sort_values("rank")["symbol"].tolist())
            if prev is not None and cur != prev:
                n_chg += 1
            prev = cur
        print(f"  {freq:8s} signals={tg.signal_date.nunique()} changes={n_chg} ({time.time()-t0:.1f}s)")

    symbols = sorted({s for tg in all_targets for s in tg["symbol"].unique()})
    print(f"加载路径 {len(symbols)} …")
    paths = load_paths(symbols)
    print(f"  ok={len(paths)}")

    summary = []
    print("\n=== 槽位回测（等止损再换）===")
    for freq, tg in zip(freqs, all_targets):
        eq, ev, st = run_slot_portfolio(tg, paths, name_map=name_map)
        eq.to_csv(OUT / f"nav_{freq}.csv")
        ev.to_csv(OUT / f"events_{freq}.csv", index=False)
        ydf = yearly_slice(eq["equity"])
        ydf.to_csv(OUT / f"yearly_{freq}.csv", index=False)
        # 2026 YTD
        eq26 = eq.loc[eq.index >= "2026-01-01", "equity"]
        st26 = _nav_stats(eq26 / float(eq26.iloc[0])) if len(eq26) > 5 else {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
        rec = {
            "freq": freq,
            "ret_2023_now": st["ret"],
            "mdd": st["mdd"],
            "sharpe": st["sharpe"],
            "ret_2026": st26["ret"],
            "mdd_2026": st26["mdd"],
            "n_buys": st["n_buys"],
            "n_stops": st["n_stops"],
            "n_assigns": st["n_assigns"],
            "avg_held": st["avg_held"],
            "turnover_proxy": st["n_stops"],  # 止损次数≈换股机会
        }
        summary.append(rec)
        print(
            f"  {freq:8s} 全段={st['ret']:+6.1f}% mdd={st['mdd']:5.1f}% sharpe={st['sharpe']:.2f}  "
            f"2026={st26['ret']:+6.1f}%  buys={st['n_buys']} stops={st['n_stops']} avg_held={st['avg_held']:.2f}"
        )
        if len(ydf):
            print("           分年:", ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ydf.itertuples()))

    sdf = pd.DataFrame(summary)
    sdf.to_csv(OUT / "summary.csv", index=False, float_format="%.4f")

    # 名单稳定度：相邻期 Jaccard
    stab = []
    for freq, tg in zip(freqs, all_targets):
        sets = []
        for tf, g in tg.groupby("trade_from"):
            sets.append((tf, set(g["symbol"])))
        jac = []
        for i in range(1, len(sets)):
            a, b = sets[i - 1][1], sets[i][1]
            jac.append(len(a & b) / max(len(a | b), 1))
        stab.append({"freq": freq, "avg_jaccard": float(np.mean(jac)) if jac else 1.0, "n_periods": len(sets)})
    pdf = pd.DataFrame(stab)
    pdf.to_csv(OUT / "stability.csv", index=False, float_format="%.4f")
    print("\n名单稳定度(Jaccard):")
    print(pdf.to_string(index=False))

    best = sdf.sort_values(["sharpe", "ret_2023_now"], ascending=False).iloc[0]
    meta = {
        "rule": "qy_blend Top5 slots, wait stop then rotate",
        "bt": {"start": BT_START, "end": BT_END},
        "best_freq": str(best["freq"]),
        "summary": summary,
        "stability": stab,
        "note": "月频与季频若名单不变则表现接近；qy_blend 信号主要在季末/年末变化。",
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>换股周期</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:980px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border:1px solid #ddd;padding:6px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}} .kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
</style></head><body>
<h1>换股周期 · 等止损再换</h1>
<p>选股 qy_blend Top5；{N_SLOTS} 槽等权；持仓只止损卖出，空仓槽接入最新目标池。</p>
<div class=kpi>
<div><b>推荐</b><br>{best['freq']}</div>
<div><b>全段收益</b><br>{best['ret_2023_now']:+.1f}%</div>
<div><b>夏普</b><br>{best['sharpe']:.2f}</div>
<div><b>2026</b><br>{best['ret_2026']:+.1f}%</div>
</div>
<h2>对比</h2>
{sdf.round(2).to_html(index=False)}
<h2>名单稳定度</h2>
{pdf.round(3).to_html(index=False)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    print(f"\n推荐频率: {best['freq']}")
    print("→", OUT / "report.html")


if __name__ == "__main__":
    main()
