"""因子改：夏普选股（无前瞻半年）· Top3 · 各30%。

两套评分（分开回测对比）：
  A) cum_sharpe：2019-01-01 → 信号日，策略开盘突破净值日收益年化夏普
  B) half_sharpe：信号日前一完整半年，同上夏普

选 Top3 → 下一半年 OOS；三槽各 30% 仓；±2.5%。

  python strategy/run_factor13_sharpe_semi.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
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

OUT = _MYQUAN / "backtest" / "factor13_sharpe_semi"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
PATH_CACHE = OUT / "eq_paths_thr025.parquet"  # long format optional; we use dict pickle-ish csv per? keep in mem

THR = 0.025
TOP_K = 3
N_SLOTS = 3
W_EACH = 0.30
INITIAL = 1_000_000.0
LOT = 100
BT_END = "20260825"
CUM_START = "20190101"
MIN_BARS_CUM = 120
MIN_BARS_HALF = 60


def _is_mb(sym: str) -> bool:
    s = str(sym).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def load_daily(sym: str, start: str = "20180101") -> pd.DataFrame | None:
    p = UNIV_CACHE / f"{sym}_daily_qfq.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p).copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(BT_END))]
    return d.reset_index(drop=True) if len(d) else None


def ann_sharpe(eq: pd.Series) -> float:
    if len(eq) < 20:
        return float("nan")
    r = eq.pct_change().dropna()
    if len(r) < 15 or float(r.std()) < 1e-12:
        return float("nan")
    return float(r.mean() / r.std() * np.sqrt(252))


def signals() -> list[pd.Timestamp]:
    out = []
    for y in range(2019, 2026):
        out += [pd.Timestamp(f"{y}-06-30"), pd.Timestamp(f"{y}-12-31")]
    return [d for d in out if d >= pd.Timestamp("2019-12-31")]


def oos_window(sig: pd.Timestamp) -> tuple[str, str, str]:
    if sig.month == 12:
        y = sig.year + 1
        return f"{y}-01-01", f"{y}-06-30", f"{y}H1"
    return f"{sig.year}-07-01", f"{sig.year}-12-31", f"{sig.year}H2"


def prior_half(sig: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """信号日前一完整半年（含信号日）。6/30→当年H1；12/31→当年H2。"""
    if sig.month == 12:
        return pd.Timestamp(f"{sig.year}-07-01"), sig
    return pd.Timestamp(f"{sig.year}-01-01"), sig


def build_eq_paths(symbols: list[str], name_map: dict[str, str]) -> dict[str, pd.Series]:
    """全样本一次模拟开盘突破净值（从本地最早有数据日起）。"""
    out: dict[str, pd.Series] = {}
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        d = load_daily(sym, "20180101")
        if d is None or len(d) < MIN_BARS_CUM:
            continue
        dates = pd.DatetimeIndex(d["date"]).normalize()
        eq, _ = simulate_open_break(
            d["open"].to_numpy(float),
            d["high"].to_numpy(float),
            d["low"].to_numpy(float),
            d["close"].to_numpy(float),
            thr=THR,
        )
        out[sym] = pd.Series(eq, index=dates, name=sym)
        if i % 200 == 0 or i == len(symbols):
            print(f"  eq paths {i}/{len(symbols)} ok={len(out)} ({time.time()-t0:.0f}s)")
    return out


def score_universe(
    eq_paths: dict[str, pd.Series],
    name_map: dict[str, str],
    sig: pd.Timestamp,
    mode: str,
) -> pd.DataFrame:
    """mode: cum | half"""
    rows = []
    cum0 = pd.Timestamp(CUM_START)
    h0, h1 = prior_half(sig)
    for sym, eq in eq_paths.items():
        if mode == "cum":
            w = eq[(eq.index >= cum0) & (eq.index <= sig)]
            if len(w) < MIN_BARS_CUM:
                continue
            # 窗口内重置净值再算夏普（避免跨窗尺度问题；收益序列等价于切段）
            sh = ann_sharpe(w)
            score = sh
        else:
            w = eq[(eq.index >= h0) & (eq.index <= h1)]
            if len(w) < MIN_BARS_HALF:
                continue
            sh = ann_sharpe(w)
            score = sh
        if not np.isfinite(score):
            continue
        rows.append(
            {
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "score": float(score),
                "sharpe": float(score),
                "n_bars": int(len(w)),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # 只要夏普为正的候选，再取 TopK；不够则放宽
    pos = df[df["sharpe"] > 0].sort_values("sharpe", ascending=False)
    if len(pos) >= TOP_K:
        return pos.head(TOP_K).reset_index(drop=True)
    return df.sort_values("sharpe", ascending=False).head(TOP_K).reset_index(drop=True)


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
        d = load_daily(sym, "20190101")
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


def run_slots(targets: pd.DataFrame, paths: dict[str, PathData]) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    by = {tf: g.sort_values("rank")["symbol"].tolist() for tf, g in targets.groupby("trade_from")}
    all_d: set = set()
    for p in paths.values():
        all_d.update(p.dates.tolist())
    cal = pd.DatetimeIndex(sorted(all_d)).normalize()
    cal = cal[(cal >= "2020-01-01") & (cal <= BT_END)]

    idle = INITIAL * (1.0 - N_SLOTS * W_EACH)
    slots = [Slot(cash=INITIAL * W_EACH) for _ in range(N_SLOTS)]
    target = by.get("2020-01-01") or by[min(by)]
    eq_rows: list[dict] = []

    def port_equity(dt: pd.Timestamp) -> float:
        tot = idle
        for slot in slots:
            if slot.symbol and slot.shares > 0:
                path = paths.get(slot.symbol)
                j = path.date_to_i.get(dt) if path else None
                tot += slot.cash + slot.shares * (
                    float(path.c[j]) if path is not None and j is not None else slot.entry_px
                )
            else:
                tot += slot.cash
        return tot

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        key = dt.strftime("%Y-%m-%d")
        md = cal[cal.to_period("M") == dt.to_period("M")]
        if len(md) and dt == md[0] and dt.month in (1, 7):
            cands = [tf for tf in by if tf[:7] == dt.strftime("%Y-%m")]
            if cands:
                target = by[min(cands)]
        tset = set(target)

        for slot in slots:
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
            stop = stop_trigger_price(oi, stop_pct=THR, tick=TICK_SIZE)
            if j > slot.buy_i and li <= stop + 1e-12:
                prev = float(path.c[j - 1]) if j > 0 else ci
                lim = limit_down_state(
                    prev_close=prev, open_px=oi, high_px=hi, low_px=li, close_px=ci,
                    limit_down_pct=0.10, tick=TICK_SIZE,
                )
                if not bool(lim["locked"]):
                    px = float(lim["limit_px"] if bool(lim["opened"]) else stop) * (1 - SLIP)
                    proceeds = slot.shares * px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    slot.shares = 0.0
                    slot.symbol = None
                    slot.buy_i = -1
                    slot.entry_px = 0.0

        held = {s.symbol for s in slots if s.symbol and s.shares > 0}
        for s in slots:
            if s.shares <= 0 and s.symbol and s.symbol not in tset:
                s.symbol = None
        pending = {s.symbol for s in slots if s.symbol and s.shares <= 0}
        total_eq = port_equity(dt)

        for slot in slots:
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
                want = total_eq * W_EACH
                delta = want - slot.cash
                if delta > 0:
                    take = min(delta, idle)
                    idle -= take
                    slot.cash += take
                elif delta < 0:
                    give = min(-delta, slot.cash)
                    slot.cash -= give
                    idle += give
                slot.symbol = assign
                pending.add(assign)
                total_eq = port_equity(dt)

            path = paths.get(slot.symbol)  # type: ignore[arg-type]
            if path is None:
                continue
            j = path.date_to_i.get(dt)
            if j is None or j < 1:
                continue
            oi, hi, li, ci = float(path.o[j]), float(path.h[j]), float(path.l[j]), float(path.c[j])
            po, pc = float(path.o[j - 1]), float(path.c[j - 1])
            if oi <= 0:
                continue
            buy = entry_trigger_price(oi, entry_pct=THR, tick=TICK_SIZE)
            allows = prev_day_allows_entry(po, pc, prev_small_yang_pct=THR, prev_entry_mode="yin_or_small_yang")
            blocked = False
            if j >= 2:
                blocked = should_block_entry_by_yang(
                    float(path.o[j - 2]), float(path.c[j - 2]), po, pc, tick=TICK_SIZE,
                    ban_double_yang=DEFAULT_BAN_DOUBLE_YANG, ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                    double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                    double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                )
            if allows and (not blocked) and (hi + 1e-12 >= buy) and slot.cash > 0:
                px = buy * (1 + SLIP)
                raw = math.floor(slot.cash * 0.99 / (px * LOT)) * LOT
                if raw >= LOT:
                    cost = raw * px
                    fee = cost * COMMISSION
                    if cost + fee <= slot.cash:
                        slot.cash -= cost + fee
                        slot.shares = float(raw)
                        slot.entry_px = px
                        slot.buy_i = j
                        held.add(slot.symbol)

        eq_rows.append({"date": dt, "equity": port_equity(dt)})

    eq = pd.DataFrame(eq_rows).set_index("date").sort_index()
    st = _nav_stats(eq["equity"] / float(eq["equity"].iloc[0]))
    ydf = pd.DataFrame(
        [{"year": int(y), **_nav_stats(g / float(g.iloc[0]))} for y, g in eq["equity"].groupby(eq.index.year)]
    )
    return eq, st, ydf


def period_ew(picks: pd.DataFrame, start: str, end: str) -> tuple[pd.Series, dict]:
    navs = {}
    for _, r in picks.iterrows():
        sym = str(r["symbol"])
        d = load_daily(sym, "20190101")
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
        s = s[(s.index >= start) & (s.index <= end)]
        if len(s) < 5:
            continue
        navs[sym] = s / float(s.iloc[0])
    if not navs:
        return pd.Series(dtype=float), {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    df = pd.concat(navs, axis=1).sort_index().ffill()
    port = (1 + df.pct_change().mean(axis=1).fillna(0)).cumprod()
    port.iloc[0] = 1.0
    return port, _nav_stats(port)


def run_mode(mode: str, eq_paths: dict[str, pd.Series], name_map: dict[str, str]) -> dict:
    print(f"\n======== mode={mode} ========")
    tg_rows, oos_rows, ew_pieces = [], [], []
    for sig in signals():
        start, end, tag = oos_window(sig)
        if pd.Timestamp(start) > pd.Timestamp(BT_END):
            continue
        end_eff = min(pd.Timestamp(end), pd.Timestamp(BT_END)).strftime("%Y-%m-%d")
        picks = score_universe(eq_paths, name_map, sig, mode)
        if picks.empty:
            print(f"  {sig.date()} → {tag}: 空")
            continue
        names = "、".join(picks["name"].tolist())
        print(f"  信号{sig.date()} → OOS {tag}: {names}  sh={picks['sharpe'].round(2).tolist()}")
        for i, r in picks.iterrows():
            tg_rows.append(
                {
                    "mode": mode,
                    "signal_date": str(sig.date()),
                    "trade_from": start,
                    "trade_to": end_eff,
                    "oos_tag": tag,
                    "rank": int(i) + 1,
                    "symbol": str(r["symbol"]),
                    "name": str(r["name"]),
                    "score": float(r["score"]),
                }
            )
        port, st = period_ew(picks, start, end_eff)
        oos_rows.append(
            {
                "mode": mode,
                "signal_date": str(sig.date()),
                "oos_tag": tag,
                "ret": st["ret"],
                "mdd": st["mdd"],
                "sharpe": st["sharpe"],
                "names": names,
            }
        )
        print(f"    OOS等权: {st['ret']:+.1f}%")
        if len(port):
            ew_pieces.append(port if not ew_pieces else port * float(ew_pieces[-1].iloc[-1]))

    targets = pd.DataFrame(tg_rows)
    oos = pd.DataFrame(oos_rows)
    targets.to_csv(OUT / f"targets_{mode}.csv", index=False, float_format="%.4f")
    oos.to_csv(OUT / f"oos_{mode}.csv", index=False, float_format="%.4f")

    ew = pd.concat(ew_pieces).sort_index()
    ew = ew[~ew.index.duplicated(keep="last")]
    ste = _nav_stats(ew / float(ew.iloc[0]))
    ew.to_csv(OUT / f"nav_ew_{mode}.csv")

    paths = load_paths(sorted(targets["symbol"].unique()))
    eq, st, ydf = run_slots(targets, paths)
    eq.to_csv(OUT / f"nav_slot_{mode}.csv")
    ydf.to_csv(OUT / f"yearly_slot_{mode}.csv", index=False, float_format="%.4f")
    eq26 = eq.loc[eq.index >= "2026-01-01", "equity"]
    st26 = _nav_stats(eq26 / float(eq26.iloc[0])) if len(eq26) > 5 else {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}

    print(f"  三槽全段={st['ret']:+.1f}% mdd={st['mdd']:.1f}%  2026={st26['ret']:+.1f}%")
    print("  分年:", ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ydf.itertuples()))
    print(f"  等权拼接={ste['ret']:+.1f}%")

    return {
        "mode": mode,
        "slot": st,
        "slot_2026": st26,
        "ew": ste,
        "targets": targets,
        "oos": oos,
        "yearly": ydf,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    name_map = _name_map()
    symbols = [
        fp.name.replace("_daily_qfq.parquet", "")
        for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet"))
        if _is_mb(fp.name.replace("_daily_qfq.parquet", ""))
    ]
    print(f"主板 {len(symbols)}，预计算策略净值…")
    eq_paths = build_eq_paths(symbols, name_map)
    print(f"有效路径 {len(eq_paths)}")

    results = []
    for mode in ("cum", "half"):
        results.append(run_mode(mode, eq_paths, name_map))

    # 汇总报告
    rows = []
    for r in results:
        rows.append(
            {
                "mode": r["mode"],
                "label": "2019→信号累计夏普" if r["mode"] == "cum" else "前一半年夏普",
                "ret": r["slot"]["ret"],
                "mdd": r["slot"]["mdd"],
                "sharpe": r["slot"]["sharpe"],
                "ret_2026": r["slot_2026"]["ret"],
                "ew_ret": r["ew"]["ret"],
            }
        )
    summary = pd.DataFrame(rows).sort_values("ret", ascending=False)
    summary.to_csv(OUT / "summary.csv", index=False, float_format="%.4f")

    best = summary.iloc[0]
    blocks = []
    for r in results:
        blocks.append(f"<h2>{'累计夏普' if r['mode']=='cum' else '半年夏普'}</h2>")
        blocks.append(r["oos"].round(2).to_html(index=False))
        blocks.append(r["yearly"].round(2).to_html(index=False))
        blocks.append(r["targets"].round(3).to_html(index=False))

    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>夏普因子半年选股</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:16px}}
th,td{{border:1px solid #ddd;padding:5px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}} .kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
</style></head><body>
<h1>因子改：夏普选股 · Top3 · 各30%</h1>
<p>无前瞻半年；A=2019→信号累计夏普；B=前一半年夏普。开盘突破 ±2.5%。</p>
<div class=kpi>
<div><b>较优</b><br>{best['label']}</div>
<div><b>全段</b><br>{best['ret']:+.1f}%</div>
<div><b>2026</b><br>{best['ret_2026']:+.1f}%</div>
</div>
<h2>对比</h2>
{summary.round(2).to_html(index=False)}
{''.join(blocks)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "meta.json").write_text(
        json.dumps({"summary": rows, "best": best.to_dict()}, ensure_ascii=False, indent=2, default=float),
        encoding="utf-8",
    )
    print("\n=== 对比 ===")
    print(summary.to_string(index=False))
    print(f"→ {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
