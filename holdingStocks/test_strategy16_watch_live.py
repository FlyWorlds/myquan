"""策略十六默认 + 盯盘：用当日真实日线/1m 核对隔夜高点、开盘保护、T+1 已记。

案例来自 2026-09-14 纸面账本（只读，不写 holdings.json）：
  · 隔夜仓（周五买入）：特发 000070、远东 600869、中天 600522 → 应用昨收/昨高
  · 今日新买：天通 600330、神州数码 000034、招商轮船 601872 → 不用昨收/昨高
研究用途，非投资建议。
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_config import (  # noqa: E402
    FACTOR_ID,
    FACTOR22_ID,
    MAX_BUYS_PER_DAY,
    MAX_PORTFOLIO_SLOTS,
    SELF_WATCHLIST_PICKS,
    STRATEGY_ID,
    USE_FACTOR4,
    session_open_bell_ts,
    sina_of,
)
from index import (  # noqa: E402
    _closed_mark_px,
    fetch_today_quote,
    paper_exit_decision,
    purge_illegal_t1_stop_notes,
    t1_stop_note_allowed,
    t1_stop_note_px_is_legal,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import is_t1_buy_day  # noqa: E402
from strategy.pullback_wave_stop import (  # noqa: E402
    cost_hard_stop_px,
    first_session_exit_fill,
    overnight_open_protect_px,
    overnight_peak_px,
    overnight_session_high_ok,
    path_dependent_pullback_hit,
    simulate_factor26_day_1m,
)

SESSION = "2026-09-14"
PREV_SESSION = "2026-09-11"

# 隔夜仓：周五策略买入，周一开盘保护
OVERNIGHT = {
    "000070": {
        "name": "特发信息",
        "buy_time": "2026-09-11 09:43:32",
        "cost": 16.29,
        "fill": 16.93,
        "peak_high": 17.65,
    },
    "600869": {
        "name": "远东股份",
        "buy_time": "2026-09-11 09:30:37",
        "cost": 23.78,
        "fill": 24.10,
        "peak_high": 25.35,
    },
    "600522": {
        "name": "中天科技",
        "buy_time": "2026-09-11 09:43:32",
        "cost": 33.48,
        "fill": 33.84,
        "peak_high": 34.78,
    },
}
# 今日新买：T+1，禁用昨收/昨高
TODAY_BUY = {
    "600330": {
        "name": "天通股份",
        "buy_time": "2026-09-14 10:08:53",
        "cost": 27.81,
        "peak_high": 30.23,
        "illegal_note": 29.37,
    },
    "000034": {
        "name": "神州数码",
        "buy_time": "2026-09-14 09:48:07",
        "cost": 23.09,
        "peak_high": 23.22,
        "legal_note": 22.51,
    },
    "601872": {
        "name": "招商轮船",
        "buy_time": "2026-09-14 09:40:17",
        "cost": 21.07,
        "peak_high": 21.52,
        "legal_note": 20.54,
    },
}


def _day_key(ts) -> str:
    t = pd.Timestamp(ts)
    if getattr(t, "tzinfo", None) is not None:
        t = t.tz_convert("Asia/Shanghai").tz_localize(None)
    return str(t.date())


def _session_bars(minutes: pd.DataFrame, session: str) -> pd.DataFrame:
    if minutes is None or minutes.empty or "ts" not in minutes.columns:
        return pd.DataFrame()
    day = minutes[_day_key_series(minutes["ts"]) == session]
    return day.sort_values("ts") if not day.empty else pd.DataFrame()


def _day_key_series(col: pd.Series) -> pd.Series:
    ts = pd.to_datetime(col, errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return ts.dt.strftime("%Y-%m-%d")


def _prev_ohlc(daily: pd.DataFrame, session: str) -> dict[str, float]:
    d = daily.copy()
    ts = pd.to_datetime(d["date"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    d["d"] = ts.dt.strftime("%Y-%m-%d")
    before = d[d["d"] < session]
    if before.empty:
        raise AssertionError(f"日线没有 {session} 之前的K")
    r = before.iloc[-1]
    return {
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
        "date": str(r["d"]),
    }


def _quote_ohlc(quote: dict) -> dict[str, float]:
    o = float(quote.get("open") or 0)
    h = float(quote.get("high") or 0)
    lo = float(quote.get("low") or 0)
    last = float(quote.get("last") or 0)
    prev = float(quote.get("prev_close") or 0)
    if o <= 0 or last <= 0:
        raise AssertionError(f"盯盘行情无效: {quote}")
    return {"open": o, "high": h, "low": lo, "close": last, "prev_close": prev}


def _day_bars(quote: dict) -> pd.DataFrame:
    bars = quote.get("_day_bars")
    if isinstance(bars, pd.DataFrame) and not bars.empty:
        return bars.sort_values("ts") if "ts" in bars.columns else bars
    return pd.DataFrame()


class TestStrategy16DefaultWiring(unittest.TestCase):
    def test_watch_defaults_are_strategy16_factor26(self) -> None:
        self.assertEqual(STRATEGY_ID, "strategy16")
        self.assertEqual(FACTOR_ID, "factor26")
        self.assertEqual(FACTOR22_ID, "factor22")
        self.assertFalse(USE_FACTOR4)
        self.assertEqual(MAX_PORTFOLIO_SLOTS, 5)
        self.assertEqual(MAX_BUYS_PER_DAY, 2)
        self.assertIn(("600330", "天通股份"), SELF_WATCHLIST_PICKS)

    def test_bindings_factor22_off_factor26_on(self) -> None:
        from strategy import get_strategy

        entry = get_strategy("strategy16")
        by_id = {b.factor_id: b for b in entry.bindings(enabled_only=False)}
        self.assertTrue(by_id["factor26"].enabled)
        self.assertTrue(by_id["factor2"].enabled)
        self.assertTrue(by_id["factor27"].enabled)
        self.assertFalse(by_id["factor22"].enabled)


class TestStrategy16WatchLive(unittest.TestCase):
    daily: dict[str, pd.DataFrame] = {}
    quotes: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        codes = list(OVERNIGHT) + list(TODAY_BUY)
        for code in codes:
            sina = sina_of(code)
            daily = fetch_daily(sina, "20260901", "20260914")
            if daily is None or daily.empty:
                raise AssertionError(f"拉不到日线 {code} {sina}")
            cls.daily[code] = daily
            q = fetch_today_quote(sina)
            if not q or float(q.get("open") or 0) <= 0:
                raise AssertionError(f"拉不到盯盘行情 {code} {sina}: {q}")
            cls.quotes[code] = q

    def test_overnight_names_use_prev_high_from_buy_time(self) -> None:
        for code, meta in OVERNIGHT.items():
            today = _quote_ohlc(self.quotes[code])
            prev = _prev_ohlc(self.daily[code], SESSION)
            self.assertEqual(prev["date"], PREV_SESSION, msg=meta["name"])
            ok = overnight_session_high_ok(
                qty=1000,
                buy_time=meta["buy_time"],
                session=SESSION,
            )
            self.assertTrue(ok, msg=f"{meta['name']} 周五买入周一应合格")
            peak = overnight_peak_px(
                meta["cost"],
                prev["close"],
                meta["peak_high"],
                buy_time=meta["buy_time"],
                session=SESSION,
            )
            self.assertGreater(peak, 0.0, msg=meta["name"])
            protect = overnight_open_protect_px(
                meta["cost"],
                prev["close"],
                peak_high=meta["peak_high"],
                buy_time=meta["buy_time"],
                session=SESSION,
            )
            self.assertGreater(protect, cost_hard_stop_px(meta["cost"]))
            self.assertLessEqual(today["open"], protect + 1e-6)
            dec = paper_exit_decision(
                qty=1000,
                sellable=1000,
                t1_today=False,
                last=today["close"],
                open_px=today["open"],
                prev_close=prev["close"],
                cost=meta["cost"],
                peak_high=meta["peak_high"],
                working_stop=protect,
                path_hit=False,
                signal_ok=True,
                buy_time=meta["buy_time"],
                session=SESSION,
            )
            self.assertTrue(dec["hit"], msg=meta["name"])
            self.assertEqual(dec["kind"], "open_protect", msg=meta["name"])
            self.assertAlmostEqual(dec["fill_px"], today["open"], places=2)
            self.assertTrue(dec["open_bell"], msg=meta["name"])
            self.assertAlmostEqual(today["open"], meta["fill"], places=2)

    def test_today_buys_ignore_prev_close_and_prev_high(self) -> None:
        for code, meta in TODAY_BUY.items():
            today = _quote_ohlc(self.quotes[code])
            prev = _prev_ohlc(self.daily[code], SESSION)
            self.assertTrue(is_t1_buy_day(meta["buy_time"], SESSION))
            self.assertFalse(
                overnight_session_high_ok(
                    qty=1000,
                    buy_time=meta["buy_time"],
                    session=SESSION,
                ),
                msg=meta["name"],
            )
            self.assertEqual(
                overnight_peak_px(
                    meta["cost"],
                    prev["close"],
                    meta["peak_high"],
                    buy_time=meta["buy_time"],
                    session=SESSION,
                ),
                0.0,
                msg=meta["name"],
            )
            hard = cost_hard_stop_px(meta["cost"])
            protect = overnight_open_protect_px(
                meta["cost"],
                prev["close"],
                peak_high=meta["peak_high"],
                buy_time=meta["buy_time"],
                session=SESSION,
            )
            self.assertAlmostEqual(protect, hard, places=4)
            dec = paper_exit_decision(
                qty=1000,
                sellable=0,
                t1_today=True,
                last=today["close"],
                open_px=today["open"],
                prev_close=prev["close"],
                cost=meta["cost"],
                peak_high=meta["peak_high"],
                working_stop=protect,
                path_hit=False,
                signal_ok=True,
                buy_time=meta["buy_time"],
                session=SESSION,
            )
            self.assertFalse(dec["hit"], msg=meta["name"])
            if today["close"] > hard * 1.003:
                self.assertFalse(dec["hit_show"], msg=f"{meta['name']} 现价不在硬保护附近")

    def test_tian_tong_mid_gain_note_is_illegal(self) -> None:
        meta = TODAY_BUY["600330"]
        prev = _prev_ohlc(self.daily["600330"], SESSION)
        today = _quote_ohlc(self.quotes["600330"])
        self.assertFalse(
            t1_stop_note_px_is_legal(stop_px=meta["illegal_note"], cost_px=meta["cost"])
        )
        self.assertFalse(
            t1_stop_note_allowed(
                reason="hard_from_cost",
                stop_px=meta["illegal_note"],
                cost_px=meta["cost"],
                last_px=today["close"],
                prev_close=prev["close"],
            )
        )
        self.assertTrue(
            t1_stop_note_px_is_legal(
                stop_px=TODAY_BUY["000034"]["legal_note"],
                cost_px=TODAY_BUY["000034"]["cost"],
            )
        )
        ledger = json.loads((HS / "holdings.json").read_text(encoding="utf-8"))
        clone = copy.deepcopy(ledger)
        n = purge_illegal_t1_stop_notes(clone)
        self.assertGreaterEqual(n, 1)
        pos = clone["positions"]["600330"]
        self.assertFalse(pos.get("stop_noted"))
        self.assertIsNone(pos.get("stop_noted_px"))
        self.assertTrue(clone["positions"]["000034"]["stop_noted"])

    def test_tefa_1m_open_protect_stamps_0930(self) -> None:
        meta = OVERNIGHT["000070"]
        prev = _prev_ohlc(self.daily["000070"], SESSION)
        today = _quote_ohlc(self.quotes["000070"])
        bars = _day_bars(self.quotes["000070"])
        self.assertFalse(bars.empty, "特发当日 1m 为空")
        first = bars.iloc[0]
        fill = first_session_exit_fill(
            bars,
            cost_px=meta["cost"],
            prev_close=prev["close"],
            day_open=today["open"],
            peak_high=meta["peak_high"],
            buy_time=meta["buy_time"],
            session=SESSION,
        )
        self.assertIsNotNone(fill)
        self.assertAlmostEqual(float(fill), today["open"], places=2)
        hit = path_dependent_pullback_hit(
            bars,
            seed_high=overnight_peak_px(
                meta["cost"],
                prev["close"],
                meta["peak_high"],
                buy_time=meta["buy_time"],
                session=SESSION,
            ),
            cost_px=meta["cost"],
            day_open=today["open"],
            overnight_armed=False,
        )
        self.assertTrue(hit.get("hit_stop"))
        self.assertAlmostEqual(float(hit.get("touch_stop") or 0), today["open"], places=2)
        ts_s = str(hit.get("touch_ts") or "")
        self.assertIn("09:30:00", ts_s)
        self.assertEqual(session_open_bell_ts(SESSION), f"{SESSION} 09:30:00")
        # 首根即使标 09:31/09:32，成交价=今开也记 09:30
        self.assertAlmostEqual(float(first["open"]), today["open"], places=2)

    def test_zhongtian_closed_fill_is_open_protect(self) -> None:
        """中天：昨收已过 3%，今开低于隔夜中段保护。盯盘/已平仓都是开盘保护，成交价=今开。

        1m 路径 first_session_exit_fill 不负责开盘保护（禁止用今开去撞盘中抬高后的止损）；
        与 paper_exit / _closed_mark_px 同序：开盘保护优先。
        """
        meta = OVERNIGHT["600522"]
        prev = _prev_ohlc(self.daily["600522"], SESSION)
        today = _quote_ohlc(self.quotes["600522"])
        bars = _day_bars(self.quotes["600522"])
        self.assertFalse(bars.empty)
        self.assertAlmostEqual(today["open"], 33.84, places=2)
        protect = overnight_open_protect_px(
            meta["cost"],
            prev["close"],
            peak_high=meta["peak_high"],
            buy_time=meta["buy_time"],
            session=SESSION,
        )
        self.assertGreater(protect, cost_hard_stop_px(meta["cost"]))
        self.assertLessEqual(today["open"], protect + 1e-6)
        dec = paper_exit_decision(
            qty=1000,
            sellable=1000,
            t1_today=False,
            last=today["close"],
            open_px=today["open"],
            prev_close=prev["close"],
            cost=meta["cost"],
            peak_high=meta["peak_high"],
            working_stop=protect,
            path_hit=False,
            signal_ok=True,
            buy_time=meta["buy_time"],
            session=SESSION,
        )
        self.assertTrue(dec["hit"])
        self.assertEqual(dec["kind"], "open_protect")
        self.assertAlmostEqual(float(dec["fill_px"]), today["open"], places=2)
        closed = _closed_mark_px(
            {
                "代码": "600522",
                "交易日": SESSION,
                "买入时间": meta["buy_time"],
                "开盘": today["open"],
                "昨收": prev["close"],
                "峰值": meta["peak_high"],
                "成本": meta["cost"],
                "持仓": 1000,
            },
            cost=meta["cost"],
            bars=bars,
        )
        self.assertIsNotNone(closed)
        self.assertAlmostEqual(float(closed), today["open"], places=2)

    def test_tiantong_1m_today_buy_does_not_sell(self) -> None:
        meta = TODAY_BUY["600330"]
        prev = _prev_ohlc(self.daily["600330"], SESSION)
        today = _quote_ohlc(self.quotes["600330"])
        bars = _day_bars(self.quotes["600330"])
        self.assertFalse(bars.empty)
        sim = simulate_factor26_day_1m(
            bars,
            open_px=today["open"],
            holding_in=False,
            can_sell=False,
            allow_entry=True,
            prev_close=prev["close"],
            peak_high_in=meta["peak_high"],
            buy_time=meta["buy_time"],
            session=SESSION,
        )
        # 今日新买：T+1 不卖；即使传入昨高也不能种进隔夜峰值
        self.assertFalse(sim.get("holding_out") and sim.get("sell_px"))
        if sim.get("bought_today"):
            self.assertIsNone(sim.get("sell_px"))
        leaked = simulate_factor26_day_1m(
            bars,
            open_px=today["open"],
            holding_in=True,
            can_sell=True,
            allow_entry=False,
            cost_px=meta["cost"],
            peak_high_in=meta["peak_high"],
            prev_close=prev["close"],
            buy_time=meta["buy_time"],
            session=SESSION,
        )
        hard = cost_hard_stop_px(meta["cost"])
        if leaked.get("sell_px") is not None:
            self.assertLessEqual(float(leaked["sell_px"]), hard + 1e-6)


if __name__ == "__main__":
    unittest.main()
