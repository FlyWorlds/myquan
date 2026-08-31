"""因子17 CLI：大盘低开统计报告。

  python -m strategy.run_factor17_market_low_open
  python -m strategy.run_factor17_market_low_open --start 20200101 --no-breadth
  python -m strategy.run_factor17_market_low_open --breadth-refresh --breadth-max 200
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategy.factor17_market_low_open import (
    OUT_DIR,
    build_markdown_report,
    factor17_signal,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="因子17·大盘低开统计")
    parser.add_argument("--start", default="20150101", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD，默认今日")
    parser.add_argument("--index", default="sh000001", help="指数代码")
    parser.add_argument("--no-breadth", action="store_true", help="跳过成分实体阳统计（更快）")
    parser.add_argument("--breadth-refresh", action="store_true", help="强制重建广度缓存")
    parser.add_argument(
        "--breadth-max",
        type=int,
        default=None,
        help="广度计算最多股票数（调试用；默认全中证1000）",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = factor17_signal(
        start=args.start,
        end=args.end,
        index_symbol=args.index,
        with_breadth=not args.no_breadth,
        breadth_max_stocks=args.breadth_max,
        breadth_force=args.breadth_refresh,
    )

    report_md = build_markdown_report(result)
    report_path = OUT_DIR / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    stats = result.get("bucket_stats")
    if stats is not None:
        stats_path = OUT_DIR / "bucket_stats.csv"
        stats.to_csv(stats_path, index=False, encoding="utf-8-sig")

    meta = {k: v for k, v in result.items() if k != "bucket_stats"}
    if stats is not None:
        meta["bucket_stats"] = stats.to_dict(orient="records")
    (OUT_DIR / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(report_md)
    print(f"\n已写入:\n  {report_path}\n  {OUT_DIR / 'bucket_stats.csv'}\n  {OUT_DIR / 'run_meta.json'}")


if __name__ == "__main__":
    main()
