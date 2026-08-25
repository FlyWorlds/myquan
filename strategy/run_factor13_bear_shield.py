"""因子13·熊市盾牌回测入口（默认季+年融合 qy_blend）。

  python strategy/run_factor13_bear_shield.py
"""

from __future__ import annotations

import json
import logging
import math
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

from strategy.factor13_bear_shield import (  # noqa: E402
    DEFAULT_PARAMS,
    rules_text,
    select_top,
)
from strategy.run_factor13_top10_quarterly import (  # noqa: E402
    OOS_END,
    OOS_START,
    backtest_symbol,
    equal_weight,
    nav_stats,
)

OUT = _MYQUAN / "backtest" / "factor13_bear_shield"
PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"

PRIMARY = {"rule": "qy_blend", "top_k": 3, "use_per_stock_thr": True}
DEFENSE = {"rule": "bear_abs_pos_floor", "top_k": 3}


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    meta = meta[~meta["name"].astype(str).str.upper().str.contains("ST")]
    mb = meta["symbol"].str.startswith("sh60") | meta["symbol"].str.startswith("sz00")
    meta = meta[mb]
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def run_port(symbols: list[str], start: str, end: str, name_map: dict):
    navs, rows = {}, []
    for s in symbols:
        res = backtest_symbol(s, name_map.get(s, s), start, end)
        if not res.get("ok"):
            continue
        navs[s] = res["nav"]
        rows.append({k: res[k] for k in ("symbol", "name", "ret", "bh", "excess", "mdd", "bh_dd", "sharpe")})
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    return nav_stats(port), rows, port


