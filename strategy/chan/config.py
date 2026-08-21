"""策略二的固定研究与交易配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CHAN_CACHE_DIR = ROOT / "data_cache" / "strategy2_chan"
CHAN_OUTPUT_DIR = ROOT / "backtest" / "strategy2_chan_out"


@dataclass(frozen=True)
class ChanStrategyConfig:
    base_freq: str = "日线"
    confirm_freq: str = "30分钟"
    higher_freq: str = "日线"
    data_start: str = "20170101"
    discovery_start: str = "20180101"
    discovery_end: str = "20221231"
    validation_start: str = "20230101"
    validation_end: str = "20241231"
    test_start: str = "20250101"
    test_end: str = field(default_factory=lambda: dt.date.today().strftime("%Y%m%d"))
    purge_days: int = 20
    warmup_bars: int = 100
    confirm_warmup_bars: int = 300
    candidate_timeout_bars: int = 20
    top_k: int = 10
    initial_cash: float = 1_000_000.0
    fee_rate: float = 0.0015
    stress_fee_rates: tuple[float, ...] = (0.0015, 0.0030, 0.0050)
    min_cross_section: int = 30
    min_eligible: int = 10
    correlation_reject: float = 0.85
    correlation_prefer: float = 0.60
    random_seed: int = 42
    cache_dir: Path = CHAN_CACHE_DIR
    output_dir: Path = CHAN_OUTPUT_DIR

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["cache_dir"] = str(self.cache_dir)
        out["output_dir"] = str(self.output_dir)
        return out


DEFAULT_CONFIG = ChanStrategyConfig()


__all__ = [
    "CHAN_CACHE_DIR",
    "CHAN_OUTPUT_DIR",
    "ChanStrategyConfig",
    "DEFAULT_CONFIG",
]
