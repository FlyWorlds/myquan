"""农产品期货季节性分析核心计算。

框架中立：输入一张主力连续日线长表 [date, close]，输出季节性统计。
不预测、不喊单——只把"历年同期的统计规律"算清楚并披露样本量与显著性。

季节性统计口径：
- 月度收益 = 该月最后交易日收盘 / 上月最后交易日收盘 - 1（跨年用 12 月→次年 1 月衔接）
- 各月：历年平均涨跌、标准差、上涨概率、样本年数
- 显著性：对"上涨概率≠50%"做二项精确检验；对"平均涨跌≠0"做单样本 t 检验
  （t 分布真实 p，非正态近似——小样本下正态会高估显著性）
  —— 样本年数少（如 10 年只有 10 个样本）时，务必看 p 值，别把噪声当规律

用法：
    python seasonality.py --csv soybean_meal.csv               # 列: date, close
    python seasonality.py --csv x.csv --symbol "M 豆粕" --out report/
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd

MIN_YEARS_WARN = 8   # 样本年数低于此值，报告须显著提示"样本太少"


# 自包含 HTML 报告模板：内联 SVG + CSS + JS，零外部依赖、离线可用、明暗主题自适应。
# 占位符由 render_html() 用 str.replace 填充（不用 f-string/format，避免与 CSS/JS 的 {} 冲突）。
_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --ground:#f6f3ec; --surface:#fffdf8; --surface-2:#f0ebe0;
    --ink:#23201a; --ink-2:#6b655a; --ink-3:#9a9284;
    --hair:rgba(35,32,26,.12); --hair-strong:rgba(35,32,26,.26);
    --up:#c0392b; --down:#147d6f; --accent:#a9791f;
    --accent-soft:rgba(169,121,31,.12); --faded:0.30;
    --shadow:0 1px 2px rgba(35,32,26,.06),0 6px 20px rgba(35,32,26,.05);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ground:#17150f; --surface:#201d16; --surface-2:#2a261d;
      --ink:#ece7db; --ink-2:#a9a293; --ink-3:#746d5e;
      --hair:rgba(236,231,219,.12); --hair-strong:rgba(236,231,219,.24);
      --up:#e15b4c; --down:#2aa697; --accent:#d6a94a;
      --accent-soft:rgba(214,169,74,.14);
      --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 22px rgba(0,0,0,.35);
    }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--ground); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",
      "Segoe UI","Noto Sans CJK SC",system-ui,sans-serif;
    line-height:1.6; font-variant-numeric:tabular-nums; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:880px; margin:0 auto; padding:40px 24px 64px; }
  .eyebrow { font-size:12px; letter-spacing:.18em; text-transform:uppercase;
    color:var(--accent); font-weight:600; margin:0 0 8px; }
  h1 { font-size:clamp(24px,4vw,32px); font-weight:700; margin:0 0 6px;
    letter-spacing:-.01em; text-wrap:balance; }
  .meta { color:var(--ink-2); font-size:14px; margin:0; }
  .meta b { color:var(--ink); font-weight:600; }
  .warn { margin:16px 0 0; padding:10px 14px; border-radius:10px; font-size:13px;
    background:rgba(192,57,43,.10); border:1px solid rgba(192,57,43,.30); color:var(--up); }
  .callout { margin:24px 0 32px; padding:18px 20px; border-radius:12px;
    background:var(--accent-soft); border:1px solid var(--hair);
    display:flex; flex-wrap:wrap; gap:6px 28px; align-items:baseline; }
  .callout .lead { font-weight:600; font-size:14px; color:var(--accent);
    letter-spacing:.02em; width:100%; margin-bottom:2px; }
  .callout .stat { font-size:14px; color:var(--ink-2); }
  .callout .stat b { color:var(--ink); font-weight:700; font-size:16px; }
  .tag { display:inline-block; font-size:12px; padding:1px 9px; border-radius:999px;
    border:1px solid var(--hair-strong); color:var(--ink-2); font-weight:600; }
  section { margin-top:40px; }
  .sec-head { display:flex; align-items:baseline; justify-content:space-between;
    gap:12px; margin-bottom:6px; flex-wrap:wrap; }
  h2 { font-size:17px; font-weight:700; margin:0; letter-spacing:-.005em; }
  .sec-note { font-size:13px; color:var(--ink-3); margin:0; }
  .card { background:var(--surface); border:1px solid var(--hair); border-radius:14px;
    box-shadow:var(--shadow); padding:20px 20px 12px; margin-top:14px; }
  .chart-scroll { overflow-x:auto; }
  svg { display:block; width:100%; min-width:560px; height:auto; }
  .legend { display:flex; flex-wrap:wrap; gap:8px 20px; margin-top:12px;
    padding-top:12px; border-top:1px solid var(--hair); font-size:12.5px; color:var(--ink-2); }
  .legend .item { display:inline-flex; align-items:center; gap:7px; }
  .sw { width:13px; height:13px; border-radius:3px; display:inline-block; }
  .sw.up { background:var(--up); } .sw.down { background:var(--down); }
  .sw.faded { opacity:var(--faded); }
  #tip { position:fixed; pointer-events:none; z-index:20; opacity:0; transition:opacity .1s;
    background:var(--surface); color:var(--ink); border:1px solid var(--hair-strong);
    border-radius:10px; box-shadow:var(--shadow); padding:10px 12px; font-size:12.5px;
    max-width:240px; line-height:1.5; }
  #tip .t-m { font-weight:700; margin-bottom:4px; font-size:13px; }
  #tip .row { display:flex; justify-content:space-between; gap:16px; color:var(--ink-2); }
  #tip .row b { color:var(--ink); font-weight:600; }
  #tip .t-sig { margin-top:5px; font-weight:600; }
  .tbl-scroll { overflow-x:auto; margin-top:14px; }
  table { border-collapse:collapse; width:100%; min-width:600px; font-size:13px; }
  th,td { padding:8px 10px; text-align:right; white-space:nowrap; }
  th { color:var(--ink-3); font-weight:600; font-size:12px; letter-spacing:.03em;
    border-bottom:1px solid var(--hair-strong); }
  td { border-bottom:1px solid var(--hair); color:var(--ink-2); }
  th:first-child,td:first-child { text-align:left; }
  tr.sig td { color:var(--ink); font-weight:600; }
  tr.sig td:first-child::after { content:"★"; color:var(--accent); margin-left:6px; font-size:11px; }
  td.up { color:var(--up); } td.down { color:var(--down); }
  tr.dim td:not(.pos) { opacity:.78; }
  .caveats { margin-top:16px; padding:18px 20px; border-radius:12px;
    background:var(--surface-2); border:1px solid var(--hair); }
  .caveats h3 { margin:0 0 10px; font-size:13px; letter-spacing:.04em; text-transform:uppercase;
    color:var(--ink-3); font-weight:700; }
  .caveats ul { margin:0; padding-left:18px; }
  .caveats li { font-size:13px; color:var(--ink-2); margin-bottom:6px; }
  .caveats li:last-child { margin-bottom:0; }
  footer { margin-top:40px; padding-top:16px; border-top:1px solid var(--hair);
    font-size:12px; color:var(--ink-3); display:flex; justify-content:space-between;
    flex-wrap:wrap; gap:8px; }
  @media (max-width:560px) { .wrap { padding:28px 16px 48px; } .callout { gap:4px 18px; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="eyebrow">农产品期货季节性分析</p>
    <h1>__SYMBOL__ · 月度季节性规律</h1>
    <p class="meta">__META__</p>
    __WARN__
  </header>
  __CALLOUT__
  <section>
    <div class="sec-head">
      <h2>逐月平均涨跌</h2>
      <p class="sec-note">实心 = 统计显著（p&lt;0.1）· 半透明 = 不显著，勿过度解读</p>
    </div>
    <div class="card">
      <div class="chart-scroll">
        <svg id="chart" viewBox="0 0 720 380" role="img" aria-label="逐月平均涨跌柱状图"></svg>
      </div>
      <div class="legend">
        <span class="item"><span class="sw up"></span>上涨（红）</span>
        <span class="item"><span class="sw down"></span>下跌（绿）</span>
        <span class="item"><span class="sw up faded"></span>不显著（半透明）</span>
        <span class="item">★ 通过显著性检验</span>
      </div>
    </div>
  </section>
  <section>
    <div class="sec-head">
      <h2>完整数据</h2>
      <p class="sec-note">平均/中位涨跌 · 上涨概率 · 样本年数 · 检验 p 值</p>
    </div>
    <div class="tbl-scroll">
      <table id="tbl">
        <thead><tr>
          <th>月份</th><th>平均涨跌</th><th>中位涨跌</th><th>上涨概率</th>
          <th>样本年</th><th>p(概率)</th><th>p(均值)</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>
  <div class="caveats">
    <h3>严谨性说明</h3>
    <ul>__CAVEATS__</ul>
  </div>
  <footer>
    <span>由 skill-ag-futures-seasonality 生成</span>
    <span>事实优先 · 不输出买卖指令</span>
  </footer>
</div>
<div id="tip" aria-hidden="true"></div>
<script>
  const DATA = __DATA_JSON__;
  const sig = d => (d.pw < 0.1) || (d.pm < 0.1);
  const pct = (x, dp=2) => (x >= 0 ? "+" : "") + (x*100).toFixed(dp) + "%";
  const SVGNS = "http://www.w3.org/2000/svg";
  const el = (n, a={}) => { const e = document.createElementNS(SVGNS, n);
    for (const k in a) e.setAttribute(k, a[k]); return e; };
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  function draw() {
    const svg = document.getElementById("chart"); svg.textContent = "";
    const W=720,H=380,padL=52,padR=16,padT=24,padB=40;
    const plotW=W-padL-padR, plotH=H-padT-padB;
    const maxAbs = Math.max(...DATA.map(d => Math.abs(d.avg))) * 1.12 || 0.01;
    const zeroY = padT + plotH/2;
    const yOf = v => zeroY - (v/maxAbs)*(plotH/2);
    const band = plotW/DATA.length, bw = Math.min(38, band*0.62);
    const upC=css("--up"),downC=css("--down"),hair=css("--hair"),hairS=css("--hair-strong"),
          ink3=css("--ink-3"),ink=css("--ink"),accent=css("--accent"),faded=css("--faded")||0.3;
    [maxAbs/2,0,-maxAbs/2].forEach(v => {
      const y=yOf(v);
      svg.appendChild(el("line",{x1:padL,y1:y,x2:W-padR,y2:y,
        stroke:v===0?hairS:hair,"stroke-width":v===0?1.3:1,"stroke-dasharray":v===0?"0":"3 4"}));
      const t=el("text",{x:padL-8,y:y+4,"text-anchor":"end","font-size":11,fill:ink3});
      t.textContent=pct(v,1); svg.appendChild(t);
    });
    DATA.forEach((d,i) => {
      const cx=padL+band*i+band/2, x=cx-bw/2, up=d.avg>=0;
      const y=up?yOf(d.avg):zeroY, h=Math.max(1.5,Math.abs(yOf(d.avg)-zeroY)), isSig=sig(d);
      const r=el("rect",{x,y,width:bw,height:h,rx:4,fill:up?upC:downC,
        opacity:isSig?1:faded,"data-i":i,class:"bar",tabindex:0});
      r.style.cursor="pointer"; r.style.transition="opacity .12s"; svg.appendChild(r);
      if (isSig) {
        const ly=up?y-8:y+h+16;
        const star=el("text",{x:cx,y:up?y-20:y+h+30,"text-anchor":"middle","font-size":13,fill:accent});
        star.textContent="★"; svg.appendChild(star);
        const val=el("text",{x:cx,y:ly,"text-anchor":"middle","font-size":11.5,"font-weight":700,fill:up?upC:downC});
        val.textContent=pct(d.avg,1); svg.appendChild(val);
      }
      const mt=el("text",{x:cx,y:H-padB+22,"text-anchor":"middle","font-size":12,
        fill:isSig?ink:ink3,"font-weight":isSig?700:400});
      mt.textContent=d.m+"月"; svg.appendChild(mt);
    });
    const tip=document.getElementById("tip");
    const show=(e,i)=>{ const d=DATA[i];
      tip.innerHTML=`<div class="t-m">${d.m} 月</div>`+
        `<div class="row"><span>平均涨跌</span><b>${pct(d.avg)}</b></div>`+
        `<div class="row"><span>中位涨跌</span><b>${pct(d.med)}</b></div>`+
        `<div class="row"><span>上涨概率</span><b>${(d.win*100).toFixed(0)}%</b></div>`+
        `<div class="row"><span>样本年数</span><b>${d.yrs} 年</b></div>`+
        `<div class="row"><span>p(概率/均值)</span><b>${d.pw.toFixed(2)} / ${d.pm.toFixed(2)}</b></div>`+
        `<div class="t-sig" style="color:${sig(d)?accent:ink3}">${sig(d)?"★ 统计显著（p<0.1）":"未通过显著性检验"}</div>`;
      tip.style.opacity=1; const rc=tip.getBoundingClientRect();
      let px=(e.clientX||0)+14, py=(e.clientY||0)+14;
      if (px+rc.width>innerWidth) px=e.clientX-rc.width-14;
      if (py+rc.height>innerHeight) py=e.clientY-rc.height-14;
      tip.style.left=px+"px"; tip.style.top=py+"px";
    };
    const hide=()=>{ tip.style.opacity=0; };
    svg.querySelectorAll(".bar").forEach(b => {
      const i=+b.getAttribute("data-i");
      b.addEventListener("mousemove",e=>show(e,i));
      b.addEventListener("mouseleave",hide);
      b.addEventListener("focus",()=>{ const bb=b.getBoundingClientRect();
        show({clientX:bb.left+bb.width/2,clientY:bb.top},i); });
      b.addEventListener("blur",hide);
    });
  }
  function table() {
    const tb=document.querySelector("#tbl tbody");
    DATA.forEach(d => {
      const tr=document.createElement("tr"), isSig=sig(d);
      tr.className=(isSig?"sig ":"")+(isSig?"":"dim");
      const cls=d.avg>=0?"up":"down";
      tr.innerHTML=`<td>${d.m} 月</td>`+
        `<td class="pos ${cls}">${pct(d.avg)}</td>`+
        `<td>${pct(d.med)}</td>`+
        `<td>${(d.win*100).toFixed(0)}%</td>`+
        `<td>${d.yrs} 年</td>`+
        `<td>${d.pw.toFixed(2)}</td>`+
        `<td>${d.pm.toFixed(2)}</td>`;
      tb.appendChild(tr);
    });
  }
  draw(); table();
  new MutationObserver(draw).observe(document.documentElement,
    {attributes:true, attributeFilter:["data-theme"]});
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
</script>
</body>
</html>
"""


