"""Render a self-contained offline HTML research report."""

from __future__ import annotations

import json
import os
import re
from html import escape
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "report_template.html"

_REPORT_EXTENSION_SCRIPT = r'''<style>
.detail-charts{grid-column:1/-1;display:block;margin:2px 0 12px}
.data-completeness-toggle{display:block;width:100%;padding:8px 10px;border:1px solid #d7ad67;border-radius:4px;background:#fffaf0;color:#654717;cursor:pointer;font-weight:700;text-align:left}.data-completeness-content{padding-top:8px}
.trajectory-matrix{margin:0 0 16px;padding:18px 20px;background:#fff;border:1px solid var(--line);border-radius:4px 14px 4px 4px;box-shadow:0 8px 24px rgba(20,45,55,.05)}
.trajectory-matrix h2,.consensus-state-module h3{margin:0;font:700 18px "STSong","Songti SC",Georgia,serif}.trajectory-matrix .sub{margin:3px 0 12px}.trajectory-wrap{max-height:520px;overflow:auto;position:relative;border:1px solid #edf1ee}.trajectory-table{min-width:1420px;table-layout:fixed;border-collapse:separate;border-spacing:0}.trajectory-table th,.trajectory-table td{box-sizing:border-box;display:table-cell;text-align:center;vertical-align:top}.trajectory-table th{position:sticky;top:0;z-index:3;background:#f8faf7}.trajectory-table th:first-child,.trajectory-table td:first-child{position:sticky;left:0;z-index:2;width:220px;min-width:220px;background:#fff;text-align:left}.trajectory-table th:nth-child(2),.trajectory-table td:nth-child(2){position:sticky;left:220px;z-index:2;width:210px;min-width:210px;background:#fff;text-align:left}.trajectory-table th:nth-child(n+3),.trajectory-table td:nth-child(n+3){min-width:104px;width:104px}.trajectory-table th:first-child,.trajectory-table th:nth-child(2){z-index:4;background:#f8faf7}.trajectory-table td:nth-child(2){max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trajectory-signal{display:block;white-space:nowrap;font:700 11px/1.45 Consolas,"Microsoft YaHei",sans-serif}.trajectory-signal.positive{color:var(--green)}.trajectory-signal.negative{color:var(--red)}.trajectory-signal.flat{color:var(--muted)}.trajectory-signal.unavailable{color:var(--muted)}.trajectory-empty{padding:22px;text-align:center;color:var(--muted);background:#f5f7f4}.consensus-state-module{grid-column:1/-1;margin:4px 0 12px;padding:16px;background:#f8fbf8;border:1px solid #dbe5df;border-radius:3px 12px 3px 3px}.consensus-state-module h3{font-size:15px}.state-disclaimer{margin:5px 0 10px;color:var(--muted);font-size:11px}.state-list{display:grid;gap:9px}.state-card{padding:11px;background:#fff;border-left:3px solid var(--blue)}.state-label{display:inline-block;padding:2px 7px;border-radius:999px;background:#edf5f1;color:#245649;font-size:11px;font-weight:700}.state-card p{margin:7px 0 0;font-size:12px}.state-card details{margin-top:8px}.state-card summary{font-size:11px}.state-card pre{margin:7px 0 0;padding:8px;overflow:auto;background:#f5f7f4;color:var(--ink);font:10px/1.5 Consolas,monospace;white-space:pre-wrap}.state-metadata{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0;color:var(--muted);font-size:11px}.state-metadata span{padding:2px 6px;background:#edf3ef}@media(max-width:560px){.trajectory-wrap{max-height:420px}}
.trajectory-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 10px}.trajectory-toolbar label{font-size:12px;font-weight:700}.trajectory-search{min-width:220px;flex:1;padding:7px 9px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink)}.trajectory-search-count{color:var(--muted);font-size:12px}.trajectory-search-empty{margin:0 0 10px;padding:10px;text-align:center;color:var(--muted);background:#f5f7f4}.security-trajectory{grid-column:1/-1;margin:4px 0 12px;padding:16px;background:#fff;border:1px solid var(--line);border-radius:3px 12px 3px 3px}.security-trajectory h3{margin:0 0 4px;font:700 15px "STSong","Songti SC",Georgia,serif}.security-trajectory-wrap{overflow:auto;border:1px solid #edf1ee}.security-trajectory-table{min-width:520px;width:100%;border-collapse:collapse}.security-trajectory-table th,.security-trajectory-table td{padding:8px;border-bottom:1px solid #edf1ee;text-align:left}.security-trajectory-table th{background:#f8faf7;font-size:12px}@media(max-width:560px){.trajectory-search{min-width:100%}}
.detail-charts .chart-card{width:100%}
.detail-charts .rating-row{grid-template-columns:minmax(88px,110px) minmax(220px,1fr) minmax(64px,76px);gap:10px}
.detail-charts .rating-track{min-width:0}
.evidence-chart{grid-column:1/-1}
.time-disclosure{margin:0 0 18px;padding:18px 20px;background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:4px 14px 4px 4px;box-shadow:0 8px 24px rgba(20,45,55,.05)}
.time-disclosure h2,.eligibility-funnels h2{margin:0;font:700 18px "STSong","Songti SC",Georgia,serif}
.time-disclosure>p,.eligibility-funnels>p{margin:3px 0 12px;color:var(--muted);font-size:11px}
.time-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}
.time-item{padding:11px;background:#f5f7f4;border-top:3px solid var(--blue);min-width:0}
.time-item span{display:block;color:var(--muted);font-size:10px}.time-item strong{display:block;margin-top:3px;font:700 12px/1.5 Consolas,"Microsoft YaHei",sans-serif;word-break:break-word}
.eligibility-funnels{margin:16px 0 0;padding:18px 20px;background:#fff;border:1px solid var(--line);border-radius:4px 14px 4px 4px}
.funnel-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.funnel-card{padding:13px;background:#f8faf7;border:1px solid #dfe7e2}.funnel-card h3{margin:0 0 10px;font-size:13px}
.funnel-track{display:flex;gap:8px;align-items:stretch}.funnel-stage{position:relative;flex:1;min-width:0;padding:9px 7px;background:#edf3ef;border-top:3px solid var(--green);text-align:center}.funnel-stage:not(:last-child):after{content:"›";position:absolute;right:-7px;top:50%;z-index:1;transform:translateY(-50%);color:var(--muted);font-size:17px}.funnel-stage span{display:block;min-height:34px;color:var(--muted);font-size:9px;line-height:1.35}.funnel-stage b{display:block;font:700 18px Consolas,monospace}.funnel-stage small{display:block;color:var(--muted);font-size:9px}
#coverageChangeEvidence.significant{border-color:#d7ad67;background:#fffaf0}#coverageChangeEvidence.significant h3{background:#fff0cf}
.event-market-overview{margin:0 0 18px;padding:18px 20px;background:#fff;border:1px solid var(--line);border-radius:4px 14px 4px 4px;box-shadow:0 8px 24px rgba(20,45,55,.05)}
.event-market-overview h2,.event-timeline>h3{margin:0;font:700 18px "STSong","Songti SC",Georgia,serif}.event-market-overview>p,.event-timeline>.sub{margin:3px 0 12px;color:var(--muted);font-size:11px}
.event-overview-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.event-overview-item{padding:11px;background:#f5f7f4;border-top:3px solid var(--blue);min-width:0}.event-overview-item span{display:block;color:var(--muted);font-size:10px}.event-overview-item strong{display:block;margin-top:3px;font:700 12px/1.5 Consolas,"Microsoft YaHei",sans-serif;word-break:break-word}
.event-context-filters{display:flex;align-items:center;gap:6px;overflow-x:auto;margin:-5px 0 12px;padding:5px 1px}.event-context-filters>span{flex:0 0 auto;color:var(--muted);font-size:11px}.event-filter-chip{flex:0 0 auto;padding:5px 9px;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--ink);cursor:pointer;font-size:11px}.event-filter-chip.active{border-color:var(--blue);background:#edf5f8;color:var(--navy)}
.event-context-head,.event-context-cell{text-align:left}.event-context-head{min-width:230px}.event-context-cell{min-width:230px;max-width:330px;vertical-align:top}.event-snippet{padding:3px 0;border-bottom:1px dotted #d8e1dc;color:var(--ink);font-size:10px;line-height:1.45}.event-snippet:last-child{border-bottom:0}.event-snippet time{color:var(--blue);font-family:Consolas,monospace}.event-snippet .event-category-label{color:var(--muted)}.event-estimated,.event-availability{display:inline-block;margin-left:5px;padding:1px 5px;border-radius:999px;background:#fff0cf;color:#744d12;font-size:9px}.event-availability{margin:0 0 3px;background:#fff4dc}.event-filter-empty{padding:12px;color:var(--muted);text-align:center;font-size:11px}
.event-timeline{grid-column:1/-1;margin:4px 0 12px;padding:18px 20px;background:#fff;border:1px solid var(--line);border-radius:4px 14px 4px 4px}.event-timeline-state{margin:0 0 10px;padding:8px 10px;border-left:3px solid var(--amber);background:#fffaf0;color:#654717;font-size:11px}.event-timeline-list{position:relative;display:grid;gap:9px;margin:0;padding:0 0 0 18px}.event-timeline-list:before{content:"";position:absolute;left:5px;top:8px;bottom:8px;width:1px;background:#9db4aa}.event-card{position:relative;display:grid;grid-template-columns:minmax(108px,126px) 1fr;gap:12px;padding:12px 13px;background:#f8faf7;border:1px solid #dfe7e2;border-radius:2px 10px 2px 2px}.event-card:before{content:"";position:absolute;left:-18px;top:18px;width:9px;height:9px;border:2px solid #fff;border-radius:50%;background:var(--blue);box-shadow:0 0 0 1px var(--blue)}.event-card[data-category="financial"]:before{background:var(--green);box-shadow:0 0 0 1px var(--green)}.event-card[data-category="meeting"]:before,.event-card[data-category="capital_market"]:before{background:var(--amber);box-shadow:0 0 0 1px var(--amber)}.event-card-date{font:700 12px/1.45 Consolas,monospace;color:var(--navy)}.event-card-date small{display:block;color:var(--muted);font:10px/1.4 "Microsoft YaHei",sans-serif}.event-card-body{min-width:0}.event-card-badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:4px}.event-category-badge,.event-type-badge{padding:2px 6px;border-radius:999px;background:#e8f1ed;color:#245649;font-size:9px}.event-type-badge{background:#eef2f3;color:#51636b}.event-card-title{margin:0 0 6px!important;font:700 13px/1.5 "Microsoft YaHei",sans-serif!important;word-break:break-word}.event-card-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 12px;color:var(--muted);font-size:10px}.event-card-meta span{word-break:break-word}.event-expand{margin:11px 0 0 18px;padding:7px 11px;border:1px solid var(--blue);border-radius:7px;background:#fff;color:var(--blue);cursor:pointer}.event-empty{padding:24px 12px;text-align:center;background:#f5f7f4;color:var(--muted)}
.event-data-completeness{margin-top:12px;padding-top:10px;border-top:1px solid #e1e8e3}.event-data-completeness h3{margin:0 0 6px;font:700 13px "Microsoft YaHei",sans-serif}.event-completeness-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 12px;margin:7px 0}.event-completeness-grid span{color:var(--muted);font-size:10px}.event-completeness-grid b{float:right;color:var(--ink);font:700 11px Consolas,monospace}.event-interface-table th,.event-interface-table td{text-align:left}.event-interface-table th{position:static}.event-stale-warning{color:#744d12!important}.sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
@media(max-width:560px){.detail-charts .rating-row{grid-template-columns:minmax(78px,82px) minmax(0,1fr) minmax(58px,62px);gap:8px}}
@media(max-width:980px){.time-grid{grid-template-columns:1fr 1fr}.funnel-grid{grid-template-columns:1fr}.funnel-track{display:grid;grid-template-columns:1fr}.funnel-stage{text-align:left;padding-left:12px}.funnel-stage span{min-height:0}.funnel-stage:not(:last-child):after{content:"↓";right:10px;top:auto;bottom:-12px;transform:none}}
@media(max-width:760px){.event-overview-grid{grid-template-columns:1fr}.event-card{grid-template-columns:1fr}.event-card-meta,.event-completeness-grid{grid-template-columns:1fr}.event-context-cell{min-width:190px}.event-interface-table{display:block;overflow-x:auto;white-space:nowrap}}
@media(max-width:560px){.time-grid{grid-template-columns:1fr}}
</style>
<script>
(function () {
  const purposeMap = {
    get_hk_detail: "证券名称、状态、类型与行业身份", get_us_detail: "证券名称、状态、类型与行业身份",
    get_stock_ncycl_consensus: "目标价一致预期", get_stock_ncycl_estimate: "目标价一致预期",
    get_stock_recommendation_consensus: "评级一致预期", get_stock_recommendation_estimate: "评级一致预期",
    get_hk_daily: "收盘价与日行情", get_us_daily: "收盘价与日行情", get_last_trade_date: "最近交易日探测",
    get_stock_dividend_event: "港股分红拆股事件", get_stock_market_event: "港股资本市场事件",
    get_stock_meeting_event: "港股公司会议事件", get_stock_financial_event: "港股财务披露事件",
    get_stock_ir_event: "港股投资者关系事件", get_stock_dividend_activity: "美股分红拆股活动",
    get_stock_market_activity: "美股资本市场活动", get_stock_meeting_activity: "美股公司会议活动",
    get_stock_financial_activity: "美股财务披露活动", get_stock_ir_activity: "美股投资者关系活动",
  };
  const categoryLabels = {
    financial: "财务披露", ir: "投资者关系", meeting: "公司会议",
    capital_market: "资本市场", dividend: "分红拆股",
  };
  const categoryFilters = [
    ["all", "全部"], ["financial", "财务披露"], ["ir", "投资者关系"],
    ["meeting", "公司会议"], ["capital_market", "资本市场"], ["dividend", "分红拆股"],
  ];
  let eventCategory = "all";
  const finite = value => value === null || value === undefined || value === "" ? null
    : Number.isFinite(Number(value)) ? Number(value) : null;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
  const activeMarket = () => document.querySelector("#marketTabs .active")?.dataset.m
    || Object.keys(window.REPORT_DATA.markets || {})[0] || "hk";
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const displayValue = value => value === null || value === undefined || value === "" ? "—" : String(value);
  const validEvents = market => (market.events || []).filter(event =>
    event.validation_status === "valid" && event.time_status !== "invalid_date"
  );
  const eventsForSymbol = (market, symbol) => validEvents(market)
    .filter(event => String(event.symbol) === String(symbol));
  const compactDate = value => String(value ?? "").replace(/\D/g, "").slice(0, 8);
  const formatDate = value => {
    const date = compactDate(value);
    return date.length === 8 ? date.slice(0, 4) + "-" + date.slice(4, 6) + "-" + date.slice(6) : displayValue(value);
  };
  const dateOrdinal = value => {
    const date = compactDate(value);
    if (date.length !== 8) return Number.POSITIVE_INFINITY;
    return Date.UTC(Number(date.slice(0, 4)), Number(date.slice(4, 6)) - 1, Number(date.slice(6))) / 86400000;
  };
  const eventDateRange = event => compactDate(event.start_date) === compactDate(event.end_date)
    ? formatDate(event.start_date) : formatDate(event.start_date) + " — " + formatDate(event.end_date);
  const interfaceDiagnostics = market => market.event_context?.interface_diagnostics || [];
  const eventModuleState = market => {
    const context = market.event_context || {};
    const payloadState = context.status;
    if (payloadState === "disabled") return "disabled";
    if (payloadState === "partial") return "partial";
    if (payloadState === "unavailable") return "unavailable";
    if (payloadState === "empty") return "empty";
    if (payloadState === "available") return validEvents(market).length ? "available" : "empty";
    const diagnostics = interfaceDiagnostics(market);
    const allFailed = diagnostics.length > 0 && diagnostics.every(item =>
      item.status === "failed" || item.status === "not_called"
    );
    if (!context.event_reference_date || allFailed) return "unavailable";
    if (diagnostics.some(item => item.status === "failed" || item.status === "partial")) return "partial";
    return validEvents(market).length ? "available" : "empty";
  };
  const eventStateLabel = state => ({
    empty: "当前窗口无事件", partial: "事件接口部分可用",
    unavailable: "事件模块不可用", disabled: "事件模块已关闭",
  })[state] || "事件数据可用";
  const formatNumber = value => finite(value) === null ? "—" : finite(value).toFixed(0);
  const formatSigned = value => finite(value) === null ? "—" : (finite(value) > 0 ? "+" : "") + finite(value).toFixed(0);
  const formatPercent = value => finite(value) === null ? "—" : (finite(value) > 0 ? "+" : "") + (finite(value) * 100).toFixed(1) + "%";
  const card = (role, title, subtitle) => {
    const node = make("section", undefined, "chart-card");
    node.id = role === "target" ? "targetPositionChart" : "ratingDistributionChart";
    node.setAttribute("data-chart-role", role);
    node.append(make("h3", title));
    if (subtitle) node.append(make("p", subtitle));
    return node;
  };
  function renderSourceProvenance() {
    const box = document.querySelector("#dataAlert");
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    const interfaces = (market.source_interfaces || market.sources || []).map(item =>
      typeof item === "string" ? { interface: item, purpose: purposeMap[item] || "PandaData 数据接口" } : item
    ).filter(item => item && item.interface);
    if (!box) return;
    box.querySelector("#dataCompletenessFallback")?.remove();
    box.querySelector("#sourceProvenance")?.remove();
    box.querySelector("#qualityGovernance")?.remove();
    if (!interfaces.length) return;
    if (!box.querySelector("strong")) {
      box.insertAdjacentHTML("afterbegin", "<strong>数据完整性</strong><p>本报告的原始数据仅来自 PandaData。</p>");
    }
    const section = make("section", undefined, "source-provenance");
    section.id = "sourceProvenance";
    section.append(make("h3", "数据来源与接口"));
    section.append(make("p", "原始数据全部来自 PandaData；本市场本次运行实际调用以下接口，不使用其他数据源补值。"));
    const table = make("table", undefined, "source-table");
    table.innerHTML = "<thead><tr><th>接口</th><th>用途</th></tr></thead><tbody>" + interfaces.map(item =>
      "<tr><td><code>" + esc(item.interface) + "</code></td><td>" + esc(item.purpose || purposeMap[item.interface] || "PandaData 数据接口") + "</td></tr>"
    ).join("") + "</tbody>";
    section.append(table);
    const quality = market.quality || {};
    const governance = make("section", undefined, "source-provenance");
    governance.id = "qualityGovernance";
    governance.append(make("h3", "股票池与一致性校验"));
    const details = [
      "核心股票池 " + (quality.core_universe_rows ?? 0) + " 条",
      "排除但保留诊断 " + (quality.excluded_universe_rows ?? 0) + " 条",
      "目标价可排名 " + (quality.eligible_rows ?? 0) + " 条（最低覆盖 " + (market.overview?.min_analysts ?? window.REPORT_DATA.min_analysts ?? 5) + "）",
      "评级可排名 " + (quality.rating_eligible_rows ?? 0) + " 条（最低覆盖 " + (market.overview?.min_recommendations ?? window.REPORT_DATA.min_recommendations ?? 5) + "）",
      "一致性错误 " + (quality.validation_error_rows ?? 0) + " 条",
      "一致性警告 " + (quality.validation_warning_rows ?? 0) + " 条",
      "部分可验证 " + (quality.validation_partial_rows ?? 0) + " 条",
      "币种不可比 " + (quality.currency_unverified_rows ?? 0) + " 条",
    ];
    governance.append(make("p", details.join("；") + "。异常记录保留原始 PandaData 值，只从受影响榜单排除。"));
    const reasonLabels = {
      inactive_security: "非在市证券", unknown_security_status: "状态未知",
      unknown_security_type: "类型未知", non_ordinary_security: "非普通股",
      missing_security_detail: "证券详情缺失", outside_core_universe: "核心股票池外",
      not_returned_by_api: "接口未返回", no_recent_trade: "近期无有效交易",
      invalid_or_nonpositive: "价格无效或非正数",
    };
    const reasonSummary = (values, prefix) => Object.entries(values || {}).map(([key, value]) =>
      prefix + (reasonLabels[key] || key) + " " + value + " 条"
    );
    const reasons = [
      ...reasonSummary(quality.universe_exclusion_reasons, "股票池："),
      ...reasonSummary(quality.price_missing_reasons, "价格："),
    ];
    if (reasons.length) governance.append(make("p", "原因分类：" + reasons.join("；") + "。"));
    box.classList.add("show");
    box.append(governance, section);
  }
  function renderEventDataCompleteness() {
    const box = document.querySelector("#dataAlert");
    if (!box) return;
    box.querySelector("#eventDataCompleteness")?.remove();
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    if (!Object.prototype.hasOwnProperty.call(market, "event_context")) return;
    const context = market.event_context || {};
    const section = make("section", undefined, "event-data-completeness");
    section.id = "eventDataCompleteness";
    section.append(make("h3", "事件数据完整性"));
    const grid = make("div", undefined, "event-completeness-grid");
    const unexpectedSymbolRows = context.unexpected_symbol_rows
      ?? (market.events || []).filter(event => event.validation_status === "unexpected_symbol").length;
    const facts = [
      ["请求证券", context.requested_symbol_count], ["接口返回记录", context.returned_rows],
      ["窗口展示记录", context.display_event_rows], ["无效记录", context.invalid_rows],
      ["意外证券记录", unexpectedSymbolRows], ["窗口外记录", context.outside_display_window_rows],
      ["返回证券", context.returned_symbol_count], ["有事件证券", context.symbols_with_display_events],
      ["无事件证券", context.symbols_without_display_events], ["覆盖不完整证券", context.coverage_incomplete_symbol_count],
      ["完全重复记录合并", context.exact_duplicate_rows], ["相邻日期冲突组", context.conflict_group_count],
    ];
    facts.forEach(([label, value]) => {
      const item = make("span", label + " ");
      item.append(make("b", displayValue(value)));
      grid.append(item);
    });
    section.append(grid);
    if (finite(context.conflict_group_count) > 0) {
      section.append(make("p", "检测到相邻日期冲突 " + context.conflict_group_count + " 组；请结合来源接口核查标题和执行日期。", "event-stale-warning"));
    }
    const diagnostics = interfaceDiagnostics(market);
    section.append(make("p", "接口状态、尝试次数与返回行数", "sub"));
    if (diagnostics.length) {
      const table = make("table", undefined, "event-interface-table");
      const head = make("thead"), headRow = make("tr");
      ["接口 / 用途", "状态", "尝试", "返回行数"].forEach(label => headRow.append(make("th", label)));
      head.append(headRow);
      const body = make("tbody");
      const statusLabels = { success: "成功", partial: "部分成功", failed: "失败", not_called: "未调用" };
      diagnostics.forEach(item => {
        const row = make("tr");
        row.append(
          make("td", displayValue(item.interface) + " · " + (purposeMap[item.interface] || categoryLabels[item.category] || "PandaData 事件接口")),
          make("td", statusLabels[item.status] || displayValue(item.status)),
          make("td", displayValue(item.attempts)),
          make("td", displayValue(item.returned_rows))
        );
        body.append(row);
      });
      table.append(head, body);
      section.append(table);
    } else {
      section.append(make("p", "没有接口调用诊断。", "sub"));
    }
    const limitation = context.discovery_limitation
      || "PandaData事件接口按公告日期筛选；早于公告发现窗口发布的窗口内事件可能无法发现。";
    section.append(make("p", limitation, "sub"));
    const referenceDate = compactDate(context.event_reference_date);
    (market.rows || []).filter(row => {
      const priceDate = compactDate(row.price_date);
      return referenceDate.length === 8 && priceDate.length === 8 && priceDate < referenceDate;
    }).forEach(row => {
      section.append(make("p", displayValue(row.symbol) + "：价格日期早于事件参考日（" + formatDate(row.price_date) + " < " + formatDate(context.event_reference_date) + "）。", "event-stale-warning"));
    });
    box.classList.add("show");
    box.append(section);
  }
  function collapseDataCompleteness() {
    const box = document.querySelector("#dataAlert");
    if (!box) return;
    const previousContent = box.querySelector("#dataCompletenessContent");
    if (previousContent) {
      while (previousContent.firstChild) box.insertBefore(previousContent.firstChild, previousContent);
      previousContent.remove();
    }
    box.querySelector("#dataCompletenessToggle")?.remove();
    const collapsedLabel = "\u6570\u636e\u5b8c\u6574\u6027\uff08\u70b9\u51fb\u5c55\u5f00\uff09";
    const expandedLabel = "\u6570\u636e\u5b8c\u6574\u6027\uff08\u70b9\u51fb\u6536\u8d77\uff09";
    const toggle = make("button", collapsedLabel, "data-completeness-toggle");
    toggle.id = "dataCompletenessToggle";
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "dataCompletenessContent");
    const content = make("div", undefined, "data-completeness-content");
    content.id = "dataCompletenessContent";
    content.hidden = true;
    Array.from(box.childNodes).forEach(node => content.append(node));
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      content.hidden = expanded;
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.textContent = expanded ? collapsedLabel : expandedLabel;
    });
    box.replaceChildren(toggle, content);
  }
  function renderTimeDisclosure() {
    document.querySelector("#consensusTimeDisclosure")?.remove();
    const overview = document.querySelector("#overview");
    if (!overview) return;
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    const diagnostics = market.diagnostics || {};
    const section = make("section", undefined, "time-disclosure reveal");
    section.id = "consensusTimeDisclosure";
    section.append(make("h2", "时间口径"));
    section.append(make("p", "区分报告生成时间、数据抓取时间和一致预期业务日期，避免把抓取时刻误当成目标价更新时间。"));
    const grid = make("div", undefined, "time-grid");
    const items = [
      ["报告生成时间", displayValue(window.REPORT_DATA.generated_at)],
      [activeMarket().toUpperCase() + " 一致预期抓取完成", displayValue(diagnostics.consensus_retrieved_at)],
      ["当前目标价均值", "PandaData 最新可用快照；PandaData 未提供具体业务日期"],
      ["历史比较快照", displayValue(diagnostics.historical_snapshot_label || window.REPORT_DATA.horizon) + " 回看字段；PandaData 未提供具体业务日期"],
    ];
    items.forEach(([label, value]) => {
      const item = make("div", undefined, "time-item");
      item.append(make("span", label), make("strong", value));
      grid.append(item);
    });
    section.append(grid);
    overview.insertAdjacentElement("afterend", section);
  }
  function renderEventMarketOverview() {
    document.querySelector("#eventMarketOverview")?.remove();
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    if (!Object.prototype.hasOwnProperty.call(market, "event_context")) return;
    const context = market.event_context || {};
    const events = validEvents(market);
    const section = make("section", undefined, "event-market-overview reveal");
    section.id = "eventMarketOverview";
    section.append(make("h2", "事件市场概览"));
    section.append(make("p", "事件上下文不参与一致预期榜单排序；按执行日期和类别展示窗口内证据。"));
    const statusCounts = { recent: 0, today: 0, ongoing: 0, upcoming: 0 };
    const categoryCounts = {};
    events.forEach(event => {
      if (Object.prototype.hasOwnProperty.call(statusCounts, event.time_status)) statusCounts[event.time_status] += 1;
      categoryCounts[event.category] = (categoryCounts[event.category] || 0) + 1;
    });
    const categories = Object.entries(categoryCounts).map(([key, count]) =>
      (categoryLabels[key] || key) + " " + count
    ).join(" · ") || "—";
    const grid = make("div", undefined, "event-overview-grid");
    const items = [
      ["模块状态", eventStateLabel(eventModuleState(market))],
      ["事件阶段", "近期 " + statusCounts.recent + " · 今日 " + statusCounts.today + " · 进行中 " + statusCounts.ongoing + " · 即将发生 " + statusCounts.upcoming],
      ["类别分布", categories],
      ["展示窗口", formatDate(context.event_window_start) + " — " + formatDate(context.event_window_end)],
      ["市场参考日", formatDate(context.event_reference_date)],
      ["公告发现窗口", formatDate(context.announcement_query_start) + " — " + formatDate(context.announcement_query_end) + "（" + displayValue(context.event_discovery_days) + " 天）"],
    ];
    items.forEach(([label, value]) => {
      const item = make("div", undefined, "event-overview-item");
      item.append(make("span", label), make("strong", value));
      grid.append(item);
    });
    section.append(grid);
    const anchor = document.querySelector("#consensusTimeDisclosure") || document.querySelector("#overview");
    anchor?.insertAdjacentElement("afterend", section);
  }
  function renderEligibilityFunnels() {
    document.querySelector("#eligibilityFunnels")?.remove();
    const ranking = document.querySelector(".ranking-panel");
    if (!ranking) return;
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    const funnels = market.eligibility_funnels || {};
    if (!(funnels.target_revision || []).length && !(funnels.rating || []).length) return;
    const section = make("section", undefined, "eligibility-funnels");
    section.id = "eligibilityFunnels";
    section.append(make("h2", "排名资格漏斗"));
    section.append(make("p", "每一级均以上一级为基数；留存率为本级数量 ÷ 上一级数量。"));
    const grid = make("div", undefined, "funnel-grid");
    const addCard = (title, stages, note) => {
      const cardNode = make("article", undefined, "funnel-card");
      cardNode.append(make("h3", title));
      const track = make("div", undefined, "funnel-track");
      (stages || []).forEach(stage => {
        const node = make("div", undefined, "funnel-stage");
        node.append(
          make("span", displayValue(stage.label)),
          make("b", displayValue(stage.count)),
          make("small", stage.retention === null || stage.retention === undefined ? "起点" : "留存 " + (Number(stage.retention) * 100).toFixed(1) + "%")
        );
        track.append(node);
      });
      cardNode.append(track, make("p", note, "sub"));
      grid.append(cardNode);
    };
    addCard("目标价修订榜资格漏斗", funnels.target_revision, "历史快照是修订计算的必要条件；高分歧和价格偏离榜只使用当前快照，因此不由本漏斗改变其既有资格口径。");
    addCard("评级榜资格漏斗", funnels.rating, "评级变化需要当前与回看期推荐均值，并达到独立的推荐覆盖阈值。");
    section.append(grid);
    ranking.insertAdjacentElement("afterend", section);
  }
  const trajectoryHorizonLabel = horizon => ({
    week: "周度", "1month": "1个月", "3month": "3个月", "6month": "6个月",
    "12month": "12个月",
  })[horizon] || displayValue(horizon);
  const trajectoryDirectionLabel = direction => ({
    positive: "正向", negative: "负向", flat: "持平", unavailable: "缺失",
  })[direction] || "缺失";
  const trajectoryValue = item => {
    const value = finite(item?.change);
    return value === null ? "— 缺失" : (value > 0 ? "+" : "")
      + (value * 100).toFixed(1) + "% " + trajectoryDirectionLabel(item.direction);
  };
  const trajectoryByHorizon = (items, horizon) => (items || []).find(item => item.horizon === horizon) || {};
  function renderTrajectoryMatrix() {
    document.querySelector("#trajectoryMatrix")?.remove();
    const overview = document.querySelector("#overview");
    if (!overview) return;
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    const section = make("section", undefined, "trajectory-matrix");
    section.id = "trajectoryMatrix";
    section.append(make("h2", "修订轨迹矩阵"));
    section.append(make("p", "目标价与评级均按五个回看期展示；单元格同时给出符号、数值和方向文字，缺失值显示为 —。", "sub"));
    const rows = market.trajectory_matrix || [];
    if (!rows.length) {
      section.append(make("div", "暂无轨迹矩阵数据", "trajectory-empty"));
      overview.insertAdjacentElement("afterend", section);
      return;
    }
    const toolbar = make("div", undefined, "trajectory-toolbar");
    const label = make("label", "搜索名称或代码");
    label.htmlFor = "trajectorySearch";
    const search = make("input", undefined, "trajectory-search");
    search.id = "trajectorySearch";
    search.type = "search";
    search.placeholder = "例如 Alpha 或 0001.HK";
    const count = make("span", "", "trajectory-search-count");
    count.id = "trajectorySearchCount";
    const empty = make("div", "未找到匹配的修订轨迹", "trajectory-search-empty");
    empty.id = "trajectorySearchEmpty";
    empty.hidden = true;
    toolbar.append(label, search, count);
    section.append(toolbar, empty);
    const table = make("table", undefined, "trajectory-table");
    const head = make("thead"), headRow = make("tr");
    ["名称 · 代码", "行业", ...["week", "1month", "3month", "6month", "12month"].flatMap(horizon => [
      trajectoryHorizonLabel(horizon) + "目标价修订", trajectoryHorizonLabel(horizon) + "评级修订",
    ])].forEach(label => headRow.append(make("th", label)));
    head.append(headRow); table.append(head);
    const body = make("tbody");
    rows.forEach(row => {
      const tr = make("tr");
      tr.dataset.search = ((row.name || "") + " " + (row.symbol || "")).toLowerCase();
      tr.append(make("td", (row.name ? row.name + " · " : "") + displayValue(row.symbol)));
      const industry = displayValue(row.industry_group);
      const industryCell = make("td", industry);
      industryCell.title = industry === "—" ? "" : industry;
      tr.append(industryCell);
      ["week", "1month", "3month", "6month", "12month"].forEach(horizon => {
        [row.target_price_trajectory, row.rating_trajectory].forEach(series => {
          const item = trajectoryByHorizon(series, horizon);
          tr.append(make("td", trajectoryValue(item), "trajectory-signal " + (item.direction || "unavailable")));
        });
      });
      body.append(tr);
    });
    const applySearch = () => {
      const query = search.value.trim().toLowerCase();
      let matches = 0;
      body.querySelectorAll("tr").forEach(tr => {
        const matched = !query || tr.dataset.search.includes(query);
        tr.style.display = matched ? "" : "none";
        if (matched) matches += 1;
      });
      count.textContent = "匹配 " + matches + " / 总计 " + rows.length;
      empty.hidden = matches !== 0;
    };
    search.addEventListener("input", applySearch);
    applySearch();
    table.append(body);
    const wrap = make("div", undefined, "trajectory-wrap"); wrap.append(table); section.append(wrap);
    overview.insertAdjacentElement("afterend", section);
  }
  function renderConsensusStates(detail, row, market) {
    detail.querySelector("#consensusStateModule")?.remove();
    const matrixRow = (market.trajectory_matrix || []).find(item => String(item.symbol) === String(row.symbol)) || row;
    const section = make("section", undefined, "consensus-state-module");
    section.id = "consensusStateModule";
    section.append(make("h3", "状态解读"));
    section.append(make("p", "状态为规则化研究分类，不改变榜单排序，不构成投资建议。", "state-disclaimer"));
    section.append(make("p", "评级均值越低代表评级更积极（绝对水平）；评级变化 = 历史评级均值 − 当前评级均值，历史评级均值 − 当前评级均值越大代表评级改善/更积极。", "state-disclaimer"));
    const metadata = make("div", undefined, "state-metadata");
    metadata.append(
      make("span", "高分歧阈值 P75：" + displayValue(matrixRow.dispersion_p75)),
      make("span", "有效核心样本数：" + displayValue(matrixRow.dispersion_sample_count)),
      make("span", "覆盖变化：" + displayValue(row.coverage_change_status)),
    );
    section.append(metadata);
    const states = matrixRow.consensus_states || row.consensus_states || [];
    if (!states.length) {
      section.append(make("div", "暂无状态数据", "trajectory-empty"));
    } else {
      const list = make("div", undefined, "state-list");
      states.forEach(state => {
        const card = make("article", undefined, "state-card");
        card.append(make("span", displayValue(state.label), "state-label"));
        card.append(make("p", displayValue(state.explanation)));
        const evidence = make("details");
        evidence.append(make("summary", "查看结构化 evidence"));
        evidence.append(make("pre", JSON.stringify(state.evidence ?? {}, null, 2)));
        card.append(evidence); list.append(card);
      });
      section.append(list);
    }
    const interpretation = detail.querySelector(".interpretation");
    if (interpretation) interpretation.insertAdjacentElement("afterend", section);
    else detail.prepend(section);
  }
  function renderSecurityTrajectory(detail, row, market) {
    detail.querySelector("#securityTrajectory")?.remove();
    const section = make("section", undefined, "security-trajectory");
    section.id = "securityTrajectory";
    section.append(make("h3", "个股修订轨迹"));
    const matrixRow = (market.trajectory_matrix || []).find(item =>
      String(item.symbol).toLowerCase() === String(row.symbol).toLowerCase());
    if (!matrixRow) {
      section.append(make("div", "暂无该个股修订轨迹数据", "trajectory-empty"));
    } else {
      const table = make("table", undefined, "security-trajectory-table");
      const head = make("thead"), headRow = make("tr");
      ["回看期", "目标价修订", "评级修订"].forEach(label => headRow.append(make("th", label)));
      head.append(headRow);
      const body = make("tbody");
      ["week", "1month", "3month", "6month", "12month"].forEach(horizon => {
        const tr = make("tr");
        tr.append(make("td", trajectoryHorizonLabel(horizon)));
        [matrixRow.target_price_trajectory, matrixRow.rating_trajectory].forEach(series => {
          const item = trajectoryByHorizon(series, horizon);
          tr.append(make("td", trajectoryValue(item), "trajectory-signal " + (item.direction || "unavailable")));
        });
        body.append(tr);
      });
      table.append(head, body);
      const wrap = make("div", undefined, "security-trajectory-wrap");
      wrap.append(table);
      section.append(wrap);
    }
    const states = detail.querySelector("#consensusStateModule");
    if (states) states.insertAdjacentElement("afterend", section);
    else detail.prepend(section);
  }
  function coverageChangeEvidence(row, market) {
    const diagnostics = market.diagnostics || {};
    const horizon = diagnostics.historical_snapshot_label || window.REPORT_DATA.horizon || "1month";
    const section = make("section", undefined, "evidence-group");
    section.id = "coverageChangeEvidence";
    if (row.coverage_change_status === "significant") section.classList.add("significant");
    section.append(make("h3", "覆盖样本变化拆解"));
    const grid = make("div", undefined, "evidence-grid");
    const rows = [
      ["当前估计数", formatNumber(row.estimates_num)],
      [horizon + " 回看估计数", formatNumber(row["estimates_num_" + horizon])],
      ["估计数变化", formatSigned(row.estimates_change_abs)],
      ["估计数变化率", formatPercent(row.estimates_change_ratio)],
      ["当前纳入统计", formatNumber(row.included_estimates_num)],
      [horizon + " 回看纳入统计", formatNumber(row["included_estimates_num_" + horizon])],
      ["纳入统计变化", formatSigned(row.included_estimates_change_abs)],
      ["纳入统计变化率", formatPercent(row.included_estimates_change_ratio)],
    ];
    rows.forEach(([label, value]) => {
      const item = make("div", undefined, "evidence-item");
      item.append(make("span", label), make("strong", value));
      grid.append(item);
    });
    section.append(grid);
    const statusText = ({ significant: "显著变化", stable_or_minor: "稳定或轻微变化", unavailable: "无法比较" })[row.coverage_change_status] || "无法比较";
    const retrievalText = diagnostics.consensus_retrieved_at
      ? " 当前目标价均值为 PandaData 最新可用快照；本次抓取完成于 " + diagnostics.consensus_retrieved_at + "，该时刻不是目标价更新时间；PandaData 未提供具体业务日期。"
      : " 当前目标价均值为 PandaData 最新可用快照；PandaData 未提供具体业务日期。";
    const note = "判定：" + statusText + "。显著变化需同时满足 |数量变化| ≥ 2 且 |变化率| ≥ 20%。" + (row.coverage_change_note ? " " + row.coverage_change_note + "。" : "") + retrievalText;
    section.append(make("div", note, "evidence-note"));
    return section;
  }
  function targetChart(row, horizon) {
    const currencyComparable = row.price_currency_verified === true;
    const section = card("target", "目标价定位", currencyComparable
      ? "对比最新收盘价、回看期目标价均值与当前目标价均值；数据来自 PandaData 聚合一致预期。"
      : "目标价与价格币种无法可靠验证，收盘价不参与定位比较；不进行无依据换算。" );
    const values = [
      ["最新收盘价", currencyComparable ? row.close : null, "legend-close"],
      [horizon + "前目标价均值", row["tp_mean_" + horizon], "legend-history"],
      ["当前目标价均值（PandaData 最新可用快照）", row.tp_mean, "legend-current"],
    ];
    const all = values.map(item => finite(item[1])).filter(value => value !== null);
    const low = finite(row.tp_low), high = finite(row.tp_high);
    if (low !== null) all.push(low);
    if (high !== null) all.push(high);
    const min = all.length ? Math.min(...all) : 0;
    const max = all.length ? Math.max(...all) : 1;
    const span = max - min || 1;
    values.forEach(([label, value, colorClass]) => {
      const rowNode = make("div", undefined, "rating-row");
      rowNode.append(make("span", label));
      const track = make("span", undefined, "rating-track");
      const marker = make("i", undefined, colorClass);
      marker.style.width = finite(value) === null ? "0%" : Math.max(3, (finite(value) - min) / span * 100).toFixed(1) + "%";
      track.append(marker);
      rowNode.append(track, make("b", finite(value) === null ? "—" : finite(value).toFixed(2)));
      section.append(rowNode);
    });
    section.append(make("div", "灰线区间：" + (low === null || high === null ? "缺失" : low.toFixed(2) + " – " + high.toFixed(2)), "rating-legend"));
    return section;
  }
  function ratingChart(row) {
    const section = card("rating", "评级分布", "展示 PandaData 返回的聚合推荐数量，不代表个别分析师的修订事件。" );
    const values = [["强买", "strong_buy_num", "legend-current"], ["买入", "buy_num", "legend-current"], ["持有", "hold", "legend-history"], ["卖出", "sell_num", "legend-close"], ["强卖", "strong_sell_num", "legend-current"], ["无意见", "no_opinion_num", "legend-history"]]
      .map(([label, key, colorClass]) => [label, finite(row[key]), colorClass]).filter(item => item[1] !== null && item[1] >= 0);
    const total = values.reduce((sum, item) => sum + item[1], 0);
    if (!total) { section.append(make("div", "PandaData 未返回可用的推荐分布数据。", "chart-empty")); return section; }
    const bars = make("div", undefined, "rating-bars");
    values.forEach(([label, value, colorClass]) => {
      const rowNode = make("div", undefined, "rating-row");
      rowNode.append(make("span", label));
      const track = make("span", undefined, "rating-track");
      const bar = make("i", undefined, colorClass);
      bar.style.width = value === 0 ? "0%" : Math.max(2, value / total * 100).toFixed(1) + "%";
      track.append(bar);
      rowNode.append(track, make("b", String(value)));
      bars.append(rowNode);
    });
    section.append(bars, make("div", "合计 " + total + " 份推荐", "rating-legend"));
    return section;
  }
  const eventSourceText = event => Array.isArray(event.source_interfaces)
    ? event.source_interfaces.filter(item => typeof item === "string").join("、") || "—" : "—";
  const eventConfirmationText = event => event.is_estimated === true
    ? "预计" : event.is_estimated === false ? "已确认" : "确认状态未提供";
  function sortedSecurityEvents(market, symbol) {
    return eventsForSymbol(market, symbol).slice().sort((first, second) => {
      const dateOrder = String(first.start_date || "").localeCompare(String(second.start_date || ""));
      if (dateOrder) return dateOrder;
      const categoryOrder = String(first.category || "").localeCompare(String(second.category || ""));
      return categoryOrder || String(first.title || "").localeCompare(String(second.title || ""));
    });
  }
  function eventAccessibleText(event) {
    return [
      eventDateRange(event), categoryLabels[event.category] || displayValue(event.category),
      displayValue(event.event_type), displayValue(event.title),
      "公告 " + formatDate(event.publish_date), "执行 " + eventDateRange(event),
      "财季 " + displayValue(event.fiscal_quarter), eventConfirmationText(event),
      "来源 " + eventSourceText(event),
    ].join("；");
  }
  function eventCard(event) {
    const article = make("article", undefined, "event-card");
    article.setAttribute("data-category", displayValue(event.category));
    const date = make("time", eventDateRange(event), "event-card-date");
    date.append(make("small", event.time_status === "upcoming" ? "即将发生" : event.time_status === "ongoing" ? "进行中" : event.time_status === "today" ? "今日" : "近期"));
    const body = make("div", undefined, "event-card-body");
    const badges = make("div", undefined, "event-card-badges");
    badges.append(
      make("span", categoryLabels[event.category] || displayValue(event.category), "event-category-badge"),
      make("span", displayValue(event.event_type), "event-type-badge")
    );
    body.append(badges, make("h3", displayValue(event.title), "event-card-title"));
    const meta = make("div", undefined, "event-card-meta");
    [
      "公告日期 " + formatDate(event.publish_date),
      "执行区间 " + eventDateRange(event),
      "财季 " + displayValue(event.fiscal_quarter),
      eventConfirmationText(event),
      "来源接口 " + eventSourceText(event),
    ].forEach(text => meta.append(make("span", text)));
    body.append(meta);
    article.append(date, body);
    return article;
  }
  function eventTimeline(market, row) {
    const timeline = make("section", undefined, "event-timeline");
    timeline.id = "eventTimeline";
    timeline.append(make("h3", "事件时间轨"));
    timeline.append(make("p", "按执行开始日期排序；类别标记用于区分事件性质，不改变榜单结论。", "sub"));
    const events = sortedSecurityEvents(market, row.symbol);
    const state = eventModuleState(market);
    if (state === "partial") timeline.append(make("p", eventStateLabel(state) + "；以下仅展示成功接口返回的有效事件。", "event-timeline-state"));
    if (!events.length) {
      const emptyState = ["partial", "unavailable", "disabled"].includes(state) ? state : "empty";
      timeline.append(make("div", eventStateLabel(emptyState), "event-empty"));
      return timeline;
    }
    const cards = make("div", undefined, "event-timeline-list");
    cards.id = "eventTimelineCards";
    const initialEvents = events.slice(0, 8);
    initialEvents.forEach(event => cards.append(eventCard(event)));
    const extraCards = events.slice(8).map(event => {
      const node = eventCard(event);
      node.hidden = true;
      cards.append(node);
      return node;
    });
    timeline.append(cards);
    if (extraCards.length) {
      const button = make("button", "查看全部（" + events.length + "）", "event-expand");
      button.type = "button";
      button.setAttribute("aria-controls", cards.id);
      button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", () => {
        const expanded = button.getAttribute("aria-expanded") === "true";
        extraCards.forEach(card => { card.hidden = expanded; });
        button.setAttribute("aria-expanded", String(!expanded));
        button.textContent = expanded ? "查看全部（" + events.length + "）" : "收起事件";
      });
      timeline.append(button);
    }
    const accessibleList = make("ul", undefined, "event-accessible-list sr-only");
    accessibleList.setAttribute("aria-label", "完整事件文本列表，共 " + events.length + " 条");
    events.forEach(event => accessibleList.append(make("li", eventAccessibleText(event))));
    timeline.append(accessibleList);
    return timeline;
  }
  function enhanceDetail() {
    const detail = document.querySelector("#detail");
    if (!detail) return;
    const identity = detail.querySelector(".identity strong");
    if (!identity) return;
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    const identityText = (identity.textContent || "").trim();
    const row = (market.rows || []).find(item => identityText === String(item.symbol)
      || identityText.endsWith(" · " + String(item.symbol)));
    if (!row) return;
    renderConsensusStates(detail, row, market);
    renderSecurityTrajectory(detail, row, market);
    const hasEventPayload = Object.prototype.hasOwnProperty.call(market, "event_context")
      || Object.prototype.hasOwnProperty.call(market, "events");
    if (hasEventPayload && !detail.querySelector("#eventTimeline")) {
      const timeline = eventTimeline(market, row);
      const interpretation = detail.querySelector(".interpretation");
      if (interpretation) interpretation.insertAdjacentElement("afterend", timeline);
      else detail.prepend(timeline);
    }
    if (detail.querySelector("[data-chart-role]")) return;
    const ledger = detail.querySelector(".evidence-ledger");
    const targetEvidence = ledger?.querySelector("#targetEvidence");
    if (ledger && !ledger.querySelector("#coverageChangeEvidence")) {
      const coverageEvidence = coverageChangeEvidence(row, market);
      if (targetEvidence) targetEvidence.insertAdjacentElement("afterend", coverageEvidence);
      else ledger.prepend(coverageEvidence);
    }
    const charts = make("div", undefined, "detail-charts");
    charts.append(targetChart(row, window.REPORT_DATA.horizon || "1month"));
    if (ledger) detail.insertBefore(charts, ledger);
    else detail.append(charts);
    const recommendation = ledger?.querySelector("#recommendationEvidence");
    const ratingSlot = make("div", undefined, "evidence-chart");
    ratingSlot.append(ratingChart(row));
    if (ledger && recommendation) {
      ledger.insertBefore(ratingSlot, recommendation);
    } else if (ledger) {
      ledger.insertBefore(ratingSlot, ledger.firstChild);
    } else {
      detail.append(ratingSlot);
    }
  }
  function rankingEventDistance(event, referenceDate) {
    if (event.time_status === "today" || event.time_status === "ongoing") return 0;
    const reference = dateOrdinal(referenceDate);
    const eventDate = dateOrdinal(event.time_status === "recent" ? event.end_date || event.start_date : event.start_date);
    return Number.isFinite(reference) && Number.isFinite(eventDate) ? Math.abs(eventDate - reference) : Number.POSITIVE_INFINITY;
  }
  function closestRankingEvents(events, context) {
    const sortClosest = (first, second) => {
      const distance = rankingEventDistance(first, context.event_reference_date) - rankingEventDistance(second, context.event_reference_date);
      if (distance) return distance;
      const dateOrder = String(first.start_date || "").localeCompare(String(second.start_date || ""));
      if (dateOrder) return dateOrder;
      const categoryOrder = String(first.category || "").localeCompare(String(second.category || ""));
      return categoryOrder || String(first.title || "").localeCompare(String(second.title || ""));
    };
    const current = events.filter(event => ["recent", "today", "ongoing"].includes(event.time_status)).sort(sortClosest)[0];
    const upcoming = events.filter(event => event.time_status === "upcoming").sort(sortClosest)[0];
    return [current, upcoming].filter(Boolean);
  }
  function renderRankingEventCell(cell, events, context, state) {
    cell.replaceChildren();
    if (["partial", "unavailable", "disabled"].includes(state)) {
      cell.append(make("span", eventStateLabel(state), "event-availability"));
    }
    const selectedEvents = eventCategory === "all"
      ? events : events.filter(event => event.category === eventCategory);
    const snippets = closestRankingEvents(selectedEvents, context);
    if (!snippets.length) {
      cell.append(make("span", "—"));
      return;
    }
    snippets.forEach(event => {
      const snippet = make("div", undefined, "event-snippet");
      snippet.append(
        make("time", formatDate(event.start_date)),
        make("span", " · " + (categoryLabels[event.category] || displayValue(event.category)) + " · ", "event-category-label"),
        make("span", displayValue(event.title))
      );
      if (event.is_estimated === true) snippet.append(make("span", "预计", "event-estimated"));
      cell.append(snippet);
    });
  }
  function applyRankingEventFilter(table, market) {
    const context = market.event_context || {};
    const state = eventModuleState(market);
    table.querySelectorAll("tbody tr").forEach(tr => {
      const baseHidden = tr.dataset.eventBaseHidden === "true";
      const symbol = tr.querySelector("button.symbol")?.dataset.s;
      const symbolEvents = symbol ? eventsForSymbol(market, symbol) : [];
      const filteredEvents = eventCategory === "all"
        ? symbolEvents : symbolEvents.filter(event => event.category === eventCategory);
      tr.hidden = baseHidden || eventCategory !== "all" && filteredEvents.length === 0;
      const cell = tr.querySelector(".event-context-cell");
      if (cell) renderRankingEventCell(cell, symbolEvents, context, state);
    });
  }
  function renderEventCategoryFilters(table, market) {
    document.querySelector("#eventCategoryFilters")?.remove();
    const method = document.querySelector("#rankingMethod");
    if (!method) return;
    const filters = make("div", undefined, "event-context-filters");
    filters.id = "eventCategoryFilters";
    filters.setAttribute("role", "group");
    filters.setAttribute("aria-label", "按事件类别筛选当前榜单");
    filters.append(make("span", "事件类别"));
    categoryFilters.forEach(([key, label]) => {
      const button = make("button", label, "event-filter-chip" + (eventCategory === key ? " active" : ""));
      button.type = "button";
      button.dataset.eventCategory = key;
      button.setAttribute("aria-pressed", String(eventCategory === key));
      button.addEventListener("click", () => {
        eventCategory = key;
        filters.querySelectorAll("button").forEach(item => {
          const active = item.dataset.eventCategory === eventCategory;
          item.classList.toggle("active", active);
          item.setAttribute("aria-pressed", String(active));
        });
        applyRankingEventFilter(table, market);
      });
      filters.append(button);
    });
    method.insertAdjacentElement("afterend", filters);
  }
  function enhanceRankingContext() {
    const active = document.querySelector("#rankingTabs .rank-button.active");
    const ratingMode = active?.dataset.k === "rating_changes";
    const market = window.REPORT_DATA.markets?.[activeMarket()] || {};
    const method = document.querySelector("#rankingMethod span");
    if (method) {
      method.textContent = ratingMode
        ? "评级变化 = 回看期推荐均值 − 当前推荐均值；PandaData 推荐均值越低越积极；覆盖 = recommendations_num（推荐总数），最低覆盖 " + (market.overview?.min_recommendations ?? window.REPORT_DATA.min_recommendations ?? 5) + "。"
        : "修订 = 当前目标价均值 ÷ 回看期目标价均值 - 1；价格偏离 = 当前目标价均值 ÷ 最新收盘价 - 1；分歧 = 目标价标准差 ÷ |当前目标价均值|；覆盖 = estimates_num（目标价估计数），最低覆盖 " + (market.overview?.min_analysts ?? window.REPORT_DATA.min_analysts ?? 5) + "。";
    }
    const table = document.querySelector("#rankingTable table");
    document.querySelector("#eventCategoryFilters")?.remove();
    if (!table) return;
    const coverageHeader = table.querySelectorAll("th")[5];
    if (coverageHeader) coverageHeader.textContent = ratingMode ? "评级覆盖" : "目标价覆盖";
    if (ratingMode) {
      const rows = new Map((market.rows || []).map(row => [String(row.symbol), row]));
      table.querySelectorAll("tbody tr").forEach(tr => {
        const symbol = tr.querySelector("button.symbol")?.dataset.s;
        const cell = tr.querySelectorAll("td")[5];
        if (cell && symbol) cell.textContent = rows.get(String(symbol))?.recommendations_num ?? "—";
      });
    }
    table.querySelectorAll(".event-context-head,.event-context-cell").forEach(node => node.remove());
    const header = make("th", "事件上下文", "event-context-head");
    table.querySelector("thead tr")?.append(header);
    table.querySelectorAll("tbody tr").forEach(tr => {
      const rankCell = tr.querySelector("td");
      tr.dataset.eventOriginalRank = rankCell?.textContent || "";
      if (!Object.prototype.hasOwnProperty.call(tr.dataset, "eventBaseHidden")) {
        tr.dataset.eventBaseHidden = tr.hidden ? "true" : "false";
      }
      tr.append(make("td", undefined, "event-context-cell"));
    });
    renderEventCategoryFilters(table, market);
    applyRankingEventFilter(table, market);
  }
  function enhanceMethodology() {
    const steps = document.querySelectorAll("#methodologySteps .method-step");
    const last = steps[steps.length - 1]?.querySelector("span");
    if (last) last.textContent = "目标价榜达到 " + (window.REPORT_DATA.min_analysts ?? 5) + " 位分析师覆盖；评级榜达到 " + (window.REPORT_DATA.min_recommendations ?? 5) + " 份推荐覆盖。非核心证券和严重一致性异常不进入受影响榜单，原始值仍保留在诊断中。";
  }
  function install() {
    renderSourceProvenance();
    renderEventDataCompleteness();
    collapseDataCompleteness();
    renderTimeDisclosure();
    renderEventMarketOverview();
    renderEligibilityFunnels();
    renderTrajectoryMatrix();
    enhanceDetail();
    enhanceRankingContext();
    enhanceMethodology();
    const detail = document.querySelector("#detail");
    if (detail) new MutationObserver(() => setTimeout(enhanceDetail, 0)).observe(detail, { childList: true, subtree: true });
    document.querySelector("#rankingTabs")?.addEventListener("click", () => setTimeout(enhanceRankingContext, 0));
    document.querySelector("#search")?.addEventListener("input", () => setTimeout(enhanceRankingContext, 0));
    document.querySelector("#marketTabs")?.addEventListener("click", () => {
      eventCategory = "all";
      setTimeout(() => {
        renderSourceProvenance();
        renderEventDataCompleteness();
        collapseDataCompleteness();
        renderTimeDisclosure();
        renderEventMarketOverview();
        renderEligibilityFunnels();
        renderTrajectoryMatrix();
        enhanceDetail();
        enhanceRankingContext();
      }, 0);
    });
  }
  setTimeout(install, 0);
})();
</script>'''


