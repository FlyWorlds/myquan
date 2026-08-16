#!/usr/bin/env python3
"""
DOCX report generator for skill-investment-decision.

Converts a validated report JSON into a formatted .docx file.
- Title page: company name, ticker, market, date (NO recommendation spoiler)
- Sections in build-up order; BUY/NEUTRAL/SELL decision revealed at the END
- Language: defaults to English (en), Chinese (zh) supported
- Color-coded recommendation (only in final section)
- Formatted tables + mandatory disclaimer

Usage: python generate_report.py --report <report.json> --output <output.docx> [--language en|zh]
"""

import json
import sys
import os
import argparse
import collections
from datetime import datetime

try:
    from docx import Document
    from docx.shared import Inches, Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
except ImportError:
    print("ERROR: python-docx is required. Install with: pip install python-docx",
          file=sys.stderr)
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# --- Color definitions ---
COLOR_BUY = RGBColor(0x00, 0x80, 0x00)       # Green
COLOR_NEUTRAL = RGBColor(0xCC, 0x88, 0x00)    # Amber/Yellow
COLOR_SELL = RGBColor(0xCC, 0x00, 0x00)       # Red
COLOR_HEADING = RGBColor(0x1A, 0x3C, 0x6E)    # Dark blue
COLOR_BODY = RGBColor(0x33, 0x33, 0x33)       # Dark gray