def load_prices(path):
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    dcol = cols.get("date") or cols.get("日期")
    ccol = cols.get("close") or cols.get("收盘价") or cols.get("收盘")
    if not dcol or not ccol:
        raise ValueError(f"CSV 需含 date/close 列，实际列：{list(df.columns)}")
    out = pd.DataFrame({
        "date": pd.to_datetime(df[dcol]),
        "close": pd.to_numeric(df[ccol], errors="coerce"),
    }).dropna().sort_values("date").reset_index(drop=True)
    if len(out) < 250:
        raise ValueError(f"数据太短（{len(out)} 行），季节性至少需要数年日线。")
    return out


def monthly_returns(px):
    """各年各月的月度收益。用连续月末价 pct_change，天然跨年衔接，
    不会像'按年分组'那样把每年 1 月丢成 NaN。"""
    m = (px.set_index("date")["close"]
         .resample("ME").last()          # 每月最后交易日收盘
         .to_frame("close"))
    m["ret"] = m["close"].pct_change()
    m["year"] = m.index.year
    m["month"] = m.index.month
    return m.dropna(subset=["ret"])


def _binom_two_sided_p(k, n, p=0.5):
    """上涨 k/n 年，检验上涨概率是否显著偏离 50%（二项精确检验，双侧）。"""
    from math import comb
    if n == 0:
        return float("nan")
    probs = [comb(n, i) * p**i * (1 - p)**(n - i) for i in range(n + 1)]
    obs = probs[k]
    return float(min(1.0, sum(pr for pr in probs if pr <= obs + 1e-12)))


