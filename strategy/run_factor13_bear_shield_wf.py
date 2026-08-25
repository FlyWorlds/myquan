"""因子13·熊市盾牌 · 反过拟合 Walk-Forward（默认 thr* Top3）。

要点：
  · 交易年 T：选股/thr* 仅用 ≤T-1（无偷看）
  · 个股 thr*：{2%,2.5%,3%} 拟合窗夏普；天通钉 ±3%
  · 稳定性：近 2 个拟合年末均进 Top12，再取 Top3
  · 门槛冻结，不按 2026 再调参

  python strategy/run_factor13_bear_shield_wf.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
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
from backtest.universe_zz500_1000 import CACHE_DIR  # noqa: E402
from strategy.factor13_bear_shield import (  # noqa: E402
    DEFAULT_PARAMS,
    PIN_THR,
    fit_symbol_thresholds,
    resolve_trade_thr,
    rules_text,
    select_top,
    select_top_stable,
)

OUT = _MYQUAN / "backtest" / "factor13_bear_shield_wf"
PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"

TRADE_YEARS = list(range(2023, 2027))  # 2026 到数据末日
OOS_END = "2026-08-25"


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def _load_sym(sym: str) -> pd.DataFrame | None:
    d = load_daily(sym)
    if d is None:
        p = CACHE_DIR / f"{sym}_daily_qfq.parquet"
        if not p.exists():
            return None
        d = pd.read_parquet(p)
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    else:
        d = d.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    return d.reset_index(drop=True)


def _nav_stats(nav: pd.Series) -> dict:
    if len(nav) < 5:
        return {"ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    ret = float(nav.iloc[-1] / nav.iloc[0] - 1) * 100
    mdd = abs(float((nav / nav.cummax() - 1).min() * 100))
    r = nav.pct_change().dropna()
    sh = float(r.mean() / r.std() * np.sqrt(252)) if float(r.std()) > 1e-12 else np.nan
    return {"ret": ret, "mdd": mdd, "sharpe": sh}


def sim_window(sym: str, thr: float, start: str, end: str) -> dict:
    d = _load_sym(sym)
    if d is None or len(d) < 40:
        return {"ok": 0}
    dates = pd.DatetimeIndex(pd.to_datetime(d["date"])).normalize()
    eq, _ = simulate_open_break(
        d["open"].to_numpy(float),
        d["high"].to_numpy(float),
        d["low"].to_numpy(float),
        d["close"].to_numpy(float),
        thr=float(thr),
    )
    s = pd.Series(eq, index=dates)
    c = pd.Series(d["close"].to_numpy(float), index=dates)
    m = (s.index >= start) & (s.index <= end)
    s, c = s[m], c[m]
    if len(s) < 5:
        return {"ok": 0}
    nav = s / float(s.iloc[0])
    st = _nav_stats(nav)
    bh = float(c.iloc[-1] / c.iloc[0] - 1) * 100
    return {"ok": 1, "nav": nav, "bh": bh, "excess": st["ret"] - bh, **st}


def equal_weight(navs: dict[str, pd.Series]) -> pd.Series:
    df = pd.concat(navs, axis=1).sort_index().ffill()
    port = (1 + df.pct_change().mean(axis=1).fillna(0)).cumprod()
    port.iloc[0] = 1.0
    return port


def year_bounds(y: int) -> tuple[str, str]:
    start = f"{y}-01-01"
    end = OOS_END if y >= 2026 else f"{y}-12-31"
    return start, end


def run_year_basket(picks: pd.DataFrame, params: dict, start: str, end: str) -> tuple[dict, pd.DataFrame, pd.Series]:
    navs, rows = {}, []
    pin = {str(k).lower(): float(v) for k, v in (params.get("pin_thr") or PIN_THR).items()}
    for _, r in picks.iterrows():
        sym = str(r["symbol"]).lower()
        if sym in pin:
            thr = float(pin[sym])
        elif "thr" in picks.columns and pd.notna(r.get("thr")):
            thr = float(r["thr"])
        else:
            thr = resolve_trade_thr(sym, params)
        name = str(r.get("name", sym))
        res = sim_window(sym, thr, start, end)
        if not res.get("ok"):
            continue
        navs[sym] = res["nav"]
        rows.append(
            {
                "symbol": sym,
                "name": name,
                "thr": thr,
                "ret": res["ret"],
                "bh": res["bh"],
                "excess": res["excess"],
                "mdd": res["mdd"],
                "sharpe": res["sharpe"],
                "stab_hits": r.get("stab_hits", np.nan),
                "score": r.get("score", np.nan),
            }
        )
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    return _nav_stats(port), pd.DataFrame(rows), port


def leaky_once(panel, q_panel, params, name_map) -> tuple[dict, pd.DataFrame]:
    """对照：用满 2020–2025 定 thr/名单，再测 2026（故意泄露）。"""
    leaky = {**params, "use_per_stock_thr": True, "stability_lookback": 1, "stability_min_hits": 1}
    picks = select_top(panel, fit_end_year=2025, params=leaky, quarter_panel=q_panel, k=3)
    if picks.empty:
        return {}, picks
    picks["name"] = picks.apply(
        lambda r: r["name"] if str(r.get("name", "")).strip() else name_map.get(str(r["symbol"]), ""),
        axis=1,
    )
    # thr from fit on 2020-2025 including for trade
    from strategy.factor13_bear_shield import fit_symbol_thresholds

    thr_df = fit_symbol_thresholds(panel, fit_start_year=2020, fit_end_year=2025)
    tm = dict(zip(thr_df["symbol"], thr_df["thr"]))
    picks = picks.copy()
    picks["thr"] = picks["symbol"].map(lambda s: tm.get(str(s).lower(), 0.025))
    st, detail, _ = run_year_basket(picks, {**leaky, "pin_thr": {}}, *year_bounds(2026))
    # override thr in sim via picks column — run_year_basket uses resolve_trade_thr; patch:
    navs, rows = {}, []
    for _, r in picks.iterrows():
        sym = str(r["symbol"]).lower()
        thr = float(r["thr"])
        res = sim_window(sym, thr, *year_bounds(2026))
        if not res.get("ok"):
            continue
        navs[sym] = res["nav"]
        rows.append({"symbol": sym, "name": r["name"], "thr": thr, "ret": res["ret"], "excess": res["excess"]})
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    return _nav_stats(port), pd.DataFrame(rows)


def html_report(yearly: pd.DataFrame, targets: pd.DataFrame, stitch: dict, y2026: dict, leaky: dict, picks26: pd.DataFrame) -> str:
    def tbl(df):
        if df is None or df.empty:
            return "<p>（空）</p>"
        show = df.copy()
        for c in show.select_dtypes(include=[float, np.floating]).columns:
            show[c] = show[c].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")
        return show.to_html(index=False, border=0, classes="t")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>因子13 熊盾 · 反过拟合 WF</title>
<style>
body{{font-family:-apple-system,PingFang SC,sans-serif;max-width:980px;margin:32px auto;padding:0 16px;
color:#e8eaed;background:#0f1115;line-height:1.55}}
h1,h2{{font-weight:650}} h2{{margin-top:2rem;border-bottom:1px solid #2a2f3a;padding-bottom:6px}}
.muted{{color:#9aa3b2}} .t{{width:100%;border-collapse:collapse;font-size:13px}}
.t th,.t td{{border-bottom:1px solid #2a2f3a;padding:6px 8px;text-align:left}}
.good{{color:#3dd68c}} .warn{{color:#e6c07b}} .bad{{color:#f07178}}
</style></head><body>
<h1>因子13 · 熊市盾牌 · 反过拟合 Walk-Forward</h1>
<p class="muted">交易年 T 仅用 ≤T-1；个股 thr*（夏普择优，天通钉±3%）；近2窗 Top12 稳定性 → Top3。
门槛冻结。研究用途，非投资建议。</p>

<h2>样本外主结果（拼接）</h2>
<p>2023→2026 拼接：<b class="good">{stitch.get('ret', float('nan')):+.1f}%</b>
　回撤 {stitch.get('mdd', float('nan')):.1f}%　夏普 {stitch.get('sharpe', float('nan')):.2f}</p>
<p>其中 2026YTD：<b class="good">{y2026.get('ret', float('nan')):+.1f}%</b>
　回撤 {y2026.get('mdd', float('nan')):.1f}%</p>
<p class="warn">对照「泄露」一次定名单测2026：{leaky.get('ret', float('nan')):+.1f}%
（仅作偏差演示，不作推荐）</p>

<h2>分年 OOS（严格 WF）</h2>
{tbl(yearly)}

<h2>2026 持仓（fit≤2025）</h2>
{tbl(picks26)}

<h2>历年目标名单</h2>
{tbl(targets)}

<h2>过拟合治理清单</h2>
<ul>
<li>thr* 仅用 ≤T-1，禁止交易年偷看</li>
<li>稳定性过滤，降低单年噪声冠军</li>
<li>门槛不按最新 OOS 回写</li>
</ul>
</body></html>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL)
    q_panel = pd.read_parquet(Q_PANEL)
    name_map = _name_map()
    params = {**DEFAULT_PARAMS}
    print(rules_text(params))

    target_rows = []
    year_stats = []
    nav_pieces = []
    detail_all = []

    for trade_y in TRADE_YEARS:
        fit_end = trade_y - 1
        if fit_end < int(params["fit_start_year"]) + 1:
            continue
        thr_map = None
        if bool(params.get("use_per_stock_thr", True)):
            thr_df = fit_symbol_thresholds(
                panel,
                fit_start_year=int(params.get("fit_start_year", 2020)),
                fit_end_year=int(fit_end),
                pin=params.get("pin_thr", PIN_THR),
            )
            thr_map = dict(zip(thr_df["symbol"], thr_df["thr"])) if len(thr_df) else {}
        picks = select_top_stable(
            panel,
            fit_end_year=fit_end,
            params=params,
            quarter_panel=q_panel,
            thr_map=thr_map,
        )
        if picks.empty:
            print(f"{trade_y}: 无入选")
            continue
        picks = picks.copy()
        picks["name"] = picks.apply(
            lambda r: r["name"] if str(r.get("name", "")).strip() else name_map.get(str(r["symbol"]), ""),
            axis=1,
        )
        pin = {str(k).lower(): float(v) for k, v in (params.get("pin_thr") or PIN_THR).items()}

        def _thr_row(sym: str, row_thr) -> float:
            s = str(sym).lower()
            if s in pin:
                return float(pin[s])
            if pd.notna(row_thr):
                return float(row_thr)
            if thr_map and s in thr_map:
                return float(thr_map[s])
            return float(params.get("thr", 0.025))

        if "thr" not in picks.columns or picks["thr"].isna().all():
            picks["thr"] = picks["symbol"].map(lambda s: _thr_row(s, np.nan))
        else:
            picks["thr"] = [_thr_row(s, t) for s, t in zip(picks["symbol"], picks["thr"])]
        picks["trade_year"] = trade_y
        picks["fit_end_year"] = fit_end
        for i, r in picks.iterrows():
            target_rows.append(
                {
                    "trade_year": trade_y,
                    "fit_end_year": fit_end,
                    "rank": int(i) + 1,
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "thr": float(r["thr"]),
                    "score": float(r.get("score", np.nan)),
                    "stab_hits": int(r.get("stab_hits", 0)) if pd.notna(r.get("stab_hits", np.nan)) else 0,
                }
            )
        start, end = year_bounds(trade_y)
        st, detail, port = run_year_basket(picks, params, start, end)
        detail["trade_year"] = trade_y
        detail_all.append(detail)
        year_stats.append({"trade_year": trade_y, "fit_end": fit_end, **st, "n": len(detail)})
        if len(port):
            nav_pieces.append((trade_y, port))
        names = ", ".join(f"{r['name']}(±{float(r['thr'])*100:.1f}%)" for _, r in picks.iterrows())
        print(f"{trade_y} ←fit{fit_end}: {st['ret']:+.1f}% MDD {st['mdd']:.1f}% | {names}")

    targets = pd.DataFrame(target_rows)
    yearly = pd.DataFrame(year_stats)
    targets.to_csv(OUT / "targets_wf.csv", index=False, float_format="%.4f")
    yearly.to_csv(OUT / "yearly_oos.csv", index=False, float_format="%.4f")
    if detail_all:
        pd.concat(detail_all, ignore_index=True).to_csv(OUT / "detail_by_year.csv", index=False, float_format="%.4f")

    # stitch: compound yearly portfolio returns using each year's daily port chained
    if nav_pieces:
        # reindex each year nav to start at 1, then chain by multiplying terminal
        equity = 1.0
        frames = []
        for y, port in nav_pieces:
            p = port / float(port.iloc[0]) * equity
            frames.append(p)
            equity = float(p.iloc[-1])
        stitch_nav = pd.concat(frames)
        stitch_nav = stitch_nav[~stitch_nav.index.duplicated(keep="last")]
        stitch_st = _nav_stats(stitch_nav)
        stitch_nav.to_csv(OUT / "nav_stitch.csv")
    else:
        stitch_st = {}

    # 2026 slice
    y2026_row = yearly[yearly["trade_year"] == 2026]
    y2026_st = y2026_row.iloc[0].to_dict() if len(y2026_row) else {}
    picks26 = targets[targets["trade_year"] == 2026].copy()

    # leaky contrast
    leaky_st, leaky_detail = leaky_once(panel, q_panel, params, name_map)
    if len(leaky_detail):
        leaky_detail.to_csv(OUT / "leaky_2026_contrast.csv", index=False, float_format="%.4f")
    print(f"\nWF 拼接 2023→今: {stitch_st.get('ret', float('nan')):+.1f}% MDD {stitch_st.get('mdd', float('nan')):.1f}%")
    print(f"WF 2026YTD:       {y2026_st.get('ret', float('nan')):+.1f}%")
    print(f"泄露对照 2026:    {leaky_st.get('ret', float('nan')):+.1f}%（勿作推荐）")

    # turnover of names
    if len(targets):
        by_y = targets.groupby("trade_year")["symbol"].apply(set)
        turns = []
        ys = sorted(by_y.index)
        for a, b in zip(ys, ys[1:]):
            inter = len(by_y[a] & by_y[b])
            turns.append({"from": a, "to": b, "overlap": inter, "turnover": 1 - inter / max(len(by_y[b]), 1)})
        pd.DataFrame(turns).to_csv(OUT / "name_turnover.csv", index=False)
        print("名单重叠:", turns)

    meta = {
        "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items() if k != "pin_thr"},
        "pin_thr": params.get("pin_thr"),
        "trade_years": TRADE_YEARS,
        "stitch": stitch_st,
        "y2026": {k: (float(v) if isinstance(v, (float, np.floating, int)) else v) for k, v in y2026_st.items()},
        "leaky_2026": leaky_st,
        "anti_overfit": [
            "PIT: fit_end = trade_year - 1",
            "no full-universe thr grid",
            "stability 2x Top12",
            "frozen gates",
            "leaky contrast labeled only",
        ],
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "report.html").write_text(
        html_report(yearly, targets, stitch_st, y2026_st, leaky_st, picks26),
        encoding="utf-8",
    )
    print(f"→ {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
