"""策略十六 meta_for_code 不吃策略一遗留池阈值。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = Path(__file__).resolve().parent
for p in (str(ROOT), str(HS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watch_config import (  # noqa: E402
    DEFAULT_PCT,
    STRATEGY_ID,
    _WATCH_PCT,
    load_strategy16_thr_map,
    meta_for_code,
)


def test_strategy16_meta_ignores_legacy_watch_pct() -> None:
    assert STRATEGY_ID == "strategy16"
    leftover = "600301"
    assert leftover in _WATCH_PCT
    assert leftover not in load_strategy16_thr_map()
    item = meta_for_code(leftover, {"positions": []})
    assert item["pct"] == DEFAULT_PCT
    assert abs(float(item["pct"]) - 0.03) > 1e-9


def test_strategy16_meta_uses_thr_2026() -> None:
    thrs = load_strategy16_thr_map()
    code = "600330"
    assert code in thrs
    item = meta_for_code(code, {"positions": []})
    assert abs(float(item["pct"]) - float(thrs[code])) < 1e-12


if __name__ == "__main__":
    test_strategy16_meta_ignores_legacy_watch_pct()
    test_strategy16_meta_uses_thr_2026()
    print("ok")
