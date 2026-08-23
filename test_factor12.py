"""因子12 / 策略六：反转池近高，研究候选。"""

from __future__ import annotations

import unittest

import pandas as pd

from strategy.factor12_combo import weekly_factor12_gate
from strategy.near_high_hold import picks_on
from strategy.s1_price_select import weekly_two_stage_gate


class Factor12Tests(unittest.TestCase):
    def test_registered(self) -> None:
        from strategy import get_factor, get_strategy

        f = get_factor("factor12")
        self.assertEqual(f.id, "factor12")
        s = get_strategy("strategy6")
        self.assertEqual(s.id, "strategy6")
        self.assertEqual(s.factor_ids, ("factor12",))
        self.assertEqual(get_strategy("rev_near").id, "strategy6")

    def test_invert_stage1_picks_losers(self) -> None:
        idx = pd.bdate_range("2020-01-06", periods=40)
        close = pd.DataFrame(index=idx)
        high = pd.DataFrame(index=idx)
        t = pd.Series(range(len(idx)), index=idx, dtype=float)
        for i in range(8):
            close[f"flat{i}"] = 10.0 + 0.01 * i
            high[f"flat{i}"] = close[f"flat{i}"] * 1.01
        close["winner"] = 8.0 + 0.25 * t
        high["winner"] = close["winner"] * 1.02
        close["loser"] = 20.0 - 0.08 * t
        high["loser"] = close["loser"] * 1.001
        later = str(idx[-1].date())
        mom = picks_on(
            weekly_two_stage_gate(
                close, high, mom_n=20, high_n=5, stage1_k=5, stage2_k=5, invert_stage1=False
            ),
            later,
        )
        rev = picks_on(
            weekly_two_stage_gate(
                close, high, mom_n=20, high_n=5, stage1_k=5, stage2_k=5, invert_stage1=True
            ),
            later,
        )
        self.assertIn("winner", mom)
        self.assertNotIn("winner", rev)
        self.assertNotEqual(set(mom), set(rev))

    def test_first_week_empty(self) -> None:
        idx = pd.bdate_range("2020-01-06", periods=8)
        close = pd.DataFrame({f"s{i}": 10.0 + i * 0.01 for i in range(6)}, index=idx)
        high = close * 1.02
        for d in idx[:5]:
            self.assertEqual(picks_on(weekly_factor12_gate(close, high), str(d.date())), [])


if __name__ == "__main__":
    unittest.main()