# --- Language packs ---
LANG = {
    "en": {
        "title_subtitle": "Investment Decision Report",
        "title_date": "Report Date",
        "section_company": "Company Overview",
        "section_financial": "Financial Analysis",
        "section_valuation": "Valuation Analysis",
        "section_sentiment": "Market & Sentiment Analysis",
        "section_risk": "Risk Assessment",
        "section_recommendation": "Long-Term Investment Decision",
        "section_disclaimer": "Disclaimer",
        "section_references": "Data Sources & References",
        "chart_price": "Monthly Closing Price History",
        "chart_monthly": "Monthly Returns (Last 12 Months)",
        "chart_yearly": "Annual Returns",
        "kv_name": "Company Name",
        "kv_ticker": "Ticker",
        "kv_market": "Market",
        "kv_industry": "Industry",
        "kv_listed": "Listed Date",
        "kv_headquarters": "Headquarters",
        "kv_revenue": "Revenue Trend (YoY)",
        "kv_profit": "Net Profit Trend (YoY)",
        "kv_roe": "ROE (TTM)",
        "kv_roa": "ROA (TTM)",
        "kv_gross_margin": "Gross Margin (TTM)",
        "kv_net_margin": "Net Margin (TTM)",
        "kv_de": "Debt / Equity (MRQ)",
        "kv_cf_quality": "Operating CF Quality (TTM)",
        "kv_pe": "PE (TTM)",
        "kv_pb": "PB (MRQ)",
        "kv_pe_1yr": "PE 1-Year Percentile",
        "kv_pe_3yr": "PE 3-Year Percentile",
        "kv_pe_5yr": "PE 5-Year Percentile",
        "kv_peg": "PEG Ratio (TTM)",
        "kv_return_1m": "1-Month Return",
        "kv_return_3m": "3-Month Return",
        "kv_return_6m": "6-Month Return",
        "kv_return_12m": "12-Month Return",
        "kv_volume": "Volume Trend (1Y vs Prior)",
        "kv_news": "News Sentiment (30-Day)",
        "risk_header_factor": "Risk Factor",
        "risk_header_level": "Level",
        "risk_header_mitigation": "Mitigation",
        "score_header_dim": "Dimension",
        "score_header_weight": "Weight",
        "score_header_score": "Score (1–10)",
        "score_header_rationale": "Rationale",
        "score_total": "TOTAL",
        "score_100pct": "100%",
        "rec_final": "Long-Term Decision (6–18 months)",
        "rec_confidence": "Confidence",
        "dim_financial": "Financial Health",
        "dim_growth": "Growth",
        "dim_valuation": "Valuation",
        "dim_momentum": "Momentum & Sentiment",
        "dim_industry": "Industry Position",
        "dim_risk": "Risk Profile",
        "default_disclaimer": (
            "This report is for research methodology purposes only and does not "
            "constitute any investment advice. Investment involves risk; decisions "
            "should be made with caution."
        ),
        "ref_disclaimer": "This report is AI-generated for research purposes only. Not financial advice.",
    },
    "zh": {
        "title_subtitle": "投资决策报告",
        "title_date": "报告日期",
        "section_company": "公司概览",
        "section_financial": "财务分析",
        "section_valuation": "估值分析",
        "section_sentiment": "市场与情绪分析",
        "section_risk": "风险评估",
        "section_recommendation": "长期投资决策",
        "section_disclaimer": "免责声明",
        "section_references": "数据来源与参考文献",
        "chart_price": "月度收盘价走势",
        "chart_monthly": "月度回报率（近12个月）",
        "chart_yearly": "年度回报率",
        "kv_name": "公司名称",
        "kv_ticker": "股票代码",
        "kv_market": "市场",
        "kv_industry": "行业",
        "kv_listed": "上市日期",
        "kv_headquarters": "总部所在地",
        "kv_revenue": "营收趋势（同比）",
        "kv_profit": "净利润趋势（同比）",
        "kv_roe": "ROE (TTM)",
        "kv_roa": "ROA (TTM)",
        "kv_gross_margin": "毛利率 (TTM)",
        "kv_net_margin": "净利率 (TTM)",
        "kv_de": "负债权益比 (MRQ)",
        "kv_cf_quality": "经营现金流质量 (TTM)",
        "kv_pe": "市盈率 (TTM)",
        "kv_pb": "市净率 (MRQ)",
        "kv_pe_1yr": "PE 1年分位",
        "kv_pe_3yr": "PE 3年分位",
        "kv_pe_5yr": "PE 5年分位",
        "kv_peg": "PEG比率 (TTM)",
        "kv_return_1m": "1月回报",
        "kv_return_3m": "3月回报",
        "kv_return_6m": "6月回报",
        "kv_return_12m": "12月回报",
        "kv_volume": "成交量趋势（1年对比）",
        "kv_news": "新闻舆情（30日）",
        "risk_header_factor": "风险因素",
        "risk_header_level": "级别",
        "risk_header_mitigation": "缓解因素",
        "score_header_dim": "维度",
        "score_header_weight": "权重",
        "score_header_score": "得分 (1–10)",
        "score_header_rationale": "理由",
        "score_total": "总计",
        "score_100pct": "100%",
        "rec_final": "长期投资决策（6–18个月）",
        "rec_confidence": "置信度",
        "dim_financial": "财务健康",
        "dim_growth": "成长性",
        "dim_valuation": "估值",
        "dim_momentum": "动量与情绪",
        "dim_industry": "行业地位",
        "dim_risk": "风险状况",
        "default_disclaimer": (
            "本报告仅作研究方法层面的整理与展示，不构成任何投资建议。"
            "投资有风险，决策须谨慎。"
        ),
        "ref_disclaimer": "本报告由AI生成，仅供研究参考，不构成投资建议。",
    },
}


def get_rec_color(recommendation: str) -> RGBColor:
    """Return color for recommendation."""
    rec = recommendation.upper().strip()
    if rec == "BUY":
        return COLOR_BUY
    elif rec == "SELL":
        return COLOR_SELL
    return COLOR_NEUTRAL


def set_cell_shading(cell, color_hex: str):
    """Set cell background color."""
    shading_elm = OxmlElement("w:shd")
    shading_elm.set(qn("w:fill"), color_hex)
    shading_elm.set(qn("w:val"), "clear")
    cell._tc.get_or_add_tcPr().append(shading_elm)


def add_styled_paragraph(doc, text: str, style: str = "Normal",
                         bold: bool = False, color: RGBColor = None,
                         size: Pt = None, alignment=None):
    """Add a paragraph with optional styling."""
    para = doc.add_paragraph(style=style)
    run = para.add_run(text)
    if bold:
        run.bold = True
    if color:
        run.font.color.rgb = color
    if size:
        run.font.size = size
    if alignment is not None:
        para.alignment = alignment
    return para


# --- Chart generation ---

