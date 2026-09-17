"""研究宇宙 research_watchlist 与盯盘 WATCHLIST 代码/阈值对齐。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestWatchUniverseParity(unittest.TestCase):
    def test_codes_and_entry_pct_match(self) -> None:
        from holdingStocks.watch_config import WATCHLIST as live
        from strategy.watch_universe import research_watchlist

        research = research_watchlist()
        self.assertEqual(
            {str(x["code"]) for x in research},
            {str(x["code"]) for x in live},
        )
        live_by = {str(x["code"]): x for x in live}
        for row in research:
            code = str(row["code"])
            other = live_by[code]
            self.assertAlmostEqual(
                float(row["entry_pct"]),
                float(other.get("entry_pct") or other.get("pct")),
                places=6,
                msg=f"entry_pct drift @ {code}",
            )


if __name__ == "__main__":
    unittest.main()
