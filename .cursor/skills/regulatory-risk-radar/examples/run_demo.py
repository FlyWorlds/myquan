#!/usr/bin/env python3
"""run_demo.py — 无需凭证的离线演示。

强制使用内置样本数据，扫描一个含多种风险的股票池，展示分级效果。
真实使用见 README（配置 panda_data SDK 后去掉 prefer="sample"）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from reg_risk_report import build_report  # noqa: E402
import formatters                          # noqa: E402

DEMO_UNIVERSE = ["000021.SZ", "600519.SH", "300750.SZ", "000662.SZ"]


def main():
    report = build_report(
        DEMO_UNIVERSE,
        lookback=180,
        lookahead=90,
        min_severity="low",
        prefer="sample",
    )
    print(formatters.to_text(report))
    print("\n" + "-" * 56)
    print("Markdown 版：\n")
    print(formatters.to_markdown(report))


if __name__ == "__main__":
    main()
