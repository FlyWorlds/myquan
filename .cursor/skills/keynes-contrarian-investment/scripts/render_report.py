"""Markdown renderer for Keynes/contrarian research reports."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def _value(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value).replace("|", "\\|")


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# 凯恩斯长期预期与反共识投资研究", "", f"- 分析截止日：`{report.get('as_of', 'N/A')}`", "- 数据来源：**PandaData only**", "- 研究定位：企业性投资与市场预期差分析，不是机械抄底", ""]
    lines += ["## 研究摘要", ""]
    for item in report.get("summary", []):
        lines.append(f"- {item}")
    if not report.get("summary"):
        lines.append("- N/A：尚未生成摘要。")
    lines += ["", "## 凯恩斯框架", "", "> 先判断资产在正常状态下能产生多少长期现金流，再判断市场预期已经反映了多少；反共识不是单纯与大众相反。", "", "- **长期预期：**未来多年收益的估计，受不确定性和信心影响。", "- **企业性投资：**估计资产整个生命周期的预期收益。", "- **投机性预测：**预测其他投资者将如何改变价格。", "- **市场共识：**本报告只能用估值、业绩预告和市场行为构造代理，不能冒充正式一致预期。", ""]
    lines += ["## 标的研究", "", "| 股票 | 研究门控 | 总分 | 覆盖率 | 否决/降级 |", "|---|---|---:|---:|---|"]
    for subject in report.get("subjects", []):
        reasons = "；".join(subject.get("vetoes", []) + subject.get("downgrades", [])) or "—"
        lines.append(f"| {subject.get('symbol', 'N/A')} {subject.get('name') or ''} | {subject.get('score', {}).get('decision_gate', 'N/A')} | {_value(subject.get('score', {}).get('score'))} | {_value(subject.get('score', {}).get('coverage_pct'))}% | {reasons} |")
    if not report.get("subjects"):
        lines.append("| — | N/A | — | — | 没有可分析标的 |")
    for subject in report.get("subjects", []):
        lines += ["", f"### {subject.get('symbol', 'N/A')} {subject.get('name') or ''}", "", "#### 长期预期与现实", "", f"- 市场共识代理：{_value(subject.get('expectation', {}).get('market_consensus_proxy'))}", f"- 价格隐含预期：{_value(subject.get('expectation', {}).get('price_implied_expectation'))}", f"- 基本面耐久性：{_value(subject.get('fundamentals', {}).get('fundamental_confidence'))}", "", "#### 估值与市场定位", "", f"- 估值：`{json.dumps(subject.get('valuation', {}), ensure_ascii=False)}`", f"- 市场行为代理：`{json.dumps(subject.get('market_context', {}), ensure_ascii=False)}`", "", "#### 反共识证据、催化与证伪", "", "- 支持证据：" + ("；".join(subject.get("evidence", [])) or "N/A"), "- 反证：" + ("；".join(subject.get("counter_evidence", [])) or "N/A"), "- 催化剂：" + ("；".join(subject.get("catalysts", [])) or "N/A"), "- 证伪条件：" + ("；".join(subject.get("invalidation", [])) or "N/A")]
    lines += ["", "## 数据限制", ""]
    for item in report.get("limitations", []):
        lines.append(f"- {item}")
    if not report.get("limitations"):
        lines.append("- N/A：未记录额外限制。")
    lines += ["", "## 数据溯源", "", "| 方法 | 状态 | 行数 | 最新日期 | 说明 |", "|---|---|---:|---|---|"]
    for item in report.get("provenance", []):
        lines.append(f"| `{item.get('method', 'N/A')}` | {item.get('status', 'N/A')} | {item.get('rows', 0)} | {item.get('latest_date') or 'N/A'} | {_value(item.get('error') or '—')} |")
    lines += ["", "## 免责声明", "", "> 本报告基于 PandaData 公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。反共识判断可能长期不被市场验证，低估值也可能对应永久性资本损失。", ""]
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
