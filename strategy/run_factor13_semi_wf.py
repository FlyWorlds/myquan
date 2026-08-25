"""半年选股 · 严格无前瞻 walkforward。

规则：
  · 信号日：每年 6/30、12/31（已结束半年）
  · 选股只用信号日及之前可见特征：完整日历年 ≤ fit_end；季度 ≤ 信号季
  · 选出 Top5 后，只回测「下一半年」样本外（后面未知）
  · 组合：五槽等权，持仓等止损再换；另报研究等权（票内独立）
  · 不用未来年份去回看过去选股

  python strategy/run_factor13_semi_wf.py
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

from backtest.factor1_monthly_top3 import simulate_open_break  # noqa: E402
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402
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

OUT = _MYQUAN / "backtest" / "factor13_semi_wf"
YEAR_PANEL = _MYQUAN / "backtest" / "factor13_from2020" / "year_panel_ext.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_from2020" / "quarter_panel_ext.parquet"
# 回退
YEAR_FALLBACK = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_FALLBACK = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"

THR = 0.025
TOP_K = 5
N_SLOTS = 5
INITIAL_CASH = 500_000.0
TARGET_PCT = 0.95
LOT = 100
BT_END = "20260825"
FIT_START = 2018  # 本地日线最早约此；选股仍严格截断到信号日
PARAMS = {"rule": "qy_blend", "top_k": TOP_K, "fit_start_year": FIT_START, "thr": THR}


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def _load_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    yp = YEAR_PANEL if YEAR_PANEL.exists() else YEAR_FALLBACK
    qp = Q_PANEL if Q_PANEL.exists() else Q_FALLBACK
    y = pd.read_parquet(yp)
    q = pd.read_parquet(qp)
    if "thr" in y.columns:
        y = y[np.isclose(y["thr"].astype(float), THR)].copy()
    if "kind" in q.columns:
        q = q[q["kind"] == "quarter"].copy()
    # 统一 year
    if "year" not in q.columns or q["year"].isna().all():
        q["year"] = q["period"].astype(str).str.slice(0, 4).astype(int)
    else:
        q["year"] = pd.to_numeric(q["year"], errors="coerce").astype("Int64")
        q = q.dropna(subset=["year"]).copy()
        q["year"] = q["year"].astype(int)
    q["pq"] = pd.PeriodIndex(q["period"].astype(str), freq="Q")
    return y, q


def signal_dates() -> list[pd.Timestamp]:
    """2019H2 末起 → 覆盖 2020H1 起的 OOS；含 2025H2 末 → 2026H1。"""
    out = []
    for y in range(2019, 2026):
        out.append(pd.Timestamp(f"{y}-06-30"))
        out.append(pd.Timestamp(f"{y}-12-31"))
    # 2019 只要 12-31 起步（2019-06 特征太薄可跳过）
    out = [d for d in out if d >= pd.Timestamp("2019-12-31")]
    return out


def oos_window(signal: pd.Timestamp) -> tuple[str, str, str]:
    """下一半年 [trade_from, trade_to]。"""
    if signal.month == 12:
        y = signal.year + 1
        return f"{y}-01-01", f"{y}-06-30", f"{y}H1"
    y = signal.year
    return f"{y}-07-01", f"{y}-12-31", f"{y}H2"


def fit_end_year(signal: pd.Timestamp) -> int:
    """只用已完整结束的日历年（6/30 不用当年年面板）。"""
    return int(signal.year) if signal.month == 12 else int(signal.year) - 1


def truncate_quarters(q: pd.DataFrame, signal: pd.Timestamp) -> pd.DataFrame:
    asof = pd.Period(signal, freq="Q")
    return q[q["pq"] <= asof].copy()


def pick_at(signal: pd.Timestamp, year_panel: pd.DataFrame, q_panel: pd.DataFrame) -> pd.DataFrame:
    fit_y = fit_end_year(signal)
    q = truncate_quarters(q_panel, signal)
    # 年面板：禁止任何 > fit_y 的行（防 2025/2026 泄漏）
    y = year_panel[year_panel["year"] <= fit_y].copy()
    picks = select_top(y, fit_end_year=fit_y, params=PARAMS, quarter_panel=q)
    if picks.empty:
        picks = select_top(
            y,
            fit_end_year=fit_y,
            params={**PARAMS, "min_q_obear": 2, "min_q_ex": 0.0, "min_obear": 1},
            quarter_panel=q,
        )
    return picks


def load_daily(symbol: str, start: str = "20190101") -> pd.DataFrame | None:
    p = UNIV_CACHE / f"{symbol}_daily_qfq.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p).copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(BT_END))]
    return d.reset_index(drop=True) if len(d) else None


def _nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 2:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    ret = float(nav.iloc[-1] / nav.iloc[0] - 1) * 100
    mdd = abs(float((nav / nav.cummax() - 1).min() * 100))
    r = nav.pct_change().dropna()
    sh = float(r.mean() / r.std() * np.sqrt(252)) if float(r.std()) > 1e-12 else np.nan
    return {"ret": ret, "mdd": mdd, "sharpe": sh}


@dataclass
class PathData:
    dates: pd.DatetimeIndex
    date_to_i: dict
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray


@dataclass
class Slot:
    cash: float
    symbol: str | None = None
    shares: float = 0.0
    buy_i: int = -1
    entry_px: float = 0.0


def load_paths(symbols: list[str]) -> dict[str, PathData]:
    out: dict[str, PathData] = {}
    for sym in symbols:
        d = load_daily(sym)
        if d is None or len(d) < 60:
            continue
        dates = pd.DatetimeIndex(d["date"]).normalize()
        out[sym] = PathData(
            dates=dates,
            date_to_i={pd.Timestamp(x).normalize(): i for i, x in enumerate(dates)},
            o=d["open"].to_numpy(float),
            h=d["high"].to_numpy(float),
            l=d["low"].to_numpy(float),
            c=d["close"].to_numpy(float),
        )
    return out


def period_ew(picks: pd.DataFrame, start: str, end: str) -> tuple[pd.Series, dict]:
    """当期五票：各自只在 [start,end] 内独立模拟，再等权。"""
    navs = {}
    for _, r in picks.iterrows():
        sym = str(r["symbol"]).lower()
        d = load_daily(sym)
        if d is None:
            continue
        dates = pd.DatetimeIndex(d["date"]).normalize()
        eq, _ = simulate_open_break(
            d["open"].to_numpy(float),
            d["high"].to_numpy(float),
            d["low"].to_numpy(float),
            d["close"].to_numpy(float),
            thr=THR,
        )
        s = pd.Series(eq, index=dates)
        s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
        if len(s) < 5:
            continue
        navs[sym] = s / float(s.iloc[0])
    if not navs:
        return pd.Series(dtype=float), {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan, "n": 0}
    df = pd.concat(navs, axis=1).sort_index().ffill()
    port = (1 + df.pct_change().mean(axis=1).fillna(0)).cumprod()
    port.iloc[0] = 1.0
    st = _nav_stats(port)
    st["n"] = len(navs)
    return port, st


def run_slots(targets: pd.DataFrame, paths: dict[str, PathData]) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    by_from: dict[str, list[str]] = {}
    for tf, g in targets.groupby("trade_from"):
        by_from[str(tf)] = g.sort_values("rank")["symbol"].tolist()

    all_dates: set = set()
    for p in paths.values():
        all_dates.update(p.dates.tolist())
    cal = pd.DatetimeIndex(sorted(all_dates)).normalize()
    cal = cal[(cal >= pd.Timestamp("2020-01-01")) & (cal <= pd.Timestamp(BT_END))]

    slots = [Slot(cash=INITIAL_CASH / N_SLOTS) for _ in range(N_SLOTS)]
    target: list[str] = []
    prior = [tf for tf in by_from if tf <= "2020-01-01"]
    if prior:
        target = by_from[max(prior)]
    elif by_from:
        target = by_from[min(by_from)]

    equity_rows, events = [], []
    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        key = dt.strftime("%Y-%m-%d")
        # 半年切换：1月/7月首个交易日换目标池
        md = cal[cal.to_period("M") == dt.to_period("M")]
        if len(md) and dt == md[0] and dt.month in (1, 7):
            cands = [tf for tf in by_from if tf[:7] == dt.strftime("%Y-%m")]
            if cands:
                target = by_from[min(cands)]

        tset = set(target)
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
            stop_px = stop_trigger_price(oi, stop_pct=THR, tick=TICK_SIZE)
            if j > slot.buy_i and li <= stop_px + 1e-12:
                prev_c = float(path.c[j - 1]) if j > 0 else ci
                lim = limit_down_state(
                    prev_close=prev_c, open_px=oi, high_px=hi, low_px=li, close_px=ci,
                    limit_down_pct=0.10, tick=TICK_SIZE,
                )
                if not bool(lim["locked"]):
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px) * (1.0 - SLIP)
                    proceeds = slot.shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    events.append({"date": key, "slot": si, "side": "sell_stop", "symbol": slot.symbol})
                    slot.shares = 0.0
                    slot.symbol = None
                    slot.buy_i = -1
                    slot.entry_px = 0.0

        held = {s.symbol for s in slots if s.symbol and s.shares > 0}
        for slot in slots:
            if slot.shares <= 0 and slot.symbol and slot.symbol not in tset:
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
                events.append({"date": key, "slot": si, "side": "assign", "symbol": assign})

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
                    float(path.o[j - 2]), float(path.c[j - 2]), po, pc, tick=TICK_SIZE,
                    ban_double_yang=DEFAULT_BAN_DOUBLE_YANG, ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                    double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                    double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                )
            if allows and (not blocked) and (hi + 1e-12 >= buy_px) and slot.cash > 0:
                px = buy_px * (1.0 + SLIP)
                raw = math.floor(slot.cash * TARGET_PCT / (px * LOT)) * LOT
                if raw >= LOT:
                    cost = raw * px
                    fee = cost * COMMISSION
                    if cost + fee <= slot.cash:
                        slot.cash -= cost + fee
                        slot.shares = float(raw)
                        slot.entry_px = px
                        slot.buy_i = j
                        held.add(slot.symbol)
                        events.append({"date": key, "slot": si, "side": "buy", "symbol": slot.symbol})

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
    st = _nav_stats(eq["equity"] / float(eq["equity"].iloc[0]))
    st["avg_held"] = float(eq["n_held"].mean())
    # 按自然年切片（仍是真实串联净值，非偷看选股）
    yrows = []
    for y, g in eq["equity"].groupby(eq.index.year):
        yrows.append({"year": int(y), **_nav_stats(g / float(g.iloc[0]))})
    return eq, st, pd.DataFrame(yrows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    name_map = _name_map()
    year_panel, q_panel = _load_panels()
    # 硬性：选股阶段永远丢掉「未来年」行由 truncate 保证；这里再删 2026 年特征防误用
    assert year_panel["year"].max() >= 2025

    print("=== 半年 walkforward（选股只用当时可见数据 → 回测下一半年）===")
    tg_rows = []
    oos_rows = []
    ew_pieces: list[pd.Series] = []

    for sig in signal_dates():
        fit_y = fit_end_year(sig)
        start, end, tag = oos_window(sig)
        if pd.Timestamp(start) > pd.Timestamp(BT_END):
            continue
        end_eff = min(pd.Timestamp(end), pd.Timestamp(BT_END)).strftime("%Y-%m-%d")
        picks = pick_at(sig, year_panel, q_panel)
        if picks.empty:
            print(f"  {sig.date()} fit≤{fit_y} → {tag}: 空名单")
            continue
        names = "、".join(picks["name"].astype(str).tolist())
        print(f"  信号{sig.date()} | 特征年≤{fit_y} 季≤{pd.Period(sig, freq='Q')} | OOS {tag} {start}~{end_eff}")
        print(f"    选: {names}")

        for i, r in picks.iterrows():
            tg_rows.append(
                {
                    "signal_date": str(sig.date()),
                    "fit_end_year": fit_y,
                    "trade_from": start,
                    "trade_to": end_eff,
                    "oos_tag": tag,
                    "rank": int(i) + 1,
                    "symbol": str(r["symbol"]).lower(),
                    "name": str(r.get("name") or name_map.get(str(r["symbol"]).lower(), "")),
                    "score": float(r.get("score", np.nan)),
                }
            )

        port, st = period_ew(picks, start, end_eff)
        oos_rows.append(
            {
                "signal_date": str(sig.date()),
                "fit_end_year": fit_y,
                "oos_tag": tag,
                "trade_from": start,
                "trade_to": end_eff,
                "ret": st["ret"],
                "mdd": st["mdd"],
                "sharpe": st["sharpe"],
                "n": st.get("n", 0),
                "names": names,
            }
        )
        print(f"    OOS等权: {st['ret']:+.1f}% mdd={st['mdd']:.1f}%")
        if len(port):
            if not ew_pieces:
                ew_pieces.append(port)
            else:
                ew_pieces.append(port * float(ew_pieces[-1].iloc[-1]))

    targets = pd.DataFrame(tg_rows)
    oos = pd.DataFrame(oos_rows)
    targets.to_csv(OUT / "targets_semi.csv", index=False, float_format="%.4f")
    oos.to_csv(OUT / "oos_by_half.csv", index=False, float_format="%.4f")

    # 拼接研究等权
    if ew_pieces:
        ew = pd.concat(ew_pieces).sort_index()
        ew = ew[~ew.index.duplicated(keep="last")]
        ste = _nav_stats(ew / float(ew.iloc[0]))
        ew.to_csv(OUT / "nav_ew_stitch.csv")
    else:
        ste = {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}

    print(f"\n研究等权拼接全段: {ste['ret']:+.1f}% mdd={ste['mdd']:.1f}% sh={ste['sharpe']:.2f}")

    # 五槽连续
    syms = sorted(targets["symbol"].unique())
    paths = load_paths(syms)
    print(f"槽位路径 {len(paths)}/{len(syms)}")
    eq, st_slot, ydf = run_slots(targets, paths)
    eq.to_csv(OUT / "nav_slot.csv")
    ydf.to_csv(OUT / "yearly_slot.csv", index=False, float_format="%.4f")
    print(f"五槽全段: {st_slot['ret']:+.1f}% mdd={st_slot['mdd']:.1f}% sh={st_slot['sharpe']:.2f}")
    print("分年:", ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ydf.itertuples()))
    # 2026
    eq26 = eq.loc[eq.index >= "2026-01-01", "equity"]
    st26 = _nav_stats(eq26 / float(eq26.iloc[0])) if len(eq26) > 5 else {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    print(f"五槽2026: {st26['ret']:+.1f}%")

    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>半年WF无前瞻</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{border:1px solid #ddd;padding:5px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}} .kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
</style></head><body>
<h1>半年选股 · 严格 walkforward</h1>
<p>信号日只用当时可见年/季特征；选出后只回测下一半年。阈值 ±2.5%，Top5。</p>
<div class=kpi>
<div><b>五槽全段</b><br>{st_slot['ret']:+.1f}%</div>
<div><b>五槽2026</b><br>{st26['ret']:+.1f}%</div>
<div><b>等权拼接</b><br>{ste['ret']:+.1f}%</div>
<div><b>回撤(槽)</b><br>{st_slot['mdd']:.1f}%</div>
</div>
<h2>每期 OOS（选股→下一半年）</h2>
{oos.round(2).to_html(index=False)}
<h2>目标池</h2>
{targets.round(3).to_html(index=False)}
<h2>五槽分年</h2>
{ydf.round(2).to_html(index=False)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。无用未来年回看过去选股。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "meta.json").write_text(
        json.dumps(
            {
                "rule": "semi_annual_walkforward_no_peek",
                "fit_start": FIT_START,
                "slot": st_slot,
                "slot_2026": st26,
                "ew_stitch": ste,
                "n_periods": len(oos),
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