def monthly_table(nav: pd.Series) -> pd.DataFrame:
    if nav.empty:
        return pd.DataFrame()
    m = nav.resample("ME").last().pct_change().dropna() * 100
    return pd.DataFrame({"month": [i.strftime("%Y-%m") for i in m.index], "ret_pct": m.values})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL)
    q_panel = pd.read_parquet(Q_PANEL) if Q_PANEL.exists() else None
    name_map = _name_map()
    params = {**DEFAULT_PARAMS, **PRIMARY}
    print(rules_text(params))

    picks = select_top(panel, fit_end_year=2025, params=params, quarter_panel=q_panel)
    picks.to_csv(OUT / "picks_2025_for_2026.csv", index=False, float_format="%.4f")
    show_cols = [
        c
        for c in ("symbol", "name", "obear_ret", "obear_ex", "q_obear_ex", "q_obear_hit", "score")
        if c in picks.columns
    ]
    print(f"入选 Top{params['top_k']}:")
    print(picks[show_cols].round(2).to_string(index=False))

    st, rows, port = run_port(picks["symbol"].tolist(), OOS_START, OOS_END, name_map)
    detail = pd.DataFrame(rows)
    detail.to_csv(OUT / "oos_2026_detail.csv", index=False, float_format="%.4f")
    if not port.empty:
        port.to_csv(OUT / "oos_2026_port_nav.csv", header=["nav"])
    mt = monthly_table(port)
    mt.to_csv(OUT / "oos_2026_monthly.csv", index=False, float_format="%.4f")

    print("\n=== 2026 ===")
    for r in rows:
        print(
            f"  {r['name']:8s} 策略={r['ret']:+7.2f}% BH={r['bh']:+7.2f}% "
            f"超额={r['excess']:+7.2f}% 回撤={r['mdd']:.1f}%"
        )
    ex_med = float(np.median([r["excess"] for r in rows])) if rows else float("nan")
    print(f"等权 {st['ret']:+.2f}% 回撤{st['mdd']:.1f}% 超额中位{ex_med:+.1f}%")
    if not mt.empty:
        print("月收益:")
        for _, row in mt.iterrows():
            print(f"  {row['month']}: {row['ret_pct']:+.1f}%")

    mkt = (
        panel[np.isclose(panel.thr.astype(float), 0.025)]
        .drop_duplicates(["symbol", "year"])
        .groupby("year")["bh"]
        .median()
    )
    wf = []
    print("\n=== Walk-forward ===")
    for fit_end in range(2022, 2026):
        pk = select_top(panel, fit_end_year=fit_end, params=params, quarter_panel=q_panel)
        oos = fit_end + 1
        start, end = f"{oos}0101", (OOS_END if oos >= 2026 else f"{oos}1231")
        st2, rows2, port2 = run_port(pk["symbol"].tolist(), start, end, name_map)
        mt2 = monthly_table(port2)
        is_bear = bool(mkt.get(oos, 0) < 0)
        rec = {
            "fit_end": fit_end,
            "oos": oos,
            "is_bear": int(is_bear),
            "market_bh_med": float(mkt.get(oos, np.nan)),
            "n": len(rows2),
            "ret": st2["ret"],
            "mdd": st2["mdd"],
            "ex_med": float(np.median([r["excess"] for r in rows2])) if rows2 else np.nan,
            "pos": sum(1 for r in rows2 if r["ret"] > 0),
            "pos_months": int((mt2["ret_pct"] > 0).sum()) if len(mt2) else 0,
            "n_months": len(mt2),
            "names": "、".join(r["name"] for r in rows2),
        }
        wf.append(rec)
        print(
            f"  ≤{fit_end}→{oos} {'BEAR' if is_bear else 'BULL/FLAT'}: "
            f"ret={st2['ret']:+.1f}% exMed={rec['ex_med']:+.1f}% mdd={st2['mdd']:.1f}% | {rec['names']}"
        )
    wdf = pd.DataFrame(wf)
    wdf.to_csv(OUT / "walkforward.csv", index=False, float_format="%.4f")

    picks_ns = select_top(
        panel,
        fit_end_year=2025,
        params=params,
        quarter_panel=q_panel,
        exclude={"sh600330", "sh600552"},
    )
    st_ns, rows_ns, _ = run_port(picks_ns["symbol"].tolist(), OOS_START, OOS_END, name_map)
    ex_ns = float(np.median([r["excess"] for r in rows_ns])) if rows_ns else float("nan")
    print(
        f"\n去种子 Top{params['top_k']}: {st_ns['ret']:+.1f}% exMed={ex_ns:+.1f}% | "
        + "、".join(r["name"] for r in rows_ns)
    )

    def_params = {**DEFAULT_PARAMS, **DEFENSE}
    picks_def = select_top(panel, fit_end_year=2025, params=def_params, quarter_panel=q_panel)
    st_def, rows_def, _ = run_port(picks_def["symbol"].tolist(), OOS_START, OOS_END, name_map)
    ex_def = float(np.median([r["excess"] for r in rows_def])) if rows_def else float("nan")
    print(
        f"对照 defense floor×3: {st_def['ret']:+.1f}% exMed={ex_def:+.1f}% mdd={st_def['mdd']:.1f}% | "
        + "、".join(r["name"] for r in rows_def)
    )

    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>熊市盾牌 qy_blend</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}}.kpi div{{background:#f7f7f7;padding:12px 14px;border-radius:8px}}
.pos{{color:#0a7}} pre{{background:#f6f8fa;padding:12px;font-size:12px}}
</style></head><body>
<h1>因子13 · 熊市盾牌 qy_blend Top5</h1>
<p>季熊+年熊融合默认；纯月熊不稳（见 factor13_bear_multi）。</p>
<div class="kpi">
<div><b>2026等权</b><br><span class="pos">{st['ret']:+.1f}%</span></div>
<div><b>超额中位</b><br><span class="pos">{ex_med:+.1f}%</span></div>
<div><b>回撤</b><br>{st['mdd']:.1f}%</div>
<div><b>去种子</b><br>{st_ns['ret']:+.1f}% / ex {ex_ns:+.1f}%</div>
<div><b>defense×3</b><br>{st_def['ret']:+.1f}% / mdd {st_def['mdd']:.1f}%</div>
</div>
<pre>{rules_text(params).strip()}</pre>
<h2>入选</h2>
{picks[show_cols].round(2).to_html(index=False)}
<h2>2026单票</h2>
{detail.round(2).to_html(index=False)}
<h2>月收益</h2>
{mt.round(2).to_html(index=False) if not mt.empty else ''}
<h2>Walk-forward</h2>
{wdf.round(2).to_html(index=False)}
<p style="color:#888;font-size:12px">研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")

    def _j(o):
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
            return None
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, dict):
            return {k: _j(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_j(v) for v in o]
        return o

    meta = {
        "factor": "factor13_bear_shield",
        "params": params,
        "oos": {**st, "ex_med": ex_med, "noseed_ret": st_ns["ret"], "noseed_ex_med": ex_ns},
        "defense": {"ret": st_def["ret"], "ex_med": ex_def, "mdd": st_def["mdd"]},
        "picks": picks["symbol"].tolist(),
    }
    (OUT / "meta.json").write_text(json.dumps(_j(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告 → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
