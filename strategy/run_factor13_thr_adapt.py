"""个股阈值择优：买入/止损同用 ±2% / ±2.5% / ±3%（开盘价）。

规则：
  · 选股仍用年频 qy_blend Top5
  · 交易年 T：用 T-1 年三阈值回测夏普最高者作为该票阈值（无前瞻）
  · 买入触发 +thr、止损 -thr，同一 thr
  · 槽位：等止损后再换；对照固定 2%/2.5%/3%

  python strategy/run_factor13_thr_adapt.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
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
from strategy.run_factor13_rebalance_horizon import (  # noqa: E402
    PathData,
    _calendar,
    _nav_stats,
    yearly_slice,
    BT_START,
    BT_END,
    INITIAL_CASH,
    N_SLOTS,
    TARGET_PCT,
    LOT,
    TOP_K,
)

OUT = _MYQUAN / "backtest" / "factor13_thr_adapt"
YEAR_PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
WF_PANEL = _MYQUAN / "backtest" / "factor13_walkforward" / "year_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
THRESHOLDS = (0.02, 0.025, 0.03)


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


@dataclass
class Slot:
    cash: float
    symbol: str | None = None
    thr: float = 0.025
    shares: float = 0.0
    buy_i: int = -1
    entry_px: float = 0.0


def load_paths_serial(symbols: list[str]) -> dict[str, PathData]:
    out: dict[str, PathData] = {}
    for sym in symbols:
        daily = load_daily(sym)
        if daily is None or len(daily) < 80:
            continue
        dates = pd.DatetimeIndex(pd.to_datetime(daily["date"]))
        if getattr(dates, "tz", None) is not None:
            dates = dates.tz_localize(None)
        dates = dates.normalize()
        out[sym] = PathData(
            dates=dates,
            date_to_i={pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)},
            o=daily["open"].to_numpy(float),
            h=daily["high"].to_numpy(float),
            l=daily["low"].to_numpy(float),
            c=daily["close"].to_numpy(float),
        )
    return out


def build_annual_targets(year_panel: pd.DataFrame, q_panel: pd.DataFrame, wf: pd.DataFrame) -> pd.DataFrame:
    """每年末选股 → 次年交易；附带 fit 年 thr_best。"""
    rows = []
    for fit_y in range(2022, 2026):
        picks = select_top(
            year_panel,
            fit_end_year=fit_y,
            params={"rule": "qy_blend", "top_k": TOP_K},
            quarter_panel=q_panel,
        )
        if picks.empty:
            continue
        sub = wf[(wf["year"] == fit_y) & (wf["mainboard"].astype(int) == 1)].copy()
        sub["symbol"] = sub["symbol"].astype(str).str.lower()
        thr_map = sub.drop_duplicates("symbol").set_index("symbol")["thr_best"].to_dict()
        trade_from = f"{fit_y + 1}-01-01"
        for i, r in picks.iterrows():
            sym = str(r["symbol"]).lower()
            thr = float(thr_map.get(sym, 0.025))
            if thr not in THRESHOLDS:
                thr = 0.025
            rows.append(
                {
                    "fit_end_year": fit_y,
                    "trade_from": trade_from,
                    "rank": int(i) + 1,
                    "symbol": sym,
                    "name": str(r.get("name", "")),
                    "thr": thr,
                    "score": float(r.get("score", np.nan)),
                }
            )
    return pd.DataFrame(rows)


def run_slots(
    targets: pd.DataFrame,
    paths: dict[str, PathData],
    name_map: dict[str, str],
    *,
    thr_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """thr_mode: adapt | 0.02 | 0.025 | 0.03"""
    by_from: dict[str, list[dict]] = {}
    for tf, g in targets.groupby("trade_from"):
        items = []
        for _, r in g.sort_values("rank").iterrows():
            thr = float(r["thr"]) if thr_mode == "adapt" else float(thr_mode)
            items.append({"symbol": str(r["symbol"]), "thr": thr, "name": str(r["name"])})
        by_from[str(tf)] = items

    cal = _calendar(paths, BT_START, BT_END)
    slots = [Slot(cash=INITIAL_CASH / N_SLOTS) for _ in range(N_SLOTS)]
    target: list[dict] = []
    equity_rows, events = [], []

    prior = [tf for tf in by_from if tf <= BT_START]
    if prior:
        target = by_from[max(prior)]
    elif by_from:
        target = by_from[min(by_from)]

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        key = dt.strftime("%Y-%m-%d")
        if len(cal[cal.to_period("M") == dt.to_period("M")]) and dt == cal[cal.to_period("M") == dt.to_period("M")][0]:
            tf_cands = [tf for tf in by_from if tf[:7] == dt.strftime("%Y-%m")]
            if tf_cands:
                target = by_from[min(tf_cands)]

        target_syms = {t["symbol"] for t in target}

        # stop
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
            thr = float(slot.thr)
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
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px) * (1.0 - SLIP)
                    proceeds = slot.shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    events.append(
                        {
                            "date": key,
                            "slot": si,
                            "side": "sell_stop",
                            "symbol": slot.symbol,
                            "thr": thr,
                            "px": sell_px,
                            "shares": slot.shares,
                        }
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
                for t in target:
                    sym = t["symbol"]
                    if sym in held or sym in pending or sym not in paths:
                        continue
                    if any(s.symbol == sym for s in slots if s is not slot):
                        continue
                    assign = t
                    break
                if assign is None:
                    continue
                slot.symbol = assign["symbol"]
                slot.thr = float(assign["thr"])
                pending.add(slot.symbol)
                events.append(
                    {
                        "date": key,
                        "slot": si,
                        "side": "assign",
                        "symbol": slot.symbol,
                        "thr": slot.thr,
                        "px": np.nan,
                        "shares": 0.0,
                    }
                )

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
            thr = float(slot.thr)
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
                                "thr": thr,
                                "px": px,
                                "shares": slot.shares,
                            }
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
    if len(ev) and "thr" in ev.columns:
        buys = ev[ev["side"] == "buy"]
        st["thr_share"] = buys["thr"].value_counts(normalize=True).to_dict() if len(buys) else {}
    return eq, ev, st


def fixed_ew_year(targets: pd.DataFrame, thr_mode: str) -> list[dict]:
    """分年：目标池各票独立 simulate 后等权（研究口径）。"""
    rows = []
    for tf, g in targets.groupby("trade_from"):
        y = int(str(tf)[:4])
        if y < 2023:
            continue
        start, end = f"{y}0101", (BT_END if y >= 2026 else f"{y}1231")
        navs = {}
        thr_used = []
        for _, r in g.sort_values("rank").iterrows():
            sym = str(r["symbol"])
            thr = float(r["thr"]) if thr_mode == "adapt" else float(thr_mode)
            thr_used.append(thr)
            daily = load_daily(sym)
            if daily is None:
                continue
            dates = pd.DatetimeIndex(pd.to_datetime(daily["date"]))
            if getattr(dates, "tz", None) is not None:
                dates = dates.tz_localize(None)
            eq, _ = simulate_open_break(
                daily["open"].to_numpy(float),
                daily["high"].to_numpy(float),
                daily["low"].to_numpy(float),
                daily["close"].to_numpy(float),
                thr=thr,
            )
            s = pd.Series(eq, index=dates.normalize())
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
        rows.append(
            {
                "year": y,
                "thr_mode": thr_mode,
                "ret": st["ret"],
                "mdd": st["mdd"],
                "sharpe": st["sharpe"],
                "thrs": ",".join(f"{t*100:.1f}%" for t in thr_used),
                "names": "、".join(g.sort_values("rank")["name"].tolist()),
            }
        )
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    name_map = _name_map()
    year_panel = pd.read_parquet(YEAR_PANEL)
    q_panel = pd.read_parquet(Q_PANEL)
    wf = pd.read_parquet(WF_PANEL)

    print("=== 年频目标 + 个股 thr_best(T-1) ===")
    targets = build_annual_targets(year_panel, q_panel, wf)
    targets.to_csv(OUT / "targets_annual_adapt_thr.csv", index=False, float_format="%.4f")
    for tf, g in targets.groupby("trade_from"):
        print(
            f"  {tf}: "
            + "、".join(f"{r.name}(±{r.thr*100:.1f}%)" for r in g.sort_values("rank").itertuples())
        )

    syms = sorted(targets["symbol"].unique())
    print(f"加载路径 {len(syms)}")
    paths = load_paths_serial(syms)
    print(f"  ok={len(paths)}")

    modes = ["adapt", "0.02", "0.025", "0.03"]
    summary = []
    print("\n=== 槽位（等止损再换）===")
    for mode in modes:
        eq, ev, st = run_slots(targets, paths, name_map, thr_mode=mode)
        tag = mode if mode != "adapt" else "adapt"
        eq.to_csv(OUT / f"nav_slot_{tag}.csv")
        ev.to_csv(OUT / f"events_slot_{tag}.csv", index=False)
        ydf = yearly_slice(eq["equity"])
        ydf.to_csv(OUT / f"yearly_slot_{tag}.csv", index=False)
        eq26 = eq.loc[eq.index >= "2026-01-01", "equity"]
        st26 = (
            _nav_stats(eq26 / float(eq26.iloc[0]))
            if len(eq26) > 5
            else {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
        )
        thr_share = st.get("thr_share", {})
        rec = {
            "mode": tag,
            "ret": st["ret"],
            "mdd": st["mdd"],
            "sharpe": st["sharpe"],
            "ret_2026": st26["ret"],
            "mdd_2026": st26["mdd"],
            "n_buys": st["n_buys"],
            "n_stops": st["n_stops"],
            "avg_held": st["avg_held"],
            "buy_share_2.0": float(thr_share.get(0.02, 0)),
            "buy_share_2.5": float(thr_share.get(0.025, 0)),
            "buy_share_3.0": float(thr_share.get(0.03, 0)),
        }
        summary.append(rec)
        print(
            f"  {tag:8s} 全段={st['ret']:+6.1f}% mdd={st['mdd']:5.1f}% sh={st['sharpe']:.2f}  "
            f"2026={st26['ret']:+6.1f}%  buys={st['n_buys']}  "
            f"thr占比 2/2.5/3={rec['buy_share_2.0']:.0%}/{rec['buy_share_2.5']:.0%}/{rec['buy_share_3.0']:.0%}"
        )
        if len(ydf):
            print("         ", ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ydf.itertuples()))

    sdf = pd.DataFrame(summary).sort_values("sharpe", ascending=False)
    sdf.to_csv(OUT / "summary_slot.csv", index=False, float_format="%.4f")

    print("\n=== 研究等权（票内独立）===")
    ew_rows = []
    for mode in modes:
        ew_rows.extend(fixed_ew_year(targets, mode))
    ewf = pd.DataFrame(ew_rows)
    ewf.to_csv(OUT / "summary_ew_yearly.csv", index=False, float_format="%.4f")
    for mode in modes:
        sub = ewf[ewf.thr_mode == mode]
        print(f"  {mode:8s} " + ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in sub.itertuples()))

    best = sdf.iloc[0]
    best_mode = str(best["mode"])
    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>个股阈值择优</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border:1px solid #ddd;padding:6px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}} .kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
</style></head><body>
<h1>个股阈值 ±2% / ±2.5% / ±3%</h1>
<p>买入与止损用同一阈值；adapt = 用上一年三档夏普择优。选股：年频 qy_blend Top5；执行：槽位等止损再换。</p>
<div class=kpi>
<div><b>槽位最优</b><br>{best_mode}</div>
<div><b>全段</b><br>{best['ret']:+.1f}%</div>
<div><b>2026</b><br>{best['ret_2026']:+.1f}%</div>
<div><b>回撤</b><br>{best['mdd']:.1f}%</div>
</div>
<h2>目标池（含阈值）</h2>
{targets.round(3).to_html(index=False)}
<h2>槽位对比</h2>
{sdf.round(3).to_html(index=False)}
<h2>研究等权分年</h2>
{ewf.round(2).to_html(index=False)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "meta.json").write_text(
        json.dumps(
            {
                "thresholds": list(THRESHOLDS),
                "adapt_rule": "thr_best from fit year T-1 by sharpe among 2/2.5/3%",
                "best_slot": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in best.items()},
            },
            ensure_ascii=False,
            indent=2,
            default=float,
        ),
        encoding="utf-8",
    )
    print(f"\nBEST slot={best_mode} {best['ret']:+.1f}% → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
