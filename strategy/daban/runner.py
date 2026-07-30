"""打板战法 — 回测入口。"""

from __future__ import annotations

from typing import Any

from strategy.base import run_backtest_pipeline
from strategy.daban.backtest import DaBanStrategy
from strategy.daban.config import DaBanConfig
from strategy.daban.summary import print_summary


def _configure(cls: type[DaBanStrategy], cfg: DaBanConfig) -> None:
    cls.symbol = cfg.symbol
    cls.symbol_name = cfg.symbol_name
    cls.target_pct = cfg.target_pct
    cls.limit_pct = cfg.limit_pct
    cls.gap_down_exit_pct = cfg.gap_down_exit_pct
    cls.seal_high_ticks = cfg.seal_high_ticks
    cls.start_date = cfg.start_date
    cls.end_date = cfg.end_date


def run_daban(
    cfg: DaBanConfig,
    *,
    show_report: bool = False,
    verbose: bool = True,
) -> tuple[Any, Any]:
    def _summary(result, daily, **_kw):
        print_summary(result, daily, cfg=cfg)

    return run_backtest_pipeline(
        params=cfg,
        strategy_cls=DaBanStrategy,
        configure=_configure,
        print_summary_fn=_summary,
        report_title=f"{cfg.symbol_name} {cfg.report_title_suffix()}",
        show_report=show_report,
        verbose=verbose,
    )
