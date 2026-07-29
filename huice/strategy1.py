"""凯盛科技 (sh600552) 回测 — 开盘 ±2.5% 策略（含低开 945 规则）。

策略规则全文见 strategy.open_break.STRATEGY_RULES。

运行：
  cd myquan/huice && python strategy1.py
  python strategy1.py --no-open          # 不自动打开 HTML
  python strategy1.py --rules            # 只打印策略规则
  python strategy1.py --gap945-mode 5m   # 945 卖价用 5 分钟 K 收盘价
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
    STRATEGY_RULES,
    build_gap_down_945_proxy_map,
    fetch_daily,
    fetch_minute_1m,
    print_summary,
)

# --- 标的 ---
SYMBOL = "sh600552"
SYMBOL_NAME = "凯盛科技"
EM_SYMBOL = "600552"
THRESHOLD_PCT = 0.025  # 开盘 ±2.5%
START_DATE = "20200101"
END_DATE = dt.date.today().strftime("%Y%m%d")

# --- 低开 945 规则（已开启）---
ENABLE_GAP945 = True
# 无历史 1 分钟线时用开盘价 proxy 近似 945 卖价（东财接口仅能拉最近几天）
GAP945_USE_PROXY = True
GAP945_PROXY = "open"  # open | mid
# 945 卖出价："1m"=09:45 分钟收盘价；"5m"=09:40~09:45 五分钟收盘价
GAP945_EXIT_MODE = "1m"

# --- 资金与费用 ---
INITIAL_CASH = 100_000.0
TARGET_PCT = 0.95
LOT_SIZE = 100
COMMISSION_RATE = 0.0000854
STAMP_TAX_RATE = 0.001
SLIPPAGE = {"type": "percent", "value": 0.001}
FILL_CLOSE = CurrentClose()
REPORT_PATH = Path(__file__).with_name(f"{SYMBOL_NAME}_report.html")
MIN1_CACHE_PATH = Path(__file__).with_name(f"{SYMBOL}_1m_qfq.parquet")


def main(*, show_report: bool = True, gap945_mode: str = GAP945_EXIT_MODE) -> None:
    print(f"akquant={getattr(aq, '__version__', '?')}")
    print(f"拉取 {SYMBOL_NAME}({SYMBOL}) 日线 {START_DATE} → {END_DATE} ...")
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    print(
        f"日线数: {len(daily)}，"
        f"区间: {daily['date'].iloc[0]} → {daily['date'].iloc[-1]}"
    )

    gap_map: dict = {}
    if ENABLE_GAP945:
        print(f"拉取 1 分钟线（945 卖价 mode={gap945_mode}）…")
        minute = fetch_minute_1m(
            sina_symbol=SYMBOL,
            em_symbol=EM_SYMBOL,
            cache_path=MIN1_CACHE_PATH,
            start_date=START_DATE,
            end_date=END_DATE,
        )
        if GAP945_USE_PROXY:
            gap_map = build_gap_down_945_proxy_map(
                daily,
                minute,
                proxy=GAP945_PROXY,
                exit_mode=gap945_mode,
            )
        else:
            from strategy import build_gap_down_945_map

            gap_map = build_gap_down_945_map(daily, minute, exit_mode=gap945_mode)
        n_exact = sum(
            1 for v in gap_map.values() if str(v.get("source")) in ("1m", "5m")
        )
        n_proxy = len(gap_map) - n_exact
        print(
            f"  低开945可触发日: {len(gap_map)} "
            f"（精确分钟价={n_exact}，proxy={n_proxy}）"
        )
    else:
        print("  低开945规则: 关闭")

    OpenBreak3Strategy.symbol = SYMBOL
    OpenBreak3Strategy.symbol_name = SYMBOL_NAME
    OpenBreak3Strategy.target_pct = TARGET_PCT
    OpenBreak3Strategy.lot_size = LOT_SIZE
    OpenBreak3Strategy.start_date = START_DATE
    OpenBreak3Strategy.end_date = END_DATE
    OpenBreak3Strategy.slippage_value = SLIPPAGE["value"]
    OpenBreak3Strategy.gap_down_945_map = gap_map
    OpenBreak3Strategy.enable_gap945 = ENABLE_GAP945
    OpenBreak3Strategy.entry_pct = THRESHOLD_PCT
    OpenBreak3Strategy.stop_pct = THRESHOLD_PCT
    OpenBreak3Strategy.prev_small_yang_pct = THRESHOLD_PCT

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

    mode_label = "945未翻红全清" if ENABLE_GAP945 else "无945"
    print(f"\n生成 HTML: {REPORT_PATH}")
    result.viz.report(
        title=(
            f"{SYMBOL_NAME} 开盘±{THRESHOLD_PCT*100:.1f}%({mode_label}/阳持/阴出) "
            f"滑点0.1点 ({START_DATE}~{END_DATE})"
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
    parser.add_argument(
        "--rules",
        action="store_true",
        help="打印策略规则并退出",
    )
    parser.add_argument(
        "--gap945-mode",
        choices=("1m", "5m"),
        default=GAP945_EXIT_MODE,
        help="945 卖出价：1m=09:45分钟收盘；5m=09:40~09:45五分钟收盘",
    )
    args = parser.parse_args()
    if args.rules:
        print(STRATEGY_RULES.strip())
        raise SystemExit(0)
    main(show_report=not args.no_open, gap945_mode=args.gap945_mode)
