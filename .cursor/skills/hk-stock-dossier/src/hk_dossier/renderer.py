"""Markdown renderer — 将数据渲染为结构化中文研报."""

import logging
from typing import Any

from hk_dossier.utils import (
    fmt_date,
    fmt_market_cap,
    fmt_number,
    fmt_pct,
    fmt_shares,
)

logger = logging.getLogger(__name__)


def render_dossier(
    symbol: str,
    profile: dict,
    market: dict,
    financials: dict,
    dividends: dict,
    shareholders: dict,
    insider: dict,
    consensus: dict,
    events: dict,
    chart_paths: dict | None = None,
    research: dict | None = None,
) -> str:
    """Render all collected data into a complete Markdown dossier."""
    lines: list[str] = []

    name = profile.get("cn_name") or profile.get("name", symbol)
    _add(lines, f"# {name}（{symbol}）港股尽职调查报告")
    _add(lines, f"> 报告生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    _add(lines, "> **免责声明：** 本报告仅供参考，不构成投资建议。数据来源为 Pandadata。")
    _add(lines, "")

    # ── Section 1: Company Profile ──
    _render_profile(lines, profile)

    # ── Section 1a: Business Analysis (curated) ──
    if research and research.get("business"):
        _render_business_analysis(lines, research["business"])

    # ── Section 2: Market & Valuation ──
    _render_market(lines, market)

    # ── Section 2a: Charts (if generated) ──
    if chart_paths:
        _render_charts(lines, chart_paths)

    # ── Section 3: Financial Analysis ──
    _render_financials(lines, financials, market)

    # ── Section 4: Dividends & Capital Actions ──
    _render_dividends(lines, dividends)

    # ── Section 5: Shareholder Structure ──
    _render_shareholders(lines, shareholders)

    # ── Section 6: Insider Trading ──
    _render_insider(lines, insider)

    # ── Section 7: Analyst Consensus ──
    _render_consensus(lines, consensus, market)

    # ── Section 8: Broker Research Views ──
    _render_research(lines, research)

    # ── Section 9: Corporate Events ──
    _render_events(lines, events)

    # ── Section 10: Risk Notes ──
    _render_risks(lines, profile, market, financials, shareholders, insider, consensus, dividends)

    # ── Section 11: Due Diligence Conclusion ──
    _render_conclusion(lines, consensus, research, market, financials, insider, dividends)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_profile(lines: list[str], p: dict):
    _add(lines, "## 一、公司概览")
    _add(lines, "")
    _add(lines, f"- **股票代码：** {p.get('symbol', '')}")
    _add(lines, f"- **公司名称：** {p.get('name', '')}")
    _add(lines, f"- **中文名称：** {p.get('cn_name', '')}")
    _add(lines, f"- **上市日期：** {fmt_date(p.get('listed_date'))}")
    _add(lines, f"- **成立日期：** {fmt_date(p.get('incorp_date'))}")
    _add(lines, f"- **上市板块：** {p.get('board_type', '—')}")
    _add(lines, f"- **经济 sector：** {p.get('economic_sector', '—')}")
    _add(lines, f"- **业务 sector：** {p.get('business_sector', '—')}")
    _add(lines, f"- **行业组：** {p.get('industry_group', '—')}")
    _add(lines, f"- **ISIN：** {p.get('isin_code', '—')}")
    _add(lines, f"- **交易代码：** {p.get('trading_code', '—')}")
    _add(lines, f"- **每手股数：** {p.get('min_order_amount', '—')}")
    _add(lines, f"- **交易状态：** {'在交易' if p.get('asset_state') == 'AC' else p.get('asset_state', '—')}")
    _add(lines, f"- **总部地址：** {p.get('office_address', '')}，{p.get('office_city', '')}，{p.get('office_country', '')}")
    if p.get("website"):
        _add(lines, f"- **公司网站：** [{p['website']}]({p['website']})")
    if "error" in p:
        _add(lines, f"\n> ⚠️ 数据获取异常：{p['error']}")
    _add(lines, "")


def _render_business_analysis(lines: list[str], biz: dict):
    """Render curated business analysis section."""
    _add(lines, "## 二、业务分析")
    _add(lines, "")

    # Overview
    overview = biz.get("overview", "")
    if overview:
        _add(lines, "### 公司业务概览")
        _add(lines, "")
        _add(lines, overview)
        _add(lines, "")

    # Revenue breakdown
    segments = biz.get("business_segments", [])
    if segments:
        _add(lines, "### 收入构成")
        _add(lines, "")
        rev_total = biz.get("revenue_total", "")
        rev_trend = biz.get("revenue_trend", "")
        header = f"总收入：{rev_total}" if rev_total else "各业务板块占比"
        if rev_trend:
            header += f"（{rev_trend}）"
        _add(lines, header)
        _add(lines, "")
        _add(lines, "| 业务板块 | 收入占比 | 说明 |")
        _add(lines, "|---------|---------|------|")
        for name, pct, desc in segments[:5]:
            _add(lines, f"| {name} | {pct} | {desc} |")
        _add(lines, "")

    # Business model
    bm = biz.get("business_model", "")
    if bm:
        _add(lines, "### 商业模式")
        _add(lines, "")
        _add(lines, bm)
        _add(lines, "")

    # Competitive advantages
    advantages = biz.get("competitive_advantages", [])
    if advantages:
        _add(lines, "### 竞争优势")
        _add(lines, "")
        for adv in advantages:
            _add(lines, f"- {adv}")
        _add(lines, "")

    # Strategy
    strategy = biz.get("strategy", "")
    if strategy:
        _add(lines, "### 发展战略")
        _add(lines, "")
        _add(lines, strategy)
        _add(lines, "")

    # Industry position
    ind_pos = biz.get("industry_position", "")
    if ind_pos:
        _add(lines, "### 行业地位与竞争格局")
        _add(lines, "")
        _add(lines, ind_pos)
        _add(lines, "")


def _render_market(lines: list[str], m: dict):
    _add(lines, "## 三、行情与估值")
    _add(lines, "")

    pv = m.get("pv_indicators", {}) or {}
    summary = m.get("summary", {}) or {}

    # Price stats
    _add(lines, "### 最新行情")
    _add(lines, "")
    close = summary.get("latest_close") or pv.get("close")
    close_date = summary.get("latest_date") or pv.get("close_date")
    _add(lines, f"- **最新收盘价：** {fmt_number(close)} {pv.get('close_currency', '')}（{fmt_date(close_date)}）")
    _add(lines, f"- **开盘价：** {fmt_number(summary.get('open'))}")
    _add(lines, f"- **最高价：** {fmt_number(summary.get('high'))}")
    _add(lines, f"- **最低价：** {fmt_number(summary.get('low'))}")
    _add(lines, f"- **成交量：** {fmt_shares(summary.get('volume'))}")
    _add(lines, f"- **VWAP：** {fmt_number(summary.get('vwap'))}")
    _add(lines, "")

    # Market cap & 52-week range
    _add(lines, "### 市值与价量指标")
    _add(lines, "")
    _add(lines, f"- **总市值：** {fmt_market_cap(pv.get('market_cap'), pv.get('market_cap_currency', 'HKD'))}")
    _add(lines, f"- **5年 Beta：** {fmt_number(pv.get('beta_5y'), 4)}")
    _add(lines, f"- **52周最高：** {fmt_number(pv.get('high_52w'))}（{fmt_date(pv.get('high_52w_date'))}）")
    _add(lines, f"- **52周最低：** {fmt_number(pv.get('low_52w'))}（{fmt_date(pv.get('low_52w_date'))}）")
    _add(lines, "")

    # Returns
    _add(lines, "### 阶段涨跌幅")
    _add(lines, "")
    _add(lines, "| 区间 | 涨幅 | 相对基准涨幅 |")
    _add(lines, "|------|------|------------|")
    _add(lines, f"| 1日 | {fmt_pct(pv.get('return_1d'))} | — |")
    _add(lines, f"| 5日 | {fmt_pct(pv.get('return_5d'))} | — |")
    _add(lines, f"| 年初至今 | {fmt_pct(pv.get('return_ytd'))} | {fmt_pct(pv.get('rel_return_ytd'))} |")
    _add(lines, f"| 13周 | {fmt_pct(pv.get('return_13w'))} | {fmt_pct(pv.get('rel_return_13w'))} |")
    _add(lines, f"| 26周 | {fmt_pct(pv.get('return_26w'))} | {fmt_pct(pv.get('rel_return_26w'))} |")
    _add(lines, f"| 52周 | {fmt_pct(pv.get('return_52w'))} | {fmt_pct(pv.get('rel_return_52w'))} |")
    _add(lines, "")

    # Volume
    _add(lines, "### 成交量")
    _add(lines, "")
    _add(lines, f"- **日均成交量（10日）：** {fmt_shares(summary.get('avg_volume_10d') or pv.get('avg_vol_10d'))}")
    _add(lines, f"- **日均成交量（90日）：** {fmt_shares(summary.get('avg_volume_90d') or pv.get('avg_vol_90d'))}")
    _add(lines, f"- **日均成交额（3月）：** {fmt_number(pv.get('avg_val_3m'))}")
    _add(lines, "")


def _render_charts(lines: list[str], chart_paths: dict):
    """Embed generated chart images into the report."""
    _add(lines, "### 图表可视化")
    _add(lines, "")

    price = chart_paths.get("price_chart")
    volume = chart_paths.get("volume_chart")

    if price:
        # Use relative path for markdown image embedding
        rel = _get_relative_path(price)
        _add(lines, f"![股价走势]({rel})")
        _add(lines, "")
    if volume:
        rel = _get_relative_path(volume)
        _add(lines, f"![成交量]({rel})")
        _add(lines, "")


def _get_relative_path(abs_path: str) -> str:
    """Convert absolute path to relative for Markdown embedding."""
    import os
    try:
        rel = os.path.relpath(abs_path)
        return rel
    except ValueError:
        return abs_path


def _render_financials(lines: list[str], fin: dict, market: dict):
    _add(lines, "## 四、财务分析")

    _add(lines, "")

    mkt = fin.get("mktfin", {}) or {}
    ind = fin.get("industry_median", {}) or {}
    stmt = fin.get("statement", {}) or {}
    comp = fin.get("computed_ratios", {}) or {}
    stmt_currency = stmt.get("currency", "CNY")

    _add(lines, "### 关键估值指标")
    _add(lines, "")
    _add(lines, "| 指标 | 公司 | 行业中位数 |")
    _add(lines, "|------|------|-----------|")

    def row(label: str, co_val: Any, ind_val: Any = None, note: str = "") -> str:
        co = fmt_number(co_val) if co_val is not None else "—"
        iv = fmt_number(ind_val) if ind_val is not None else "—"
        note_str = f" {note}" if note else ""
        return f"| {label} | {co}{note_str} | {iv} |"

    pe = comp.get("pe_ttm")
    pe_note = "（亏损）" if pe is not None and not comp.get("pe_positive", True) else ""
    _add(lines, row("PE (TTM)", pe, ind.get("imed_pe_ttm"), pe_note))
    _add(lines, row("PB", comp.get("pb"), ind.get("imed_pb_ttm")))
    _add(lines, row("股息率", comp.get("dividend_yield"), ind.get("imed_gross_div_yield_ttm")))
    _add(lines, "")

    # Profitability ratios vs industry
    if any(comp.get(k) is not None for k in ["gross_margin", "net_margin", "roe"]):
        _add(lines, "### 盈利比率")
        _add(lines, "")
        _add(lines, "| 指标 | 公司 | 行业中位数 |")
        _add(lines, "|------|------|-----------|")
        if comp.get("gross_margin") is not None:
            _add(lines, row("毛利率", comp.get("gross_margin"), ind.get("imed_gross_margin_ratio_fye_mid")))
        if comp.get("net_margin") is not None:
            _add(lines, row("净利率", comp.get("net_margin"), ind.get("imed_net_margin_ratio_fye_mid")))
        if comp.get("roe") is not None:
            _add(lines, row("ROE", comp.get("roe"), ind.get("imed_roe_avg_common_ttm")))
        _add(lines, "")

    # EPS
    eps = stmt.get("basic_eps")
    if eps is not None:
        _add(lines, f"- **基本每股收益 (EPS)：** {fmt_number(eps)} {stmt_currency}")
        _add(lines, "")

    # Per-share / employee metrics (HK mktfin)
    _add(lines, "### 人均效能")
    _add(lines, "")
    _add(lines, f"- **人均销售额 (TTM)：** {fmt_number(mkt.get('sales_per_emp'))}")
    _add(lines, f"- **人均净利润 (TTM)：** {fmt_number(mkt.get('net_inc_per_emp'))}")
    _add(lines, "")

    # Industry context
    if ind.get("industry_name"):
        _add(lines, f"> 📊 行业对比基准：**{ind['industry_name']}** 行业中位数")
        _add(lines, "")

    # Financial statement summary
    if stmt and stmt.get("fy_period"):
        _add(lines, "### 财务报表摘要（最新报告期）")
        _add(lines, "")
        _add(lines, "```")
        stmt_currency = stmt.get("currency", "CNY")
        _add(lines, f"报告期：{stmt.get('fy_period', '—')}  （币种：{stmt_currency}）")
        _add(lines, f"资产总计：{fmt_market_cap(stmt.get('total_assets'), stmt_currency)}")
        _add(lines, f"负债合计：{fmt_market_cap(stmt.get('total_liabilities'), stmt_currency)}")
        _add(lines, f"股东权益：{fmt_market_cap(stmt.get('total_equity'), stmt_currency)}")

        if stmt.get("revenue") is not None:
            _add(lines, f"营业收入：{fmt_market_cap(stmt.get('revenue'), stmt_currency)}")
        if stmt.get("ebit") is not None:
            _add(lines, f"营业利润 (EBIT)：{fmt_market_cap(stmt.get('ebit'), stmt_currency)}")
        if stmt.get("gross_profit") is not None:
            _add(lines, f"毛利润：{fmt_market_cap(stmt.get('gross_profit'), stmt_currency)}")
        if stmt.get("net_income") is not None:
            _add(lines, f"净利润（归母）：{fmt_market_cap(stmt.get('net_income'), stmt_currency)}")
        if stmt.get("operating_cf") is not None:
            _add(lines, f"经营现金流：{fmt_market_cap(stmt.get('operating_cf'), stmt_currency)}")
        _add(lines, "```")
        _add(lines, "")
    else:
        _add(lines, "_暂无财务报表数据。_")
        _add(lines, "")


def _render_dividends(lines: list[str], d: dict):
    _add(lines, "## 五、分红与股本动作")
    _add(lines, "")

    divs = d.get("dividend_events", [])
    mkt_events = d.get("market_events", [])

    if divs:
        _add(lines, "### 分红历史")
        _add(lines, "")
        _add(lines, "| 公告日期 | 除权日 | 类型 | 每股金额 | 币种 | 事件 |")
        _add(lines, "|----------|--------|------|---------|------|------|")
        for ev in divs[:10]:
            _add(
                lines,
                "| {} | {} | {} | {} | {} | {} |".format(
                    fmt_date(ev.get("publish_date")),
                    fmt_date(ev.get("excute_date")),
                    ev.get("event_type", ""),
                    fmt_number(ev.get("number")),
                    ev.get("currency", ""),
                    str(ev.get("event", ""))[:60],
                ),
            )
        _add(lines, "")
    else:
        _add(lines, "_暂无分红数据。_")
        _add(lines, "")

    if mkt_events:
        _add(lines, "### 市场活动（配售/增发/锁定期等）")
        _add(lines, "")
        _add(lines, "| 公告日期 | 事件 |")
        _add(lines, "|----------|------|")
        for ev in mkt_events[:10]:
            _add(
                lines,
                "| {} | {} |".format(
                    fmt_date(ev.get("info_date")),
                    str(ev.get("event", ""))[:80],
                ),
            )
        _add(lines, "")


def _render_shareholders(lines: list[str], sh: dict):
    _add(lines, "## 六、股东结构")
    _add(lines, "")

    conc = sh.get("concentration", {}) or {}
    top20 = sh.get("top20", {}) or {}
    holdings = sh.get("holdings", []) or []

    if conc:
        _add(lines, "### 投资者集中度")
        _add(lines, "")
        _add(lines, f"- **投资者总数：** {fmt_number(conc.get('total_investors'), 0)}")
        _add(lines, f"- **机构持仓占流通比：** {fmt_pct(conc.get('investor_outstanding_ratio'))}")
        _add(lines, f"- **机构总持股：** {fmt_shares(conc.get('total_sharehold'))}")
        _add(lines, f"- **机构持股市值：** {fmt_market_cap(conc.get('total_holdings_value'), conc.get('currency', 'HKD'))}")
        _add(lines, "")

    if top20:
        _add(lines, "### 前20大投资者")
        _add(lines, "")
        _add(lines, f"- **前 {fmt_number(top20.get('top_investors_num', 0), 0)} 大投资者持股占流通比：** {fmt_pct(top20.get('investor_outstanding_ratio'))}")
        _add(lines, f"- **持股合计：** {fmt_shares(top20.get('sharehold'))}")
        _add(lines, f"- **持股市值：** {fmt_market_cap(top20.get('holdings_value'), top20.get('currency', 'HKD'))}")
        _add(lines, "")

    if holdings:
        _add(lines, "### 主要股东持股报告")
        _add(lines, "")
        _add(lines, "| 报告日期 | 股东名称 | 类别 | 持股数 | 占流通比 | 变动 | 变动比例 |")
        _add(lines, "|----------|----------|------|--------|---------|------|---------|")
        for h in holdings[:10]:
            _add(
                lines,
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    fmt_date(h.get("holding_date")),
                    str(h.get("investor_name", ""))[:25],
                    h.get("investor_category", ""),
                    fmt_shares(h.get("sharehold")),
                    fmt_pct(h.get("outstanding_ratio")),
                    fmt_shares(h.get("sharehold_change")),
                    fmt_pct(h.get("sharehold_change_ratio")),
                ),
            )
        _add(lines, "")


