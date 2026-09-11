"""单测不得改写生产 holdings.json。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MYQUAN_DISABLE_HOLDINGS_IO", "1")

_HS = Path(__file__).resolve().parent
_ROOT = _HS.parent
for p in (str(_ROOT), str(_HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from index import (  # noqa: E402
    HOLDINGS_FILE,
    _apply_trigger_date_fields,
    _running_unit_tests,
    _use_isolated_holdings_memory,
    remember_factor_trigger,
)


class TestHoldingsIoGuard(unittest.TestCase):
    def test_unittest_is_isolated(self):
        self.assertTrue(_running_unit_tests())
        self.assertTrue(_use_isolated_holdings_memory())

    def test_apply_trigger_does_not_touch_production_file(self):
        path = HOLDINGS_FILE
        before = path.read_bytes() if path.exists() else None
        mtime = path.stat().st_mtime if path.exists() else None
        row = {
            "持仓状态": "已平仓",
            "预警": "止损",
            "已触买": "否",
            "买点": 10.5,
            "止损": 9.8,
            "成交价": 9.8,
        }
        sig = {
            "hit_buy": False,
            "hit_stop": True,
            "因子触发": "已触发",
            "持仓状态": "已平仓",
        }
        _apply_trigger_date_fields(
            row,
            sig=sig,
            session="2026-09-07",
            last_px=10.2,
            px_digits=2,
            buy_time="2026-09-05",
            qty=0,
            replay={"holding": False},
            code="600330",
            allow_entry=True,
        )
        remember_factor_trigger("000070", side="sell", px=1.23, session="2026-09-11")
        if before is None:
            self.assertFalse(path.exists())
            return
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime, mtime)
        data = json.loads(before.decode("utf-8"))
        mem = (data.get("factor_memory") or {}).get("000070") or {}
        self.assertNotEqual(mem.get("last_sell_factor_px"), 1.23)


if __name__ == "__main__":
    unittest.main()
