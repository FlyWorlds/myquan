"""中证500 ETF (sh510580) 回测 — 策略逻辑见 myquan/strategy。

运行：
  cd myquan/huice && python zz500.py
  python zz500.py --no-open   # 不自动打开 HTML 报告
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import akquant as aq
from akquant import CurrentClose

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from strategy import (
    OpenBreak3Strategy,
    build_gap_down_945_map,
    fetch_daily,
    fetch_minute_1m,
    print_summary,
)

SYMBOL = "sh510580"
SYMBOL_NAME = "中证500ETF"
EM_SYMBOL = "510580"
THRESHOLD_PCT = 0.01  # 开盘 ±1.0%
TICK_SIZE = 0.001
START_DATE = "20250101"
END_DATE = dt.date.today().strftime("%Y%m%d")

INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT_SIZE = 100
COMMISSION_RATE = 0.0000854
STAMP_TAX_RATE = 0.0  # ETF 无印花税
SLIPPAGE = {"type": "percent", "value": 0.001}
FILL_CLOSE = CurrentClose()
REPORT_PATH = Path(__file__).with_name(f"{SYMBOL_NAME}_report.html")
MIN1_CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_1m_qfq.parquet")


def main(*, show_report: bool = True) -> None:
    print(f"akquant={getattr(aq, '__version__', '?')}")
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 {START_DATE} → {END_DATE} ...")
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    print(
        f"日线数: {len(daily)}，"
        f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
    )

    print("拉取 1 分钟线（低开 9:45 前未翻红 → 9:45 出）…")
    minute = fetch_minute_1m(
        sina_symbol=SYMBOL,
        em_symbol=EM_SYMBOL,
        cache_path=MIN1_CACHE_PATH,
    )
    gap_map = build_gap_down_945_map(daily, minute)
    n_1m = sum(1 for v in gap_map.values() if v.get("source") == "1m")
    n_proxy = sum(1 for v in gap_map.values() if v.get("source") == "daily_proxy")
    print(f"  低开规则可触发日: {len(gap_map)}（1分钟={n_1m}，日线近似={n_proxy}）")

    OpenBreak3Strategy.symbol = SYMBOL
    OpenBreak3Strategy.symbol_name = SYMBOL_NAME
    OpenBreak3Strategy.target_pct = TARGET_PCT
    OpenBreak3Strategy.lot_size = LOT_SIZE
    OpenBreak3Strategy.start_date = START_DATE
    OpenBreak3Strategy.end_date = END_DATE
    OpenBreak3Strategy.slippage_value = SLIPPAGE["value"]
    OpenBreak3Strategy.gap_down_945_map = gap_map
    OpenBreak3Strategy.entry_pct = THRESHOLD_PCT
    OpenBreak3Strategy.stop_pct = THRESHOLD_PCT
    OpenBreak3Strategy.prev_small_yang_pct = THRESHOLD_PCT
    OpenBreak3Strategy.tick = TICK_SIZE
    OpenBreak3Strategy.t0 = False  # T+1：买入当日不可卖

    result = aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=LOT_SIZE,
        fill_policy=FILL_CLOSE,
        slippage=SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )

    print("\n=== Backtest Result ===")
    print(result)
    print_summary(
        result,
        daily,
        symbol_name=SYMBOL_NAME,
        symbol=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=STAMP_TAX_RATE,
        slippage_value=SLIPPAGE["value"],
        entry_pct=THRESHOLD_PCT,
        stop_pct=THRESHOLD_PCT,
        prev_small_yang_pct=THRESHOLD_PCT,
    )

    print(f"\n生成 HTML: {REPORT_PATH}")
    result.viz.report(
        title=(
            f"{SYMBOL_NAME} 开盘±{THRESHOLD_PCT*100:.1f}%(低开945未翻红/阳持/阴出) "
            f"滑点0.1点 T+1 ({START_DATE}~{END_DATE})"
        ),
        filename=str(REPORT_PATH),
        show=show_report,
        market_data=daily,
        plot_symbol=SYMBOL,
        curve_freq="D",
    )
    print(f"报告已生成: {REPORT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"{SYMBOL_NAME} 开盘±{THRESHOLD_PCT*100:.1f}% 策略回测"
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="生成 HTML 报告但不自动打开浏览器",
    )
    args = parser.parse_args()
    main(show_report=not args.no_open)