def _student_t_sf_two_sided(t, df):
    """t 分布双侧尾概率 P(|T| > |t|)，T~t(df)。

    用正则化不完全 Beta 函数 I_x(df/2, 1/2)（x = df/(df+t²)）实现，
    等价于 scipy.stats.t.sf(|t|, df)*2，但不引入 scipy 依赖。
    """
    from math import lgamma, log, exp
    df = float(df)
    x = df / (df + t * t)          # ∈ (0, 1]

    def _betacf(a, b, x):
        fpmin, eps, maxit = 1e-300, 3e-14, 300
        qab, qap, qam = a + b, a + 1.0, a - 1.0
        c = 1.0
        d = 1.0 - qab * x / qap
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        h = d
        for m in range(1, maxit):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > fpmin else fpmin)
            c = 1.0 + aa / c
            c = c if abs(c) > fpmin else fpmin
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > fpmin else fpmin)
            c = 1.0 + aa / c
            c = c if abs(c) > fpmin else fpmin
            de = d * c
            h *= de
            if abs(de - 1.0) < eps:
                break
        return h

    def _betai(a, b, x):
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        lbeta = lgamma(a) + lgamma(b) - lgamma(a + b)
        bt = exp(a * log(x) + b * log(1.0 - x) - lbeta)
        if x < (a + 1.0) / (a + b + 2.0):
            return bt * _betacf(a, b, x) / a
        return 1.0 - bt * _betacf(b, a, 1.0 - x) / b

    return _betai(df / 2.0, 0.5, x)


