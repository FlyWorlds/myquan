"""Klarman 4 类 Tab dashboard。

从 validation/scan_5y.parquet（或 scan_1y）读入事件，生成:
  - 概览 Tab: 5 年时间线、按事件类型/月份分布、缺失核心门
  - 定增 Tab: 折价率分布、解禁倒计时、参与者浮盈
  - 重组 Tab: 批文时间线、失败风险、需要分散押注
  - 分拆 Tab: SOTP 表（如有）
  - 困境 Tab: ST 名单、财务好转 double check
  - 分散押注 Tab: allocation.suggest_diversification 结果
"""
from __future__ import annotations

import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd

from allocation import suggest_diversification


CSS = """
:root {
  --bg:#0d1117; --panel:#161b22; --panel2:#1c2129; --border:#30363d;
  --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff; --accent2:#79c0ff;
  --warn:#d29922; --err:#f85149; --ok:#3fb950; --purple:#a371f7;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
.wrap { max-width:1280px; margin:0 auto; padding:32px 24px 60px; }
.header { margin-bottom:20px; }
h1 { font-size:26px; margin:0 0 6px; letter-spacing:-.5px; }
.sub { color:var(--muted); font-size:13px; }
.sub code { color:var(--accent2); background:rgba(88,166,255,.08); padding:1px 6px; border-radius:3px; font-size:12px; }
.banner { background:rgba(210,153,34,.08); border:1px solid rgba(210,153,34,.35);
  color:#e5c26a; padding:12px 16px; border-radius:8px; margin:16px 0 20px; font-size:13px; }
.banner strong { color:#ffb84d; }

.kpis { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:20px; }
.kpi { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:14px 16px; }
.kpi .label { color:var(--muted); font-size:11px; letter-spacing:.5px; text-transform:uppercase; }
.kpi .value { font-size:22px; font-weight:600; margin-top:4px; }
.kpi .note { color:var(--muted); font-size:11px; margin-top:2px; }
.kpi.warn .value { color:var(--warn); }
.kpi.err .value { color:var(--err); }
.kpi.ok .value { color:var(--ok); }
.kpi.acc .value { color:var(--accent); }

.tabs { display:flex; gap:2px; border-bottom:1px solid var(--border); margin-bottom:0; overflow-x:auto; }
.tab { padding:10px 16px; background:transparent; border:none; color:var(--muted);
  cursor:pointer; font-size:13px; font-weight:500; border-radius:6px 6px 0 0;
  border-bottom:2px solid transparent; white-space:nowrap; }
.tab:hover { color:var(--text); background:var(--panel); }
.tab.active { color:var(--accent); border-bottom-color:var(--accent); background:var(--panel); }
.tab .badge { display:inline-block; background:var(--panel2); color:var(--muted);
  padding:0 6px; border-radius:8px; font-size:11px; margin-left:6px; }
.tab.active .badge { background:rgba(88,166,255,.15); color:var(--accent); }

.tab-panel { display:none; padding:24px 0; }
.tab-panel.active { display:block; }

.panel { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:20px; margin-bottom:16px; }
.panel h2 { font-size:15px; margin:0 0 12px; letter-spacing:.2px; }
.panel h3 { font-size:13px; margin:16px 0 8px; color:var(--muted); font-weight:500; text-transform:uppercase; letter-spacing:.5px; }
.panel .caption { color:var(--muted); font-size:12px; margin-bottom:12px; line-height:1.5; }
.grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.grid-3 { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }

table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); }
th { color:var(--muted); font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }
tr:hover td { background:rgba(88,166,255,.04); }
td.num { font-variant-numeric:tabular-nums; text-align:right; }

.bar-row { display:flex; align-items:center; gap:12px; margin:6px 0; }
.bar-row .name { min-width:200px; font-size:13px; }
.bar-row .track { flex:1; height:16px; background:#21262d; border-radius:3px; overflow:hidden; }
.bar-row .fill { height:100%; background:var(--accent); }
.bar-row .fill.warn { background:var(--warn); }
.bar-row .fill.err { background:var(--err); }
.bar-row .fill.ok { background:var(--ok); }
.bar-row .fill.purple { background:var(--purple); }
.bar-row .n { min-width:70px; text-align:right; color:var(--muted); font-variant-numeric:tabular-nums; }

.month-bars { display:grid; grid-template-columns:repeat(auto-fit, minmax(28px, 1fr)); gap:3px;
  align-items:end; height:140px; margin-top:12px; }
.month-bars .mb { display:flex; flex-direction:column; align-items:center; height:100%; }
.month-bars .col-wrap { flex:1; display:flex; align-items:end; width:100%; padding:0 2px; }
.month-bars .col { width:100%; background:var(--accent); border-radius:2px 2px 0 0; min-height:2px; }
.month-bars .label { font-size:9px; color:var(--muted); margin-top:4px; }
.month-bars .n { font-size:9px; color:var(--text); }

.pill { display:inline-block; padding:1px 7px; border-radius:9px; font-size:11px; }
.pill.warn { background:rgba(210,153,34,.15); color:var(--warn); }
.pill.err { background:rgba(248,81,73,.15); color:var(--err); }
.pill.ok { background:rgba(63,185,80,.15); color:var(--ok); }
.pill.muted { background:rgba(133,133,133,.15); color:var(--muted); }

code { font-size:12px; color:var(--accent2); }
.footer { color:var(--muted); font-size:12px; margin-top:32px; text-align:center; }

.klarman-quote { font-style:italic; color:#c9d1d9; padding:12px 16px; border-left:3px solid var(--accent);
  background:rgba(88,166,255,.04); margin:12px 0; font-size:13px; }
.klarman-quote::before { content:'"'; font-size:24px; color:var(--accent); margin-right:6px; vertical-align:-4px; }

@media (max-width:900px) {
  .kpis { grid-template-columns:repeat(2,1fr); }
  .grid-2, .grid-3 { grid-template-columns:1fr; }
}
"""

