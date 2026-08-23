"""策略九 2025 至今回测。

  python strategy/strategies/strategy4/run_2025.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import fee_rules_text  # noqa: E402
from strategy.strategies.strategy4.portfolio import run_strategy9_portfolio  # noqa: E402

OUT = Path(__file__).resolve().parent / "backtest_2025"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    out = run_strategy9_portfolio(verbose=True)
    table = out["table"]
    table.to_csv(OUT / "summary.csv", index=False)
    out["picks"].to_csv(OUT / "weekly_picks.csv", index=False)
    month = {}
    for vid, nav in out["navs"].items():
        m = nav.copy()
        m.index = pd.to_datetime(m.index)
        m = m[m.index >= pd.Timestamp("2025-01-01")]
        if m.empty:
            continue
        m = m / float(m.iloc[0])
        month[vid] = {
            str(k.date())[:7]: float(v)
            for k, v in m.resample("ME").last().dropna().items()
        }
    (OUT / "nav_monthly.json").write_text(
        json.dumps(
            {
                "s9_trades": out["s9_trades"],
                "s1_p2_trades": out["s1_p2_trades"],
                "nav": month,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lines = [
        "# 策略九 2025 至今",
        "",
        "研究回测，不构成投资建议。策略1 默认未改。",
        "",
        "- 规则：因子1 开盘突破 + 因子4 牛市放宽止损 + 20% 昨高次日开盘全清 + 因子10 周频20日动量 Top5",
        "- 宇宙：盯盘 26 只；T 收盘算动量，本周最后交易日排名，下一周开仓",
        f"- 成本：{fee_rules_text()}",
        "- 区间：2025-01-02～缓存末日；因子用 2020 起预热。因子4 参数曾扫过含 2025 的弱年，本年不是干净样本外",
        "- 组合：入选名单每日再平衡等权",
        "",
        table.to_markdown(index=False),
        "",
        f"策略九成交笔数（门控后合计）{out['s9_trades']:.0f}；策略1 两票 {out['s1_p2_trades']:.0f}。",
        "",
        "本报告仅供研究参考，不构成投资建议。",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
