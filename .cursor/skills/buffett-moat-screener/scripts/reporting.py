"""Offline validation artifacts for the Q44 portfolio feasibility study."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from collections.abc import Mapping as MappingABC

# Matplotlib is an optional reporting dependency.  Some supported runtimes
# ship NumPy 2 with a Matplotlib wheel compiled against NumPy 1; importing it
# at module load would then make screening and backtest APIs unusable.  Keep
# the data/report path importable and use the built-in SVG fallback below.
try:  # pragma: no cover - availability depends on the host runtime
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
except Exception:  # noqa: BLE001 - binary import failures vary by platform
    matplotlib = None
    plt = None

    class FontProperties:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

from .panda_adapter import canonical_json


def _repair_legacy_mojibake(value: str) -> str:
    """Repair legacy GBK/UTF-8 display corruption in report-only labels.

    Older artifacts contain Chinese literals that were decoded with the
    wrong Windows code page.  Repair only reversible CJK runs and leave
    replacement characters or non-Chinese data untouched.
    """
    import re

    gbk = "gbk"
    pattern = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef\u00b7\u2026\u2013\u2014]+")

    def convert(match: re.Match[str]) -> str:
        text = match.group(0)
        if "\ufffd" in text:
            return text
        try:
            decoded = text.encode(gbk).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
        return text if "\ufffd" in decoded else decoded

    return pattern.sub(convert, value)


def _parquet_safe(frame: pd.DataFrame) -> pd.DataFrame:
    safe = frame.copy()
    for column in safe.columns:
        values = safe[column].dropna()
        if values.map(lambda value: isinstance(value, (MappingABC, list, tuple))).any():
            safe[column] = safe[column].map(
                lambda value: canonical_json(list(value) if isinstance(value, tuple) else value)
                if isinstance(value, (MappingABC, list, tuple))
                else value
            )
    return safe


def _line_points(values: pd.Series, width: int = 920, height: int = 300) -> str:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return ""
    low, high = float(numeric.min()), float(numeric.max())
    span = high - low or 1.0
    count = max(len(numeric) - 1, 1)
    return " ".join(
        f"{index / count * width:.1f},{height - (float(value) - low) / span * height:.1f}"
        for index, value in enumerate(numeric)
    )


def _write_placeholder_png(path: Path) -> None:
    """Keep artifact contracts intact when optional plotting is unavailable."""
    import base64

    # 1x1 transparent PNG; the HTML still contains the data-backed SVG curve.
    payload = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    path.write_bytes(payload)


_STATUS_ZH = {
    "enter": "新建仓",
    "add": "加仓",
    "hold": "继续持有",
    "warning_hold": "警告后持有",
    "risk_trim": "风险修剪",
    "exit": "退出",
    "pending_exit": "等待退出",
    "research_candidate": "研究候选",
    "watchlist": "观察名单",
    "manual_review": "人工复核",
    "reject": "拒绝",
    "insufficient_data": "数据不足",
    "qualitative_pending": "定性审查待完成",
}

_REASON_ZH = {
    "two_consecutive_quality_warnings": "连续两次质量警告",
    "two_consecutive_data_warnings": "连续两次数据警告",
    "single_weight_above_30pct": "单只权重超过30%",
    "industry_weight_above_40pct": "行业权重超过40%",
    "high_threshold_opportunity_replacement": "高门槛机会替换",
    "quality_and_valuation_pass": "质量与估值同时通过",
    "qualitative_serious_red_flag": "定性审查发现严重红旗",
    "fundamental_exit": "基本面破坏退出",
}

_INDUSTRY_FALLBACK = {
    "000063.SZ": "通信",
    "000338.SZ": "汽车",
    "000786.SZ": "建筑材料",
    "002027.SZ": "传媒",
    "600332.SH": "医药生物",
    "600809.SH": "食品饮料",
    "601939.SH": "银行",
}


def _zh(value: Any, mapping: Mapping[str, str], fallback: str = "未记录") -> str:
    text = str(value) if value is not None else ""
    if not text or text.lower() in {"nan", "none", "unknown", "n/a"}:
        return fallback
    if "," in text:
        return "、".join(mapping.get(item, item) for item in text.split(","))
    return mapping.get(text, text)


def _evidence_zh(value: Any) -> str:
    return {
        "quantitative_retrospective_diagnostic": "量化回顾诊断",
        "retrospective_diagnostic": "回顾诊断",
        "sealed": "封存验证",
        "forward_validation": "前向验证",
        "supported": "支持",
        "mixed": "混合",
        "unsupported": "不支持",
    }.get(str(value), "未定义")


def _bool_zh(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    return {"true": "是", "false": "否"}.get(str(value).lower(), str(value))


def _disclaimer_zh(value: Any) -> str:
    text = str(value or "")
    if "Official evidence" in text or "Quantitative retrospective" in text:
        return "仅为量化回顾诊断，未回填官方文件证据和定性审查；不构成未来收益保证，也不是投资建议。"
    if "Historical evidence" in text:
        return "历史证据不代表未来收益，不构成收益保证，也不是投资建议。"
    return text or "本工具仅供研究，不构成投资建议。"


_REPORT_OVERRIDES = """
:root {
  --paper: #eef1ef;
  --surface: #ffffff;
  --ink: #20272a;
  --muted: #6d7778;
  --line: #dfe5e2;
  --red: #c94c3d;
  --teal: #14756a;
  --blue: #486e9c;
  --shadow: 0 16px 34px rgba(30, 43, 43, .08);
}
body { background: var(--paper); color: var(--ink); }
main { max-width: 1320px; padding: 30px 32px 72px; }
header {
  background: #20282b;
  color: #f8fbf9;
  border: 0;
  border-left: 6px solid var(--red);
  border-radius: 16px;
  padding: 28px 30px 30px;
  box-shadow: 0 18px 38px rgba(25, 33, 35, .18);
}
header h1 { color: #f8fbf9; font-size: clamp(30px, 4.2vw, 52px); letter-spacing: .01em; }
header h1 span:first-child { color: #f08a73; }
header h1 span:last-child { color: #f8fbf9; }
header .subtitle { color: #c7d2cf; max-width: 720px; }
header .stamp { color: #aebdb9; }
header .badge { border-radius: 999px; padding: 8px 12px; }
header .badge.diagnostic { background: #4c2e2b; color: #ffc5b8; }
header .badge.verified { background: #204d46; color: #bce9dc; }
.metrics { gap: 14px; margin-top: 18px; }
.metric {
  border: 0;
  border-radius: 14px;
  box-shadow: var(--shadow);
  padding: 18px 19px 17px;
  position: relative;
  overflow: hidden;
}
.metric::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--red); }
.metric:nth-child(2)::before { background: #d48c45; }
.metric:nth-child(3)::before { background: var(--teal); }
.metric:nth-child(4)::before { background: var(--blue); }
.metric strong { color: #1d2729; font-size: 28px; }
.section {
  margin-top: 20px;
  border: 0;
  border-radius: 14px;
  box-shadow: var(--shadow);
  padding: 26px;
}
.section-head { margin-bottom: 20px; }
h2 { color: #20282b; font-size: 21px; letter-spacing: .02em; }
.section-note { color: #7b8585; }
.insight-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 20px; }
.insight { background: #f7faf8; border: 1px solid #e1e9e5; border-radius: 11px; padding: 14px 16px; }
.insight span { display: block; color: #778180; font-size: 12px; }
.insight strong { display: block; margin-top: 6px; color: #20282b; font-size: 20px; }
.insight strong.latin { font-family: "Times New Roman", serif; }
.chart-wrap { background: #f8faf9; border: 1px solid #e3e9e6; border-radius: 12px; padding: 16px; }
.legend { margin-top: 15px; font-size: 12px; }
table { border-spacing: 0; }
th { color: #778180; font-size: 12px; letter-spacing: .03em; padding: 0 12px 12px; }
td { padding: 15px 12px; border-bottom: 1px solid #edf1ef; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: #f7faf8; }
td:first-child b { font-size: 15px; }
td:first-child small { margin-top: 3px; }
.status { padding: 5px 10px; font-weight: 700; }
.callout { border-radius: 12px; padding: 17px 19px; }
.exit-list li { padding: 14px 0; }
footer { color: #788281; max-width: 940px; }
@media (max-width: 820px) {
  main { padding: 18px 14px 46px; }
  header { padding: 23px 20px 24px; border-radius: 13px; }
  .section { padding: 19px 16px; border-radius: 12px; }
  .metric { padding: 15px 16px; }
  .insight-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
"""


def _html_report(result: Mapping[str, Any], nav: pd.DataFrame) -> str:
    palette = {
        "strategy_nav": "#c04436",
        "benchmark_000985_nav": "#16796b",
        "benchmark_510300_nav": "#4d6f9f",
        "cash_511880_nav": "#7b8490",
    }
    labels = {
        "strategy_nav": '<span class="latin">Q44</span> 策略',
        "benchmark_000985_nav": '<span class="latin">000985.SH</span>',
        "benchmark_510300_nav": '<span class="latin">510300.SH</span>',
        "cash_511880_nav": '<span class="latin">511880.SH</span> 现金',
    }
    lines = []
    for column, color in palette.items():
        if column in nav:
            lines.append(
                f'<polyline points="{_line_points(nav[column], width=960, height=330)}" fill="none" stroke="{color}" stroke-width="{3 if column == "strategy_nav" else 1.8}" stroke-linecap="round" stroke-linejoin="round" />'
            )
    legend = "".join(
        f'<span class="legend"><i style="background:{color}"></i>{labels[column]}</span>'
        for column, color in palette.items() if column in nav
    )

    def _num(value: Any, fallback: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    full = result.get("periods", {}).get("full", {})
    strategy_metrics = full.get("strategy", full.get("strategy_nav", {}))
    benchmark_metrics = full.get("benchmark_000985", full.get("benchmark_510300", full.get("benchmark_510300_nav", {})))
    actual_cash_weight = result.get("current_actual_cash_weight")
    if actual_cash_weight is None:
        actual_cash_weight = result.get("current_cash_weight")
    metric_cards = "".join(
        f'<div class="metric"><span>{title}</span><strong class="latin">{value}</strong><small>{note}</small></div>'
        for title, value, note in (
            ("策略年化复合收益", f"{_num(strategy_metrics.get('cagr')):.2%}", "完整诊断区间"),
            ("最大回撤", f"{_num(strategy_metrics.get('max_drawdown')):.2%}", "峰值到谷值"),
            ("基准年化复合收益", f"{_num(benchmark_metrics.get('cagr')):.2%}", '<span class="latin">000985.SH</span> 主基准'),
            ("现金权重", f"{_num(actual_cash_weight):.1%}", "当前实际状态"),
        )
    )
    holding_rows = []
    display_holdings = result.get("current_actual_holdings") or result.get("current_holdings", [])
    for row in display_holdings:
        evidence_metrics = ((row.get("evidence") or {}).get("metrics") or {})
        owner_ratio = evidence_metrics.get("owner_earnings_positive_year_ratio")
        owner_ratio_text = "--" if owner_ratio is None else f"{_num(owner_ratio):.0%}"
        holding_rows.append(
            "<tr><td><b class=\"latin\">{}</b><small>{}</small></td><td><b class=\"latin\">{:.1%}</b></td><td class=\"latin\">{:.1%}</td><td class=\"latin\">{}</td><td class=\"latin\">{}</td><td class=\"latin\">{}</td><td><span class=\"status\">{}</span></td></tr>".format(
                html.escape(str(row.get("target_id", ""))),
                html.escape(str(row.get("industry", "")) if str(row.get("industry", "")).strip() and "?" not in str(row.get("industry", "")) else _INDUSTRY_FALLBACK.get(str(row.get("target_id", "")), "")),
                _num(row.get("actual_weight", row.get("target_weight", row.get("policy_weight")))),
                _num(row.get("policy_weight", row.get("target_weight"))),
                html.escape(f"{_num(row.get('quality_score')):.1f}" if row.get("quality_score") is not None else "--"),
                html.escape(str(row.get("holding_since", "--"))),
                html.escape(owner_ratio_text),
                html.escape(_zh(row.get("review_action", "hold"), _STATUS_ZH, "未记录")),
            )
        )
    holdings = "".join(holding_rows) or '<tr><td colspan="7" class="empty">本次运行没有通过审查的持仓。</td></tr>'
    attribution = result.get("attribution", {})
    contribution_rows = "".join(
        "<tr><td class=\"latin\">{}</td><td class=\"contribution {} latin\">{:.2%}</td></tr>".format(
            html.escape(str(symbol)), "positive" if _num(value) >= 0 else "negative", _num(value)
        )
        for symbol, value in sorted(dict(attribution.get("stock_contributions", {})).items(), key=lambda item: item[1], reverse=True)
    ) or '<tr><td colspan="2" class="empty">暂无收益贡献数据。</td></tr>'
    sell_rows = "".join(
        "<li><b class=\"latin\">{}</b><span>{}</span></li>".format(html.escape(str(item.get("target_id", ""))), html.escape(_zh(item.get("reason", ""), _REASON_ZH, "未记录")))
        for item in attribution.get("sell_reasons", [])
    ) or "<li><span>诊断区间内没有记录退出。</span></li>"
    attribution_scope = result.get("attribution_scope", {}) or {}
    relative_cagr = _num(strategy_metrics.get("cagr")) - _num(benchmark_metrics.get("cagr"))
    insight_strip = "".join(
        f'<div class="insight"><span>{label}</span><strong class="latin">{value}</strong></div>'
        for label, value in (
            ("相对主基准年化差", f"{relative_cagr:+.2%}"),
            ("当前持仓数量", str(len(display_holdings))),
            ("诊断区间退出数", str(len(attribution.get("sell_reasons", [])))),
            ("现金收益贡献", f"{_num(attribution.get('cash_contribution')):.2%}"),
            ("最大单股贡献占比", f"{_num(attribution_scope.get('top_stock_contribution_share')):.1%}"),
        )
    )
    coverage_summary = result.get("coverage_summary", {}) or {}
    price_failure_count = len(coverage_summary.get("price_window_failures", []) or [])
    insight_strip += (
        f'<div class="insight"><span>价格窗口失败批次</span>'
        f'<strong class="latin">{price_failure_count}</strong></div>'
    )
    audit_backtested = bool(result.get("audit_gate_backtested", False))
    insight_strip += (
        f'<div class="insight"><span>历史审计门禁</span>'
        f'<strong>{"已回测" if audit_backtested else "未回测"}</strong></div>'
    )
    equity_only = result.get("equity_only_sensitivity", {}) or {}
    insight_strip += (
        f'<div class="insight"><span>收益主导来源</span>'
        f'<strong>{"现金" if attribution_scope.get("cash_dominates") else "股票或混合"}</strong></div>'
    )
    disclaimer = html.escape(_disclaimer_zh(result.get("disclaimer", "")))
    evidence_scope = _evidence_zh(result.get("evidence_scope", result.get("economic_evidence", "unknown")))
    gate = bool(result.get("qualitative_gate_backtested", False))
    status_class = "verified" if gate else "diagnostic"
    status_text = "定性审查已通过" if gate else "量化诊断·未应用定性门禁"
    report = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>Q44 · 巴菲特式 A 股研究</title>
<style>
:root{{--ink:#20262d;--muted:#66717c;--line:#dfe4e8;--paper:#f4f6f7;--surface:#fff;--red:#c04436;--teal:#16796b;--blue:#4d6f9f;--shadow:0 12px 28px rgba(28,39,48,.08)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:"SimSun","宋体",serif;font-size:15px;line-height:1.5}}.latin{{font-family:"Times New Roman",serif;font-variant-numeric:normal}}main{{max-width:1240px;margin:0 auto;padding:34px 28px 64px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;padding:18px 0 30px;border-bottom:1px solid var(--line)}}h1,h2,p{{margin:0}}h1{{font-size:clamp(28px,4vw,48px);line-height:1.05;max-width:720px}}h1 span{{color:var(--red)}}.subtitle{{color:var(--muted);margin-top:12px;max-width:680px}}.stamp{{font-size:12px;color:var(--muted);text-align:right;white-space:nowrap}}.badge{{display:inline-flex;align-items:center;padding:7px 10px;border-radius:999px;font-size:12px;font-weight:700}}.badge.diagnostic{{background:#fff0ed;color:#9b3329}}.badge.verified{{background:#e4f4ef;color:#126253}}.section{{margin-top:24px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow);border-radius:12px;padding:24px}}.section-head{{display:flex;justify-content:space-between;align-items:baseline;gap:16px;margin-bottom:18px}}h2{{font-size:20px}}.section-note{{font-size:12px;color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:24px}}.metric{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 17px}}.metric span,.metric small{{display:block;color:var(--muted);font-size:12px}}.metric strong{{display:block;font-size:25px;line-height:1.2;margin:8px 0 4px}}.chart-wrap{{background:#fbfcfc;border:1px solid var(--line);border-radius:10px;padding:12px}}svg{{display:block;width:100%;height:auto}}.legend{{display:inline-flex;align-items:center;gap:7px;margin:14px 18px 0 0;color:var(--muted);font-size:12px}}.legend i{{display:inline-block;width:22px;height:3px;border-radius:3px}}.grid-2{{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr);gap:24px}}table{{width:100%;border-collapse:collapse}}th{{font-size:12px;color:var(--muted);text-align:left;padding:0 10px 10px;border-bottom:1px solid var(--line)}}td{{padding:13px 10px;border-bottom:1px solid #edf0f2;vertical-align:middle}}td:first-child small{{display:block;color:var(--muted);font-size:12px}}.status{{display:inline-block;color:var(--teal);background:#e8f5f1;border-radius:999px;padding:4px 8px;font-size:12px}}.contribution{{font-weight:700}}.positive{{color:var(--teal)}}.negative{{color:var(--red)}}.empty{{color:var(--muted);text-align:center;padding:28px}}.exit-list{{list-style:none;padding:0;margin:0}}.exit-list li{{display:flex;justify-content:space-between;gap:18px;padding:12px 0;border-bottom:1px solid #edf0f2}}.exit-list li span{{color:var(--muted);text-align:right}}.callout{{border:1px solid #efc8c1;background:#fff8f6;border-radius:10px;padding:15px 17px;color:#6f3028}}.callout b{{display:block;margin-bottom:4px;color:#9b3329}}footer{{color:var(--muted);font-size:12px;margin-top:24px;max-width:820px}}@media(max-width:820px){{main{{padding:22px 16px 42px}}header{{display:block}}.stamp{{text-align:left;margin-top:18px}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.grid-2{{grid-template-columns:1fr}}.section{{padding:18px;overflow-x:auto}}table{{min-width:650px}}}}@media(max-width:480px){{.metrics{{grid-template-columns:1fr 1fr;gap:8px}}.metric strong{{font-size:21px}}.section{{border-radius:9px}}}}
</style></head>
<body><main>
<header><div><h1><span class="latin">Q44</span> <span>巴菲特式 <span class="latin">A</span> 股研究</span></h1><p class="subtitle">点时研究队列与长期持仓状态机：质量优先于价格，证据先于信念，机会不足时保留现金。</p></div><div class="stamp"><span class="badge {status_class}">{status_text}</span><br><br>数据版本 <span class="latin">{html.escape(str(result.get("data_version", "")))}</span><br>截至 <span class="latin">{html.escape(str(result.get("as_of_date", "")))}</span></div></header>
<div class="metrics">{metric_cards}</div>
<section class="section"><div class="section-head"><h2>策略曲线</h2><span class="section-note"><span class="latin">{html.escape(str(nav["date"].min() if "date" in nav and not nav.empty else ""))}</span> → <span class="latin">{html.escape(str(nav["date"].max() if "date" in nav and not nav.empty else ""))}</span> · {evidence_scope}</span></div><div class="chart-wrap"><svg viewBox="0 0 960 330" role="img" aria-label="策略与基准净值">{''.join(lines)}</svg>{legend}</div></section>
<div class="insight-grid">{insight_strip}</div>
<section class="section"><div class="section-head"><h2>目标状态</h2><span class="section-note">实际权重会随市场漂移，政策目标仅供复核</span></div><div class="callout"><b>{status_text}</b>{"历史回测不回填定性证据；这些目标仅是量化诊断，正式入场前仍需查阅官方文件。" if not gate else "本次复核中两个定性角色均通过证据门禁。"}</div><div style="height:14px"></div><table><thead><tr><th>股票代码 / 行业</th><th>实际权重</th><th>政策目标</th><th>质量分</th><th>持有起点</th><th>五年现金代理为正</th><th>复核动作</th></tr></thead><tbody>{holdings}</tbody></table><p style="margin-top:14px;color:var(--muted)">实际现金权重：<b class="latin">{_num(actual_cash_weight):.1%}</b> · 主要现金工具：<span class="latin">511880.SH</span> · 现金代理并非真实所有者收益。</p></section>
<div class="grid-2"><section class="section"><div class="section-head"><h2>收益贡献代理</h2><span class="section-note">股票与现金归因</span></div><table><thead><tr><th>股票代码</th><th>收益贡献</th></tr></thead><tbody>{contribution_rows}</tbody></table><p style="margin-top:14px;color:var(--muted)">现金贡献：<b class="latin">{_num(attribution.get("cash_contribution")):.2%}</b></p></section><section class="section"><div class="section-head"><h2>退出记录</h2><span class="section-note">状态机触发原因</span></div><ul class="exit-list">{sell_rows}</ul></section></div>
<section class="section"><div class="section-head"><h2>研究边界</h2><span class="section-note">解读曲线前请先阅读</span></div><p class="section-note" style="font-size:14px;color:var(--ink)">{disclaimer}</p></section>
<footer>独立研究工具，与沃伦·巴菲特或伯克希尔·哈撒韦无隶属关系。不生成交易指令。历史诊断不代表未来收益，不构成收益保证，也不是投资建议。</footer>
</main></body></html>"""
    report = report.replace("</style></head>", f"</style><style>{_REPORT_OVERRIDES}</style></head>")
    return _repair_legacy_mojibake(report)


def write_validation_artifacts(
    result: Mapping[str, Any], directory: str | Path
) -> dict[str, Path]:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    nav = pd.DataFrame(result.get("nav_curve", []))
    holdings = pd.DataFrame(result.get("holdings_history", []))
    rebalances = pd.DataFrame(result.get("rebalance_history", []))

    paths = {
        "nav": output / "nav.parquet",
        "holdings": output / "holdings_history.parquet",
        "rebalances": output / "rebalance_history.parquet",
        "cost_sensitivity": output / "cost_sensitivity.json",
        "lookahead_audit": output / "lookahead_audit.json",
        "lot_sensitivity": output / "lot_sensitivity_1m.json",
        "attribution": output / "attribution.json",
        "coverage_summary": output / "coverage_summary.json",
        "acceptance_report": output / "acceptance_report.md",
        "html_report": output / "validation_report.html",
        "preview": output / "strategy_curve.png",
        "portfolio_explanation": output / "portfolio_holdings.png",
    }
    _parquet_safe(nav).to_parquet(paths["nav"], index=False)
    _parquet_safe(holdings).to_parquet(paths["holdings"], index=False)
    _parquet_safe(rebalances).to_parquet(paths["rebalances"], index=False)
    paths["cost_sensitivity"].write_text(
        canonical_json(dict(result.get("cost_sensitivity_bps", {}))), encoding="utf-8"
    )
    paths["lookahead_audit"].write_text(
        canonical_json(dict(result.get("lookahead_audit", {}))), encoding="utf-8"
    )
    paths["lot_sensitivity"].write_text(
        canonical_json(list(result.get("lot_sensitivity_1m", []))), encoding="utf-8"
    )
    paths["attribution"].write_text(
        canonical_json(dict(result.get("attribution", {}))), encoding="utf-8"
    )
    paths["coverage_summary"].write_text(
        canonical_json(dict(result.get("coverage_summary", {}))), encoding="utf-8"
    )
    full = result.get("periods", {}).get("full", {})
    strategy = full.get("strategy", full.get("strategy_nav", {})) or {}
    benchmark = full.get("benchmark_000985", full.get("benchmark_510300", {})) or {}
    benchmark_secondary = full.get("benchmark_510300", {}) or {}
    diagnostic = result.get("periods", {}).get("retrospective_diagnostic", {}) or {}
    diagnostic_strategy = diagnostic.get("strategy", {}) or {}
    diagnostic_benchmark = diagnostic.get("benchmark_000985", {}) or {}
    diagnostic_secondary = diagnostic.get("benchmark_510300", {}) or {}
    coverage = result.get("coverage_summary", {}).get("latest", {}) or {}
    attribution_scope = result.get("attribution_scope", {}) or {}
    equity_only = result.get("equity_only_sensitivity", {}) or {}
    evidence_block = (
        "\n## 核心证据\n\n"
        f"- 实际净值起始日：`{result.get('start_date', '')}`\n"
        f"- 策略年化复合收益：`{float(strategy.get('cagr', 0.0)):.2%}`\n"
        f"- 中证全指年化复合收益：`{float(benchmark.get('cagr', 0.0)):.2%}`\n"
        f"- 沪深300辅助基准年化复合收益：`{float(benchmark_secondary.get('cagr', 0.0)):.2%}`\n"
        f"- 诊断期策略年化复合收益：`{float(diagnostic_strategy.get('cagr', 0.0)):.2%}`\n"
        f"- 诊断期中证全指年化复合收益：`{float(diagnostic_benchmark.get('cagr', 0.0)):.2%}`\n"
        f"- 诊断期沪深300年化复合收益：`{float(diagnostic_secondary.get('cagr', 0.0)):.2%}`\n"
        f"- 策略最大回撤：`{float(strategy.get('max_drawdown', 0.0)):.2%}`\n"
        f"- 当前现金实际权重：`{float(result.get('current_actual_cash_weight', result.get('current_cash_weight', 0.0))):.1%}`\n"
        f"- 股票收益贡献代理：`{float(attribution_scope.get('stock_contribution_total', 0.0)):.2%}`\n"
        f"- 现金收益贡献代理：`{float(attribution_scope.get('cash_contribution', 0.0)):.2%}`\n"
        f"- 最大单股收益贡献占比：`{float(attribution_scope.get('top_stock_contribution_share', 0.0)):.1%}`\n"
        f"- 集中度风险状态：`{'需研究' if attribution_scope.get('concentration_warning') else '未触发'}`\n"
        f"- 收益主导来源：`{'现金' if attribution_scope.get('cash_dominates') else '股票或混合'}`\n"
        f"- 股票腿纯投资反事实年化：`{float(equity_only.get('cagr', 0.0)):.2%}`\n"
        f"- 最新信号日研究候选：`{coverage.get('entry_eligible_count', 0)}`\n"
        "- 历史定性门禁：未回测；上述收益仅是量化回顾诊断。\n"
    )
    report = (
        "# Q44 V9 量化回顾诊断报告\n\n"
        f"- 数据版本：`{result.get('data_version')}`\n"
        f"- 回顾诊断结论：`{_evidence_zh(result.get('economic_evidence'))}（仅适用于冻结后的诊断期）`\n"
        f"- 证据范围：`{_evidence_zh(result.get('evidence_scope'))}`\n"
        f"- 验证级别：`{'已验证' if result.get('validation_level') == 'verified' else '可运行'}`\n"
        f"- 前向验证资格：`{_bool_zh(result.get('forward_validation', {}).get('eligible'))}`\n"
        f"- 点时审计：`{_bool_zh(result.get('lookahead_audit', {}).get('passed'))}`\n\n"
        "## 风险说明\n\n"
        f"{_disclaimer_zh(result.get('disclaimer', ''))}\n"
    )
    report = report + evidence_block
    paths["acceptance_report"].write_text(_repair_legacy_mojibake(report), encoding="utf-8")
    paths["html_report"].write_text(_html_report(result, nav), encoding="utf-8")

    if plt is None:
        _write_placeholder_png(paths["preview"])
        _write_placeholder_png(paths["portfolio_explanation"])
        return paths

    simsun = FontProperties(fname="C:/Windows/Fonts/simsun.ttc")
    times = FontProperties(fname="C:/Windows/Fonts/times.ttf")
    figure, axis = plt.subplots(figsize=(10, 5), dpi=150)
    for column, label in (
        ("strategy_nav", "Q44 策略"),
        ("benchmark_000985_nav", "000985.SH"),
        ("benchmark_510300_nav", "510300.SH"),
    ):
        if column in nav:
            axis.plot(pd.to_datetime(nav["date"], format="%Y%m%d"), nav[column], label=label)
    axis.set_title("Q44 巴菲特式 A 股策略验证", fontproperties=simsun)
    axis.set_ylabel("净值", fontproperties=simsun)
    axis.grid(alpha=0.2)
    axis.legend(prop=simsun, labels=["策略", "中证全指", "沪深300"])
    for tick in axis.get_xticklabels() + axis.get_yticklabels():
        tick.set_fontproperties(times)
    figure.tight_layout()
    figure.savefig(paths["preview"])
    plt.close(figure)
    holdings = list(result.get("current_actual_holdings") or result.get("current_holdings", []))
    figure, axis = plt.subplots(figsize=(10, 5), dpi=150)
    if holdings:
        labels = [f"{row.get('target_id', '')}\nQ{float(row.get('quality_score', 0)):.0f}" for row in holdings]
        values = [float(row.get("actual_weight", row.get("target_weight", row.get("policy_weight", 0)))) for row in holdings]
        bars = axis.bar(labels, values, color="#b3261e")
        axis.bar_label(bars, labels=[f"{value:.1%}" for value in values], padding=3)
        axis.set_ylim(0, max(values + [0.25]) * 1.25)
    else:
        axis.text(0.5, 0.5, "本次没有通过审查的持仓", ha="center", va="center", fontsize=18, fontproperties=simsun)
    axis.set_title("Q44 V9 量化诊断目标" if not result.get("qualitative_gate_backtested", True) else "Q44 V9 当前持仓与政策权重", fontproperties=simsun)
    axis.set_ylabel("实际权重", fontproperties=simsun)
    axis.grid(axis="y", alpha=0.2)
    for tick in axis.get_xticklabels() + axis.get_yticklabels():
        tick.set_fontproperties(times)
    figure.tight_layout()
    figure.savefig(paths["portfolio_explanation"])
    plt.close(figure)
    return paths
