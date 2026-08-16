"""CLI entry point — python -m hk_dossier <SYMBOL>"""

import argparse
import logging
import os
import sys
from pathlib import Path

from hk_dossier.client import PandadataClient
from hk_dossier.core import generate_dossier


def main():
    parser = argparse.ArgumentParser(
        description="港股尽职调查研报生成工具 (HK Stock Dossier)"
    )
    parser.add_argument(
        "symbol",
        type=str,
        help="港股代码，如 0700.HK 或 0700（自动补齐 .HK 后缀）",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出 Markdown 文件路径",
    )
    parser.add_argument(
        "--charts",
        action="store_true",
        help="生成股价走势图和成交量图（需 matplotlib）",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="同时输出 PDF 版本（需安装 pandoc 或 weasyprint）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志输出",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    symbol = args.symbol.upper().strip()
    if not symbol.endswith(".HK"):
        symbol = symbol + ".HK"
        print(f"[INFO] 自动补齐后缀: {args.symbol} -> {symbol}")

    # Determine output paths
    output_dir = None
    md_path = args.output
    if args.charts:
        if md_path:
            output_dir = str(Path(md_path).parent)
        else:
            output_dir = "."

    try:
        client = PandadataClient()
        report = generate_dossier(
            symbol,
            client=client,
            output_dir=output_dir,
        )
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        print("\n请按以下方式配置 Pandadata 凭证：")
        print("  export DEFAULT_USERNAME='your_username'")
        print("  export DEFAULT_PASSWORD='your_password'")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 生成研报失败: {e}")
        logger = logging.getLogger(__name__)
        logger.debug("Detail", exc_info=True)
        sys.exit(1)

    # Output Markdown
    if md_path:
        os.makedirs(Path(md_path).parent, exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[OK] Markdown 研报已保存到: {md_path}")
    else:
        print(report)

    # Output PDF (optional)
    if args.pdf:
        _try_generate_pdf(report, symbol, md_path)


def _try_generate_pdf(report: str, symbol: str, md_path: str | None):
    """Attempt to convert Markdown to PDF using available tools."""
    pdf_path = (Path(md_path).stem + ".pdf") if md_path else f"{symbol.replace('.', '_')}_report.pdf"

    # Try weasyprint first
    try:
        import markdown
        html_body = markdown.markdown(
            report,
            extensions=["extra", "codehilite", "tables"],
        )
        html_full = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; padding: 2em; line-height: 1.6; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ccc; padding: 0.5em; text-align: left; }}
th {{ background: #f5f5f5; }}
code {{ background: #f0f0f0; padding: 0.2em 0.4em; border-radius: 3px; }}
img {{ max-width: 100%; }}
</style></head><body>{html_body}</body></html>"""
        from weasyprint import HTML
        HTML(string=html_full).write_pdf(pdf_path)
        print(f"[OK] PDF 研报已保存到: {pdf_path}")
        return
    except ImportError:
        pass
    except Exception as e:
        print(f"[WARN] PDF 生成失败 (weasyprint): {e}", file=sys.stderr)

    # Try pandoc as fallback
    try:
        import subprocess
        if md_path:
            subprocess.run(
                ["pandoc", md_path, "-o", pdf_path, "--pdf-engine=xelatex"],
                capture_output=True, text=True, check=False,
            )
            if Path(pdf_path).exists():
                print(f"[OK] PDF 研报已保存到: {pdf_path}")
                return
    except FileNotFoundError:
        pass

    print("[WARN] PDF 生成需要额外工具：pip install weasyprint markdown 或安装 pandoc")


if __name__ == "__main__":
    main()
