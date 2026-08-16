"""Generate a standalone production-health dashboard without re-running Panda queries."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

try:
    from .core import DATA_VERSION
    from .operations import health_report
    from .replay import build_replay
except ImportError:
    from core import DATA_VERSION
    from operations import health_report
    from replay import build_replay

ROOT = Path(__file__).resolve().parents[1]

STATUS_LABELS = {
    "healthy": "健康",
    "attention": "需关注",
    "critical": "严重",
    "current": "当前有效",
    "completed": "已完成",
    "running": "运行中",
    "failed": "失败",
    "underwriting_incomplete": "承保证据不完整",
    "insufficient_evidence": "证据不足",
    "qualified_special_situation": "合格特殊情况",
    "rejected": "已排除",
    "risk_watch": "风险观察",
    "no_events": "无事件",
    "not_applicable": "不适用",
    "warning": "警告",
}

SITUATION_LABELS = {
    "private_placement_unlock": "定增解禁供给风险",
    "private_placement_supply_risk": "定增解禁供给风险",
    "reorganization": "重组或借壳",
    "reorganization_event": "重组或借壳",
    "spin_off": "分拆上市",
    "spin_off_event": "分拆上市",
    "distress": "困境反转",
    "distress_turnaround": "困境反转",
    "distress_event": "困境反转",
}

GATE_LABELS = {
    "security_access": "证券可交易性",
    "symbol": "证券身份",
    "market_price": "市场价格",
    "catalyst": "事件催化剂",
    "catalyst_verified": "催化剂核验",
    "deal_terms": "交易条款",
    "conservative_value": "保守价值",
    "failure_value": "失败价值",
    "capital_structure": "资本结构",
    "capital_structure_verified": "资本结构核验",
    "legal_accounting": "法律与会计核验",
    "legal_accounting_verified": "法律与会计核验",
    "liquidity": "流动性",
    "liquidity_verified": "流动性核验",
    "minimum_margin_of_safety": "最低安全边际",
    "conditions_verified": "先决条件核验",
    "financing_verified": "融资安排核验",
    "approvals_verified": "审批状态核验",
    "termination_terms_verified": "终止条款核验",
    "expected_close_date": "预计完成日期",
    "ownership_pct": "母公司持股比例",
    "subsidiary_value": "子公司保守价值",
    "remaining_business_value": "剩余业务价值",
    "net_debt": "净债务",
    "tax_leakage": "税费损耗",
    "holdco_discount_pct": "控股折价",
    "fully_diluted_shares": "完全稀释股数",
    "failure_value_per_share": "每股失败价值",
    "asset_recovery_values": "资产回收价值",
    "secured_debt": "有担保债务",
    "priority_claims": "优先债权",
    "unsecured_debt": "无担保债务",
    "contingent_liabilities": "或有负债",
    "restructuring_costs": "重整成本",
    "api_available": "接口可用性",
}

SCORE_LABELS = {
    "event_state": "状态事件",
    "fundamentals": "财务改善",
    "audit_quality": "审计质量",
    "current_tradable_price": "可交易价格",
    "event_recency": "事件时效",
    "capital_behavior_context": "资本行为",
    "symbol_mapping": "证券映射",
    "csrc_catalyst": "证监会催化剂",
    "clear_reorg_or_spinoff_keyword": "明确事件关键词",
    "current_fundamentals": "当前财务",
    "context": "上下文",
    "unlock_overhang_ratio": "解禁占流通盘",
    "participant_gain": "参与者浮盈",
    "unlock_proximity": "解禁临近",
    "liquidity_absorption": "成交额消化",
    "active_distress_marker": "风险警示仍生效",
    "audit_warning": "审计警示",
    "financial_check_failed": "财务核验失败",
    "negative_operating_cash_flow": "经营现金流为负",
    "shareholder_reduction": "股东减持",
}

ALERT_LABELS = {
    "coverage_gap": "接口覆盖缺口",
    "manifest_missing": "缺少完成的运行清单",
    "runtime_sla": "运行时间超过上限",
    "artifact_not_current": "生产数据不是当前有效版本",
    "empty_current_partition": "当前版本没有数据",
    "invalid_result_json": "结果内容无法解析",
    "duplicate_production_key": "生产主键重复",
    "scope_not_full_market": "扫描范围不是全市场",
    "artifact_stale": "生产数据已过时",
    "latest_run_failed": "最近一次运行失败",
    "latest_run_incomplete": "最近一次运行未完成",
}

ALERT_MESSAGE_LABELS = {
    "no completed run manifest": "尚无完成的运行清单",
    "current": "当前有效",
    "partial_artifact": "仅有局部扫描数据",
    "stale_artifact": "数据版本已过期",
    "missing_artifact": "缺少生产数据文件",
    "invalid_artifact": "生产数据文件无效",
}

API_EXPLANATIONS = [
    ("get_stock_private_placement", "定向增发明细", "读取发行价、发行数量和上市日期；只用于识别参与者浮盈及潜在供给压力，不代表二级市场安全边际。"),
    ("get_restricted_list", "限售股解禁", "读取解禁日期与解禁数量，并与流通股本比较；缺失时定增解禁链路保持证据不足。"),
    ("get_stock_csrc_approval", "证监会审批", "识别重大资产重组、借壳和分拆相关批文或受理事件；批文本身只构成催化剂证据。"),
    ("get_stock_material_contract", "重大合同", "补充已识别事件的业务背景；不得单独创建候选，也不得据此晋级承保。"),
    ("get_stock_status_change", "证券状态变更", "识别 ST、*ST、退市风险警示和状态恢复，作为困境事件发现入口。"),
    ("get_stock_daily", "日行情与交易状态", "提供市场价格、成交量、停复牌和可成交性，用于点时价格与流动性核验。"),
    ("get_fina_reports", "财务报告", "检查现金流、盈利、负债和资产变化；只作基本面核验，不能替代官方交易条款。"),
    ("get_audit_opinion", "审计意见", "识别保留、否定、无法表示意见及持续经营风险，服务法律与会计承保门。"),
    ("get_stock_detail", "证券基础信息", "提供证券代码、名称和上市状态，用于事件文本映射及证券身份核验。"),
    ("get_share_float", "流通股本", "计算解禁数量占流通盘比例，衡量潜在供给冲击。"),
    ("get_stock_pledge", "股权质押", "补充控股股东质押风险，作为非核心风险证据。"),
    ("get_stock_litigation_arbitration", "诉讼与仲裁", "补充重大诉讼、仲裁及潜在赔偿责任。"),
    ("get_cumu_guarantee", "累计担保", "补充对外担保与或有负债风险。"),
    ("get_stock_equity_illegal", "股权违规", "补充股权冻结、违规占用和监管风险；兼容当前 SDK 内部旧函数名。"),
    ("get_repurchase", "股份回购", "补充回购进度、数量、金额和价格区间；仅作资本行为背景，不抵消核心承保门。"),
    ("get_stock_equity_placard", "举牌明细", "补充持股比例、均价和后续增持计划；可能提示控制权变化，但不能独立创建重组候选。"),
    ("get_stock_shareholder_change", "股东增减持", "补充股东增减持方向、数量上限和实施进度；仅作供需与治理背景。"),
]

EVENT_EXPLANATIONS = [
    ("定增解禁供给风险", "比较定增发行价、市价、解禁日期及解禁量占流通盘比例。发行价折价只是参与者浮盈，普通二级市场买方无法取得该成本，因此固定归入风险观察，不作为套利候选。"),
    ("重组或借壳", "以证监会审批和停复牌等事件为发现入口，随后核验对价、先决条件、融资、终止条款、保守价值和失败价值。核心证据缺失时保持承保证据不完整，并对失败概率进行压力测试。"),
    ("分拆上市", "用母公司持股比例、子公司保守价值、剩余业务、净债务、税费、控股折价和完全稀释股数计算保守分部估值。重大合同金额不能替代子公司价值。"),
    ("困境反转", "由 ST、*ST、破产重整或退市风险事件触发，重点检查资产回收、债务清偿顺位、或有负债、重整成本、审计意见和股权回收瀑布；利润改善或摘帽不能单独晋级。"),
]


def _escape(value: Any) -> str:
    return html.escape("-" if value is None else str(value))


def _translated(value: Any, labels: dict[str, str]) -> str:
    text = "-" if value is None else str(value)
    return labels.get(text, text)


def _translated_gates(values: list[Any]) -> str:
    return "、".join(_translated(value, GATE_LABELS) for value in values)


def _pill(value: str, tone: str) -> str:
    return f'<span class="pill {tone}">{_escape(value)}</span>'


def _bar(label: str, count: int, total: int, tone: str = "blue") -> str:
    width = 0 if not total else count * 100 / total
    return f'<div class="bar-row"><span>{_escape(label)}</span><i><b class="{tone}" style="width:{width:.1f}%"></b></i><strong>{count}</strong></div>'


def _score_breakdown(item: Mapping[str, Any]) -> str:
    breakdown = item.get("score_breakdown") if isinstance(item.get("score_breakdown"), Mapping) else {}
    parts = [
        f"{SCORE_LABELS.get(str(key), str(key))} {_escape(value)}"
        for key, value in breakdown.items()
        if key != "total" and value not in (None, 0)
    ]
    return " · ".join(parts) or "暂无分数拆解"


def _priority_item(item: Mapping[str, Any], *, risk: bool = False) -> str:
    score = item.get("risk_score", item.get("score", 0))
    situation = _translated(item.get("situation_type"), SITUATION_LABELS)
    name = f"{_escape(item.get('stock_name'))} " if item.get("stock_name") else ""
    positive = "、".join(str(value) for value in item.get("positive_signals", [])[:4]) or "暂无正向信号"
    risks = "、".join(str(value) for value in item.get("risk_flags", [])[:4]) or "暂无额外风险标记"
    missing = "、".join(_translated(value, GATE_LABELS) for value in item.get("missing_core_evidence", [])[:4]) or "暂无新增缺失项"
    actions = "；".join(str(value) for value in item.get("next_research_actions", [])[:3]) or "保持证据跟踪"
    tone = "red" if risk else "blue"
    title = "风险观察" if risk else "研究候选"
    return (
        f'<article class="priority-item" style="border-bottom:1px solid var(--line);padding:12px 0">'
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">'
        f'<div><strong>{_escape(item.get("rank"))}. {name}{_escape(item.get("symbol"))}</strong>'
        f'<div class="muted" style="font-size:12px;margin-top:2px">{_escape(situation)} · 事件日 {_escape(item.get("event_date"))}</div></div>'
        f'<span class="pill {tone}">{_escape(title)} {int(score or 0)} 分</span></div>'
        f'<p style="margin:9px 0 5px;font-weight:600">{_escape(item.get("thesis"))}</p>'
        f'<div class="muted" style="font-size:12px">评分贡献：{_score_breakdown(item)}</div>'
        f'<div style="font-size:12px;margin-top:5px"><span class="muted">正向：</span>{_escape(positive)}</div>'
        f'<div style="font-size:12px;margin-top:3px"><span class="muted">风险：</span>{_escape(risks)}</div>'
        f'<div style="font-size:12px;margin-top:3px"><span class="muted">待补证据：</span>{_escape(missing)}</div>'
        f'<div style="font-size:12px;margin-top:3px"><span class="muted">下一步：</span>{_escape(actions)}</div>'
        f'<div class="muted" style="font-size:11px;margin-top:6px">承保状态：{_escape(_translated(item.get("underwriting_status"), STATUS_LABELS))} · 仅供研究，不是交易信号</div>'
        f'</article>'
    )


def _parse_current(path: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frame = pd.read_parquet(path)
    current = frame.loc[frame["data_version"].astype(str) == DATA_VERSION].copy()
    payloads = []
    for _, row in current.iterrows():
        try:
            payloads.append({"row": row.to_dict(), "payload": json.loads(row["result_json"])})
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return current, payloads


def build(
    output_html: str | Path,
    *,
    production_path: str | Path | None = None,
    operations_path: str | Path | None = None,
) -> Path:
    production = Path(production_path or ROOT / "生产产物" / "数据库.parquet")
    operations_dir = Path(operations_path or ROOT / "validation" / "operations")
    replay_path = operations_dir / "replay_latest.parquet"
    health = health_report(
        production,
        data_version=DATA_VERSION,
        manifest_dir=operations_dir,
        output_path=operations_dir / "health_latest.json",
    )
    replay = build_replay(production, data_version=DATA_VERSION, output_path=replay_path)
    evidence_queue_path = operations_dir / "evidence_queue.json"
    try:
        evidence_queue = json.loads(evidence_queue_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        evidence_queue = {"bundle_count": 0, "ready_count": 0, "rows": []}
    current, events = _parse_current(production)
    digest = next(
        (item["payload"] for item in events if item["row"].get("result_type") == "research_digest"),
        {},
    )
    shortlist = digest.get("shortlist", []) if isinstance(digest, Mapping) else []
    risk_watchlist = digest.get("risk_watchlist", []) if isinstance(digest, Mapping) else []
    real_events = [item for item in events if item["row"].get("result_type") not in {"coverage_gap", "scan_summary", "research_digest"}]
    statuses = Counter(str(item["row"].get("result_value")) for item in real_events)
    situations = Counter(str(item["payload"].get("situation_type") or item["row"].get("result_type")) for item in real_events)
    gates = Counter(gate for item in real_events for gate in (item["payload"].get("klarman_gates") or {}).get("missing_required", []))
    gaps = health["coverage_gaps"]
    latest_date = max(current["trade_date"].astype(str), default="-")
    coverage = health["artifact"]
    manifest = health.get("manifest") or {}
    evidence_invalid = sum(
        row.get("status") == "invalid_bundle" for row in evidence_queue.get("rows", [])
    )
    evidence_incomplete = sum(
        row.get("status") == "evidence_incomplete" for row in evidence_queue.get("rows", [])
    )
    evidence_attention = evidence_invalid + evidence_incomplete > 0
    phase_rows = [
        ("P0", "接口治理", "受限" if gaps else "正常", "amber" if gaps else "green", f"{len(gaps)} 个覆盖缺口；失败分类与有界重试已启用"),
        ("P1", "可恢复运行", "已记录" if manifest else "待新运行", "green" if manifest and manifest.get("status") == "completed" else "amber", "分片检查点与原子运行清单"),
        ("P2", "官方证据包", "待补证" if evidence_attention else f"{evidence_queue.get('ready_count', 0)} 就绪", "amber" if evidence_attention else "green", f"{evidence_queue.get('bundle_count', 0)} 个证据包 · {evidence_invalid} 无效 · {evidence_incomplete} 不完整；缺证不进入承保"),
        ("P3", "点时回放", f"{replay['eligible_count']} 可验证", "green", "事件账本已生成；收益回放等待合格且已解决事件"),
        ("P4", "生产告警", _translated(health["status"], STATUS_LABELS), "red" if health["status"] == "critical" else ("amber" if health["status"] == "attention" else "green"), "结构化健康报告已落地"),
    ]
    phase_cards = "".join(
        f'<div class="phase"><div><b>{code}</b><span>{_escape(name)}</span></div>{_pill(status, tone)}<p>{_escape(note)}</p></div>'
        for code, name, status, tone, note in phase_rows
    )
    event_rows = "".join(
        f"<tr><td>{_escape(item['payload'].get('knowledge_cutoff'))}</td><td><code>{_escape(item['payload'].get('symbol'))}</code></td><td>{_escape(_translated(item['payload'].get('situation_type'), SITUATION_LABELS))}</td><td>{_pill(_translated(item['row'].get('result_value'), STATUS_LABELS), 'amber' if item['row'].get('result_value') == 'underwriting_incomplete' else 'red')}</td><td>{_escape(_translated_gates((item['payload'].get('klarman_gates') or {}).get('missing_required', [])[:4]))}</td></tr>"
        for item in real_events[:80]
    ) or '<tr><td colspan="5" class="muted">本期没有事件记录</td></tr>'
    gap_rows = "".join(f"<li><code>{_escape(api)}</code> 本轮没有满足口径的覆盖数据，相关事件保持失败封闭。</li>" for api in gaps) or "<li>本轮没有接口或数据覆盖缺口。</li>"
    alert_rows = "".join(
        f"<li>{_pill(_translated(alert['severity'], STATUS_LABELS), 'red' if alert['severity'] == 'critical' else 'amber')} {_escape(_translated(alert['code'], ALERT_LABELS))}：{_escape(_translated(alert['message'], ALERT_MESSAGE_LABELS))}</li>"
        for alert in health['alerts']
    ) or "<li>无生产告警。</li>"
    status_bars = "".join(_bar(_translated(name, STATUS_LABELS), count, len(real_events), "amber" if name == "underwriting_incomplete" else "red") for name, count in statuses.most_common())
    situation_bars = "".join(_bar(_translated(name, SITUATION_LABELS), count, len(real_events), "blue") for name, count in situations.most_common())
    gate_bars = "".join(_bar(_translated(name, GATE_LABELS), count, len(real_events), "red") for name, count in gates.most_common(8)) or '<p class="muted">没有可统计的承保门缺失项。</p>'
    score_totals: Counter[str] = Counter()
    for item in shortlist:
        breakdown = item.get("score_breakdown") if isinstance(item.get("score_breakdown"), Mapping) else {}
        for key, value in breakdown.items():
            if key != "total" and isinstance(value, (int, float)):
                score_totals[key] += float(value)
    score_contribution_rows = "".join(
        _bar(
            SCORE_LABELS.get(key, key),
            int(round(value / max(len(shortlist), 1))),
            100,
            "blue",
        )
        for key, value in score_totals.most_common()
    ) or '<p class="muted">本期没有达到 60 分门槛的研究候选。</p>'
    risk_action_values = []
    for item in risk_watchlist[:5]:
        for value in item.get("risk_flags", [])[:2]:
            risk_action_values.append(f"{item.get('symbol', '-')}: {value}")
        for value in item.get("missing_core_evidence", [])[:2]:
            risk_action_values.append(f"{item.get('symbol', '-')}: 待补 {_translated(value, GATE_LABELS)}")
    risk_action_rows = "".join(f"<li>{_escape(value)}</li>" for value in risk_action_values) or "<li>本期没有独立风险观察。</li>"
    shortlist_html = "".join(_priority_item(item) for item in shortlist) or '<p class="muted">本期没有达到 60 分门槛的研究候选；不凑数。</p>'
    risk_watch_html = "".join(_priority_item(item, risk=True) for item in risk_watchlist) or '<p class="muted">本期没有需要独立观察的供给或困境风险。</p>'
    api_explanations = "".join(
        f'<div class="reference-item"><code>{_escape(api)}</code><strong>{_escape(name)}</strong><span>{_escape(description)}</span></div>'
        for api, name, description in API_EXPLANATIONS
    )
    event_explanations = "".join(
        f'<div class="reference-item event-reference"><strong>{_escape(name)}</strong><span>{_escape(description)}</span></div>'
        for name, description in EVENT_EXPLANATIONS
    )
    scope_label = "、".join(
        "全部 A 股" if value == "all_a_share" else str(value)
        for value in coverage.get("scope_types", [])
    ) or "-"
    output = Path(output_html)
    output.parent.mkdir(parents=True, exist_ok=True)
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>克拉曼特殊情况生产承保看板</title><style>
:root{{--ink:#18212b;--muted:#64717f;--line:#d9e0e7;--paper:#f5f7f8;--panel:#fff;--blue:#1478a6;--blue-soft:#e6f2f6;--amber:#a95d08;--amber-soft:#fff3df;--red:#b63832;--red-soft:#ffebe8;--green:#17765d;--green-soft:#e6f5ef}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 "Segoe UI","Microsoft YaHei",sans-serif}}.shell{{max-width:1480px;margin:auto;padding:24px}}header{{display:flex;align-items:flex-end;justify-content:space-between;border-bottom:2px solid var(--ink);padding:0 0 18px;margin-bottom:18px;gap:16px}}h1{{font-size:25px;margin:0;letter-spacing:0;font-weight:700}}h1 span{{color:var(--blue)}}.meta{{color:var(--muted);font-size:12px;text-align:right}}.meta code,code{{font-family:Consolas,monospace;font-size:.92em}}.status{{display:grid;grid-template-columns:1.5fr repeat(4,1fr);gap:10px;margin-bottom:14px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px;min-height:92px}}.card .k{{font-size:11px;color:var(--muted)}}.card .v{{font-size:25px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}}.card .s{{font-size:12px;color:var(--muted);margin-top:3px}}.phases{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin:0 0 14px}}.phase{{background:var(--panel);padding:12px;min-height:102px}}.phase>div{{display:flex;align-items:center;gap:8px}}.phase b{{color:var(--blue);font:700 12px Consolas,monospace}}.phase span:not(.pill){{font-weight:600;font-size:12px}}.phase .pill{{margin-left:auto}}.phase p{{color:var(--muted);font-size:11px;line-height:1.45;margin:10px 0 0}}.alert{{border-left:4px solid var(--amber);background:var(--amber-soft);padding:11px 13px;margin:0 0 14px}}.grid{{display:grid;grid-template-columns:1.05fr .95fr;gap:14px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px;margin-bottom:14px}}.panel h2{{font-size:14px;margin:0 0 4px}}.caption{{color:var(--muted);font-size:12px;margin:0 0 14px}}.bar-row{{display:grid;grid-template-columns:175px 1fr 44px;align-items:center;gap:9px;margin:8px 0}}.bar-row i{{background:#edf0f2;height:10px;border-radius:2px;overflow:hidden}}.bar-row b{{display:block;height:100%}}.blue{{background:var(--blue)}}.amber{{background:var(--amber)}}.red{{background:var(--red)}}.pill{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600}}.pill.amber{{background:var(--amber-soft);color:var(--amber)}}.pill.red{{background:var(--red-soft);color:var(--red)}}.pill.green{{background:var(--green-soft);color:var(--green)}}ul{{padding-left:18px;margin:8px 0}}li{{margin:7px 0}}.table-scroll{{max-height:900px;overflow:auto;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;font-size:12px}}th{{position:sticky;top:0;z-index:1;background:var(--panel);text-align:left;color:var(--muted);font-size:11px}}th,td{{border-bottom:1px solid var(--line);padding:9px 8px;vertical-align:top}}tr:hover td{{background:#f6fafb}}.reference-list{{border-top:1px solid var(--line)}}.reference-item{{display:grid;grid-template-columns:220px 150px 1fr;gap:16px;padding:11px 4px;border-bottom:1px solid var(--line);align-items:start}}.reference-item strong{{font-size:12px}}.reference-item span{{color:#3f4b57;font-size:12px}}.event-reference{{grid-template-columns:150px 1fr}}.muted{{color:var(--muted)}}.footer{{font-size:11px;color:var(--muted);padding:10px 0;overflow-wrap:anywhere}}@media(max-width:1000px){{.phases{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:800px){{.shell{{padding:12px}}header{{align-items:flex-start;flex-direction:column}}h1{{font-size:21px;line-height:1.25}}.meta{{text-align:left}}.status{{grid-template-columns:repeat(2,1fr)}}.status .card:first-child{{grid-column:1/-1}}.grid,.phases{{grid-template-columns:1fr}}.bar-row{{grid-template-columns:minmax(100px,130px) 1fr 30px}}.card{{min-height:auto}}.panel{{padding:13px}}.table-scroll{{max-height:1200px}}.review-table,.review-table thead,.review-table tbody,.review-table tr,.review-table th,.review-table td{{display:block}}.review-table thead{{position:absolute;left:-9999px}}.review-table tr{{border-top:1px solid var(--line);padding:9px 0}}.review-table td{{border:0;padding:3px 0;white-space:normal;overflow-wrap:anywhere}}.review-table td:nth-child(1)::before{{content:"知识截止日 · ";color:var(--muted)}}.review-table td:nth-child(2)::before{{content:"证券 · ";color:var(--muted)}}.review-table td:nth-child(3)::before{{content:"事件 · ";color:var(--muted)}}.review-table td:nth-child(4)::before{{content:"状态 · ";color:var(--muted)}}.review-table td:nth-child(5)::before{{content:"缺失门 · ";color:var(--muted)}}.reference-item,.event-reference{{grid-template-columns:1fr;gap:4px;padding:12px 0}}}}
<section class="grid"><div class="panel"><h2>今日研究候选 <span class="pill blue">{len(shortlist)}/5</span></h2><p class="caption">按透明规则评分排序；最低 60 分、每类最多 3 只，不足不凑数。实时榜使用决策日前最新公开证据。</p>{shortlist_html}</div><div class="panel"><h2>独立风险观察 <span class="pill red">{len(risk_watchlist)}/5</span></h2><p class="caption">定增解禁供给风险与困境风险单独输出，不进入机会榜，也不改变承保状态。</p>{risk_watch_html}</div></section>
<section class="grid"><div class="panel"><h2>评分贡献</h2><p class="caption">研究候选各评分项的平均贡献，满分 100；分数只用于研究排序。</p>{score_contribution_rows}</div><div class="panel"><h2>风险与补证动作</h2><p class="caption">先处理高分风险和关键缺口，再决定是否建立官方证据包。</p><ul>{risk_action_rows}</ul></div></section>
<section class="status"><div class="card"><div class="k">生产健康</div><div class="v">{_escape(_translated(health['status'], STATUS_LABELS))}</div><div class="s">{len(health['alerts'])} 个需关注项</div></div><div class="card"><div class="k">研究候选</div><div class="v">{len(shortlist)}</div><div class="s">最低 60 分，不凑数</div></div><div class="card"><div class="k">风险观察</div><div class="v">{len(risk_watchlist)}</div><div class="s">独立于机会榜</div></div><div class="card"><div class="k">合格承保</div><div class="v">{statuses.get('qualified_special_situation', 0)}</div><div class="s">允许供 Alpha 读取</div></div><div class="card"><div class="k">覆盖缺口</div><div class="v">{len(gaps)}</div><div class="s">接口或数据覆盖不足</div></div></section>
<section class="phases">{phase_cards}</section>
<div class="alert"><strong>承保结果：</strong> 本期 {statuses.get('qualified_special_situation', 0)} 个合格候选。{('零合格候选是有效输出；核心证据缺失不会被事件热度替代。' if statuses.get('qualified_special_situation', 0) == 0 else '合格行仍须由消费方遵守风险预算与独立复核。')}</div>
<section class="grid"><div><div class="panel"><h2>承保漏斗</h2><p class="caption">按最终事件状态。观察名单和证据不足不能作为交易输入。</p>{status_bars}</div><div class="panel"><h2>事件类别</h2><p class="caption">全市场生产快照的事件发现分布。</p>{situation_bars}</div></div><div><div class="panel"><h2>运行与数据告警</h2><ul>{alert_rows}</ul></div><div class="panel"><h2>接口覆盖缺口</h2><ul>{gap_rows}</ul></div><div class="panel"><h2>P3 点时回放</h2><p class="caption">已生成无前视偏差的事件账本；只对合格事件等待价格回放，未解决事件按右删失处理。</p><div><strong>{replay['event_count']}</strong> 事件 · <strong>{replay['eligible_count']}</strong> 可验证 · <strong>{replay['right_censored_count']}</strong> 右删失</div><p class="caption"><code>{_escape(replay['output_path'])}</code></p></div></div></section>
<section class="panel"><h2>待补核心承保门</h2><p class="caption">这是 P2 的工作队列：补证据，而不是放宽门槛。</p>{gate_bars}</section>
<section class="panel"><h2>事件复核队列</h2><p class="caption">展示前 80 条。承保证据不完整与证据不足的记录只能用于研究和证据补齐。</p><div class="table-scroll"><table class="review-table"><thead><tr><th>知识截止日</th><th>证券</th><th>事件</th><th>承保状态</th><th>缺失核心门</th></tr></thead><tbody>{event_rows}</tbody></table></div></section>
<section class="panel"><h2>相关接口说明</h2><p class="caption">以下为本看板生产链使用的 Panda Data 接口。函数名保留原始调用名称，说明为中文业务口径。</p><div class="reference-list">{api_explanations}</div></section>
<section class="panel"><h2>事件解释说明</h2><p class="caption">四类事件都是研究入口，不等于投资结论；只有核心承保门全部通过才可成为合格特殊情况。</p><div class="reference-list">{event_explanations}</div></section>
<footer class="footer">生产文件：<code>{_escape(production.resolve())}</code> · 运行清单：<code>{_escape(str(manifest.get('run_id', '-')))}</code> · 本页面不触发 Panda 查询。</footer></main></body></html>"""
    header_html = (
        '</style></head><body><main class="shell"><header><div>'
        '<h1><span>Q51</span> 克拉曼特殊情况生产承保看板</h1>'
        '<div class="muted">事件发现不是投资结论。研究榜只用于排定复核顺序，完整承保证据才可进入合格候选。</div>'
        '</div><div class="meta">决策日 <code>'
        + _escape(latest_date)
        + '</code> · 版本 <code>'
        + _escape(DATA_VERSION)
        + '</code><br>范围 <span>'
        + _escape(scope_label)
        + '</span> · 生产状态 <span>'
        + _escape(_translated(coverage["status"], STATUS_LABELS))
        + '</span></div></header>\n'
    )
    body = body.replace('<section class="grid">', header_html + '<section class="grid">', 1)
    output.write_text(body, encoding="utf-8")
    return output


def main() -> None:
    output = build(ROOT / "validation" / "production_dashboard.html")
    print(f"[ok] {output}")


if __name__ == "__main__":
    main()
