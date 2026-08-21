#!/usr/bin/env python
"""策略二·缠论：数据、选股、因子挖掘和冻结验证 CLI。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy.chan.config import DEFAULT_CONFIG  # noqa: E402
from strategy.chan.data_adapter import synthetic_frame  # noqa: E402
from strategy.chan.mining import mine_factors  # noqa: E402
from strategy.chan.reporting import write_research_report  # noqa: E402
from strategy.chan.validation import validate_frozen_factor  # noqa: E402
from strategy.strategies.strategy2.portfolio import (  # noqa: E402
    build_feature_panel,
    build_symbol_features,
    build_xiaozhuan_daily_features,
)


def _mine_validate(
    panel: pd.DataFrame,
    *,
    config=DEFAULT_CONFIG,
    data_label: str,
    point_in_time_universe: bool,
) -> None:
    output = Path(config.output_dir)
    print("开始因子挖掘（发现集/验证集，不碰最终测试集）", flush=True)
    mined = mine_factors(panel, config=config)
    print(f"挖掘完成 accepted={mined.accepted or '无'} trials={len(mined.journal)}", flush=True)
    mined.save(output)
    print("冻结后运行最终测试集一次", flush=True)
    frozen = validate_frozen_factor(
        mined.panel,
        mined.combined_column,
        journal=mined.journal,
        config=config,
    )
    frozen.save(output)
    report = write_research_report(
        output,
        journal=mined.journal,
        accepted=mined.accepted,
        diagnostics=frozen.diagnostics,
        data_label=data_label,
        point_in_time_universe=point_in_time_universe,
    )
    print(f"接受因子: {mined.accepted or '无'}")
    print(f"最终测试: {frozen.diagnostics['test_stats']}")
    print(f"研究等级: {frozen.diagnostics['decision']}")
    print(f"报告: {report}")


def command_demo(args: argparse.Namespace) -> None:
    count = max(2, int(args.symbols))
    config = replace(
        DEFAULT_CONFIG,
        min_cross_section=min(DEFAULT_CONFIG.min_cross_section, count),
        output_dir=Path(args.output) if args.output else DEFAULT_CONFIG.output_dir / "demo",
    )
    frames = []
    for i in range(count):
        symbol = f"SYN{i:04d}"
        raw = synthetic_frame(
            symbol,
            start="20170101",
            end=config.test_end,
            seed=config.random_seed + i,
        )
        frames.append(
            build_xiaozhuan_daily_features(
                raw,
                config=config,
                include_structure=True,
            )
        )
        if (i + 1) % 5 == 0:
            print(f"合成面板 {i + 1}/{count}", flush=True)
    panel = pd.concat(frames, ignore_index=True)
    panel_path = Path(config.output_dir) / "demo_feature_panel.parquet"
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(panel_path, index=False)
    print(f"面板完成 rows={len(panel)} symbols={panel['symbol'].nunique()} path={panel_path}", flush=True)
    _mine_validate(
        panel,
        config=config,
        data_label=f"CZSC可复现合成数据（{count}标的，仅用于流水线验证）",
        point_in_time_universe=False,
    )


def command_symbol(args: argparse.Namespace) -> None:
    feature, quality = build_symbol_features(args.symbol, refresh=args.refresh)
    target = Path(args.output) if args.output else (
        DEFAULT_CONFIG.output_dir / f"{args.symbol}_features.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    feature.to_parquet(target, index=False)
    print(quality)
    print(f"特征: {target} rows={len(feature)}")


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [x.strip() for x in args.symbols.split(",") if x.strip()]
    from backtest.zz1000_momentum_select import load_zz500_1000_mainboard

    universe = load_zz500_1000_mainboard()
    symbols = universe["symbol"].astype(str).tolist()
    if args.limit and int(args.limit) > 0:
        symbols = symbols[: int(args.limit)]
    return symbols


def command_prepare(args: argparse.Namespace) -> None:
    symbols = _resolve_symbols(args)
    print(f"准备缠论特征面板 symbols={len(symbols)}", flush=True)
    panel_path = Path(args.output) if args.output else None
    panel = build_feature_panel(
        symbols,
        refresh=args.refresh,
        panel_path=panel_path,
    )
    print(f"特征面板完成: symbols={panel['symbol'].nunique()} rows={len(panel)}")


def command_mine(args: argparse.Namespace) -> None:
    path = Path(args.panel) if args.panel else DEFAULT_CONFIG.cache_dir / "feature_panel.parquet"
    panel = pd.read_parquet(path)
    config = DEFAULT_CONFIG
    if getattr(args, "result_dir", None):
        config = replace(DEFAULT_CONFIG, output_dir=Path(args.result_dir))
    _mine_validate(
        panel,
        config=config,
        data_label=f"真实日线+30分钟小转大：{path}",
        point_in_time_universe=bool(args.point_in_time),
    )


def command_all(args: argparse.Namespace) -> None:
    command_prepare(args)
    panel_path = Path(args.output) if args.output else DEFAULT_CONFIG.cache_dir / "feature_panel.parquet"
    args.panel = str(panel_path)
    command_mine(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="策略二·CZSC缠论研究")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="可复现合成数据端到端验证")
    demo.add_argument("--symbols", type=int, default=32)
    demo.add_argument("--output")
    demo.set_defaults(func=command_demo)

    symbol = sub.add_parser("symbol", help="构建单票真实信号与特征")
    symbol.add_argument("symbol")
    symbol.add_argument("--refresh", action="store_true")
    symbol.add_argument("--output")
    symbol.set_defaults(func=command_symbol)

    for name, func in (("prepare", command_prepare), ("all", command_all)):
        item = sub.add_parser(name, help="构建全池面板" if name == "prepare" else "准备并完整研究")
        item.add_argument("--symbols", help="逗号分隔代码；留空取中证500+1000")
        item.add_argument("--limit", type=int, default=0)
        item.add_argument("--refresh", action="store_true")
        item.add_argument("--output")
        item.add_argument("--result-dir")
        item.add_argument("--point-in-time", action="store_true")
        item.set_defaults(func=func, panel=None)

    mine = sub.add_parser("mine", help="对已有特征面板挖因子并冻结验证")
    mine.add_argument("--panel")
    mine.add_argument("--result-dir")
    mine.add_argument("--point-in-time", action="store_true")
    mine.set_defaults(func=command_mine)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