def _t_test_p(x):
    """平均涨跌是否显著≠0（单样本 t 检验，无 scipy 依赖）。

    用真实 t 分布算双侧 p——季节性样本只有几年（如 11 年 = 10 自由度），
    小样本尾部若用正态近似会系统性低估 p、高估显著性，与本 skill
    "不把噪声当规律"的立身之本相悖，故必须用 t 分布。
    """
    x = np.asarray(x, float)
    n = len(x)
    if n < 2 or x.std(ddof=1) == 0:
        return float("nan")
    t = x.mean() / (x.std(ddof=1) / np.sqrt(n))
    return float(min(1.0, _student_t_sf_two_sided(t, n - 1)))


def seasonality_table(m):
    """按月聚合季节性统计。"""
    rows = []
    for month, g in m.groupby("month"):
        rets = g["ret"].values
        n = len(rets)
        k = int((rets > 0).sum())
        rows.append({
            "month": int(month),
            "avg_return": float(np.mean(rets)),
            "median_return": float(np.median(rets)),
            "std": float(np.std(rets, ddof=1)) if n > 1 else float("nan"),
            "win_rate": k / n if n else float("nan"),
            "years": n,
            "p_winrate": _binom_two_sided_p(k, n),
            "p_mean": _t_test_p(rets),
        })
    tbl = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    return tbl