def _render_insider(lines: list[str], ins: dict):
    _add(lines, "## 七、内部人交易")
    _add(lines, "")

    trades = ins.get("trades", [])
    summary = ins.get("summary", {}) or {}

    if summary:
        _add(lines, f"- **交易总次数：** {fmt_number(summary.get('total_transactions', 0), 0)}")
        _add(lines, f"- **买入次数：** {summary.get('buy_count', 0)}")
        _add(lines, f"- **卖出次数：** {summary.get('sell_count', 0)}")
        _add(lines, f"- **净成交量：** {fmt_shares(summary.get('net_volume'))}")
        _add(lines, "")

    if trades:
        _add(lines, "### 近期交易记录")
        _add(lines, "")
        _add(lines, "| 消息日期 | 交易日期 | 内部人 | 类型 | 调整后股数 | 交易价格 | 占流通比 |")
        _add(lines, "|----------|----------|--------|------|-----------|---------|---------|")
        for t in trades[:10]:
            _add(
                lines,
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    fmt_date(t.get("info_date")),
                    fmt_date(t.get("transaction_date")),
                    str(t.get("investor_name", ""))[:20],
                    t.get("transaction_type", ""),
                    fmt_shares(t.get("adjusted_trade_shares")),
                    fmt_number(t.get("transaction_price")),
                    fmt_pct(t.get("trade_outstanding_ratio")),
                ),
            )
        _add(lines, "")
    else:
        _add(lines, "_暂无内部人交易数据。_")
        _add(lines, "")


