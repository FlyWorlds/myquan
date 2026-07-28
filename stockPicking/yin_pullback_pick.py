"""阴线次日 · 冲高回落选股

规则：
  1. 昨天收阴：昨收 ≤ 昨开
  2. 今天冲高：最高 ≥ 昨收 × (1 + SURGE_PCT)（默认 2.5%）
  3. 较最高回落：回落% = (最高−现价)/最高×100
     输入 2 → ≥2%；输入 1-3 / 1~3 → [1%, 3%]
  4. 池子：沪深主板 A 股；排除创业板 / 科创板 / 北交所 / ST

数据：
  · 盘中：新浪全市场 spot（今开/高/低/现价/昨收）+ 日线补昨开验阴
  · 框架：akquant Strategy.on_cross_section 做日线横截面扫描（收盘价近似「回落现价」）

用法：
  python yin_pullback_pick.py              # 提示输入：2 或 1-3
  python yin_pullback_pick.py -p 2         # 较最高回落 ≥ 2%
  python yin_pullback_pick.py -p 1-3       # 较最高回落 1%～3%
  python yin_pullback_pick.py --demo
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parent
REPORT_CSV = ROOT / "yin_pullback_picks.csv"
REPORT_HTML = ROOT / "yin_pullback_report.html"

SURGE_PCT = 0.025  # 冲高相对昨收
# 较最高回落默认：至少 1%，无上限
PULLBACK_MIN_PCT = 1.0  # 百分点，如 1.0 = 1%
PULLBACK_MAX_PCT = None  # None = 不限上限


def _disable_proxy() -> None:
    """避免本机坏代理阻断行情请求。"""
    for k in list(os.environ):
        if "proxy" in k.lower():
            del os.environ[k]
    try:
        import requests

        _orig = requests.Session.request

        def _req(self: Any, *a: Any, **kw: Any) -> Any:
            self.trust_env = False
            return _orig(self, *a, **kw)

        requests.Session.request = _req  # type: ignore[method-assign]
    except Exception:
        pass


def _code6(raw: str) -> str:
    s = "".join(ch for ch in str(raw) if ch.isdigit())
    return s.zfill(6)[-6:]


def to_sina(code: str) -> str:
    c = _code6(code)
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    return f"sz{c}"


def is_main_board(code: str) -> bool:
    """沪深主板（含中小板 002）；排除创业/科创/北交。"""
    c = _code6(code)
    if c.startswith(("300", "301", "688", "689", "8", "4")):
        return False
    if c.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return True
    return False


def is_st_name(name: str) -> bool:
    n = str(name or "").upper().replace(" ", "")
    return "ST" in n or "退" in n


def match_intraday(
    *,
    open_px: float,
    high_px: float,
    last_px: float,
    prev_close: float,
    surge_pct: float = SURGE_PCT,
    pullback_min_pct: float = PULLBACK_MIN_PCT,
    pullback_max_pct: float | None = PULLBACK_MAX_PCT,
) -> dict[str, float] | None:
    """盘中条件（不含昨阴）：冲高 + 较最高回落带。

    回落% = (最高 − 现价) / 最高 × 100（现价动态，选股时取 spot 最新价）。
    须落在 [pullback_min_pct, pullback_max_pct]。
    """
    vals = (open_px, high_px, last_px, prev_close)
    if any((v is None) or (not isinstance(v, (int, float))) for v in vals):
        return None
    if any((float(v) <= 0) or (float(v) != float(v)) for v in vals):  # NaN check
        return None
    open_px, high_px, last_px, prev_close = map(float, vals)
    if last_px > high_px + 1e-12:
        return None
    surge = high_px / prev_close - 1.0
    dd_from_high = (high_px - last_px) / high_px * 100.0
    vs_open = (last_px / open_px - 1.0) * 100.0
    if surge + 1e-12 < surge_pct:
        return None
    if dd_from_high + 1e-12 < float(pullback_min_pct):
        return None
    if pullback_max_pct is not None and dd_from_high > float(pullback_max_pct) + 1e-12:
        return None
    return {
        "surge_pct": surge * 100.0,
        "dd_from_high_pct": dd_from_high,
        "vs_open_pct": vs_open,
    }


def fetch_spot() -> pd.DataFrame:
    """新浪 A 股实时行情。"""
    _disable_proxy()
    df = ak.stock_zh_a_spot()
    if df is None or df.empty:
        raise RuntimeError("新浪 spot 为空")
    need = ["代码", "名称", "最新价", "昨收", "今开", "最高", "最低"]
    for col in need:
        if col not in df.columns:
            raise RuntimeError(f"spot 缺列: {col}; 实际={list(df.columns)}")
    out = df[need].copy()
    for col in ("最新价", "昨收", "今开", "最高", "最低"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["最新价", "昨收", "今开", "最高"])
    return out


def fetch_prev_yin(sina: str) -> dict[str, Any] | None:
    """取上一完整交易日 OHLC，并判断是否阴线（新浪 K 线 JSON，可并行）。"""
    import requests

    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    params = {"symbol": sina, "scale": 240, "ma": "no", "datalen": 10}
    try:
        sess = requests.Session()
        sess.trust_env = False
        r = sess.get(
            url,
            params=params,
            timeout=12,
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        r.raise_for_status()
        rows = r.json()
    except Exception:
        return None
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    df = pd.DataFrame(rows)
    if not {"day", "open", "close"}.issubset(df.columns):
        return None
    df["day"] = pd.to_datetime(df["day"])
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "close"]).sort_values("day")
    if len(df) < 2:
        return None
    today = pd.Timestamp(date.today())
    last = df.iloc[-1]
    if pd.Timestamp(last["day"]).normalize() >= today:
        prev = df.iloc[-2]
    else:
        prev = last
    o = float(prev["open"])
    c = float(prev["close"])
    if o <= 0 or c <= 0:
        return None
    return {
        "prev_date": str(pd.Timestamp(prev["day"]).date()),
        "prev_open": o,
        "prev_close": c,
        "prev_yin": c <= o + 1e-12,
        "prev_chg_pct": (c / o - 1.0) * 100.0,
    }


def screen_live(
    *,
    surge_pct: float = SURGE_PCT,
    pullback_min_pct: float = PULLBACK_MIN_PCT,
    pullback_max_pct: float | None = PULLBACK_MAX_PCT,
    max_workers: int = 12,
) -> pd.DataFrame:
    """实时选股：spot 初筛 → 日线验昨阴。"""
    _disable_proxy()
    spot = fetch_spot()
    candidates: list[dict[str, Any]] = []
    for _, row in spot.iterrows():
        code_raw = str(row["代码"])
        name = str(row["名称"])
        if not is_main_board(code_raw) or is_st_name(name):
            continue
        open_px = float(row["今开"])
        high_px = float(row["最高"])
        last_px = float(row["最新价"])
        prev_close = float(row["昨收"])
        m = match_intraday(
            open_px=open_px,
            high_px=high_px,
            last_px=last_px,
            prev_close=prev_close,
            surge_pct=surge_pct,
            pullback_min_pct=pullback_min_pct,
            pullback_max_pct=pullback_max_pct,
        )
        if m is None:
            continue
        sina = to_sina(code_raw) if not code_raw.startswith(("sh", "sz")) else code_raw
        if not sina.startswith(("sh", "sz")):
            sina = to_sina(code_raw)
        candidates.append(
            {
                "代码": _code6(code_raw),
                "sina": sina,
                "名称": name,
                "今开": round(open_px, 3),
                "最高": round(high_px, 3),
                "最低": round(float(row["最低"]), 3) if pd.notna(row["最低"]) else None,
                "现价": round(last_px, 3),
                "昨收": round(prev_close, 3),
                "冲高%": round(m["surge_pct"], 2),
                "回落%": round(m["dd_from_high_pct"], 2),
                "较开盘%": round(m["vs_open_pct"], 2),
            }
        )

    if not candidates:
        return pd.DataFrame()

    print(f"盘中初筛 {len(candidates)} 只，校验昨阴…")
    picks: list[dict[str, Any]] = []

    def _job(item: dict[str, Any]) -> dict[str, Any] | None:
        info = fetch_prev_yin(item["sina"])
        if not info or not info["prev_yin"]:
            return None
        out = dict(item)
        out["昨开"] = round(info["prev_open"], 3)
        out["昨阴日"] = info["prev_date"]
        out["昨实体%"] = round(info["prev_chg_pct"], 2)
        out["冲高%(昨收核)"] = round(
            (float(item["最高"]) / float(info["prev_close"]) - 1.0) * 100.0, 2
        )
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_job, c): c for c in candidates}
        for fut in as_completed(futs):
            try:
                row = fut.result()
            except Exception:
                continue
            if row:
                picks.append(row)

    if not picks:
        return pd.DataFrame()
    df = pd.DataFrame(picks).sort_values(["回落%", "冲高%"], ascending=[True, False])
    return df.reset_index(drop=True)


def _pullback_label(lo: float, hi: float | None) -> str:
    if hi is None:
        return f"较最高回落≥{lo:g}%"
    return f"较最高回落[{lo:g}%, {hi:g}%]"


def write_html(
    df: pd.DataFrame,
    path: Path = REPORT_HTML,
    *,
    surge_pct: float = SURGE_PCT,
    pullback_min_pct: float = PULLBACK_MIN_PCT,
    pullback_max_pct: float | None = PULLBACK_MAX_PCT,
) -> Path:
    from html import escape

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pb = _pullback_label(pullback_min_pct, pullback_max_pct)
    default_hi = "" if pullback_max_pct is None else f"{pullback_max_pct:g}"

    cols = [
        "代码", "名称", "昨阴日", "昨开", "昨收", "今开", "最高", "最低", "现价",
        "冲高%", "回落%", "较开盘%", "昨实体%",
    ]
    show_cols = [c for c in cols if c in df.columns] if not df.empty else cols
    live_fields = {"最高", "最低", "现价", "冲高%", "回落%", "较开盘%"}

    def _cell(v: Any, col: str) -> str:
        if v is None or (isinstance(v, float) and v != v):
            txt = "-"
        elif col.endswith("%") and isinstance(v, (int, float)):
            txt = (
                f"{float(v):+.2f}"
                if col in ("较开盘%", "昨实体%")
                else f"{float(v):.2f}"
            )
        elif isinstance(v, float):
            txt = f"{v:.3f}"
        else:
            txt = escape(str(v))
        if col in live_fields:
            return f'<td data-field="{escape(col)}">{txt}</td>'
        return f"<td>{txt}</td>"

    if df.empty:
        body = '<p id="empty-msg">无符合条件标的。</p><table class="tbl" id="pick-table" hidden></table>'
    else:
        thead = "".join(
            f'<th title="回落%=(最高−现价)/最高，随现价刷新">{escape(c)}</th>'
            if c == "回落%"
            else f"<th>{escape(c)}</th>"
            for c in show_cols
        )
        rows_html: list[str] = []
        for _, r in df.iterrows():
            code = _code6(str(r.get("代码") or ""))
            sina = str(r.get("sina") or to_sina(code))
            high = float(r.get("最高") or 0)
            open_px = float(r.get("今开") or 0)
            prev = float(r.get("昨收") or 0)
            last = float(r.get("现价") or 0)
            dd = (high - last) / high * 100.0 if high > 0 else float(r.get("回落%") or 0)
            surge = (high / prev - 1.0) * 100.0 if prev > 0 else float(r.get("冲高%") or 0)
            vs_open = (last / open_px - 1.0) * 100.0 if open_px > 0 else float(r.get("较开盘%") or 0)
            tds = "".join(_cell(r.get(c), c) for c in show_cols)
            rows_html.append(
                "<tr "
                f'data-sina="{escape(sina)}" '
                f'data-open="{open_px:.6f}" '
                f'data-prev="{prev:.6f}" '
                f'data-high="{high:.6f}" '
                f'data-low="{float(r.get("最低") or high):.6f}" '
                f'data-last="{last:.6f}" '
                f'data-dd="{dd:.4f}" '
                f'data-surge="{surge:.4f}" '
                f'data-vsopen="{vs_open:.4f}"'
                f">{tds}</tr>"
            )
        body = f"""
  <div class="filters">
    <label>回落%(最高→现价) <input id="f-dd-lo" type="number" step="0.1" value="{pullback_min_pct:g}" placeholder="下限" /></label>
    <span class="sep">~</span>
    <label><input id="f-dd-hi" type="number" step="0.1" value="{escape(default_hi)}" placeholder="不限" /></label>
    <label>冲高%≥ <input id="f-surge" type="number" step="0.1" value="{surge_pct*100:g}" /></label>
    <label>较开盘% <input id="f-open-lo" type="number" step="0.1" placeholder="下限" /></label>
    <span class="sep">~</span>
    <label><input id="f-open-hi" type="number" step="0.1" placeholder="上限" /></label>
    <button type="button" id="btn-filter">过滤</button>
    <button type="button" id="btn-reset" class="ghost">重置</button>
    <button type="button" id="btn-refresh">刷新现价</button>
    <label class="auto"><input type="checkbox" id="f-auto" checked /> 每15秒自动刷新</label>
    <span class="count" id="filter-count">显示 {len(df)} / {len(df)}</span>
  </div>
  <p class="hint">回落% = (当日最高 − 现价) / 最高 × 100，现价/最高随行情动态更新后再按过滤条件筛。</p>
  <table class="tbl" id="pick-table">
    <thead><tr>{thead}</tr></thead>
    <tbody>
      {"".join(rows_html)}
    </tbody>
  </table>
  <p id="empty-msg" hidden>当前过滤无结果。</p>
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>阴线冲高回落选股</title>
<style>
  :root {{
    --ink: #14201a; --muted: #5c6f66; --line: #c9d6cf;
    --bg: #f4f7f5; --card: #fff; --accent: #1f6b4a;
  }}
  body {{ font-family: "IBM Plex Sans","Noto Sans SC",sans-serif; margin: 24px; background:var(--bg); color:var(--ink); }}
  h1 {{ font-size: 1.35rem; margin: 0 0 6px; }}
  .meta {{ color:var(--muted); margin-bottom: 8px; }}
  .hint {{ color:var(--muted); font-size: 0.88rem; margin: 0 0 12px; }}
  .filters {{
    display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center;
    margin-bottom: 10px; padding: 12px 14px; background: var(--card);
    border: 1px solid var(--line); border-radius: 8px;
  }}
  .filters label {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.9rem; color: var(--muted); }}
  .filters label.auto {{ margin-left: 4px; }}
  .filters input[type="number"] {{
    width: 72px; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px;
    font: inherit; color: var(--ink); background: #fafcfb;
  }}
  .filters .sep {{ color: var(--muted); }}
  .filters button {{
    border: 0; background: var(--accent); color: #fff; padding: 7px 14px;
    border-radius: 6px; font: inherit; font-weight: 600; cursor: pointer;
  }}
  .filters button:hover {{ filter: brightness(1.05); }}
  .filters button.ghost {{ background: transparent; color: var(--accent); border: 1px solid var(--line); }}
  .filters .count {{ margin-left: auto; font-size: 0.9rem; color: var(--muted); }}
  .tbl {{ border-collapse: collapse; width: 100%; background: var(--card); }}
  .tbl th, .tbl td {{ border-bottom: 1px solid #d5e0da; padding: 8px 10px; text-align: left; font-size: 0.92rem; }}
  .tbl th {{ background: #e8f0eb; position: sticky; top: 0; }}
  .tbl tr.hidden {{ display: none; }}
  .tbl td.flash {{ background: #e8f6ee; transition: background 0.8s; }}
  #live-ts {{ color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>
  <h1>阴线次日 · 冲高回落选股</h1>
  <p class="meta">昨阴 · 今高≥昨收×{surge_pct*100:g}% · {pb} · 主板非ST · 选股时刻 {now} · 共 <span id="total-n">{len(df)}</span> 只 · <span id="live-ts">现价未刷新</span></p>
  {body}
<script>
(function () {{
  const table = document.getElementById("pick-table");
  if (!table) return;
  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const emptyMsg = document.getElementById("empty-msg");
  const countEl = document.getElementById("filter-count");
  const liveTs = document.getElementById("live-ts");
  const total = rows.length;
  let timer = null;

  const num = (id) => {{
    const el = document.getElementById(id);
    if (!el) return null;
    const v = el.value.trim();
    if (v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }};

  function setField(tr, name, text) {{
    const td = tr.querySelector('td[data-field="' + name + '"]');
    if (!td) return;
    if (td.textContent !== text) {{
      td.textContent = text;
      td.classList.remove("flash");
      void td.offsetWidth;
      td.classList.add("flash");
    }}
  }}

  function recomputeRow(tr) {{
    const high = Number(tr.dataset.high);
    const low = Number(tr.dataset.low);
    const last = Number(tr.dataset.last);
    const open = Number(tr.dataset.open);
    const prev = Number(tr.dataset.prev);
    if (!(high > 0 && last > 0)) return;
    // 回落：最高 → 现价（动态）
    const dd = (high - last) / high * 100;
    const surge = prev > 0 ? (high / prev - 1) * 100 : Number(tr.dataset.surge);
    const vs = open > 0 ? (last / open - 1) * 100 : Number(tr.dataset.vsopen);
    tr.dataset.dd = String(dd);
    tr.dataset.surge = String(surge);
    tr.dataset.vsopen = String(vs);
    setField(tr, "最高", high.toFixed(3));
    setField(tr, "最低", low.toFixed(3));
    setField(tr, "现价", last.toFixed(3));
    setField(tr, "冲高%", surge.toFixed(2));
    setField(tr, "回落%", dd.toFixed(2));
    setField(tr, "较开盘%", (vs >= 0 ? "+" : "") + vs.toFixed(2));
  }}

  function applyFilter() {{
    const ddLo = num("f-dd-lo");
    const ddHi = num("f-dd-hi");
    const surgeMin = num("f-surge");
    const openLo = num("f-open-lo");
    const openHi = num("f-open-hi");
    let shown = 0;
    rows.forEach((tr) => {{
      const dd = Number(tr.dataset.dd);
      const surge = Number(tr.dataset.surge);
      const vs = Number(tr.dataset.vsopen);
      let ok = true;
      if (ddLo != null && dd < ddLo) ok = false;
      if (ddHi != null && dd > ddHi) ok = false;
      if (surgeMin != null && surge < surgeMin) ok = false;
      if (openLo != null && vs < openLo) ok = false;
      if (openHi != null && vs > openHi) ok = false;
      tr.classList.toggle("hidden", !ok);
      if (ok) shown += 1;
    }});
    if (countEl) countEl.textContent = "显示 " + shown + " / " + total;
    if (emptyMsg) emptyMsg.hidden = shown > 0;
    table.hidden = shown === 0;
  }}

  function resetFilter() {{
    const defaults = {{
      "f-dd-lo": "{pullback_min_pct:g}",
      "f-dd-hi": "{escape(default_hi)}",
      "f-surge": "{surge_pct*100:g}",
      "f-open-lo": "",
      "f-open-hi": "",
    }};
    Object.keys(defaults).forEach((id) => {{
      const el = document.getElementById(id);
      if (el) el.value = defaults[id];
    }});
    applyFilter();
  }}

  function applyQuotes() {{
    rows.forEach((tr) => {{
      const sina = tr.dataset.sina;
      const raw = window["hq_str_" + sina];
      if (!raw) return;
      const p = String(raw).split(",");
      // 1今开 2昨收 3现价 4最高 5最低
      const open = Number(p[1]);
      const prev = Number(p[2]);
      const last = Number(p[3]);
      const high = Number(p[4]);
      const low = Number(p[5]);
      if (!(last > 0)) return;
      if (open > 0) tr.dataset.open = String(open);
      if (prev > 0) tr.dataset.prev = String(prev);
      tr.dataset.last = String(last);
      if (high > 0) tr.dataset.high = String(Math.max(Number(tr.dataset.high) || 0, high));
      if (low > 0) {{
        const oldLow = Number(tr.dataset.low);
        tr.dataset.low = String(oldLow > 0 ? Math.min(oldLow, low) : low);
      }}
      recomputeRow(tr);
    }});
    if (liveTs) {{
      const t = new Date();
      liveTs.textContent = "现价刷新 " + t.toLocaleTimeString();
    }}
    applyFilter();
  }}

  function refreshQuotes() {{
    const sinas = rows.map((tr) => tr.dataset.sina).filter(Boolean);
    if (!sinas.length) return;
    const s = document.createElement("script");
    s.charset = "gbk";
    s.src = "https://hq.sinajs.cn/rn=" + Date.now() + "&list=" + sinas.join(",");
    s.onload = function () {{
      applyQuotes();
      s.remove();
    }};
    s.onerror = function () {{
      if (liveTs) liveTs.textContent = "现价刷新失败（可检查网络/跨域）";
      s.remove();
    }};
    document.body.appendChild(s);
  }}

  function syncAuto() {{
    if (timer) {{ clearInterval(timer); timer = null; }}
    const auto = document.getElementById("f-auto");
    if (auto && auto.checked) {{
      timer = setInterval(refreshQuotes, 15000);
    }}
  }}

  document.getElementById("btn-filter")?.addEventListener("click", applyFilter);
  document.getElementById("btn-reset")?.addEventListener("click", resetFilter);
  document.getElementById("btn-refresh")?.addEventListener("click", refreshQuotes);
  document.getElementById("f-auto")?.addEventListener("change", syncAuto);
  ["f-dd-lo","f-dd-hi","f-surge","f-open-lo","f-open-hi"].forEach((id) => {{
    document.getElementById(id)?.addEventListener("keydown", (e) => {{
      if (e.key === "Enter") applyFilter();
    }});
  }});

  // 打开页面先刷一次，并按勾选自动刷新
  refreshQuotes();
  syncAuto();
}})();
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# akquant 横截面：日线回放扫描（收盘价当作「回落现价」）
# ---------------------------------------------------------------------------


def run_akquant_demo(
    symbols: list[str] | None = None,
    start: str = "20260101",
    end: str | None = None,
) -> pd.DataFrame:
    """用 akquant Strategy.on_cross_section 在少量标的上演示同规则选股。"""
    import akquant as aq
    from akquant import Strategy
    from akquant.utils import fetch_akshare_symbol

    end = end or date.today().strftime("%Y%m%d")
    symbols = symbols or ["600000", "000001", "600519", "601318", "000858"]
    symbols = [to_sina(_code6(s)) for s in symbols]

    data: dict[str, pd.DataFrame] = {}
    for s in symbols:
        try:
            df = fetch_akshare_symbol(s, start, end, adjust="")
        except Exception as e:
            print(f"跳过 {s}: {e}")
            continue
        if df.empty:
            continue
        df = df.copy()
        df["symbol"] = s
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        data[s] = df
    if len(data) < 2:
        raise RuntimeError("可用标的不足，无法演示横截面")

    picks: list[dict[str, Any]] = []

    class YinPullbackScan(Strategy):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            self.universe = list(data.keys())
            self.warmup_period = 3

        def on_start(self) -> None:
            for s in self.universe:
                self.subscribe(s)

        def on_cross_section(self, trading_date: Any, timestamp: int) -> None:
            for s in self.universe:
                opens = self.get_history(count=2, symbol=s, field="open")
                highs = self.get_history(count=2, symbol=s, field="high")
                closes = self.get_history(count=2, symbol=s, field="close")
                if len(opens) < 2 or len(highs) < 2 or len(closes) < 2:
                    continue
                prev_o, today_o = float(opens[0]), float(opens[1])
                prev_c, today_c = float(closes[0]), float(closes[1])
                today_h = float(highs[1])
                if prev_c > prev_o + 1e-12:  # 昨非阴
                    continue
                m = match_intraday(
                    open_px=today_o,
                    high_px=today_h,
                    last_px=today_c,
                    prev_close=prev_c,
                )
                if m is None:
                    continue
                picks.append(
                    {
                        "日期": str(trading_date),
                        "代码": _code6(s),
                        "sina": s,
                        "今开": round(today_o, 3),
                        "最高": round(today_h, 3),
                        "收盘": round(today_c, 3),
                        "昨收": round(prev_c, 3),
                        "冲高%": round(m["surge_pct"], 2),
                        "回落%": round(m["dd_from_high_pct"], 2),
                        "较开盘%": round(m["vs_open_pct"], 2),
                    }
                )

    aq.run_backtest(
        data=data,
        strategy=YinPullbackScan,
        symbols=list(data.keys()),
        show_progress=False,
    )
    return pd.DataFrame(picks)


def _parse_pct_input(raw: str) -> float:
    """接受 1 / 1% / 1.5，一律按百分点（1 = 1%）。"""
    s = str(raw).strip().replace("%", "")
    if not s:
        raise ValueError("空输入")
    return float(s)


def parse_pullback_spec(raw: str) -> tuple[float, float | None]:
    """解析回落筛选。

    - ``2`` / ``2%`` → (≥2%, 不限)
    - ``1-3`` / ``1~3`` / ``1,3`` / ``1～3`` → [1%, 3%]
    """
    s = str(raw).strip().replace("%", "").replace(" ", "")
    if not s:
        raise ValueError("空输入")
    for sep in ("～", "~", "-", ",", "—", "至"):
        if sep in s:
            parts = [p for p in s.split(sep) if p != ""]
            if len(parts) != 2:
                raise ValueError(f"区间格式无效: {raw}（示例: 1-3）")
            lo = float(parts[0])
            hi = float(parts[1])
            if hi < lo:
                lo, hi = hi, lo
            return lo, hi
    return float(s), None


def _ask_pullback(
    default_min: float = PULLBACK_MIN_PCT,
) -> tuple[float, float | None]:
    """交互：输入 2（≥2%）或 1-3（区间）。"""
    raw = input(
        f"较最高回落？输入点数或区间（如 2 或 1-3）[回车=≥{default_min:g}%]: "
    ).strip()
    if not raw:
        return float(default_min), None
    return parse_pullback_spec(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="阴线次日冲高回落选股")
    parser.add_argument("--demo", action="store_true", help="akquant 横截面演示")
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--surge", type=float, default=SURGE_PCT, help="冲高阈值，默认0.025")
    parser.add_argument(
        "--pullback",
        "-p",
        type=str,
        default=None,
        help="回落筛选：2(=≥2%%) 或 1-3(=区间)；省略则交互询问",
    )
    parser.add_argument(
        "--pullback-max",
        type=float,
        default=None,
        help="可选：单独指定上限（与 -p 单值联用）；-p 已写区间时不必再传",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="不交互；未传 -p 时默认回落≥1%%",
    )
    args = parser.parse_args()

    if args.demo:
        print("akquant on_cross_section 演示…")
        df = run_akquant_demo()
        print(df.to_string(index=False) if not df.empty else "演示区间无命中")
        return

    try:
        if args.pullback is not None:
            pb_min, pb_max = parse_pullback_spec(str(args.pullback))
            if args.pullback_max is not None:
                # 单值 -p 时可再叠加上限；区间已被 -p 指定则以后者为准覆盖
                if pb_max is None:
                    pb_max = float(args.pullback_max)
                else:
                    pb_max = min(pb_max, float(args.pullback_max))
        elif args.no_prompt:
            pb_min = float(PULLBACK_MIN_PCT)
            pb_max = (
                None if args.pullback_max is None else float(args.pullback_max)
            )
        else:
            pb_min, pb_max = _ask_pullback()
            if args.pullback_max is not None and pb_max is None:
                pb_max = float(args.pullback_max)
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return
    except ValueError as e:
        print(f"输入无效: {e}")
        return

    if pb_max is not None and pb_max < pb_min:
        print(f"上限 {pb_max:g}% 小于下限 {pb_min:g}%")
        return

    print(
        f"选股条件：昨阴 · 今高≥昨收×{args.surge*100:g}% · "
        f"{_pullback_label(pb_min, pb_max)} · 主板非ST"
    )
    df = screen_live(
        surge_pct=float(args.surge),
        pullback_min_pct=pb_min,
        pullback_max_pct=pb_max,
        max_workers=args.max_workers,
    )
    if df.empty:
        print("无符合条件标的")
    else:
        cols = [
            "代码", "名称", "昨阴日", "昨开", "昨收", "今开", "最高", "现价",
            "冲高%", "回落%", "较开盘%", "昨实体%",
        ]
        show = [c for c in cols if c in df.columns]
        print(df[show].to_string(index=False))
        df.to_csv(REPORT_CSV, index=False, encoding="utf-8-sig")
        print(f"CSV -> {REPORT_CSV}")
    html = write_html(
        df,
        surge_pct=float(args.surge),
        pullback_min_pct=pb_min,
        pullback_max_pct=pb_max,
    )
    print(f"HTML -> {html}")


if __name__ == "__main__":
    main()