JS = """
function selectTab(idx) {
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',i===idx));
  document.querySelectorAll('.tab-panel').forEach((p,i)=>p.classList.toggle('active',i===idx));
}
"""


def _bar(name: str, value: int, total: int, cls: str = "") -> str:
    pct = (100.0 * value / total) if total else 0.0
    return (
        f'<div class="bar-row"><div class="name">{html.escape(str(name))}</div>'
        f'<div class="track"><div class="fill {cls}" style="width:{pct:.1f}%"></div></div>'
        f'<div class="n">{value}</div></div>'
    )


def _pill(text: str, cls: str) -> str:
    return f'<span class="pill {cls}">{html.escape(str(text))}</span>'


def _month_bars(months: pd.Series) -> str:
    if not len(months):
        return '<div class="caption">无数据</div>'
    max_v = int(months.max())
    parts = []
    for m, cnt in months.items():
        h = int(round(cnt * 100.0 / max_v)) if max_v else 0
        parts.append(
            f'<div class="mb"><div class="col-wrap"><div class="col" style="height:{max(h,2)}%"></div></div>'
            f'<div class="n">{cnt}</div><div class="label">{html.escape(str(m))}</div></div>'
        )
    return "".join(parts)


def _load_events(input_parquet: Path) -> list[dict]:
    df = pd.read_parquet(input_parquet)
    events = []
    for _, row in df.iterrows():
        try:
            p = json.loads(row["payload_json"])
        except Exception:
            continue
        events.append({
            "row": row.to_dict(),
            "payload": p,
        })
    return events


