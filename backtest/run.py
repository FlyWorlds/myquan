"""backtest 共用 CLI：统一回测入口，减少各标的脚本复制。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from strategy import (  # noqa: E402
    HANGTIANDIANZI,
    KAICHENG,
    TIANTONG,
    XIEXINNENGKE,
    ZZ500_ETF,
    BacktestConfig,
    get_strategy,
    run_strategy1,
)
from strategy.backtest import monthly_returns_df  # noqa: E402

_CACHE = _MYQUAN / "data_cache"

PRESETS: dict[str, BacktestConfig] = {
    "kaicheng": KAICHENG,
    "hangtiandianzi": HANGTIANDIANZI,
    "xiexinnengke": XIEXINNENGKE,
    "zz500": ZZ500_ETF,
    "huayouguye": BacktestConfig(
        symbol="sh603799",
        symbol_name="华友钴业",
        em_symbol="603799",
        threshold_pct=0.02,
        start_date="20200101",
        daily_cache=_CACHE / "sh603799_daily_qfq.parquet",
    ),
    "zhaoyi": BacktestConfig(
        symbol="sh603986",
        symbol_name="兆易创新",
        em_symbol="603986",
        threshold_pct=0.025,
        start_date="20200101",
    ),
    "saiteng": BacktestConfig(
        symbol="sh603283",
        symbol_name="赛腾股份",
        em_symbol="603283",
        threshold_pct=0.025,
        start_date="20200101",
    ),
    "shenkeji": BacktestConfig(
        symbol="sz000021",
        symbol_name="深科技",
        em_symbol="000021",
        threshold_pct=0.025,
        start_date="20200101",
    ),
    "tiantong": TIANTONG,
}


def _with_report(cfg: BacktestConfig, report_dir: Path | None = None) -> BacktestConfig:
    out = report_dir or Path(__file__).resolve().parent
    return replace(
        cfg,
        report_path=out / f"{cfg.symbol_name}_report.html",
    )


def run_backtest_cli(
    cfg: BacktestConfig,
    *,
    show_report: bool = True,
    save_monthly: bool = False,
    monthly_csv: Path | None = None,
    argv: list[str] | None = None,
) -> tuple[Any, Any] | None:
    """解析通用参数并跑策略一（因子1+因子2）。返回 (result, daily)；仅 --rules 时返回 None。"""
    parser = argparse.ArgumentParser(
        description=(
            f"{cfg.symbol_name} 策略一回测 "
            f"（因子1开盘±{cfg.threshold_pct * 100:.1f}% + 因子2回撤补仓）"
        )
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML")
    parser.add_argument("--rules", action="store_true", help="打印策略一完整规则（含因子绑定）")
    parser.add_argument(
        "--no-factor2",
        action="store_true",
        help="不叠加因子2，仅跑因子1交易",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="忽略日线缓存，全量重拉",
    )
    args = parser.parse_args(argv)
    if args.rules:
        print(get_strategy("strategy1").print_rules())
        return None

    cfg = _with_report(cfg) if cfg.report_path is None else cfg
    result, daily = run_strategy1(
        cfg,
        show_report=show_report and not args.no_open,
        force_daily_refresh=bool(args.force_refresh),
        apply_factor2_overlay=not bool(args.no_factor2),
    )
    if save_monthly:
        path = monthly_csv or Path(__file__).with_name(
            f"{cfg.symbol_name}_monthly.csv"
        )
        df = monthly_returns_df(result, daily, initial_cash=cfg.initial_cash)
        if not df.empty:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            print(f"\n分月 CSV: {path}")
    return result, daily


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="OpenBreak3 统一回测入口")
    parser.add_argument(
        "preset",
        nargs="?",
        choices=sorted(PRESETS),
        help="标的预设名",
    )
    parser.add_argument("--list", action="store_true", help="列出可用预设")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--rules", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument(
        "--monthly",
        action="store_true",
        help="导出分月 CSV 到 backtest/",
    )
    args = parser.parse_args(argv)

    if args.list or not args.preset:
        print("可用预设:")
        for key, cfg in sorted(PRESETS.items()):
            print(f"  {key:16s} {cfg.symbol_name} ({cfg.symbol})")
        if not args.preset:
            raise SystemExit(0 if args.list else 2)

    cfg = _with_report(PRESETS[args.preset])
    forward = []
    if args.no_open:
        forward.append("--no-open")
    if args.rules:
        forward.append("--rules")
    if args.force_refresh:
        forward.append("--force-refresh")
    run_backtest_cli(
        cfg,
        show_report=not args.no_open,
        save_monthly=bool(args.monthly),
        monthly_csv=Path(__file__).with_name(f"{cfg.symbol_name}_monthly.csv"),
        argv=forward,
    )


if __name__ == "__main__":
    main()
