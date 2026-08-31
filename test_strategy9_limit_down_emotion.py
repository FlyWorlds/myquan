"""策略九·低开跌停情绪单元测试（不联网）。"""

from __future__ import annotations

import unittest

from strategy.strategies.strategy9.limit_down_emotion import is_gap_down_limit_down_open
from strategy.strategies.strategy9.sentiment_phase import (
    LD_OPEN_CALM_MAX,
    LD_OPEN_PANIC_MIN,
    classify_ld_open_phase,
)


class TestStrategy9LimitDownEmotion(unittest.TestCase):
    def test_gap_down_limit_down_open_main_board(self) -> None:
        prev = 10.0
        ld = 9.0  # 10% limit down
        self.assertTrue(
            is_gap_down_limit_down_open(prev, ld, limit_ratio=0.10),
        )
        self.assertFalse(
            is_gap_down_limit_down_open(prev, 9.5, limit_ratio=0.10),
        )

    def test_not_gap_down_when_open_above_prev(self) -> None:
        self.assertFalse(
            is_gap_down_limit_down_open(10.0, 10.0, limit_ratio=0.10),
        )

    def test_phase_classification(self) -> None:
        calm = classify_ld_open_phase(LD_OPEN_CALM_MAX)
        self.assertEqual(calm["ldPhase"], "calm")
        panic = classify_ld_open_phase(LD_OPEN_PANIC_MIN)
        self.assertEqual(panic["ldPhase"], "panic")
        normal = classify_ld_open_phase(LD_OPEN_CALM_MAX + 1)
        self.assertEqual(normal["ldPhase"], "normal")


if __name__ == "__main__":
    unittest.main()
