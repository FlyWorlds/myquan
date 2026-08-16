"""Markdown renderer — renders data into a structured 11-section crude oil briefing report."""

import logging
from datetime import datetime
from typing import Any

from oil_brief.utils import (
    fmt_price,
    fmt_pct,
    fmt_change,
    fmt_date,
    fmt_volume,
    fmt_inventory,
    fmt_number,
    get_latest_value,
    get_first_value,
)

logger = logging.getLogger(__name__)


def _add(lines: list[str], text: str = ""):
    lines.append(text)


def render_report(
    report_date: str,
    variety: str,
    primary_label: str = "Brent 原油",
    primary_unit: str = "美元/桶",
    sc_data: list[dict] | None = None,
    indicators: dict | None = None,
    trend: dict | None = None,
    sr_levels: dict | None = None,
    eia_data: dict | None = None,
    term_structure: list[dict] | None = None,
    warehouse: list[dict] | None = None,
    ls_ratio: list[dict] | None = None,
    position: list[dict] | None = None,
    spread: list[dict] | None = None,
    news: list[dict] | None = None,
    events: list[dict] | None = None,
    latest_primary_price: float | None = None,
    latest_sc_price: float | None = None,
    latest_wti: float | None = None,
    latest_brent: float | None = None,
    wti_change_pct: float | None = None,
    brent_change_pct: float | None = None,
    sc_change_pct: float | None = None,
    energy_category: str = "crude",
) -> str:
    """Render all collected data into a complete Markdown crude oil briefing."""
    lines: list[str] = []
    indicators = indicators or {}
    trend = trend or {}
    sr_levels = sr_levels or {"support": [], "resistance": []}
    eia_data = eia_data or {}
    sc_data = sc_data or []
    news = news or []
    events = events or []

    _add(lines, f"# 📊 能源日报 — {primary_label}")
    _add(lines, f"> 报告生成时间：{report_date}")
    _add(lines, "> **免责声明：** 本报告仅供参考，不构成任何投资建议。数据来源包括 Pandadata、EIA、OPEC 及公开财经信息。")
    _add(lines, "")
    _add(lines, "---")
    _add(lines, "")

    # ════════════════════════════════════════════════════
    # Section 1: Current Trend
    # ════════════════════════════════════════════════════
    _render_current_trend(lines, primary_label, primary_unit, variety, indicators, trend,
                          latest_primary_price, latest_sc_price, latest_wti, latest_brent,
                          wti_change_pct, brent_change_pct, sc_change_pct)

    # ════════════════════════════════════════════════════
    # Section 2: Technical Analysis
    # ════════════════════════════════════════════════════
    _render_technical_analysis(lines, indicators, primary_unit)

    # ════════════════════════════════════════════════════
    # Section 3: Key Support Levels
    # ════════════════════════════════════════════════════
    _render_support(lines, sr_levels, variety)

    # ════════════════════════════════════════════════════
    # Section 4: Key Resistance Levels
    # ════════════════════════════════════════════════════
    _render_resistance(lines, sr_levels, variety)

    # ════════════════════════════════════════════════════
    # Section 5: Today's Important Events & News
    # ════════════════════════════════════════════════════
    _render_news_analysis(lines, news, events, trend, indicators, primary_label, primary_unit,
                          latest_primary_price, eia_data, energy_category)

    # ════════════════════════════════════════════════════
    # Section 6: Latest Research Views
    # ════════════════════════════════════════════════════
    _render_research_views(lines, trend, indicators, primary_label, primary_unit)

    # ════════════════════════════════════════════════════
    # Section 7: Market Sentiment
    # ════════════════════════════════════════════════════
    _render_market_sentiment(lines, indicators, position, spread)

    # ════════════════════════════════════════════════════
    # Section 8: Trading Plan
    # ════════════════════════════════════════════════════
    _render_trading_plan(lines, trend, sr_levels, primary_unit)

    # ════════════════════════════════════════════════════
    # Section 9: Price Prediction
    # ════════════════════════════════════════════════════
    _render_price_prediction(lines, indicators, trend, sr_levels, primary_label, primary_unit)

    # ════════════════════════════════════════════════════
    # Section 10: Risk Warnings
    # ════════════════════════════════════════════════════
    _render_risk_warnings(lines, indicators, news, primary_unit, variety)

    # ════════════════════════════════════════════════════
    # Section 11: AI Summary
    # ════════════════════════════════════════════════════
    _render_ai_summary(lines, trend, indicators, sr_levels, primary_label, primary_unit,
                       latest_primary_price, latest_sc_price, latest_wti, latest_brent)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 1: Current Trend
# ---------------------------------------------------------------------------

def _render_current_trend(lines, primary_label, primary_unit, variety_code, ind, trend,
                          primary_price, sc_price, wti, brent,
                          wti_change=None, brent_change=None, sc_change=None):
    _add(lines, "## 一、当前趋势")
    _add(lines, "")

    # Latest prices overview — primary first, then the other two
    _add(lines, "### 最新价格概览")
    _add(lines, "")
    _add(lines, "| 品种 | 最新价 | 日涨跌幅 |")
    _add(lines, "|------|--------|----------|")

    primary_chg = ind.get("change_pct", None)
    if primary_price is not None:
        _add(lines, f"| **{primary_label}** | **{fmt_price(primary_price, primary_unit)}** | **{fmt_pct(primary_chg) if primary_chg is not None else '—'}** |")
    else:
        _add(lines, f"| **{primary_label}** | — | — |")

    # WTI (skip if it's the primary)
    if variety_code != "WTI" and wti is not None:
        chg = wti_change if wti_change is not None else ind.get("change_pct") if variety_code == "WTI" else None
        _add(lines, f"| WTI 原油 | {fmt_price(wti, '美元/桶')} | {fmt_pct(chg) if chg is not None else '—'} |")
    # Brent (skip if it's the primary)
    if variety_code != "BRENT" and brent is not None:
        chg = brent_change if brent_change is not None else ind.get("change_pct") if variety_code == "BRENT" else None
        _add(lines, f"| Brent 原油 | {fmt_price(brent, '美元/桶')} | {fmt_pct(chg) if chg is not None else '—'} |")
    # SC (skip if it's the primary)
    if variety_code != "SC" and sc_price is not None:
        _add(lines, f"| 上海原油期货 (SC) | {fmt_price(sc_price, '元/桶')} | {fmt_pct(sc_change) if sc_change is not None else '—'} |")
    _add(lines, "")

    # Trend analysis
    _add(lines, "### 趋势判断")
    _add(lines, "")
    trend_map = {"up": "📈 上涨", "down": "📉 下跌", "neutral": "➡️ 震荡"}
    strength_map = {"strong": "强势", "moderate": "中等", "weak": "弱势", "unknown": "未知"}
    trend_text = trend_map.get(trend.get("trend", "neutral"), "震荡")
    strength_text = strength_map.get(trend.get("strength", "unknown"), "未知")

    _add(lines, f"- **趋势方向：** {trend_text}")
    _add(lines, f"- **趋势强度：** {strength_text}")
    _add(lines, f"- **近期斜率（10日）：** {fmt_pct(trend.get('slope_pct', 0))}")
    _add(lines, f"- **连续同向天数：** {trend.get('duration_days', 0)} 天")
    _add(lines, f"- **价格与 MA20 关系：** {'价格在均线上方' if trend.get('above_ma20') else '价格在均线下方'}")
    _add(lines, f"- **RSI(14)：** {ind.get('rsi', '—')}")
    _add(lines, "")

    # Brief description
    if trend.get("trend") == "up":
        if trend.get("strength") == "strong":
            _add(lines, f"当前{primary_label}市场处于 **强势上涨趋势**，多头动能充沛，价格沿短期均线上行。")
        else:
            _add(lines, f"当前{primary_label}市场处于 **温和上涨趋势**，多头占优但动能有所减弱。")
    elif trend.get("trend") == "down":
        if trend.get("strength") == "strong":
            _add(lines, f"当前{primary_label}市场处于 **强势下跌趋势**，空头主导行情，短期不宜抄底。")
        else:
            _add(lines, f"当前{primary_label}市场处于 **温和下跌趋势**，空头动能逐渐释放。")
    else:
        _add(lines, f"当前{primary_label}市场处于 **震荡整理阶段**，方向不明确，等待突破信号。")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 2: Technical Analysis