def _overview_tab(events: list[dict], df: pd.DataFrame) -> str:
    total = len(events)
    unique_symbols = df["symbol"].astype(str).replace("", pd.NA).dropna().nunique()

    situation_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()
    gates_counter: Counter[str] = Counter()

    for e in events:
        p = e["payload"]
        st = p.get("situation_type") or e["row"]["result_type"]
        situation_counter[str(st)] += 1
        status_counter[str(e["row"]["result_value"])] += 1
        for g in (p.get("klarman_gates") or {}).get("missing_required") or []:
            gates_counter[g] += 1

    df["signal_month"] = df["signal_date"].astype(str).str[:6]
    months = df["signal_month"].value_counts().sort_index()

    situation_bars = "".join(_bar(s, c, total, "purple") for s, c in situation_counter.most_common())
    status_bars = "".join(
        _bar(s, c, total, "err" if s in ("insufficient_evidence", "underwriting_incomplete") else "warn")
        for s, c in status_counter.most_common()
    )
    gates_bars = "".join(_bar(g, c, total, "err") for g, c in gates_counter.most_common())

    return f"""
    <div class="panel">
      <div class="klarman-quote">
        每一次投资的核心问题是：我能失去什么？只有回答了这个问题才有资格问：我能赚什么？<br>
        <span style="color:var(--muted); font-size:12px;">—— Seth Klarman《安全边际》</span>
      </div>
    </div>
    <div class="grid-2">
      <div class="panel">
        <h2>按事件类型分布</h2>
        <div class="caption">Klarman 4 类特殊情况在 A 股的实际发现分布</div>
        {situation_bars}
      </div>
      <div class="panel">
        <h2>按承保状态分布</h2>
        <div class="caption">发现层 × 承保门结果。零 qualified 是有效结果</div>
        {status_bars}
      </div>
    </div>
    <div class="panel">
      <h2>按月发现事件量</h2>
      <div class="caption">signal_date 月度分布，反映 A 股特殊情况的时间聚集性（年报季 ST、批文集中期）</div>
      <div class="month-bars">{_month_bars(months)}</div>
    </div>
    <div class="panel">
      <h2>缺失核心承保门</h2>
      <div class="caption">Klarman 承保需要 9 个核心门。此表说明补齐 evidence_dir 时应重点填哪些字段</div>
      {gates_bars}
    </div>
    """


def _placement_tab(events: list[dict]) -> str:
    items = [e for e in events if e["payload"].get("situation_type") == "private_placement_unlock"]
    if not items:
        return f"""
        <div class="panel">
          <h2>定增折价套利 —— Klarman 第 1 类</h2>
          <div class="banner">
            <strong>本轮扫描无 private_placement_unlock 命中。</strong>
            要触发定增候选需同时满足：参与者浮盈 &gt; 20% 且存在 150–1200 日锁定期的解禁记录。
            承保逻辑将此类事件固定为 <code>risk_watch</code> —— 因为发行价是参与者成本，
            不是二级市场投资者的安全边际。这是 Klarman 关键坑之一：<em>定增折价的解禁风险须计入</em>。
          </div>
          <h3>如何补齐</h3>
          <ol>
            <li>用 <code>references/evidence_templates/private_placement_unlock.json</code> 手工提交 evidence</li>
            <li>Panda <code>get_stock_private_placement</code> 已扫，但需要参与浮盈突破阈值</li>
          </ol>
        </div>
        """
    rows_html = ""
    for e in items[:30]:
        p = e["payload"]
        rows_html += f"""<tr>
          <td>{html.escape(str(p.get('knowledge_cutoff') or ''))}</td>
          <td><code>{html.escape(str(p.get('symbol') or ''))}</code></td>
          <td class="num">{p.get('issue_price') or '-'}</td>
          <td class="num">{p.get('market_price', {}).get('close', '-') if isinstance(p.get('market_price'), dict) else '-'}</td>
          <td class="num">{f"{p.get('participant_unrealized_gain', 0):.1%}" if p.get('participant_unrealized_gain') else '-'}</td>
          <td class="num">{f"{p.get('unlock_overhang_ratio', 0):.1%}" if p.get('unlock_overhang_ratio') else '-'}</td>
          <td>{_pill('risk_watch', 'warn')}</td>
        </tr>"""
    return f"""
    <div class="panel">
      <h2>定增折价套利 —— Klarman 第 1 类</h2>
      <div class="caption">
        跟踪定增发行价 vs 市价。<strong>发行价是参与者成本，不是二级安全边际</strong>——
        本 skill 将此类固定为 <code>risk_watch</code>，仅报告解禁供给风险。
      </div>
      <table>
        <thead><tr><th>signal</th><th>symbol</th><th class="num">发行价</th>
          <th class="num">市价</th><th class="num">参与者浮盈</th><th class="num">解禁量/流通盘</th><th>状态</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    """


