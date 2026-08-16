"""Generate an offline, standalone Chinese explainer for the Q51 BUILD.

The generator deliberately reads an existing production Parquet snapshot only.
It does not initialise Panda Data, read credentials, or run a market scan.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

try:
    from .core import DATA_VERSION
except ImportError:
    from core import DATA_VERSION


def _resolve_root(script_path: Path) -> Path:
    """Return the BUILD root for either the source tree or a portable delivery."""
    script_root = script_path.resolve().parents[1]
    portable_root = script_root.parent
    if script_root.name == "开发产物" and (portable_root / "生产产物").is_dir():
        return portable_root
    return script_root


ROOT = _resolve_root(Path(__file__))
DEFAULT_PRODUCTION = ROOT / "生产产物" / "数据库.parquet"
DEFAULT_OUTPUT = ROOT / "validation" / "skill_demo.html"
DEFAULT_SCREENSHOT = ROOT / "validation" / "output" / "playwright" / "production-dashboard-desktop.png"
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024

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

STATUS_LABELS = {
    "underwriting_incomplete": "承保证据不完整",
    "insufficient_evidence": "证据不足",
    "qualified_special_situation": "合格特殊情况",
    "rejected": "已排除",
    "risk_watch": "风险观察",
    "no_events": "无事件",
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

GATE_LABELS = {
    "security_access": "证券可交易性",
    "symbol": "证券身份",
    "market_price": "市场价格",
    "catalyst": "事件催化剂",
    "deal_terms": "交易条款",
    "conservative_value": "保守价值",
    "failure_value": "失败价值",
    "capital_structure": "资本结构",
    "legal_accounting": "法律与会计核验",
    "liquidity": "流动性",
    "minimum_margin_of_safety": "最低安全边际",
}

EVENT_FAMILIES = [
    (
        "定增解禁供给风险",
        "定增股份在限售期结束后可流通。系统比较解禁数量、流通盘、参与者浮盈和成交额消化天数，识别潜在供给冲击。",
        "发行价是参与者历史成本，不是二级市场买方可取得的成本，因此只进入风险观察。",
    ),
    (
        "重组或借壳",
        "证监会批文、受理和停复牌等信息先形成催化剂线索，随后核验对价、条件、融资、终止条款和失败价值。",
        "审批不是完成。重组失败压力必须独立测算，不能由事件热度替代。",
    ),
    (
        "分拆上市",
        "从母公司持股比例、子公司保守价值、剩余业务、净债务、税费、控股折价和稀释股数建立保守分部估值。",
        "重大合同金额不等于子公司价值，不能替代分拆估值。",
    ),
    (
        "困境反转",
        "风险警示变化、盈利与现金流改善、审计意见和当前价格共同决定研究优先级，并保留完整的承保缺口。",
        "摘帽或利润改善只是入口，仍须核对债务顺位、资产回收和股权稀释。",
    ),
]

API_GROUPS = [
    (
        "事件发现",
        [
            ("get_stock_private_placement", "定增发行价、数量、上市日期。用于参与者浮盈和供给风险。"),
            ("get_restricted_list", "解禁日期、解禁股数和解禁原因。用于识别未来供给。"),
            ("get_share_float", "流通 A 股分母。用于计算解禁量占流通盘比例。"),
            ("get_stock_csrc_approval", "监管批文与公告。只构成重组或分拆催化剂。"),
            ("get_stock_status_change", "ST、*ST 与状态变化。用于发现困境事件。"),
        ],
    ),
    (
        "市场与基本面核验",
        [
            ("get_stock_daily", "价格、成交额、成交量、停复牌和可交易性。"),
            ("get_fina_reports", "盈利、现金流、负债和资产变化。只使用决策日前披露。"),
            ("get_audit_opinion", "审计意见与持续经营风险。服务法律和会计承保门。"),
            ("get_stock_detail", "证券代码、名称和上市状态。用于身份映射与核验。"),
        ],
    ),
    (
        "背景与风险补充",
        [
            ("get_stock_material_contract", "已识别事件的业务背景，不能单独创建或晋级候选。"),
            ("get_stock_pledge", "控股股东质押风险。"),
            ("get_stock_litigation_arbitration", "重大诉讼、仲裁及潜在赔偿责任。"),
            ("get_cumu_guarantee", "对外担保与或有负债。"),
            ("get_stock_equity_illegal", "股权违规、冻结和监管风险。"),
            ("get_repurchase / get_stock_equity_placard / get_stock_shareholder_change", "回购、举牌与增减持只提供资本行为背景。"),
        ],
    ),
]

P0_P4 = [
    ("P0", "接口治理", "记录接口能力、失败分类和有界重试。接口缺口会降级为 coverage gap，不切换非 Panda 数据源。"),
    ("P1", "可恢复运行", "全市场任务按证券批次写入检查点，并以原子运行清单结束。"),
    ("P2", "官方证据包", "核心事实必须进入 EvidenceAtom。缺交易条款、估值或资本结构时保持不完整。"),
    ("P3", "点时验证", "实时研究和历史回放分别保留证据时间口径，禁止把事件日之后数据带入回放。"),
    ("P4", "生产任务与告警", "统一生成 Parquet、健康报告和看板。只生成结构化告警，不自行发送外部消息。"),
]


def _plain(value: Any, default: str = "-") -> str:
    """Return a display-safe scalar without letting pandas missing values leak into HTML."""
    if value is None:
        return default
    if not isinstance(value, (dict, list, tuple, set)):
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
    text = str(value).strip()
    return text or default


def _escape(value: Any, default: str = "-") -> str:
    return html.escape(_plain(value, default))


def _number(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _date(value: Any) -> str:
    digits = "".join(character for character in _plain(value, "") if character.isdigit())[:8]
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return _plain(value)


def _label(value: Any, labels: Mapping[str, str]) -> str:
    raw = _plain(value)
    return labels.get(raw, raw)


def _text_items(value: Any, *, labels: Mapping[str, str] | None = None, limit: int = 4) -> str:
    if not isinstance(value, list) or not value:
        return "暂无"
    values = []
    for item in value[:limit]:
        raw = _plain(item, "")
        if raw:
            values.append((labels or {}).get(raw, raw))
    return "；".join(values) or "暂无"


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "暂无"
    if not math.isfinite(number):
        return "暂无"
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.2f} 亿"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.2f} 万"
    return f"{number:.2f}"


def _require_cards(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"research_digest.{name} 必须是列表")
    if len(value) > 5:
        raise ValueError(f"research_digest.{name} 超过 5 条，拒绝展示不符合生产契约的快照")
    cards = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"research_digest.{name} 包含非对象记录")
        if item.get("not_trade_signal") is not True:
            raise ValueError(f"research_digest.{name} 缺少 not_trade_signal=true")
        cards.append(dict(item))
    return cards


def load_research_digest(production_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the newest current research digest and a compact, real snapshot summary."""
    production = Path(production_path)
    if not production.is_file():
        raise FileNotFoundError(f"找不到生产 Parquet: {production}")

    frame = pd.read_parquet(production)
    required = {"trade_date", "data_version", "result_type", "result_value", "result_json"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"生产 Parquet 缺少演示页所需字段: {missing}")

    rows = frame.loc[
        frame["data_version"].astype(str).eq(DATA_VERSION)
        & frame["result_type"].astype(str).eq("research_digest")
    ].copy()
    if rows.empty:
        raise ValueError(f"生产 Parquet 中没有 data_version={DATA_VERSION} 的 research_digest")

    sort_columns = ["trade_date"]
    if "update_time" in rows.columns:
        sort_columns.append("update_time")
    row = rows.sort_values(sort_columns, kind="stable", na_position="last").iloc[-1]
    try:
        digest = json.loads(row["result_json"])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("最新 research_digest 的 result_json 无法解析") from exc
    if not isinstance(digest, Mapping):
        raise ValueError("最新 research_digest 的 result_json 必须是对象")
    if digest.get("not_trade_signal") is not True:
        raise ValueError("最新 research_digest 缺少 not_trade_signal=true，拒绝生成讲解页")

    shortlist = _require_cards(digest.get("shortlist", []), "shortlist")
    risks = _require_cards(digest.get("risk_watchlist", []), "risk_watchlist")
    digest = dict(digest)
    digest["shortlist"] = shortlist
    digest["risk_watchlist"] = risks

    same_snapshot = frame.loc[
        frame["data_version"].astype(str).eq(DATA_VERSION)
        & frame["trade_date"].astype(str).eq(str(row["trade_date"]))
    ]
    alpha_eligible = int(
        same_snapshot["result_value"].astype(str).eq("qualified_special_situation").sum()
    )
    excluded = digest.get("excluded_summary")
    excluded = excluded if isinstance(excluded, Mapping) else {}
    summary = {
        "trade_date": _plain(row["trade_date"]),
        "update_time": _plain(row.get("update_time")),
        "shortlist_count": len(shortlist),
        "risk_watch_count": len(risks),
        "unmapped_event_count": _number(digest.get("unmapped_event_count")),
        "opportunity_input_count": _number(excluded.get("opportunity_input_count")),
        "alpha_eligible_count": alpha_eligible,
        "evidence_time_basis": _plain(digest.get("evidence_time_basis")),
        "historical_replay_time_basis": _plain(digest.get("historical_replay_time_basis")),
    }
    return digest, summary


