"""紫阳真君宇宙：国泰海通/国泰君安武汉紫阳东路近 3 个月龙虎榜成交池。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MYQUAN = Path(__file__).resolve().parents[1]
DEFAULT_PICKS_PATH = _MYQUAN / "backtest" / "strategy17_ziyang" / "picks_3m.json"

SEAT_NAME = "国泰海通证券股份有限公司武汉紫阳东路证券营业部"
SEAT_ALIASES = (
    "国泰海通证券股份有限公司武汉紫阳东路证券营业部",
    "国泰君安证券股份有限公司武汉紫阳东路证券营业部",
    "国泰海通证券武汉紫阳东路证券营业部",
    "国泰君安证券武汉紫阳东路证券营业部",
)


def load_picks(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PICKS_PATH
    if not p.is_file():
        return {
            "horizon": "rolling_3m",
            "n_picks": 0,
            "picks": [],
            "note": "池为空，请先跑 python strategy/run_ziyang_pool.py",
        }
    return json.loads(p.read_text(encoding="utf-8"))


def pick_codes(payload: dict[str, Any] | None = None) -> list[str]:
    data = payload if payload is not None else load_picks()
    out: list[str] = []
    seen: set[str] = set()
    for it in data.get("picks") or []:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code") or it.get("symbol") or "").strip()
        digits = "".join(ch for ch in code if ch.isdigit())
        c = digits.zfill(6)[-6:] if digits else ""
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def refresh_pool() -> dict[str, Any]:
    """调用挖池脚本重写 picks_3m.json。"""
    import runpy

    script = DEFAULT_PICKS_PATH.parent / "mine_ziyang_lhb.py"
    runpy.run_path(str(script), run_name="__main__")
    return load_picks()