def _reorg_tab(events: list[dict]) -> str:
    items = [e for e in events if e["payload"].get("situation_type") == "reorganization"]

    # 分散押注建议
    advice = suggest_diversification(
        [{"symbol": e["payload"].get("symbol"), "situation_type": "reorganization"} for e in items],
        failure_rate=0.30,
    )

    if not items:
        table_html = '<div class="caption">本轮无重组/借壳事件</div>'
    else:
        rows_html = ""
        for e in items[:30]:
            p = e["payload"]
            rows_html += f"""<tr>
              <td>{html.escape(str(p.get('knowledge_cutoff') or ''))}</td>
              <td><code>{html.escape(str(p.get('symbol') or ''))}</code></td>
              <td>{html.escape(str(p.get('event_state') or ''))}</td>
              <td>{_pill(e['row']['result_value'], 'err' if 'insufficient' in str(e['row']['result_value']) else 'warn')}</td>
            </tr>"""
        table_html = f"""<table>
          <thead><tr><th>signal</th><th>symbol</th><th>event_state</th><th>状态</th></tr></thead>
          <tbody>{rows_html}</tbody></table>"""

    flags_html = "".join(f'<div class="pill warn" style="margin:2px">{html.escape(f)}</div>' for f in advice.concentration_flags) or '<span class="pill ok">无集中度警报</span>'

    return f"""
    <div class="panel">
      <h2>重组 / 借壳 —— Klarman 第 2 类</h2>
      <div class="caption">
        CSRC 批文 + 停牌复牌事件驱动。<strong>关键坑：失败率 30%+，须分散押注</strong>。
      </div>
      {table_html}
    </div>
    <div class="panel">
      <h2>分散押注建议器</h2>
      <div class="caption">基于 30% 失败率、50% 永久损失、20% 组合回撤忍受度。<strong>仅指导，非交易指令</strong>。</div>
      <div class="grid-3">
        <div class="kpi"><div class="label">当前候选</div><div class="value">{len(items)}</div></div>
        <div class="kpi acc"><div class="label">建议最小持仓</div><div class="value">{advice.min_positions}</div></div>
        <div class="kpi ok"><div class="label">单事件权重上限</div><div class="value">{advice.max_weight_per_event*100:.1f}%</div></div>
      </div>
      <h3>集中度警报</h3>
      {flags_html}
      <div class="caption" style="margin-top:12px;">{html.escape(advice.rationale)}</div>
    </div>
    """


def _spinoff_tab(events: list[dict]) -> str:
    items = [e for e in events if e["payload"].get("situation_type") == "spin_off"]
    if not items:
        return """
        <div class="panel">
          <h2>分拆上市 —— Klarman 第 3 类</h2>
          <div class="banner">
            <strong>Panda Data 数据源限制：<code>get_stock_csrc_approval</code> 中不含"分拆"自然语言。</strong>
            CSRC 批文按行政类别编码组织，不区分分拆事件。此类事件目前仅能通过
            <code>evidence_dir</code> 人工提交上市公司分拆预案获取。
          </div>
          <div class="caption">
            <strong>SOTP 保守估值要求</strong>：子公司身份 + 母公司持股比例 +
            <em>子公司独立保守价值</em>（不能用合同金额替代）+ 剩余业务价值 + 净债务 + 税费 + 控股折价 + 稀释股数。
          </div>
          <h3>如何补齐</h3>
          <ol>
            <li>参考 <code>references/evidence_templates/spin_off.json</code></li>
            <li>手工搜集上市公司分拆预案公告，填入 atoms</li>
            <li>特别注意：<code>subsidiary_conservative_value</code> 必须独立估值，禁用合同金额</li>
          </ol>
        </div>
        """
    rows_html = ""
    for e in items[:30]:
        p = e["payload"]
        rows_html += f"""<tr>
          <td>{html.escape(str(p.get('knowledge_cutoff') or ''))}</td>
          <td><code>{html.escape(str(p.get('symbol') or ''))}</code></td>
          <td>{html.escape(str(p.get('event_state') or ''))}</td>
          <td>{_pill(e['row']['result_value'], 'err')}</td>
        </tr>"""
    return f"""
    <div class="panel">
      <h2>分拆上市 —— Klarman 第 3 类</h2>
      <table>
        <thead><tr><th>signal</th><th>symbol</th><th>状态</th><th>承保</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    """