def _score_breakdown(item: Mapping[str, Any]) -> str:
    breakdown = item.get("score_breakdown")
    if not isinstance(breakdown, Mapping):
        return '<span class="muted">暂无评分拆解</span>'
    values = []
    for key, value in breakdown.items():
        if key == "total" or _number(value) == 0:
            continue
        values.append(
            '<span class="score-piece"><span>'
            + _escape(SCORE_LABELS.get(str(key), str(key)))
            + "</span><b>"
            + _escape(_number(value))
            + "</b></span>"
        )
    return "".join(values) or '<span class="muted">暂无非零评分贡献</span>'


def _market_evidence(item: Mapping[str, Any]) -> str:
    market = item.get("current_market_evidence")
    if not isinstance(market, Mapping):
        return "暂无当前市场证据"
    parts = []
    if market.get("date") is not None:
        parts.append(f"日期 {_date(market.get('date'))}")
    if market.get("close") is not None:
        parts.append(f"收盘价 {_money(market.get('close'))}")
    if market.get("average_20d_amount") is not None:
        parts.append(f"20日均额 {_money(market.get('average_20d_amount'))}")
    if market.get("unlock_absorption_days") is not None:
        parts.append(f"解禁消化 {_money(market.get('unlock_absorption_days'))} 日")
    return "；".join(parts) or "暂无当前市场证据"


