"""Health classification: block trading vs notification/display only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HS = Path(__file__).resolve().parent
if str(HS) not in sys.path:
    sys.path.insert(0, str(HS))

from health_status import (  # noqa: E402
    BLOCK_TRADING,
    DISPLAY_ONLY,
    NOTIFICATION_ONLY,
    classify_health_issue,
    classify_snapshot_health,
)


class TestHealthStatus(unittest.TestCase):
    def test_quote_stale_blocks_trading(self) -> None:
        out = classify_snapshot_health({"feedOk": False, "quoteStale": True})
        self.assertTrue(out["blockTrading"])
        self.assertEqual(out["healthLevel"], BLOCK_TRADING)

    def test_wechat_is_notification_only(self) -> None:
        out = classify_snapshot_health({"wechatSessionInvalid": True})
        self.assertFalse(out["blockTrading"])
        self.assertEqual(out["healthLevel"], NOTIFICATION_ONLY)

    def test_unknown_is_display_only(self) -> None:
        issue = classify_health_issue("something_new")
        self.assertEqual(issue["severity"], DISPLAY_ONLY)


if __name__ == "__main__":
    unittest.main()
