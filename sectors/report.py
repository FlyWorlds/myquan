"""板块轮动 HTML 报告。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_rotation_report(payload: dict[str, Any], path: Path) -> Path:
    """板块轮动交互报告：行业/概念 Tab × 涨幅/涨停/资金 × 前10后10。"""
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    updated = escape(str(payload.get("updated_at") or _now()))
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>板块轮动</title>
  <style>
    :root {{
      --bg: #f5f6f8;
      --card: #fff;
      --line: #e3e6eb;
      --text: #1a1a1a;
      --muted: #6b7280;
      --up: #e11d2e;
      --down: #0a9b57;
      --r1: #e11d2e;
      --r2: #f05a28;
      --r3: #f5a623;
      --hl: #ff8c3a;
      --head: #c62828;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: "DIN Alternate", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text); background: var(--bg);
    }}
    .topbar {{
      background: linear-gradient(180deg, #d32f2f 0%, #c62828 100%);
      color: #fff; padding: 12px 14px 10px;
    }}
    .topbar h1 {{ margin: 0; font-size: 1.15rem; font-weight: 700; letter-spacing: 0.02em; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 0 40px; }}
    .controls {{
      display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 12px;
      background: var(--card); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5;
    }}
    .tabs {{ display: flex; gap: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    .tab {{
      appearance: none; border: 0; background: #fff; padding: 7px 14px; cursor: pointer;
      font-size: 0.88rem; color: var(--muted);
    }}
    .tab.active {{ background: #fff5f5; color: var(--head); font-weight: 700; }}
    select {{
      appearance: none; border: 1px solid var(--line); border-radius: 8px; background: #fff;
      padding: 7px 28px 7px 10px; font-size: 0.88rem; color: var(--text);
      background-image: linear-gradient(45deg, transparent 50%, #888 50%),
        linear-gradient(135deg, #888 50%, transparent 50%);
      background-position: calc(100% - 14px) 55%, calc(100% - 9px) 55%;
      background-size: 5px 5px, 5px 5px; background-repeat: no-repeat;
    }}
    .selected {{
      display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
      padding: 8px 12px; background: #fff; border-bottom: 1px solid var(--line);
      font-size: 0.9rem; min-height: 40px;
    }}
    .selected .name {{ font-weight: 700; }}
    .selected .chg.up {{ color: var(--up); }}
    .selected .chg.down {{ color: var(--down); }}
    .selected .actions {{ margin-left: auto; display: flex; gap: 10px; }}
    .selected a, .selected button.link {{
      color: #2563eb; text-decoration: none; background: none; border: 0;
      cursor: pointer; font-size: 0.85rem; padding: 0;
    }}
    .grid-wrap {{ overflow: auto; background: #fff; max-height: 70vh; }}
    table.heat {{
      border-collapse: collapse; font-size: 0.78rem; min-width: 100%;
    }}
    table.heat th, table.heat td {{
      border: 1px solid var(--line); padding: 0; text-align: center; vertical-align: middle;
    }}
    table.heat th {{
      position: sticky; top: 0; z-index: 2; background: #fafafa; color: var(--muted);
      font-weight: 600; padding: 6px 4px; white-space: nowrap;
    }}
    table.heat th.rank-h, table.heat td.rank {{
      position: sticky; left: 0; z-index: 3; background: #fff; width: 28px; min-width: 28px;
      color: var(--muted); font-weight: 700;
    }}
    table.heat th.rank-h {{ z-index: 4; }}
    table.heat td.rank.bot {{ color: var(--down); }}
    .cell {{
      display: block; width: 100%; min-width: 88px; padding: 6px 4px; cursor: pointer;
      background: #fff; border: 0; font: inherit; color: inherit; text-align: center;
    }}
    .cell:hover {{ filter: brightness(0.97); }}
    .cell .n {{ display: block; font-weight: 600; line-height: 1.2; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis; max-width: 96px; margin: 0 auto; }}
    .cell .v {{ display: block; font-size: 0.75rem; margin-top: 2px; }}
    .cell .v.up {{ color: var(--up); }}
    .cell .v.down {{ color: var(--down); }}
    .cell.r1 {{ background: var(--r1); color: #fff; }}
    .cell.r1 .v {{ color: #fff; }}
    .cell.r2 {{ background: var(--r2); color: #fff; }}
    .cell.r2 .v {{ color: #fff; }}
    .cell.r3 {{ background: var(--r3); color: #fff; }}
    .cell.r3 .v {{ color: #fff; }}
    .cell.hl {{ background: var(--hl) !important; color: #fff !important; }}
    .cell.hl .v {{ color: #fff !important; }}
    .cell.empty {{ color: #ccc; cursor: default; }}
    tr.sep td {{ background: #f0f2f5; height: 6px; padding: 0; border-left: 0; border-right: 0; }}
    .panel {{
      margin: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 10px;
      background: #fff; display: none;
    }}
    .panel.show {{ display: block; }}
    .panel h3 {{ margin: 0 0 8px; font-size: 1rem; }}
    .panel table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    .panel th, .panel td {{ padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; }}
    .panel th {{ color: var(--muted); background: #fafafa; }}
    .up {{ color: var(--up); font-weight: 700; }}
    .down {{ color: var(--down); font-weight: 700; }}
    .note {{ margin: 10px 12px; color: var(--muted); font-size: 0.78rem; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar"><h1>板块轮动</h1></div>
    <div class="controls">
      <div class="tabs" id="kind-tabs">
        <button type="button" class="tab active" data-kind="行业">行业</button>
        <button type="button" class="tab" data-kind="概念">概念</button>
      </div>
      <select id="metric">
        <option value="涨幅">涨幅</option>
        <option value="涨停数">涨停数</option>
        <option value="资金">资金</option>
      </select>
      <select id="range" disabled>
        <option>前后10</option>
      </select>
      <select id="days" disabled>
        <option id="days-label">近5日</option>
      </select>
    </div>
    <div class="selected" id="selected">
      <span class="muted">点击格子选中板块，追踪轮动；再点可查看个股</span>
      <div class="actions">
        <button type="button" class="link" id="btn-stocks" hidden>查看个股</button>
        <button type="button" class="link" id="btn-clear" hidden>取消高亮</button>
      </div>
    </div>
    <div class="grid-wrap"><table class="heat" id="heat"></table></div>
    <div class="panel" id="stocks-panel">
      <h3 id="stocks-title">个股</h3>
      <div id="stocks-body"></div>
    </div>
    <p class="note" id="fund-note"></p>
    <p class="note">更新时间 {updated} · 行业历史=申万二级；概念历史=同花顺；今日均用东财实时补齐。</p>
  </div>
  <script type="application/json" id="rot-data">{data}</script>
  <script>
  (function () {{
    const raw = document.getElementById("rot-data").textContent;
    let DATA; try {{ DATA = JSON.parse(raw); }} catch (e) {{ return; }}
    const topN = DATA.top_n || 10;
    let kind = "行业";
    let metric = "涨幅";
    let selected = null;

    const heat = document.getElementById("heat");
    const selectedEl = document.getElementById("selected");
    const panel = document.getElementById("stocks-panel");
    const stocksBody = document.getElementById("stocks-body");
    const stocksTitle = document.getElementById("stocks-title");
    const daysLabel = document.getElementById("days-label");
    const fundNote = document.getElementById("fund-note");

    function fmtVal(metric, v) {{
      if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
      const x = Number(v);
      if (metric === "涨幅") return x.toFixed(2) + "%";
      if (metric === "涨停数") return String(Math.round(x));
      const abs = Math.abs(x);
      if (abs >= 1e8) return (x / 1e8).toFixed(2) + "亿";
      if (abs >= 1e4) return (x / 1e4).toFixed(1) + "万";
      return x.toFixed(0);
    }}
    function clsNum(v) {{
      const x = Number(v);
      if (!Number.isFinite(x) || x === 0) return "flat";
      return x > 0 ? "up" : "down";
    }}
    function cellClass(rank, isTop, name) {{
      let c = "cell";
      if (isTop && rank === 1) c += " r1";
      else if (isTop && rank === 2) c += " r2";
      else if (isTop && rank === 3) c += " r3";
      if (selected && name === selected) c += " hl";
      return c;
    }}

    function renderSelected() {{
      if (!selected) {{
        selectedEl.innerHTML =
          '<span style="color:var(--muted)">点击格子选中板块，追踪轮动；再点可查看个股</span>' +
          '<div class="actions"><button type="button" class="link" id="btn-stocks" hidden>查看个股</button>' +
          '<button type="button" class="link" id="btn-clear" hidden>取消高亮</button></div>';
        panel.classList.remove("show");
        return;
      }}
      const k = DATA.kinds[kind] || {{}};
      const by = (k.by_metric || {{}})[metric] || {{ top: [], bottom: [] }};
      let val = null;
      const tops = by.top || [];
      if (tops.length) {{
        (tops[0] || []).forEach(function (c) {{ if (c.name === selected) val = c.value; }});
        if (val === null) (by.bottom[0] || []).forEach(function (c) {{ if (c.name === selected) val = c.value; }});
      }}
      selectedEl.innerHTML =
        '<span>选中板块: <span class="name">' + selected + '</span> ' +
        '<span class="chg ' + clsNum(val) + '">' + fmtVal(metric, val) + '</span></span>' +
        '<div class="actions">' +
          '<button type="button" class="link" id="btn-stocks">查看个股</button>' +
          '<button type="button" class="link" id="btn-clear">取消高亮</button>' +
        '</div>';
      document.getElementById("btn-stocks").onclick = showStocks;
      document.getElementById("btn-clear").onclick = function () {{
        selected = null; render(); renderSelected();
      }};
    }}

    function showStocks() {{
      if (!selected) return;
      const members = ((DATA.kinds[kind] || {{}}).members || {{}})[selected] || [];
      stocksTitle.textContent = selected + " · 成分股";
      if (!members.length) {{
        stocksBody.innerHTML = '<p style="color:var(--muted)">暂无成分数据（可稍后重跑并开启成分缓存）</p>';
      }} else {{
        const rows = members.map(function (m) {{
          return "<tr><td>" + (m["代码"] || "") + "</td><td>" + (m["名称"] || "") +
            "</td><td>" + (m["现价"] == null ? "-" : Number(m["现价"]).toFixed(2)) +
            "</td><td class='" + clsNum(m["涨跌幅"]) + "'>" +
            (m["涨跌幅"] == null ? "-" : Number(m["涨跌幅"]).toFixed(2) + "%") +
            "</td><td>" + (m["换手率"] == null ? "-" : Number(m["换手率"]).toFixed(2)) +
            "</td></tr>";
        }}).join("");
        stocksBody.innerHTML = "<table><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>换手%</th></tr></thead><tbody>" +
          rows + "</tbody></table>";
      }}
      panel.classList.add("show");
      panel.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
    }}

    function pickCell(name) {{
      if (!name) return;
      if (selected === name) {{ showStocks(); return; }}
      selected = name;
      render();
      renderSelected();
    }}

    function render() {{
      const k = DATA.kinds[kind] || {{}};
      const dates = k.dates || [];
      const by = (k.by_metric || {{}})[metric] || {{ top: [], bottom: [] }};
      daysLabel.textContent = "近" + Math.max(dates.length, 1) + "日";
      fundNote.textContent = (k.fund_note || "") + " · " + kind + "共 " + (k.board_count || 0) + " 个板块";

      let html = "<thead><tr><th class='rank-h'></th>";
      dates.forEach(function (d) {{ html += "<th>" + d + "</th>"; }});
      html += "</tr></thead><tbody>";

      for (let r = 1; r <= topN; r++) {{
        html += "<tr><td class='rank'>" + r + "</td>";
        dates.forEach(function (_, di) {{
          const cell = ((by.top[di] || [])[r - 1]) || null;
          if (!cell) {{
            html += "<td><span class='cell empty'>-</span></td>";
            return;
          }}
          const cls = cellClass(cell.rank, true, cell.name);
          html += "<td><button type='button' class='" + cls + "' data-name='" + cell.name.replace(/'/g, "") +
            "'><span class='n'>" + cell.name +
            "</span><span class='v " + clsNum(cell.value) + "'>" + fmtVal(metric, cell.value) +
            "</span></button></td>";
        }});
        html += "</tr>";
      }}
      html += "<tr class='sep'><td colspan='" + (dates.length + 1) + "'></td></tr>";
      for (let i = 0; i < topN; i++) {{
        const rankLabel = topN - i;
        html += "<tr><td class='rank bot'>" + rankLabel + "</td>";
        dates.forEach(function (_, di) {{
          const cell = ((by.bottom[di] || [])[i]) || null;
          if (!cell) {{
            html += "<td><span class='cell empty'>-</span></td>";
            return;
          }}
          const cls = cellClass(cell.rank, false, cell.name);
          html += "<td><button type='button' class='" + cls + "' data-name='" + cell.name.replace(/'/g, "") +
            "'><span class='n'>" + cell.name +
            "</span><span class='v " + clsNum(cell.value) + "'>" + fmtVal(metric, cell.value) +
            "</span></button></td>";
        }});
        html += "</tr>";
      }}
      html += "</tbody>";
      heat.innerHTML = html;
      heat.querySelectorAll("button.cell").forEach(function (btn) {{
        btn.addEventListener("click", function () {{
          pickCell(btn.getAttribute("data-name"));
        }});
      }});
    }}

    document.getElementById("kind-tabs").addEventListener("click", function (ev) {{
      const btn = ev.target.closest(".tab");
      if (!btn) return;
      kind = btn.getAttribute("data-kind");
      document.querySelectorAll(".tab").forEach(function (t) {{
        t.classList.toggle("active", t === btn);
      }});
      selected = null;
      render();
      renderSelected();
    }});
    document.getElementById("metric").addEventListener("change", function (ev) {{
      metric = ev.target.value;
      render();
      renderSelected();
    }});

    render();
    renderSelected();
  }})();
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, html)
    return path
