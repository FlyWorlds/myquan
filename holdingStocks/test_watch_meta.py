"""策略一 meta_for_code 用定盘池阈值；策略十六遗留实仓可回退 thr_2026。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_config import (  # noqa: E402
    STRATEGY_ID,
    _WATCH_PCT,
    load_strategy16_thr_map,
    meta_for_code,
)


def test_strategy1_meta_uses_watch_pct() -> None:
    assert STRATEGY_ID == "strategy1"
    leftover = "600301"
    assert leftover in _WATCH_PCT
    item = meta_for_code(leftover, {"positions": {}})
    assert abs(float(item["pct"]) - 0.03) < 1e-12


def test_strategy1_leftover_falls_back_to_thr_2026() -> None:
    thrs = load_strategy16_thr_map()
    code = "002580"
    assert code in thrs
    item = meta_for_code(
        code,
        {"positions": {code: {"qty": 400, "name": "圣阳股份"}}},
    )
    assert abs(float(item["pct"]) - float(thrs[code])) < 1e-12


if __name__ == "__main__":
    test_strategy1_meta_uses_watch_pct()
    test_strategy1_leftover_falls_back_to_thr_2026()
    print("ok")