def _make_price_chart(price_data: dict, ticker: str, chart_dir: str, t: dict) -> str:
    """Generate a modern monthly closing price chart with gradient fill."""
    if not HAS_MATPLOTLIB or not price_data.get("dates"):
        return ""
    dates = price_data["dates"]
    closes = price_data["closes"]
    if len(dates) < 3:
        return ""

    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    x = range(len(dates))
    
    # Gradient fill under the line
    color_main = '#2563EB'
    ax.plot(x, closes, color=color_main, linewidth=1.8, zorder=3)
    ax.fill_between(x, closes, min(closes) * 0.95, alpha=0.08, color=color_main)
    
    # Add subtle dots at data points
    step = max(1, len(dates) // 30)
    ax.scatter(x[::step], closes[::step], color=color_main, s=6, zorder=4, alpha=0.5)
    
    ax.set_title(t.get("chart_price", "Monthly Closing Price History"), fontsize=11, fontweight='600', color='#1E293B', pad=10)
    
    # Clean x-axis
    tick_step = max(1, len(dates) // 6)
    tick_pos = list(range(0, len(dates), tick_step))
    tick_labels = [dates[i] for i in tick_pos]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels, fontsize=7, color='#64748B')
    ax.set_xlim(-1, len(dates))
    
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'\${x:,.0f}'))
    ax.tick_params(axis='y', labelsize=7, colors='#64748B')
    ax.grid(True, alpha=0.3, color='#CBD5E1')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#E2E8F0')
    ax.spines['bottom'].set_color('#E2E8F0')
    
    fig.tight_layout()
    path = os.path.join(chart_dir, f"{ticker}_price.png")
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def _make_returns_chart(sent: dict, ticker: str, chart_dir: str, t: dict) -> str:
    """REMOVED — data is in the table."""
    return ""