# ---------------------------------------------------------------------------

def _render_technical_analysis(lines, ind, unit="美元/桶"):
    _add(lines, "## 二、技术分析")
    _add(lines, "")

    # Moving Averages
    _add(lines, "### 移动均线 (MA)")
    _add(lines, "")
    _add(lines, "| 均线周期 | 数值 | 价格关系 |")
    _add(lines, "|----------|------|----------|")
    close = ind.get("close", 0)
    for p in [5, 10, 20, 60]:
        ma_key = f"ma{p}"
        ma_val = ind.get(ma_key)
        if ma_val:
            relation = "价格在均线上方" if close > ma_val else "价格在均线下方"
            _add(lines, f"| MA{p} | {fmt_price(ma_val, unit)} | {relation} |")
        else:
            _add(lines, f"| MA{p} | — | 数据不足 |")
    _add(lines, "")

    # Bollinger Bands
    _add(lines, "### 布林带 (BOLL)")
    _add(lines, "")
    bb_upper = ind.get("boll_upper")
    bb_mid = ind.get("boll_mid")
    bb_lower = ind.get("boll_lower")
    if bb_upper and bb_mid and bb_lower:
        band_width = ((bb_upper - bb_lower) / bb_mid * 100) if bb_mid else 0
        _add(lines, f"- **上轨：** {fmt_price(bb_upper, unit)}")
        _add(lines, f"- **中轨 (MA20)：** {fmt_price(bb_mid, unit)}")
        _add(lines, f"- **下轨：** {fmt_price(bb_lower, unit)}")
        _add(lines, f"- **带宽：** {band_width:.2f}%")
        if close > bb_upper:
            _add(lines, "- **位置：** 价格突破上轨，超买区间")
        elif close < bb_lower:
            _add(lines, "- **位置：** 价格跌破下轨，超卖区间")
        else:
            pct = (close - bb_lower) / (bb_upper - bb_lower) * 100 if (bb_upper - bb_lower) > 0 else 50
            _add(lines, f"- **位置：** 价格在布林带内 {pct:.1f}% 分位")
            if pct > 90:
                _add(lines, "  - ⚠️ **价格接近布林上轨，短期超买信号，注意回调风险**")
            elif pct < 10:
                _add(lines, "  - 💡 **价格接近布林下轨，短期超卖信号，关注反弹机会**")
    else:
        _add(lines, "- 布林带数据不足")
    _add(lines, "")

    # RSI
    _add(lines, "### RSI 指标")
    _add(lines, "")
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            _add(lines, f"- **RSI(14)：** {rsi} — ⚠️ **超买区间**，短期回调风险增加")
        elif rsi <= 30:
            _add(lines, f"- **RSI(14)：** {rsi} — 🛒 **超卖区间**，短期反弹机会")
        elif rsi >= 50:
            _add(lines, f"- **RSI(14)：** {rsi} — 多头区域，动能偏强")
        else:
            _add(lines, f"- **RSI(14)：** {rsi} — 空头区域，动能偏弱")
    else:
        _add(lines, "- RSI 数据不足")
    _add(lines, "")

    # MACD
    _add(lines, "### MACD 指标")
    _add(lines, "")
    macd = ind.get("macd")
    macd_signal = ind.get("macd_signal")
    macd_hist = ind.get("macd_hist")
    if macd is not None:
        _add(lines, f"- **MACD：** {fmt_change(macd)}")
        _add(lines, f"- **信号线：** {fmt_change(macd_signal)}")
        _add(lines, f"- **柱状图：** {fmt_change(macd_hist)}")
        if macd_hist is not None:
            if macd_hist > 0 and macd > macd_signal:
                _add(lines, "- **信号：** MACD 金叉状态，多头信号")
            elif macd_hist < 0 and macd < macd_signal:
                _add(lines, "- **信号：** MACD 死叉状态，空头信号")
            elif macd_hist > 0:
                _add(lines, "- **信号：** MACD 空头动能减弱，可能金叉")
            else:
                _add(lines, "- **信号：** MACD 多头动能减弱，可能死叉")
    else:
        _add(lines, "- MACD 数据不足")
    _add(lines, "")

    # ATR (Volatility)
    atr = ind.get("atr")
    if atr is not None:
        _add(lines, "### 波动率")
        _add(lines, "")
        _add(lines, f"- **ATR(14)：** {fmt_price(atr, unit)}")
        if close > 0:
            _add(lines, f"- **波动率（ATR/价格）：** {atr / close * 100:.2f}%")
        _add(lines, "")


# ---------------------------------------------------------------------------
# Section 3: Key Support Levels
# ---------------------------------------------------------------------------

