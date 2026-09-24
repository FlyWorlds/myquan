# -*- coding: utf-8 -*-
"""盯盘 / 因子26 / 时间完整性默认回归套件。

改 trailing、HWM、成交时刻、paper exit 相关代码后必须跑通本脚本。
不包含会动真实 holdings 的集成测试。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 默认 CI / 本地回归：时间完整性为必跑项
REGRESSION_MODULES = (
    "test_temporal_integrity",
    "test_high_watermark_sell_side",
)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in REGRESSION_MODULES:
        suite.addTests(loader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
