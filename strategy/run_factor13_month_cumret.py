"""月度轮动：开盘突破±2.5%，用 2020→信号日累计收益选 Top3，各30%仓。

结果：backtest/factor13_month_cumret/report.html
规则：每月末打分 → 下月交易；月初强制换出不在名单的票。
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backtest" / "factor13_month_cumret"


def main() -> None:
    m = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    print("月度轮动 · 2020累计收益选股")
    print(f"全段={m['slot']['ret']:+.1f}%  2026={m['slot_2026']['ret']:+.1f}%  回撤={m['slot']['mdd']:.1f}%")
    print("报告:", OUT / "report.html")


if __name__ == "__main__":
    main()
