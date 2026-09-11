"""策略十六 / 因子26：10% 半仓后剩余仓当日仍可止盈。"""

from __future__ import annotations

import unittest

import pandas as pd

from backtest.strategy1_pool_1m.run import simulate_portfolio_3slots


def _daily(*rows: tuple[str, float, float, float, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(d),
                "day": d,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
            }
            for d, o, h, lo, c in rows
        ]
    )


def _minutes(day: str, bars: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    rows = []
    for hm, o, h, lo, c in bars:
        rows.append(
            {
                "ts": pd.Timestamp(f"{day} {hm}:00"),
                "day": day,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
            }
        )
    return pd.DataFrame(rows)


class TestStrategy16HalfRemaining(unittest.TestCase):
    def test_pool_1m_half_then_peak_trail_clears_remainder_same_day(self):
        """隔夜仓先触 10% 半仓，随后峰值回落 2% 必须卖掉剩余；sold_today 不得禁卖。"""
        daily = _daily(
            ("2026-09-07", 101.0, 101.5, 99.5, 100.0),  # 阴，次日可买
            ("2026-09-08", 100.0, 103.5, 99.8, 103.0),
            ("2026-09-09", 113.0, 113.4, 110.4, 111.0),
        )
        minutes = pd.concat(
            [
                _minutes(
                    "2026-09-08",
                    [("09:31", 100.0, 103.2, 99.9, 102.8)],
                ),
                _minutes(
                    "2026-09-09",
                    [
                        ("09:31", 113.0, 113.2, 112.9, 113.0),
                        ("09:32", 111.5, 111.8, 110.5, 111.0),
                    ],
                ),
            ],
            ignore_index=True,
        )
        out = simulate_portfolio_3slots(
            [
                {
                    "code": "600000",
                    "name": "测试",
                    "entry_pct": 0.025,
                    "pullback_pct": 0.025,
                    "daily": daily,
                    "minutes": minutes,
                }
            ],
            days=2,
            initial_cash=100_000.0,
            max_slots=3,
            allow_f22_rebuy=False,
            allow_open_rebuy_after_sell=False,
        )
        sells = [t for t in out["trades"] if t["side"] == "sell"]
        reasons = [str(t.get("exit_reason") or "") for t in sells]
        self.assertTrue(
            any(r == "ladder_half_10" for r in reasons),
            f"缺少半仓卖出: {out['trades']}",
        )
        self.assertTrue(
            any(r == "peak_pullback_clear" for r in reasons),
            f"半仓后剩余仓当日未被峰值回落清掉: {out['trades']}",
        )
        self.assertEqual(out["summary"].get("n_open"), 0, out["summary"])


if __name__ == "__main__":
    unittest.main()
