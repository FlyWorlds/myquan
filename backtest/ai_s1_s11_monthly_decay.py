"""AI应用主板池 · 策略1 各指标月度衰减曲线。

口径：
  · 阈值：沿用 all_metrics.csv 定参段（FIT）冻结 thr
  · 指标：胜率 / 盈亏比 / 超额% / 最大回撤%（策略1权益）
  · 序列：自然月截面中位数（全池）+ Top5 等权组合 + Top5 单票
  · 衰减：月末滚动12M选股 Top20 → 前瞻 1–12 个月累计超额均值

输出：backtest/ai_s1_s11_periods/monthly_decay/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")

from backtest.ai_s1_s11_periods import (  # noqa: E402
    FULL_START,
    MIN_BARS,
    _metrics_from_equity,
    _trade_stats,
    load_daily,
)
from backtest.factor1_monthly_top3 import _month_ends  # noqa: E402

OUT_DIR = _MYQUAN / "backtest" / "ai_s1_s11_periods" / "monthly_decay"
METRICS_CSV = _MYQUAN / "backtest" / "ai_s1_s11_periods" / "all_metrics.csv"
TOP5_CSV = _MYQUAN / "backtest" / "ai_s1_s11_periods" / "top5_score_blend.csv"
UNIVERSE = _MYQUAN / "backtest" / "ai_s1_s11_periods" / "universe_mainboard.csv"

W_EXCESS, W_SHARPE, W_DD = 5.0, 3.0, 2.0
TOP_N_FWD = 20
MIN_TRADES_MONTH = 2
ROLL_SCORE_MONTHS = 12


def _today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def simulate_with_trade_dates(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    dates: pd.DatetimeIndex,
    *,
    thr: float,
) -> tuple[np.ndarray, list[tuple[pd.Timestamp, float]]]:
    """返回权益序列与 (平仓日, 收益率) 列表。"""
    # 复用逻辑：本地轻量改写以记录平仓日
    import math

    from strategy.costs import ENGINE_COMMISSION_RATE as COMMISSION  # noqa: WPS433
    from strategy.costs import SLIPPAGE_VALUE as SLIP  # noqa: WPS433
    from strategy.costs import STAMP_TAX_RATE as STAMP  # noqa: WPS433
    from strategy.open_break import (  # noqa: WPS433
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

    n = len(o)
    equity = np.empty(n, dtype=np.float64)
    cash = 100_000.0
    shares = 0.0
    entry_px = 0.0
    buy_i = -1
    tick = TICK_SIZE
    target_pct = 0.95
    lot = 100
    trade_events: list[tuple[pd.Timestamp, float]] = []

    for i in range(n):
        oi, hi, li, ci = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        if oi <= 0 or ci <= 0:
            equity[i] = cash + shares * (ci if ci > 0 else 0.0)
            continue
        buy_px = entry_trigger_price(oi, entry_pct=thr, tick=tick)
        stop_px = stop_trigger_price(oi, stop_pct=thr, tick=tick)

        if shares > 0:
            if i > buy_i and li <= stop_px + 1e-12:
                prev_c = float(c[i - 1]) if i > 0 else ci
                lim = limit_down_state(
                    prev_close=prev_c,
                    open_px=oi,
                    high_px=hi,
                    low_px=li,
                    close_px=ci,
                    limit_down_pct=0.10,
                    tick=tick,
                )
                if not bool(lim["locked"]):
                    sell_px = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                    sell_px *= 1.0 - SLIP
                    proceeds = shares * sell_px
                    fee = proceeds * COMMISSION + proceeds * STAMP
                    cash += proceeds - fee
                    if entry_px > 0:
                        trade_events.append((pd.Timestamp(dates[i]).normalize(), sell_px / entry_px - 1.0))
                    shares = 0.0
                    entry_px = 0.0
                    buy_i = -1
        else:
            if i >= 1:
                po, pc = float(o[i - 1]), float(c[i - 1])
                allows = prev_day_allows_entry(
                    po, pc, prev_small_yang_pct=thr, prev_entry_mode="yin_or_small_yang"
                )
                blocked = False
                if i >= 2:
                    blocked = should_block_entry_by_yang(
                        float(o[i - 2]),
                        float(c[i - 2]),
                        po,
                        pc,
                        tick=tick,
                        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                    )
                if allows and (not blocked) and (hi + 1e-12 >= buy_px):
                    px = buy_px * (1.0 + SLIP)
                    budget = cash * target_pct
                    raw = math.floor(budget / (px * lot)) * lot
                    if raw >= lot:
                        cost = raw * px
                        fee = cost * COMMISSION
                        if cost + fee <= cash:
                            cash -= cost + fee
                            shares = float(raw)
                            entry_px = px
                            buy_i = i
        equity[i] = cash + shares * ci

    return equity, trade_events


def month_metrics_one(
    daily: pd.DataFrame,
    thr: float,
    month_end: pd.Timestamp,
) -> dict[str, float]:
    period = month_end.to_period("M")
    m_start = pd.Timestamp(period.start_time).normalize()
    m_end = month_end.normalize()
    sub = daily[(daily["date"] >= m_start) & (daily["date"] <= m_end)].reset_index(drop=True)
    if len(sub) < 5:
        return {
            "excess": np.nan,
            "win_rate": np.nan,
            "pl_ratio": np.nan,
            "mdd": np.nan,
            "ret": np.nan,
            "n_trades": 0,
            "ok": 0,
        }
    dates = pd.DatetimeIndex(sub["date"])
    o = sub["open"].to_numpy(float)
    h = sub["high"].to_numpy(float)
    l = sub["low"].to_numpy(float)
    c = sub["close"].to_numpy(float)
    eq, trades = simulate_with_trade_dates(o, h, l, c, dates, thr=thr)
    m = _metrics_from_equity(eq, c)
    month_trades = [r for d, r in trades if m_start <= d <= m_end]
    ts = _trade_stats(month_trades)
    return {
        "excess": m["excess_return_pct"],
        "win_rate": ts["win_rate"],
        "pl_ratio": ts["pl_ratio"],
        "mdd": m["max_drawdown_pct"],
        "ret": m["total_return_pct"],
        "n_trades": int(ts["n_trades"]),
        "ok": 1 if int(ts["n_trades"]) >= MIN_TRADES_MONTH else 0,
    }


def build_stock_monthly(row: dict, oos_end: str) -> pd.DataFrame:
    symbol = str(row["symbol"])
    code = str(row["code"]).zfill(6)
    name = str(row["name"])
    thr = float(row["thr"])
    daily = load_daily(symbol)
    if daily is None:
        return pd.DataFrame()
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.tz_localize(None).dt.normalize()
    daily = daily[(daily["date"] >= pd.Timestamp(FULL_START)) & (daily["date"] <= pd.Timestamp(oos_end))]
    if len(daily) < MIN_BARS:
        return pd.DataFrame()
    ends = _month_ends(pd.DatetimeIndex(daily["date"]))
    rows = []
    for me in ends:
        if me < pd.Timestamp(FULL_START):
            continue
        met = month_metrics_one(daily, thr, me)
        rows.append(
            {
                "month": str(me.to_period("M")),
                "month_end": str(me.date()),
                "code": code,
                "name": name,
                "symbol": symbol,
                "thr": thr,
                **met,
            }
        )
    return pd.DataFrame(rows)


def pool_median_monthly(stock_monthly: pd.DataFrame) -> pd.DataFrame:
    ok = stock_monthly[stock_monthly["ok"] == 1].copy()
    agg = (
        ok.groupby("month", as_index=False)
        .agg(
            n_ok=("code", "count"),
            excess_median=("excess", "median"),
            win_rate_median=("win_rate", "median"),
            pl_ratio_median=("pl_ratio", "median"),
            mdd_median=("mdd", "median"),
            ret_median=("ret", "median"),
        )
        .sort_values("month")
    )
    return agg


def top5_equal_monthly(stock_monthly: pd.DataFrame, top5: pd.DataFrame) -> pd.DataFrame:
    codes = set(top5["code"].astype(str).str.zfill(6))
    sub = stock_monthly[stock_monthly["code"].isin(codes)].copy()
    agg = (
        sub.groupby("month", as_index=False)
        .agg(
            excess_mean=("excess", "mean"),
            win_rate_mean=("win_rate", "mean"),
            pl_ratio_mean=("pl_ratio", "mean"),
            mdd_mean=("mdd", "mean"),
            ret_mean=("ret", "mean"),
            n_stocks=("code", "nunique"),
        )
        .sort_values("month")
    )
    return agg


def rolling12m_excess(eq_monthly_ret: pd.Series) -> pd.Series:
    """由月度策略收益% 序列算滚动12M累计超额（相对0，即策略月收益之和近似）。"""
    return eq_monthly_ret.rolling(12, min_periods=6).sum()


def forward_decay(stock_monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """滚动12M末截面评分选 Top20，统计前瞻 1–12 月累计超额衰减。"""
    months = sorted(stock_monthly["month"].unique())
    if len(months) < ROLL_SCORE_MONTHS + 2:
        return pd.DataFrame(), pd.DataFrame()

    pivot_ex = stock_monthly.pivot_table(index="month", columns="code", values="excess", aggfunc="first")
    pivot_wr = stock_monthly.pivot_table(index="month", columns="code", values="win_rate", aggfunc="first")
    pivot_pl = stock_monthly.pivot_table(index="month", columns="code", values="pl_ratio", aggfunc="first")
    pivot_mdd = stock_monthly.pivot_table(index="month", columns="code", values="mdd", aggfunc="first")

    lag_rows = []
    curve_rows = []

    for i in range(ROLL_SCORE_MONTHS - 1, len(months) - 1):
        score_m = months[i]
        win_ms = months[i - ROLL_SCORE_MONTHS + 1 : i + 1]
        fwd_ms = months[i + 1 :]

        codes = pivot_ex.columns
        scores = []
        for code in codes:
            ex_s = pivot_ex.loc[win_ms, code].dropna()
            if len(ex_s) < 6:
                continue
            ex_mean = float(ex_s.mean())
            wr_mean = float(pivot_wr.loc[win_ms, code].dropna().mean()) if code in pivot_wr else np.nan
            pl_mean = float(pivot_pl.loc[win_ms, code].dropna().mean()) if code in pivot_pl else np.nan
            mdd_mean = float(pivot_mdd.loc[win_ms, code].dropna().mean()) if code in pivot_mdd else np.nan
            scores.append(
                {
                    "code": code,
                    "select_excess": ex_mean,
                    "select_win_rate": wr_mean,
                    "select_pl_ratio": pl_mean,
                    "select_mdd": mdd_mean,
                }
            )
        if len(scores) < TOP_N_FWD:
            continue
        sdf = pd.DataFrame(scores)
        for col in ("select_excess", "select_win_rate", "select_pl_ratio"):
            v = sdf[col].astype(float)
            sdf[f"r_{col}"] = (v - v.min()) / (v.max() - v.min()) if v.max() > v.min() else 0.5
        mdd_v = sdf["select_mdd"].astype(float)
        sdf["r_mdd"] = 1.0 - (mdd_v - mdd_v.min()) / (mdd_v.max() - mdd_v.min()) if mdd_v.max() > mdd_v.min() else 0.5
        sdf["score"] = (
            W_EXCESS * sdf["r_select_excess"]
            + W_SHARPE * sdf["r_select_pl_ratio"]
            + W_DD * sdf["r_mdd"]
        )
        top = sdf.nlargest(TOP_N_FWD, "score")
        top_codes = top["code"].tolist()
        sel_ex = float(top["select_excess"].mean())

        for lag in range(1, min(13, len(fwd_ms) + 1)):
            fwd_slice = fwd_ms[:lag]
            fwd_vals = []
            for code in top_codes:
                if code not in pivot_ex.columns:
                    continue
                vals = pivot_ex.loc[fwd_slice, code].dropna()
                if len(vals):
                    fwd_vals.append(float(vals.sum()))
            if not fwd_vals:
                continue
            fwd_mean = float(np.mean(fwd_vals))
            lag_rows.append(
                {
                    "score_month": score_m,
                    "lag_months": lag,
                    "select_excess_mean": sel_ex,
                    "fwd_cum_excess_mean": fwd_mean,
                    "decay": fwd_mean - sel_ex,
                    "n_top": len(top_codes),
                }
            )

    lag_df = pd.DataFrame(lag_rows)
    if lag_df.empty:
        return lag_df, pd.DataFrame()

    curve = (
        lag_df.groupby("lag_months", as_index=False)
        .agg(
            select_excess_mean=("select_excess_mean", "mean"),
            fwd_cum_excess_mean=("fwd_cum_excess_mean", "mean"),
            decay_mean=("decay", "mean"),
            n_samples=("score_month", "count"),
        )
        .sort_values("lag_months")
    )
    return lag_df, curve


def build_html(
    pool: pd.DataFrame,
    top5_eq: pd.DataFrame,
    top5_stocks: pd.DataFrame,
    stock_monthly: pd.DataFrame,
    fwd_curve: pd.DataFrame,
    meta: dict,
) -> str:
    months = pool["month"].tolist()
    top5_codes = meta.get("top5_codes", [])

    per_stock = {}
    for code in top5_codes:
        sub = stock_monthly[stock_monthly["code"] == code].sort_values("month")
        if len(sub):
            name = str(sub["name"].iloc[0])
            per_stock[f"{code} {name}"] = {
                "excess": sub["excess"].astype(float).tolist(),
                "win_rate": sub["win_rate"].astype(float).tolist(),
                "pl_ratio": sub["pl_ratio"].astype(float).tolist(),
                "mdd": sub["mdd"].astype(float).tolist(),
            }

    payload = {
        "meta": meta,
        "months": months,
        "pool": {
            "excess": pool["excess_median"].astype(float).tolist(),
            "win_rate": pool["win_rate_median"].astype(float).tolist(),
            "pl_ratio": pool["pl_ratio_median"].astype(float).tolist(),
            "mdd": pool["mdd_median"].astype(float).tolist(),
        },
        "top5_equal": {
            "excess": top5_eq["excess_mean"].astype(float).tolist(),
            "win_rate": top5_eq["win_rate_mean"].astype(float).tolist(),
            "pl_ratio": top5_eq["pl_ratio_mean"].astype(float).tolist(),
            "mdd": top5_eq["mdd_mean"].astype(float).tolist(),
        },
        "top5_stocks": per_stock,
        "fwd_decay": {
            "lags": fwd_curve["lag_months"].astype(int).tolist() if len(fwd_curve) else [],
            "select": fwd_curve["select_excess_mean"].astype(float).tolist() if len(fwd_curve) else [],
            "fwd": fwd_curve["fwd_cum_excess_mean"].astype(float).tolist() if len(fwd_curve) else [],
            "decay": fwd_curve["decay_mean"].astype(float).tolist() if len(fwd_curve) else [],
        },
    }
    data_js = json.dumps(payload, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AI应用主板 · 策略1 月衰减曲线</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#8b9bb4; --accent:#3d9cf0; --good:#3ecf8e; --bad:#f07178; }}
  body {{ margin:0; font-family:"IBM Plex Sans","Noto Sans SC",system-ui,sans-serif; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:28px 20px 56px; }}
  h1 {{ font-size:1.4rem; margin:0 0 6px; }}
  .sub {{ color:var(--muted); font-size:0.88rem; margin-bottom:20px; line-height:1.55; }}
  .card {{ background:var(--card); border-radius:12px; padding:16px 18px 10px; margin-bottom:18px; }}
  .card h2 {{ font-size:0.96rem; margin:0 0 8px; }}
  canvas {{ width:100% !important; max-height:320px; }}
  .note {{ color:var(--muted); font-size:0.78rem; margin:8px 0 0; line-height:1.5; }}
  .pill {{ display:inline-block; background:#243247; color:var(--accent); padding:2px 10px; border-radius:999px; font-size:0.76rem; margin-right:6px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>AI应用主板 · 策略1 各指标月衰减曲线</h1>
  <p class="sub" id="subtitle"></p>

  <div class="card"><h2>全池月度超额%（中位数）</h2><canvas id="c_excess"></canvas>
    <p class="note">灰线=Top5等权均值；彩色虚线=稳健分Top5单票。</p></div>
  <div class="card"><h2>全池月度胜率%（中位数）</h2><canvas id="c_wr"></canvas></div>
  <div class="card"><h2>全池月度盈亏比（中位数）</h2><canvas id="c_pl"></canvas></div>
  <div class="card"><h2>全池月度最大回撤%（中位数）</h2><canvas id="c_mdd"></canvas></div>
  <div class="card"><h2>滚动12M选股 Top20 · 前瞻累计超额衰减</h2><canvas id="c_decay"></canvas>
    <p class="note">选股窗=过去12自然月均值超额；前瞻=Top20 在随后 1–12 个月的累计超额均值；decay=前瞻−选股。</p></div>
</div>
<script>
const D = {data_js};
document.getElementById('subtitle').innerHTML =
  `<span class="pill">主板98只</span><span class="pill">冻结FIT阈值</span>` +
  D.meta.interval + ` · 有效样本 ` + D.meta.n_stocks;

const colors = ['#a78bfa','#fbbf24','#3ecf8e','#f07178','#3d9cf0'];
const common = {{
  responsive:true,
  interaction:{{mode:'index',intersect:false}},
  plugins:{{legend:{{labels:{{color:'#c5d0e0'}}}}}},
  scales:{{
    x:{{ticks:{{color:'#8b9bb4',maxTicksLimit:14}},grid:{{color:'rgba(255,255,255,0.04)'}}}},
    y:{{ticks:{{color:'#8b9bb4'}},grid:{{color:'rgba(255,255,255,0.06)'}}}}
  }}
}};

function lineChart(id, label, poolKey, yLabel) {{
  const ds = [
    {{label:'全池中位', data:D.pool[poolKey], borderColor:'#3d9cf0', backgroundColor:'rgba(61,156,240,0.1)', tension:0.2, fill:false}},
    {{label:'Top5等权', data:D.top5_equal[poolKey], borderColor:'#8b9bb4', borderDash:[6,4], tension:0.2, fill:false}},
  ];
  let ci = 0;
  for (const [name, obj] of Object.entries(D.top5_stocks)) {{
    ds.push({{label:name, data:obj[poolKey], borderColor:colors[ci%colors.length], borderDash:[3,3], tension:0.2, fill:false, pointRadius:0}});
    ci++;
  }}
  new Chart(document.getElementById(id), {{type:'line', data:{{labels:D.months, datasets:ds}}, options:{{...common, plugins:{{...common.plugins, title:{{display:false}}}}, scales:{{...common.scales, y:{{...common.scales.y, title:{{display:true,text:yLabel,color:'#8b9bb4'}}}}}}}}}});
}}

lineChart('c_excess','超额','excess','超额 %');
lineChart('c_wr','胜率','win_rate','胜率 %');
lineChart('c_pl','盈亏比','pl_ratio','盈亏比');
lineChart('c_mdd','回撤','mdd','回撤 %');

new Chart(document.getElementById('c_decay'), {{
  type:'line',
  data:{{
    labels: D.fwd_decay.lags.map(x=>'+'+x+'M'),
    datasets:[
      {{label:'选股期超额(12M均)', data:D.fwd_decay.select, borderColor:'#3d9cf0', tension:0.2}},
      {{label:'前瞻累计超额', data:D.fwd_decay.fwd, borderColor:'#3ecf8e', tension:0.2}},
      {{label:'衰减(decay)', data:D.fwd_decay.decay, borderColor:'#f07178', borderDash:[5,5], tension:0.2}},
    ]
  }},
  options: common
}});
</script>
</body>
</html>"""


