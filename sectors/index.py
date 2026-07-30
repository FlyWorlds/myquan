"""板块轮动 CLI。

用法：
  python index.py
  python index.py --no-limitup
  python index.py --no-members --no-open
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_MYQUAN = ROOT.parent
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from sectors.report import write_rotation_report  # noqa: E402
from sectors.rotation import build_rotation_payload  # noqa: E402

ROTATION_FILE = ROOT / "sectors_rotation.html"


def cmd_rotation(args: argparse.Namespace) -> None:
    print("正在生成板块轮动数据（行业+概念）…")
    if not args.no_limitup:
        print("  涨停数统计会拉成分股，首次较慢，结果会写入 cache/")
    payload = build_rotation_payload(
        days=args.days,
        top_n=args.top_n,
        with_limitup=not args.no_limitup,
        with_members=not args.no_members,
    )
    for kind in ("行业", "概念"):
        k = payload["kinds"].get(kind) or {}
        dates = k.get("dates") or []
        print(f"  {kind}: {k.get('board_count', 0)} 板块 · 历史 {len(dates)} 日")
        by = (k.get("by_metric") or {}).get("涨幅") or {}
        top0 = (by.get("top") or [[]])[0] if by.get("top") else []
        if top0:
            parts = []
            for c in top0[:5]:
                v = c.get("value")
                if v is None:
                    parts.append(str(c.get("name") or ""))
                else:
                    parts.append(f"{c['name']}({float(v):+.2f}%)")
            print(f"    今日涨幅前五: {'、'.join(parts)}")
    path = write_rotation_report(payload, ROTATION_FILE)
    print(f"\n板块轮动 HTML: {path}")
    if not args.no_open:
        webbrowser.open(path.as_uri())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="板块轮动：行业/概念 × 涨幅/涨停/资金")
    p.add_argument("--days", type=int, default=5, help="近N个交易日（默认5）")
    p.add_argument("--top-n", type=int, default=10, help="前N/后N")
    p.add_argument("--no-limitup", action="store_true", help="跳过涨停数统计（更快）")
    p.add_argument("--no-members", action="store_true", help="不预拉个股成分")
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    cmd_rotation(args)


if __name__ == "__main__":
    main()