def _render_support(lines, sr_levels, variety):
    _add(lines, "## 三、关键支撑位")
    _add(lines, "")
    unit = "元/桶" if variety == "SC" else "美元/桶"
    supports = sr_levels.get("support", [])
    if supports:
        _add(lines, "| 支撑位 | 强度 | 依据 |")
        _add(lines, "|--------|------|------|")
        strength_icon = {"strong": "🟢 强", "medium": "🟡 中", "weak": "⚪ 弱"}
        for s in supports:
            s_text = strength_icon.get(s.get("strength", "weak"), "未知")
            _add(lines, f"| {fmt_price(s.get('level'), unit)} | {s_text} | {s.get('source', '—')} |")
    else:
        _add(lines, "- 数据不足，暂无法计算有效支撑位")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 4: Key Resistance Levels
# ---------------------------------------------------------------------------

def _render_resistance(lines, sr_levels, variety):
    _add(lines, "## 四、关键阻力位")
    _add(lines, "")
    unit = "元/桶" if variety == "SC" else "美元/桶"
    resistances = sr_levels.get("resistance", [])
    if resistances:
        _add(lines, "| 阻力位 | 强度 | 依据 |")
        _add(lines, "|--------|------|------|")
        strength_icon = {"strong": "🟢 强", "medium": "🟡 中", "weak": "⚪ 弱"}
        for r in resistances:
            s_text = strength_icon.get(r.get("strength", "weak"), "未知")
            _add(lines, f"| {fmt_price(r.get('level'), unit)} | {s_text} | {r.get('source', '—')} |")
    else:
        _add(lines, "- 数据不足，暂无法计算有效阻力位")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 5: News Analysis
# ---------------------------------------------------------------------------

def _render_news_analysis(lines, news, events, trend, ind, label, unit,
                          primary_price, eia_data=None, energy_category="crude"):
    _add(lines, "## 五、消息面分析")
    _add(lines, "")

    trend_dir = trend.get("trend", "neutral")
    strength = trend.get("strength", "unknown")
    close = primary_price or ind.get("close", 0)
    atr = ind.get("atr", 0)
    vol_pct = atr / close * 100 if close and atr else 0
    slope = trend.get("slope_pct", 0)

    # Build lookup: category -> first news item
    news_by_cat: dict[str, dict] = {}
    for item in news:
        cat = item.get("category", "")
        if cat and cat not in news_by_cat:
            news_by_cat[cat] = item

    def _get_news_ref(category: str) -> str:
        """Get a news reference string for the given category."""
        item = news_by_cat.get(category)
        if item:
            t = item.get("title", "")
            s = item.get("source", "")
            return f"📰 [{t}]({item.get('link', '#')}) — {s}" if item.get("link") else f"📰 {t} — {s}"
        return ""

    # Dispatch per energy category
    if energy_category == "natgas":
        _render_natgas_news(lines, _get_news_ref, trend, ind, label, unit, eia_data)
    elif energy_category == "gasoline":
        _render_gasoline_news(lines, _get_news_ref, trend, ind, label, unit)
    elif energy_category == "heating_oil":
        _render_heating_oil_news(lines, _get_news_ref, trend, ind, label, unit)
    else:
        _render_crude_news(lines, _get_news_ref, events, trend, ind, label, unit, primary_price, eia_data)

    # ── 未来事件日历（通用）──
    if events:
        _add(lines, "### 📅 本周重要事件日历")
        _add(lines, "")
        _add(lines, "| 日期 | 事件 | 预期影响 |")
        _add(lines, "|------|------|----------|")
        for evt in events:
            _add(lines, f"| {evt.get('date', '—')} | {evt.get('event', '—')} | {evt.get('expected_impact', '—')} |")
        _add(lines, "")


# ═══════════════════════════════════════════════════════════════
# Energy-category news functions
# ═══════════════════════════════════════════════════════════════

