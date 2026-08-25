"""半年评分选股 Top3 · 各 30% 仓 · 无前瞻 · 2020 起。

结果目录：backtest/factor13_semi_top3/
  python strategy/run_factor13_semi_top3.py   # 打印摘要；完整复跑见下方说明

参数：
  · Top3，每票目标仓位 30%（合计 90%，闲置 10%）
  · 半年信号 6/30、12/31；只用当时可见特征 → 回测下一半年
  · ±2.5%，等止损再换
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backtest" / "factor13_semi_top3"


def main() -> None:
    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    tg = (OUT / "targets_semi.csv").read_text(encoding="utf-8").splitlines()[:8]
    print("=== 半年 Top3 × 30%（已落盘）===")
    print(f"全段三槽: {meta['slot']['ret']:+.1f}%  回撤 {meta['slot']['mdd']:.1f}%")
    print(f"2026:     {meta['slot_2026']['ret']:+.1f}%")
    print(f"等权拼接: {meta['ew_stitch']['ret']:+.1f}%")
    print(f"报告: {OUT / 'report.html'}")
    print("目标表示例:\n" + "\n".join(tg))


if __name__ == "__main__":
    main()