def _card(item: Mapping[str, Any], *, risk: bool) -> str:
    score = _number(item.get("risk_score") if risk else item.get("score"))
    label = _label(item.get("situation_type"), SITUATION_LABELS)
    title = "独立风险观察" if risk else "研究候选"
    risk_text = _text_items(item.get("risk_flags"), limit=4)
    positive_text = _text_items(item.get("positive_signals"), limit=4)
    missing_text = _text_items(item.get("missing_core_evidence"), labels=GATE_LABELS, limit=4)
    action_text = _text_items(item.get("next_research_actions"), limit=3)
    return "".join(
        [
            f'<article class="study-card {"risk" if risk else "opportunity"}">',
            '<div class="card-top"><div>',
            f'<p class="card-kicker">{_escape(title)} #{_escape(item.get("rank"))}</p>',
            f'<h3>{_escape(item.get("stock_name"))} <code>{_escape(item.get("symbol"))}</code></h3>',
            f'<p class="card-meta">{_escape(label)} | 事件日 {_escape(_date(item.get("event_date")))}</p>',
            "</div>",
            f'<div class="score"><b>{score}</b><span>研究分</span></div>',
            "</div>",
            f'<p class="thesis">{_escape(item.get("thesis"))}</p>',
            '<div class="score-row"><span class="row-label">评分拆解</span><div class="score-list">',
            _score_breakdown(item),
            "</div></div>",
            '<dl class="card-facts">',
            f'<div><dt>当前市场证据</dt><dd>{_escape(_market_evidence(item))}</dd></div>',
            f'<div><dt>{"风险信号" if risk else "正向信号"}</dt><dd>{_escape(risk_text if risk else positive_text)}</dd></div>',
            f'<div><dt>待补核心证据</dt><dd>{_escape(missing_text)}</dd></div>',
            f'<div><dt>下一步研究动作</dt><dd>{_escape(action_text)}</dd></div>',
            "</dl>",
            '<p class="card-boundary">承保状态：'
            + _escape(_label(item.get("underwriting_status"), STATUS_LABELS))
            + "。not_trade_signal=true</p>",
            "</article>",
        ]
    )