def _render_consensus(lines: list[str], con: dict, market: dict):
    _add(lines, "## 八、市场机构观点")
    _add(lines, "")

    nc = con.get("ncycl_consensus", {}) or {}
    rec = con.get("recommendation", {}) or {}

    if nc:
        _add(lines, "### 一致预期（目标价）")
        _add(lines, "")
        _add(lines, f"- **机构覆盖数：** {int(nc.get('num_estimates', 0) or 0)}")
        _add(lines, f"- **目标均价：** {fmt_number(nc.get('mean_target_price'))} {nc.get('currency', '')}")
        _add(lines, f"- **目标中位数：** {fmt_number(nc.get('median_target_price'))} {nc.get('currency', '')}")
        _add(lines, f"- **目标最高：** {fmt_number(nc.get('high_target_price'))} {nc.get('currency', '')}")
        _add(lines, f"- **目标最低：** {fmt_number(nc.get('low_target_price'))} {nc.get('currency', '')}")

        # Upside/downside
        close = market.get("pv_indicators", {}).get("close") or market.get("summary", {}).get("latest_close")
        if close and nc.get("mean_target_price"):
            try:
                upside = (float(nc["mean_target_price"]) / float(close) - 1) * 100
                _add(lines, f"- **潜在涨跌幅：** {fmt_pct(upside)}（相对目标均价）")
            except (ValueError, TypeError):
                pass
        _add(lines, "")

    if rec:
        _add(lines, "### 买卖建议分布")
        _add(lines, "")
        total = rec.get("total_recommendations", 0) or 0
        _add(lines, f"- **总建议数：** {int(total)}")
        buy = int(rec.get("strong_buy_count", 0) or 0)
        buy += int(rec.get("buy_count", 0) or 0)
        _add(lines, f"- **买入（含强力买入）：** {buy}")
        _add(lines, f"- **持有：** {int(rec.get('hold_count', 0) or 0)}")
        sell = int(rec.get("strong_sell_count", 0) or 0)
        sell += int(rec.get("sell_count", 0) or 0)
        _add(lines, f"- **卖出（含强力卖出）：** {sell}")

        if total:
            buy_pct = buy / total * 100
            _add(lines, f"- **买入占比：** {fmt_pct(buy_pct)}")
        _add(lines, "")

    if not nc and not rec:
        _add(lines, "_暂无机构覆盖数据。_")
        _add(lines, "")