def _distress_tab(events: list[dict]) -> str:
    items = [e for e in events if e["payload"].get("situation_type") == "distress_turnaround"]
    if not items:
        return '<div class="panel"><h2>困境反转 —— Klarman 第 4 类</h2><div class="caption">本轮无困境事件</div></div>'

    # 财务好转 double check 分布
    fund_counter: Counter[str] = Counter()
    for e in items:
        f = e["payload"].get("fundamental_double_check") or {}
        fund_counter[str(f.get("double_check") or "unknown")] += 1

    fund_bars = "".join(
        _bar(k, v, len(items),
             "ok" if "improving" in k else "warn" if "insufficient" in k else "err")
        for k, v in fund_counter.most_common()
    )

    rows_html = ""
    for e in items[:30]:
        p = e["payload"]
        f = p.get("fundamental_double_check") or {}
        rows_html += f"""<tr>
          <td>{html.escape(str(p.get('knowledge_cutoff') or ''))}</td>
          <td><code>{html.escape(str(p.get('symbol') or ''))}</code></td>
          <td>{html.escape(str(f.get('double_check') or ''))}</td>
          <td class="num">{f.get('net_profit') if f.get('net_profit') is not None else '-'}</td>
          <td>{_pill(e['row']['result_value'], 'err' if 'insufficient' in str(e['row']['result_value']) else 'warn')}</td>
        </tr>"""

    return f"""
    <div class="panel">
      <h2>困境反转 —— Klarman 第 4 类</h2>
      <div class="caption">
        ST / *ST 股 + 财务好转信号。<strong>ST 摘帽或干净审计不能直接晋级 qualified</strong> ——
        必须走股权回收瀑布，看清偿顺位、优先债务、或有负债，而非利润改善。
      </div>
    </div>
    <div class="panel">
      <h2>基本面 double check 分布</h2>
      <div class="caption">Klarman 关键坑：每类都需事件驱动 + 基本面 double check</div>
      {fund_bars}
    </div>
    <div class="panel">
      <h2>困境事件明细（前 30 条）</h2>
      <table>
        <thead><tr><th>signal</th><th>symbol</th><th>double_check</th><th class="num">净利润</th><th>承保</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    """


