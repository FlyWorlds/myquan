"""策略二的 CZSC 缠论研究内核。"""

from strategy.chan.config import ChanStrategyConfig, DEFAULT_CONFIG
from strategy.chan.data_adapter import (
    load_symbol_frame,
    standardize_czsc_frame,
    to_raw_bars,
)
from strategy.chan.features import FACTOR_CANDIDATES, build_feature_frame
from strategy.chan.signals import (
    SIGNALS_CONFIG,
    ChanSignalSnapshot,
    apply_xiaozhuan,
    collapse_signals_to_daily,
    generate_signal_frame,
)
from strategy.chan.state_machine import ChanState, ChanStateMachine, ChanTransition

__all__ = [
    "FACTOR_CANDIDATES",
    "SIGNALS_CONFIG",
    "ChanSignalSnapshot",
    "ChanState",
    "ChanStateMachine",
    "ChanStrategyConfig",
    "ChanTransition",
    "DEFAULT_CONFIG",
    "apply_xiaozhuan",
    "build_feature_frame",
    "collapse_signals_to_daily",
    "generate_signal_frame",
    "load_symbol_frame",
    "standardize_czsc_frame",
    "to_raw_bars",
]
