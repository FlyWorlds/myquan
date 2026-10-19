"""板块轮动缓存与数据库键规则 — 防止隔日表头、短结果覆盖长历史、校验多周期热门卡片保留。"""

from __future__ import annotations

import re
import unittest

from sectors.rotation_cache import (
    date_columns,
    ensure_today_column,
    payload_has_today_column,
    payload_session_fresh,
    resolve_rotation_payload,
    session_label,
    splice_today_onto_hist,
)
from sectors.store import make_doc_key


def _cell(name: str, value: float, rank: int = 1) -> dict:
    return {"name": name, "value": value, "rank": rank, "label": "", "metric": "涨幅"}


def _payload(session: str, date_names: list[str], tops: list[list[dict]], *, source="同花顺热点轮动"):
    return {
        "session": session,
        "updated_at": f"{session} 23:00:00",
        "source": source,
        "top_n": 10,
        "days": 20,
        "metrics": ["涨幅"],
        "kinds": {
            "概念": {
                "dates": [session_label(d) if "-" in d else d for d in date_names],
                "by_metric": {"涨幅": {"top": tops, "bottom": [[] for _ in tops]}},
                "members": {},
                "board_count": 10,
            }
        },
    }


class RotationCacheTests(unittest.TestCase):
    def test_yesterday_not_fresh(self) -> None:
        p = _payload("2026-09-02", ["2026-09-02", "2026-09-01"], [[_cell("军贸", 2.4)], [_cell("次新", 1.0)]])
        self.assertFalse(payload_session_fresh(p, today="2026-09-03"))
        self.assertFalse(payload_has_today_column(p, today="2026-09-03"))

    def test_session_today_but_dates_yesterday_not_fresh(self) -> None:
        p = _payload("2026-09-03", ["2026-09-02"], [[_cell("军贸", 2.4)]])
        p["session"] = "2026-09-03"
        self.assertFalse(payload_session_fresh(p, today="2026-09-03"))

    def test_empty_today_column_not_fresh(self) -> None:
        p = _payload("2026-09-03", ["2026-09-03"], [[]])
        self.assertTrue(payload_has_today_column(p, today="2026-09-03"))
        self.assertFalse(payload_session_fresh(p, today="2026-09-03"))

    def test_splice_prepends_today_keeps_hist(self) -> None:
        hist = _payload(
            "2026-09-02",
            ["2026-09-02", "2026-09-01"],
            [[_cell("军贸", 2.4)], [_cell("次新", 1.0)]],
        )
        today = _payload("2026-09-03", ["2026-09-03"], [[_cell("兵装重组概念", 3.51)]])
        today["kinds"]["概念"]["hot_periods"] = {
            "1": [{"name": "兵装重组概念", "chg_pct": 3.51, "net_inflow": -1.41e8}]
        }
        today["kinds"]["概念"]["board_stats"] = {
            "兵装重组概念": {"name": "兵装重组概念", "today_rank": 1, "appear_15d": 2}
        }
        out = splice_today_onto_hist(hist, today, days=20, today="2026-09-03")
        assert out is not None
        self.assertEqual(date_columns(out)[:3], ["09月03日", "09月02日", "09月01日"])
        self.assertEqual(out["kinds"]["概念"]["by_metric"]["涨幅"]["top"][0][0]["name"], "兵装重组概念")
        self.assertEqual(out["kinds"]["概念"]["by_metric"]["涨幅"]["top"][1][0]["name"], "军贸")
        self.assertEqual(out["kinds"]["概念"]["hot_periods"]["1"][0]["name"], "兵装重组概念")
        self.assertEqual(out["kinds"]["概念"]["board_stats"]["兵装重组概念"]["appear_15d"], 2)
        self.assertEqual(out["session"], "2026-09-03")

    def test_one_day_fresh_must_not_replace_20day_hist(self) -> None:
        hist_dates = [f"2026-09-{d:02d}" for d in range(2, 0, -1)] + [
            f"2026-08-{d:02d}" for d in range(31, 14, -1)
        ]
        tops = [[_cell(f"h{i}", 1.0)] for i in range(len(hist_dates))]
        hist = _payload("2026-09-02", hist_dates, tops)
        today = _payload("2026-09-03", ["2026-09-03"], [[_cell("影视", 2.5)]])
        out = resolve_rotation_payload(fresh=today, disk=hist, today="2026-09-03", days=20)
        assert out is not None
        dates = date_columns(out)
        self.assertEqual(dates[0], "09月03日")
        self.assertGreaterEqual(len(dates), 18)
        self.assertEqual(out["kinds"]["概念"]["by_metric"]["涨幅"]["top"][0][0]["name"], "影视")

    def test_full_fresh_today_wins(self) -> None:
        disk = _payload("2026-09-02", ["2026-09-02"], [[_cell("旧", 1.0)]])
        dates = ["2026-09-03", "2026-09-02", "2026-09-01", "2026-08-31", "2026-08-28"]
        fresh = _payload("2026-09-03", dates, [[_cell("新", 3.0)] for _ in dates])
        out = resolve_rotation_payload(fresh=fresh, disk=disk, today="2026-09-03", days=20)
        self.assertIs(out, fresh)

    def test_ensure_today_column_on_yesterday_hist(self) -> None:
        hist = _payload("2026-09-02", ["2026-09-02", "2026-09-01"], [[_cell("军贸", 2.4)], [_cell("次新", 1.0)]])
        out = ensure_today_column(hist, today="2026-09-03", days=20)
        assert out is not None
        self.assertEqual(date_columns(out)[0], "09月03日")
        self.assertEqual(date_columns(out)[1], "09月02日")
        self.assertEqual(out["session"], "2026-09-03")
        self.assertFalse(payload_session_fresh(out, today="2026-09-03"))

    def test_missing_fresh_still_exposes_today_header(self) -> None:
        hist = _payload("2026-09-02", ["2026-09-02"], [[_cell("军贸", 2.4)]])
        out = resolve_rotation_payload(fresh=None, disk=hist, today="2026-09-03", days=20)
        assert out is not None
        self.assertEqual(date_columns(out)[0], "09月03日")
        self.assertEqual(date_columns(out)[1], "09月02日")

    def test_doc_key_matches_java_constraint(self) -> None:
        for name in ("兵装重组概念", "DRG/DIP", "海上丝路", "共封装光学(CPO)"):
            k = make_doc_key("sectors_detail", name)
            self.assertRegex(k, r"^[a-z][a-z0-9_]{0,63}$")


if __name__ == "__main__":
    unittest.main()