def _event_family_cards() -> str:
    return "".join(
        "<article class=\"event-card\"><h3>"
        + _escape(title)
        + "</h3><p>"
        + _escape(description)
        + "</p><strong>边界："
        + _escape(boundary)
        + "</strong></article>"
        for title, description, boundary in EVENT_FAMILIES
    )


def _api_groups() -> str:
    parts = []
    for title, rows in API_GROUPS:
        row_html = "".join(
            "<div class=\"api-row\"><code>"
            + _escape(api)
            + "</code><p>"
            + _escape(description)
            + "</p></div>"
            for api, description in rows
        )
        parts.append(f'<section class="api-group"><h3>{_escape(title)}</h3>{row_html}</section>')
    return "".join(parts)


def _p0_p4_rows() -> str:
    return "".join(
        "<article class=\"phase\"><code>"
        + _escape(code)
        + "</code><div><h3>"
        + _escape(title)
        + "</h3><p>"
        + _escape(description)
        + "</p></div></article>"
        for code, title, description in P0_P4
    )


def _screenshot_section(enabled: bool) -> str:
    if not enabled or not DEFAULT_SCREENSHOT.is_file():
        return ""
    if DEFAULT_SCREENSHOT.stat().st_size > MAX_SCREENSHOT_BYTES:
        return ""
    image_data = base64.b64encode(DEFAULT_SCREENSHOT.read_bytes()).decode("ascii")
    return (
        '<section class="section screenshot-section"><div class="section-heading"><h2>生产看板界面预览</h2>'
        '<p>此预览来自已有的生产看板截图，仅用于录制时说明界面位置。讲解数据以本页读取的 Parquet 快照为准。</p>'
        '</div><figure><img alt="Q51 生产承保看板截图" src="data:image/png;base64,'
        + image_data
        + '"></figure></section>'
    )