def _render_events(lines: list[str], ev: dict):
    _add(lines, "## 十、公司事件日历")
    _add(lines, "")

    meetings = ev.get("meeting_events", [])
    fin_events = ev.get("financial_events", [])
    ir_events = ev.get("ir_events", [])

    if meetings:
        _add(lines, "### 公司会议")
        _add(lines, "")
        _add(lines, "| 公告日期 | 会议日期 | 会议类型 | 事件 |")
        _add(lines, "|----------|----------|----------|------|")
        for m in meetings[:5]:
            _add(
                lines,
                "| {} | {} | {} | {} |".format(
                    fmt_date(m.get("info_date")),
                    fmt_date(m.get("start_date")),
                    m.get("event_type", ""),
                    str(m.get("event", ""))[:60],
                ),
            )
        _add(lines, "")

    if fin_events:
        _add(lines, "### 财务披露")
        _add(lines, "")
        _add(lines, "| 公告日期 | 事件 |")
        _add(lines, "|----------|------|")
        for f in fin_events[:5]:
            _add(
                lines,
                "| {} | {} |".format(
                    fmt_date(f.get("info_date")),
                    str(f.get("event", ""))[:80],
                ),
            )
        _add(lines, "")

    if ir_events:
        _add(lines, "### 投资者关系活动")
        _add(lines, "")
        _add(lines, "| 公告日期 | 事件 |")
        _add(lines, "|----------|------|")
        for ir in ir_events[:5]:
            _add(
                lines,
                "| {} | {} |".format(
                    fmt_date(ir.get("info_date")),
                    str(ir.get("event", ""))[:80],
                ),
            )
        _add(lines, "")

    if not meetings and not fin_events and not ir_events:
        _add(lines, "_暂无公司事件数据。_")
        _add(lines, "")


def _render_research(lines: list[str], research: dict | None):
    """Render broker research views section."""
    _add(lines, "## 九、券商研报观点")
    _add(lines, "")

    if not research or not research.get("views"):
        _add(lines, "_暂未获取到近期券商研报观点。_")
        _add(lines, "")
        return

    views = research["views"]
    _add(lines, research.get("summary", ""))
    _add(lines, "")

    # Group by broker if multiple views
    _add(lines, "| 日期 | 券商 | 评级 | 目标价 | 摘要 |")
    _add(lines, "|------|------|------|--------|------|")
    for v in views[:10]:
        date = v.get("date", "")[:10] if v.get("date") else "—"
        broker = v.get("broker", "—")
        rating = v.get("rating", "—") or "—"

        tp = v.get("target_price")
        tp_str = (
            f"{tp['price']:.2f} {tp.get('currency', 'HKD')}"
            if tp and tp.get("price")
            else "—"
        )
        summary = (v.get("summary", "") or "")[:60]

        _add(lines, f"| {date} | {broker} | {rating} | {tp_str} | {summary} |")

    _add(lines, "")
    _add(lines, "> 数据来源：公开财经数据源，仅供参考，不构成投资建议。")
    _add(lines, "")


