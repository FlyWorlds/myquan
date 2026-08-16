"""从 CSV 生成凯盛+天通 策略一·因子1 可视化 HTML。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
OUT = DIR / "report.html"


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


def main() -> None:
    monthly = pd.read_csv(DIR / "monthly_excess.csv")
    yearly = pd.read_csv(DIR / "yearly_decay.csv")
    rolling = pd.read_csv(DIR / "rolling12m_excess.csv")
    decay = pd.read_csv(DIR / "decay_summary.csv")
    summary = json.loads((DIR / "summary.json").read_text(encoding="utf-8"))

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
    rp["日期"] = pd.to_datetime(rp["日期"])
    rp = rp.sort_values("日期")
    rk = rolling[rolling["标的"] == "凯盛科技"].sort_values("日期")
    rt = rolling[rolling["标的"] == "天通股份"].sort_values("日期")

    # 年末滚动12M
    r_end = []
    for yr in sorted(rp["日期"].dt.year.unique()):
        sub = rp[rp["日期"].dt.year == yr]
        if len(sub):
            r_end.append(
                {
                    "year": int(yr),
                    "组合": float(sub.iloc[-1]["滚动12M超额%"]),
                    "凯盛": float(rk.iloc[rk.index.get_loc(sub.index[-1])]["滚动12M超额%"])
                    if sub.index[-1] in rk.index
                    else None,
                }
            )

    payload = {
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
            "dates": rp["日期"].dt.strftime("%Y-%m-%d").tolist(),
            "组合": rp["滚动12M超额%"].astype(float).tolist(),
            "凯盛": rk["滚动12M超额%"].astype(float).tolist(),
            "天通": rt["滚动12M超额%"].astype(float).tolist(),
        },
        "decay": decay.to_dict(orient="records"),
    }

    data_js = json.dumps(payload, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>凯盛+天通 · 策略一·因子1 · 可视化</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#8b9bb4;
    --accent:#3d9cf0; --kc:#a78bfa; --tt:#fbbf24; --good:#3ecf8e; --bad:#f07178;
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
  .two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:900px) {{ .two {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <h1>凯盛科技 + 天通股份 · 策略一 · 因子1</h1>
  <p class="sub" id="subtitle"></p>
  <div class="grid" id="stats"></div>

  <div class="card">
    <h2>归一净值曲线（月末 · 名义本金 10 万）</h2>
    <canvas id="equity"></canvas>
    <p class="note">蓝=组合策略，灰虚线=组合平权持有，紫=凯盛单票策略，黄=天通单票策略（各独立 10 万后合成对比）。</p>
  </div>

  <div class="card">
    <h2>分月超额收益（% · 相对平权持有）</h2>
    <canvas id="monthly"></canvas>
    <p class="note">柱在零轴上方表示当月策略跑赢平权持有。数据源：monthly_excess.csv</p>
  </div>

  <div class="two">
    <div class="card">
      <h2>分年超额（%）</h2>
      <canvas id="yearly"></canvas>
    </div>
    <div class="card">
      <h2>因子1 闭环笔数（衰减代理）</h2>
      <canvas id="trades"></canvas>
      <p class="note">闭环笔数下降可能意味着信号变少；需结合超额一起看。</p>
    </div>
  </div>

  <div class="card">
    <h2>滚动 12 个月累计超额（% · 252 交易日）</h2>
    <canvas id="rolling"></canvas>
    <p class="note">2025 末组合滚动超额探底 (~9%)，2026 回升；反映阶段性环境切换而非单调衰减。</p>
  </div>
</div>
<script>
const D = {data_js};
const meta = D.meta;
document.getElementById('subtitle').innerHTML =
  `<span class="pill">策略一 · 仅因子1</span><span class="pill">凯盛 2.5% / 天通 3%</span>` +
  meta['区间'] + ' · ' + meta['口径'];

const p = meta['组合'];
const stats = [
  ['组合累计策略', '+' + p['累计策略%'].toFixed(1) + '%', 'good'],
  ['组合累计超额', '+' + p['累计超额%'].toFixed(1) + ' pct', 'good'],
  ['超额月胜率', p['超额月胜率%'] + '%', ''],
  ['滚动12M超额', '+' + p['滚动12M最新超额%'].toFixed(1) + '%', 'good'],
  ['凯盛累计超额', '+' + meta['凯盛科技']['累计超额%'].toFixed(0) + ' pct', 'good'],
  ['天通累计超额', '+' + meta['天通股份']['累计超额%'].toFixed(0) + ' pct', 'good'],
  ['2024 组合超额', '+' + p['2024超额%'].toFixed(1) + '%', 'good'],
  ['2025 组合超额', (p['2025超额%']>=0?'+':'') + p['2025超额%'].toFixed(1) + '%', p['2025超额%']>=0?'good':'bad'],
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
    datasets: [
      {{ label: '组合超额%', data: D.monthly_excess['组合'], backgroundColor: barColors(D.monthly_excess['组合']), borderWidth: 0 }},
    ]
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

new Chart(document.getElementById('yearly'), {{
  type: 'bar',
  data: {{
    labels: D.yearly.years,
    datasets: [
      {{ label: '组合', data: D.yearly['组合超额'], backgroundColor: 'rgba(61,156,240,0.8)' }},
      {{ label: '凯盛', data: D.yearly['凯盛超额'], backgroundColor: 'rgba(167,139,250,0.8)' }},
      {{ label: '天通', data: D.yearly['天通超额'], backgroundColor: 'rgba(251,191,36,0.8)' }},
    ]
  }},
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
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
