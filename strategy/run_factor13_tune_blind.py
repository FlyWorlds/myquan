"""快速版：2020–2023 筛选 → 2023–2024 调参 → 盲测 2025/2026。

预计算每个信号日的特征截面，网格只做过滤/TopK/加权（快）。
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import sys
import warnings
from pathlib import Path
from typing import Any

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
from strategy.factor13_bear_shield import (  # noqa: E402
    build_features,
    build_quarter_features,
    _pct_rank,
)
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

OUT = _MYQUAN / "backtest" / "factor13_tune_blind"
YEAR_PANEL = _MYQUAN / "backtest" / "factor13_from2020" / "year_panel_ext.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_from2020" / "quarter_panel_ext.parquet"

THR = 0.025
BT_END = "20260825"
INVEST = 0.90
INITIAL = 1_000_000.0
LOT = 100
TRAIN_YEARS = {2020, 2021, 2022, 2023}
VALID_YEARS = {2023, 2024}
BLIND_YEARS = {2025, 2026}

_EQ: dict[str, pd.Series] = {}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    y = pd.read_parquet(YEAR_PANEL)
    y = y[np.isclose(y["thr"].astype(float), THR)].copy()
    q = pd.read_parquet(Q_PANEL)
    q = q[q["kind"] == "quarter"].copy()
    q["year"] = q["period"].astype(str).str.slice(0, 4).astype(int)
    q["pq"] = pd.PeriodIndex(q["period"].astype(str), freq="Q")
    return y, q


def signals(freq: str) -> list[pd.Timestamp]:
    if freq == "annual":
        return [pd.Timestamp(f"{y}-12-31") for y in range(2019, 2026)]
    out = []
    for y in range(2019, 2026):
        out += [pd.Timestamp(f"{y}-06-30"), pd.Timestamp(f"{y}-12-31")]
    return [d for d in out if d >= pd.Timestamp("2019-12-31")]


def oos_of(sig: pd.Timestamp, freq: str) -> tuple[str, str, str, int]:
    if freq == "annual":
        y = sig.year + 1
        end = BT_END if y >= 2026 else f"{y}-12-31"
        return f"{y}-01-01", end, f"{y}Y", y
    if sig.month == 12:
        y = sig.year + 1
        return f"{y}-01-01", f"{y}-06-30", f"{y}H1", y
    return f"{sig.year}-07-01", f"{sig.year}-12-31", f"{sig.year}H2", sig.year


def fit_end(sig: pd.Timestamp) -> int:
    return int(sig.year) if sig.month == 12 else int(sig.year) - 1


def nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 2:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    ret = float(nav.iloc[-1] / nav.iloc[0] - 1) * 100
    mdd = abs(float((nav / nav.cummax() - 1).min() * 100))
    r = nav.pct_change().dropna()
    sh = float(r.mean() / r.std() * np.sqrt(252)) if float(r.std()) > 1e-12 else np.nan
    return {"ret": ret, "mdd": mdd, "sharpe": sh}


def load_daily(sym: str) -> pd.DataFrame | None:
    p = UNIV_CACHE / f"{sym}_daily_qfq.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p).copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    d = d[(d["date"] >= "20190101") & (d["date"] <= BT_END)].reset_index(drop=True)
    return d if len(d) else None


def strategy_nav(sym: str) -> pd.Series | None:
    if sym in _EQ:
        return _EQ[sym]
    d = load_daily(sym)
    if d is None or len(d) < 60:
        return None
    dates = pd.DatetimeIndex(d["date"]).normalize()
    eq, _ = simulate_open_break(
        d["open"].to_numpy(float),
        d["high"].to_numpy(float),
        d["low"].to_numpy(float),
        d["close"].to_numpy(float),
        thr=THR,
    )
    _EQ[sym] = pd.Series(eq, index=dates)
    return _EQ[sym]


def period_ret(picks: pd.DataFrame, start: str, end: str) -> float:
    end_ts = min(pd.Timestamp(end), pd.Timestamp(BT_END))
    cols, ws = {}, {}
    for _, r in picks.iterrows():
        sym = str(r["symbol"]).lower()
        s = strategy_nav(sym)
        if s is None:
            continue
        w = s[(s.index >= start) & (s.index <= end_ts)]
        if len(w) < 5:
            continue
        cols[sym] = w / float(w.iloc[0])
        ws[sym] = float(r["weight"])
    if not cols:
        return float("nan")
    df = pd.concat(cols, axis=1).sort_index().ffill()
    w = pd.Series(ws)
    w = w / w.sum()
    port = (1 + (df.pct_change().fillna(0) * w).sum(axis=1)).cumprod()
    return float(port.iloc[-1] / port.iloc[0] - 1) * 100


def cross_section(year_panel: pd.DataFrame, q_panel: pd.DataFrame, sig: pd.Timestamp, fit_start: int) -> pd.DataFrame:
    fy = fit_end(sig)
    y = year_panel[year_panel["year"] <= fy]
    q = q_panel[q_panel["pq"] <= pd.Period(sig, freq="Q")]
    feat = build_features(y, fit_end_year=fy, params={"fit_start_year": fit_start, "thr": THR})
    if feat.empty:
        return feat
    qf = build_quarter_features(q, fit_end_year=fy, params={"fit_start_year": fit_start})
    r = feat.merge(qf, on="symbol", how="left", suffixes=("", "_q"))
    return r


def apply_pick(cs: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    if cs is None or cs.empty:
        return pd.DataFrame()
    rule = cfg["rule"]
    k = int(cfg["top_k"])
    if rule == "qy_blend":
        r = cs[
            (cs["n_obear"] >= int(cfg["min_obear"]))
            & (cs["obear_ret"].fillna(-999) >= 0)
            & (cs["obear_ex"].fillna(-999) >= float(cfg["min_obear_ex"]))
            & (cs["obear_ex_min"].fillna(-999) >= 0)
            & (cs["q_n_obear"].fillna(0) >= int(cfg["min_q_obear"]))
            & (cs["q_obear_ex"].fillna(-999) >= float(cfg["min_q_ex"]))
        ].copy()
        if r.empty:
            return r
        r["score"] = (
            3 * _pct_rank(r["obear_ex"])
            + 2 * _pct_rank(r["obear_ret"])
            + 2 * _pct_rank(r["q_obear_ex"].fillna(r["q_obear_ex"].min()))
            + 2 * _pct_rank(r["q_obear_hit"].fillna(0))
            + 2 * _pct_rank(r["obear_ex_min"])
        )
    else:
        r = cs[
            (cs["n_obear"] >= int(cfg["min_obear"]))
            & (cs["obear_ret"].fillna(-999) >= 0)
            & (cs["obear_ex"].fillna(-999) >= float(cfg["min_obear_ex"]))
            & (cs["obear_ex_min"].fillna(-999) >= 0)
        ].copy()
        if r.empty:
            return r
        r["score"] = (
            3 * _pct_rank(r["obear_ret"])
            + 3 * _pct_rank(r["obear_ex"])
            + 2 * _pct_rank(r["obear_ex_min"])
            + 1 * _pct_rank(r["obear_dd_imp"].fillna(0))
        )
    r = r.sort_values("score", ascending=False).head(k).reset_index(drop=True)
    if cfg["weight_mode"] == "equal":
        r["weight"] = INVEST / len(r)
    else:
        s = r["score"].clip(lower=0)
        r["weight"] = (s / s.sum() * INVEST).to_numpy() if float(s.sum()) > 0 else INVEST / len(r)
    return r


def grid() -> list[dict[str, Any]]:
    out = []
    for rule, top_k, fit_start, freq, wmode in itertools.product(
        ["qy_blend", "bear_abs_pos_floor"],
        [3, 5],
        [2018, 2020],
        ["semi", "annual"],
        ["equal", "score"],
    ):
        if rule == "qy_blend":
            for mex, qn, qex in itertools.product([5.0, 8.0], [2, 3], [0.0, 2.0]):
                out.append(
                    dict(
                        rule=rule, top_k=top_k, fit_start=fit_start, freq=freq, weight_mode=wmode,
                        min_obear=2, min_obear_ex=mex, min_q_obear=qn, min_q_ex=qex,
                    )
                )
        else:
            for mex in (5.0, 8.0):
                out.append(
                    dict(
                        rule=rule, top_k=top_k, fit_start=fit_start, freq=freq, weight_mode=wmode,
                        min_obear=2, min_obear_ex=mex, min_q_obear=0, min_q_ex=0.0,
                    )
                )
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    yp, qp = load_panels()
    configs = grid()
    log(f"网格 {len(configs)} | train={sorted(TRAIN_YEARS)} valid={sorted(VALID_YEARS)} blind={sorted(BLIND_YEARS)}")

    # 预计算截面：每个 (freq, fit_start, signal)
    cs_cache: dict[tuple, pd.DataFrame] = {}
    for freq in ("semi", "annual"):
        for fs in (2018, 2020):
            for sig in signals(freq):
                key = (freq, fs, str(sig.date()))
                cs_cache[key] = cross_section(yp, qp, sig, fs)
            log(f"  截面就绪 freq={freq} fit_start={fs}")

    rows = []
    for i, cfg in enumerate(configs, 1):
        period_rets = []
        for sig in signals(cfg["freq"]):
            start, end, tag, oos_y = oos_of(sig, cfg["freq"])
            if pd.Timestamp(start) > pd.Timestamp(BT_END):
                continue
            end_eff = min(pd.Timestamp(end), pd.Timestamp(BT_END)).strftime("%Y-%m-%d")
            cs = cs_cache[(cfg["freq"], cfg["fit_start"], str(sig.date()))]
            picks = apply_pick(cs, cfg)
            if picks.empty:
                continue
            ret = period_ret(picks, start, end_eff)
            period_rets.append({"tag": tag, "oos_year": oos_y, "ret": ret, "names": "、".join(picks["name"].astype(str))})
        if not period_rets:
            continue
        df = pd.DataFrame(period_rets)
        tr = df[df.oos_year.isin(TRAIN_YEARS)]
        va = df[df.oos_year.isin(VALID_YEARS)]
        b25 = df[df.oos_year == 2025]
        b26 = df[df.oos_year == 2026]
        train_ret = float(tr.ret.mean()) if len(tr) else np.nan
        valid_ret = float(va.ret.mean()) if len(va) else np.nan
        rows.append({
            **cfg,
            "train_ret": train_ret,
            "valid_ret": valid_ret,
            "valid_score": valid_ret,  # 调参：验证集均收益
            "blind_2025": float(b25.ret.mean()) if len(b25) else np.nan,
            "blind_2026": float(b26.ret.mean()) if len(b26) else np.nan,
            "_detail": df,
        })
        if i % 30 == 0 or i == len(configs):
            log(f"  eval {i}/{len(configs)}")

    rdf = pd.DataFrame([{k: v for k, v in r.items() if k != "_detail"} for r in rows])
    details = {i: r["_detail"] for i, r in enumerate(rows)}
    cand = rdf[(rdf.train_ret > 0)].copy()
    if cand.empty:
        cand = rdf.copy()
        log("训练筛选放宽：无 train_ret>0")
    cand = cand.sort_values(["valid_score", "train_ret"], ascending=False)
    rdf.to_csv(OUT / "grid_all.csv", index=False, float_format="%.4f")
    cand.head(20).to_csv(OUT / "grid_top20_by_valid.csv", index=False, float_format="%.4f")

    best_i = int(cand.index[0])
    # map to rows index: cand.index are from rdf which aligns with rows enumeration... 
    # rdf was built without original index from rows - use position
    best_row = None
    best_cfg = cand.iloc[0].to_dict()
    for r in rows:
        ok = all(r.get(k) == best_cfg.get(k) for k in ["rule", "top_k", "fit_start", "freq", "weight_mode", "min_obear_ex", "min_q_obear", "min_q_ex"])
        if ok:
            best_row = r
            break
    assert best_row is not None
    det = best_row["_detail"]

    log("\n=== 调参最优（valid 2023-2024 均收益）===")
    for k in ["rule", "top_k", "fit_start", "freq", "weight_mode", "min_obear_ex", "min_q_obear", "min_q_ex",
              "train_ret", "valid_ret", "blind_2025", "blind_2026"]:
        log(f"  {k}: {best_cfg.get(k)}")
    log(f"\n*** 盲测（选参未用）2025={best_cfg['blind_2025']:+.1f}%  2026={best_cfg['blind_2026']:+.1f}% ***")

    det.to_csv(OUT / "oos_best_detail.csv", index=False, float_format="%.4f")
    cfg = {k: best_cfg[k] for k in ["rule", "top_k", "fit_start", "freq", "weight_mode", "min_obear", "min_obear_ex", "min_q_obear", "min_q_ex"]}
    cfg["top_k"] = int(cfg["top_k"]); cfg["fit_start"] = int(cfg["fit_start"])
    cfg["min_obear"] = int(cfg["min_obear"]); cfg["min_q_obear"] = int(cfg["min_q_obear"])
    cfg["min_obear_ex"] = float(cfg["min_obear_ex"]); cfg["min_q_ex"] = float(cfg["min_q_ex"])

    # 目标池
    tg = []
    for sig in signals(cfg["freq"]):
        start, end, tag, oos_y = oos_of(sig, cfg["freq"])
        if pd.Timestamp(start) > pd.Timestamp(BT_END):
            continue
        end_eff = min(pd.Timestamp(end), pd.Timestamp(BT_END)).strftime("%Y-%m-%d")
        cs = cs_cache[(cfg["freq"], cfg["fit_start"], str(sig.date()))]
        picks = apply_pick(cs, cfg)
        for i, r in picks.iterrows():
            tg.append(dict(signal_date=str(sig.date()), trade_from=start, trade_to=end_eff, oos_tag=tag, oos_year=oos_y,
                           rank=i+1, symbol=str(r.symbol).lower(), name=str(r['name']), score=float(r.score), weight=float(r.weight)))
    targets = pd.DataFrame(tg)
    targets.to_csv(OUT / "targets_best.csv", index=False, float_format="%.4f")

    # 简化槽位：研究加权已给盲测；再跑连续槽位净值
    from dataclasses import dataclass

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
        weight: float = 0.3

    paths = {}
    for sym in sorted(targets.symbol.unique()):
        d = load_daily(sym)
        if d is None or len(d) < 60:
            continue
        dates = pd.DatetimeIndex(d.date).normalize()
        paths[sym] = PathData(dates, {pd.Timestamp(x).normalize(): i for i, x in enumerate(dates)},
                              d.open.to_numpy(float), d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float))

    by = {tf: [(str(r.symbol), float(r.weight)) for r in g.sort_values("rank").itertuples()] for tf, g in targets.groupby("trade_from")}
    switch_m = sorted({int(str(tf)[5:7]) for tf in by})
    all_d = set()
    for p in paths.values():
        all_d.update(p.dates.tolist())
    cal = pd.DatetimeIndex(sorted(all_d)).normalize()
    cal = cal[(cal >= "2020-01-01") & (cal <= BT_END)]
    top_k = int(cfg["top_k"])
    idle = INITIAL * (1 - INVEST)
    slots = [Slot(cash=INITIAL * INVEST / top_k) for _ in range(top_k)]
    target = by.get("2020-01-01") or by[min(by)]
    eq_rows = []

    def port_eq(dt):
        tot = idle
        for s in slots:
            if s.symbol and s.shares > 0:
                path = paths.get(s.symbol)
                j = path.date_to_i.get(dt) if path else None
                tot += s.cash + s.shares * (float(path.c[j]) if path is not None and j is not None else s.entry_px)
            else:
                tot += s.cash
        return tot

    for dt0 in cal:
        dt = pd.Timestamp(dt0).normalize()
        md = cal[cal.to_period("M") == dt.to_period("M")]
        if len(md) and dt == md[0] and dt.month in switch_m:
            cands = [tf for tf in by if tf[:7] == dt.strftime("%Y-%m")]
            if cands:
                target = by[min(cands)]
        tset = {s for s, _ in target}
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
                lim = limit_down_state(prev_close=prev, open_px=oi, high_px=hi, low_px=li, close_px=ci, limit_down_pct=0.10, tick=TICK_SIZE)
                if not bool(lim["locked"]):
                    px = float(lim["limit_px"] if bool(lim["opened"]) else stop) * (1 - SLIP)
                    proceeds = slot.shares * px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    slot.cash += proceeds - fee
                    slot.shares = 0
                    slot.symbol = None
                    slot.buy_i = -1
                    slot.entry_px = 0
        held = {s.symbol for s in slots if s.symbol and s.shares > 0}
        for s in slots:
            if s.shares <= 0 and s.symbol and s.symbol not in tset:
                s.symbol = None
        pending = {s.symbol for s in slots if s.symbol and s.shares <= 0}
        total = port_eq(dt)
        for slot in slots:
            if slot.shares > 0:
                continue
            if slot.symbol is None:
                assign = aw = None
                for sym, w in target:
                    if sym in held or sym in pending or sym not in paths:
                        continue
                    if any(s.symbol == sym for s in slots if s is not slot):
                        continue
                    assign, aw = sym, w
                    break
                if assign is None:
                    continue
                want = total * aw
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
                slot.weight = aw
                pending.add(assign)
                total = port_eq(dt)
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
            if allows and not blocked and hi + 1e-12 >= buy and slot.cash > 0:
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
        eq_rows.append({"date": dt, "equity": port_eq(dt)})

    eq = pd.DataFrame(eq_rows).set_index("date").sort_index()
    st = nav_stats(eq.equity / float(eq.equity.iloc[0]))
    ydf = pd.DataFrame([{"year": int(y), **nav_stats(g / float(g.iloc[0]))} for y, g in eq.equity.groupby(eq.index.year)])
    eq.to_csv(OUT / "nav_slot_best.csv")
    ydf.to_csv(OUT / "yearly_slot_best.csv", index=False, float_format="%.4f")

    log("\n=== 冻结参数 · 槽位 ===")
    log(f"全段={st['ret']:+.1f}% mdd={st['mdd']:.1f}%")
    log("分年: " + ", ".join(f"{int(r.year)}:{r.ret:+.1f}%" for r in ydf.itertuples()))
    log("盲测各期(研究):")
    for r in det[det.oos_year.isin(BLIND_YEARS)].itertuples():
        log(f"  {r.tag}: {r.ret:+.1f}% | {r.names}")

    top20 = cand.head(20)
    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>调参盲测</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #ddd;padding:5px;text-align:right}}
th{{background:#f5f5f5}}td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}}.kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
.warn{{color:#a40}}</style></head><body>
<h1>2020–2023 筛选 → 2023–2024 调参 → 盲测 2025/2026</h1>
<p>选参未使用盲测段。研究组合按权重加权。</p>
<div class=kpi>
<div><b>最优</b><br>{cfg['rule']} Top{cfg['top_k']} {cfg['freq']}</div>
<div><b>train</b><br>{best_cfg['train_ret']:+.1f}%</div>
<div><b>valid</b><br>{best_cfg['valid_ret']:+.1f}%</div>
<div class=warn><b>盲测2025</b><br>{best_cfg['blind_2025']:+.1f}%</div>
<div class=warn><b>盲测2026</b><br>{best_cfg['blind_2026']:+.1f}%</div>
<div><b>槽位全段</b><br>{st['ret']:+.1f}%</div>
</div>
<pre>{json.dumps(cfg, ensure_ascii=False, indent=2)}</pre>
<h2>Top20 by valid</h2>{top20.round(2).to_html(index=False)}
<h2>最优各期OOS</h2>{det.round(2).to_html(index=False)}
<h2>槽位分年</h2>{ydf.round(2).to_html(index=False)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。</p></body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "best_params.json").write_text(
        json.dumps(
            {"cfg": cfg, "train_ret": best_cfg["train_ret"], "valid_ret": best_cfg["valid_ret"],
             "blind_2025": best_cfg["blind_2025"], "blind_2026": best_cfg["blind_2026"], "slot": st},
            ensure_ascii=False, indent=2, default=float,
        ),
        encoding="utf-8",
    )
    # 覆盖旧慢脚本入口：同路径结果
    log(f"→ {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