def build(
    output_html: str | Path,
    *,
    production_path: str | Path | None = None,
    include_screenshot: bool = True,
) -> Path:
    """Write a standalone explainer HTML page from an existing Parquet snapshot."""
    production = Path(production_path or DEFAULT_PRODUCTION)
    digest, summary = load_research_digest(production)
    shortlist = digest["shortlist"]
    risks = digest["risk_watchlist"]
    exclusion = digest.get("excluded_summary")
    exclusion = exclusion if isinstance(exclusion, Mapping) else {}
    exclusion_reasons = exclusion.get("by_reason")
    exclusion_reasons = exclusion_reasons if isinstance(exclusion_reasons, Mapping) else {}
    reason_text = "；".join(
        f"{_label(key, {'category_cap': '类别上限', 'shortlist_limit': '总榜上限', 'unmapped_event': '待映射事件', 'missing_current_price': '缺当前价格'})} {_number(value)}"
        for key, value in exclusion_reasons.items()
    ) or "本期没有额外排除统计"

    shortlist_html = "".join(_card(item, risk=False) for item in shortlist)
    if not shortlist_html:
        shortlist_html = '<p class="empty">本期没有达到 60 分且满足展示条件的研究候选。系统不以凑数替代证据。</p>'
    risk_html = "".join(_card(item, risk=True) for item in risks)
    if not risk_html:
        risk_html = '<p class="empty">本期没有独立风险观察记录。</p>'

    placeholders = {
        "{{decision_date}}": _escape(_date(summary["trade_date"])),
        "{{update_time}}": _escape(summary["update_time"]),
        "{{shortlist_count}}": str(summary["shortlist_count"]),
        "{{risk_watch_count}}": str(summary["risk_watch_count"]),
        "{{unmapped_event_count}}": str(summary["unmapped_event_count"]),
        "{{opportunity_input_count}}": str(summary["opportunity_input_count"]),
        "{{alpha_eligible_count}}": str(summary["alpha_eligible_count"]),
        "{{evidence_time_basis}}": _escape(summary["evidence_time_basis"]),
        "{{historical_replay_time_basis}}": _escape(summary["historical_replay_time_basis"]),
        "{{exclusion_reasons}}": _escape(reason_text),
        "{{event_cards}}": _event_family_cards(),
        "{{shortlist_cards}}": shortlist_html,
        "{{risk_cards}}": risk_html,
        "{{api_groups}}": _api_groups(),
        "{{phase_rows}}": _p0_p4_rows(),
        "{{screenshot_section}}": _screenshot_section(include_screenshot),
        "{{production_path}}": _escape(production.resolve()),
    }
    page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <link rel="icon" href="data:,">
  <title>Q51 克拉曼特殊情况研究演示</title>
  <style>
    :root {
      --paper: #f5f7f4;
      --panel: #ffffff;
      --ink: #18221d;
      --muted: #5f6c65;
      --line: #d9e1db;
      --accent: #167266;
      --accent-soft: #e2f0eb;
      --warning: #a06a00;
      --warning-soft: #fff4d7;
      --risk: #a53634;
      --risk-soft: #fce9e7;
      --shadow: 0 12px 28px rgba(23, 45, 37, 0.08);
    }
    * { box-sizing: border-box; }
    html { background: var(--paper); }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 15px/1.58 "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    code, pre { font-family: Consolas, "Cascadia Mono", monospace; }
    code { overflow-wrap: anywhere; }
    .shell { width: min(1240px, calc(100% - 40px)); margin: 0 auto; padding: 28px 0 48px; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.75fr);
      gap: 30px;
      align-items: end;
      padding: 26px 0 25px;
      border-bottom: 2px solid var(--ink);
    }
    .eyebrow { color: var(--accent); font: 700 12px/1.3 Consolas, monospace; margin: 0 0 10px; }
    h1, h2, h3, p { margin-top: 0; }
    h1 { max-width: 760px; margin-bottom: 12px; font-size: 38px; line-height: 1.15; font-weight: 760; }
    .hero p { max-width: 680px; margin-bottom: 0; color: var(--muted); }
    .hero-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .meta-block { padding: 11px 12px; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; }
    .meta-block span { display: block; color: var(--muted); font-size: 12px; }
    .meta-block strong { display: block; margin-top: 3px; font-size: 14px; overflow-wrap: anywhere; }
    .meta-block.boundary { grid-column: 1 / -1; border-color: var(--accent); background: var(--accent-soft); }
    .meta-block.boundary strong { color: #0b4b43; }
    .section { padding: 38px 0; border-bottom: 1px solid var(--line); }
    .section-heading { max-width: 800px; margin-bottom: 18px; }
    h2 { margin-bottom: 7px; font-size: 25px; line-height: 1.25; }
    .section-heading p, .section > p { color: var(--muted); margin-bottom: 0; }
    .event-grid { display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 12px; }
    .event-card, .contract-panel, .study-card, .phase, .api-group, .recording { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
    .event-card { padding: 17px; }
    .event-card:nth-child(1), .event-card:nth-child(4) { background: #f8fbf9; }
    .event-card h3 { margin-bottom: 7px; font-size: 17px; }
    .event-card p { color: var(--muted); margin-bottom: 10px; }
    .event-card strong { display: block; color: #315047; font-size: 13px; font-weight: 650; }
    .contract-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
    .contract-panel { min-width: 0; padding: 18px; }
    .contract-panel h3 { margin-bottom: 8px; font-size: 17px; }
    .contract-panel p { color: var(--muted); }
    pre { margin: 12px 0 0; padding: 14px; border-radius: 6px; background: #edf2ef; color: #244238; font-size: 12px; line-height: 1.55; overflow: auto; }
    .contract-list { padding-left: 20px; margin: 12px 0 0; }
    .contract-list li { margin: 7px 0; }
    .snapshot-strip { display: grid; grid-template-columns: 1.2fr repeat(3, 0.8fr); gap: 10px; margin-bottom: 18px; }
    .snapshot-stat { padding: 14px; border-left: 3px solid var(--accent); background: var(--panel); }
    .snapshot-stat p { margin: 0; color: var(--muted); font-size: 12px; }
    .snapshot-stat strong { display: block; margin-top: 3px; font-size: 25px; font-variant-numeric: tabular-nums; }
    .snapshot-stat:first-child strong { font-size: 17px; line-height: 1.4; }
    .study-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .study-card { padding: 16px; box-shadow: var(--shadow); min-width: 0; }
    .study-card.risk { border-left: 3px solid var(--risk); }
    .study-card.opportunity { border-left: 3px solid var(--accent); }
    .card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .card-kicker { color: var(--muted); font-size: 12px; margin-bottom: 5px; }
    .card-top h3 { margin-bottom: 4px; font-size: 18px; overflow-wrap: anywhere; }
    .card-top h3 code { color: var(--accent); font-size: 13px; font-weight: 650; }
    .card-meta { color: var(--muted); font-size: 12px; margin-bottom: 0; }
    .score { flex: 0 0 52px; text-align: right; }
    .score b { display: block; color: var(--accent); font-size: 28px; line-height: 1; font-variant-numeric: tabular-nums; }
    .risk .score b { color: var(--risk); }
    .score span { color: var(--muted); font-size: 11px; }
    .thesis { margin: 15px 0 12px; font-weight: 650; }
    .score-row { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid var(--line); }
    .row-label { color: var(--muted); font-size: 12px; }
    .score-list { display: flex; flex-wrap: wrap; gap: 6px; }
    .score-piece { display: inline-flex; gap: 5px; align-items: baseline; color: #3d5148; font-size: 11px; }
    .score-piece b { color: var(--accent); font-variant-numeric: tabular-nums; }
    .card-facts { margin: 0; }
    .card-facts div { padding: 7px 0; border-top: 1px solid var(--line); }
    .card-facts dt { color: var(--muted); font-size: 11px; }
    .card-facts dd { margin: 2px 0 0; font-size: 12px; overflow-wrap: anywhere; }
    .card-boundary { margin: 11px 0 0; padding: 8px 9px; border-radius: 5px; color: #315047; background: var(--accent-soft); font-size: 11px; font-weight: 650; }
    .risk .card-boundary { color: #74312f; background: var(--risk-soft); }
    .empty { padding: 22px; margin: 0; color: var(--muted); border: 1px dashed var(--line); }
    .boundary-layout { display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 18px; align-items: start; }
    .boundary-card { padding: 18px; border-left: 4px solid var(--accent); background: var(--accent-soft); }
    .boundary-card h3 { margin-bottom: 8px; font-size: 18px; }
    .boundary-card p { margin-bottom: 0; color: #315047; }
    .path { display: grid; gap: 7px; }
    .path-item { position: relative; padding: 12px 14px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; font-weight: 650; }
    .path-item:last-child { border-color: var(--accent); color: #0b4b43; }
    .path-item span { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; font-weight: 400; }
    .audit-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
    .phase { padding: 14px; min-width: 0; }
    .phase > code { color: var(--accent); font-size: 12px; font-weight: 700; }
    .phase h3 { margin: 8px 0 5px; font-size: 15px; }
    .phase p { margin-bottom: 0; color: var(--muted); font-size: 12px; }
    .api-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .api-group { padding: 15px; }
    .api-group h3 { margin-bottom: 9px; font-size: 16px; }
    .api-row { padding: 10px 0; border-top: 1px solid var(--line); }
    .api-row code { color: var(--accent); font-size: 11px; font-weight: 700; }
    .api-row p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
    .recording { padding: 18px; background: #f8fbf9; }
    .recording h2 { margin-bottom: 8px; }
    .recording ol { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 28px; padding-left: 20px; margin: 14px 0 0; }
    .recording li { padding-left: 3px; }
    .recording li strong { display: block; margin-bottom: 3px; }
    .recording li span { color: var(--muted); font-size: 13px; }
    .screenshot-section figure { margin: 0; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 10px; overflow: hidden; }
    .screenshot-section img { display: block; width: 100%; height: auto; border-radius: 4px; }
    footer { padding: 22px 0 0; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    @media (prefers-color-scheme: dark) {
      :root {
        --paper: #16201b;
        --panel: #1d2a24;
        --ink: #edf5ef;
        --muted: #b0c0b6;
        --line: #34463b;
        --accent: #6ac3aa;
        --accent-soft: #183a30;
        --warning: #f0c15d;
        --warning-soft: #443517;
        --risk: #f09a95;
        --risk-soft: #4a2928;
        --shadow: none;
      }
      .event-card:nth-child(1), .event-card:nth-child(4), .recording { background: #1a2721; }
      pre { background: #132019; color: #d8eee1; }
      .meta-block.boundary strong, .card-boundary, .boundary-card p, .path-item:last-child { color: #bcebdc; }
      .score-piece { color: #cfdfd5; }
      .risk .card-boundary { color: #ffd0cc; }
    }
    @media (max-width: 920px) {
      .hero, .contract-layout, .boundary-layout { grid-template-columns: 1fr; }
      .audit-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .api-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 680px) {
      .shell { width: min(100% - 24px, 1240px); padding-top: 16px; }
      .hero { gap: 18px; padding-top: 8px; }
      h1 { font-size: 29px; }
      h2 { font-size: 22px; }
      .hero-meta, .snapshot-strip, .study-grid, .event-grid, .recording ol, .audit-grid { grid-template-columns: 1fr; }
      .study-card { padding: 14px; }
      .snapshot-stat { min-height: auto; }
      .section { padding: 28px 0; }
      .score-row { grid-template-columns: 1fr; gap: 6px; }
      .recording ol { gap: 12px; }
      .contract-layout { grid-template-columns: minmax(0, 1fr); }
      pre { white-space: pre-wrap; overflow-wrap: anywhere; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">Q51 / 克拉曼特殊情况研究</p>
        <h1>把事件线索变成可复核的研究队列</h1>
        <p>这是一份离线讲解页。它从既有生产 Parquet 读取真实快照，展示研究候选、独立风险观察和承保边界，不发起 Panda Data 查询。</p>
      </div>
      <div class="hero-meta">
        <div class="meta-block"><span>决策日</span><strong>{{decision_date}}</strong></div>
        <div class="meta-block"><span>逻辑版本</span><strong>{{data_version}}</strong></div>
        <div class="meta-block boundary"><span>研究边界</span><strong>not_trade_signal=true</strong></div>
      </div>
    </header>

    <section class="section">
      <div class="section-heading">
        <h2>四类事件都是研究入口</h2>
        <p>系统先把复杂事件整理为可比较的待研究问题，再把证据、估值和失败情景交给严格承保层。</p>
      </div>
      <div class="event-grid">{{event_cards}}</div>
    </section>

    <section class="section">
      <div class="section-heading">
        <h2>调用与输出契约</h2>
        <p>真实扫描通过 Panda Data 获取结构化数据。演示页只消费扫描后已经落地的生产结果。</p>
      </div>
      <div class="contract-layout">
        <article class="contract-panel">
          <h3>调用 BUILD</h3>
          <pre>from scripts.build import run

result = run(
    {"as_of_date": "20260724", "start_date": "20250724"},
    config={"evidence_dir": "官方证据目录"},
)</pre>
          <p>入口会校验输入、记录数据能力和证据时间口径，再返回稳定的 BUILD envelope。</p>
        </article>
        <article class="contract-panel">
          <h3>消费研究摘要</h3>
          <ul class="contract-list">
            <li><code>research_digest.shortlist</code>：最多 5 条、每类最多 3 条、最低 60 分。</li>
            <li><code>research_digest.risk_watchlist</code>：独立的供给和困境风险清单。</li>
            <li>所有研究卡固定带 <code>not_trade_signal=true</code>。</li>
            <li>只有原始事件行的 <code>qualified_special_situation</code> 才允许 Alpha 读取。</li>
          </ul>
        </article>
      </div>
    </section>

    <section class="section">
      <div class="section-heading">
        <h2>本次生产快照</h2>
        <p>更新时间 {{update_time}}。实时研究使用决策日前最新公开证据，历史回放使用事件时点可见证据，两种口径分别保存。</p>
      </div>
      <div class="snapshot-strip">
        <div class="snapshot-stat"><p>实时证据口径</p><strong>{{evidence_time_basis}}</strong></div>
        <div class="snapshot-stat"><p>研究候选</p><strong>{{shortlist_count}} / 5</strong></div>
        <div class="snapshot-stat"><p>独立风险观察</p><strong>{{risk_watch_count}} / 5</strong></div>
        <div class="snapshot-stat"><p>待映射批文</p><strong>{{unmapped_event_count}}</strong></div>
      </div>
      <p class="section-note">机会输入 {{opportunity_input_count}} 条。排除统计：{{exclusion_reasons}}。</p>
    </section>

    <section class="section">
      <div class="section-heading">
        <h2>今日优先研究什么</h2>
        <p>分数用于排序，不替代交易条款、资本结构、保守价值、失败价值、法律审计与流动性的逐项核验。</p>
      </div>
      <div class="study-grid">{{shortlist_cards}}</div>
    </section>

    <section class="section">
      <div class="section-heading">
        <h2>哪些风险需要独立观察</h2>
        <p>定增解禁和困境风险不与机会榜混排。高风险分表示优先核验，不表示可以采取交易动作。</p>
      </div>
      <div class="study-grid">{{risk_cards}}</div>
    </section>

    <section class="section">
      <div class="section-heading">
        <h2>研究排序不会绕过承保</h2>
        <p>这是这套 BUILD 最重要的边界。任何缺失核心事实的高分卡，都只能停留在研究与补证阶段。</p>
      </div>
      <div class="boundary-layout">
        <article class="boundary-card">
          <h3>Alpha 消费边界</h3>
          <p>本次快照中原始事件行的 <code>qualified_special_situation</code> 数量为 <strong>{{alpha_eligible_count}}</strong>。研究摘要从不直接成为 Alpha 输入。</p>
        </article>
        <div class="path">
          <div class="path-item">事件发现<span>定增、重组、分拆、困境反转</span></div>
          <div class="path-item">研究优先级<span>透明评分与风险清单</span></div>
          <div class="path-item">官方证据与承保门<span>条款、估值、失败价值、资本结构、审计、流动性</span></div>
          <div class="path-item">合格特殊情况<span>仅原始事件行可供 Alpha 继续使用</span></div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-heading">
        <h2>生产审计链</h2>
        <p>从接口治理到生产告警，每一步都保留可复核的结果，而不是只输出一个候选名单。</p>
      </div>
      <div class="audit-grid">{{phase_rows}}</div>
    </section>

    {{screenshot_section}}

    <section class="section">
      <div class="section-heading">
        <h2>相关 Panda Data 接口</h2>
        <p>接口函数名保留原始名称，页面用中文说明其用途和承保边界。可选接口不可用时会形成覆盖缺口，不会临时换源。</p>
      </div>
      <div class="api-grid">{{api_groups}}</div>
    </section>

    <section class="section">
      <article class="recording">
        <h2>录制时按这个顺序讲</h2>
        <ol>
          <li><strong>先讲边界</strong><span>研究优先级不是交易信号，所有卡都保留 not_trade_signal=true。</span></li>
          <li><strong>再讲四类事件</strong><span>说明定增解禁是供给风险，其他三类是待承保的研究入口。</span></li>
          <li><strong>展示真实清单</strong><span>点开研究候选和风险观察，讲分数拆解、缺失证据和下一步动作。</span></li>
          <li><strong>最后讲承保与 Alpha</strong><span>强调只有原始合格事件行可继续被 Alpha 使用，并展示 P0-P4 审计链。</span></li>
        </ol>
      </article>
    </section>

    <footer>
      生产来源：<code>{{production_path}}</code><br>
      本页只读取已有生产 Parquet 和可选的本地界面截图。不会读取账户、密码、Token，也不会发起 Panda Data 查询。
    </footer>
  </main>
</body>
</html>
"""
    placeholders["{{data_version}}"] = _escape(DATA_VERSION)
    for marker, value in placeholders.items():
        page = page.replace(marker, value)

    output = Path(output_html)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="从生产 Parquet 生成 Q51 中文演示讲解页")
    parser.add_argument("--production-path", type=Path, default=DEFAULT_PRODUCTION, help="现有生产 Parquet 路径")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 HTML 路径")
    parser.add_argument("--no-screenshot", action="store_true", help="不嵌入已有生产看板截图")
    args = parser.parse_args()
    output = build(
        args.output,
        production_path=args.production_path,
        include_screenshot=not args.no_screenshot,
    )
    print(f"[ok] {output.resolve()}")


if __name__ == "__main__":
    main()
