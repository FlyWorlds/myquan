#!/usr/bin/env python3
"""
reg_risk_report.py — 合规风险雷达 CLI 入口

用法:
  python scripts/reg_risk_report.py --symbols 000021.SZ,600519.SH \
      --lookback 180 --lookahead 90 --min-severity low \
      --out report.json --md report.md

无凭证时自动回退内置样本（examples/sample_data/）。
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_source import DataSource            # noqa: E402
from scoring import score_name, SEVERITY_ORDER  # noqa: E402
import formatters                             # noqa: E402


def parse_symbols(raw: str) -> list[str]:
    if Path(raw).exists():
        text = Path(raw).read_text(encoding="utf-8")
        toks = [t.strip() for line in text.splitlines() for t in line.replace(",", " ").split()]
    else:
        toks = [t.strip() for t in raw.replace(",", " ").split()]
    return [t.upper() for t in toks if t and t[0].isdigit()]


def build_report(symbols, lookback, lookahead, min_severity, prefer=None) -> dict:
    ds = DataSource(prefer=prefer)
    today = datetime.now()
    start = (today - timedelta(days=lookback)).strftime("%Y%m%d")
    end = (today + timedelta(days=lookahead)).strftime("%Y%m%d")

    degraded = set()
    items = []
    for sym in symbols:
        sources = {
            "shareholder_change": ds.shareholder_change(sym, start, today.strftime("%Y%m%d")),
            "restricted": ds.restricted(sym, today.strftime("%Y%m%d"), end),
            "pledge": ds.pledge(sym, start, today.strftime("%Y%m%d")),
            "placard": ds.placard(sym, start, today.strftime("%Y%m%d")),
            "top_holders": ds.top_holders(sym, start, today.strftime("%Y%m%d")),
            "daily": ds.daily(sym, (today - timedelta(days=15)).strftime("%Y%m%d"),
                              today.strftime("%Y%m%d")),
        }
        for key, rows in sources.items():
            if not rows:
                degraded.add(key)
        # 名称：从任一含 name 的源提取
        name = ""
        for rows in sources.values():
            if rows and rows[0].get("name"):
                name = rows[0]["name"]
                break
        nr = score_name(sym, name, sources, today)
        items.append(nr)

    thr = SEVERITY_ORDER[min_severity]
    items = [i for i in items if SEVERITY_ORDER[i.severity] >= thr]
    items.sort(key=lambda i: i.score, reverse=True)

    return {
        "generated_at": today.strftime("%Y-%m-%d %H:%M"),
        "backend": ds.backend,
        "universe_size": len(symbols),
        "params": {"lookback_days": lookback, "lookahead_days": lookahead,
                   "min_severity": min_severity},
        "items": [i.to_dict() for i in items],
        "degraded_sources": sorted(degraded),
    }


def main():
    ap = argparse.ArgumentParser(description="A股合规/监管风险雷达")
    ap.add_argument("--symbols", required=True, help="逗号分隔代码，或 CSV 文件路径")
    ap.add_argument("--lookback", type=int, default=180)
    ap.add_argument("--lookahead", type=int, default=90)
    ap.add_argument("--min-severity", choices=["low", "medium", "high"], default="low")
    ap.add_argument("--prefer", choices=["sdk", "sample"], default=None)
    ap.add_argument("--out", default=None, help="JSON 输出路径")
    ap.add_argument("--md", default=None, help="Markdown 输出路径")
    args = ap.parse_args()

    symbols = parse_symbols(args.symbols)
    if not symbols:
        print("未解析到有效股票代码", file=sys.stderr)
        sys.exit(2)

    report = build_report(symbols, args.lookback, args.lookahead,
                          args.min_severity, prefer=args.prefer)

    print(formatters.to_text(report))
    if args.out:
        Path(args.out).write_text(formatters.to_json(report), encoding="utf-8")
        print(f"\n[已写出 JSON] {args.out}")
    if args.md:
        Path(args.md).write_text(formatters.to_markdown(report), encoding="utf-8")
        print(f"[已写出 Markdown] {args.md}")


if __name__ == "__main__":
    main()