def build(input_parquet: Path, output_html: Path) -> None:
    events = _load_events(input_parquet)
    df = pd.read_parquet(input_parquet)
    total = len(events)
    unique_symbols = df["symbol"].astype(str).replace("", pd.NA).dropna().nunique()

    situation_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()
    for e in events:
        p = e["payload"]
        st = p.get("situation_type") or e["row"]["result_type"]
        situation_counter[str(st)] += 1
        status_counter[str(e["row"]["result_value"])] += 1

    n_placement = situation_counter.get("private_placement_unlock", 0)
    n_reorg = situation_counter.get("reorganization", 0)
    n_spinoff = situation_counter.get("spin_off", 0)
    n_distress = situation_counter.get("distress_turnaround", 0)

    signal_dates = df["signal_date"].astype(str)
    date_range = (signal_dates.min() if len(signal_dates) else "", signal_dates.max() if len(signal_dates) else "")
    span_days = 0
    try:
        from datetime import datetime as _dt
        span_days = (_dt.strptime(date_range[1], "%Y%m%d") - _dt.strptime(date_range[0], "%Y%m%d")).days
    except Exception:
        pass

    try:
        import importlib.metadata
        sdk_ver = importlib.metadata.version("panda-data")
    except Exception:
        sdk_ver = "unknown"

    n_qualified = status_counter.get("qualified_special_situation", 0)

    tabs_config = [
        ("概览", "overview", total),
        ("定增折价", "placement", n_placement),
        ("重组/借壳", "reorg", n_reorg),
        ("分拆上市", "spinoff", n_spinoff),
        ("困境反转", "distress", n_distress),
    ]
    tabs_html = ""
    for i, (name, key, n) in enumerate(tabs_config):
        cls = "tab active" if i == 0 else "tab"
        tabs_html += f'<button class="{cls}" onclick="selectTab({i})">{name}<span class="badge">{n}</span></button>'

    panels_html = ""
    contents = [
        _overview_tab(events, df),
        _placement_tab(events),
        _reorg_tab(events),
        _spinoff_tab(events),
        _distress_tab(events),
    ]
    for i, c in enumerate(contents):
        cls = "tab-panel active" if i == 0 else "tab-panel"
        panels_html += f'<div class="{cls}">{c}</div>'

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Klarman 特殊情况投资 · 多年扫描 dashboard</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>Klarman 特殊情况投资 · dashboard</h1>
    <div class="sub">
      A 股扫描 · 窗口 <code>{date_range[0]}</code> → <code>{date_range[1]}</code>
      （{span_days} 天）· Panda Data <code>{sdk_ver}</code>
      · 4 类特殊情况：定增 / 重组 / 分拆 / 困境
    </div>
  </div>

  <div class="banner">
    <strong>发现层展示，非交易指令。</strong> Klarman 严格承保要求 9 个核心门 + 20% 安全边际。
    本次扫描找到 <b>{total}</b> 个可发现事件，其中 <b>{n_qualified}</b> 通过承保门（
    {"零合格候选是有效结果——" if n_qualified == 0 else ""}
    "核心证据缺失时保持不完整"）。补齐 <code>evidence_dir</code> 才能晋级 qualified。
  </div>

  <div class="kpis">
    <div class="kpi"><div class="label">扫描事件</div><div class="value">{total}</div><div class="note">4 类合计</div></div>
    <div class="kpi"><div class="label">唯一 A 股</div><div class="value">{unique_symbols}</div><div class="note">去重后</div></div>
    <div class="kpi ok"><div class="label">合格候选</div><div class="value">{n_qualified}</div><div class="note">通过 20% 安全边际</div></div>
    <div class="kpi warn"><div class="label">承保不完整</div><div class="value">{status_counter.get('underwriting_incomplete', 0)}</div><div class="note">缺核心门</div></div>
    <div class="kpi err"><div class="label">证据不足</div><div class="value">{status_counter.get('insufficient_evidence', 0)}</div><div class="note">API/身份缺</div></div>
  </div>

  <div class="tabs">{tabs_html}</div>
  {panels_html}

  <div class="footer">
    build_id=<code>Q51</code> · <code>skill-klarman-special-situations</code>
    · 生成于 {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
  </div>
</div>
<script>{JS}</script>
</body>
</html>
"""
    output_html.write_text(body, encoding="utf-8")
    print(f"[ok] {total} events -> {output_html}")


def main():
    input_parquet = ROOT / "validation" / "scan_5y.parquet"
    if not input_parquet.exists():
        input_parquet = ROOT / "validation" / "scan_1y.parquet"
        print(f"[warn] scan_5y.parquet 不存在，回退到 scan_1y")
    build(input_parquet, ROOT / "validation" / "dashboard.html")


if __name__ == "__main__":
    main()
