"""策略十七·紫阳真君：叠加观察池轻量行情行（不进 collect_rows / 不占 SSE）。

大池（可至数百只）只走新浪批量分块轮询；买卖信号仍只在热池（持仓+默认策略）上算。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from watch_config import (
    POOL_SRC_FACTOR28,
    POOL_SRC_LABEL,
    ZIYANG_PICKS_PATH,
    code_key,
    factor28_codes,
    load_ziyang_payload,
    overlay_watchlist,
    sina_of,
)

# 叠加池轮询参数（500 只 ≈ 10 次新浪请求/轮）
OVERLAY_CHUNK = 50
OVERLAY_POLL_SEC = 3.0
# 单轮最多刷新只数（防止异常名单拖死；仍可分多轮扫完）
OVERLAY_MAX_PER_CYCLE = 500

_lock = threading.RLock()
_quotes: dict[str, dict[str, Any]] = {}  # sina -> quote dict
_rows_cache: list[dict[str, Any]] = []
_last_ok_ts = 0.0
_stop: threading.Event | None = None
_thread: threading.Thread | None = None


def overlay_sina_list() -> list[str]:
    """叠加池 sina 代码（不含热池重叠部分由 overlay_watchlist 已去重）。"""
    return [str(w["sina"]).lower() for w in overlay_watchlist()]


def get_overlay_quote(sina: str) -> dict[str, Any] | None:
    with _lock:
        q = _quotes.get(str(sina).lower())
        return dict(q) if q else None


def cached_strategy17_rows() -> list[dict[str, Any]]:
    with _lock:
        return [dict(r) for r in _rows_cache]


def _build_rows_from_quotes(quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    payload = load_ziyang_payload()
    picks = payload.get("picks") or []
    by_code: dict[str, dict[str, Any]] = {}
    for it in picks:
        if not isinstance(it, dict):
            continue
        c = code_key(str(it.get("code") or it.get("symbol") or ""))
        if not c:
            continue
        by_code[c] = it

    rows: list[dict[str, Any]] = []
    # 按 picks 顺序；无 picks 时退回 codes
    order = list(by_code.keys()) or sorted(factor28_codes())
    for rank, code in enumerate(order, 1):
        meta = by_code.get(code) or {}
        sina = sina_of(code).lower()
        q = quotes.get(sina) or {}
        last = q.get("last")
        prev = q.get("prev_close")
        open_px = q.get("open")
        try:
            day_chg = float(q["day_chg_pct"]) if q.get("day_chg_pct") is not None else None
        except (TypeError, ValueError):
            day_chg = None
        if day_chg is None and last is not None and prev not in (None, 0, 0.0):
            try:
                day_chg = (float(last) / float(prev) - 1.0) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                day_chg = None
        name = str(meta.get("name") or q.get("name") or code)
        rows.append(
            {
                "代码": code,
                "名称": name,
                "市场": "上证" if code.startswith(("5", "6", "9")) else "深证",
                "现价": None if last is None else float(last),
                "开盘": None if open_px is None else float(open_px),
                "昨收": None if prev is None else float(prev),
                "当日涨幅": day_chg,
                "池来源": POOL_SRC_LABEL.get(POOL_SRC_FACTOR28, "紫阳真君"),
                "pool_src": POOL_SRC_FACTOR28,
                "universe": "strategy17",
                "持仓": "空仓",
                "信号": "观察",
                "阈值%": "-",
                "距买点%": None,
                "appearances": meta.get("appearances"),
                "last_date": meta.get("last_date"),
                "rank": int(meta.get("rank") or rank),
                "quote_tier": "overlay",
                "bg_class": "",
            }
        )
    rows.sort(
        key=lambda r: (
            0 if r.get("现价") is not None else 1,
            -float(r["当日涨幅"]) if isinstance(r.get("当日涨幅"), (int, float)) else 0.0,
            str(r.get("代码") or ""),
        )
    )
    return rows


def refresh_overlay_quotes_once(
    *,
    fetch_batch: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None,
    max_codes: int = OVERLAY_MAX_PER_CYCLE,
) -> int:
    """拉一轮叠加池新浪批量，更新缓存。返回更新只数。"""
    from quote_feed import fetch_sina_batch
    from index import _quote_from_sina_spot

    sinas = overlay_sina_list()[: max(0, int(max_codes))]
    if not sinas:
        with _lock:
            _rows_cache.clear()
        return 0

    batch_fn = fetch_batch
    if batch_fn is None:

        def batch_fn(codes: list[str]) -> dict[str, dict[str, Any]]:  # noqa: F811
            raw = fetch_sina_batch(codes)
            out: dict[str, dict[str, Any]] = {}
            for s, spot in raw.items():
                out[str(s).lower()] = _quote_from_sina_spot(spot)
            return out

    updated = 0
    merged: dict[str, dict[str, Any]] = {}
    with _lock:
        merged.update(_quotes)

    for i in range(0, len(sinas), OVERLAY_CHUNK):
        chunk = sinas[i : i + OVERLAY_CHUNK]
        try:
            part = batch_fn(chunk)
        except Exception:  # noqa: BLE001
            continue
        for s, q in part.items():
            merged[str(s).lower()] = q
            updated += 1

    rows = _build_rows_from_quotes(merged)
    with _lock:
        _quotes.clear()
        _quotes.update(merged)
        _rows_cache[:] = rows
        global _last_ok_ts
        if updated:
            _last_ok_ts = time.time()
    return updated


def start_overlay_poller(
    *,
    stop: threading.Event,
    on_log: Callable[[str], None] | None = None,
    interval: float = OVERLAY_POLL_SEC,
) -> threading.Thread:
    """后台轮询叠加池；与热池 QuoteFeed 无关。"""
    global _stop, _thread
    log = on_log or (lambda _m: None)
    _stop = stop

    def _run() -> None:
        # 等首屏就绪后再开始，避免抢带宽
        while not stop.is_set():
            try:
                from index import _WATCH_FRONT_READY

                if _WATCH_FRONT_READY.is_set():
                    break
            except Exception:  # noqa: BLE001
                break
            if stop.wait(0.25):
                return
        n0 = len(overlay_sina_list())
        log(f"叠加池行情轮询启动：{n0} 只 · 新浪分块{OVERLAY_CHUNK} · {interval:.0f}s/轮（不占 SSE）")
        last_log = 0.0
        while not stop.is_set():
            try:
                n = refresh_overlay_quotes_once()
                now = time.time()
                # 降噪：每 60s 最多打一条
                if n and now - last_log >= 60.0:
                    log(f"叠加池行情已更新 {n} 只")
                    last_log = now
            except Exception as e:  # noqa: BLE001
                log(f"叠加池行情失败: {e}")
            if stop.wait(max(2.0, float(interval))):
                break

    t = threading.Thread(target=_run, name="overlay-sina-poll", daemon=True)
    _thread = t
    t.start()
    return t


def picks_path_note() -> str:
    return str(ZIYANG_PICKS_PATH)