def _render_risks(
    lines: list[str],
    profile: dict,
    market: dict,
    financials: dict,
    shareholders: dict,
    insider: dict,
    consensus: dict,
    dividends: dict | None = None,
):
    _add(lines, "## 十一、风险提示")
    _add(lines, "")
    risks: list[str] = []

    pv = market.get("pv_indicators", {}) or {}
    summary = market.get("summary", {}) or {}
    mkt = financials.get("mktfin", {}) or {}
    ind = financials.get("industry_median", {}) or {}
    conc = shareholders.get("concentration", {}) or {}
    ins_summary = insider.get("summary", {}) or {}
    divs = (dividends or {}).get("dividend_events", [])

    # 1. Market / Beta risk
    if pv.get("beta_5y") is not None:
        try:
            beta = float(pv["beta_5y"])
            if beta > 1.2:
                risks.append(f"- **高 Beta 风险：** 股票 Beta 为 {fmt_number(beta, 4)}，波动性显著高于市场，市场下行时跌幅可能更大。")
            elif beta > 0.8:
                risks.append(f"- **中等 Beta 风险：** 股票 Beta 为 {fmt_number(beta, 4)}，波动性与市场基本同步。")
        except (ValueError, TypeError):
            pass

    # 2. Price decline risk (52w drop > 30%)
    return_52w = pv.get("return_52w")
    if return_52w is not None:
        try:
            r52 = float(return_52w)
            if r52 < -40:
                risks.append(f"- **深度下跌风险：** 52周跌幅达 {fmt_pct(r52)}，股价处于弱势区间。")
            elif r52 < -20:
                risks.append(f"- **显著下跌风险：** 52周跌幅达 {fmt_pct(r52)}，需关注基本面是否恶化。")
        except (ValueError, TypeError):
            pass

    # 3. YTD decline
    return_ytd = pv.get("return_ytd")
    if return_ytd is not None:
        try:
            rytd = float(return_ytd)
            if rytd < -30:
                risks.append(f"- **年初至今跌幅较大：** {fmt_pct(rytd)}，今年以来表现弱于预期。")
        except (ValueError, TypeError):
            pass

    # 4. Valuation risk (PE)
    pe = mkt.get("pe_ttm")
    if pe is not None and ind.get("imed_pe_ttm") is not None:
        try:
            if float(pe) > float(ind["imed_pe_ttm"]) * 2:
                risks.append(f"- **估值偏高风险：** PE（TTM）为 {fmt_number(pe)}，显著高于行业中位数 {fmt_number(ind['imed_pe_ttm'])}。")
            elif float(pe) < 0:
                risks.append(f"- **盈利亏损风险：** PE（TTM）为负值，公司目前处于亏损状态。")
        except (ValueError, TypeError):
            pass

    # 5. EV/EBITDA based risk
    if mkt.get("ev_to_ebitda") is not None:
        try:
            ev_ebitda = float(mkt["ev_to_ebitda"])
            if ev_ebitda > 30:
                risks.append(f"- **估值偏高风险：** EV/EBITDA 为 {fmt_number(ev_ebitda)}，估值水平较高。")
            elif ev_ebitda < 0:
                risks.append(f"- **盈利风险：** EV/EBITDA 为负值，公司盈利能力堪忧。")
        except (ValueError, TypeError):
            pass

    # 6. Liquidity risk
    if summary.get("avg_volume_90d") is not None:
        try:
            if float(summary["avg_volume_90d"]) < 100000:
                risks.append("- **流动性风险：** 近90日日均成交量低于10万股，可能存在流动性不足的问题。")
            elif float(summary["avg_volume_90d"]) < 500000:
                risks.append("- **流动性偏弱：** 近90日日均成交量低于50万股，大额交易可能产生较大冲击成本。")
        except (ValueError, TypeError):
            pass

    # 7. Volume shrinkage (10d avg vs 90d avg)
    avg_10d = summary.get("avg_volume_10d")
    avg_90d = summary.get("avg_volume_90d")
    if avg_10d and avg_90d:
        try:
            v_10d = float(avg_10d)
            v_90d = float(avg_90d)
            if v_90d > 0 and v_10d < v_90d * 0.5:
                risks.append(f"- **成交量萎缩风险：** 近10日日均成交量仅为90日日均的 {fmt_pct(v_10d / v_90d * 100)}，交投活跃度显著下降。")
        except (ValueError, TypeError):
            pass

    # 8. Shareholder concentration risk
    if conc.get("investor_outstanding_ratio") is not None:
        try:
            ratio = float(conc["investor_outstanding_ratio"])
            if ratio > 80:
                risks.append(f"- **持股集中度风险：** 机构持仓占流通股 {fmt_pct(ratio)}，筹码高度集中，需关注大额减持风险。")
        except (ValueError, TypeError):
            pass

    # 9. Insider selling signal
    if ins_summary:
        sell_c = ins_summary.get("sell_count", 0) or 0
        buy_c = ins_summary.get("buy_count", 0) or 0
        if sell_c > 0 and buy_c == 0:
            risks.append(f"- **内部人减持信号：** 历史交易记录显示有 {sell_c} 笔减持行为，无增持记录，需关注内部人信心。")
        elif sell_c > buy_c * 3 and sell_c > 3:
            risks.append(f"- **内部人持续减持：** 减持次数（{sell_c} 次）远大于增持次数（{buy_c} 次），内部人可能对公司前景持谨慎态度。")

    # 10. Dividend sustainability
    if len(divs) >= 2:
        try:
            amounts = []
            for d in divs[:4]:
                v = d.get("number")
                if v is not None:
                    amounts.append(float(v))
            if len(amounts) >= 2 and amounts[0] < amounts[-1] * 0.5:
                risks.append(f"- **分红下降风险：** 最近一次分红（{fmt_number(amounts[0])}）较前期（{fmt_number(amounts[-1])}）下降超过50%，需关注现金流状况。")
        except (ValueError, TypeError):
            pass

    # 11. Near 52-week low
    close = summary.get("latest_close") or pv.get("close")
    low_52w = pv.get("low_52w")
    high_52w = pv.get("high_52w")
    if close and low_52w and high_52w:
        try:
            c = float(close)
            l = float(low_52w)
            h = float(high_52w)
            if h > l and (c - l) / (h - l) < 0.1:
                risks.append(f"- **接近52周低点：** 当前股价 {fmt_number(c)} 接近52周最低价 {fmt_number(l)}，处于年内低位区间。")
        except (ValueError, TypeError):
            pass

    if not risks:
        risks.append("_基于当前数据未识别出显著风险。_")
    _add(lines, "\n".join(risks))
    _add(lines, "")