def current_position(m, tbl):
    """当前处在季节周期的什么位置：最新数据的月份 + 下个月的季节性倾向。"""
    last = m.index.max()
    cur_month = last.month
    nxt = cur_month % 12 + 1
    row = tbl[tbl["month"] == nxt]
    if row.empty:
        return {"as_of": str(last.date()), "next_month": nxt}
    r = row.iloc[0]
    return {
        "as_of": str(last.date()),
        "current_month": cur_month,
        "next_month": nxt,
        "next_month_avg_return": r["avg_return"],
        "next_month_win_rate": r["win_rate"],
        "next_month_years": int(r["years"]),
        "next_month_significant": bool(r["p_winrate"] < 0.1 or r["p_mean"] < 0.1),
    }


def _is_significant(row):
    """与逐月表星号同一口径：上涨概率或平均涨跌任一检验显著（p<0.1）。"""
    return (row["p_winrate"] < 0.1) or (row["p_mean"] < 0.1)


def build_report(tbl, pos, symbol=None):
    # 强弱月判定与逐月表星号保持一致：统计显著 + 方向，避免"表里打星、汇总说无显著"的自相矛盾
    sig = tbl.apply(_is_significant, axis=1)
    strong_up = tbl[sig & (tbl["avg_return"] > 0) & (tbl["win_rate"] > 0.5)]
    strong_dn = tbl[sig & (tbl["avg_return"] < 0) & (tbl["win_rate"] < 0.5)]
    min_years = int(tbl["years"].min())
    return {
        "symbol": symbol,
        "sample_years": int(tbl["years"].max()),
        "min_years_any_month": min_years,
        "low_sample_warning": min_years < MIN_YEARS_WARN,
        "seasonal_strong_up_months": strong_up["month"].tolist(),
        "seasonal_strong_down_months": strong_dn["month"].tolist(),
        "current": pos,
        "monthly_table": json.loads(tbl.to_json(orient="records")),
        "caveats": [
            "季节性是历史概率规律，不是当年保证；当年基本面（天气、政策、供需）可覆盖季节性。",
            f"样本年数最少的月份仅 {min_years} 年，样本量小，p 值不显著的月份勿过度解读。",
            "多重检验提示：同时检验了 12 个月，即使纯随机也预期约有 1 个月偶然显著（p<0.1）——"
            "标星月份是‘提示性’而非‘已证实’，须结合作物日历机理判断。",
            "本结果不构成买卖指令，仅供研究与择时参考。",
        ],
    }


