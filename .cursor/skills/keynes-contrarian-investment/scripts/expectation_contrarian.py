#!/usr/bin/env python3
"""Keynes long-term expectation and contrarian A-share research Skill."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from contrarian_scoring import score_case
from fundamentals import build_fundamental_snapshot
from market_context import build_market_context
from pandadata_source import INDEX_UNIVERSES, PandaDataSource, fetch_index_universe, fetch_windows, normalize_symbol, probe_interfaces, quarter_for_date, resolve_as_of
from valuation import calculate_a_share_valuation
from render_report import write_outputs
from valuation import calculate_valuation_metrics

DEFAULT_JSON = "/tmp/keynes_contrarian.json"
DEFAULT_MD = "/tmp/keynes_contrarian.md"


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="凯恩斯长期预期与反共识投资研究")
    parser.add_argument("--symbol")
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--universe", choices=tuple(INDEX_UNIVERSES), default=None)
    parser.add_argument("--as-of")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--horizon-years", type=int, default=5)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--out-json", default=DEFAULT_JSON)
    parser.add_argument("--out-md", default=DEFAULT_MD)
    return parser.parse_args()


def normalize_symbols(values: list[str]) -> list[str]:
    result, seen = [], set()
    for value in values:
        symbol = normalize_symbol(value)
        if symbol not in seen:
            result.append(symbol)
            seen.add(symbol)
    return result


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def _data(result: Any) -> pd.DataFrame:
    return result.data if result is not None and result.ok else _empty()


def _name(detail: pd.DataFrame, symbol: str) -> str | None:
    if detail.empty or "symbol" not in detail.columns:
        return None
    frame = detail[detail["symbol"].astype(str) == symbol]
    if frame.empty:
        return None
    for column in ("name", "stock_name", "sec_name", "symbol_cn"):
        if column in frame.columns:
            return str(frame.iloc[-1][column])
    return None


def _fundamental_score(fundamentals: dict[str, Any]) -> float | None:
    metrics = fundamentals.get("reported_reality", {}).get("metrics", {})
    available = []
    revenue = metrics.get("revenue_yoy", {}).get("value")
    profit = metrics.get("net_profit_yoy", {}).get("value")
    cash = metrics.get("cash_conversion", {}).get("value")
    if revenue is not None:
        available.append(max(0.0, min(100.0, 50.0 + revenue * 100)))
    if profit is not None:
        available.append(max(0.0, min(100.0, 50.0 + profit * 100)))
    if cash is not None:
        available.append(max(0.0, min(100.0, cash * 50)))
    return float(np.mean(available)) if available else None


def _valuation_score(valuation: dict[str, Any]) -> float | None:
    percentiles = [v for v in (valuation.get("pe_percentile"), valuation.get("pb_percentile")) if v is not None]
    # A static price/annual-EPS proxy lacks a historical or peer anchor, so it is
    # shown for context but deliberately does not generate a safety score.
    return float(max(0.0, min(100.0, 100.0 - np.mean(percentiles)))) if percentiles else None


def _expectation_score(valuation: dict[str, Any], fundamentals: dict[str, Any]) -> float | None:
    percentile = valuation.get("pe_percentile")
    profit = fundamentals.get("reported_reality", {}).get("metrics", {}).get("net_profit_yoy", {}).get("value")
    if percentile is None and profit is None:
        return None
    if percentile is not None and profit is not None:
        # A low valuation with stable/improving earnings scores as a possible gap;
        # low valuation with worsening earnings is handled by the veto layer.
        return max(0.0, min(100.0, (100.0 - percentile) * 0.6 + (50.0 + profit * 100) * 0.4))
    return max(0.0, min(100.0, 100.0 - percentile)) if percentile is not None else max(0.0, min(100.0, 50.0 + profit * 100))


def _fetch_subject_bundle(source: PandaDataSource, symbol: str, as_of: str) -> dict[str, pd.DataFrame]:
    start_3y = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=365 * 3 + 30)).strftime("%Y%m%d")
    common = {"symbol": [symbol], "fields": []}
    # Financial statement APIs use quarter bounds. Performance/forecast expose
    # latest disclosures and are filtered by info_date in the analysis layer.
    return {
        "detail": _data(source.call("get_stock_detail", **common)),
        "performance": _data(source.call("get_fina_performance", **common)),
        "reports": _data(source.call("get_fina_reports", **common, start_quarter=quarter_for_date(start_3y), end_quarter=quarter_for_date(as_of))),
        "forecast": _data(source.call("get_fina_forecast", **common)),
        "audit": _data(source.call("get_audit_opinion", **common)),
        # A-share valuation comes from get_factor; do not call the SDK's
        # HK-only mktfin reader for .SH/.SZ symbols.
        "indicator": pd.DataFrame(),
        "factor": _data(source.call("get_factor", symbol=[symbol], start_date=start_3y, end_date=as_of, type="stock", factors=["net_profit", "operating_revenue", "pb_ratio_lf", "pb_ratio_ttm", "pb_ratio_lyr", "pe_ratio_ttm", "pe_ratio_lyr", "market_cap"])),
        "shares": _data(source.call("get_share_float", **common, start_date=start_3y, end_date=as_of)),
        "daily": _data(source.call("get_stock_daily", **common, start_date=start_3y, end_date=as_of)),
        "benchmark": _data(source.call("get_index_indicator", symbol=["000300.SH"], start_date=start_3y, end_date=as_of, fields=[])),
    }


def build_subject(source: PandaDataSource, symbol: str, as_of: str, market: dict[str, Any], horizon_years: int) -> dict[str, Any]:
    bundle = _fetch_subject_bundle(source, symbol, as_of)
    fundamentals = build_fundamental_snapshot(symbol, bundle["performance"], bundle["reports"], bundle["forecast"], bundle["audit"], as_of)
    annual_eps = fundamentals.get("reported_reality", {}).get("metrics", {}).get("annual_eps", {}).get("value")
    valuation = calculate_valuation_metrics(bundle["indicator"], bundle["daily"], as_of, annual_eps=annual_eps, reports=bundle["reports"], shares=bundle["shares"], benchmark=bundle["benchmark"], factor=bundle["factor"])
    fundamental_score = _fundamental_score(fundamentals)
    valuation_score = _valuation_score(valuation)
    expectation_score = _expectation_score(valuation, fundamentals)
    market_score = None if market.get("status") == "empty" else 50.0
    catalysts = ["下一次财务披露将检验当前盈利预期"] if not bundle["forecast"].empty else []
    catalyst_score = 40.0 if catalysts else None
    scoring = score_case(expectation_score, fundamental_score, valuation_score, market_score, catalyst_score, fundamentals, valuation)
    counter = list(fundamentals.get("deterioration_flags", []))
    return {"symbol": symbol, "name": _name(bundle["detail"], symbol), "expectation": {"market_consensus_proxy": {"value": valuation.get("pe_percentile"), "status": "proxy", "label": "历史估值分位代理，不是分析师一致预期"}, "price_implied_expectation": {"status": "N/A", "value": None, "caveat": "需要可比的每股盈利基数和目标倍数假设"}, "horizon_years": horizon_years}, "fundamentals": fundamentals, "valuation": valuation, "market_context": market, "score": scoring, "vetoes": scoring["vetoes"], "downgrades": scoring["downgrades"], "evidence": ["已披露基本面与估值字段将决定反共识判断"], "counter_evidence": counter, "catalysts": catalysts, "invalidation": ["后续盈利和经营现金流继续恶化将证伪基本面修复假设"], "limitations": ["市场共识为历史估值/公司预告代理，非正式一致预期"], "provenance": source.provenance()}


def build_probe(source: PandaDataSource, as_of: str, symbols: list[str]) -> dict[str, Any]:
    statuses = {name: result.provenance() for name, result in probe_interfaces(source, as_of, symbols).items()}
    return {"mode": "probe", "generated_at": datetime.now().isoformat(timespec="seconds"), "as_of": as_of, "strict_source": "PandaData only", "summary": {"available": sum(item["status"] == "ok" for item in statuses.values()), "total": len(statuses)}, "interfaces": statuses, "limitations": ["接口可用不等于字段足够；完整扫描以实际返回字段为准"]}


def build_report(source: PandaDataSource, symbols: list[str], as_of: str, universe: str | None, top_n: int, horizon_years: int) -> dict[str, Any]:
    universe_info: dict[str, Any] = {"type": "specified", "name": "手工指定股票池", "constituent_date": None, "count": len(symbols)}
    if universe and not symbols:
        result = fetch_index_universe(source, as_of, universe)
        if not result.ok:
            raise RuntimeError(f"无法获取指数成分：{result.status} - {result.error}")
        symbols = normalize_symbols(result.data["stock_symbol"].dropna().astype(str).tolist())
        universe_info = {"type": "index_constituents", "key": universe, "name": INDEX_UNIVERSES[universe]["label"], "index_symbol": INDEX_UNIVERSES[universe]["index_symbol"], "constituent_date": result.latest_date, "count": len(symbols)}
    market_start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
    market_daily_result = source.call("get_stock_daily", symbol=[], start_date=market_start, end_date=as_of, fields=[])
    index_daily_result = source.call("get_index_daily", symbol=["000300.SH", "000905.SH", "000852.SH"], start_date=market_start, end_date=as_of, fields=[])
    margin_result = source.call("get_margin", symbol=[], start_date=market_start, end_date=as_of, fields=[])
    etf_result = source.call("get_fund_etf_cr_net", symbol=["510050.SH", "510300.SH", "510500.SH", "512100.SH", "159915.SZ"], start_date=market_start, end_date=as_of, fields=[], unsupported_hint=True)
    market = build_market_context(_data(market_daily_result), _data(index_daily_result), _data(margin_result), None, None, _data(etf_result), as_of)
    subjects = [build_subject(source, symbol, as_of, market, horizon_years) for symbol in symbols[: max(1, top_n)]]
    return {"mode": "scan", "generated_at": datetime.now().isoformat(timespec="seconds"), "as_of": as_of, "strict_source": "PandaData only", "universe": universe_info, "summary": [f"研究标的 {len(subjects)} 只；市场共识字段均按代理口径解释", "反共识判断优先检验基本面耐久性和安全边际，不因价格下跌自动加分"], "subjects": subjects, "limitations": ["当前首版将市场共识表示为估值和公司披露的代理，不能替代正式分析师一致预期", "市场资金接口可能存在滞后、覆盖范围和权限限制"], "provenance": source.provenance(), "methodology": {"weights": {"expectation_gap": 25, "fundamental_durability": 30, "valuation_safety": 20, "market_positioning": 15, "catalyst_falsification": 10}, "na_rule": "缺失值不填0，按可用权重归一化；核心维度缺失不得PASS"}, "disclaimer": "本报告基于 PandaData 公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。"}


def main() -> int:
    cli = args()
    values = ([cli.symbol] if cli.symbol else []) + cli.symbols
    symbols = normalize_symbols(values)
    source = PandaDataSource()
    as_of = resolve_as_of(source, cli.as_of)
    report = build_probe(source, as_of, symbols) if cli.probe_only else build_report(source, symbols, as_of, cli.universe, cli.top_n, cli.horizon_years)
    write_outputs(report, Path(cli.out_json), Path(cli.out_md))
    print(f"完成：{cli.out_json}\nMarkdown：{cli.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
