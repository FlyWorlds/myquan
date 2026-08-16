"""策略七（因子1+因子4）回测 → CSV/summary → report_s7.html。"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from strategy import KAICHENG, TIANTONG, run_strategy7  # noqa: E402
from strategy.backtest import metric, monthly_returns_df  # noqa: E402

DIR = Path(__file__).resolve().parent
S1_SUMMARY = DIR / "summary.json"
OUT_HTML = DIR / "report_s7.html"


def _prepare_eq_close(result: Any, daily: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eq = result.equity_curve.sort_index()
    if getattr(eq.index, "tz", None) is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq.index = eq.index.normalize()
    eq = eq.groupby(eq.index).last()

    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    else:
        px["date"] = px["date"].dt.tz_convert("Asia/Shanghai")
    close = px.set_index("date")["close"].astype(float).sort_index()
    close.index = close.index.normalize()
    close = close.resample("D").last().ffill()
    eq = eq.reindex(close.index).ffill()
    return eq, close


def _monthly_rows(
    result: Any,
    daily: pd.DataFrame,
    *,
    label: str,
    initial_cash: float,
) -> pd.DataFrame:
    m = monthly_returns_df(result, daily, initial_cash=initial_cash)
    eq, _ = _prepare_eq_close(result, daily)
    rows = []
    for _, r in m.iterrows():
        month = str(r["月份"])
        period = pd.Period(month, freq="M")
        eq_m = eq[eq.index.to_period("M") == period]
        mdd = float("nan")
        if not eq_m.empty:
            peak = eq_m.cummax()
            dd = (eq_m / peak - 1.0) * 100.0
            mdd = float(dd.min())
        strat = float(r["策略收益%"])
        bh = float(r["持有收益%"])
        end_eq = float(eq_m.iloc[-1]) if not eq_m.empty else float("nan")
        rows.append(
            {
                "月份": month,
                "标的": label,
                "策略%": round(strat, 2),
                "平权持有%": round(bh, 2),
                "超额%": round(strat - bh, 2),
                "月末权益": round(end_eq, 2),
                "月内回撤%": round(mdd, 2) if mdd == mdd else None,
            }
        )
    return pd.DataFrame(rows)


def _yearly_rows(
    result: Any,
    daily: pd.DataFrame,
    *,
    label: str,
    initial_cash: float,
) -> pd.DataFrame:
    eq, close = _prepare_eq_close(result, daily)
    years = sorted(set(eq.index.year) | set(close.index.year))
    rows = []
    for y in years:
        eq_y = eq[eq.index.year == y]
        px_y = close[close.index.year == y]
        if eq_y.empty:
            continue
        prev_eq = eq[eq.index.year < y]
        base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else initial_cash
        strat = (float(eq_y.iloc[-1]) / base_eq - 1.0) * 100.0
        prev_px = close[close.index.year < y]
        base_px = float(prev_px.iloc[-1]) if not prev_px.empty else float(px_y.iloc[0])
        bh = (float(px_y.iloc[-1]) / base_px - 1.0) * 100.0
        peak = eq_y.cummax()
        mdd = float((eq_y / peak - 1.0).min() * 100.0)
        closed = 0
        td = getattr(result, "trades_df", None)
        if td is not None and not td.empty:
            col = next(
                (c for c in ("exit_time", "close_time", "end_time", "timestamp") if c in td.columns),
                None,
            )
            if col:
                cts = pd.to_datetime(td[col])
                if getattr(cts.dt, "tz", None) is not None:
                    cts = cts.dt.tz_convert("Asia/Shanghai")
                closed = int((cts.dt.year == y).sum())
        rows.append(
            {
                "年份": int(y),
                "标的": label,
                "策略%": round(strat, 2),
                "平权持有%": round(bh, 2),
                "超额%": round(strat - bh, 2),
                "年内回撤%": round(mdd, 2),
                "闭环笔数": closed,
            }
        )
    return pd.DataFrame(rows)


def _rolling12m(eq: pd.Series, close: pd.Series, *, label: str) -> pd.DataFrame:
    df = pd.DataFrame({"eq": eq, "close": close}).dropna()
    rows = []
    for i in range(252, len(df)):
        sl = df.iloc[i - 252 : i + 1]
        s_ret = (sl["eq"].iloc[-1] / sl["eq"].iloc[0] - 1.0) * 100.0
        h_ret = (sl["close"].iloc[-1] / sl["close"].iloc[0] - 1.0) * 100.0
        rows.append(
            {
                "日期": sl.index[-1].strftime("%Y-%m-%d"),
                "滚动12M策略%": round(s_ret, 2),
                "滚动12M持有%": round(h_ret, 2),
                "滚动12M超额%": round(s_ret - h_ret, 2),
                "标的": label,
            }
        )
    return pd.DataFrame(rows)


def _portfolio_eq_bh(
    rk: Any, dk: pd.DataFrame, rt: Any, dt: pd.DataFrame, cash: float
) -> tuple[pd.Series, pd.Series]:
    eqk, ck = _prepare_eq_close(rk, dk)
    eqt, ct = _prepare_eq_close(rt, dt)
    idx = eqk.index.union(eqt.index).sort_values()
    pk = eqk.reindex(idx).ffill().fillna(cash)
    pt = eqt.reindex(idx).ffill().fillna(cash)
    port = 0.5 * pk + 0.5 * pt
    bk = ck.reindex(idx).ffill()
    bt = ct.reindex(idx).ffill()
    bh = 0.5 * (bk / bk.iloc[0] * cash) + 0.5 * (bt / bt.iloc[0] * cash)
    return port, bh


def _summary_block(
    result: Any,
    daily: pd.DataFrame,
    monthly: pd.DataFrame,
    rolling: pd.DataFrame,
    *,
    initial_cash: float,
) -> dict[str, Any]:
    eq, close = _prepare_eq_close(result, daily)
    strat = float(metric(result.metrics_df, "total_return_pct"))
    bh = (float(close.iloc[-1]) / float(close.iloc[0]) - 1.0) * 100.0
    m = monthly[monthly["标的"] == monthly["标的"].iloc[0]] if len(monthly) else monthly
    win = float((m["超额%"] > 0).mean() * 100.0) if len(m) else 0.0
    roll_last = float(rolling["滚动12M超额%"].iloc[-1]) if len(rolling) else 0.0
    yr_ex = {}
    for _, r in _yearly_rows(result, daily, label="x", initial_cash=initial_cash).iterrows():
        yr_ex[int(r["年份"])] = float(r["超额%"])
    out = {
        "累计策略%": round(strat, 2),
        "累计平权%": round(bh, 2),
        "累计超额%": round(strat - bh, 2),
        "超额月胜率%": round(win, 1),
        "月均超额%": round(float(m["超额%"].mean()), 2) if len(m) else 0.0,
        "年超额均值%": round(float(pd.Series(list(yr_ex.values())).mean()), 2) if yr_ex else 0.0,
        "2021超额%": round(yr_ex.get(2021, 0.0), 2),
        "2024超额%": round(yr_ex.get(2024, 0.0), 2),
        "2025超额%": round(yr_ex.get(2025, 0.0), 2),
        "2026YTD超额%": round(yr_ex.get(2026, 0.0), 2),
        "滚动12M最新超额%": round(roll_last, 2),
    }
    return out


def _decay_summary(yearly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in yearly["标的"].unique():
        y = yearly[yearly["标的"] == label].sort_values("年份")
        early = y[y["年份"] <= 2022]
        late = y[y["年份"] >= 2023]
        pos = int((y["超额%"] > 0).sum())
        rows.append(
            {
                "标的": label,
                "2020-2022累计超额%": round(float(early["超额%"].sum()), 2),
                "2023-至今累计超额%": round(float(late["超额%"].sum()), 2),
                "2020-2022年均超额%": round(float(early["超额%"].mean()), 2) if len(early) else 0,
                "2023-至今年均超额%": round(float(late["超额%"].mean()), 2) if len(late) else 0,
                "超额为正年数": pos,
                "总年数": len(y),
                "最近滚动12M超额%": None,
            }
        )
    return pd.DataFrame(rows)


def _norm_from_monthly(m: pd.DataFrame) -> tuple[list[str], list[float], list[float]]:
    eq, bh = 100_000.0, 100_000.0
    dates, s, h = [], [], []
    for _, r in m.sort_values("月份").iterrows():
        eq *= 1 + float(r["策略%"]) / 100
        bh *= 1 + float(r["平权持有%"]) / 100
        dates.append(str(r["月份"]))
        s.append(round(eq, 2))
        h.append(round(bh, 2))
    return dates, s, h


def build_data() -> dict[str, Any]:
    rk, dk = run_strategy7(KAICHENG, mode="unified", verbose=False, show_report=False)
    rt, dt = run_strategy7(TIANTONG, mode="unified", verbose=False, show_report=False)
    cash = float(KAICHENG.initial_cash)

    mk = _monthly_rows(rk, dk, label="凯盛科技", initial_cash=cash)
    mt = _monthly_rows(rt, dt, label="天通股份", initial_cash=cash)
    port_eq, port_bh = _portfolio_eq_bh(rk, dk, rt, dt, cash)
    port_close = port_bh  # synthetic bh equity
    mp_rows = []
    for month in sorted(set(mk["月份"]) | set(mt["月份"])):
        subk = mk[mk["月份"] == month]
        subt = mt[mt["月份"] == month]
        if subk.empty or subt.empty:
            continue
        sk, bk = float(subk.iloc[0]["策略%"]), float(subk.iloc[0]["平权持有%"])
        st, bt = float(subt.iloc[0]["策略%"]), float(subt.iloc[0]["平权持有%"])
        mp_rows.append(
            {
                "月份": month,
                "标的": "组合",
                "策略%": round((sk + st) / 2, 2),
                "平权持有%": round((bk + bt) / 2, 2),
                "超额%": round((sk + st) / 2 - (bk + bt) / 2, 2),
                "月末权益": round(float(port_eq[port_eq.index.to_period("M") == pd.Period(month, "M")].iloc[-1]), 2)
                if len(port_eq[port_eq.index.to_period("M") == pd.Period(month, "M")])
                else None,
                "月内回撤%": None,
            }
        )
    mp = pd.DataFrame(mp_rows)

    monthly = pd.concat([mp, mk, mt], ignore_index=True)
    monthly.to_csv(DIR / "monthly_excess_s7.csv", index=False, encoding="utf-8-sig")

    yk = _yearly_rows(rk, dk, label="凯盛科技", initial_cash=cash)
    yt = _yearly_rows(rt, dt, label="天通股份", initial_cash=cash)
    yp_rows = []
    for y in sorted(set(yk["年份"]) | set(yt["年份"])):
        a = yk[yk["年份"] == y].iloc[0]
        b = yt[yt["年份"] == y].iloc[0]
        yp_rows.append(
            {
                "年份": y,
                "标的": "组合",
                "策略%": round((a["策略%"] + b["策略%"]) / 2, 2),
                "平权持有%": round((a["平权持有%"] + b["平权持有%"]) / 2, 2),
                "超额%": round((a["超额%"] + b["超额%"]) / 2, 2),
                "年内回撤%": round((a["年内回撤%"] + b["年内回撤%"]) / 2, 2),
                "闭环笔数": int(a["闭环笔数"] + b["闭环笔数"]),
            }
        )
    yp = pd.DataFrame(yp_rows)
    yearly = pd.concat([yp, yk, yt], ignore_index=True)
    yearly.to_csv(DIR / "yearly_decay_s7.csv", index=False, encoding="utf-8-sig")

    rp = _rolling12m(port_eq, port_close, label="组合")
    rk_r = _rolling12m(*_prepare_eq_close(rk, dk), label="凯盛科技")
    rt_r = _rolling12m(*_prepare_eq_close(rt, dt), label="天通股份")
    rolling = pd.concat([rp, rk_r, rt_r], ignore_index=True)
    rolling.to_csv(DIR / "rolling12m_excess_s7.csv", index=False, encoding="utf-8-sig")

    decay = _decay_summary(yearly)
    for i, label in enumerate(["组合", "凯盛科技", "天通股份"]):
        sub = rolling[rolling["标的"] == label]
        if len(sub):
            decay.loc[decay["标的"] == label, "最近滚动12M超额%"] = float(sub.iloc[-1]["滚动12M超额%"])
    decay.to_csv(DIR / "decay_summary_s7.csv", index=False, encoding="utf-8-sig")

    t0 = str(dk["date"].iloc[0])[:10]
    t1 = str(dk["date"].iloc[-1])[:10]
    s_tot = (port_eq.iloc[-1] / port_eq.iloc[0] - 1) * 100
    b_tot = (port_bh.iloc[-1] / port_bh.iloc[0] - 1) * 100
    roll_p = float(rp["滚动12M超额%"].iloc[-1]) if len(rp) else 0.0
    summary = {
        "区间": f"{t0} → {t1}",
        "口径": "策略七·因子1+因子4(roc_ma60·牛市止损放宽2x)；凯盛2.5%/天通3%；独立半仓等权",
        "组合": {
            "累计策略%": round(float(s_tot), 2),
            "累计平权%": round(float(b_tot), 2),
            "累计超额%": round(float(s_tot - b_tot), 2),
            "超额月胜率%": round(float((mp["超额%"] > 0).mean() * 100.0), 1),
            "月均超额%": round(float(mp["超额%"].mean()), 2),
            "年超额均值%": round(float(yp["超额%"].mean()), 2),
            "2021超额%": round(float(yp.loc[yp["年份"] == 2021, "超额%"].iloc[0]), 2)
            if (yp["年份"] == 2021).any()
            else 0.0,
            "2024超额%": round(float(yp.loc[yp["年份"] == 2024, "超额%"].iloc[0]), 2)
            if (yp["年份"] == 2024).any()
            else 0.0,
            "2025超额%": round(float(yp.loc[yp["年份"] == 2025, "超额%"].iloc[0]), 2)
            if (yp["年份"] == 2025).any()
            else 0.0,
            "2026YTD超额%": round(float(yp.loc[yp["年份"] == 2026, "超额%"].iloc[0]), 2)
            if (yp["年份"] == 2026).any()
            else 0.0,
            "滚动12M最新超额%": round(roll_p, 2),
        },
        "凯盛科技": _summary_block(rk, dk, mk, rk_r, initial_cash=cash),
        "天通股份": _summary_block(rt, dt, mt, rt_r, initial_cash=cash),
    }

    if S1_SUMMARY.exists():
        summary["对比策略一"] = json.loads(S1_SUMMARY.read_text(encoding="utf-8"))

    (DIR / "summary_s7.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"summary": summary, "monthly": monthly, "yearly": yearly, "rolling": rolling, "decay": decay}


def build_html(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    monthly = payload["monthly"]
    yearly = payload["yearly"]
    rolling = payload["rolling"]
    decay = payload["decay"]

    mp = monthly[monthly["标的"] == "组合"].sort_values("月份")
    mk = monthly[monthly["标的"] == "凯盛科技"].sort_values("月份")
    mt = monthly[monthly["标的"] == "天通股份"].sort_values("月份")
    eq_dates, eq_s, eq_h = _norm_from_monthly(mp)
    _, eq_k, _ = _norm_from_monthly(mk)
    _, eq_t, _ = _norm_from_monthly(mt)

    yp = yearly[yearly["标的"] == "组合"].sort_values("年份")
    yk = yearly[yearly["标的"] == "凯盛科技"].sort_values("年份")
    yt = yearly[yearly["标的"] == "天通股份"].sort_values("年份")

    rp = rolling[rolling["标的"] == "组合"].copy()
    rk = rolling[rolling["标的"] == "凯盛科技"].sort_values("日期")
    rt = rolling[rolling["标的"] == "天通股份"].sort_values("日期")

    s1 = summary.get("对比策略一", {})
    cmp_note = ""
    if s1:
        d_ex = summary["组合"]["累计超额%"] - s1.get("组合", {}).get("累计超额%", 0)
        d21 = summary["组合"].get("2021超额%", 0) - 0
        cmp_note = (
            f"相对策略一：累计超额 {d_ex:+.1f} pct；"
            f"弱年2021/2023/2025 见分年柱图。"
        )

    chart_payload = {
        "meta": summary,
        "equity": {
            "months": eq_dates,
            "组合策略": eq_s,
            "组合平权": eq_h,
            "凯盛策略": eq_k,
            "天通策略": eq_t,
        },
        "monthly_excess": {
            "months": mp["月份"].astype(str).tolist(),
            "组合": mp["超额%"].astype(float).tolist(),
            "凯盛": mk.set_index("月份").reindex(mp["月份"])["超额%"].astype(float).tolist(),
            "天通": mt.set_index("月份").reindex(mp["月份"])["超额%"].astype(float).tolist(),
        },
        "yearly": {
            "years": yp["年份"].astype(int).tolist(),
            "组合超额": yp["超额%"].astype(float).tolist(),
            "凯盛超额": yk.set_index("年份").reindex(yp["年份"])["超额%"].astype(float).tolist(),
            "天通超额": yt.set_index("年份").reindex(yp["年份"])["超额%"].astype(float).tolist(),
            "凯盛闭环": yk.set_index("年份").reindex(yp["年份"])["闭环笔数"].astype(float).tolist(),
            "天通闭环": yt.set_index("年份").reindex(yp["年份"])["闭环笔数"].astype(float).tolist(),
        },
        "rolling": {
            "dates": rp["日期"].tolist(),
            "组合": rp["滚动12M超额%"].astype(float).tolist(),
            "凯盛": rk["滚动12M超额%"].astype(float).tolist(),
            "天通": rt["滚动12M超额%"].astype(float).tolist(),
        },
        "decay": decay.to_dict(orient="records"),
        "s1_yearly": {},
    }
    if s1:
        s1y = pd.read_csv(DIR / "yearly_decay.csv")
        y1 = s1y[s1y["标的"] == "组合"].sort_values("年份")
        chart_payload["s1_yearly"] = {
            "years": y1["年份"].astype(int).tolist(),
            "组合超额": y1["超额%"].astype(float).tolist(),
        }

    data_js = json.dumps(chart_payload, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>凯盛+天通 · 策略七·因子1+因子4 · 可视化</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#8b9bb4;
    --accent:#3d9cf0; --f4:#34d399; --kc:#a78bfa; --tt:#fbbf24; --good:#3ecf8e; --bad:#f07178;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"IBM Plex Sans","Noto Sans SC",system-ui,sans-serif; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:28px 20px 56px; }}
  h1 {{ font-size:1.45rem; font-weight:650; margin:0 0 6px; }}
  .sub {{ color:var(--muted); font-size:0.88rem; margin-bottom:20px; line-height:1.55; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:20px; }}
  @media (max-width:900px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} }}
  .stat {{ background:var(--card); border-radius:10px; padding:14px 16px; }}
  .stat .l {{ color:var(--muted); font-size:0.72rem; }}
  .stat .v {{ font-size:1.18rem; font-weight:700; margin-top:4px; }}
  .good {{ color:var(--good); }} .bad {{ color:var(--bad); }}
  .card {{ background:var(--card); border-radius:12px; padding:16px 18px 10px; margin-bottom:18px; }}
  .card h2 {{ font-size:0.98rem; margin:0 0 8px; font-weight:600; }}
  canvas {{ width:100% !important; max-height:340px; }}
  .note {{ color:var(--muted); font-size:0.78rem; margin:8px 0 0; line-height:1.5; }}
  .pill {{ display:inline-block; background:#243247; color:var(--accent); padding:2px 10px; border-radius:999px; font-size:0.76rem; margin-right:6px; }}
  .pill.f4 {{ color:var(--f4); }}
  .two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:900px) {{ .two {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <h1>凯盛科技 + 天通股份 · 策略七 · 因子1 + 因子4</h1>
  <p class="sub" id="subtitle"></p>
  <div class="grid" id="stats"></div>

  <div class="card">
    <h2>归一净值曲线（月末 · 名义本金 10 万）</h2>
    <canvas id="equity"></canvas>
    <p class="note">蓝=组合策略，灰虚线=组合平权持有，紫=凯盛，黄=天通。因子4：roc_ma60 牛市内止损放宽 2 倍。</p>
  </div>

  <div class="card">
    <h2>分月超额收益（% · 相对平权持有）</h2>
    <canvas id="monthly"></canvas>
  </div>

  <div class="two">
    <div class="card">
      <h2>分年超额（% · S7 vs S1 组合）</h2>
      <canvas id="yearly"></canvas>
    </div>
    <div class="card">
      <h2>闭环笔数</h2>
      <canvas id="trades"></canvas>
    </div>
  </div>

  <div class="card">
    <h2>滚动 12 个月累计超额（%）</h2>
    <canvas id="rolling"></canvas>
    <p class="note">{cmp_note}</p>
  </div>
</div>
<script>
const D = {data_js};
const meta = D.meta;
document.getElementById('subtitle').innerHTML =
  `<span class="pill">策略七 · F1+F4</span><span class="pill f4">roc_ma60 · 止损×2</span>` +
  `<span class="pill">凯盛 2.5% / 天通 3%</span>` + meta['区间'];

const p = meta['组合'];
const s1 = meta['对比策略一'] && meta['对比策略一']['组合'];
const stats = [
  ['S7 组合累计超额', '+' + p['累计超额%'].toFixed(1) + ' pct', 'good'],
  ['S1 组合累计超额', s1 ? '+' + s1['累计超额%'].toFixed(1) + ' pct' : '—', ''],
  ['超额月胜率', p['超额月胜率%'] + '%', ''],
  ['滚动12M超额', '+' + p['滚动12M最新超额%'].toFixed(1) + '%', 'good'],
  ['2021 组合超额', (p['2021超额%']>=0?'+':'') + (p.get('2021超额%')||0).toFixed(1) + '%', (p.get('2021超额%')||0)>=0?'good':'bad'],
  ['2025 组合超额', '+' + p['2025超额%'].toFixed(1) + '%', 'good'],
  ['凯盛累计超额', '+' + meta['凯盛科技']['累计超额%'].toFixed(0) + ' pct', 'good'],
  ['天通累计超额', '+' + meta['天通股份']['累计超额%'].toFixed(0) + ' pct', 'good'],
];
document.getElementById('stats').innerHTML = stats.map(([l,v,c]) =>
  `<div class="stat"><div class="l">${{l}}</div><div class="v ${{c}}">${{v}}</div></div>`).join('');

const common = {{
  responsive: true,
  interaction: {{ mode: 'index', intersect: false }},
  plugins: {{ legend: {{ labels: {{ color: '#c5d0e0' }} }} }},
  scales: {{
    x: {{ ticks: {{ color: '#8b9bb4', maxTicksLimit: 12 }}, grid: {{ color: 'rgba(255,255,255,0.04)' }} }},
    y: {{ ticks: {{ color: '#8b9bb4' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }}
  }}
}};

new Chart(document.getElementById('equity'), {{
  type: 'line',
  data: {{
    labels: D.equity.months,
    datasets: [
      {{ label: '组合策略', data: D.equity['组合策略'], borderColor: '#3d9cf0', backgroundColor: 'rgba(61,156,240,0.08)', fill: true, tension: 0.12, pointRadius: 0, borderWidth: 2 }},
      {{ label: '组合平权', data: D.equity['组合平权'], borderColor: '#8b9bb4', borderDash: [6,4], tension: 0.12, pointRadius: 0, borderWidth: 1.5 }},
      {{ label: '凯盛策略', data: D.equity['凯盛策略'], borderColor: '#a78bfa', tension: 0.12, pointRadius: 0, borderWidth: 1.2 }},
      {{ label: '天通策略', data: D.equity['天通策略'], borderColor: '#fbbf24', tension: 0.12, pointRadius: 0, borderWidth: 1.2 }},
    ]
  }},
  options: {{ ...common, scales: {{ ...common.scales, y: {{ ...common.scales.y, title: {{ display: true, text: '权益 (元)', color: '#8b9bb4' }} }} }} }}
}});

function barColors(vals) {{
  return vals.map(v => v >= 0 ? 'rgba(62,207,142,0.75)' : 'rgba(240,113,120,0.75)');
}}

new Chart(document.getElementById('monthly'), {{
  type: 'bar',
  data: {{
    labels: D.monthly_excess.months,
    datasets: [{{ label: '组合超额%', data: D.monthly_excess['组合'], backgroundColor: barColors(D.monthly_excess['组合']), borderWidth: 0 }}]
  }},
  options: {{
    ...common,
    plugins: {{ ...common.plugins, legend: {{ display: false }} }},
    scales: {{
      ...common.scales,
      x: {{ ...common.scales.x, ticks: {{ ...common.scales.x.ticks, maxTicksLimit: 18 }} }},
      y: {{ ...common.scales.y, title: {{ display: true, text: '超额 (%)', color: '#8b9bb4' }} }}
    }}
  }}
}});

const yearlyDs = [
  {{ label: 'S7 组合', data: D.yearly['组合超额'], backgroundColor: 'rgba(61,156,240,0.85)' }},
  {{ label: '凯盛', data: D.yearly['凯盛超额'], backgroundColor: 'rgba(167,139,250,0.75)' }},
  {{ label: '天通', data: D.yearly['天通超额'], backgroundColor: 'rgba(251,191,36,0.75)' }},
];
if (D.s1_yearly.years && D.s1_yearly.years.length) {{
  yearlyDs.push({{ label: 'S1 组合', data: D.s1_yearly['组合超额'], backgroundColor: 'rgba(139,155,180,0.45)' }});
}}
new Chart(document.getElementById('yearly'), {{
  type: 'bar',
  data: {{ labels: D.yearly.years, datasets: yearlyDs }},
  options: {{ ...common, scales: {{ ...common.scales, y: {{ ...common.scales.y, title: {{ display: true, text: '年超额 (%)', color: '#8b9bb4' }} }} }} }}
}});

new Chart(document.getElementById('trades'), {{
  type: 'bar',
  data: {{
    labels: D.yearly.years,
    datasets: [
      {{ label: '凯盛闭环', data: D.yearly['凯盛闭环'], backgroundColor: 'rgba(167,139,250,0.75)' }},
      {{ label: '天通闭环', data: D.yearly['天通闭环'], backgroundColor: 'rgba(251,191,36,0.75)' }},
    ]
  }},
  options: {{ ...common, scales: {{ ...common.scales, y: {{ ...common.scales.y, title: {{ display: true, text: '笔数', color: '#8b9bb4' }} }} }} }}
}});

new Chart(document.getElementById('rolling'), {{
  type: 'line',
  data: {{
    labels: D.rolling.dates,
    datasets: [
      {{ label: '组合', data: D.rolling['组合'], borderColor: '#3d9cf0', tension: 0.15, pointRadius: 0, borderWidth: 1.8 }},
      {{ label: '凯盛', data: D.rolling['凯盛'], borderColor: '#a78bfa', tension: 0.15, pointRadius: 0, borderWidth: 1.2 }},
      {{ label: '天通', data: D.rolling['天通'], borderColor: '#fbbf24', tension: 0.15, pointRadius: 0, borderWidth: 1.2 }},
    ]
  }},
  options: {{
    ...common,
    scales: {{
      ...common.scales,
      x: {{ ...common.scales.x, ticks: {{ ...common.scales.x.ticks, maxTicksLimit: 10 }} }},
      y: {{ ...common.scales.y, title: {{ display: true, text: '滚动12M超额 (%)', color: '#8b9bb4' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML}")


def main() -> None:
    payload = build_data()
    build_html(payload)
    s = payload["summary"]["组合"]
    print(f"S7 组合累计超额: {s['累计超额%']}%")
    if "对比策略一" in payload["summary"]:
        s1 = payload["summary"]["对比策略一"]["组合"]["累计超额%"]
        print(f"S1 组合累计超额: {s1}%  (Δ {s['累计超额%'] - s1:+.1f})")


if __name__ == "__main__":
    main()
