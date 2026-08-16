"""CLI entry point — python -m oil_brief [OPTIONS]"""

import argparse
import logging
import os
import sys
from pathlib import Path

from oil_brief.client import PandadataClient
from oil_brief.core import generate_report


def main():
    parser = argparse.ArgumentParser(
        description="原油简报生成工具 (Crude Oil Briefing)"
    )
    parser.add_argument(
        "--variety", "-v",
        type=str,
        default="BRENT",
        help="分析品种：BRENT（默认）、WTI、SC、NG（天然气）、RB（汽油）、HO（取暖油）",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=120,
        help="历史数据回溯天数，默认 120 天",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出 Markdown 文件路径",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志输出",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        client = PandadataClient()
        report = generate_report(
            variety=args.variety,
            days=args.days,
            output_path=args.output,
            client=client,
            verbose=args.verbose,
        )
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        print("\n请按以下方式配置 Pandadata 凭证：")
        print("  export DEFAULT_USERNAME='your_username'")
        print("  export DEFAULT_PASSWORD='your_password'")
        print("  或在项目根目录创建 .env 文件：")
        print("  DEFAULT_USERNAME=your_username")
        print("  DEFAULT_PASSWORD=your_password")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 生成简报失败: {e}")
        logger = logging.getLogger(__name__)
        logger.debug("Detail", exc_info=True)
        sys.exit(1)

    # Output
    if args.output:
        os.makedirs(Path(args.output).parent, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[OK] 原油简报已保存到: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