def _render_conclusion(
    lines: list[str],
    consensus: dict,
    research: dict,
    market: dict,
    financials: dict,
    insider: dict | None = None,
    dividends: dict | None = None,
):
    """Render due diligence conclusion — professional research-style analysis."""
    _add(lines, "## 十二、尽调结论")
    _add(lines, "")

    nc = consensus.get("ncycl_consensus", {}) or {}
    rec = consensus.get("recommendation", {}) or {}
    views = research.get("views", []) if research else []
    comp = financials.get("computed_ratios", {}) or {}
    stmt = financials.get("statement", {}) or {}
    mktfin = financials.get("mktfin", {}) or {}
    pv = market.get("pv_indicators", {}) or {}
    summary = market.get("summary", {}) or {}
    profile_name = lines[0].replace("# ", "").split("（")[0] if lines else "该标的"

    close = summary.get("latest_close") or pv.get("close")
    pe = comp.get("pe_ttm")
    pb = comp.get("pb")
    mean_tp = nc.get("mean_target_price")
    upside = None
    if mean_tp and close:
        try:
            upside = (float(mean_tp) / float(close) - 1) * 100
        except (ValueError, TypeError):
            pass

    # -- Collect key metrics --
    market_cap = pv.get("market_cap")
    mc_str = fmt_market_cap(market_cap, pv.get("market_cap_currency", "HKD")) if market_cap else "N/A"
    return_52w = pv.get("return_52w")
    return_ytd = pv.get("return_ytd")
    beta = pv.get("beta_5y")
    revenue = stmt.get("revenue")
    net_income = stmt.get("net_income")
    total_assets = stmt.get("total_assets")
    total_liab = stmt.get("total_liabilities")
    gross_margin = comp.get("gross_margin")
    net_margin = comp.get("net_margin")
    roe = comp.get("roe")
    eps = stmt.get("basic_eps")
    stmt_currency = stmt.get("currency", "CNY")
    fy_period = stmt.get("fy_period", "最新报告期")
    rec_total = int(rec.get("total_recommendations", 0) or 0)
    buy_count = int(rec.get("strong_buy_count", 0) or 0) + int(rec.get("buy_count", 0) or 0)
    hold_count = int(rec.get("hold_count", 0) or 0)
    sell_count = int(rec.get("strong_sell_count", 0) or 0) + int(rec.get("sell_count", 0) or 0)
    institutions = int(nc.get("num_estimates", 0) or 0)
    close_price_str = fmt_number(close) if close else "N/A"
    pe_str = fmt_number(pe) if pe is not None else "N/A"
    pb_str = fmt_number(pb) if pb is not None else "N/A"
    eps_str = fmt_number(eps) if eps is not None else "N/A"

    # ── 1. 业务与市场定位 ──
    _add(lines, "### 1. 业务与市场定位")
    _add(lines, "")
    lines.append(
        f"{profile_name}作为一家在港股上市的公司（该报告覆盖标的），"
        f"当前总市值约{mc_str}。"
    )
    if return_52w is not None:
        r52 = float(return_52w)
        if r52 > 0:
            lines.append(f"从股价表现来看，过去52周累计上涨{fmt_pct(r52)}，走势相对强劲，反映出市场对其业务发展和行业前景持有一定信心。")
        elif r52 < -20:
            lines.append(f"然而从股价表现来看，过去52周累计下跌{fmt_pct(r52)}，走势显著弱于大盘，反映出市场对其基本面及行业前景存在较大分歧或担忧。")
        else:
            lines.append(f"过去52周股价累计变动{fmt_pct(r52)}，整体表现与大盘基本同步，未出现显著超额收益或亏损。")
    if return_ytd is not None and float(return_ytd) < -20:
        lines.append(f"年初至今跌幅已达{fmt_pct(float(return_ytd))}，短期下行趋势明显，投资者需关注是否存在尚未充分定价的负面因素。")
    _add(lines, "")

    # ── 2. 财务分析 ──
    _add(lines, "### 2. 财务状况分析")
    _add(lines, "")

    # Revenue & profit
    if revenue is not None:
        rev_str = fmt_market_cap(revenue, stmt_currency)
        lines.append(
            f"根据{stmt_currency}计价的财务报表（{fy_period}），公司当期实现营业收入{rev_str}。"
        )
    else:
        lines.append(f"最新财务报表数据（{fy_period}）显示部分关键财务指标暂不可用，可能受限于数据源更新时效。")

    if net_income is not None:
        ni = float(net_income)
        ni_str = fmt_market_cap(ni, stmt_currency)
        if ni > 0:
            lines.append(f"当期实现归母净利润{ni_str}，处于盈利状态，盈利质量需结合现金流进一步评估。")
        else:
            lines.append(f"当期归母净利润为{ni_str}，处于亏损状态。")
            if revenue is not None and float(revenue) > 0:
                nm = ni / float(revenue) * 100
                lines.append(f"净利率为{fmt_pct(nm)}，亏损幅度相对营收规模而言较为显著，反映出成本费用端存在较大压力。")
    if gross_margin is not None:
        gm = float(gross_margin)
        if gm > 40:
            lines.append(f"毛利率达{fmt_pct(gm)}，处于较高水平，表明公司产品或服务具备较强的定价能力和竞争优势。")
        elif gm > 0:
            lines.append(f"毛利率为{fmt_pct(gm)}，处于中等水平，需关注成本端变动对盈利的影响。")
        else:
            lines.append(f"毛利率为{fmt_pct(gm)}，已转为负值，表明营业成本已超过收入，盈利模式面临严峻挑战。")

    # Balance sheet
    if total_assets is not None and total_liab is not None:
        ta = float(total_assets)
        tl = float(total_liab)
        alr = tl / ta * 100 if ta > 0 else 0
        ta_str = fmt_market_cap(ta, stmt_currency)
        tl_str = fmt_market_cap(tl, stmt_currency)
        lines.append(
            f"资产负债方面，公司总资产{ta_str}、总负债{tl_str}，资产负债率约{fmt_pct(alr)}。"
        )
        if alr > 80:
            lines.append("负债率处于较高水平，财务杠杆偏大，需关注债务到期结构与再融资能力。若叠加行业下行周期，可能面临流动性压力。")
        elif alr > 50:
            lines.append("负债率处于中等水平，财务结构基本稳健，但仍需关注有息负债规模及利息覆盖能力。")
        else:
            lines.append("负债率较低，财务结构相对稳健，偿债压力较小。")

    # Cash flow vs profit quality
    ocf = stmt.get("operating_cf")
    if ocf is not None and net_income is not None:
        ocf_val = float(ocf)
        ni_val = float(net_income)
        if ni_val != 0:
            cf_ratio = ocf_val / ni_val
            if cf_ratio > 1:
                lines.append("经营活动现金流覆盖净利润倍数超过1，利润的现金转化质量较高，盈利真实性较为可信。")
            elif cf_ratio > 0:
                lines.append("经营活动现金流为正但低于净利润，部分利润尚未实现现金回收，需关注应收账款及存货周转情况。")
            else:
                lines.append('经营活动现金流为负，与净利润方向不一致，盈利的现金支撑不足，需警惕「纸面利润」风险。')

    # EPS
    if eps is not None:
        lines.append(f"每股收益（EPS）为{eps_str} {stmt_currency}，为股东价值创造提供了量化参考。")

    if roe is not None:
        roe_val = float(roe)
        if roe_val > 15:
            lines.append(f"净资产收益率（ROE）达{fmt_pct(roe_val)}，股东回报水平较为突出，显示出较强的资本运用效率。")
        elif roe_val < 0:
            lines.append(f"净资产收益率（ROE）为{fmt_pct(roe_val)}，股东权益正在被亏损侵蚀，长期来看将影响净资产规模。")

    _add(lines, "")

    # ── 3. 估值分析 ──
    _add(lines, "### 3. 估值水平与机构观点")
    _add(lines, "")

    lines.append(
        f"当前股价{close_price_str} HKD，对应PE为{pe_str}、PB为{pb_str}。"
    )
    if pe is not None and float(pe) < 0:
        lines.append("PE为负值，反映公司当前处于亏损状态，传统PE估值法参考意义有限，估值锚点应以PB及远期盈利恢复预期为主。")
    elif pe is not None:
        lines.append(f"PE为{pe_str}倍，处于可比较区间。")
    if pb is not None:
        pb_val = float(pb)
        if pb_val < 1:
            lines.append(f"PB为{pb_str}倍，已跌破净资产（破净）。破净一方面可能意味着市场对资产质量存在疑虑（如房地产企业的存货减值风险、金融资产的隐含不良等），另一方面也可能提供了安全边际。两者的区分需结合行业特征和公司具体资产构成来判断。")
        elif pb_val < 3:
            lines.append(f"PB为{pb_str}倍，处于1-3倍的合理区间，市场对公司的资产价值给予了适度溢价。")
        else:
            lines.append(f"PB为{pb_str}倍，高于3倍，市场给予了较高溢价，可能反映了对公司无形资产、品牌价值或成长预期的定价。")

    # Consensus view
    if institutions > 0 and mean_tp is not None:
        lines.append(f"")
        lines.append(
            f"从机构覆盖来看，共有{institutions}家机构对该标的进行跟踪覆盖，目标均价为{fmt_number(mean_tp)} HKD"
        )
        if upside is not None:
            if upside > 0:
                lines.append(f"，较当前股价有{fmt_pct(upside)}的上行空间。机构整体偏乐观，认为当前价格尚未充分反映其内在价值。")
            else:
                lines.append(f"，但较当前股价低{fmt_pct(abs(upside))}，机构整体持谨慎态度，认为当前估值偏高或基本面存在下行风险。")

    if rec_total > 0:
        buy_pct = buy_count / rec_total * 100
        lines.append(
            f"买卖建议方面，共{rec_total}条建议中买入（含强力买入）{buy_count}条、持有{hold_count}条、卖出（含强力卖出）{sell_count}条，"
            f"买入占比{fmt_pct(buy_pct)}。"
        )
        if buy_pct > 60:
            lines.append("买入占比较高，机构情绪偏积极，一致看好该标的后续表现。")
        elif buy_pct > 30:
            lines.append("买卖建议分布较为分散，机构之间存在明显分歧。")
        else:
            lines.append("买入占比较低，机构情绪偏谨慎甚至悲观，多数分析师认为下行风险大于上行空间。")

    # Broker research summary
    if views:
        lines.append("")
        lines.append("在近期覆盖的券商研报中：")
        for v in views:
            broker = v.get("broker", "")
            rating = v.get("rating", "")
            tp = v.get("target_price")
            tp_str = f"，目标价{tp['price']} {tp['currency']}" if tp and tp.get("price") else ""
            summary_text = v.get("summary", "")
            date = v.get("date", "")[:10] if v.get("date") else ""
            lines.append(
                f"- {broker}（{date}）给予「{rating}」评级{tp_str}。"
                f"{'核心逻辑：' + summary_text + '。' if summary_text else ''}"
            )
    _add(lines, "")

    # ── 4. 核心风险与关注事项 ──
    _add(lines, "### 4. 核心风险与关注事项")
    _add(lines, "")

    risks_text = []
    if beta is not None:
        b = float(beta)
        if b > 1.5:
            risks_text.append(f"**高波动风险**：Beta系数为{fmt_number(b, 4)}，显著高于市场平均水平。意味着当市场下跌时，该标的跌幅可能更大。对于风险偏好较低的投资者，需评估波动承受能力。")
        elif b > 1.2:
            risks_text.append(f"**较高波动风险**：Beta系数为{fmt_number(b, 4)}，高于市场平均水平，股价波动性相对较大。")
    if return_52w is not None and float(return_52w) < -30:
        risks_text.append(f"**趋势偏弱风险**：52周跌幅达{fmt_pct(float(return_52w))}，股价处于明显的下行通道中。在趋势逆转信号出现之前，需警惕「接飞刀」风险。")
    if pe is not None and float(pe) < 0:
        risks_text.append(f"**持续亏损风险**：公司处于亏损状态，{'' if net_income is None else f'当期归母亏损{fmt_market_cap(float(net_income), stmt_currency)}'}。若亏损持续，将不断消耗净资产，影响公司持续经营能力。需重点关注营收增长趋势、费用控制进展以及毛利率变化方向。")
    if gross_margin is not None and float(gross_margin) < 0:
        risks_text.append(f"**毛利润转负风险**：毛利率为{fmt_pct(float(gross_margin))}，营业成本已超过营业收入。这种状况若不能及时扭转，将加速现金消耗。")
    if sell_count > buy_count * 2 and sell_count > 0:
        risks_text.append(f"**机构情绪偏空**：卖出建议数量（{sell_count}条）远超买入建议（{buy_count}条），表明专业机构对该标的前景持较为一致的审慎态度。")
    ins_summary = insider.get("summary", {}) if insider else {}
    if ins_summary:
        sell_ins = ins_summary.get("sell_count", 0) or 0
        buy_ins = ins_summary.get("buy_count", 0) or 0
        if sell_ins > 0 and buy_ins == 0:
            risks_text.append(f"**内部人减持信号**：历史交易数据显示有{sell_ins}笔内部人减持行为，且无增持记录。内部人（通常包括高管及核心股东）的持续减持可能反映出对公司未来前景信心不足。")
    divs_data = (dividends or {}).get("dividend_events", []) if dividends else []
    if not divs_data or len(divs_data) <= 1:
        risks_text.append("**股东回报有限**：近两年无持续稳定的分红记录。对于看重股息收入的投资者而言，该标的当前不具备分红吸引力。")

    if risks_text:
        for i, t in enumerate(risks_text):
            if i > 0:
                lines.append("")
            lines.append(t)
    else:
        lines.append("基于当前可获取的数据，未识别出显著风险信号。但仍需持续跟踪行业政策变化、竞争格局演变及公司经营动态。")

    _add(lines, "")

    # ── 5. 综合评估与展望 ──
    _add(lines, "### 5. 综合评估与投资展望")
    _add(lines, "")

    # Count positive vs negative signals
    pos_signals = sum([
        1 if upside is not None and upside > 20 else 0,
        1 if buy_pct > 60 else 0,
        1 if gross_margin is not None and float(gross_margin) > 40 else 0,
        1 if return_52w is not None and float(return_52w) > 0 else 0,
        1 if pb is not None and float(pb) < 1 else 0,
    ])
    neg_signals = sum([
        1 if pe is not None and float(pe) < 0 else 0,
        1 if return_52w is not None and float(return_52w) < -20 else 0,
        1 if gross_margin is not None and float(gross_margin) < 0 else 0,
        1 if sell_count > buy_count and rec_total > 0 else 0,
        1 if beta is not None and float(beta) > 1.5 else 0,
    ])

    # Build narrative
    if pos_signals > neg_signals + 1:
        outlook = "偏积极"
        lines.append(f"综合来看，该标的存在{pos_signals}项积极信号和{neg_signals}项谨慎信号，正面因素多于负面因素。")
        if upside is not None and upside > 20:
            lines.append(f"机构一致目标价隐含{fmt_pct(upside)}的上行空间，叠加财务基本面相对稳健，中长期具备一定的配置价值。")
        lines.append("但投资者仍需持续跟踪行业景气度变化及公司经营节奏，在合理估值区间内审慎决策。")
    elif neg_signals > pos_signals + 1:
        outlook = "偏谨慎"
        lines.append(f"综合来看，该标的识别出{neg_signals}项谨慎信号和{pos_signals}项积极信号，风险因素占据主导。")
        if pe is not None and float(pe) < 0:
            lines.append("公司当前处于亏损状态，盈利拐点尚不明朗。在盈利能力恢复得到财务数据验证之前，估值缺乏有效支撑。")
        if rec_total > 0 and sell_count > buy_count:
            lines.append("机构整体偏空，分析师建议以观望或减持为主。")
        lines.append("投资者应重点关注：1）亏损收窄或扭亏的明确信号；2）负债率变化及流动性状况；3）行业政策与竞争格局的边际变化。在基本面出现实质性改善之前，建议保持审慎。")
    else:
        outlook = "中性"
        lines.append(f"综合来看，该标的积极信号与谨慎信号各为{pos_signals}项和{neg_signals}项，多空因素交织，呈现中性特征。")
        if upside is not None:
            if upside > 0:
                lines.append(f"一方面，机构目标价隐含{fmt_pct(upside)}的上行空间；")
            else:
                lines.append(f"一方面，机构目标价显示存在{fmt_pct(abs(upside))}的下行风险；")
        if pe is not None and float(pe) < 0:
            lines.append("另一方面，公司当前仍处于亏损状态，盈利能力和估值基准尚未稳固。")
        elif pe is not None:
            lines.append(f"另一方面，当前PE为{pe_str}倍，估值水平尚需业绩增长来消化。")
        lines.append("投资者需结合自身的风险偏好和投资期限独立判断，关注后续财报数据对当前分歧的验证方向。")

    _add(lines, "")
    _add(lines, "---")
    _add(lines, "")
    _add(lines, "> **免责声明：** 本报告由自动化工具生成，所有数据来源于 Pandadata 接口。")
    _add(lines, "> 报告中的分析和判断仅供参考，不构成任何投资建议。投资者应独立判断并承担投资风险。")
    _add(lines, "> 报告生成时间：" + __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))


def _add(lines: list[str], text: str = ""):
    lines.append(text)
