#!/usr/bin/env python3
"""PandaData-only A-share oversold-rebound timing and candidate scanner."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from indicators import cross_section_snapshot, latest_snapshot, to_numeric_frame
from pandadata_source import (
    CallResult,
    PandaDataSource,
    fetch_etf_proxy,
    fetch_index_daily,
    fetch_index_universe,
    fetch_national_team,
    fetch_northbound_hold,
    fetch_recent_funds,
    fetch_stock_daily,
    fetch_stock_metadata,
    normalize_symbol,
    probe_interfaces,
    resolve_as_of,
)
from scoring import (
    aggregate_market,
    analyze_etf_proxy,
    analyze_lhb,
    analyze_margin,
    analyze_national_team,
    analyze_northbound,
    score_candidate,
    score_fund_structure,
    score_market_flow,
    score_sentiment,
    score_tape,
)


DEFAULT_JSON = "/tmp/oversold_rebound.json"
DEFAULT_MD = "/tmp/oversold_rebound.md"
UNIVERSE_LABELS = {
    "csi300": "沪深300",
    "csi500": "中证500",
    "csi1000": "中证1000",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="严格使用 PandaData 的 A 股超跌反弹择时与选股"
    )
    parser.add_argument(
        "--universe",
        choices=tuple(UNIVERSE_LABELS),
        default="csi300",
        help="指数成分股池：csi300/csi500/csi1000，默认csi300",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=[],
        help="手工指定股票代码；传入后覆盖 --universe，主要用于定向研究",
    )
    parser.add_argument("--as-of", help="分析截止日 YYYYMMDD，默认最近完整交易日")
    parser.add_argument("--top-n", type=int, default=20, help="候选数量，默认20")
    parser.add_argument("--min-amount", type=float, default=50_000_000, help="20日平均成交额降级阈值，默认5000万")
    parser.add_argument("--out-json", default=DEFAULT_JSON)
    parser.add_argument("--out-md", default=DEFAULT_MD)
    parser.add_argument("--probe-only", action="store_true", help="只探测接口与字段，不运行扫描")
    return parser.parse_args()


def normalize_symbols(symbols: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for symbol in symbols:
        value = normalize_symbol(symbol)
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def first_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lower_map = {str(column).lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        for lowered, original in lower_map.items():
            if candidate in lowered:
                return original
    return None


def metadata_maps(results: dict[str, CallResult]) -> tuple[dict[str, str], dict[str, str]]:
    names: dict[str, str] = {}
    industries: dict[str, str] = {}
    detail = results["detail"].data if results.get("detail") and results["detail"].ok else pd.DataFrame()
    if not detail.empty and "symbol" in detail.columns:
        name_col = first_column(detail, ("name", "symbol_cn", "sec_name", "stock_name"))
        if name_col:
            names = {
                str(row["symbol"]): str(row[name_col])
                for _, row in detail[["symbol", name_col]].dropna().drop_duplicates("symbol", keep="last").iterrows()
            }
    industry = results["industry"].data if results.get("industry") and results["industry"].ok else pd.DataFrame()
    if not industry.empty:
        symbol_col = first_column(industry, ("stock_symbol", "symbol"))
        industry_col = first_column(industry, ("industry_name", "industry", "name"))
        if symbol_col and industry_col:
            industries = {
                str(row[symbol_col]): str(row[industry_col])
                for _, row in industry[[symbol_col, industry_col]].dropna().drop_duplicates(symbol_col, keep="last").iterrows()
            }
    return names, industries


def per_symbol_fund_signal(symbol: str, funds: dict[str, pd.DataFrame]) -> dict[str, Any] | None:
    items: list[tuple[str, dict[str, Any] | None, float]] = []
    for label, analyzer, key, weight in (
        ("融资", analyze_margin, "margin", 45.0),
        ("北向持仓", analyze_northbound, "northbound", 30.0),
        ("龙虎榜机构", analyze_lhb, "lhb", 25.0),
    ):
        frame = funds.get(key, pd.DataFrame())
        if not frame.empty and "symbol" in frame.columns:
            frame = frame[frame["symbol"].astype(str) == symbol]
        analyzed = analyzer(frame)
        items.append((label, analyzed, weight))
    available = [(label, item, weight) for label, item, weight in items if item and item.get("score") is not None]
    if not available:
        return None
    denominator = sum(weight for _, _, weight in available)
    score = sum(float(item["score"]) * weight for _, item, weight in available) / denominator
    return {
        "score": round(score, 1),
        "coverage_pct": round(denominator / 100 * 100, 1),
        "evidence": [item["evidence"] for _, item, _ in available],
    }


def calculate_industry_strength(
    snapshots: dict[str, dict[str, Any]], industries: dict[str, str], market_ret_5d: float | None
) -> dict[str, float | None]:
    industry_values: dict[str, list[float]] = {}
    for symbol, snapshot in snapshots.items():
        industry = industries.get(symbol)
        value = snapshot.get("ret_5d")
        if industry and value is not None:
            industry_values.setdefault(industry, []).append(float(value))
    industry_means = {
        industry: float(np.median(values))
        for industry, values in industry_values.items()
        if len(values) >= 3
    }
    strengths: dict[str, float | None] = {}
    for symbol, snapshot in snapshots.items():
        value = snapshot.get("ret_5d")
        industry = industries.get(symbol)
        benchmark = industry_means.get(industry) if industry else market_ret_5d
        strengths[symbol] = (
            float(value) - float(benchmark)
            if value is not None and benchmark is not None
            else None
        )
    return strengths


def market_return_5d(index_frame: pd.DataFrame) -> float | None:
    if index_frame.empty or "symbol" not in index_frame.columns:
        return None
    frame = index_frame[index_frame["symbol"].astype(str) == "000300.SH"]
    snapshot = latest_snapshot(frame) if len(frame) >= 10 else {}
    value = snapshot.get("ret_5d")
    return float(value) if value is not None else None


def build_probe_report(source: PandaDataSource, as_of: str) -> dict[str, Any]:
    probes = probe_interfaces(source, as_of)
    statuses = {name: result.provenance() for name, result in probes.items()}
    ok = sum(item["status"] == "ok" for item in statuses.values())
    return {
        "mode": "probe",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "summary": {
            "ok": ok,
            "total": len(statuses),
            "etf_net_creation_available": statuses["etf_net_creation"]["status"] == "ok",
            "strict_source": "PandaData only",
        },
        "interfaces": statuses,
        "rules": [
            "接口存在不等于服务端可用；以本次状态为准。",
            "empty/error/unsupported 不填0，也不当作中性。",
            "ETF接口失败时，国家队ETF代理保持N/A。",
        ],
    }


def build_scan_report(
    source: PandaDataSource,
    as_of: str,
    symbols: list[str],
    universe: str,
    top_n: int,
    min_amount: float,
) -> dict[str, Any]:
    if symbols:
        candidate_symbols = symbols
        universe_info = {
            "type": "specified",
            "key": "custom",
            "name": "手工指定股票池",
            "index_symbol": None,
            "constituent_date": None,
            "requested_symbols": symbols,
            "constituent_count": len(symbols),
        }
    else:
        universe_result = fetch_index_universe(source, as_of, universe)
        if not universe_result.ok:
            raise RuntimeError(
                f"无法获取{UNIVERSE_LABELS[universe]}成分股："
                f"{universe_result.status} - {universe_result.error}"
            )
        candidate_symbols = normalize_symbols(
            universe_result.data["stock_symbol"].dropna().astype(str).tolist()
        )
        if not candidate_symbols:
            raise RuntimeError(f"{UNIVERSE_LABELS[universe]}成分股快照为空")
        universe_info = {
            "type": "index_constituents",
            "key": universe,
            "name": UNIVERSE_LABELS[universe],
            "index_symbol": {
                "csi300": "000300.SH",
                "csi500": "000905.SH",
                "csi1000": "000852.SH",
            }[universe],
            "constituent_date": universe_result.latest_date,
            "requested_symbols": [],
            "constituent_count": len(candidate_symbols),
        }

    # Market timing always uses the full A-share cross-section. The selected
    # index pool only narrows candidate scoring; it never redefines sentiment.
    market_stock_result = fetch_stock_daily(source, as_of, None)
    if symbols:
        candidate_stock_result = fetch_stock_daily(source, as_of, candidate_symbols)
    elif market_stock_result.ok:
        pool = set(candidate_symbols)
        candidate_frame = market_stock_result.data[
            market_stock_result.data["symbol"].astype(str).isin(pool)
        ].copy()
        candidate_stock_result = CallResult(
            method="get_stock_daily[index_filter]",
            status="ok" if not candidate_frame.empty else "empty",
            data=candidate_frame,
            rows=len(candidate_frame),
            columns=[str(column) for column in candidate_frame.columns],
            latest_date=market_stock_result.latest_date,
            params={"universe": universe, "symbol_count": len(candidate_symbols)},
            error=None if not candidate_frame.empty else "全市场日线中未匹配到指数成分股",
        )
    else:
        candidate_stock_result = market_stock_result
    index_result = fetch_index_daily(source, as_of)
    market_funds_results = fetch_recent_funds(source, as_of, None)
    # The all-market fund frames already contain any index constituents and
    # avoid sending a 300–1000 symbol parameter to interfaces with batch limits.
    candidate_funds_results = market_funds_results
    metadata_results = fetch_stock_metadata(source, symbols or None)
    # National-team evidence is a market dimension, so it must not change with
    # the user's candidate pool.
    holder_result = fetch_national_team(source, as_of, None)
    etf_results = fetch_etf_proxy(source, as_of)

    market_stock_frame = market_stock_result.data if market_stock_result.ok else pd.DataFrame()
    if not market_stock_frame.empty:
        market_stock_frame = market_stock_frame[
            market_stock_frame["date"].astype(str).str.replace("-", "", regex=False) <= as_of
        ]
    stock_frame = candidate_stock_result.data if candidate_stock_result.ok else pd.DataFrame()
    if not stock_frame.empty:
        stock_frame = stock_frame[
            stock_frame["date"].astype(str).str.replace("-", "", regex=False) <= as_of
        ]
    index_frame = index_result.data if index_result.ok else pd.DataFrame()
    if not index_frame.empty:
        index_frame = index_frame[index_frame["date"].astype(str).str.replace("-", "", regex=False) <= as_of]

    breadth = cross_section_snapshot(market_stock_frame)
    etf_proxy = analyze_etf_proxy(
        etf_results["etf_net_creation"].data
        if etf_results["etf_net_creation"].ok
        else pd.DataFrame()
    )
    market_fund_frames = {
        key: result.data if result.ok else pd.DataFrame()
        for key, result in market_funds_results.items()
    }
    # get_hsgt_hold returns data for an explicit symbol list; fetch the
    # selected index pool separately and use it for both market structure and
    # per-candidate signals. The empty all-market call remains provenance only.
    if candidate_symbols:
        northbound_result = fetch_northbound_hold(source, as_of, candidate_symbols)
        if northbound_result.ok:
            market_fund_frames["northbound"] = northbound_result.data
            candidate_funds_results["northbound"] = northbound_result
    candidate_fund_frames = {
        key: result.data if result.ok else pd.DataFrame()
        for key, result in candidate_funds_results.items()
    }

    dimensions = {
        "市场情绪": score_sentiment(breadth),
        "大盘资金流向": score_market_flow(breadth, etf_proxy),
        "资金结构": score_fund_structure(market_fund_frames),
        "盘面特点": score_tape(index_frame),
        "国家队证据": analyze_national_team(
            holder_result.data if holder_result.ok else pd.DataFrame(), etf_proxy
        ),
    }
    market = aggregate_market(dimensions, breadth)

    names, industries = metadata_maps(metadata_results)
    snapshots: dict[str, dict[str, Any]] = {}
    if not stock_frame.empty and "symbol" in stock_frame.columns:
        for symbol, group in stock_frame.groupby("symbol", sort=False):
            snapshots[str(symbol)] = latest_snapshot(group)
    relative_strengths = calculate_industry_strength(
        snapshots, industries, market_return_5d(index_frame)
    )

    candidates = []
    for symbol, snapshot in snapshots.items():
        candidate = score_candidate(
            symbol=symbol,
            snapshot=snapshot,
            market=market,
            fund_signal=per_symbol_fund_signal(symbol, candidate_fund_frames),
            relative_strength=relative_strengths.get(symbol),
            name=names.get(symbol),
            min_amount=min_amount,
        )
        candidate["industry"] = industries.get(symbol)
        candidates.append(candidate)

    selected = sorted(
        (item for item in candidates if item["selected"]),
        key=lambda item: (item["score"] is not None, item["score"] or -1),
        reverse=True,
    )[:top_n]
    rejected = sorted(
        (item for item in candidates if not item["selected"]),
        key=lambda item: item["score"] or -1,
        reverse=True,
    )[: min(50, max(top_n, 20))]

    limitations = []
    for label, dimension_data in dimensions.items():
        limitations.extend(f"{label}: {reason}" for reason in dimension_data.get("missing", []))
    if not market_stock_result.ok:
        limitations.append(
            f"全市场行情不可用: {market_stock_result.status} - {market_stock_result.error}"
        )
    if not candidate_stock_result.ok:
        limitations.append(
            f"候选池行情不可用: {candidate_stock_result.status} - {candidate_stock_result.error}"
        )

    return {
        "mode": "scan",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "universe": {
            **universe_info,
            "stocks_with_history": len(snapshots),
            "latest_cross_section_size": breadth.get("sample_size"),
        },
        "market": market,
        "dimensions": dimensions,
        "breadth": breadth,
        "national_team": dimensions["国家队证据"],
        "candidates": selected,
        "rejected": rejected,
        "limitations": list(dict.fromkeys(limitations)),
        "provenance": source.provenance(),
        "methodology": {
            "horizon": "1–10 trading days",
            "strict_source": "PandaData only",
            "na_rule": "missing values are excluded from weighted denominators, never filled with zero",
            "execution_assumption": "daily close signals can only be acted on from the next trading day",
        },
        "disclaimer": "本报告基于 PandaData 公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。超跌可能继续下跌。",
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) or np.isinf(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NA:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def format_value(value: Any, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def probe_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PandaData 接口探测 · 超跌反弹 Skill",
        "",
        f"- 分析截止日：`{report['as_of']}`",
        f"- 可用接口：**{report['summary']['ok']} / {report['summary']['total']}**",
        f"- ETF净申赎：**{'可用' if report['summary']['etf_net_creation_available'] else 'N/A'}**",
        f"- 数据策略：**{report['summary']['strict_source']}**",
        "",
        "## 接口状态",
        "",
        "| 模块 | 方法 | 状态 | 行数 | 最新日期 | 字段 | 说明 |",
        "|---|---|---|---:|---|---|---|",
    ]
    for name, item in report["interfaces"].items():
        columns = ", ".join(item.get("columns", [])[:8]) or "—"
        error = (item.get("error") or "—").replace("|", "\\|")
        lines.append(
            f"| {name} | `{item['method']}` | {item['status']} | {item['rows']} | "
            f"{item.get('latest_date') or '—'} | {columns} | {error} |"
        )
    lines.extend(["", "## 规则", ""])
    lines.extend(f"- {rule}" for rule in report["rules"])
    return "\n".join(lines) + "\n"


def scan_markdown(report: dict[str, Any]) -> str:
    market = report["market"]
    gate_text = {"PASS": "通过", "CAUTION": "谨慎通过", "FAIL": "未通过"}.get(market["market_gate"], market["market_gate"])
    lines = [
        "# A股超跌反弹扫描",
        "",
        "## 结论摘要",
        "",
        f"- 分析截止日：`{report['as_of']}`（只使用该日及以前的数据）",
        f"- 市场阶段：**{market['stage']}**",
        f"- 反弹环境分：**{format_value(market['environment_score'], '/100')}**；数据覆盖率 **{market['coverage_pct']}%**",
        f"- 市场门控：**{gate_text}**",
        f"- 股票池：**{report['universe']['name']}**；成分/指定 {report['universe']['constituent_count']} 只；有效历史 {report['universe']['stocks_with_history']} 只",
        f"- 成分股快照日：{report['universe'].get('constituent_date') or '手工指定，不适用'}",
        f"- 国家队证据：**{report['national_team']['evidence_level']}** — {report['national_team']['interpretation']}",
        "",
        "阶段依据：" + "；".join(market["reasons"]),
        "",
        "## 五维环境",
        "",
        "| 维度 | 得分 | 子项覆盖率 | 证据摘要 | 缺失/限制 |",
        "|---|---:|---:|---|---|",
    ]
    for name, item in report["dimensions"].items():
        evidence_parts = []
        for evidence in item.get("evidence", [])[:3]:
            if isinstance(evidence, dict):
                evidence_parts.append(
                    f"{evidence.get('holder', '明确主体')}@{evidence.get('report_date') or '未知报告期'}"
                    f"(比例变化={format_value(evidence.get('holding_ratio_change'))})"
                )
            else:
                evidence_parts.append(str(evidence))
        evidence = ("；".join(evidence_parts) or "N/A").replace("|", "\\|")
        missing = ("；".join(item.get("missing", [])) or "—").replace("|", "\\|")
        lines.append(
            f"| {name} | {format_value(item.get('score'))} | {item.get('coverage_pct', 0)}% | "
            f"{evidence} | {missing} |"
        )

    lines.extend([
        "",
        "## 国家队证据",
        "",
        f"- 等级：**{report['national_team']['evidence_level']}**",
        f"- 解读：{report['national_team']['interpretation']}",
    ])
    for evidence in report["national_team"].get("evidence", []):
        if isinstance(evidence, dict):
            lines.append(
                f"- {evidence.get('symbol') or 'N/A'}｜{evidence.get('holder')}｜"
                f"报告期 {evidence.get('report_date') or 'N/A'}｜披露日 {evidence.get('publish_date') or 'N/A'}｜"
                f"持股 {format_value(evidence.get('holding'))}｜比例 {format_value(evidence.get('holding_ratio'))}｜"
                f"比例变化 {format_value(evidence.get('holding_ratio_change'))}"
            )
        else:
            lines.append(f"- {evidence}")
    if not report["national_team"].get("evidence"):
        lines.append("- N/A：无可验证硬证据或可用 ETF 代理数据。")

    lines.extend([
        "",
        "## 反弹候选",
        "",
        "| # | 股票 | 行业 | 总分 | 覆盖率 | 市场门控 | 观察窗 | 核心证据 |",
        "|---:|---|---|---:|---:|---|---|---|",
    ])
    for index, candidate in enumerate(report["candidates"], 1):
        stock = candidate["symbol"]
        if candidate.get("name"):
            stock += f" {candidate['name']}"
        evidence = ("；".join(candidate.get("evidence", [])[:3]) or "N/A").replace("|", "\\|")
        lines.append(
            f"| {index} | {stock} | {candidate.get('industry') or 'N/A'} | "
            f"{format_value(candidate.get('score'))} | {candidate['coverage_pct']}% | "
            f"{candidate['market_gate']} | {candidate['expected_window']} | {evidence} |"
        )
    if not report["candidates"]:
        lines.append("| — | 无符合条件候选 | — | — | — | — | — | 请查看否决项与数据缺失 |")

    for candidate in report["candidates"][:10]:
        lines.extend([
            "",
            f"### {candidate['symbol']} {candidate.get('name') or ''}",
            "",
            "- 子分：" + "；".join(
                f"{name}={format_value(score)}" for name, score in candidate["sub_scores"].items()
            ),
            "- 反证：" + ("；".join(candidate["counter_evidence"]) or "未发现明显反证"),
            "- 降级项：" + ("；".join(candidate["downgrades"]) or "无"),
            "- 失效条件：" + "；".join(candidate["invalidation"]),
        ])

    lines.extend([
        "",
        "## 否决名单（截取）",
        "",
        "| 股票 | 分数 | 否决原因 |",
        "|---|---:|---|",
    ])
    for candidate in report["rejected"]:
        rejection_reasons = candidate["vetoes"] or candidate["downgrades"]
        veto_text = "；".join(rejection_reasons).replace("|", "\\|")
        lines.append(
            f"| {candidate['symbol']} {candidate.get('name') or ''} | {format_value(candidate.get('score'))} | "
            f"{veto_text} |"
        )
    if not report["rejected"]:
        lines.append("| — | — | 无 |")

    lines.extend(["", "## 数据覆盖与限制", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    if not report["limitations"]:
        lines.append("- 未发现额外缺失项。")

    lines.extend([
        "",
        "## 数据溯源",
        "",
        "| 方法 | 状态 | 行数 | 最新日期 | 参数摘要 | 说明 |",
        "|---|---|---:|---|---|---|",
    ])
    for item in report["provenance"]:
        params = json.dumps(item.get("params", {}), ensure_ascii=False)
        error = (item.get("error") or "—").replace("|", "\\|")
        lines.append(
            f"| `{item['method']}` | {item['status']} | {item['rows']} | "
            f"{item.get('latest_date') or '—'} | `{params}` | {error} |"
        )

    lines.extend([
        "",
        "## 口径说明",
        "",
        "- 近涨停/近跌停使用统一 ±9.5% 阈值，不是交易所精确涨跌停统计。",
        "- 北向数据表示持仓变化，不是实时交易流量；成交额不是主力净流入。",
        "- 日线收盘信号只能从下一交易日执行；历史扫描不会读取分析日之后的数据。",
        "- N/A 项不填0，按可用权重归一化，同时展示覆盖率。",
        "",
        "> " + report["disclaimer"],
    ])
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    safe_report = json_safe(report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(safe_report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = probe_markdown(safe_report) if safe_report["mode"] == "probe" else scan_markdown(safe_report)
    md_path.write_text(markdown, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not 1 <= args.top_n <= 100:
        raise SystemExit("--top-n 必须在 1–100 之间")
    symbols = normalize_symbols(args.symbols)
    try:
        source = PandaDataSource()
    except RuntimeError as exc:
        raise SystemExit(f"配置错误：{exc}") from None
    as_of = resolve_as_of(source, args.as_of)
    if args.probe_only:
        report = build_probe_report(source, as_of)
    else:
        try:
            report = build_scan_report(
                source, as_of, symbols, args.universe, args.top_n, args.min_amount
            )
        except RuntimeError as exc:
            raise SystemExit(f"股票池错误：{exc}") from None
    write_outputs(report, Path(args.out_json), Path(args.out_md))

    if report["mode"] == "probe":
        print(
            f"PandaData 探测完成：{report['summary']['ok']}/{report['summary']['total']} 可用；"
            f"ETF净申赎={'可用' if report['summary']['etf_net_creation_available'] else 'N/A'}"
        )
    else:
        market = report["market"]
        print(
            f"扫描完成：{market['stage']}，环境分={market['environment_score']}，"
            f"覆盖率={market['coverage_pct']}%，候选={len(report['candidates'])}"
        )
    print(f"JSON: {args.out_json}")
    print(f"Markdown: {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
