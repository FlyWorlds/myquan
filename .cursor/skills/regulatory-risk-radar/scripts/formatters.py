"""formatters.py — RegRiskReport 渲染为 JSON / 中文文本 / Markdown"""
from __future__ import annotations
import json

SEV_CN = {"high": "高", "medium": "中", "low": "低"}
SEV_MARK = {"high": "🔴", "medium": "🟠", "low": "🟢"}


def to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def to_text(report: dict) -> str:
    lines = []
    lines.append("=" * 56)
    lines.append("A股合规/监管风险雷达报告")
    lines.append(f"生成时间: {report['generated_at']}   股票池: {report['universe_size']} 只   后端: {report['backend']}")
    lines.append("=" * 56)
    items = report["items"]
    if not items:
        lines.append("（在给定阈值下无风险项）")
    for it in items:
        lines.append("")
        lines.append(f"{SEV_MARK[it['severity']]} {it['symbol']} {it['name']}  "
                     f"风险分 {it['score']}  等级 {SEV_CN[it['severity']]}")
        for t in it["triggers"]:
            ev = t["evidence"]
            ev_str = "  ".join(f"{k}={v}" for k, v in ev.items() if v is not None)
            lines.append(f"    - [{t['subscore']:>5}] {t['label']}: {ev_str}")
    if report.get("degraded_sources"):
        lines.append("")
        lines.append("⚠️ 数据降级（以下风险源未取到，评分可能偏低）:")
        for d in report["degraded_sources"]:
            lines.append(f"    - {d}")
    lines.append("")
    lines.append("免责声明：仅供研究/风控参考，不构成投资建议。数据以公告日期为准，非实时。")
    return "\n".join(lines)


def to_markdown(report: dict) -> str:
    lines = [f"# A股合规风险雷达 — {report['generated_at']}", ""]
    lines.append(f"股票池 {report['universe_size']} 只 · 后端 `{report['backend']}`")
    lines.append("")
    lines.append("| 代码 | 名称 | 风险分 | 等级 | 主要触发 |")
    lines.append("|---|---|---|---|---|")
    for it in report["items"]:
        top = it["triggers"][0]["label"] if it["triggers"] else "-"
        lines.append(f"| {it['symbol']} | {it['name']} | {it['score']} | "
                     f"{SEV_MARK[it['severity']]}{SEV_CN[it['severity']]} | {top} |")
    lines.append("")
    lines.append("> 仅供研究/风控参考，不构成投资建议。")
    return "\n".join(lines)