def render_text(rep):
    L = []
    L.append(f"农产品期货季节性分析" + (f"（{rep['symbol']}）" if rep["symbol"] else ""))
    L.append("=" * 56)
    L.append(f"样本年数：{rep['sample_years']} 年" +
             ("  ⚠ 样本偏少，谨慎解读" if rep["low_sample_warning"] else ""))
    up = "、".join(f"{m}月" for m in rep["seasonal_strong_up_months"]) or "无显著"
    dn = "、".join(f"{m}月" for m in rep["seasonal_strong_down_months"]) or "无显著"
    L.append(f"季节性偏强月份：{up}")
    L.append(f"季节性偏弱月份：{dn}")
    c = rep["current"]
    if "next_month_win_rate" in c:
        L.append("")
        L.append(f"当前数据截至 {c['as_of']}（{c.get('current_month')}月），"
                 f"下月（{c['next_month']}月）季节性：")
        L.append(f"  历年平均涨跌 {c['next_month_avg_return']:+.2%}，"
                 f"上涨概率 {c['next_month_win_rate']:.0%}，"
                 f"样本 {c['next_month_years']} 年，"
                 f"{'统计显著' if c['next_month_significant'] else '不显著（当噪声看）'}")
    L.append("")
    L.append("逐月季节性：")
    L.append(f"{'月份':>4} {'平均涨跌':>9} {'上涨概率':>7} {'样本年':>6} {'显著性':>8}")
    for r in rep["monthly_table"]:
        sig = "*" if _is_significant(r) else ""
        L.append(f"{r['month']:>3}月 {r['avg_return']:>+9.2%} "
                 f"{r['win_rate']:>7.0%} {r['years']:>5}年 {sig:>8}")
    L.append("")
    L.append("说明：")
    for c in rep["caveats"]:
        L.append(f"  - {c}")
    return "\n".join(L)


