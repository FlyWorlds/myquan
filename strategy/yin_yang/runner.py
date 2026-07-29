"""日线阴阳策略 — 回测入口。"""

from __future__ import annotations

from typing import Any

from strategy.base import run_backtest_pipeline
from strategy.yin_yang.backtest import YinYangStrategy
from strategy.yin_yang.config import YinYangConfig
from strategy.yin_yang.summary import print_summary


def _configure(cls: type[YinYangStrategy], cfg: YinYangConfig) -> None:
    cls.symbol = cfg.symbol
    cls.symbol_name = cfg.symbol_name
    cls.target_pct = cfg.target_pct
    cls.start_date = cfg.start_date
    cls.end_date = cfg.end_date


def run_yin_yang(
    cfg: YinYangConfig,
    *,
    show_report: bool = False,
    verbose: bool = True,
) -> tuple[Any, Any]:
    def _summary(result, daily, **_kw):
        print_summary(result, daily, cfg=cfg)

    return run_backtest_pipeline(
        params=cfg,
        strategy_cls=YinYangStrategy,
        configure=_configure,
        print_summary_fn=_summary,
        report_title=f"{cfg.symbol_name} {cfg.report_title_suffix()}",
        show_report=show_report,
        verbose=verbose,
    )
