"""因子26 characterization：锁定 eval_multi_tp_bar / evaluate_pullback_wave_stop 行为。

目的：重构调用路径时不得无意改变现有交易行为（非证明旧逻辑「正确」）。
"""

from __future__ import annotations

import unittest

from strategy.core.factor_result import DecisionContext, FactorResult
from strategy.pullback_wave_stop import (
    evaluate_pullback_wave_stop,
    eval_multi_tp_bar,
)


def _bar(
    *,
    o: float,
    h: float,
    lo: float,
    cost: float,
    peak: float,
    shares: int = 400,
    can_sell: bool = True,
    overnight_armed: bool = False,
    day_open: float | None = None,
    tp_stage: int = 0,
    vol20: float | None = 0.05,
) -> dict:
    return dict(
        bar_open=o,
        bar_high=h,
        bar_low=lo,
        cost_px=cost,
        peak_before=peak,
        shares=shares,
        can_sell=can_sell,
        overnight_armed=overnight_armed,
        day_open=day_open if day_open is not None else o,
        tp_stage=tp_stage,
        vol20_daily=vol20,
    )


class TestFactor26Characterization(unittest.TestCase):
    def test_case_a_no_trigger_mid_range(self) -> None:
        """Case A：成本附近震荡，不触发卖出。"""
        kw = _bar(o=100.0, h=101.0, lo=99.5, cost=100.0, peak=101.0)
        raw = eval_multi_tp_bar(**kw)
        self.assertIsNone(raw["action"])
        fr = evaluate_pullback_wave_stop(DecisionContext(
            symbol="TEST",
            entry_price=100.0,
            bar_open=100.0,
            bar_high=101.0,
            bar_low=99.5,
            peak_before=101.0,
            shares=400,
            day_open=100.0,
            vol20_daily=0.05,
        ))
        self.assertFalse(fr.triggered)
        self.assertEqual(fr.factor_id, "factor26")

    def test_case_b_hard_gap_sell(self) -> None:
        """Case B：低开已破硬保护 → 开盘立刻卖。"""
        kw = _bar(o=97.0, h=97.5, lo=96.5, cost=100.0, peak=100.0, day_open=97.0)
        raw = eval_multi_tp_bar(**kw)
        self.assertIsNotNone(raw["action"])
        self.assertEqual(raw["action"]["kind"], "full")
        fr = evaluate_pullback_wave_stop(DecisionContext(
            entry_price=100.0,
            bar_open=97.0,
            bar_high=97.5,
            bar_low=96.5,
            peak_before=100.0,
            shares=400,
            day_open=97.0,
            vol20_daily=0.05,
        ))
        self.assertTrue(fr.triggered)
        self.assertEqual(fr.factor_id, "factor26")
        self.assertEqual(fr.metadata.get("kind"), "full")
        self.assertIsNotNone(fr.price)

    def test_case_c_t1_cannot_sell_but_may_mark(self) -> None:
        """Case C：T+1 不可卖 — action 为空（可记 tp_marked）。"""
        # 用明显破硬保护的 bar，但 can_sell=False
        kw = _bar(
            o=97.0, h=97.5, lo=96.5, cost=100.0, peak=100.0, day_open=97.0, can_sell=False
        )
        raw = eval_multi_tp_bar(**kw)
        # 生产路径：不可卖时不应成交
        self.assertIsNone(raw["action"])
        fr = evaluate_pullback_wave_stop(
            DecisionContext(
                entry_price=100.0,
                bar_open=97.0,
                bar_high=97.5,
                bar_low=96.5,
                peak_before=100.0,
                shares=400,
                day_open=97.0,
                can_sell=False,
                vol20_daily=0.05,
            )
        )
        self.assertFalse(fr.triggered)

    def test_case_d_ladder_half_at_10pct(self) -> None:
        """Case D：峰值浮盈≥10% 且触及阶梯半仓区 → 可能 half。"""
        # 成本 100，峰值已到 112，本 bar 低点打到 ladder 半仓价附近
        kw = _bar(o=110.0, h=112.0, lo=109.5, cost=100.0, peak=112.0, vol20=0.02)
        raw = eval_multi_tp_bar(**kw)
        fr = evaluate_pullback_wave_stop(DecisionContext(
            entry_price=100.0,
            bar_open=110.0,
            bar_high=112.0,
            bar_low=109.5,
            peak_before=112.0,
            shares=400,
            day_open=110.0,
            vol20_daily=0.02,
        ))
        # wrapper 与 raw 触发态一致
        self.assertEqual(fr.triggered, raw["action"] is not None)
        if raw["action"] is not None:
            self.assertEqual(fr.reason, raw["action"]["reason"])
            self.assertEqual(fr.metadata.get("kind"), raw["action"]["kind"])

    def test_wrapper_matches_raw_dict_on_idle_and_fire(self) -> None:
        cases = [
            _bar(o=100.0, h=100.5, lo=99.8, cost=100.0, peak=100.5),
            _bar(o=96.5, h=97.0, lo=96.0, cost=100.0, peak=100.0, day_open=96.5),
            _bar(o=105.0, h=106.0, lo=104.0, cost=100.0, peak=106.0, vol20=0.03),
        ]
        for kw in cases:
            raw = eval_multi_tp_bar(**kw)
            ctx = DecisionContext(
                entry_price=kw["cost_px"],
                bar_open=kw["bar_open"],
                bar_high=kw["bar_high"],
                bar_low=kw["bar_low"],
                peak_before=kw["peak_before"],
                shares=kw["shares"],
                day_open=kw["day_open"],
                can_sell=kw["can_sell"],
                vol20_daily=kw["vol20_daily"],
                tp_stage=kw["tp_stage"],
            )
            fr = evaluate_pullback_wave_stop(ctx)
            self.assertIsInstance(fr, FactorResult)
            self.assertEqual(fr.triggered, raw["action"] is not None)
            if raw["action"]:
                self.assertEqual(fr.reason, raw["action"]["reason"])
                self.assertAlmostEqual(float(fr.price or 0), float(raw["action"]["fill_px"]), places=6)


if __name__ == "__main__":
    unittest.main()
