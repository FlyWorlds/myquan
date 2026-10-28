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


def test_strategy16_meta_ignores_legacy_watch_pct(monkeypatch) -> None:
    monkeypatch.setattr("watch_config.STRATEGY_ID", "strategy16")
    leftover = "600301"
    assert leftover in _WATCH_PCT
    assert leftover not in load_strategy16_thr_map()
    item = meta_for_code(leftover, {"positions": []})
    assert item["pct"] == DEFAULT_PCT
    assert abs(float(item["pct"]) - 0.03) > 1e-9


def test_strategy16_meta_uses_thr_2026(monkeypatch) -> None:
    monkeypatch.setattr("watch_config.STRATEGY_ID", "strategy16")
    thrs = {"600330": .03}
    monkeypatch.setattr("watch_config.load_strategy16_thr_map", lambda: thrs)
    code = "600330"
    item = meta_for_code(code, {"positions": []})
    assert abs(float(item["pct"]) - float(thrs[code])) < 1e-12


def test_default_strategy1_uses_its_own_thresholds(monkeypatch):
    import watch_config as cfg
    assert cfg.STRATEGY_ID == "strategy1"
    monkeypatch.setattr(cfg, "load_strategy1_thr_map", lambda: {"600330": .03})
    monkeypatch.setattr(cfg, "load_strategy16_thr_map", lambda: {"600330": .025})
    assert cfg.meta_for_code("600330", {"positions": {}})["pct"] == .03
    s1 = {item["code"]: item for item in cfg.self_watch_items({"positions": {}}, strategy_id="strategy1")}
    s16 = {item["code"]: item for item in cfg.self_watch_items({"positions": {}}, strategy_id="strategy16")}
    assert s1["600330"]["pct"] == .03
    assert s16["600330"]["pct"] == .025
