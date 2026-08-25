"""累计收益选股 + 按累计收益加权（半年无前瞻 Top3）。

结果：backtest/factor13_cumret_wt/
  · cum：2019→信号日策略累计收益打分，权重∝max(收益,0)，合计90%
  · half：前一半年累计收益同上

复跑：见该目录 report.html / summary.csv（完整逻辑已在最近一次会话中执行）。
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backtest" / "factor13_cumret_wt"


def main() -> None:
    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    print("=== 累计收益 + 加权 ===")
    for r in meta["summary"]:
        print(
            f"{r['label']}: 全段={r['ret']:+.1f}% 2026={r['ret_2026']:+.1f}% "
            f"回撤={r['mdd']:.1f}% 加权拼={r['wt_stitch']:+.1f}%"
        )
    print("报告:", OUT / "report.html")


if __name__ == "__main__":
    main()
