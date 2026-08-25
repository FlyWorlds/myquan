"""因子13·夏普波动率契合：2020–2025 选股 → 2026 盲测 + 分年/月正反馈。

  python strategy/run_factor13_sharpe_vol.py

池：中证500∪1000 主板缓存（≈中证1500中小盘），无创业板/科创板/ST。
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

from strategy.factor13_sharpe_vol import (  # noqa: E402
    DEFAULT_PARAMS,
    build_stock_features,
    enrich_scores,
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

OUT = _MYQUAN / "backtest" / "factor13_sharpe_vol"
PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
TOP_K = 8
SEEDS = {"sh600330", "sh600552"}


def _load_panel() -> pd.DataFrame:
    if not PANEL.exists():
        raise FileNotFoundError(f"缺少年面板: {PANEL}")
    return pd.read_parquet(PANEL)


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name", "index"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    # 剔 ST
    names = meta["name"].astype(str)
    meta = meta[~names.str.upper().str.contains("ST", regex=False)]
    # 主板
    mb = meta["symbol"].str.startswith("sh60") | meta["symbol"].str.startswith("sz00")
    meta = meta[mb]
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def _universe_meta() -> dict:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name", "index"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    names = meta["name"].astype(str)
    meta = meta[~names.str.upper().str.contains("ST", regex=False)]
    mb = meta["symbol"].str.startswith("sh60") | meta["symbol"].str.startswith("sz00")
    meta = meta[mb]
    return {
        "universe": "CSI500 ∪ CSI1000 mainboard (≈CSI1500 mid-small, no ChiNext/STAR/ST)",
        "n_symbols": int(meta["symbol"].nunique()),
        "by_index": meta["index"].value_counts().to_dict(),
        "note": "官方无独立「中证1500」成分文件；本池为 500+1000 主板并集。",
    }


def run_port(symbols: list[str], start: str, end: str, name_map: dict) -> tuple[dict, list, pd.Series]:
    navs: dict[str, pd.Series] = {}
    rows: list[dict] = []
    for sym in symbols:
        res = backtest_symbol(sym, name_map.get(sym, sym), start, end)
        if not res.get("ok"):
            continue
        navs[sym] = res["nav"]
        rows.append({k: res[k] for k in ("symbol", "name", "ret", "bh", "excess", "mdd", "bh_dd", "sharpe")})
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    return nav_stats(port), rows, port


def monthly_table(nav: pd.Series) -> pd.DataFrame:
    if nav.empty:
        return pd.DataFrame()
    m = nav.resample("ME").last().pct_change().dropna() * 100
    return pd.DataFrame({"month": [i.strftime("%Y-%m") for i in m.index], "ret_pct": m.values})


def yearly_feedback(panel: pd.DataFrame, name_map: dict) -> pd.DataFrame:
    """Walk-forward：用 ≤Y 年夏普波动率特征选 TopK → 回测 Y+1。"""
    recs = []
    for fit_end in range(2022, 2026):  # 至少 2020-2022 三年起步
        picks = select_top(panel, fit_end_year=fit_end, k=TOP_K)
        oos = fit_end + 1
        start = f"{oos}0101"
        end = OOS_END if oos >= 2026 else f"{oos}1231"
        if start > OOS_END:
            continue
        st, rows, port = run_port(picks["symbol"].tolist(), start, end, name_map)
        med = float(np.median([r["ret"] for r in rows])) if rows else float("nan")
        pos_n = sum(1 for r in rows if r["ret"] > 0)
        mtab = monthly_table(port)
        pos_m = int((mtab["ret_pct"] > 0).sum()) if len(mtab) else 0
        recs.append(
            {
                "fit_end": fit_end,
                "oos": oos,
                "n": len(rows),
                "ret": st["ret"],
                "med": med,
                "mdd": st["mdd"],
                "sharpe": st["sharpe"],
                "pos_stocks": pos_n,
                "pos_months": pos_m,
                "n_months": len(mtab),
                "symbols": ",".join(r["symbol"] for r in rows),
                "names": "、".join(r["name"] for r in rows),
            }
        )
        print(
            f"  fit≤{fit_end}→{oos}: N={len(rows)} 等权={st['ret']:+.1f}% "
            f"中位={med:+.1f}% 回撤={st['mdd']:.1f}% 正票={pos_n}/{len(rows)} "
            f"正月={pos_m}/{len(mtab)}"
        )
    return pd.DataFrame(recs)


def write_report(
    *,
    univ: dict,
    picks: pd.DataFrame,
    detail: pd.DataFrame,
    port_stats: dict,
    monthly: pd.DataFrame,
    wf: pd.DataFrame,
    seed_feat: pd.DataFrame,
) -> None:
    lines = [
        "# 因子13 · 夏普波动率契合选股报告",
        "",
        "## 因子定义",
        "```",
        rules_text().strip(),
        "```",
        "",
        f"**股票池**：{univ['universe']}；N={univ['n_symbols']}；{univ['note']}",
        f"**成分分布**：{univ['by_index']}",
        "",
        "## 种子参照（天通/凯盛 2020–2025）",
        "",
        seed_feat.to_markdown(index=False) if not seed_feat.empty else "(无)",
        "",
        f"## 2025末选 → 2026 盲测 Top{TOP_K}",
        "",
        picks[
            [
                "symbol",
                "name",
                "sharpe_mean",
                "sharpe_vol",
                "pos_yr",
                "pos_ex",
                "ex_mean",
                "feedback",
                "score_sv",
            ]
        ].round(4).to_markdown(index=False),
        "",
        "### 单票 2026",
        "",
        detail.round(2).to_markdown(index=False) if not detail.empty else "(无)",
        "",
        "### 等权组合 2026",
        "",
        f"- 等权收益：**{port_stats.get('ret', float('nan')):+.2f}%**",
        f"- 最大回撤：{port_stats.get('mdd', float('nan')):.2f}%",
        f"- 夏普：{port_stats.get('sharpe', float('nan')):.2f}",
        f"- 区间：{OOS_START} → {OOS_END}",
        "",
        "### 等权月收益",
        "",
        monthly.round(2).to_markdown(index=False) if not monthly.empty else "(无)",
        "",
        "## Walk-forward 正反馈（fit≤Y → Y+1）",
        "",
        wf.round(2).to_markdown(index=False) if not wf.empty else "(无)",
        "",
        "### 正反馈解读",
    ]
    if not wf.empty:
        pos_years = int((wf["ret"] > 0).sum())
        avg = float(wf["ret"].mean())
        lines.append(
            f"- OOS 年正收益：{pos_years}/{len(wf)}；均值 {avg:+.1f}%"
        )
        if len(wf) >= 2:
            seq = (wf.sort_values("oos")["ret"] > 0).astype(int).tolist()
            fb = sum(1 for i in range(len(seq) - 1) if seq[i] == 1 and seq[i + 1] == 1)
            den = sum(1 for i in range(len(seq) - 1) if seq[i] == 1)
            rate = fb / den if den else float("nan")
            lines.append(f"- 上年组合盈利 → 下年仍盈利：{rate:.0%}（{fb}/{den}）")
    lines.extend(
        [
            "",
            "> 研究用途，不构成投资建议。幸存者偏差：成分取当前 500/1000 主板缓存。",
            "",
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")

    # 简易 HTML
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>因子13 夏普波动率契合</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.pos{{color:#0a7}} .neg{{color:#c33}} h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap}} .kpi div{{background:#f7f7f7;padding:12px 16px;border-radius:8px}}
pre{{background:#f6f8fa;padding:12px;overflow:auto;font-size:12px}}
</style></head><body>
<h1>因子13 · 夏普波动率契合</h1>
<p>{univ['universe']} · N={univ['n_symbols']} · {univ['note']}</p>
<div class="kpi">
  <div><b>2026等权</b><br><span class="{'pos' if port_stats.get('ret',0)>0 else 'neg'}">{port_stats.get('ret', float('nan')):+.2f}%</span></div>
  <div><b>回撤</b><br>{port_stats.get('mdd', float('nan')):.2f}%</div>
  <div><b>夏普</b><br>{port_stats.get('sharpe', float('nan')):.2f}</div>
  <div><b>TopK</b><br>{TOP_K}</div>
</div>
<pre>{rules_text().strip()}</pre>
<h2>入选（2025末）</h2>
{picks[['symbol','name','sharpe_mean','sharpe_vol','pos_yr','pos_ex','ex_mean','feedback','score_sv']].round(3).to_html(index=False)}
<h2>单票 2026</h2>
{detail.round(2).to_html(index=False) if not detail.empty else '<p>无</p>'}
<h2>等权月收益</h2>
{monthly.round(2).to_html(index=False) if not monthly.empty else '<p>无</p>'}
<h2>Walk-forward</h2>
{wf.round(2).to_html(index=False) if not wf.empty else '<p>无</p>'}
<p style="color:#888;font-size:12px">研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panel = _load_panel()
    name_map = _name_map()
    univ = _universe_meta()
    print(rules_text())
    print(f"池: {univ}")

    # 全样本特征
    feat = enrich_scores(build_stock_features(panel, fit_end_year=2025))
    feat.to_csv(OUT / "features_2020_2025.csv", index=False, float_format="%.6f")
    seed_feat = feat[feat["symbol"].isin(SEEDS)][
        ["symbol", "name", "sharpe_mean", "sharpe_vol", "pos_yr", "pos_ex", "ex_mean", "feedback", "score_sv"]
    ]
    print("\n种子特征:")
    print(seed_feat.to_string(index=False))

    picks = select_top(panel, fit_end_year=2025, k=TOP_K)
    picks.to_csv(OUT / "picks_2025_for_2026.csv", index=False, float_format="%.6f")
    print(f"\n入选 Top{TOP_K}:")
    print(
        picks[
            ["symbol", "name", "sharpe_mean", "sharpe_vol", "pos_ex", "feedback", "score_sv"]
        ].to_string(index=False)
    )

    print("\n=== 2026 盲测 ===")
    st, rows, port = run_port(picks["symbol"].tolist(), OOS_START, OOS_END, name_map)
    detail = pd.DataFrame(rows)
    detail.to_csv(OUT / "oos_2026_detail.csv", index=False, float_format="%.4f")
    if not port.empty:
        port.to_csv(OUT / "oos_2026_port_nav.csv", header=["nav"])
    monthly = monthly_table(port)
    monthly.to_csv(OUT / "oos_2026_monthly.csv", index=False, float_format="%.4f")

    for r in rows:
        print(
            f"  {r['name']:8s} {r['symbol']}  策略={r['ret']:+7.2f}%  "
            f"持有={r['bh']:+7.2f}%  超额={r['excess']:+7.2f}%  回撤={r['mdd']:.1f}%"
        )
    print(
        f"\n等权: {st['ret']:+.2f}%  回撤={st['mdd']:.2f}%  夏普={st['sharpe']:.2f}  "
        f"盈利={sum(1 for r in rows if r['ret']>0)}/{len(rows)}"
    )
    if not monthly.empty:
        print("月收益:")
        for _, row in monthly.iterrows():
            print(f"  {row['month']}: {row['ret_pct']:+.1f}%")

    print("\n=== Walk-forward 正反馈 ===")
    wf = yearly_feedback(panel, name_map)
    wf.to_csv(OUT / "walkforward.csv", index=False, float_format="%.4f")

    meta = {
        "factor": "factor13_sharpe_vol",
        "top_k": TOP_K,
        "params": DEFAULT_PARAMS,
        "universe": univ,
        "oos": {"start": OOS_START, "end": OOS_END, **st, "n": len(rows)},
        "picks": picks["symbol"].tolist(),
    }
    # jsonify numpy
    def _j(o):
        if isinstance(o, (np.floating, float)):
            return None if (isinstance(o, float) and math.isnan(o)) else float(o)
        if isinstance(o, (np.integer, int)):
            return int(o)
        if isinstance(o, tuple):
            return list(o)
        if isinstance(o, dict):
            return {k: _j(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_j(v) for v in o]
        return o

    (OUT / "meta.json").write_text(
        json.dumps(_j(meta), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_report(
        univ=univ,
        picks=picks,
        detail=detail,
        port_stats=st,
        monthly=monthly,
        wf=wf,
        seed_feat=seed_feat,
    )
    print(f"\n报告 → {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