def build_md(
    pool: pd.DataFrame,
    top5_eq: pd.DataFrame,
    fwd_curve: pd.DataFrame,
    top5: pd.DataFrame,
    meta: dict,
) -> str:
    lines = [
        "# AI应用主板 · 策略1 各指标月衰减曲线",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 区间：{meta['interval']}",
        f"- 股票池：主板 {meta['n_stocks']} 只；阈值沿用 FIT 冻结",
        "",
        "## 1. 月度序列说明",
        "",
        "- **全池中位**：每月截面中位数（当月闭环≥2笔的票才计入）",
        "- **Top5等权**：稳健分 Top5 当月指标算术均值",
        "- 指标：超额%、胜率%、盈亏比、最大回撤%",
        "",
        "## 2. 近期全池月度中位（最近6个月）",
        "",
        "| 月份 | 超额% | 胜率% | 盈亏比 | 回撤% | 有效票 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    tail = pool.tail(6)
    for _, r in tail.iterrows():
        lines.append(
            f"| {r['month']} | {r['excess_median']:.2f} | {r['win_rate_median']:.2f} | "
            f"{r['pl_ratio_median']:.2f} | {r['mdd_median']:.2f} | {int(r['n_ok'])} |"
        )

    lines += [
        "",
        "## 3. Top5 等权月度（最近6个月）",
        "",
        "| 月份 | 超额% | 胜率% | 盈亏比 | 回撤% |",
        "|---|---:|---:|---:|---:|",
    ]
    tail5 = top5_eq.tail(6)
    for _, r in tail5.iterrows():
        lines.append(
            f"| {r['month']} | {r['excess_mean']:.2f} | {r['win_rate_mean']:.2f} | "
            f"{r['pl_ratio_mean']:.2f} | {r['mdd_mean']:.2f} |"
        )

    lines += ["", "## 4. 前瞻超额衰减曲线（滚动12M选Top20）", ""]
    if len(fwd_curve):
        lines.append("| 前瞻月数 | 选股期超额% | 前瞻累计超额% | 衰减 | 样本月数 |")
        lines.append("|---:|---:|---:|---:|---:|")
        for _, r in fwd_curve.iterrows():
            lines.append(
                f"| +{int(r['lag_months'])}M | {r['select_excess_mean']:.2f} | "
                f"{r['fwd_cum_excess_mean']:.2f} | {r['decay_mean']:.2f} | {int(r['n_samples'])} |"
            )
    else:
        lines.append("（样本不足，未生成）")

    lines += [
        "",
        "## 5. Top5 名单",
        "",
        "| 代码 | 名称 | thr% |",
        "|---|---|---:|",
    ]
    for _, r in top5.iterrows():
        lines.append(f"| {str(r['code']).zfill(6)} | {r['name']} | {float(r['thr'])*100:.1f} |")

    lines += [
        "",
        "交互图表见 `report_monthly_decay.html`。",
        "",
        "本报告仅供研究参考，不构成任何投资建议。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    oos_end = _today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    metrics = pd.read_csv(METRICS_CSV, dtype={"code": str})
    metrics["code"] = metrics["code"].str.zfill(6)
    ok = metrics[metrics["ok"] == 1][["code", "name", "symbol", "thr"]].copy()
    top5 = pd.read_csv(TOP5_CSV, dtype={"code": str})
    top5["code"] = top5["code"].str.zfill(6)

    print(f"主板有效 {len(ok)} 只 | 月度 {FULL_START} → {oos_end}")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    parts = []
    t0 = time.time()
    tasks = ok.to_dict(orient="records")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(build_stock_monthly, t, oos_end): t for t in tasks}
        for i, fut in enumerate(as_completed(futs), 1):
            df = fut.result()
            if len(df):
                parts.append(df)
            if i % 20 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)} {time.time()-t0:.0f}s rows={sum(len(p) for p in parts)}")

    stock_monthly = pd.concat(parts, ignore_index=True)
    stock_monthly.to_csv(OUT_DIR / "stock_monthly.csv", index=False, encoding="utf-8-sig")

    pool = pool_median_monthly(stock_monthly)
    pool.to_csv(OUT_DIR / "pool_monthly_median.csv", index=False, encoding="utf-8-sig")

    top5_eq = top5_equal_monthly(stock_monthly, top5)
    top5_eq.to_csv(OUT_DIR / "top5_equal_monthly.csv", index=False, encoding="utf-8-sig")

    top5_long = stock_monthly[stock_monthly["code"].isin(top5["code"])].copy()
    top5_long.to_csv(OUT_DIR / "top5_stocks_monthly.csv", index=False, encoding="utf-8-sig")

    lag_df, fwd_curve = forward_decay(stock_monthly)
    if len(lag_df):
        lag_df.to_csv(OUT_DIR / "forward_decay_lags.csv", index=False, encoding="utf-8-sig")
    if len(fwd_curve):
        fwd_curve.to_csv(OUT_DIR / "forward_decay_curve.csv", index=False, encoding="utf-8-sig")

    meta = {
        "interval": f"{FULL_START} → {oos_end}",
        "n_stocks": int(len(ok)),
        "top5_codes": top5["code"].tolist(),
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    md = build_md(pool, top5_eq, fwd_curve, top5, meta)
    (OUT_DIR / "report_monthly_decay.md").write_text(md, encoding="utf-8")

    html = build_html(pool, top5_eq, top5, stock_monthly, fwd_curve, meta)
    (OUT_DIR / "report_monthly_decay.html").write_text(html, encoding="utf-8")

    print(f"\n完成 → {OUT_DIR}")
    if len(pool):
        last = pool.iloc[-1]
        print(
            f"最近月 {last['month']}: 超额中位 {last['excess_median']:.2f}% "
            f"胜率 {last['win_rate_median']:.2f}% 盈亏比 {last['pl_ratio_median']:.2f}"
        )


if __name__ == "__main__":
    main()