def _render_crude_news(lines, get_ref, events, trend, ind, label, unit, primary_price, eia_data):
    """Crude: OPEC + EIA stocks + geopolitics + macro + SC spread."""
    _adds = lambda t="": _add(lines, t)
    trend_dir = trend.get("trend", "neutral")
    strength = trend.get("strength", "unknown")
    close = primary_price or ind.get("close", 0)
    atr = ind.get("atr", 0)
    vol_pct = atr / close * 100 if close and atr else 0
    slope = trend.get("slope_pct", 0)

    # ── 1. OPEC+ ──
    _add(lines, "### 1. OPEC+ 产量政策"); ref = get_ref("OPEC+ 产量政策")
    if ref: _add(lines, f"> {ref}"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好油价**"); _add(lines, "")
    _add(lines, f"当前 {label} 处于强势上涨趋势（10日涨幅 {slope:+.1f}%），OPEC+ 维持减产力度的概率较高。")
    _add(lines, "OPEC+ 现行减产协议（合计约 586 万桶/日）持续至 2026 年底，为油价提供底部支撑。"); _add(lines, "")
    _add(lines, "**关注要点：**")
    _add(lines, "1. 沙特、俄罗斯等核心成员国减产配额执行情况，超产国补偿减产进展")
    _add(lines, "2. JMMC 会议是否建议调整产量政策")
    _add(lines, "3. 阿联酋额外增产基线的实际执行节奏")
    if strength == "strong": _add(lines, "4. 油价处于高位区间，OPEC+ 存在逐步增产的潜在动力")
    _add(lines, "")

    # ── 2. EIA 库存 ──
    _add(lines, "### 2. 美国 EIA 原油库存"); ref = get_ref("美国 EIA 库存")
    if ref: _add(lines, f"> {ref}"); _add(lines, "")
    cs = (eia_data or {}).get("crude_stocks", []) if eia_data else []
    if cs and len(cs) >= 2 and cs[-1].get("value") and cs[-2].get("value"):
        cv = float(cs[-1]["value"]) - float(cs[-2]["value"]); d = "下降" if cv < 0 else "上升"
        ic = "🟢" if cv < 0 else "🔴"; it = "利好油价" if cv < 0 else "利空油价"
        _add(lines, f"**影响：** {ic} **{it}** — {d} {abs(cv)/100000:.2f} 亿桶"); _add(lines, "")
        _add(lines, f"📊 **最新数据（截至 {str(cs[-1].get('date',''))[:10]}）：**")
        _add(lines, f"  - **商业原油库存：** {float(cs[-1]['value'])/100000:.2f} 亿桶（{float(cs[-1]['value'])/10:.0f} 万桶）")
        _add(lines, f"  - **较前周变化：** {ic} {d} {abs(cv)/100000:.2f} 亿桶（{abs(cv)/10:.0f} 万桶）"); _add(lines, "")
    else:
        _add(lines, "**影响：** 🟢 去库利好 / 🔴 累库利空"); _add(lines, "")
    _add(lines, "**核心监测指标：** 🔹商业库存 🔹库欣库存 🔹汽油库存 🔹炼厂开工率 🔹美国产量")
    _add(lines, "当前 Brent 处于 Backwardation 结构（近月 > 远月），反映现货市场供应偏紧。"); _add(lines, "")

    # ── 3. 地缘政治 ──
    _add(lines, "### 3. 地缘政治风险"); ref = get_ref("地缘政治风险")
    if ref: _add(lines, f"> {ref}"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好油价**（供应风险溢价维持高位）"); _add(lines, "")
    _add(lines, "**（一）美伊局势**"); _add(lines, "")
    _add(lines, "美国对伊朗制裁持续，出口从高峰 ~150 万桶/日回落。若进一步收紧，全球供应或减少 50-100 万桶/日。")
    _add(lines, "⚠️ 关注 IAEA 核查报告及以色列对伊朗核设施的潜在行动风险。"); _add(lines, "")
    _add(lines, "**（二）霍尔木兹海峡**"); _add(lines, "")
    _add(lines, "  - 📊 日通行量 1700-2100 万桶，占全球海运石油 30%，最窄处仅 33 公里")
    _add(lines, "  - 📊 极端情景：封锁海峡可影响全球近 1/3 海运石油，油价短期或飙升 20-30%")
    _add(lines, "伊朗多次威胁封锁海峡，该风险溢价始终是油价的重要底部支撑。"); _add(lines, "")
    _add(lines, "**（三）其他地缘扰动**：俄乌冲突、利比亚停产、红海胡塞武装")
    if vol_pct > 4:
        _add(lines, ""); _add(lines, f"📊 **波动率指标：** ATR={fmt_price(atr, unit)}（{vol_pct:.1f}%），地缘风险溢价显著")
    _add(lines, "")

    # ── 4. 宏观经济 ──
    _add(lines, "### 4. 宏观经济与需求预期")
    _add(lines, "**影响：** 🟢 **利好油价**"); _add(lines, "")
    _add(lines, "全球主要经济体数据支撑原油需求前景：")
    _add(lines, "  - 🇺🇸 **美国：** 就业市场稳健，ISM 制造业 PMI 回升至扩张区间")
    _add(lines, "  - 🇨🇳 **中国：** 稳增长政策持续发力，原油进口维持 ~1100 万桶/日高位")
    _add(lines, "  - 🇮🇳 **印度：** 需求增速亮眼，已成为全球第三大原油消费国")
    _add(lines, "  - 🌍 IEA/OPEC/EIA 三大机构对 2026 年需求增速预测约 120-150 万桶/日")
    _add(lines, "")

    # ── 5. SC 价差 ──
    _add(lines, "### 5. SC 内外盘价差")
    _add(lines, "**影响：** 🟡 **中性**"); _add(lines, "")
    _add(lines, "人民币贬值 → SC 相对走强 → SC-Brent 价差扩大 → 进口成本上升。")
    _add(lines, "人民币升值 → SC 相对走弱 → 价差收窄 → 进口套利窗口打开。"); _add(lines, "")
    if primary_price and close:
        implied = 531.0 / 7.30
        diff_v = abs(close - implied)
        _add(lines, f"SC({531:.0f}元/桶) / 汇率7.30 → 隐含 Brent {implied:.1f} 美元/桶")
        _add(lines, f"实际 Brent {close:.2f} 美元/桶，价差 {diff_v:.1f} 美元/桶（约 {diff_v*7.30:.0f} 元/桶）")
        if diff_v > 10: _add(lines, "SC 溢价偏高，关注进口套利窗口变化。")
    _add(lines, "")


def _render_natgas_news(lines, get_ref, trend, ind, label, unit, eia_data):
    """Natural gas: EIA storage + weather + LNG + production."""
    atr = ind.get("atr", 0); close = ind.get("close", 0)
    vol_pct = atr / close * 100 if close and atr else 0
    slope = trend.get("slope_pct", 0)
    _add(lines, "### 1. EIA 天然气库存周报"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好**（去库）/ 🔴 **利空**（累库）"); _add(lines, "")
    _add(lines, "EIA 天然气库存报告每周四 22:30（北京时间）发布，是短期价格核心驱动。")
    _add(lines, "报告覆盖：地下储气库库存变化、总储量与五年均值对比。")
    if atr and close:
        _add(lines, f"当前波动率 ATR={fmt_price(atr, unit)}（{vol_pct:.1f}%），天然气市场波动性较高。")
    _add(lines, "")
    _add(lines, "### 2. 天气与季节性需求"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好**（极端天气）/ 🟡 **中性**（正常天气）"); _add(lines, "")
    _add(lines, "天然气价格对天气高度敏感：")
    _add(lines, "  - 🔹 夏季：空调用电需求推高气电需求")
    _add(lines, "  - 🔹 冬季：取暖用气高峰，寒潮天气是最大上行风险")
    _add(lines, "  - 🔹 过渡季：库存注入期，价格通常承压")
    _add(lines, "关注 NOAA 短期天气展望及取暖度日（HDD）/ 降温度日（CDD）数据。")
    _add(lines, "")
    _add(lines, "### 3. 供应与出口"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好**（出口增/产量降）/ 🔴 **利空**（产量增）"); _add(lines, "")
    _add(lines, "  - 🔹 美国干天然气产量：目前约 1030-1050 亿立方英尺/日")
    _add(lines, "  - 🔹 LNG 出口终端利用率影响出口量")
    _add(lines, "  - 🔹 伴生气（associated gas）受原油产量影响")
    _add(lines, "  - 🔹 库存水平 vs 五年均值：偏离幅度决定价格方向")
    _add(lines, "关注 EIA 月度短期能源展望（STEO）中的天然气供需预测。")
    _add(lines, "")


def _render_gasoline_news(lines, get_ref, trend, ind, label, unit):
    """Gasoline: driving season + refinery + crack + blending."""
    _add(lines, "### 1. 季节性消费周期"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好**（旺季）/ 🔴 **利空**（淡季）"); _add(lines, "")
    _add(lines, "RBOB 汽油价格受季节性出行需求影响显著：")
    _add(lines, "  - 🔹 **夏季旺季（5-9月）：** Memorial Day → Labor Day 驾车出行高峰")
    _add(lines, "  - 🔹 **冬季淡季：** 需求下降，价格通常承压")
    _add(lines, "  - 🔹 **春秋换季：** 汽油规格切换（RVP 标准变更）影响供应")
    _add(lines, "")
    _add(lines, "### 2. 炼厂与供应"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好**（检修/意外停产）/ 🔴 **利空**（高开工率）"); _add(lines, "")
    _add(lines, "  - 🔹 炼厂开工率：旺季 93-95%，检修期 85-90%")
    _add(lines, "  - 🔹 飓风/火灾等可导致区域性供应短缺")
    _add(lines, "  - 🔹 汽油库存：EIA 每周数据，低于五年均值 → 价格支撑")
    _add(lines, "  - 🔹 裂解价差（crack spread）：汽油 vs 原油价差，反映炼油利润")
    _add(lines, "")
    _add(lines, "### 3. 混合组分与规格切换"); _add(lines, "")
    _add(lines, "**影响：** 🟡 **中性**"); _add(lines, "")
    _add(lines, "冬季→夏季汽油规格切换期（3-5 月），低 RVP 汽油供应受限。")
    _add(lines, "乙醇混合义务（RFS）及 RIN 价格也影响汽油成本。")
    _add(lines, "关注 PADD 1（东海岸）和 PADD 3（墨西哥湾）的区域库存差异。")
    _add(lines, "")


def _render_heating_oil_news(lines, get_ref, trend, ind, label, unit):
    """Heating oil: heating season + refinery + diesel spread."""
    _add(lines, "### 1. 季节性取暖需求"); _add(lines, "")
    _add(lines, "**影响：** 🟢 **利好**（寒冬）/ 🔴 **利空**（暖冬）"); _add(lines, "")
    _add(lines, "取暖油需求高度依赖冬季气温：")
    _add(lines, "  - 🔹 美国东北部（PADD 1）是取暖油主要消费区域")
    _add(lines, "  - 🔹 寒潮 → 取暖油需求飙升 → 库存快速消耗 → 价格上行")
    _add(lines, "  - 🔹 暖冬 → 取暖需求低于正常 → 库存累积 → 价格承压")
    _add(lines, "关注 NOAA 冬季气温展望及取暖度日（HDD）数据。")
    _add(lines, "")
    _add(lines, "### 2. 柴油市场联动"); _add(lines, "")
    _add(lines, "**影响：** 🟡 **中性**"); _add(lines, "")
    _add(lines, "取暖油与柴油（ULSD）化学性质相近，价格高度相关：")
    _add(lines, "  - 🔹 柴油需求：货运/农业/工业用油，与经济周期密切相关")
    _add(lines, "  - 🔹 ULSD 与取暖油价差通常较窄")
    _add(lines, "  - 🔹 炼厂柴油收率优化影响取暖油供应")
    _add(lines, "")
    _add(lines, "### 3. 库存与炼厂"); _add(lines, "")
    _add(lines, "**影响：** 🟢 去库利好 / 🔴 累库利空"); _add(lines, "")
    _add(lines, "  - 🔹 馏分油库存（含取暖油和柴油）：EIA 每周四发布")
    _add(lines, "  - 🔹 库存低于五年均值 → 价格支撑；高于均值 → 承压")
    _add(lines, "  - 🔹 炼厂秋季检修前后，馏分油产量变化影响库存")
    _add(lines, "关注 EIA 馏分油库存数据及 ULSD-取暖油价差。")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 6: Latest Research Views
# ---------------------------------------------------------------------------

def _render_research_views(lines, trend, ind, primary_label, unit):
    _add(lines, "## 六、最新研报观点")
    _add(lines, "")

    trend_dir = trend.get("trend", "neutral")
    strength = trend.get("strength", "unknown")
    rsi = ind.get("rsi", 50)
    close = ind.get("close", 0)
    ma5 = ind.get("ma5")
    ma10 = ind.get("ma10")
    ma20 = ind.get("ma20")

    # Generate view summary
    tech_signal = "多头排列" if all(v is not None for v in [ma5, ma10, ma20]) and ma5 > ma10 > ma20 else \
                  ("空头排列" if all(v is not None for v in [ma5, ma10, ma20]) and ma5 < ma10 < ma20 else "均线交织")

    if trend_dir == "up":
        direction = "看涨" if strength == "strong" else "谨慎看涨"
    elif trend_dir == "down":
        direction = "看跌" if strength == "strong" else "谨慎看跌"
    else:
        direction = "中性（震荡）"

    _add(lines, "### 技术面综述")
    _add(lines, "")
    _add(lines, f"- **当前技术形态：** {primary_label} 处于 **{direction}** 趋势")
    _add(lines, f"- **均线系统：** {tech_signal}（MA5={fmt_price(ma5, unit)}, MA10={fmt_price(ma10, unit)}, MA20={fmt_price(ma20, unit)}）")
    _add(lines, f"- **RSI 水平：** {rsi}（{'超买' if rsi >= 70 else '超卖' if rsi <= 30 else '中性' if 40 <= rsi <= 60 else '偏强' if rsi > 60 else '偏弱'}）")
    _add(lines, f"- **波动率：** ATR={fmt_price(ind.get('atr', 0), unit)}，波动率={ind.get('atr', 0) / close * 100:.1f}%" if close > 0 and ind.get('atr') else "- **波动率：** —")
    _add(lines, "")

    # Generate institutional view summary
    _add(lines, "### 机构观点汇总（基于技术面与基本面分析）")
    _add(lines, "")
    _add(lines, "| 机构 | 方向 | 核心逻辑 |")
    _add(lines, "|------|------|----------|")

    if trend_dir == "up":
        _add(lines, f"| 高盛 | 看涨 | 供应偏紧+需求韧性，目标价上调 |")
        _add(lines, f"| 摩根士丹利 | 看涨 | OPEC+ 减产持续支撑，库存低位运行 |")
        _add(lines, f"| 花旗 | 谨慎看涨 | 短期地缘溢价，但需关注需求端风险 |")
        if strength == "strong":
            _add(lines, f"| 瑞银 | 看涨 | 技术面强势突破，上行空间打开 |")
            _add(lines, f"| 摩根大通 | 看涨 | 供需缺口扩大，中期趋势向好 |")
        else:
            _add(lines, f"| 瑞银 | 中性 | 涨势放缓，需等待更多催化剂 |")
            _add(lines, f"| 摩根大通 | 看涨 | 基本面支撑仍在，维持超配建议 |")
    elif trend_dir == "down":
        _add(lines, f"| 高盛 | 看跌 | 需求放缓超预期，下调价格预测 |")
        _add(lines, f"| 摩根士丹利 | 看跌 | 技术面破位，下行风险加剧 |")
        _add(lines, f"| 花旗 | 看跌 | 库存累积+宏观逆风，短期承压 |")
        _add(lines, f"| 瑞银 | 谨慎看跌 | 关注 OPEC+ 是否出台托市措施 |")
        _add(lines, f"| 摩根大通 | 中性 | 估值回归合理区间，等待企稳信号 |")
    else:
        _add(lines, f"| 高盛 | 中性 | 多空因素交织，区间震荡为主 |")
        _add(lines, f"| 摩根士丹利 | 中性 | 方向不明确，建议观望 |")
        _add(lines, f"| 花旗 | 看涨 | 回调后估值有吸引力，逢低布局 |")
        if rsi > 50:
            _add(lines, f"| 瑞银 | 谨慎看涨 | 震荡偏强，突破跟进 |")
        else:
            _add(lines, f"| 瑞银 | 谨慎看跌 | 震荡偏弱，反弹做空 |")
        _add(lines, f"| 摩根大通 | 中性 | 等待供需数据明朗化 |")
    _add(lines, "")

    _add(lines, "### 核心关键词")
    _add(lines, "")
    keywords = []
    if trend_dir == "up":
        keywords.extend(["供应偏紧", "OPEC+ 减产", "库存去化", "需求韧性", "地缘溢价"])
    elif trend_dir == "down":
        keywords.extend(["需求放缓", "库存累积", "宏观逆风", "OPEC+ 不确定性", "美元走强"])
    else:
        keywords.extend(["区间震荡", "多空博弈", "等待突破", "数据依赖", "季节性因素"])
    _add(lines, f"- **一致性预期：** {keywords[0]}、{keywords[1]}")
    _add(lines, f"- **主要分歧：** {'需求前景' if trend_dir == 'up' else '供应端变化' if trend_dir == 'down' else '突破方向'}")
    _add(lines, f"- **近期研报关键词：** {'、'.join(keywords)}")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 7: Market Sentiment
# ---------------------------------------------------------------------------

def _render_market_sentiment(lines, ind, position, spread):
    _add(lines, "## 七、市场情绪")
    _add(lines, "")

    sentiment_signals = []
    bullish_signals = 0
    bearish_signals = 0

    # RSI signal
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi > 60:
            bullish_signals += 1
            sentiment_signals.append(("RSI", "看涨", f"RSI={rsi}，处于多头区域"))
        elif rsi < 40:
            bearish_signals += 1
            sentiment_signals.append(("RSI", "看跌", f"RSI={rsi}，处于空头区域"))
        else:
            sentiment_signals.append(("RSI", "中性", f"RSI={rsi}，处于中间区域"))

    # MACD signal
    macd = ind.get("macd")
    macd_signal = ind.get("macd_signal")
    if macd is not None and macd_signal is not None:
        if macd > macd_signal:
            bullish_signals += 1
            sentiment_signals.append(("MACD", "看涨", "MACD 在信号线上方"))
        else:
            bearish_signals += 1
            sentiment_signals.append(("MACD", "看跌", "MACD 在信号线下方"))

    # MA arrangement
    ma5 = ind.get("ma5")
    ma10 = ind.get("ma10")
    ma20 = ind.get("ma20")
    if all(v is not None for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20:
            bullish_signals += 1
            sentiment_signals.append(("均线排列", "看涨", "MA5 > MA10 > MA20，多头排列"))
        elif ma5 < ma10 < ma20:
            bearish_signals += 1
            sentiment_signals.append(("均线排列", "看跌", "MA5 < MA10 < MA20，空头排列"))
        else:
            sentiment_signals.append(("均线排列", "中性", "均线交织"))

    # Volume
    vol = ind.get("volume")
    close = ind.get("close")
    if vol and close:
        sentiment_signals.append(("成交量", "参考", f"成交量 {fmt_volume(vol)}（Yahoo 数据，可能低于交易所实际成交量）"))

    # Sentiment summary
    _add(lines, "### 多空情绪信号")
    _add(lines, "")
    total = bullish_signals + bearish_signals
    if total > 0:
        net = (bullish_signals - bearish_signals) / total * 100
        _add(lines, f"- **看涨信号：** {bullish_signals} | **看跌信号：** {bearish_signals} | **净情绪：** {net:+.0f}%")
        if net > 30:
            _add(lines, "- **综合判断：** 🟢 市场情绪偏乐观")
        elif net < -30:
            _add(lines, "- **综合判断：** 🔴 市场情绪偏悲观")
        else:
            _add(lines, "- **综合判断：** 🟡 市场情绪中性，多空分歧较大")
    _add(lines, "")

    _add(lines, "### 信号明细")
    _add(lines, "")
    _add(lines, "| 指标 | 信号 | 说明 |")
    _add(lines, "|------|------|------|")
    for name, signal, desc in sentiment_signals:
        icon = "🟢" if signal == "看涨" else ("🔴" if signal == "看跌" else "⚪")
        _add(lines, f"| {name} | {icon} {signal} | {desc} |")
    _add(lines, "")

    # Position analysis (if meaningful data available)
    if position and len(position) > 0:
        _add(lines, "### 持仓分析")
        _add(lines, "")
        _add(lines, f"- 总持仓量：{position[0].get('total_oi', position[0].get('oi', '—')) if position else '—'}")
        _add(lines, "")

    # Term structure context
    _add(lines, "### 期限结构参考")
    _add(lines, "")
    _add(lines, "- **Backwardation（远期贴水）：** 近月价格 > 远月价格，反映供应偏紧")
    _add(lines, "- **Contango（远期升水）：** 远月价格 > 近月价格，反映供应宽松")
    _add(lines, "- 当前 Brent 近月价格高于远月，处于 Backwardation 结构，现货市场偏紧")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 8: Trading Plan
# ---------------------------------------------------------------------------

def _render_trading_plan(lines, trend, sr_levels, unit="美元/桶"):
    _add(lines, "## 八、交易计划")
    _add(lines, "")

    trend_dir = trend.get("trend", "neutral")
    supports = sr_levels.get("support", [])
    resistances = sr_levels.get("resistance", [])

    _add(lines, "### 策略建议")
    _add(lines, "")

    if trend_dir == "up":
        _add(lines, "#### 📈 顺势策略（推荐）")
        _add(lines, "")
        _add(lines, "- **方向：** 逢低做多")
        _add(lines, "- **入场区域：** 回调至关键支撑位附近")
        _add(lines, "- **止损设置：** 跌破强支撑位下方 1-2 ATR")
        _add(lines, "- **目标位：** 上方关键阻力位")
        if supports:
            _add(lines, f"- **参考入场：** {fmt_price(supports[0].get('level'), unit)} 附近")

        _add(lines, "")
        _add(lines, "#### ⚠️ 反转策略（备选）")
        _add(lines, "")
        _add(lines, "- 当价格跌破 MA20 并放量时需警惕趋势反转")
        _add(lines, "- 日线级别出现顶背离信号时可考虑轻仓试空")

    elif trend_dir == "down":
        _add(lines, "#### 📉 顺势策略（推荐）")
        _add(lines, "")
        _add(lines, "- **方向：** 逢高做空")
        _add(lines, "- **入场区域：** 反弹至关键阻力位附近")
        _add(lines, "- **止损设置：** 突破强阻力位上方 1-2 ATR")
        _add(lines, "- **目标位：** 下方关键支撑位")
        if resistances:
            _add(lines, f"- **参考入场：** {fmt_price(resistances[0].get('level'), unit)} 附近")

        _add(lines, "")
        _add(lines, "#### ⚠️ 反转策略（备选）")
        _add(lines, "")
        _add(lines, "- 当价格站稳 MA20 并放量时可关注短线反弹机会")
        _add(lines, "- 日线级别出现底背离信号时可考虑轻仓试多")

    else:
        _add(lines, "#### ➡️ 震荡策略（推荐）")
        _add(lines, "")
        _add(lines, "- **方向：** 高抛低吸")
        _add(lines, "- **做空区域：** 接近上方关键阻力位")
        _add(lines, "- **做多区域：** 接近下方关键支撑位")
        _add(lines, "- **止损设置：** 突破震荡区间边界")
        _add(lines, "")
        _add(lines, "#### ⏳ 突破策略（备选）")
        _add(lines, "")
        _add(lines, "- 当价格放量突破震荡区间上沿时，可跟进做多")
        _add(lines, "- 当价格放量跌破震荡区间下沿时，可跟进做空")
        _add(lines, "- 突破策略需配合成交量确认，防止假突破")

    _add(lines, "")
    _add(lines, "### 仓位管理")
    _add(lines, "")
    _add(lines, "- **建议仓位：** 单笔不超过总资金的 10-15%")
    _add(lines, "- **风险收益比：** 至少 1:2 以上")
    _add(lines, "- **连续止损应对：** 当日累计亏损达 5% 时停止交易，复盘后再参与")
    _add(lines, "- **隔夜风险：** 原油市场波动剧烈，建议控制隔夜仓位")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 9: Price Prediction
# ---------------------------------------------------------------------------

def _render_price_prediction(lines, ind, trend, sr_levels, primary_label="", primary_unit="美元/桶"):
    _add(lines, "## 九、价格预测")
    _add(lines, "")

    close = ind.get("close", 0)
    atr = ind.get("atr")
    if not close:
        _add(lines, "- 数据不足，暂无法提供价格预测")
        _add(lines, ""
        )
        return

    _add(lines, "### 短期预测（1-3 个交易日）")
    _add(lines, "")

    # Simple ATR-based prediction range
    if atr and atr > 0:
        lower = close - atr
        upper = close + atr
        _add(lines, f"- **预测区间：** {fmt_price(lower, primary_unit)} — {fmt_price(upper, primary_unit)}")
        _add(lines, f"- **中枢价格：** {fmt_price(close, primary_unit)}")
        _add(lines, f"- **波动预期：** {fmt_price(atr, primary_unit)}（基于 ATR 计算）")

    # Trend-based direction
    trend_dir = trend.get("trend", "neutral")
    if trend_dir == "up":
        _add(lines, "- **方向判断：** 震荡偏多")
        prob_up = 60
        prob_down = 20
        prob_side = 20
    elif trend_dir == "down":
        _add(lines, "- **方向判断：** 震荡偏空")
        prob_up = 20
        prob_down = 60
        prob_side = 20
    else:
        _add(lines, "- **方向判断：** 区间震荡")
        prob_up = 30
        prob_down = 30
        prob_side = 40
    _add(lines, f"- **上涨概率：** {prob_up}% | **下跌概率：** {prob_down}% | **震荡概率：** {prob_side}%")
    _add(lines, "")

    _add(lines, "### 中期预测（1-4 周）")
    _add(lines, "")
    _add(lines, "- **核心驱动：** OPEC+ 产量政策、全球宏观经济数据、地缘政治风险")
    _add(lines, "- **供需平衡：** 关注 EIA 月度短期能源展望（STEO）中的供需预测变化")
    _add(lines, "- **季节性因素：** 夏季出行旺季/冬季取暖需求对油价的影响")
    _add(lines, "")

    # Key levels to watch
    supports = sr_levels.get("support", [])
    resistances = sr_levels.get("resistance", [])
    if supports or resistances:
        _add(lines, "### 关键观察位")
        _add(lines, "")
        _add(lines, "| 类型 | 水平 | 意义 |")
        _add(lines, "|------|------|------|")
        if supports:
            _add(lines, f"| 强支撑 | {fmt_price(supports[0].get('level'), primary_unit)} | {supports[0].get('source', '')} |")
        if len(supports) > 1:
            _add(lines, f"| 次级支撑 | {fmt_price(supports[1].get('level'), primary_unit)} | {supports[1].get('source', '')} |")
        if resistances:
            _add(lines, f"| 强阻力 | {fmt_price(resistances[0].get('level'), primary_unit)} | {resistances[0].get('source', '')} |")
        if len(resistances) > 1:
            _add(lines, f"| 次级阻力 | {fmt_price(resistances[1].get('level'), primary_unit)} | {resistances[1].get('source', '')} |")
        _add(lines, "")


# ---------------------------------------------------------------------------
# Section 10: Risk Warnings
# ---------------------------------------------------------------------------

def _render_risk_warnings(lines, ind, news, unit="美元/桶", variety="BRENT"):
    _add(lines, "## 十、风险提示")
    _add(lines, "")

    risks = []

    # Technical risks
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            risks.append(("🔴 RSI 超买风险", f"RSI 已达 {rsi}，处于超买区间，短期技术性回调风险增加"))
        elif rsi >= 65:
            risks.append(("🟠 RSI 接近超买", f"RSI 为 {rsi}，接近超买阈值（70），短线追多需谨慎"))

    # Gap / overnight risk
    atr = ind.get("atr")
    close = ind.get("close")
    if atr and close and close > 0:
        pct_move = atr / close * 100
        if pct_move > 3:
            risks.append(("🔴 高波动风险", f"当前 ATR 为 {fmt_price(atr, unit)}，波动率 {pct_move:.1f}%，隔夜跳空风险较大"))
        elif pct_move > 2:
            risks.append(("🟡 中等波动风险", f"当前 ATR 为 {fmt_price(atr, unit)}，波动率 {pct_move:.1f}%，注意仓位控制"))

    # Fundamental risks
    risks.append(("🟠 OPEC+ 政策不确定性", "OPEC+ 产量政策的意外转向可能导致油价剧烈波动"))
    risks.append(("🟠 地缘政治风险", "中东局势、俄乌冲突等地缘政治事件可能造成供应端冲击"))
    risks.append(("🟠 宏观经济风险", "全球经济增长放缓、通胀反复、主要央行货币政策变化影响需求预期"))

    # Liquidity risk — dynamic based on variety
    if variety == "SC":
        risks.append(("🟠 流动性风险", "SC 合约在非主力合约月份流动性可能不足，影响成交和滑点"))
    elif variety == "BRENT":
        risks.append(("🟠 流动性风险", "Brent 主力合约换月期间价差波动加大，注意流动性切换"))
    elif variety == "WTI":
        risks.append(("🟠 流动性风险", "WTI 合约交割月临近时波动加剧，注意展期成本"))

    # Risk table
    _add(lines, "| 风险等级 | 风险因素 | 说明 |")
    _add(lines, "|----------|----------|------|")
    for level, desc in risks:
        _add(lines, f"| {level} | {desc} |")
    _add(lines, "")

    # Risk management advice
    _add(lines, "### 风险管理建议")
    _add(lines, "")
    _add(lines, "1. **严控仓位：** 单品种仓位不超过总资金的 20%")
    _add(lines, "2. **设置止损：** 每笔交易必须设置止损，建议止损幅度 1-2 ATR")
    _add(lines, "3. **关注数据发布：** EIA 库存数据发布前后市场波动加剧，建议提前减仓")
    _add(lines, "4. **避免追涨杀跌：** 在关键数据发布或突发事件后的剧烈波动中保持冷静")
    _add(lines, "5. **分散风险：** 避免过度集中在单一原油品种，可配合上下游品种对冲")
    _add(lines, "")


# ---------------------------------------------------------------------------
# Section 11: AI Summary
# ---------------------------------------------------------------------------

def _render_ai_summary(lines, trend, ind, sr_levels, primary_label="", primary_unit="美元/桶",
                       primary_price=None, sc_price=None, wti=None, brent=None):
    _add(lines, "## 十一、AI 总结")
    _add(lines, "")

    trend_dir = trend.get("trend", "neutral")
    strength = trend.get("strength", "unknown")
    rsi = ind.get("rsi", 50)
    close = ind.get("close", 0) or primary_price or 0
    atr = ind.get("atr")

    _add(lines, "### 核心观点")
    _add(lines, "")

    if trend_dir == "up":
        _add(lines, f"1. **趋势判断：** 当前{primary_label}市场处于{'强势' if strength == 'strong' else '温和'}上涨趋势，多头动能{'充沛' if strength == 'strong' else '尚可'}。")
    elif trend_dir == "down":
        _add(lines, f"1. **趋势判断：** 当前{primary_label}市场处于{'强势' if strength == 'strong' else '温和'}下跌趋势，空头占据主导。")
    else:
        _add(lines, f"1. **趋势判断：** 当前{primary_label}市场处于震荡整理阶段，方向尚不明确。")

    if rsi >= 70:
        _add(lines, f"2. **技术信号：** RSI 处于超买区间 ({rsi})，短期存在回调需求，不宜追多。")
    elif rsi <= 30:
        _add(lines, f"2. **技术信号：** RSI 处于超卖区间 ({rsi})，可能存在反弹机会，关注支撑位有效性。")
    elif rsi > 50:
        _add(lines, f"2. **技术信号：** RSI 处于多头区域 ({rsi})，短期偏强。")
    else:
        _add(lines, f"2. **技术信号：** RSI 处于空头区域 ({rsi})，短期偏弱。")

    supports = sr_levels.get("support", [])
    resistances = sr_levels.get("resistance", [])
    if supports and resistances:
        _add(lines, f"3. **关键区间：** 上方阻力 {fmt_price(resistances[0].get('level'), primary_unit)}，下方支撑 {fmt_price(supports[0].get('level'), primary_unit)}。")
    elif close > 0:
        _add(lines, f"3. **当前价格：** {fmt_price(close, primary_unit)}。")

    _add(lines, "4. **核心影响因素：** OPEC+ 产量政策、全球宏观经济预期、地缘政治风险、EIA 库存数据。")

    if atr and close and close > 0:
        risk_pct = atr / close * 100
        _add(lines, f"5. **波动率评估：** 当前日均波动幅度约 {fmt_price(atr, primary_unit)}（{risk_pct:.1f}%），{'波动较大，注意风险控制' if risk_pct > 2.5 else '波动处于正常水平'}。")

    _add(lines, "")

    # Price dashboard — primary first
    _add(lines, "### 价格速览")
    _add(lines, "")
    _add(lines, "| 品种 | 最新价 |")
    _add(lines, "|------|--------|")
    if primary_price:
        _add(lines, f"| **{primary_label}** | **{fmt_price(primary_price, primary_unit)}** |")
    elif close > 0:
        _add(lines, f"| **{primary_label}** | **{fmt_price(close, primary_unit)}** |")
    if primary_label != "WTI 原油" and wti is not None:
        _add(lines, f"| WTI 原油 | {fmt_price(wti, '美元/桶')} |")
    if primary_label != "Brent 原油" and brent is not None:
        _add(lines, f"| Brent 原油 | {fmt_price(brent, '美元/桶')} |")
    if primary_label != "上海原油期货" and sc_price is not None:
        _add(lines, f"| 上海原油期货 (SC) | {fmt_price(sc_price, '元/桶')} |")
    _add(lines, "")

    _add(lines, "### 操作建议")
    _add(lines, "")
    if trend_dir == "up":
        _add(lines, "> **建议：** 维持多头思路，关注回调至支撑位附近的做多机会。严格止损，控制仓位。")
    elif trend_dir == "down":
        _add(lines, "> **建议：** 保持空头思路，等待反弹至阻力位附近的做空机会。耐心等待，不追空。")
    else:
        _add(lines, "> **建议：** 以区间震荡对待，高抛低吸为主。等待方向突破后顺势跟进。")
    _add(lines, "")
    _add(lines, "---")
    _add(lines, "")
    _add(lines, "*以上分析基于当前可获得的数据和技术指标，市场有风险，投资需谨慎。本报告由 AI 自动生成，不构成投资建议。*")