def _html_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_html(rep):
    """生成自包含 HTML 报告（内联 SVG + CSS + JS，零外部依赖，离线可用）。

    显著性直接编码进图形：显著月份（p<0.1）实心并标 ★，不显著月份半透明——
    噪声在视觉上自然退隐，避免"漂亮的图掩盖不显著"这一与本 skill 立身之本相悖的问题。
    """
    symbol = rep.get("symbol") or "未标注品种"
    cur = rep.get("current", {})
    as_of = cur.get("as_of", "")

    meta = (f"样本 <b>{rep['sample_years']} 年</b> &nbsp;·&nbsp; "
            f"数据截至 <b>{_html_escape(as_of)}</b> &nbsp;·&nbsp; 主力连续日线")

    warn = ""
    if rep.get("low_sample_warning"):
        warn = ('<div class="warn">⚠ 样本年数偏少，季节性结论可靠性下降，'
                '请谨慎解读不显著月份。</div>')

    callout = ""
    if "next_month_win_rate" in cur:
        sig_txt = "统计显著" if cur.get("next_month_significant") else "不显著 · 当噪声看"
        callout = (
            '<div class="callout">'
            '<span class="lead">当前位置 · 下月季节性倾向</span>'
            f'<span class="stat">当前 <b>{cur.get("current_month")} 月</b></span>'
            f'<span class="stat">下月（{cur.get("next_month")} 月）平均涨跌 '
            f'<b>{cur["next_month_avg_return"]:+.2%}</b></span>'
            f'<span class="stat">上涨概率 <b>{cur["next_month_win_rate"]:.0%}</b></span>'
            f'<span class="stat">样本 <b>{cur.get("next_month_years")} 年</b></span>'
            f'<span class="stat"><span class="tag">{sig_txt}</span></span>'
            '</div>')

    data = [{"m": r["month"], "avg": r["avg_return"], "med": r["median_return"],
             "win": r["win_rate"], "yrs": r["years"],
             "pw": r["p_winrate"], "pm": r["p_mean"]}
            for r in rep["monthly_table"]]
    data_json = json.dumps(data)
    caveats = "".join(f"<li>{_html_escape(c)}</li>" for c in rep["caveats"])

    return (_HTML_TEMPLATE
            .replace("__TITLE__", _html_escape(f"农产品期货季节性分析 · {symbol}"))
            .replace("__SYMBOL__", _html_escape(symbol))
            .replace("__META__", meta)
            .replace("__WARN__", warn)
            .replace("__CALLOUT__", callout)
            .replace("__DATA_JSON__", data_json)
            .replace("__CAVEATS__", caveats))


def main(argv=None):
    ap = argparse.ArgumentParser(description="农产品期货季节性分析")
    ap.add_argument("--csv", required=True, help="主力连续日线 CSV（列：date, close）")
    ap.add_argument("--symbol", default=None, help="品种标注（如 M 豆粕）")
    ap.add_argument("--out", default=None, help="输出目录（写 json + txt + html）")
    ap.add_argument("--no-html", action="store_true", help="不生成 HTML 可视化报告")
    args = ap.parse_args(argv)

    px = load_prices(args.csv)
    m = monthly_returns(px)
    tbl = seasonality_table(m)
    pos = current_position(m, tbl)
    rep = build_report(tbl, pos, args.symbol)

    print(render_text(rep))
    if args.out:
        import os
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "seasonality.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        with open(os.path.join(args.out, "seasonality.txt"), "w", encoding="utf-8") as f:
            f.write(render_text(rep) + "\n")
        outputs = "json + txt"
        if not args.no_html:
            with open(os.path.join(args.out, "seasonality.html"), "w",
                      encoding="utf-8") as f:
                f.write(render_html(rep))
            outputs += " + html"
        print(f"\n报告已写入 {args.out}/（{outputs}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