def _make_monthly_returns_chart(mr_data: dict, ticker: str, chart_dir: str, t: dict) -> str:
    """Generate a modern 12-month individual monthly returns bar chart."""
    if not HAS_MATPLOTLIB or not mr_data.get("labels"):
        return ""
    labels = mr_data["labels"]
    values = mr_data["values"]
    if len(labels) < 2:
        return ""

    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(7.5, 2.8))
    colors = ['#059669' if v >= 0 else '#DC2626' for v in values]
    bars = ax.bar(range(len(labels)), values, color=colors, width=0.55, edgecolor='white', linewidth=0.3)
    ax.axhline(y=0, color='#94A3B8', linewidth=0.8, zorder=2)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7, color='#64748B')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f'{y:.0%}'))
    ax.tick_params(axis='y', labelsize=7, colors='#64748B')
    ax.set_title(t.get("chart_monthly", "Monthly Returns"), fontsize=11, fontweight='600', color='#1E293B', pad=10)
    ax.grid(True, alpha=0.3, color='#CBD5E1', axis='y')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#E2E8F0')
    ax.spines['bottom'].set_color('#E2E8F0')
    for bar, v in zip(bars, values):
        offset = 0.015 if v >= 0 else -0.025
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                f'{v:.1%}', ha='center', fontsize=6, fontweight='600',
                color='#059669' if v >= 0 else '#DC2626')
    fig.tight_layout()
    path = os.path.join(chart_dir, f"{ticker}_monthly.png")
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def _make_yearly_returns_chart(yr_data: dict, ticker: str, chart_dir: str, t: dict) -> str:
    """Generate a modern 5-year annual returns bar chart."""
    if not HAS_MATPLOTLIB or not yr_data.get("labels"):
        return ""
    labels = yr_data["labels"]
    values = yr_data["values"]
    if len(labels) < 1:
        return ""

    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(6, 2.6))
    colors = ['#059669' if v >= 0 else '#DC2626' for v in values]
    bars = ax.bar(range(len(labels)), values, color=colors, width=0.45, edgecolor='white', linewidth=0.3)
    ax.axhline(y=0, color='#94A3B8', linewidth=0.8, zorder=2)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8, color='#64748B')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f'{y:.0%}'))
    ax.tick_params(axis='y', labelsize=7, colors='#64748B')
    ax.set_title(t.get("chart_yearly", "Annual Returns"), fontsize=11, fontweight='600', color='#1E293B', pad=10)
    ax.grid(True, alpha=0.3, color='#CBD5E1', axis='y')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#E2E8F0')
    ax.spines['bottom'].set_color('#E2E8F0')
    for bar, v in zip(bars, values):
        offset = 0.025 if v >= 0 else -0.04
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                f'{v:.1%}', ha='center', fontsize=8, fontweight='600',
                color='#059669' if v >= 0 else '#DC2626')
    fig.tight_layout()
    path = os.path.join(chart_dir, f"{ticker}_yearly.png")
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def build_title_page(doc, report: dict, t: dict):
    """Build a clean title page — NO recommendation spoiler."""
    for _ in range(7):
        doc.add_paragraph()

    meta = report.get("meta", {})

    # Company name
    company = meta.get("company_name", "Unknown")
    add_styled_paragraph(doc, company, bold=True, size=Pt(28),
                         color=COLOR_HEADING,
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)

    # Ticker
    ticker = meta.get("ticker", "N/A")
    market = meta.get("market", "")
    ticker_line = f"{ticker}" + (f"  ·  {market.upper()}" if market else "")
    add_styled_paragraph(doc, ticker_line, size=Pt(14),
                         color=COLOR_BODY,
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()
    doc.add_paragraph()

    # Subtitle
    add_styled_paragraph(doc, t["title_subtitle"], size=Pt(16),
                         color=COLOR_HEADING,
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()

    # Date
    report_date = meta.get("report_date", datetime.now().strftime("%Y-%m-%d"))
    add_styled_paragraph(doc, f"{t['title_date']}: {report_date}",
                         size=Pt(12), color=COLOR_BODY,
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_page_break()


def build_section_heading(doc, number: int, title: str):
    """Add a numbered section heading."""
    heading_text = f"{number}. {title}"
    add_styled_paragraph(doc, heading_text, bold=True, size=Pt(16),
                         color=COLOR_HEADING)
    doc.add_paragraph()


def build_key_value_table(doc, data: dict):
    """Build a key-value table from a dict with consistent 10pt font."""
    table = doc.add_table(rows=len(data), cols=2, style="Light Grid Accent 1")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (key, value) in enumerate(data.items()):
        kc = table.cell(i, 0)
        kc.text = ""
        kr = kc.paragraphs[0].add_run(str(key))
        kr.bold = True
        kr.font.size = Pt(10)
        vc = table.cell(i, 1)
        vc.text = ""
        vr = vc.paragraphs[0].add_run(str(value) if value is not None else "—")
        vr.font.size = Pt(10)
    doc.add_paragraph()


# --- Section builders (ordered: 1=Overview, 2=Financial, 3=Valuation, 4=Sentiment, 5=Risk, 6=Decision, 7=Disclaimer) ---

def build_company_overview(doc, overview: dict, meta: dict, t: dict):
    """Section 1: Company Overview."""
    build_section_heading(doc, 1, t["section_company"])

    # Business description as a text paragraph (not in table)
    biz_desc = overview.get("business_description", "")
    if biz_desc and biz_desc != "N/A" and len(biz_desc) > 10:
        add_styled_paragraph(doc, biz_desc, size=Pt(10), color=COLOR_BODY)
        doc.add_paragraph()

    data = collections.OrderedDict([
        (t["kv_name"], meta.get("company_name", "—")),
        (t["kv_ticker"], meta.get("ticker", "—")),
        (t["kv_market"], meta.get("market", "—")),
        (t["kv_industry"], overview.get("industry", "—")),
        (t["kv_listed"], overview.get("listed_date", "—")),
        (t["kv_headquarters"], overview.get("headquarters", "—")),
    ])
    build_key_value_table(doc, data)


def build_financial_analysis(doc, fin: dict, t: dict):
    """Section 2: Financial Analysis — FIXED fields, always the same."""
    build_section_heading(doc, 2, t["section_financial"])
    data = collections.OrderedDict([
        (t["kv_revenue"], fin.get("revenue_trend", "—")),
        (t["kv_profit"], fin.get("net_profit_trend", "—")),
        (t["kv_roe"], f"{fin['roe']:.2%}" if fin.get('roe') is not None else "Negative"),
        (t["kv_roa"], f"{fin['roa']:.2%}" if fin.get('roa') is not None else "Negative"),
        (t["kv_gross_margin"], f"{fin['gross_margin']:.2%}" if fin.get('gross_margin') is not None else "—"),
        (t["kv_net_margin"], f"{fin['net_margin']:.2%}" if fin.get('net_margin') is not None else "—"),
        (t["kv_de"], f"{fin['debt_to_equity']:.4f}" if fin.get('debt_to_equity') is not None else "—"),
        (t["kv_cf_quality"], fin.get("operating_cf_quality", "—")),
    ])
    build_key_value_table(doc, data)


def build_valuation_analysis(doc, val: dict, t: dict):
    """Section 3: Valuation Analysis — FIXED fields, always the same."""
    build_section_heading(doc, 3, t["section_valuation"])
    pe_val = f"{val['pe_ttm']:.2f}" if val.get('pe_ttm') is not None else "Neg. Earnings"
    peg_val = f"{val['peg_ratio']:.2f}" if val.get('peg_ratio') is not None else "Neg. Earnings"
    pb_val = f"{val['pb']:.2f}" if val.get('pb') is not None else "—"
    p1_val = f"{val['pe_percentile_1yr']:.0%}" if val.get('pe_percentile_1yr') is not None else "—"
    p3_val = f"{val['pe_percentile_3yr']:.0%}" if val.get('pe_percentile_3yr') is not None else "—"
    p5_val = f"{val['pe_percentile_5yr']:.0%}" if val.get('pe_percentile_5yr') is not None else "—"
    evr_val = f"{val['ev_to_revenue']:.2f}x" if val.get('ev_to_revenue') is not None else "—"
    eve_val = f"{val['ev_to_ebitda']:.1f}x" if val.get('ev_to_ebitda') is not None else "—"
    data = collections.OrderedDict([
        (t["kv_pe"], pe_val),
        (t["kv_pb"], pb_val),
        ("EV / Revenue", evr_val),
        ("EV / EBITDA", eve_val),
        (t["kv_peg"], peg_val),
        (t["kv_pe_1yr"], p1_val),
        (t["kv_pe_3yr"], p3_val),
        (t["kv_pe_5yr"], p5_val),
    ])
    build_key_value_table(doc, data)


def build_market_sentiment(doc, sent: dict, t: dict):
    """Section 4: Market & Sentiment — FIXED fields, always the same."""
    build_section_heading(doc, 4, t["section_sentiment"])
    r1 = f"{sent['return_1m']:.2%}" if sent.get('return_1m') is not None else "—"
    r3 = f"{sent['return_3m']:.2%}" if sent.get('return_3m') is not None else "—"
    r6 = f"{sent['return_6m']:.2%}" if sent.get('return_6m') is not None else "—"
    r12 = f"{sent['return_12m']:.2%}" if sent.get('return_12m') is not None else "—"
    data = collections.OrderedDict([
        (t["kv_return_1m"], r1),
        (t["kv_return_3m"], r3),
        (t["kv_return_6m"], r6),
        (t["kv_return_12m"], r12),
        (t["kv_volume"], sent.get("volume_trend", "—")),
        (t["kv_news"], sent.get("news_sentiment", "—")),
    ])
    build_key_value_table(doc, data)


def build_risk_assessment(doc, risk: dict, t: dict):
    """Section 5: Risk Assessment."""
    build_section_heading(doc, 5, t["section_risk"])

    risks = risk.get("risks", [])
    table = doc.add_table(rows=len(risks) + 1, cols=3, style="Light Grid Accent 1")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    headers = [t["risk_header_factor"], t["risk_header_level"], t["risk_header_mitigation"]]
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True

    for i, r in enumerate(risks):
        table.cell(i + 1, 0).text = r.get("factor", "")
        level = r.get("level", "")
        table.cell(i + 1, 1).text = level
        table.cell(i + 1, 2).text = r.get("mitigation", "")

        if level == "High":
            set_cell_shading(table.cell(i + 1, 1), "FFCCCC")
        elif level == "Medium":
            set_cell_shading(table.cell(i + 1, 1), "FFF3CD")
        else:
            set_cell_shading(table.cell(i + 1, 1), "D4EDDA")

    doc.add_paragraph()


def build_recommendation(doc, rec_data: dict, t: dict):
    """Section 6: Investment Decision — THE DECISION IS HERE, AT THE END."""
    build_section_heading(doc, 6, t["section_recommendation"])

    scores = rec_data.get("scores", {})

    # Scoring table
    table = doc.add_table(rows=len(scores) + 2, cols=4, style="Light Grid Accent 1")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    headers = [t["score_header_dim"], t["score_header_weight"],
               t["score_header_score"], t["score_header_rationale"]]
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(10)

    weights = {
        "financial_health": "20%",
        "growth": "20%",
        "valuation": "20%",
        "momentum_sentiment": "15%",
        "industry_position": "10%",
        "risk_profile": "15%",
    }
    dim_labels = {
        "financial_health": t["dim_financial"],
        "growth": t["dim_growth"],
        "valuation": t["dim_valuation"],
        "momentum_sentiment": t["dim_momentum"],
        "industry_position": t["dim_industry"],
        "risk_profile": t["dim_risk"],
    }

    def _set_cell(cell, text, bold=False):
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(str(text))
        run.font.size = Pt(10)
        if bold:
            run.bold = True

    for i, dim in enumerate([
        "financial_health", "growth", "valuation",
        "momentum_sentiment", "industry_position", "risk_profile"
    ]):
        sd = scores.get(dim, {})
        _set_cell(table.cell(i + 1, 0), dim_labels.get(dim, dim), bold=True)
        _set_cell(table.cell(i + 1, 1), weights.get(dim, "N/A"))
        _set_cell(table.cell(i + 1, 2), sd.get("score", "N/A"))
        _set_cell(table.cell(i + 1, 3), sd.get("rationale", ""))

    # Total row
    total_row = len(scores) + 1
    _set_cell(table.cell(total_row, 0), t["score_total"], bold=True)
    _set_cell(table.cell(total_row, 1), t["score_100pct"], bold=True)
    _set_cell(table.cell(total_row, 2), f"{rec_data.get('total_score', 0):.2f}", bold=True)
    _set_cell(table.cell(total_row, 3), f"→ {rec_data.get('recommendation', 'N/A')}", bold=True)

    doc.add_paragraph()

    # ★ FINAL DECISION — revealed here ★
    rec = rec_data.get("recommendation", "NEUTRAL")
    conf = rec_data.get("confidence", 0.0)
    thesis = rec_data.get("thesis", "")
    rec_color = get_rec_color(rec)

    doc.add_paragraph()
    add_styled_paragraph(doc, f"  {rec}  ",
                         bold=True, color=rec_color, size=Pt(28),
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)
    add_styled_paragraph(doc, f"{t['rec_final']}",
                         bold=True, size=Pt(14), color=COLOR_BODY,
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)
    add_styled_paragraph(doc, f"{t['rec_confidence']}: {conf:.0%}",
                         size=Pt(12), color=COLOR_BODY,
                         alignment=WD_ALIGN_PARAGRAPH.CENTER)

    if thesis:
        doc.add_paragraph()
        add_styled_paragraph(doc, thesis, size=Pt(11), color=COLOR_BODY)


def build_disclaimer(doc, disclaimer: str, t: dict):
    """Section 7: Disclaimer."""
    build_section_heading(doc, 7, t["section_disclaimer"])
    text = disclaimer if disclaimer and len(disclaimer.strip()) >= 20 else t["default_disclaimer"]
    add_styled_paragraph(doc, text, size=Pt(10), color=RGBColor(0x99, 0x99, 0x99))


def build_references(doc, meta: dict, t: dict):
    """Section 8: Data Sources & References."""
    doc.add_page_break()
    build_section_heading(doc, 8, t.get("section_references", "Data Sources & References"))
    
    sources = meta.get("data_sources", {})
    refs = []
    if sources.get("financial_data"):
        refs.append(f"Financial data: {sources['financial_data']}")
    if sources.get("price_data"):
        refs.append(f"Price data: {sources['price_data']}")
    if sources.get("news_sentiment"):
        refs.append(f"News & sentiment: {sources['news_sentiment']}")
    if sources.get("analyst_ratings"):
        refs.append(f"Analyst ratings: {sources['analyst_ratings']}")
    if sources.get("industry_research"):
        refs.append(f"Industry research: {sources['industry_research']}")
    if sources.get("risk_factors"):
        refs.append(f"Risk factors: {sources['risk_factors']}")
    if sources.get("company_info"):
        refs.append(f"Company info: {sources['company_info']}")
    
    for i, ref in enumerate(refs, 1):
        add_styled_paragraph(doc, f"{i}. {ref}", size=Pt(9), color=COLOR_BODY)
    
    doc.add_paragraph()
    report_date = meta.get("report_date", "")
    add_styled_paragraph(doc, f"Report generated: {report_date}", size=Pt(8), color=RGBColor(0x99, 0x99, 0x99))
    add_styled_paragraph(doc, t.get("ref_disclaimer", "This report is generated by AI for research purposes only."), size=Pt(8), color=RGBColor(0x99, 0x99, 0x99))


def generate_docx(report_path: str, output_path: str, language: str = "en"):
    """Generate a .docx report from a report JSON."""
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Resolve language: report's meta.language > CLI arg > default "en"
    lang = report.get("meta", {}).get("language", language)
    if lang not in LANG:
        lang = "en"
    t = LANG[lang]

    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)

    # Build sections in order — decision at the END
    build_title_page(doc, report, t)
    build_company_overview(doc, report.get("company_overview", {}), report.get("meta", {}), t)
    build_financial_analysis(doc, report.get("financial_analysis", {}), t)
    build_valuation_analysis(doc, report.get("valuation_analysis", {}), t)
    
    # Insert price chart after valuation
    chart_dir = os.path.dirname(os.path.abspath(output_path))
    price_data = report.get("price_history_monthly", {})
    price_chart = _make_price_chart(price_data, report.get("meta", {}).get("ticker", ""), chart_dir, t)
    if price_chart:
        doc.add_paragraph()
        doc.add_picture(price_chart, width=Inches(5.5))
        last_paragraph = doc.paragraphs[-1]
        last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    build_market_sentiment(doc, report.get("market_sentiment", {}), t)
    
    ticker = report.get("meta", {}).get("ticker", "")
    
    # Monthly returns chart (last 12 months)
    mr_chart = _make_monthly_returns_chart(report.get("monthly_returns_12m", {}), ticker, chart_dir, t)
    if mr_chart:
        doc.add_paragraph()
        doc.add_picture(mr_chart, width=Inches(5.5))
        last_paragraph = doc.paragraphs[-1]
        last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Yearly returns chart (last 5 years)
    yr_chart = _make_yearly_returns_chart(report.get("yearly_returns_5y", {}), ticker, chart_dir, t)
    if yr_chart:
        doc.add_paragraph()
        doc.add_picture(yr_chart, width=Inches(4.8))
        last_paragraph = doc.paragraphs[-1]
        last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    build_risk_assessment(doc, report.get("risk_assessment", {}), t)
    build_recommendation(doc, report.get("recommendation", {}), t)
    build_references(doc, report.get("meta", {}), t)

    # Save
    doc.save(output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate a formatted .docx investment decision report."
    )
    parser.add_argument("--report", required=True, help="Path to validated report JSON")
    parser.add_argument("--output", required=True, help="Path for output .docx file")
    parser.add_argument("--language", default="en", choices=["en", "zh"],
                        help="Report language (default: en)")
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print(f"ERROR: Report file not found: {args.report}", file=sys.stderr)
        sys.exit(1)

    try:
        output = generate_docx(args.report, args.output, args.language)
        print(f"Report generated: {output}")
        print(f"  Language: {args.language}")
        print(f"  Size: {os.path.getsize(output):,} bytes")
    except Exception as e:
        print(f"ERROR generating report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