def _script_safe_json(payload: dict) -> str:
    value = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (
        value.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _data_completeness_fallback(payload: dict) -> str:
    """Return visible, server-rendered completeness disclosure for the first market."""
    markets = payload.get("markets") or {}
    market = next(iter(markets.values()), {}) if isinstance(markets, dict) else {}
    market = market if isinstance(market, dict) else {}
    quality = market.get("quality") or {}
    quality = quality if isinstance(quality, dict) else {}

    def value(item: object) -> str:
        return escape(str(item if item is not None else "—"), quote=True)

    raw_sources = market.get("source_interfaces") or market.get("sources") or []
    source_items = []
    for source in raw_sources:
        if isinstance(source, str):
            source_items.append((source, "PandaData 数据接口"))
        elif isinstance(source, dict) and source.get("interface"):
            source_items.append((source["interface"], source.get("purpose") or "PandaData 数据接口"))
    source_list = "".join(
        f"<li><code>{value(interface)}</code>：{value(purpose)}</li>"
        for interface, purpose in source_items
    ) or "<li>本次运行未记录来源接口。</li>"
    quality_summary = "；".join(
        f"{label} {value(quality.get(key, 0))} 条"
        for label, key in (
            ("核心股票池", "core_universe_rows"),
            ("一致性错误", "validation_error_rows"),
            ("一致性警告", "validation_warning_rows"),
            ("名称缺失", "missing_name"),
            ("价格数据缺失", "missing_price"),
            ("历史基准缺失", "missing_history"),
            ("推荐数据缺失", "missing_recommendation"),
            ("分析师覆盖数缺失", "missing_coverage"),
        )
    )
    event_html = ""
    if "event_context" in market:
        context = market.get("event_context") or {}
        context = context if isinstance(context, dict) else {}
        event_summary = "；".join(
            f"{label} {value(context.get(key, "—"))}"
            for label, key in (
                ("请求证券", "requested_symbol_count"),
                ("接口返回记录", "returned_rows"),
                ("窗口展示记录", "display_event_rows"),
                ("无效记录", "invalid_rows"),
            )
        )
        event_html = f"<section><h3>事件数据完整性</h3><p>{event_summary}。</p></section>"
    return (
        '<section id="dataCompletenessFallback">'
        '<strong>数据完整性</strong><p>本报告的原始数据仅来自 PandaData。</p>'
        f'<section><h3>数据来源与接口</h3><p>本市场本次运行实际调用以下 PandaData 接口。</p><ul>{source_list}</ul></section>'
        f'<section><h3>股票池与一致性校验</h3><p>{quality_summary}。异常记录保留原始 PandaData 值。</p></section>'
        f'<section><h3>数据缺失摘要</h3><p>{quality_summary}。</p></section>'
        f'{event_html}</section>'
    )

def render_report(payload: dict, output_path: Path | str) -> Path:
    """Write the report atomically and return its resolved path."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_alert = (
        '<section class="alert show" id="dataAlert" role="status" aria-live="polite">'
        f'{_data_completeness_fallback(payload)}</section>'
    )
    html = _normalize_template_extensions(
        template.replace("__REPORT_DATA__", _script_safe_json(payload)).replace(
            '<section class="alert reveal" id="dataAlert" role="status" aria-live="polite"></section>',
            data_alert,
            1,
        )
    )
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(html, encoding="utf-8")
    os.replace(temporary, destination)
    return destination.resolve()
def _normalize_template_extensions(html: str) -> str:
    marker = "</html>"
    boundary = html.find(marker)
    if boundary < 0:
        return html
    tail = html[boundary + len(marker):]
    if not tail.strip():
        return html
    styles = re.findall(r"<style\b[^>]*>.*?</style>", tail, flags=re.IGNORECASE | re.DOTALL)
    scripts = re.findall(r"<script\b[^>]*>.*?</script>", tail, flags=re.IGNORECASE | re.DOTALL)
    clean = html[:boundary] + marker
    if styles:
        clean = clean.replace("</head>", "".join(styles) + "</head>", 1)
    if scripts:
        clean = clean.replace("</body></html>", _REPORT_EXTENSION_SCRIPT + "</body></html>", 1)
    return clean
