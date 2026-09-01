"""持仓记录与盯盘：与核心策略一（因子1 + 因子2）同步。

策略锁定 · 策略一：
  · 因子1 买：high≥ceil(open×(1+entry))；前日阴/小阳；禁双阳跨日≥5%；T+1
  · 因子1 卖：开盘−stop 止损全清（个股阈值见 watch_config）
  · 因子2：账户回撤加减仓预警（不自动改现金）
  · 默认定盘宇宙：因子13A+16 宽宇宙换池 Top10（无置顶；见 watch_config.WATCHLIST）
  · 可选切策略七：watch_config.USE_FACTOR4=True + S7_WATCHLIST

功能：
  · 拉取当日实时行情（东财 SSE + 新浪批量；盯盘不拉历史分钟 K）
  · 因子1 与 strategy1 bindings / open_break 同源
  · 因子2 与 strategy/dd_alert 同源
  · 有仓：止损自动结算（全清）；空仓：已触买/将买入建议限价
  · 本地 JSON 记录持仓；T+1 买入日不可卖

用法：
  python index.py              # 终端查看行情 + 持仓（若 watch 在跑则同步 JSON 并打开前端）
  python index.py watch        # 长驻盯盘：Nuxt 前端 + WebSocket JSON 推送
  python index.py buy 600552 15.50 400
  python index.py sell 600552 16.20 400
  python index.py set-cost 600552 15.95 --qty 400
  python index.py set-cost 600552 15.445 --qty 800 --available 600 --today-cost 15.78
  python index.py review       # 行情复盘并推送微信
  python index.py review-schedule install  # 周一/周五 15:00 定时推送
  python index.py history
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, quote, unquote, urlparse

import akshare as ak
import pandas as pd
import requests

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from quote_feed import LocalWsHub, QuoteFeedManager, fetch_sina_batch, ws_accept_key
from strategy.minute import pull_akshare_1m
from strategy import get_strategy_bindings
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    EXIT_REASONS,
    LOT_SIZE,
    NEAR_FACTOR_PCT,
    REASON_STOP,
    TICK_SIZE,
    bar_shape,
    entry_filters_ok,
    format_trigger_md,
    is_t1_buy_day,
    is_yang,
    limit_down_state,
    prev_day_allows_entry,
    replay_last_factor_triggers,
    should_block_entry_by_yang,
    strategy_levels,
    strategy_signal,
)
from strategy.data import AKSHARE_CALL_LOCK, fetch_daily

from factor2_watch import format_factor2_summary, sync_factor2
from factor4_watch import (
    bull_exec_today,
    effective_stop_pct,
    format_factor4_tag,
    resolve_factor4_spec,
)
from watch_config import (
    AUCTION_MILESTONES,
    FACTOR4_ID,
    FACTOR_ID,
    INDEX_WATCH,
    OPEN_PRICE_REFRESH_HOUR,
    OPEN_PRICE_REFRESH_MINUTE,
    STRATEGY_ID,
    STRATEGY_NAME,
    USE_FACTOR4,
    WATCHLIST,
    effective_watchlist,
    calc_day_pnl as _calc_day_pnl,
    code_key as _code_key,
    empty_position as _empty_position,
    find_meta as _find_meta,
    is_auction_quote_window,
    is_auction_window,
    is_signal_window,
    is_threshold_ready,
    market_phase,
    market_phase_label,
    sellable_qty as _sellable_qty,
    sina_of as _sina_of,
    watchlist_codes_label as _watchlist_codes_label,
)
from watch_snapshot import build_watch_snapshot

# 盯盘与回测共用：默认策略一 = 因子1（买卖）+ 因子2（回撤预警）
# 标的池唯一真源：watch_config.WATCHLIST
FACTOR2_ID = "factor2"

_STRATEGY_FACTORS_LABEL = (
    "因子1买卖 + 因子4牛市持股"
    if USE_FACTOR4
    else "因子1买卖 + 因子2回撤预警 · 13A+16池"
)
_STRATEGY_SYNC_NOTE = (
    "与 strategy3/strategy4 bindings / bull_regime 同源"
    if USE_FACTOR4
    else "与 strategy1 bindings / open_break 同源"
)

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / "holdings.json"
TRADES_FILE = ROOT / "trades.jsonl"
WATCH_META_FILE = ROOT / "holdings_watch.json"
WATCH_PID_FILE = ROOT / "holdings_watch.pid"
WATCH_UI_DIST = ROOT / "watch-ui" / "dist"
WATCH_UI_DIR = ROOT / "watch-ui"
WATCH_UI_DEV_PORT = 3000

# watch 模式本地 WebSocket 广播（/ws）；非 watch 为 None
_ws_hub: LocalWsHub | None = None
_last_watch_snapshot: dict[str, Any] | None = None
_last_snapshot_digest: str | None = None
_HOLDINGS_CACHE: dict[str, Any] = {"data": None, "mtime": 0.0}
_REPLAY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_MIN_WATCH_REFRESH_SEC = 1.0
_INDEX_CACHE: dict[str, Any] = {"t": 0.0, "data": []}
_INDEX_CACHE_TTL_SEC = 15.0
# 盯盘 loop 快照推送日志：每 N 次打印一条（冷启动始终打印）；1=每次；环境变量 WATCH_SNAPSHOT_LOG_EVERY
_WATCH_SNAPSHOT_LOG_EVERY = max(1, int(os.environ.get("WATCH_SNAPSHOT_LOG_EVERY", "12")))
_watch_snapshot_push_n = 0


def _log_watch_snapshot_push(message: str, *, force: bool = False) -> None:
    """限频输出「快照已推送」，避免 loop 每 5s 刷屏。"""
    global _watch_snapshot_push_n
    if force:
        print(message)
        return
    _watch_snapshot_push_n += 1
    every = _WATCH_SNAPSHOT_LOG_EVERY
    if every <= 1 or (_watch_snapshot_push_n % every == 0):
        if every > 1:
            print(f"{message}（累计第 {_watch_snapshot_push_n} 次 · 每 {every} 次输出）")
        else:
            print(message)


def _factor1_binding_params() -> dict[str, Any]:
    """策略绑定 · 因子1 参数（与回测 bindings 同源；个股阈值仍以 WATCHLIST 为准）。"""
    try:
        for b in get_strategy_bindings(STRATEGY_ID):
            if b.factor_id == FACTOR_ID and b.enabled:
                return dict(b.params)
    except Exception:
        pass
    return {
        "entry_pct": DEFAULT_PCT,
        "stop_pct": DEFAULT_PCT,
        "prev_entry_mode": "yin_or_small_yang",
        "ban_double_yang": DEFAULT_BAN_DOUBLE_YANG,
        "ban_single_yang": DEFAULT_BAN_SINGLE_YANG,
        "double_yang_combined_min_pct": DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        "double_yang_combined_mode": DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    }


# 兼容旧名
_strategy1_factor1_params = _factor1_binding_params


def _entry_gate_detail(
    prev_o: float | None,
    prev_c: float | None,
    prev2_o: float | None,
    prev2_c: float | None,
    *,
    entry_pct: float,
    prev_entry_mode: str,
    tick: float,
    f1p: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    """返回 (allow_entry, 过门说明, 前日形态)。"""
    p = f1p or _factor1_binding_params()
    prev_shape = "-"
    if prev_o is not None and prev_c is not None and float(prev_o) > 0:
        prev_shape = bar_shape(float(prev_o), float(prev_c), tick=tick)
    if prev_entry_mode == "limit_up_ok":
        return True, "前日涨停·免过门", prev_shape
    allow = entry_filters_ok(
        prev_o,
        prev_c,
        prev2_o,
        prev2_c,
        entry_pct=entry_pct,
        prev_entry_mode=prev_entry_mode,
        tick=tick,
        ban_double_yang=bool(p.get("ban_double_yang", DEFAULT_BAN_DOUBLE_YANG)),
        ban_single_yang=bool(p.get("ban_single_yang", DEFAULT_BAN_SINGLE_YANG)),
        yang_min_pct=float(p.get("yang_min_pct") or 0.0),
        double_yang_second_min_pct=p.get("double_yang_second_min_pct"),
        double_yang_combined_min_pct=p.get(
            "double_yang_combined_min_pct", DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT
        ),
        double_yang_combined_mode=str(
            p.get("double_yang_combined_mode", DEFAULT_DOUBLE_YANG_COMBINED_MODE)
            or DEFAULT_DOUBLE_YANG_COMBINED_MODE
        ),
        single_yang_min_pct=p.get("single_yang_min_pct"),
    )
    if allow:
        if prev_shape == "阴":
            return True, "前日阴线·过门", prev_shape
        if prev_shape == "十字":
            return True, "前日十字·过门", prev_shape
        if prev_shape == "阳":
            return True, "前日小阳·过门", prev_shape
        return True, "过门", prev_shape
    if prev_o is None or prev_c is None:
        return False, "缺前日K线", prev_shape
    if not prev_day_allows_entry(
        float(prev_o),
        float(prev_c),
        prev_small_yang_pct=entry_pct,
        prev_entry_mode=prev_entry_mode,
        tick=tick,
    ):
        if is_yang(float(prev_o), float(prev_c), tick=tick):
            return False, "前日大阳·不过门", prev_shape
        return False, "前日形态·不过门", prev_shape
    if should_block_entry_by_yang(
        prev2_o,
        prev2_c,
        prev_o,
        prev_c,
        tick=tick,
        ban_double_yang=bool(p.get("ban_double_yang", DEFAULT_BAN_DOUBLE_YANG)),
        ban_single_yang=bool(p.get("ban_single_yang", DEFAULT_BAN_SINGLE_YANG)),
        yang_min_pct=float(p.get("yang_min_pct") or 0.0),
        double_yang_second_min_pct=p.get("double_yang_second_min_pct"),
        double_yang_combined_min_pct=p.get(
            "double_yang_combined_min_pct", DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT
        ),
        double_yang_combined_mode=str(
            p.get("double_yang_combined_mode", DEFAULT_DOUBLE_YANG_COMBINED_MODE)
            or DEFAULT_DOUBLE_YANG_COMBINED_MODE
        ),
        single_yang_min_pct=p.get("single_yang_min_pct"),
    ):
        return False, "双阳跨日·禁买", prev_shape
    return False, "禁买", prev_shape




_FACTOR_ROLE_ZH: dict[str, str] = {
    "both": "买卖",
    "entry": "开仓/选股",
    "exit": "退出",
    "filter": "门控",
    "custom": "预警/叠加",
    "universe": "标的池",
}

# 盯盘首页 Tab：仅有实时面板/与当日行情相关的完整策略
WATCH_LIVE_TAB_IDS = frozenset({"strategy1", "strategy3", "strategy8"})

_REGISTRY_KIND_ZH = {
    "watch": "盯盘",
    "production": "完整策略",
    "combo": "因子组合",
    "research": "研究",
}


def _strategy_tab_number(strategy_id: str) -> str:
    sid = str(strategy_id)
    if sid.startswith("strategy") and sid[8:].isdigit():
        return sid[8:]
    return sid


def _strategy_tab_short_name(name: str) -> str:
    text = str(name).strip()
    if "·" in text:
        return text.split("·", 1)[1].strip()
    return text


def _strategy_tab_label(strategy_id: str, name: str) -> str:
    return f"策略{_strategy_tab_number(strategy_id)}-{_strategy_tab_short_name(name)}"


def _strategy_registry_kind(strategy_id: str, meta: Mapping[str, Any] | None) -> str:
    """Web 策略栏分区：watch / production / combo（因子组合）/ research。"""
    sid = str(strategy_id)
    m = dict(meta or {})
    if m.get("web_hide"):
        return "hidden"
    if sid in WATCH_LIVE_TAB_IDS:
        return "watch"
    if sid in ("strategy5", "strategy6") or m.get("mode") == "weekly_equal_weight_hold":
        return "combo"
    if m.get("mode") in (
        "emotion_gate",
        "gap_reclaim",
        "ld_next_open",
        "lu_next_gap",
    ) or sid == "strategy12":
        return "combo"
    if sid == "strategy9" or m.get("mode") == "market_emotion":
        return "research"
    return "production"


def _load_watch_strategy_tabs() -> list[dict[str, Any]]:
    """从 strategy 注册表加载盯盘页策略 Tab（因子绑定 + 名称）。"""
    from strategy.core.factor_registry import get_factor
    from strategy.core.strategy_registry import list_strategy_specs

    tabs: list[dict[str, Any]] = []
    for spec in list_strategy_specs():
        factors: list[dict[str, str]] = []
        for b in spec.factor_bindings:
            if not b.enabled:
                continue
            try:
                fspec = get_factor(b.factor_id)
                fname = str(fspec.name)
                fdesc = str(fspec.description or "").strip()
            except KeyError:
                fname = str(b.factor_id)
                fdesc = ""
            factors.append(
                {
                    "id": str(b.factor_id),
                    "name": fname,
                    "role": _FACTOR_ROLE_ZH.get(str(b.role), str(b.role)),
                    "filter_desc": str(b.filter_desc or "").strip(),
                    "description": fdesc,
                }
            )
        kind = _strategy_registry_kind(spec.id, spec.meta)
        if kind == "hidden":
            continue
        tabs.append(
            {
                "id": spec.id,
                "label": _strategy_tab_label(spec.id, spec.name),
                "name": spec.name,
                "description": str(spec.description or "").strip(),
                "aliases": [str(a) for a in spec.aliases],
                "implemented": bool(spec.implemented),
                "is_watch_default": spec.id == STRATEGY_ID,
                "watch_tab": spec.id in WATCH_LIVE_TAB_IDS,
                "registry_kind": kind,
                "registry_kind_label": _REGISTRY_KIND_ZH.get(kind, "策略"),
                "factors": factors,
            }
        )
        if spec.id == "strategy3":
            from strategy3_watch import load_backtest_summary

            tabs[-1]["backtest"] = load_backtest_summary()
            tabs[-1]["reportPath"] = "backtest/strategy3_first_board/REPORT.md"
        if spec.id == "strategy8":
            from strategy8_watch import load_backtest_summary as load_s8_summary

            tabs[-1]["backtest"] = load_s8_summary()
            tabs[-1]["reportPath"] = "backtest/strategy8_theme_linkage/REPORT.md"
        if spec.id == "strategy12":
            import json as _json
            from pathlib import Path as _Path

            s12 = _Path(__file__).resolve().parents[1] / "backtest" / "strategy12_emotion_gate" / "summary.json"
            if s12.is_file():
                try:
                    tabs[-1]["backtest"] = _json.loads(s12.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    tabs[-1]["backtest"] = []
            tabs[-1]["reportPath"] = "backtest/strategy12_emotion_gate/REPORT.md"
        from strategy_picks_loader import load_strategy_picks

        tabs[-1]["picks"] = load_strategy_picks(spec.id)
    tabs.sort(key=lambda t: int(_strategy_tab_number(str(t["id"]))))
    return tabs


def _json_safe_meta(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in (meta or {}).items():
        if isinstance(val, (str, int, float, bool)) or val is None:
            out[str(key)] = val
        elif isinstance(val, (list, tuple)):
            out[str(key)] = [
                x for x in val if isinstance(x, (str, int, float, bool))
            ]
    return out


def _load_watch_factors_api() -> dict[str, Any]:
    """从 factor 注册表加载因子说明（供 watch-ui /api/factors）。"""
    from strategy.core.factor_registry import list_factors
    from strategy.core.strategy_registry import list_strategy_specs

    used_by: dict[str, list[dict[str, str]]] = {}
    for spec in list_strategy_specs():
        for b in spec.factor_bindings:
            if not b.enabled:
                continue
            used_by.setdefault(str(b.factor_id), []).append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "label": _strategy_tab_label(spec.id, spec.name),
                    "role": _FACTOR_ROLE_ZH.get(str(b.role), str(b.role)),
                    "filter_desc": str(b.filter_desc or "").strip(),
                    "registry_kind": _strategy_registry_kind(spec.id, spec.meta),
                }
            )

    from strategy.factors.categories import category_label, category_of, list_category_catalog

    catalog = list_category_catalog()
    rows: list[dict[str, Any]] = []
    for fspec in list_factors():
        bindings = used_by.get(str(fspec.id), [])
        bindings.sort(key=lambda s: int(_strategy_tab_number(str(s["id"])) or 0) if str(s["id"]).startswith("strategy") else 99)
        cat = category_of(str(fspec.id), fspec.meta)
        rows.append(
            {
                "id": fspec.id,
                "name": fspec.name,
                "description": str(fspec.description or "").strip(),
                "rules_text": str(fspec.rules_text or "").strip(),
                "implemented": bool(fspec.implemented),
                "meta": _json_safe_meta(fspec.meta),
                "category": cat,
                "category_label": category_label(cat),
                "used_by": [b for b in bindings if b.get("registry_kind") != "hidden"],
            }
        )
    return {"categories": catalog, "factors": rows}


def _get_factors_api_cache() -> dict[str, Any]:
    """每次现算：开发时改因子注册不必重启才能看见列表。"""
    return _load_watch_factors_api()




def _get_strategies_api_cache() -> list[dict[str, Any]]:
    """每次现算：开发时改策略注册不必重启才能看见列表。"""
    return _load_watch_strategy_tabs()


def _parse_api_query(path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlparse(path)
    return parsed.path, parse_qs(parsed.query)


def _api_int(qs: dict[str, list[str]], key: str, default: int) -> int:
    raw = (qs.get(key) or [""])[0]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _api_bool(qs: dict[str, list[str]], key: str) -> bool:
    raw = str((qs.get(key) or [""])[0]).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _handle_sectors_api(path: str) -> tuple[int, dict[str, Any]]:
    from sectors.api import (
        get_concept_detail,
        get_concept_leader_scores,
        get_concept_members,
        get_rotation_payload,
        get_status,
    )
    from sectors_watch import set_focus_concept

    api_path, qs = _parse_api_query(path)
    if api_path == "/api/sectors/status":
        return 200, get_status()
    if api_path == "/api/sectors/focus":
        raw = (qs.get("concept") or [""])[0]
        concept = unquote(str(raw).strip()) or None
        set_focus_concept(concept)
        return 200, {"ok": True, "focusConcept": concept}
    if api_path == "/api/sectors/members":
        name = unquote(str((qs.get("name") or qs.get("concept") or [""])[0]).strip())
        limit = max(20, min(_api_int(qs, "limit", 80), 200))
        if not name:
            return 400, {"error": "缺少 name"}
        try:
            data = get_concept_members(name, limit=limit)
            if data.get("error") and not data.get("members"):
                return 404, data
            return 200, data
        except Exception as e:
            return 500, {"error": str(e)}
    if api_path == "/api/sectors/rotation":
        days = max(5, min(_api_int(qs, "days", 20), 60))
        top_n = max(5, min(_api_int(qs, "top_n", 10), 20))
        refresh = _api_bool(qs, "refresh")
        try:
            return 200, get_rotation_payload(days=days, top_n=top_n, refresh=refresh)
        except Exception as e:
            return 500, {"error": str(e)}
    if api_path.startswith("/api/sectors/concept/"):
        tail = api_path.split("/api/sectors/concept/", 1)[1]
        if "/leaders" in tail:
            name = unquote(tail.split("/leaders", 1)[0])
            start = (qs.get("start") or ["2025-01-01"])[0]
            top_n = max(1, min(_api_int(qs, "top_n", 5), 10))
            refresh = _api_bool(qs, "refresh")
            try:
                data = get_concept_leader_scores(
                    name, start=str(start), refresh=refresh, top_n=top_n
                )
                if data.get("error") and not data.get("leaders"):
                    return 404, data
                return 200, data
            except Exception as e:
                return 500, {"error": str(e)}
        name = unquote(tail)
        months = max(3, min(_api_int(qs, "months", 6), 12))
        refresh = _api_bool(qs, "refresh")
        try:
            data = get_concept_detail(name, months=months, refresh=refresh)
            if data.get("error"):
                return 404, data
            return 200, data
        except Exception as e:
            return 500, {"error": str(e)}
    return 404, {"error": "not found"}


def _build_watch_account_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """账户合计（JSON 快照 / CLI 共用口径）。"""
    total_pnl = 0.0
    total_day_pnl = 0.0
    total_mv = 0.0
    total_mv_no_cost = 0.0
    total_cost = 0.0
    total_day_base = 0.0
    settled_pnl = 0.0
    settled_day = 0.0
    settled_n = 0
    has_pos = False
    has_day = False
    for r in rows:
        qty = int(r.get("持仓") or 0)
        realized = bool(r.get("已实现"))
        if r.get("浮盈") is not None and (qty > 0 or realized):
            total_pnl += float(r["浮盈"])
            has_pos = True
        if r.get("当日盈亏") is not None and (qty > 0 or realized):
            total_day_pnl += float(r["当日盈亏"])
            has_day = True
            db = r.get("当日基数")
            if db is not None and float(db) > 0:
                total_day_base += float(db)
            else:
                dpct = r.get("当日盈亏%")
                if dpct is not None and abs(float(dpct)) > 1e-12:
                    total_day_base += float(r["当日盈亏"]) / (float(dpct) / 100.0)
                elif r.get("市值") is not None and not realized:
                    total_day_base += float(r["市值"]) - float(r["当日盈亏"])
        if realized:
            settled_n += 1
            if r.get("浮盈") is not None:
                settled_pnl += float(r["浮盈"])
            if r.get("当日盈亏") is not None:
                settled_day += float(r["当日盈亏"])
            if r.get("成本") is not None and r.get("卖出数量"):
                total_cost += float(r["成本"]) * int(r["卖出数量"])
        if r.get("市值") is not None and qty > 0:
            mv = float(r["市值"])
            total_mv += mv
            if r.get("成本额") is None:
                total_mv_no_cost += mv
        if r.get("成本额") is not None and qty > 0:
            total_cost += float(r["成本额"])
    total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else None
    total_day_pct = (
        (total_day_pnl / total_day_base * 100.0) if has_day and total_day_base > 0 else None
    )
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    available_cash = _available_cash(rows, holdings_meta)
    session_for_open = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        str(pd.Timestamp.now().date()),
    )
    _ensure_account_open_session(
        holdings_meta,
        session=session_for_open,
        account_total=account_total,
    )
    holdings_meta = load_holdings()
    account_open = _account_total_open(holdings_meta)
    if account_total is not None and account_open is not None:
        total_pnl = round(float(account_total) - float(account_open), 2)
        has_pos = True
        total_pnl_pct = round(total_pnl / float(account_open) * 100.0, 2)
    if has_day and account_open is not None and account_open > 0:
        total_day_pct = round(total_day_pnl / float(account_open) * 100.0, 2)
    position_pct = (
        round(total_mv / account_total * 100.0, 1)
        if account_total and account_total > 0 and total_mv > 0
        else None
    )
    today_opened = _today_opened_cost(rows, session_for_open)
    f2_raw = (
        holdings_meta.get("factor2")
        if isinstance(holdings_meta.get("factor2"), dict)
        else None
    )
    return {
        "totalPnl": total_pnl if has_pos else None,
        "totalPnlPct": total_pnl_pct,
        "dayPnl": total_day_pnl if has_day else None,
        "dayPnlPct": total_day_pct,
        "accountTotal": account_total,
        "accountOpen": account_open,
        "availableCash": available_cash,
        "positionPct": position_pct,
        "marketValue": total_mv if total_mv > 0 else None,
        "cost": total_cost if total_cost > 0 else None,
        "marketValueNoCost": total_mv_no_cost if total_mv_no_cost > 0 else None,
        "todayOpened": today_opened if today_opened > 0 else None,
        "settledCount": settled_n,
        "settledPnl": settled_pnl if settled_n > 0 else None,
        "settledDayPnl": settled_day if settled_n > 0 else None,
        "factor2Summary": format_factor2_summary(f2_raw),
    }


def _snapshot_business_digest(snapshot: dict[str, Any]) -> str:
    """快照业务指纹（不含 clock/ts，用于去重写盘/WS）。"""
    payload = {
        "account": snapshot.get("account"),
        "indices": snapshot.get("indices"),
        "holdings": snapshot.get("holdings"),
        "strategy1": snapshot.get("strategy1"),
        "strategy3": snapshot.get("strategy3"),
        "strategy8": snapshot.get("strategy8"),
        "phaseKey": snapshot.get("phaseKey"),
        "strategy": snapshot.get("strategy"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def publish_watch_snapshot(
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]] | None = None,
    *,
    refresh_sec: int = 5,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[Path, bool]:
    """推送 JSON 快照（WebSocket + holdings_watch.json），盯盘模式不写 HTML。

    返回 (路径, 是否已写盘并广播)；业务数据未变时跳过 I/O/WS。
    """
    global _last_watch_snapshot, _last_snapshot_digest
    indices = indices or []
    clock_now = _now()
    phase_key = market_phase()
    phase_label = market_phase_label(phase_key)
    account = _build_watch_account_summary(rows)
    session_today = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        "",
    )
    from strategy3_watch import build_strategy3_payload
    from strategy8_watch import build_strategy8_payload
    from sectors_watch import build_sectors_live_payload

    def _batch_quote(sinas: list[str]) -> dict[str, dict[str, Any]]:
        batch = fetch_sina_batch([s.lower() for s in sinas])
        out: dict[str, dict[str, Any]] = {}
        for s in sinas:
            spot = batch.get(s.lower())
            if spot:
                out[s.lower()] = _quote_from_sina_spot(spot)
        return out

    try:
        strategy3 = build_strategy3_payload(
            session=session_today or None,
            get_quote=get_quote,
            batch_quote=_batch_quote,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 策略三快照失败（继续盯盘）: {e}")
        strategy3 = {"error": str(e), "rows": []}
    try:
        strategy8 = build_strategy8_payload(
            session=session_today or None,
            get_quote=get_quote,
            batch_quote=_batch_quote,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 策略八快照失败（继续盯盘）: {e}")
        strategy8 = {"error": str(e), "rows": []}
    try:
        sectors = build_sectors_live_payload()
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 板块快照失败（继续盯盘）: {e}")
        sectors = {"error": str(e), "rows": []}
    snapshot = build_watch_snapshot(
        rows=rows,
        indices=indices,
        account=account,
        meta={
            "clock": clock_now,
            "phase": phase_label,
            "phaseKey": phase_key,
            "strategyId": STRATEGY_ID,
            "strategyName": STRATEGY_NAME,
            "factorsLabel": _STRATEGY_FACTORS_LABEL,
        },
        strategies=[t for t in _get_strategies_api_cache() if t.get("watch_tab")],
        strategy3=strategy3,
        strategy8=strategy8,
        sectors=sectors,
        refresh_sec=refresh_sec,
    )
    digest = _snapshot_business_digest(snapshot)
    if digest == _last_snapshot_digest and _last_watch_snapshot is not None:
        snap = dict(_last_watch_snapshot)
        snap["clock"] = clock_now
        snap["updatedAt"] = clock_now
        snap["ts"] = int(datetime.now().timestamp() * 1000)
        snap["sectors"] = sectors
        _last_watch_snapshot = snap
        body = json.dumps(snap, ensure_ascii=False)
        hub = _ws_hub
        if hub is not None:
            try:
                hub.broadcast_text(body)
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] WS 广播失败: {e}")
        return WATCH_META_FILE, False

    _last_snapshot_digest = digest
    _last_watch_snapshot = snapshot
    body = json.dumps(snapshot, ensure_ascii=False)
    _atomic_write_text(WATCH_META_FILE, body, encoding="utf-8")
    hub = _ws_hub
    if hub is not None:
        try:
            hub.broadcast_text(body)
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] WS 广播失败: {e}")
    return WATCH_META_FILE, True


# 兼容旧名
_strategy1_factor1_params = _factor1_binding_params


def fetch_indices_cached(*, ttl_sec: float = _INDEX_CACHE_TTL_SEC) -> list[dict[str, Any]]:
    """盯盘高频刷新时缓存大盘指数，避免每次重拉拖慢推送。"""
    now = time.monotonic()
    cached = _INDEX_CACHE.get("data") or []
    if cached and (now - float(_INDEX_CACHE.get("t") or 0.0)) < float(ttl_sec):
        return list(cached)
    data = fetch_indices()
    _INDEX_CACHE["t"] = now
    _INDEX_CACHE["data"] = data
    return data


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")




def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """先写临时文件再替换，避免浏览器读到半截 HTML 导致布局闪乱。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _watch_pct(item: dict[str, Any]) -> float:
    """入场阈值（兼容旧 pct 字段）。"""
    if item.get("entry_pct") is not None:
        return float(item["entry_pct"])
    return float(item.get("pct", DEFAULT_PCT))


def _watch_stop_pct(item: dict[str, Any]) -> float:
    if item.get("stop_pct") is not None:
        return float(item["stop_pct"])
    return _watch_pct(item)


def _watch_tick(item: dict[str, Any]) -> float:
    return float(item.get("tick", TICK_SIZE))


def _watch_limit_down_pct(item: dict[str, Any]) -> float:
    return float(item.get("limit_down_pct", 0.10))


def _px_digits(tick: float) -> int:
    """按最小变动价位决定价格小数位（ETF 0.001 → 3 位）。"""
    if tick <= 0:
        return 2
    if tick >= 1:
        return 0
    return max(0, -int(round(math.log10(tick))))


def _quote_from_sina_spot(spot: dict[str, Any]) -> dict[str, Any]:
    """新浪快照 → collect_rows 可用的 quote dict（无分钟 K）。"""
    prev = spot.get("prev_close")
    last = float(spot["last"])
    day_chg = None
    if prev is not None and float(prev) > 0:
        day_chg = (last / float(prev) - 1.0) * 100.0
    return {
        "session": str(spot.get("session") or pd.Timestamp.now().date()),
        "open": float(spot["open"]),
        "high": float(spot["high"]),
        "low": float(spot["low"]),
        "last": last,
        "prev_close": float(prev) if prev is not None else None,
        "day_chg_pct": day_chg,
        "last_ts": str(spot.get("last_ts") or _now()),
        "name": str(spot.get("name") or "").strip(),
        "_day_bars": pd.DataFrame(),
    }


def _reseed_sina_batch(
    feed: QuoteFeedManager,
    watchlist: list[dict[str, Any]] | None = None,
) -> int:
    """冷启动快路径：新浪批量快照 seed（~2s），先让页面可用。"""
    items = watchlist if watchlist is not None else effective_watchlist()
    sinas = [str(w["sina"]).lower() for w in items]
    batch = fetch_sina_batch(sinas)
    n = 0
    for w in items:
        spot = batch.get(str(w["sina"]).lower())
        if not spot:
            continue
        feed.seed(w["sina"], _quote_from_sina_spot(spot))
        n += 1
    return n


def fetch_today_quote_live(sina: str) -> dict[str, Any]:
    """盯盘专用：仅新浪实时快照，不请求东财历史分钟 K。"""
    spot = fetch_sina_spot(sina)
    if spot is None:
        raise RuntimeError(f"无实时行情: {sina}")
    return _quote_from_sina_spot(spot)


def _reseed_live_batch(
    feed: QuoteFeedManager,
    watchlist: list[dict[str, Any]] | None = None,
) -> int:
    """刷新当日实时快照（新浪批量）。"""
    return _reseed_sina_batch(feed, watchlist)


def _daily_cache_warm(watchlist: list[dict[str, Any]] | None = None) -> None:
    """并行预热日线缓存，避免首屏 collect_rows 串行等 IO。"""
    items = watchlist if watchlist is not None else effective_watchlist()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda w: _watch_daily(w["sina"]), items))


# 日线缓存：当日只拉一次，供前日过滤与最近因子触发
_DAILY_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}


def _watch_daily(sina: str, *, lookback_days: int | None = None) -> pd.DataFrame:
    """日线缓存；因子4开启时回溯加长以覆盖 roc_ma60。"""
    days = int(lookback_days) if lookback_days is not None else (280 if USE_FACTOR4 else 90)
    today = str(pd.Timestamp.now().date())
    cached = _DAILY_CACHE.get(sina)
    if cached and cached[0] == today and cached[1] is not None and not cached[1].empty:
        return cached[1]
    start = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")
    try:
        df = fetch_daily(sina, start, end)
    except Exception:
        df = pd.DataFrame()
    _DAILY_CACHE[sina] = (today, df)
    return df


def _daily_frame_sig(daily: pd.DataFrame) -> str:
    if daily is None or daily.empty:
        return "empty"
    last = daily.iloc[-1]
    return f"{len(daily)}:{last.get('date', '')}"


def _replay_last_factor_triggers_cached(
    sina: str,
    daily: pd.DataFrame,
    *,
    entry_pct: float,
    stop_pct: float,
    tick: float,
    prev_entry_mode: str,
    limit_down_pct: float,
) -> dict[str, Any]:
    """日线回放缓存：同一交易日、同一日线签名与阈值参数不重复算。"""
    today = str(pd.Timestamp.now().date())
    key = (
        str(sina).lower(),
        today,
        _daily_frame_sig(daily),
        float(entry_pct),
        float(stop_pct),
        float(tick),
        str(prev_entry_mode),
        float(limit_down_pct),
    )
    hit = _REPLAY_CACHE.get(key)
    if hit is not None:
        return hit
    out = replay_last_factor_triggers(
        daily,
        entry_pct=entry_pct,
        stop_pct=stop_pct,
        tick=tick,
        prev_entry_mode=prev_entry_mode,
        limit_down_pct=limit_down_pct,
    )
    if len(_REPLAY_CACHE) > 512:
        _REPLAY_CACHE.clear()
    _REPLAY_CACHE[key] = out
    return out


def _prev_bars_from_daily(
    daily: pd.DataFrame, session: str
) -> tuple[float | None, float | None, float | None, float | None]:
    """返回 (prev_open, prev_close, prev2_open, prev2_close)。"""
    if daily is None or daily.empty:
        return None, None, None, None
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
    d = d.dropna(subset=["open", "close"]).sort_values("date")
    sess = pd.Timestamp(session).normalize()
    hist = d[d["date"].dt.normalize() < sess]
    if hist.empty:
        return None, None, None, None
    prev = hist.iloc[-1]
    prev2 = hist.iloc[-2] if len(hist) >= 2 else None
    return (
        float(prev["open"]),
        float(prev["close"]),
        float(prev2["open"]) if prev2 is not None else None,
        float(prev2["close"]) if prev2 is not None else None,
    )


def _fill_dual_factor_dist(
    row: dict[str, Any],
    *,
    last_px: float,
    px_digits: int,
    triggered_side: str,
    triggered_px: float | None,
    next_side: str,
    next_px: float | None,
) -> None:
    """写入距已触发 / 距未触发（现价相对因子价）。

    买入侧：现价相对因子涨跌（上为正）；
    卖出侧：取反，表示还需下跌多少才到卖点（现价高于止损时为负）。
    """

    def _one(px: float | None, side: str) -> tuple[float | None, float | None]:
        if px is None or float(px) <= 0:
            return None, None
        dpx = round(float(last_px) - float(px), px_digits)
        dpct = round((float(last_px) / float(px) - 1.0) * 100.0, 2)
        if side == "卖出":
            dpx = round(-dpx, px_digits)
            dpct = round(-dpct, 2)
        return dpx, dpct

    t_px = None if triggered_px is None else round(float(triggered_px), px_digits)
    n_px = None if next_px is None else round(float(next_px), px_digits)
    d_t_px, d_t_pct = _one(t_px, triggered_side)
    d_n_px, d_n_pct = _one(n_px, next_side)
    row["已触发因子侧"] = triggered_side
    row["已触发因子价"] = t_px
    row["未触发因子侧"] = next_side
    row["未触发因子价"] = n_px
    row["距已触发价差"] = d_t_px
    row["距已触发%"] = d_t_pct
    row["距未触发价差"] = d_n_px
    row["距未触发%"] = d_n_pct
    row["距因子价差"] = d_n_px
    row["距因子%"] = d_n_pct


def _factor_memory(code: str) -> dict[str, Any]:
    data = load_holdings()
    mem = data.get("factor_memory") or {}
    rec = mem.get(_code_key(code)) or {}
    return rec if isinstance(rec, dict) else {}


def remember_factor_trigger(
    code: str,
    *,
    side: str,
    px: float,
    session: str,
    force: bool = False,
) -> None:
    """因子触发后固化触发价，供双距字段后续自动切换。"""
    if px is None or float(px) <= 0:
        return
    key = _code_key(code)
    data = load_holdings()
    mem = data.setdefault("factor_memory", {})
    rec = mem.setdefault(key, {})
    px_r = round(float(px), 4)
    side_l = str(side).lower()
    sess = str(session)[:10]
    if side_l in ("buy", "买入"):
        cur_d = str(rec.get("last_buy_factor_date") or "")[:10]
        cur_px = rec.get("last_buy_factor_px")
        # 同日同价跳过；非 force 时同日已有记录不覆盖（防成交价盖掉因子价）
        if cur_d == sess and cur_px is not None:
            if (not force) or abs(float(cur_px) - px_r) <= 1e-9:
                return
        rec["last_buy_factor_px"] = px_r
        rec["last_buy_factor_date"] = sess
    elif side_l in ("sell", "卖出", "stop", REASON_STOP):
        cur_d = str(rec.get("last_sell_factor_date") or "")[:10]
        cur_px = rec.get("last_sell_factor_px")
        if cur_d == sess and cur_px is not None:
            if (not force) or abs(float(cur_px) - px_r) <= 1e-9:
                return
        rec["last_sell_factor_px"] = px_r
        rec["last_sell_factor_date"] = sess
    else:
        return
    save_holdings(data)


def _apply_trigger_date_fields(
    row: dict[str, Any],
    *,
    sig: dict[str, Any],
    session: str,
    last_px: float,
    px_digits: int,
    buy_time: str | None,
    qty: int,
    replay: dict[str, Any],
    code: str | None = None,
    allow_entry: bool = True,
) -> None:
    """因子触发写最近触发日(M/D)；触发后双距自动翻转到「已触发/未触发」下一组。"""
    today_md = format_trigger_md(session)
    pos_st = str(sig.get("持仓状态") or "")
    hit_txt = str(sig.get("因子触发") or "")
    buy_lv = row.get("买点")
    stop_lv = row.get("止损")
    # 前日大阳等过滤未过时，今日买点仅展示、绝不算「已触发」
    hit_buy = bool(allow_entry) and (
        bool(sig.get("hit_buy")) or str(row.get("已触买") or "") == "是"
    )
    hit_stop = bool(sig.get("hit_stop")) or str(row.get("已触止损") or "") == "是"
    realized_px = row.get("成交价")
    sold_today = (
        realized_px is not None
        and float(realized_px) > 0
        and qty <= 0
        and str(row.get("预警") or "") in EXIT_REASONS
    )
    mem = _factor_memory(code) if code else {}
    # 日线回放仍处「买入未平」：本地未登记仓位时，双距按策略持有展示（勿用更早的卖出因子）
    paper_holding = bool(replay.get("holding")) and qty <= 0
    row["策略回放持有"] = bool(paper_holding)
    # 当日已止损/卖出：禁止再算买入侧（当天卖、当天不买）
    stop_exit_today = bool(
        sold_today
        or (paper_holding and hit_stop)
        or (qty > 0 and hit_stop)
    )
    row["当日禁买"] = bool(stop_exit_today)

    def _last_buy_px() -> tuple[float | None, str]:
        buy_day = str(buy_time or "")[:10]
        sess_day = str(session)[:10]
        mem_buy = mem.get("last_buy_factor_px")
        mem_buy_day = str(mem.get("last_buy_factor_date") or "")[:10]
        hist_buy = replay.get("last_buy_px")
        hist_buy_day = str(replay.get("last_buy_date") or "")[:10]
        if mem_buy is not None and buy_day and mem_buy_day == buy_day:
            return float(mem_buy), buy_day or mem_buy_day
        if hist_buy is not None:
            return float(hist_buy), hist_buy_day or buy_day
        if mem_buy is not None and (not buy_day) and mem_buy_day != sess_day:
            return float(mem_buy), mem_buy_day
        if buy_day == sess_day and buy_lv is not None:
            return float(buy_lv), buy_day
        return None, buy_day or hist_buy_day or ""

    # 触发瞬间
    just_sold = bool(
        stop_exit_today or (pos_st == "待卖出" and hit_txt == "已触发")
    )
    just_bought = bool(
        allow_entry
        and (not stop_exit_today)
        and (hit_buy or (pos_st == "待买入" and hit_txt == "已触发"))
    )

    if just_sold and (qty > 0 or sold_today or paper_holding or pos_st == "待卖出"):
        # 当日止损：已触发仍保留「上次买入价」；未触发=今日止损（已打到），不挂今日买点
        trig_side, next_side = "买入", "卖出"
        buy_px, buy_day = _last_buy_px()
        trig_px = buy_px
        next_px = float(stop_lv) if stop_lv is not None else None
        sell_mem_px = (
            float(realized_px)
            if realized_px is not None and float(realized_px) > 0
            else (float(stop_lv) if stop_lv is not None else None)
        )
        if code and sell_mem_px is not None and (qty > 0 or sold_today):
            # 实仓结算才写入卖出记忆；纸面仅展示
            remember_factor_trigger(code, side="sell", px=sell_mem_px, session=session)
        if qty > 0 and code and buy_px is not None:
            remember_factor_trigger(
                code, side="buy", px=buy_px, session=buy_day or session, force=True
            )
    elif just_bought and qty <= 0 and not paper_holding:
        trig_side, next_side = "买入", "卖出"
        trig_px = float(buy_lv) if buy_lv is not None else None
        next_px = float(stop_lv) if stop_lv is not None else None
        if code and trig_px is not None:
            remember_factor_trigger(code, side="buy", px=trig_px, session=session)
    elif qty > 0 or paper_holding:
        # 持有中 / 策略回放持有：已触发=买入因子；未触发=今日止损
        trig_side, next_side = "买入", "卖出"
        trig_px, buy_day = _last_buy_px()
        next_px = float(stop_lv) if stop_lv is not None else None
        if qty > 0 and code and trig_px is not None:
            hist_buy_day = str(replay.get("last_buy_date") or "")[:10]
            seed_sess = buy_day or hist_buy_day or str(session)[:10]
            mem_buy = mem.get("last_buy_factor_px")
            mem_buy_day = str(mem.get("last_buy_factor_date") or "")[:10]
            need_fix = (
                mem_buy is None
                or (buy_day and mem_buy_day != buy_day)
                or abs(float(mem_buy) - float(trig_px)) > 1e-9
            )
            if need_fix:
                remember_factor_trigger(
                    code, side="buy", px=trig_px, session=seed_sess, force=True
                )
    else:
        # 真正空仓且非当日止损：已触发=上次卖出；未触发=今日买点
        # 若当日刚止损过（sold_today 已在上方处理）；此处仅历史空仓
        trig_side, next_side = "卖出", "买入"
        mem_sell = mem.get("last_sell_factor_px")
        hist_sell = replay.get("last_sell_px")
        if mem_sell is not None:
            trig_px = float(mem_sell)
        elif hist_sell is not None:
            trig_px = float(hist_sell)
        elif stop_lv is not None:
            trig_px = float(stop_lv)
        else:
            trig_px = None
        next_px = float(buy_lv) if buy_lv is not None else None

    # 当日禁买：未触发侧若是买入则清空（不展示下一买点）
    if stop_exit_today and next_side == "买入":
        next_side = "卖出"
        next_px = float(stop_lv) if stop_lv is not None else next_px
        if trig_side != "买入" or trig_px is None:
            buy_px, _ = _last_buy_px()
            if buy_px is not None:
                trig_side, trig_px = "买入", buy_px

    _fill_dual_factor_dist(
        row,
        last_px=last_px,
        px_digits=px_digits,
        triggered_side=trig_side,
        triggered_px=trig_px,
        next_side=next_side,
        next_px=next_px,
    )

    # 盘中预警：已触发/接近 + 今日日期（当日禁买不再进待买入文案）
    if (
        pos_st in ("待买入", "待卖出")
        and hit_txt in ("已触发", "接近")
        and not (stop_exit_today and pos_st == "待买入")
    ):
        if hit_txt == "已触发" and today_md:
            row["因子触发"] = f"已触发 {today_md}"
        else:
            row["因子触发"] = hit_txt
        return

    # 有仓 / 策略回放持有 / 当日止损后：展示买入日，止损日单独标注
    if qty > 0 or paper_holding or stop_exit_today:
        md = (
            format_trigger_md(buy_time)
            or format_trigger_md(mem.get("last_buy_factor_date"))
            or format_trigger_md(replay.get("last_buy_date"))
        )
        if stop_exit_today and today_md:
            row["因子触发"] = f"策略止损 {today_md}"
            if str(row.get("预警") or "") in ("", "-", "空仓", "待买入"):
                row["预警"] = (
                    "今日已止损·当日不买"
                    if sold_today
                    else "策略持有·今日触止损·当日不买"
                )
            # 强制不挂买单
            row["建议挂单"] = None
            row["近买点"] = False
            if str(row.get("持仓状态") or "") == "待买入":
                row["持仓状态"] = "空仓"
            if str(row.get("因子侧") or "") == "买入":
                row["因子侧"] = "空仓"
        elif hit_txt == "未触发" and md:
            row["因子触发"] = md
        elif hit_txt == "不可用" and md:
            row["因子触发"] = f"不可用 {md}"
        elif md:
            row["因子触发"] = md
        return

    # 空仓：最近一次卖出因子日
    last_d = (
        mem.get("last_sell_factor_date")
        or replay.get("last_sell_date")
        or replay.get("last_trigger_date")
    )
    md = format_trigger_md(last_d)
    if md:
        row["因子触发"] = md
    else:
        row["因子触发"] = hit_txt or "未触发"



def _holdings_file_mtime() -> float:
    try:
        return HOLDINGS_FILE.stat().st_mtime if HOLDINGS_FILE.exists() else 0.0
    except OSError:
        return 0.0


def load_holdings() -> dict[str, Any]:
    mtime = _holdings_file_mtime()
    cached = _HOLDINGS_CACHE.get("data")
    if cached is not None and float(_HOLDINGS_CACHE.get("mtime") or 0.0) >= mtime:
        return cached
    if not HOLDINGS_FILE.exists():
        data = {
            "updated_at": None,
            "account_total": None,
            "account_cash": None,
            "positions": {
                w["code"]: _empty_position(w)
                for w in effective_watchlist()
            },
            "realized_today": {},
        }
        save_holdings(data)
        return data
    with HOLDINGS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    positions = data.setdefault("positions", {})
    for w in effective_watchlist():
        positions.setdefault(w["code"], _empty_position(w))
    data.setdefault("realized_today", {})
    data.setdefault("account_total", None)
    data.setdefault("account_cash", None)
    data.setdefault("account_total_open", None)
    data.setdefault("account_total_open_session", None)
    data.setdefault("alert_sticky", {})
    _HOLDINGS_CACHE["data"] = data
    _HOLDINGS_CACHE["mtime"] = _holdings_file_mtime()
    return data


def _account_total_open(data: dict[str, Any] | None = None) -> float | None:
    data = data if data is not None else load_holdings()
    return _as_money(data.get("account_total_open"))


def _ensure_account_open_session(
    data: dict[str, Any],
    *,
    session: str,
    account_total: float | None,
) -> None:
    """跨日或首次：锁定日初总资产，供合计/当日盈亏%分母。"""
    open_session = str(data.get("account_total_open_session") or "")
    if open_session == session and _account_total_open(data) is not None:
        return
    if account_total is None or account_total <= 0:
        return
    data["account_total_open"] = round(float(account_total), 2)
    data["account_total_open_session"] = session
    save_holdings(data)


def _as_money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _alert_sticky_map(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data if data is not None else load_holdings()
    raw = data.get("alert_sticky")
    return raw if isinstance(raw, dict) else {}


def _save_alert_sticky(session: str, sticky: dict[str, Any]) -> None:
    data = load_holdings()
    # 仅保留当日，避免跨日绿底粘住
    kept = {
        k: v
        for k, v in sticky.items()
        if isinstance(v, dict) and str(v.get("session") or "") == session
    }
    data["alert_sticky"] = kept
    save_holdings(data)


def _stabilize_sell_warn(
    *,
    code: str,
    session: str,
    sig: dict[str, Any],
    open_px: float,
    last_px: float,
    stop_px: float,
    vs_open_pts: float,
    stop_lvl: float,
    near_points: float = NEAR_FACTOR_PCT,
    sticky: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """绿底防抖：止损预警短时波动时避免30秒刷新闪没。"""
    sticky = sticky if sticky is not None else _alert_sticky_map()
    prev = sticky.get(code) if isinstance(sticky.get(code), dict) else None
    if prev and str(prev.get("session") or "") != session:
        prev = None

    bg = str(sig.get("bg_class") or "")
    alert = str(sig.get("alert") or "")

    if bg == "warn-sell":
        sticky[code] = {
            "session": session,
            "bg_class": "warn-sell",
            "alert": alert,
            "pending_sell": True,
            "建议挂单": sig.get("建议挂单"),
            "挂单说明": sig.get("挂单说明"),
            "near_stop": bool(sig.get("near_stop")),
        }
        return sig

    # 当前已非卖出预警：若仍处于近止损缓冲带，则保持上一帧绿底
    if prev and prev.get("bg_class") == "warn-sell":
        keep = False
        prev_alert = str(prev.get("alert") or "")
        # 将止损：距止损因子价仍在 near+0.5% 内则保持
        if "将止损" in prev_alert or prev.get("near_stop"):
            if stop_px > 0:
                dist_pct = abs(float(last_px) / float(stop_px) - 1.0) * 100.0
                if dist_pct <= (near_points + 0.5) + 1e-12:
                    keep = True
        # 已触止损：价格仍在止损价下方或附近则保持
        elif "止损" in prev_alert:
            if last_px <= stop_px * 1.003:
                keep = True

        if keep:
            out = dict(sig)
            out["bg_class"] = "warn-sell"
            out["pending_sell"] = True
            out["alert"] = prev_alert or alert or "将卖出"
            if prev.get("建议挂单") is not None and out.get("建议挂单") is None:
                out["建议挂单"] = prev.get("建议挂单")
            if prev.get("挂单说明") and not out.get("挂单说明"):
                out["挂单说明"] = prev.get("挂单说明")
            sticky[code] = {
                "session": session,
                "bg_class": "warn-sell",
                "alert": out["alert"],
                "pending_sell": True,
                "建议挂单": out.get("建议挂单"),
                "挂单说明": out.get("挂单说明"),
                "near_stop": bool(prev.get("near_stop")),
            }
            return out

        sticky.pop(code, None)

    return sig


def _account_cash(data: dict[str, Any] | None = None) -> float | None:
    data = data if data is not None else load_holdings()
    return _as_money(data.get("account_cash"))


def _holdings_market_value(rows: list[dict[str, Any]]) -> float:
    return sum(
        float(r["市值"])
        for r in rows
        if r.get("市值") is not None and int(r.get("持仓") or 0) > 0
    )


def _account_total(
    rows: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> float | None:
    """总资产：优先 现金+市值；否则用登记的 account_total。"""
    data = data if data is not None else load_holdings()
    cash = _account_cash(data)
    if cash is not None and rows is not None:
        return round(cash + _holdings_market_value(rows), 2)
    return _as_money(data.get("account_total"))


def _available_cash(
    rows: list[dict[str, Any]],
    data: dict[str, Any] | None = None,
) -> float | None:
    data = data if data is not None else load_holdings()
    cash = _account_cash(data)
    if cash is not None:
        return round(cash, 2)
    total = _as_money(data.get("account_total"))
    if total is None:
        return None
    return round(total - _holdings_market_value(rows), 2)


def _today_opened_cost(rows: list[dict[str, Any]], session: str | None = None) -> float:
    """当日新开仓成本额（锁定股 = 持仓 − 可用）。"""
    session = session or str(pd.Timestamp.now().date())
    total = 0.0
    positions = load_holdings().get("positions", {})
    for r in rows:
        code = str(r.get("代码") or "")
        qty = int(r.get("持仓") or 0)
        if qty <= 0:
            continue
        pos = positions.get(code) or {}
        sellable = _sellable_qty(
            pos, qty, pos.get("buy_time"), session, t0=False
        )
        locked = max(0, qty - sellable)
        if locked <= 0:
            continue
        if pos.get("today_cost") is not None:
            total += float(pos["today_cost"]) * locked
        elif pos.get("cost") is not None:
            total += float(pos["cost"]) * locked
    return round(total, 2)


def _sync_account_total(rows: list[dict[str, Any]]) -> float | None:
    """有现金登记时，用 现金+市值 回写总资产。"""
    data = load_holdings()
    cash = _account_cash(data)
    if cash is None:
        return _as_money(data.get("account_total"))
    total = round(cash + _holdings_market_value(rows), 2)
    if data.get("account_total") != total:
        data["account_total"] = total
        save_holdings(data)
    return total


def save_holdings(data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    with HOLDINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _HOLDINGS_CACHE["data"] = data
    _HOLDINGS_CACHE["mtime"] = _holdings_file_mtime()


def _purge_stale_realized(data: dict[str, Any], session: str) -> None:
    """清除非当日已实现记录，避免隔日污染合计。"""
    realized = data.setdefault("realized_today", {})
    stale = [k for k, v in realized.items() if str(v.get("session") or "") != session]
    for k in stale:
        del realized[k]


def update_high_after_stop(
    *,
    code: str,
    stop_px: float,
    high_after: float | None,
    low_after: float | None,
    qty: int,
    px_digits: int,
) -> dict[str, Any] | None:
    """刷新已结算记录中的「止损后最高/最低」，并估算踏空幅度/金额。"""
    if high_after is None and low_after is None:
        return None
    data = load_holdings()
    realized = data.setdefault("realized_today", {})
    rec = realized.get(code)
    if not rec or rec.get("reason") != REASON_STOP:
        return None
    stop_px = float(stop_px)
    if high_after is not None:
        ha = float(high_after)
        old_h = rec.get("high_after_stop")
        if old_h is not None:
            ha = max(float(old_h), ha)
        rec["high_after_stop"] = round(ha, px_digits)
    if low_after is not None:
        la = float(low_after)
        old_l = rec.get("low_after_stop")
        if old_l is not None:
            la = min(float(old_l), la)
        rec["low_after_stop"] = round(la, px_digits)
    sold_qty = int(rec.get("qty") or qty)
    if rec.get("high_after_stop") is not None:
        ha = float(rec["high_after_stop"])
        rebound_pct = (ha / stop_px - 1.0) * 100.0 if stop_px > 0 else None
        miss_pnl = (ha - stop_px) * sold_qty
        rec["rebound_pct"] = None if rebound_pct is None else round(rebound_pct, 2)
        rec["miss_pnl"] = round(miss_pnl, 2)
    save_holdings(data)
    return rec


def apply_exit_fill(
    *,
    code: str,
    meta: dict[str, Any],
    fill_px: float,
    qty: int,
    cost: float | None,
    session: str,
    buy_time: str | None,
    prev_close: float | None,
    open_px: float,
    px_digits: int,
    reason: str,
    trade_note: str,
) -> dict[str, Any]:
    """卖出视为已成交：按成交价锁定盈亏；可只卖可用股，剩余锁定仓继续持有。"""
    data = load_holdings()
    _purge_stale_realized(data, session)
    realized = data.setdefault("realized_today", {})
    existing = realized.get(code)
    if (
        existing
        and str(existing.get("session") or "") == session
        and existing.get("reason") in EXIT_REASONS
    ):
        return existing

    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    sell_qty = max(0, min(int(qty), old_qty))
    if sell_qty <= 0:
        return existing or {}

    fill_px = float(fill_px)
    cost_f = float(cost) if cost is not None else None
    pnl = (fill_px - cost_f) * sell_qty if cost_f is not None else None
    pnl_pct = (fill_px / cost_f - 1.0) * 100.0 if cost_f and cost_f > 0 else None

    # 卖出可用(=隔夜)按昨收计当日盈亏；否则按成本
    avail_before = _sellable_qty(pos, old_qty, buy_time, session, t0=False)
    overnight_sell = sell_qty <= avail_before and avail_before > 0
    if overnight_sell and prev_close is not None and float(prev_close) > 0:
        base_px = float(prev_close)
    elif (not overnight_sell) and cost_f is not None:
        base_px = cost_f
    elif prev_close is not None and float(prev_close) > 0:
        base_px = float(prev_close)
    else:
        base_px = cost_f if cost_f is not None else float(open_px)
    day_base = float(base_px) * sell_qty if base_px else None
    day_pnl = (fill_px - base_px) * sell_qty if base_px else None
    day_pnl_pct = (
        (fill_px / base_px - 1.0) * 100.0 if base_px and base_px > 0 else None
    )

    rec = {
        "session": session,
        "name": meta["name"],
        "market": meta["market"],
        "qty": int(sell_qty),
        "price": round(fill_px, px_digits),
        "cost": None if cost_f is None else round(cost_f, 4),
        "pnl": None if pnl is None else round(float(pnl), 2),
        "pnl_pct": None if pnl_pct is None else round(float(pnl_pct), 2),
        "day_base": None if day_base is None else round(float(day_base), 2),
        "day_pnl": None if day_pnl is None else round(float(day_pnl), 2),
        "day_pnl_pct": None if day_pnl_pct is None else round(float(day_pnl_pct), 2),
        "reason": reason,
        "time": _now(),
    }
    realized[code] = rec

    new_qty = old_qty - sell_qty
    pos["qty"] = new_qty
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if new_qty <= 0:
        pos["qty"] = 0
        pos["cost"] = None
        pos["buy_time"] = None
        pos["available"] = None
        pos["today_cost"] = None
        pos["note"] = f"{reason}@{rec['price']} ({session})"
    else:
        raw_avail = pos.get("available")
        if raw_avail is not None:
            try:
                pos["available"] = max(0, int(raw_avail) - sell_qty)
            except (TypeError, ValueError):
                pos["available"] = 0
        else:
            pos["available"] = 0
        # 卖的是隔夜可用仓，今日买入成本保留
        pos["note"] = f"{reason}@{rec['price']}×{sell_qty} 剩{new_qty} ({session})"

    save_holdings(data)
    append_trade(
        {
            "time": rec["time"],
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "price": rec["price"],
            "qty": sell_qty,
            "after_qty": int(pos["qty"]),
            "cost": rec["cost"],
            "pnl": rec["pnl"],
            "note": trade_note,
        }
    )
    if reason == REASON_STOP:
        remember_factor_trigger(code, side="sell", px=fill_px, session=session)
    return rec


def apply_stop_fill(
    *,
    code: str,
    meta: dict[str, Any],
    stop_px: float,
    qty: int,
    cost: float | None,
    session: str,
    buy_time: str | None,
    prev_close: float | None,
    open_px: float,
    px_digits: int,
) -> dict[str, Any]:
    """止损视为已成交：按止损价锁定盈亏、清仓，并写入当日已实现。"""
    return apply_exit_fill(
        code=code,
        meta=meta,
        fill_px=float(stop_px),
        qty=qty,
        cost=cost,
        session=session,
        buy_time=buy_time,
        prev_close=prev_close,
        open_px=open_px,
        px_digits=px_digits,
        reason=REASON_STOP,
        trade_note=f"{REASON_STOP}(自动)",
    )


def append_trade(record: dict[str, Any]) -> None:
    with TRADES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extremes_after_stop_touch(
    day: pd.DataFrame, stop_px: float
) -> tuple[float | None, float | None]:
    """触及止损后（含触及那根分钟）到现在的最高价、最低价。"""
    if day is None or getattr(day, "empty", True):
        return None, None
    stop_px = float(stop_px)
    touched = day[day["low"] <= stop_px + 1e-12]
    if touched.empty:
        return None, None
    first_ts = touched.iloc[0]["ts"]
    after = day[day["ts"] >= first_ts]
    if after.empty:
        return None, None
    return float(after["high"].max()), float(after["low"].min())


def fetch_sina_spot(sina: str) -> dict[str, Any] | None:
    """新浪实时行情（竞价/开盘后分钟线未到时可用）。"""
    try:
        resp = requests.get(
            f"https://hq.sinajs.cn/list={sina}",
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=8,
        )
        text = resp.content.decode("gbk", "ignore").strip()
    except Exception:  # noqa: BLE001
        return None
    if '="' not in text:
        return None
    payload = text.split('="', 1)[1].rstrip('";')
    parts = payload.split(",")
    if len(parts) < 32:
        return None

    def _f(i: int) -> float:
        try:
            return float(parts[i])
        except (TypeError, ValueError):
            return 0.0

    open_px = _f(1)
    prev_close = _f(2)
    last_px = _f(3)
    high_px = _f(4)
    low_px = _f(5)
    bid = _f(6)
    ask = _f(7)
    # 竞价阶段 open/last 常为 0，用买卖一价作撮合参考
    if open_px <= 0:
        open_px = bid or ask or last_px
    if last_px <= 0:
        last_px = open_px or bid or ask
    if high_px <= 0:
        high_px = max(open_px, last_px)
    if low_px <= 0:
        low_px = min(x for x in (open_px, last_px) if x > 0) if open_px or last_px else 0.0
    if open_px <= 0 or last_px <= 0 or prev_close <= 0:
        return None
    session = parts[30] or str(pd.Timestamp.now().date())
    stamp = f"{session} {parts[31]}" if parts[31] else f"{session} 09:25:00"
    return {
        "session": session,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "last": last_px,
        "prev_close": prev_close,
        "last_ts": stamp,
        "name": str(parts[0] or "").strip(),
    }


def _day_key_series(ts: pd.Series) -> pd.Series:
    """统一按日历日比较，避免 datetime64[us] 与 Timestamp 直接比较报错。"""
    return pd.to_datetime(ts).dt.strftime("%Y-%m-%d")


def fetch_today_quote(sina: str) -> dict[str, Any]:
    """用1分钟线拼当日开高低；现价优先新浪实时，避免分钟末根滞后。

    分钟线优先框架 akshare：东财 `stock_zh_a_hist_min_em` → 新浪备用。
    """
    today = str(pd.Timestamp.now().date())
    spot = fetch_sina_spot(sina)

    day = pd.DataFrame()
    prev_close: float | None = None
    em_code = sina[2:] if len(sina) >= 8 and sina[:2].lower() in ("sh", "sz") else sina
    # 盯盘用未复权更贴近盘面现价；失败则 pull 内部仍会尝试新浪
    df = pull_akshare_1m(em_symbol=em_code, sina_symbol=sina, adjust="")

    if not df.empty:
        day_keys = _day_key_series(df["ts"])
        day = df[day_keys == today].copy()
        if not day.empty:
            day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
            # 开盘初偶发 open=0 的脏分钟，丢掉无效价
            day = day[
                (day["open"] > 0) & (day["high"] > 0) & (day["low"] > 0) & (day["close"] > 0)
            ]

        prev = df[day_keys < today].copy()
        if not prev.empty:
            prev = prev.dropna(subset=["close"]).sort_values("ts")
            if not prev.empty:
                prev_last = _day_key_series(prev["ts"]).iloc[-1]
                prev_day = prev[_day_key_series(prev["ts"]) == prev_last]
                if not prev_day.empty:
                    prev_close = float(prev_day.iloc[-1]["close"])

    spot_ok = spot is not None and str(spot.get("session") or "") == today

    # 当日分钟线已到：OHLC 用分钟，现价优先新浪实时
    if not day.empty:
        open_px = float(day.iloc[0]["open"])
        high_px = float(day["high"].max())
        low_px = float(day["low"].min())
        last_px = float(day.iloc[-1]["close"])
        last_ts = str(day.iloc[-1]["ts"])
        if spot_ok:
            # 实时现价覆盖滞后的分钟收盘；开盘价固定用首根分钟，避免新浪 open 抖动导致阴/阳翻转（绿底闪没）
            last_px = float(spot["last"])
            last_ts = str(spot["last_ts"])
            high_px = max(high_px, float(spot["high"]) if float(spot["high"]) > 0 else high_px)
            low_cand = float(spot["low"])
            if low_cand > 0:
                low_px = min(low_px, low_cand)
            if prev_close is None:
                prev_close = float(spot["prev_close"])
            # 仅当分钟开盘异常时才用新浪开盘兜底
            if open_px <= 0 and float(spot["open"]) > 0:
                open_px = float(spot["open"])
        elif prev_close is None and spot is not None:
            prev_close = float(spot["prev_close"])
        day_chg = None
        if prev_close is not None and prev_close > 0:
            day_chg = (last_px / prev_close - 1.0) * 100.0
        return {
            "session": today,
            "open": open_px,
            "high": high_px,
            "low": low_px,
            "last": last_px,
            "prev_close": prev_close,
            "day_chg_pct": day_chg,
            "last_ts": last_ts,
            "_day_bars": day,
        }

    # 竞价/开盘初：分钟线尚无今日，用新浪现价
    if spot_ok:
        day_chg = None
        prev_close = float(spot["prev_close"])
        last_px = float(spot["last"])
        if prev_close > 0:
            day_chg = (last_px / prev_close - 1.0) * 100.0
        return {
            "session": today,
            "open": float(spot["open"]),
            "high": float(spot["high"]),
            "low": float(spot["low"]),
            "last": last_px,
            "prev_close": prev_close,
            "day_chg_pct": day_chg,
            "last_ts": str(spot["last_ts"]),
            "_day_bars": pd.DataFrame(),
        }

    # 非交易时段：退回最近一个交易日全日分钟线
    if df.empty:
        raise RuntimeError(f"无分钟行情: {sina}")
    df = df.copy()
    day_keys = _day_key_series(df["ts"])
    last_day = day_keys.max()
    day = df[day_keys == last_day].copy()
    for col in ("open", "high", "low", "close"):
        day[col] = pd.to_numeric(day[col], errors="coerce")
    day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
    day = day[(day["open"] > 0) & (day["high"] > 0) & (day["low"] > 0) & (day["close"] > 0)]
    if day.empty:
        raise RuntimeError(f"当日无有效分钟线: {sina}")
    prev = df[day_keys < last_day].copy()
    if not prev.empty:
        prev["close"] = pd.to_numeric(prev["close"], errors="coerce")
        prev = prev.dropna(subset=["close"]).sort_values("ts")
        if not prev.empty:
            prev_last = _day_key_series(prev["ts"]).iloc[-1]
            prev_day = prev[_day_key_series(prev["ts"]) == prev_last]
            if not prev_day.empty:
                prev_close = float(prev_day.iloc[-1]["close"])
    open_px = float(day.iloc[0]["open"])
    high_px = float(day["high"].max())
    low_px = float(day["low"].min())
    last_px = float(day.iloc[-1]["close"])
    last_ts = day.iloc[-1]["ts"]
    day_chg = None
    if prev_close is not None and prev_close > 0:
        day_chg = (last_px / prev_close - 1.0) * 100.0
    return {
        "session": last_day,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "last": last_px,
        "prev_close": prev_close,
        "day_chg_pct": day_chg,
        "last_ts": str(last_ts),
        "_day_bars": day,
    }


def points_vs_open(open_px: float, px: float) -> float:
    if open_px <= 0:
        return float("nan")
    return (px / open_px - 1.0) * 100.0


def pct_vs_open(open_px: float, px: float) -> float | None:
    """较开盘涨幅% = (现价/开盘-1)×100。"""
    v = points_vs_open(open_px, px)
    if v != v:
        return None
    return round(float(v), 2)


def fetch_indices() -> list[dict[str, Any]]:
    """拉取上证指数 / 深证成指：最新点数、涨跌点数、涨跌幅。"""
    try:
        with AKSHARE_CALL_LOCK:
            spot = ak.stock_zh_index_spot_sina()
    except Exception as e:  # noqa: BLE001
        return [
            {
                "code": x["code"],
                "name": x["name"],
                "market": x["market"],
                "price": None,
                "chg_points": None,
                "chg_pct": None,
                "error": str(e),
            }
            for x in INDEX_WATCH
        ]

    out: list[dict[str, Any]] = []
    code_col = "代码" if "代码" in spot.columns else spot.columns[0]
    for item in INDEX_WATCH:
        row = spot[spot[code_col].astype(str) == item["code"]]
        if row.empty:
            out.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "market": item["market"],
                    "price": None,
                    "chg_points": None,
                    "chg_pct": None,
                    "error": "未找到指数",
                }
            )
            continue
        r = row.iloc[0]
        price = pd.to_numeric(r.get("最新价"), errors="coerce")
        chg_pts = pd.to_numeric(r.get("涨跌额"), errors="coerce")
        chg_pct = pd.to_numeric(r.get("涨跌幅"), errors="coerce")
        out.append(
            {
                "code": item["code"],
                "name": item["name"],
                "market": item["market"],
                "price": None if pd.isna(price) else float(price),
                "chg_points": None if pd.isna(chg_pts) else float(chg_pts),
                "chg_pct": None if pd.isna(chg_pct) else float(chg_pct),
                "error": None,
            }
        )
    return out


def collect_rows(
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """拉取行情并合并持仓；已触止损视为成交并锁定当日收益。

    get_quote: 可选行情供给（watch 传入 QuoteHub）；默认 fetch_today_quote。
    """
    quote_fn = get_quote or fetch_today_quote
    holdings = load_holdings()
    positions = holdings.get("positions", {})
    realized_map = holdings.get("realized_today", {})
    sticky = _alert_sticky_map(holdings)
    rows: list[dict[str, Any]] = []
    session_today: str | None = None
    phase_now = market_phase()
    phase_label = market_phase_label(phase_now)
    threshold_ok = is_threshold_ready()
    signal_ok_global = is_signal_window()

    for w in effective_watchlist():
        code = w["code"]
        entry_pct = _watch_pct(w)
        base_stop_pct = _watch_stop_pct(w)
        tick = _watch_tick(w)
        limit_down_pct = _watch_limit_down_pct(w)
        prev_entry_mode = str(w.get("prev_entry_mode") or "yin_or_small_yang")
        px_digits = _px_digits(tick)
        if abs(entry_pct - base_stop_pct) < 1e-12:
            pct_label = f"±{entry_pct * 100:.1f}"
        else:
            pct_label = f"+{entry_pct * 100:.1f}/-{base_stop_pct * 100:.1f}"
        pct_pct = pct_label  # 卡片「阈值%」展示文案
        try:
            q = quote_fn(w["sina"])
            session_today = q["session"]
            daily = _watch_daily(w["sina"])
            if USE_FACTOR4:
                f4_kind, f4_params, f4_widen = resolve_factor4_spec(w)
                bull = bull_exec_today(
                    w["sina"],
                    str(q["session"]),
                    daily,
                    kind=f4_kind,
                    params=f4_params,
                )
                stop_pct, f4_mode = effective_stop_pct(
                    base_stop_pct, bull=bull, widen_mult=f4_widen
                )
                # 展示/成交用有效止损；暂停止损时仍展示基础止损价，但不自动结算
                stop_pct_for_levels = (
                    base_stop_pct if f4_mode == "suppressed" else stop_pct
                )
            else:
                bull = False
                f4_widen = 1.0
                stop_pct = base_stop_pct
                f4_mode = "off"
                stop_pct_for_levels = base_stop_pct
            lv = strategy_levels(
                q["open"],
                entry_pct=entry_pct,
                stop_pct=stop_pct_for_levels,
                tick=tick,
            )
            lv_base = strategy_levels(
                q["open"],
                entry_pct=entry_pct,
                stop_pct=base_stop_pct,
                tick=tick,
            )
            vs = points_vs_open(q["open"], q["last"])
            vs_pct = pct_vs_open(q["open"], q["last"])
            day_chg = q.get("day_chg_pct")
            prev_o, prev_c, prev2_o, prev2_c = _prev_bars_from_daily(daily, q["session"])
            f1p = _factor1_binding_params()
            allow_entry, gate_label, prev_shape = _entry_gate_detail(
                prev_o,
                prev_c,
                prev2_o,
                prev2_c,
                entry_pct=entry_pct,
                prev_entry_mode=prev_entry_mode,
                tick=tick,
                f1p=f1p,
            )
            auction_ref = round(float(q["last"]), px_digits)
            replay = _replay_last_factor_triggers_cached(
                w["sina"],
                daily,
                entry_pct=entry_pct,
                stop_pct=base_stop_pct,
                tick=tick,
                prev_entry_mode=prev_entry_mode,
                limit_down_pct=limit_down_pct,
            )
            hit_buy_raw = q["high"] + 1e-12 >= lv["buy_trigger"]
            hit_buy = bool(allow_entry) and hit_buy_raw
            hit_base_stop = q["low"] <= lv_base["stop"] + 1e-12
            hit_eff_stop = q["low"] <= lv["stop"] + 1e-12
            # 因子4（可选）：牛市暂停止损 → 不自动结算；放宽 → 仅触放宽价才结算
            if USE_FACTOR4 and f4_mode == "suppressed":
                hit_stop = False
            else:
                hit_stop = hit_eff_stop
            f4_tag = (
                format_factor4_tag(bull=bull, mode=f4_mode, widen_mult=f4_widen)
                if USE_FACTOR4
                else "-"
            )
            # 9:25 前：仅竞价参考；9:25–9:30：算阈值/过门但不结算；9:30 起全触发
            preview_ok = threshold_ok
            signal_ok = signal_ok_global
            if not preview_ok:
                hit_buy = False
                hit_stop = False
            elif not signal_ok:
                hit_stop = False
            # 当日止损/已结算卖出 → 禁止再买（纸面回放持有触止损同样禁买）
            _realized_pre = realized_map.get(code)
            _sold_today_pre = bool(
                _realized_pre
                and str(_realized_pre.get("session") or "") == q["session"]
                and _realized_pre.get("reason") in EXIT_REASONS
            )
            _paper_hold = bool(replay.get("holding")) and int(
                (positions.get(code) or {}).get("qty") or 0
            ) <= 0
            if _sold_today_pre or (_paper_hold and hit_stop):
                allow_entry = False
                hit_buy = False
            limit_state = limit_down_state(
                prev_close=q.get("prev_close"),
                open_px=float(q["open"]),
                high_px=float(q["high"]),
                low_px=float(q["low"]),
                close_px=float(q["last"]),
                limit_down_pct=limit_down_pct,
                tick=tick,
            )
            pos = positions.get(code, {})
            qty = int(pos.get("qty") or 0)
            buy_time = pos.get("buy_time")
            cost = pos.get("cost")
            t0 = bool(w.get("t0"))
            sellable = _sellable_qty(pos, qty, buy_time, q["session"], t0=t0)
            # 一字跌停封单不可卖；触及跌停后开板则按跌停价成交。
            stop_locked = bool(limit_state["locked"])
            stop_base_px = float(
                limit_state["limit_px"]
                if bool(limit_state["opened"])
                else lv["stop"]
            )
            # 盯盘按人工/云条件单的触发价记录，不对买卖触发价额外加滑点。
            stop_fill_px = stop_base_px
            # 已触止损且可卖 → 视为成交，锁定收益（只卖可用）
            # 隔夜仓 available=0 已在 _sellable_qty 回退为整仓，避免卡死不结算
            if qty > 0 and hit_stop and sellable > 0 and not stop_locked:
                apply_stop_fill(
                    code=code,
                    meta=w,
                    stop_px=stop_fill_px,
                    qty=sellable,
                    cost=float(cost) if cost is not None else None,
                    session=q["session"],
                    buy_time=buy_time,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    px_digits=px_digits,
                )
                holdings = load_holdings()
                positions = holdings.get("positions", {})
                realized_map = holdings.get("realized_today", {})
                pos = positions.get(code, {})
                qty = int(pos.get("qty") or 0)
                cost = pos.get("cost")
                buy_time = pos.get("buy_time")
                sellable = _sellable_qty(pos, qty, buy_time, q["session"], t0=t0)

            # 当日已卖出结算：全清时冻结收益；部分卖出则继续展示剩余仓
            realized = realized_map.get(code)
            if (
                realized
                and str(realized.get("session") or "") == q["session"]
                and realized.get("reason") in EXIT_REASONS
                and qty <= 0
            ):
                fill_px = float(realized["price"])
                sold_qty = int(realized.get("qty") or 0)
                reason = str(realized.get("reason") or "")
                # 兼容旧记录：补当日基数
                if realized.get("day_base") is None and realized.get("day_pnl") is not None:
                    dpct = realized.get("day_pnl_pct")
                    if dpct is not None and abs(float(dpct)) > 1e-12:
                        realized["day_base"] = round(
                            float(realized["day_pnl"]) / (float(dpct) / 100.0), 2
                        )
                ha_show = None
                la_show = None
                rebound = None
                miss = None
                if reason == REASON_STOP:
                    ha, la = extremes_after_stop_touch(
                        q.get("_day_bars"), float(lv["stop"])
                    )
                    # 无分钟线时用 hub/快照当日 high/low 退化
                    if ha is None:
                        try:
                            ha = float(q["high"]) if float(q["high"]) > 0 else None
                            la = float(q["low"]) if float(q["low"]) > 0 else None
                        except (TypeError, ValueError, KeyError):
                            ha, la = None, None
                    updated = update_high_after_stop(
                        code=code,
                        stop_px=float(lv["stop"]),
                        high_after=ha,
                        low_after=la,
                        qty=sold_qty,
                        px_digits=px_digits,
                    )
                    if updated:
                        realized = updated
                        realized_map[code] = updated
                    ha_show = realized.get("high_after_stop")
                    la_show = realized.get("low_after_stop")
                    rebound = realized.get("rebound_pct")
                    miss = realized.get("miss_pnl")
                live_last = round(q["last"], px_digits)
                note = (
                    f"已按{reason}@{fill_px:.{px_digits}f}，盈亏已锁定；现价仍实时更新"
                )
                if ha_show is not None:
                    note += f"；止损后最高{float(ha_show):.{px_digits}f}"
                    if rebound is not None:
                        note += f"（回抽{float(rebound):+.2f}%）"
                if la_show is not None:
                    note += f"；最低{float(la_show):.{px_digits}f}"
                # 当日已卖出：禁止再买
                allow_entry = False
                hit_buy = False
                # 已清仓：因子侧/持仓状态按空仓规则重算（当日不进待买入）
                sig0 = strategy_signal(
                    open_px=q["open"],
                    high_px=q["high"],
                    low_px=q["low"],
                    last_px=q["last"],
                    session=q["session"],
                    buy_trigger=lv["buy_trigger"],
                    stop_px=lv["stop"],
                    qty=0,
                    buy_time=None,
                    vs_open_pts=vs,
                    entry_pct=entry_pct,
                    stop_pct=stop_pct,
                    px_digits=px_digits,
                    t0=t0,
                    allow_entry=False,
                )
                row0 = {
                        "市场": w["market"],
                        "代码": code,
                        "名称": w["name"],
                        "交易日": q["session"],
                        "开盘": round(q["open"], px_digits),
                        "最高": round(q["high"], px_digits),
                        "最低": round(q["low"], px_digits),
                        "现价": live_last,
                        "成交价": round(fill_px, px_digits),
                        "止损后最高": ha_show,
                        "止损后最低": la_show,
                        "回抽%": rebound,
                        "踏空金额": miss,
                        "昨收": None
                        if q.get("prev_close") is None
                        else round(float(q["prev_close"]), px_digits),
                        "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                        "较开盘点": vs,
                        "较开盘涨幅": vs_pct,
                        "阈值%": pct_pct,
                        "买点": lv["buy_trigger"],
                        "止损": lv["stop"],
                        "基础止损": lv_base["stop"],
                        "因子4": f4_tag,
                        "牛市": ("是" if bull else "否") if USE_FACTOR4 else "-",
                        "已触买": "否",
                        "已触止损": "是" if hit_stop or reason == REASON_STOP else "否",
                        "因子侧": "空仓",
                        "因子价": sig0.get("因子价"),
                        "因子触发": sig0.get("因子触发"),
                        "持仓状态": "空仓",
                        "已触发因子侧": sig0.get("已触发因子侧"),
                        "已触发因子价": sig0.get("已触发因子价"),
                        "未触发因子侧": sig0.get("未触发因子侧"),
                        "未触发因子价": sig0.get("未触发因子价"),
                        "距已触发价差": sig0.get("距已触发价差"),
                        "距已触发%": sig0.get("距已触发%"),
                        "距未触发价差": sig0.get("距未触发价差"),
                        "距未触发%": sig0.get("距未触发%"),
                        "距因子价差": sig0.get("距因子价差"),
                        "距因子%": sig0.get("距因子%"),
                        "形态": sig0.get("形态") or bar_shape(q["open"], q["last"]),
                        "预警": reason,
                        "建议挂单": None,
                        "挂单说明": note + "；当日已卖出不再买",
                        "近买点": False,
                        "近止损": False,
                        "bg_class": sig0.get("bg_class") or "status-flat",
                        "持仓": 0,
                        "卖出数量": sold_qty,
                        "成本": realized.get("cost"),
                        "浮盈": realized.get("pnl"),
                        "浮盈%": realized.get("pnl_pct"),
                        "当日盈亏": realized.get("day_pnl"),
                        "当日盈亏%": realized.get("day_pnl_pct"),
                        "当日基数": realized.get("day_base"),
                        "市值": 0.0,
                        "成本额": None,
                        "已实现": True,
                        "价位小数": px_digits,
                        "更新": q["last_ts"][11:19]
                        if len(q["last_ts"]) >= 19
                        else q["last_ts"],
                        "error": None,
                }
                _apply_trigger_date_fields(
                    row0,
                    sig=sig0,
                    session=q["session"],
                    last_px=float(q["last"]),
                    px_digits=px_digits,
                    buy_time=None,
                    qty=0,
                    replay=replay,
                    code=code,
                    allow_entry=False,
                )
                rows.append(row0)
                continue

            # 纸面回放持有：按虚拟有仓算止损侧信号（不自动成交）；真仓仍用实际 qty
            paper_active = bool(_paper_hold and qty <= 0 and not _sold_today_pre)
            sig_qty = 1 if paper_active else qty
            if paper_active:
                sig_buy_time = str(replay.get("last_buy_date") or "")[:10] or None
            else:
                # 有可卖股时不当作整仓 T+1，避免「持有·T+1」误锁信号
                sig_buy_time = None if sellable > 0 else buy_time
            sig = strategy_signal(
                open_px=q["open"],
                high_px=q["high"],
                low_px=q["low"],
                last_px=q["last"],
                session=q["session"],
                buy_trigger=lv["buy_trigger"],
                stop_px=lv["stop"],
                qty=sig_qty,
                buy_time=sig_buy_time,
                vs_open_pts=vs,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                px_digits=px_digits,
                t0=t0,
                # 纸面仓禁止买入预警
                allow_entry=False if paper_active else (allow_entry and preview_ok),
            )
            if qty > 0 and hit_stop and stop_locked:
                limit_px = float(limit_state["limit_px"])
                sig = dict(sig)
                sig.update(
                    {
                        "alert": "一字跌停封单·不可卖",
                        "bg_class": "warn-sell",
                        "pending_sell": True,
                        "建议挂单": None,
                        "挂单说明": (
                            f"跌停价{limit_px:.{px_digits}f}封单，"
                            "止损触发但不可成交；持仓延续，待开板"
                        ),
                        "因子触发": "不可成交",
                    }
                )
            elif qty > 0 and hit_stop and sellable <= 0 and not stop_locked:
                # 典型：买入当日 T+1，止损已触但不可卖
                sig = dict(sig)
                t1_today = (not t0) and is_t1_buy_day(buy_time, q["session"])
                sig.update(
                    {
                        "alert": (
                            "已触止损·T+1暂不可卖"
                            if t1_today
                            else "已触止损·暂不可卖"
                        ),
                        "bg_class": "warn-sell",
                        "pending_sell": True,
                        "持仓状态": "待卖出",
                        "建议挂单": None,
                        "挂单说明": (
                            "今日买入不可卖，止损触发后下一交易日可卖"
                            if t1_today
                            else "无可卖数量，请核对 available / 买入日"
                        ),
                        "因子触发": "已触发",
                    }
                )
            elif (
                USE_FACTOR4
                and qty > 0
                and f4_mode == "suppressed"
                and hit_base_stop
                and signal_ok
                and not stop_locked
            ):
                # 因子4 牛市：基础止损已触但不结算
                sig = dict(sig)
                sig.update(
                    {
                        "alert": "持有·因子4牛市暂停止损",
                        "bg_class": "status-hold",
                        "pending_sell": False,
                        "持仓状态": "持有",
                        "建议挂单": None,
                        "挂单说明": (
                            f"{f4_tag}；基础止损{lv_base['stop']:.{px_digits}f}"
                            "已触，暂不结算"
                        ),
                        "因子触发": "暂停",
                    }
                )
            elif (
                USE_FACTOR4
                and qty > 0
                and f4_mode == "widened"
                and hit_base_stop
                and not hit_eff_stop
                and signal_ok
            ):
                sig = dict(sig)
                alert0 = str(sig.get("alert") or "持有")
                if alert0.startswith("持有"):
                    sig["alert"] = f"持有·{f4_tag}"
                sig["挂单说明"] = (
                    f"{f4_tag}；基础止损{lv_base['stop']:.{px_digits}f}已触，"
                    f"放宽止损{lv['stop']:.{px_digits}f}未触"
                )
            sig = _stabilize_sell_warn(
                code=code,
                session=q["session"],
                sig=sig,
                open_px=float(q["open"]),
                last_px=float(q["last"]),
                stop_px=float(lv["stop"]),
                vs_open_pts=float(vs) if vs == vs else 0.0,
                stop_lvl=-stop_pct * 100.0,
                sticky=sticky,
            )
            if qty > 0 and sellable > 0 and sellable < qty:
                # 部分 T+1：状态标为持有·部分T+1
                alert = str(sig.get("alert") or "")
                if alert.startswith("持有"):
                    sig = dict(sig)
                    rest = alert[len("持有") :]
                    sig["alert"] = f"持有·部分T+1{rest}" if rest else "持有·部分T+1"
            pnl = None
            pnl_pct = None
            market_value = (q["last"] * qty) if qty > 0 else None
            cost_value = None
            day_pnl = None
            day_pnl_pct = None
            day_base = None
            if cost is not None and qty > 0:
                cost_f = float(cost)
                pnl_pct = (q["last"] / cost_f - 1.0) * 100.0
                pnl = (q["last"] - cost_f) * qty
                cost_value = cost_f * qty

            if qty > 0:
                today_cost = pos.get("today_cost")
                day_pnl, day_pnl_pct, day_base = _calc_day_pnl(
                    last=float(q["last"]),
                    qty=qty,
                    available=sellable,
                    cost=float(cost) if cost is not None else None,
                    prev_close=q.get("prev_close"),
                    open_px=float(q["open"]),
                    today_cost=float(today_cost) if today_cost is not None else None,
                    buy_time=buy_time,
                    session=str(q["session"]),
                    t0=t0,
                )
                # 同日已部分卖出：把已实现当日盈亏并入
                if (
                    realized
                    and str(realized.get("session") or "") == q["session"]
                    and realized.get("reason") in EXIT_REASONS
                ):
                    rd = realized.get("day_pnl")
                    rb = realized.get("day_base")
                    if rd is not None:
                        day_pnl = round(float(day_pnl or 0) + float(rd), 2)
                    if rb is not None:
                        day_base = round(float(day_base or 0) + float(rb), 2)
                    if day_base and day_base > 0 and day_pnl is not None:
                        day_pnl_pct = round(float(day_pnl) / float(day_base) * 100.0, 2)

            row = {
                    "市场": w["market"],
                    "代码": code,
                    "名称": w["name"],
                    "交易日": q["session"],
                    "开盘": round(q["open"], px_digits),
                    "最高": round(q["high"], px_digits),
                    "最低": round(q["low"], px_digits),
                    "现价": round(q["last"], px_digits),
                    "昨收": None
                    if q.get("prev_close") is None
                    else round(float(q["prev_close"]), px_digits),
                    "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                    "较开盘点": vs,
                    "较开盘涨幅": vs_pct,
                    "阈值%": pct_pct,
                    "买点": lv["buy_trigger"],
                    "止损": lv["stop"],
                    "基础止损": lv_base["stop"],
                    "因子4": f4_tag,
                    "牛市": ("是" if bull else "否") if USE_FACTOR4 else "-",
                    "已触买": "是" if (qty <= 0 and hit_buy) else "否",
                    "已触止损": "是" if hit_stop else (
                        "触基础·暂停"
                        if (USE_FACTOR4 and f4_mode == "suppressed" and hit_base_stop)
                        else "否"
                    ),
                    "因子侧": sig.get("因子侧"),
                    "因子价": sig.get("因子价"),
                    "因子触发": sig.get("因子触发"),
                    "持仓状态": sig.get("持仓状态") or (
                        "持有" if qty > 0 else "空仓"
                    ),
                    "已触发因子侧": sig.get("已触发因子侧"),
                    "已触发因子价": sig.get("已触发因子价"),
                    "未触发因子侧": sig.get("未触发因子侧"),
                    "未触发因子价": sig.get("未触发因子价"),
                    "距已触发价差": sig.get("距已触发价差"),
                    "距已触发%": sig.get("距已触发%"),
                    "距未触发价差": sig.get("距未触发价差"),
                    "距未触发%": sig.get("距未触发%"),
                    "距因子价差": sig.get("距因子价差"),
                    "距因子%": sig.get("距因子%"),
                    "形态": sig["形态"],
                    "预警": sig["alert"],
                    "建议挂单": sig["建议挂单"],
                    "挂单说明": sig["挂单说明"],
                    "近买点": sig["pending_buy"],
                    "近止损": sig["pending_sell"],
                    "bg_class": sig["bg_class"],
                    "持仓": qty,
                    "可用": sellable if qty > 0 else 0,
                    "成本": None if cost is None else float(cost),
                    "浮盈": None if pnl is None else round(float(pnl), 2),
                    "浮盈%": None if pnl_pct is None else round(float(pnl_pct), 2),
                    "当日盈亏": None if day_pnl is None else round(float(day_pnl), 2),
                    "当日盈亏%": None
                    if day_pnl_pct is None
                    else round(float(day_pnl_pct), 2),
                    "当日基数": None if day_base is None else round(float(day_base), 2),
                    "市值": None if market_value is None else round(float(market_value), 2),
                    "成本额": None if cost_value is None else round(float(cost_value), 2),
                    "已实现": False,
                    "价位小数": px_digits,
                    "更新": q["last_ts"][11:19]
                    if len(q["last_ts"]) >= 19
                    else q["last_ts"],
                    "market_phase": phase_label,
                    "过门": gate_label,
                    "过门OK": allow_entry,
                    "前日形态": prev_shape,
                    "阈值就绪": preview_ok,
                    "竞价参考": auction_ref,
                    "error": None,
            }
            _apply_trigger_date_fields(
                row,
                sig=sig,
                session=q["session"],
                last_px=float(q["last"]),
                px_digits=px_digits,
                buy_time=buy_time,
                qty=qty,
                replay=replay,
                code=code,
                allow_entry=allow_entry,
            )
            try:
                from strategy3_watch import enrich_first_board_row

                row["_s3_fb"] = enrich_first_board_row(
                    code=code,
                    daily=daily,
                    session=str(q["session"]),
                    open_px=float(q["open"]) if q.get("open") else 0.0,
                )
            except Exception:  # noqa: BLE001
                row["_s3_fb"] = {}
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            pos = positions.get(code, {})
            rows.append(
                {
                    "市场": w["market"],
                    "代码": code,
                    "名称": w["name"],
                    "交易日": "-",
                    "开盘": None,
                    "最高": None,
                    "最低": None,
                    "现价": None,
                    "当日涨幅": None,
                    "较开盘点": None,
                    "较开盘涨幅": None,
                    "阈值%": pct_pct,
                    "买点": None,
                    "止损": None,
                    "基础止损": None,
                    "因子4": "-",
                    "牛市": "-",
                    "已触买": "-",
                    "已触止损": "-",
                    "因子侧": "-",
                    "因子价": None,
                    "因子触发": "-",
                    "持仓状态": "-",
                    "已触发因子侧": "-",
                    "已触发因子价": None,
                    "未触发因子侧": "-",
                    "未触发因子价": None,
                    "距已触发价差": None,
                    "距已触发%": None,
                    "距未触发价差": None,
                    "距未触发%": None,
                    "距因子价差": None,
                    "距因子%": None,
                    "形态": "-",
                    "预警": "",
                    "建议挂单": None,
                    "挂单说明": "",
                    "近买点": False,
                    "近止损": False,
                    "bg_class": "",
                    "持仓": int(pos.get("qty") or 0),
                    "可用": 0,
                    "成本": pos.get("cost"),
                    "浮盈": None,
                    "浮盈%": None,
                    "昨收": None,
                    "当日盈亏": None,
                    "当日盈亏%": None,
                    "市值": None,
                    "成本额": None,
                    "已实现": False,
                    "价位小数": px_digits,
                    "更新": "-",
                    "error": str(e),
                }
            )

    if session_today:
        data = load_holdings()
        before = dict(data.get("realized_today") or {})
        _purge_stale_realized(data, session_today)
        if data.get("realized_today") != before:
            save_holdings(data)
        _save_alert_sticky(session_today, sticky)

    for r in rows:
        _finalize_position_row(r)
        _enrich_float_pnl(r)

    total_mv = sum(
        float(r["市值"])
        for r in rows
        if r.get("市值") is not None and int(r.get("持仓") or 0) > 0
    )
    account_total = _sync_account_total(rows)
    pos_base = account_total if account_total and account_total > 0 else (
        total_mv if total_mv > 0 else None
    )
    for r in rows:
        qty = int(r.get("持仓") or 0)
        mv = r.get("市值")
        if qty > 0 and mv is not None and pos_base and pos_base > 0:
            r["仓位%"] = round(float(mv) / pos_base * 100.0, 1)
        else:
            r["仓位%"] = 0.0 if r.get("已实现") else None

    # 因子2：按账户总资产同步（可选预警；与 dd_alert 同源）
    session_f2 = session_today or str(pd.Timestamp.now().date())
    data_f2 = load_holdings()
    f2_status = sync_factor2(
        data_f2, equity=account_total, session=str(session_f2)
    )
    save_holdings(data_f2)
    for r in rows:
        r["因子2动作"] = f2_status.get("action")
        r["因子2"] = f2_status.get("label")
        r["因子2建议额"] = f2_status.get("suggest_amount")
        r["因子2回撤%"] = f2_status.get("dd_pct")
        r["因子2档位"] = f2_status.get("layers")
    return sort_watch_rows(rows)


def _enrich_float_pnl(row: dict[str, Any]) -> None:
    """策略一口径浮盈：买入成本起算；持仓动态、卖出结算。"""
    if row.get("error"):
        return
    last = row.get("现价")
    if last is None:
        return
    try:
        last_f = float(last)
    except (TypeError, ValueError):
        return
    if last_f <= 0:
        return

    qty = int(row.get("持仓") or 0)
    if row.get("已实现"):
        if row.get("浮盈") is not None:
            row["盈亏状态"] = "结算"
        return

    cost = row.get("成本")
    if qty > 0 and cost is not None:
        cost_f = float(cost)
        row["浮盈"] = round((last_f - cost_f) * qty, 2)
        row["浮盈%"] = round((last_f / cost_f - 1.0) * 100.0, 2)
        row["盈亏状态"] = "浮盈"
        return

    paper = bool(row.get("策略回放持有")) or str(row.get("持仓状态") or "") == "策略持有"
    if paper and qty <= 0:
        buy_px = row.get("已触发因子价")
        if buy_px is None:
            buy_px = row.get("因子价")
        if buy_px is not None:
            try:
                bp = float(buy_px)
            except (TypeError, ValueError):
                bp = 0.0
            if bp > 0:
                row["浮盈"] = round(last_f - bp, 2)
                row["浮盈%"] = round((last_f / bp - 1.0) * 100.0, 2)
                row["盈亏状态"] = "浮盈"
                row["盈亏说明"] = "策略买入价·单股"
        return

    if qty <= 0:
        row["浮盈"] = None
        row["浮盈%"] = None
        row["盈亏状态"] = None


def _finalize_position_row(row: dict[str, Any]) -> None:
    """收敛持仓状态：T+1 / 当日禁买 / 策略回放持有 / 可执行。"""
    if row.get("error"):
        row["可执行"] = False
        return
    qty = int(row.get("持仓") or 0)
    paper = bool(row.get("策略回放持有"))
    no_buy = bool(row.get("当日禁买"))
    alert = str(row.get("预警") or "")
    pos = str(row.get("持仓状态") or "")
    t1 = "T+1" in alert

    if no_buy and qty <= 0:
        row["持仓状态"] = "当日禁买"
        row["因子侧"] = "空仓"
        row["建议挂单"] = None
        row["近买点"] = False
        row["可执行"] = False
        row["bg_class"] = "status-flat"
        if alert in ("", "-", "空仓", "待买入"):
            row["预警"] = "今日已止损·当日不买"
        # 主展示价：保留上次买入触发价
        if row.get("已触发因子侧") == "买入" and row.get("已触发因子价") is not None:
            row["因子价"] = row["已触发因子价"]
        return

    if paper and qty <= 0:
        row["持仓状态"] = "策略持有"
        row["因子侧"] = "持有"
        row["建议挂单"] = None
        row["近买点"] = False
        row["可执行"] = False
        if alert in ("", "-", "空仓"):
            row["预警"] = "策略回放持有·未登记仓"
        # 下一动作是止损
        if row.get("未触发因子侧") == "卖出" and row.get("未触发因子价") is not None:
            row["因子价"] = row["未触发因子价"]
        # 接近止损时标近止损，便于排序/推送
        near_stop = bool(row.get("近止损"))
        try:
            stop_px = float(row.get("止损") or row.get("未触发因子价") or 0)
            last = float(row.get("现价") or 0)
            if stop_px > 0 and last > 0:
                dist_pct = abs(last / stop_px - 1.0) * 100.0
                if dist_pct <= float(NEAR_FACTOR_PCT) + 1e-12 or str(
                    row.get("已触止损") or ""
                ) == "是":
                    near_stop = True
                    row["近止损"] = True
        except (TypeError, ValueError):
            pass
        row["bg_class"] = "warn-sell" if near_stop else "status-hold"
        return

    if qty > 0:
        sellable = int(row.get("可用") or 0)
        hit_stop = str(row.get("已触止损") or "") == "是"
        # 可执行=待卖出且真正有可卖股；T+1 / 可卖0 / 跌停封单 均不可执行
        row["可执行"] = (
            pos == "待卖出"
            and (not t1)
            and sellable > 0
            and "不可卖" not in alert
        )
        if hit_stop and sellable <= 0 and "不可卖" not in alert and not t1:
            row["可执行"] = False
            if alert in ("", "-", "待卖出", "已触止损"):
                row["预警"] = "已触止损·暂不可卖"
        return

    # 真·空仓
    row["可执行"] = pos == "待买入"


def _ever_held_codes() -> set[str]:
    """曾经实盘持仓过的代码：成交流水 / 止损备注 / 卖出因子记忆 / 当日已实现。"""
    codes: set[str] = set()
    data = load_holdings()
    for code, pos in (data.get("positions") or {}).items():
        if not isinstance(pos, dict):
            continue
        note = str(pos.get("note") or "")
        if any(k in note for k in ("止损", "卖出", "成交", "清仓")):
            codes.add(_code_key(code))
    for code, mem in (data.get("factor_memory") or {}).items():
        if isinstance(mem, dict) and mem.get("last_sell_factor_px") is not None:
            codes.add(_code_key(code))
    for code in data.get("realized_today") or {}:
        codes.add(_code_key(code))
    if TRADES_FILE.exists():
        try:
            for line in TRADES_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                c = rec.get("code")
                if c:
                    codes.add(_code_key(str(c)))
        except OSError:
            pass
    return codes


def sort_watch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """排序：实仓 → 曾经持仓 → 待买入 → 策略持有 → 空仓；同档 WATCHLIST 序。"""
    order = {_code_key(w["code"]): i for i, w in enumerate(WATCHLIST)}
    former = _ever_held_codes()

    def _tier(r: dict[str, Any]) -> int:
        pos = str(r.get("持仓状态") or "")
        qty = int(r.get("持仓") or 0)
        code = _code_key(str(r.get("代码") or ""))
        if qty > 0 and pos == "待卖出":
            return 0
        if qty > 0:
            return 1
        # 曾经持仓（含当日禁买）排实仓之后
        if pos == "当日禁买" or code in former:
            return 2
        if pos == "待买入":
            return 3
        if pos == "策略持有":
            return 4
        if str(r.get("因子2动作") or "") in (
            "inject",
            "withdraw",
            "add_alert",
            "reduce_alert",
            "near_max",
        ):
            return 5
        return 6

    def _urgency(r: dict[str, Any]) -> int:
        hit = str(r.get("因子触发") or "")
        pos = str(r.get("持仓状态") or "")
        if pos == "待卖出" or hit.startswith("已触发") or hit.startswith("策略止损"):
            return 0
        if pos == "当日禁买":
            return 1
        if pos == "待买入" or hit == "接近" or r.get("近止损") or r.get("近买点"):
            return 2
        return 3

    def key(r: dict[str, Any]) -> tuple[int, int, int]:
        code = _code_key(str(r.get("代码") or ""))
        idx = order.get(code, 10_000)
        return (_tier(r), _urgency(r), idx)

    return sorted(rows, key=key)


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None or v == "-":
        return "-"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return str(v)




def cmd_status(args: argparse.Namespace) -> None:
    rows = collect_rows()
    indices = fetch_indices()
    print(f"\n持仓盯盘  {_now()}")
    print(
        f"策略: {STRATEGY_NAME} · {_STRATEGY_FACTORS_LABEL} "
        f"（卖出仅保留止损）"
    )
    print(
        f"  卖出全清: 仅止损"
    )
    print(f"持仓文件: {HOLDINGS_FILE}")
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    available = _available_cash(rows, holdings_meta)
    total_mv = _holdings_market_value(rows)
    position_pct = (
        round(total_mv / account_total * 100.0, 1)
        if account_total and account_total > 0 and total_mv > 0
        else None
    )
    session_for_open = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        str(pd.Timestamp.now().date()),
    )
    today_opened = _today_opened_cost(rows, session_for_open)
    if account_total is not None:
        print(
            f"总资产: {account_total:.2f} 元 · 可用: "
            f"{available if available is not None else '-'} 元 · "
            f"仓位: {('-' if position_pct is None else f'{position_pct:.1f}%')} · "
            f"当日开仓: {today_opened:.2f} 元"
        )
    print("-" * 108)
    print("【大盘】")
    for ix in indices:
        if ix.get("error"):
            print(f"  {ix['name']}: 失败 {ix['error']}")
            continue
        pts = ix["chg_points"]
        pct = ix["chg_pct"]
        print(
            f"  {ix['market']}{ix['name']}: 点数 {_fmt_num(ix['price'])} | "
            f"涨跌点数 {('-' if pts is None else f'{pts:+.2f}')} | "
            f"涨跌幅 {('-' if pct is None else f'{pct:+.2f}%')}"
        )
    print("-" * 108)

    show_rows = []
    for r in rows:
        pdg = int(r.get("价位小数") or 2)

        def _p(v: Any, d: int = pdg) -> str:
            return "-" if v is None else _fmt_num(v, d)

        show_rows.append(
            {
                "市场": r["市场"],
                "代码": r["代码"],
                "名称": r["名称"],
                "开盘": _p(r["开盘"]),
                "现价": _p(r["现价"]),
                "当日涨幅": "-" if r["当日涨幅"] is None else r["当日涨幅"],
                "较开盘点": "-" if r["较开盘点"] is None else r["较开盘点"],
                "较开盘涨幅": "-"
                if r.get("较开盘涨幅") is None
                else f"{float(r['较开盘涨幅']):+.2f}%",
                "阈值%": r.get("阈值%"),
                "因子4": r.get("因子4") or "-",
                "牛市": r.get("牛市") or "-",
                "最高": _p(r["最高"]),
                "最低": _p(r["最低"]),
                "买点": _p(r["买点"]),
                "止损": _p(r["止损"]),
                "基础止损": _p(r.get("基础止损")),
                "已触买": r["已触买"],
                "已触止损": r["已触止损"],
                "形态": r.get("形态") or "-",
                "状态": (
                    (r.get("预警") or "-")
                    + (
                        f" {float(r['仓位%']):.1f}%"
                        if r.get("仓位%") is not None
                        else ""
                    )
                ),
                "建议挂单": _p(r.get("建议挂单")),
                "挂单说明": r.get("挂单说明") or "-",
                "持仓": r["持仓"],
                "成本": _p(r["成本"], max(3, pdg)),
                "浮盈": r["error"] if r.get("error") else ("-" if r["浮盈"] is None else r["浮盈"]),
                "浮盈%": "-" if r["浮盈%"] is None else r["浮盈%"],
                "当日盈亏": "-" if r.get("当日盈亏") is None else r["当日盈亏"],
                "当日盈亏%": "-" if r.get("当日盈亏%") is None else r["当日盈亏%"],
                "止损后最高": _p(r.get("止损后最高")),
                "止损后最低": _p(r.get("止损后最低")),
                "回抽%": "-" if r.get("回抽%") is None else r.get("回抽%"),
                "踏空": "-" if r.get("踏空金额") is None else r.get("踏空金额"),
                "更新": r["更新"],
            }
        )
    cols = [
        "市场", "代码", "名称", "开盘", "现价", "当日涨幅", "较开盘点", "较开盘涨幅", "阈值%",
        "因子4", "牛市", "最高", "最低", "买点", "止损", "基础止损", "已触买", "已触止损", "形态", "状态",
        "建议挂单", "挂单说明", "持仓", "成本", "浮盈", "浮盈%", "当日盈亏", "当日盈亏%",
        "止损后最高", "止损后最低", "回抽%", "踏空", "更新",
    ]
    print(pd.DataFrame(show_rows)[cols].to_string(index=False))
    print("-" * 108)
    day_total = 0.0
    day_n = 0
    stock_pnl = 0.0
    stock_n = 0
    for r in show_rows:
        raw = next((x for x in rows if x["代码"] == r["代码"]), {})
        if raw.get("浮盈") is not None and (
            int(raw.get("持仓") or 0) > 0 or raw.get("已实现")
        ):
            stock_pnl += float(raw["浮盈"])
            stock_n += 1
        if r["当日盈亏"] != "-":
            try:
                day_total += float(r["当日盈亏"])
                day_n += 1
            except (TypeError, ValueError):
                pass
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    account_open = _account_total_open(holdings_meta)
    if account_total is not None and account_open is not None:
        eq_pnl = round(float(account_total) - float(account_open), 2)
        eq_pct = round(eq_pnl / float(account_open) * 100.0, 2)
        print(f"合计盈亏: {eq_pnl:+.2f} ({eq_pct:+.2f}%)  [总资产 {account_total:.2f} vs 日初 {account_open:.2f}]")
    elif stock_n:
        print(f"合计盈亏: {stock_pnl:+.2f}  [持股浮盈+已结算]")
    if day_n:
        if account_open is not None and account_open > 0:
            day_pct = day_total / float(account_open) * 100.0
            pct_txt = f"{day_pct:+.2f}%"
        else:
            pct_txt = "-"
        print(f"合计当日盈亏: {day_total:+.2f} ({pct_txt})")
    else:
        print("合计当日盈亏: -")

    lock = _read_watch_lock()
    if lock:
        refresh_sec = 5
        try:
            meta = json.loads(WATCH_META_FILE.read_text(encoding="utf-8"))
            refresh_sec = int(meta.get("refreshSec") or meta.get("refresh_sec") or refresh_sec)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        path = publish_watch_snapshot(rows, indices=indices, refresh_sec=refresh_sec)[0]
        print(f"检测到盯盘进程 (pid={lock.get('pid')})，已推送 JSON 快照: {path.name}")
        url = _report_url_if_watching()
        if url:
            print(f"前端: {url}")
            if not getattr(args, "no_open", False):
                webbrowser.open(url)
    elif _watch_ui_dist_ready():
        print("提示: 启动 Web 盯盘 → python index.py watch  （生产静态页 watch-ui/dist）")
    else:
        print(
            "提示: 开发前端无需 build → "
            "python index.py watch --ui-dev  （或单独 npm run dev，见 holdingStocks/README.md）"
        )

    print(f"策略: {STRATEGY_NAME}（{_STRATEGY_SYNC_NOTE}）")
    print("说明: 当日涨幅=(现价/昨收-1)×100；较开盘涨幅=(现价/开盘-1)×100")
    print("     当日盈亏(现价盈亏): 隔夜=(现价-昨收)×持股；今买=(现价-今买成交价)×今买股数")
    print("     因子1卖出: 仅止损；已触止损=视为成交并锁定盈亏")
    print("     因子1买入过滤: 前日阴/小阳 + 禁双阳跨日≥5%；T+1 当日不可卖")
    _f2 = load_holdings().get("factor2")
    print(f"     {format_factor2_summary(_f2 if isinstance(_f2, dict) else None)}")



def cmd_set_account(args: argparse.Namespace) -> None:
    total = float(args.total)
    if total <= 0:
        raise ValueError("总资产必须 > 0")
    data = load_holdings()
    data["account_total"] = round(total, 2)
    # 若未单独登记现金，用总资产反推（需已有市值时更准，此处仅记总值）
    save_holdings(data)
    print(f"已设总资产: {data['account_total']:.2f} 元")


def cmd_set_cash(args: argparse.Namespace) -> None:
    cash = float(args.cash)
    if cash < 0:
        raise ValueError("可用现金不能为负")
    data = load_holdings()
    data["account_cash"] = round(cash, 2)
    save_holdings(data)
    print(f"已设可用现金: {data['account_cash']:.2f} 元")


def cmd_set_cost(args: argparse.Namespace) -> None:
    """仅登记/修改成本价（可不填数量）。"""
    meta = _find_meta(args.code)
    code = meta["code"]
    cost = float(args.cost)
    if cost <= 0:
        raise ValueError("成本价必须 > 0")
    data = load_holdings()
    pos = data["positions"].setdefault(code, _empty_position(meta))
    pos["cost"] = round(cost, 4)
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if args.qty is not None:
        pos["qty"] = int(args.qty)
    if getattr(args, "available", None) is not None:
        avail = int(args.available)
        qty_now = int(pos.get("qty") or 0)
        if avail < 0 or (qty_now > 0 and avail > qty_now):
            raise ValueError(f"可用数量须在 0..持仓({qty_now}) 之间")
        pos["available"] = avail
    if getattr(args, "today_cost", None) is not None:
        tc = float(args.today_cost)
        if tc <= 0:
            raise ValueError("今日买入价必须 > 0")
        pos["today_cost"] = round(tc, 4)
    if not pos.get("buy_time"):
        pos["buy_time"] = _now()
    if args.note:
        pos["note"] = args.note
    save_holdings(data)
    avail_s = pos.get("available")
    tc_s = pos.get("today_cost")
    print(
        f"已设成本: {meta['market']}{code} {meta['name']} "
        f"成本={pos['cost']} 持仓={pos.get('qty', 0)}"
        + (f" 可用={avail_s}" if avail_s is not None else "")
        + (f" 今买价={tc_s}" if tc_s is not None else "")
    )


def cmd_buy(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    price = float(args.price)
    qty = int(args.qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")

    data = load_holdings()
    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    old_cost = float(pos["cost"]) if pos.get("cost") is not None else None
    # 加仓前可卖股保留；新买部分 T+1 锁定
    if old_qty > 0:
        if pos.get("available") is not None:
            try:
                old_avail = max(0, min(int(pos["available"]), old_qty))
            except (TypeError, ValueError):
                old_avail = old_qty
        else:
            session = str(pd.Timestamp.now().date())
            old_avail = (
                0
                if is_t1_buy_day(pos.get("buy_time"), session)
                else old_qty
            )
    else:
        old_avail = 0
    locked_before = max(0, old_qty - old_avail)
    old_today = (
        float(pos["today_cost"]) if pos.get("today_cost") is not None else None
    )
    new_qty = old_qty + qty
    if old_qty > 0 and old_cost is not None:
        new_cost = (old_cost * old_qty + price * qty) / new_qty
    else:
        new_cost = price
    # 今日买入均价（仅锁定股的成交价加权）
    if locked_before > 0 and old_today is not None:
        pos["today_cost"] = round(
            (old_today * locked_before + price * qty) / (locked_before + qty), 4
        )
    else:
        pos["today_cost"] = round(price, 4)
    pos["qty"] = new_qty
    pos["cost"] = round(new_cost, 4)
    pos["available"] = int(old_avail)
    pos["buy_time"] = _now()
    if args.note:
        pos["note"] = args.note
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash - price * qty, 2)
    save_holdings(data)
    append_trade(
        {
            "time": _now(),
            "side": "buy",
            "code": code,
            "name": meta["name"],
            "price": price,
            "qty": qty,
            "after_qty": new_qty,
            "avg_cost": pos["cost"],
            "note": args.note or "",
        }
    )
    print(
        f"买入记录: {meta['market']}{code} {meta['name']} "
        f"{qty}股 @ {price:.2f} → 持仓{new_qty} 可用{pos['available']} "
        f"成本{pos['cost']:.4f} 今买价{pos['today_cost']:.4f}"
    )


def cmd_sell(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    price = float(args.price)
    qty = int(args.qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")

    data = load_holdings()
    pos = data["positions"].get(code)
    if not pos or int(pos.get("qty") or 0) <= 0:
        raise RuntimeError(f"{code} 当前无持仓")
    old_qty = int(pos["qty"])
    if qty > old_qty:
        raise RuntimeError(f"卖出数量 {qty} > 持仓 {old_qty}")
    cost = float(pos["cost"]) if pos.get("cost") is not None else price
    buy_time = pos.get("buy_time")
    pnl = (price - cost) * qty
    new_qty = old_qty - qty
    pos["qty"] = new_qty
    raw_avail = pos.get("available")
    if raw_avail is not None:
        try:
            pos["available"] = max(0, min(int(raw_avail) - qty, new_qty))
        except (TypeError, ValueError):
            pos["available"] = 0 if new_qty > 0 else None
    if new_qty == 0:
        pos["cost"] = None
        pos["buy_time"] = None
        pos["available"] = None
        pos["today_cost"] = None
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash + price * qty, 2)

    # 全清时写入当日已实现，供合计盈亏/卡片锁定展示
    session = str(pd.Timestamp.now().date())
    note = args.note or ""
    if new_qty == 0:
        _purge_stale_realized(data, session)
        reason = REASON_STOP if "止损" in note else "手动卖出"
        bought_today = is_t1_buy_day(buy_time, session)
        base_px = cost if (bought_today or cost) else price
        day_base = float(base_px) * qty
        day_pnl = (price - base_px) * qty
        day_pnl_pct = (price / base_px - 1.0) * 100.0 if base_px > 0 else None
        px_digits = 3 if abs(price) < 10 else 2
        data.setdefault("realized_today", {})[code] = {
            "session": session,
            "name": meta["name"],
            "market": meta["market"],
            "qty": int(qty),
            "price": round(price, px_digits),
            "cost": round(cost, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round((price / cost - 1.0) * 100.0, 2) if cost > 0 else None,
            "day_base": round(day_base, 2),
            "day_pnl": round(day_pnl, 2),
            "day_pnl_pct": None if day_pnl_pct is None else round(day_pnl_pct, 2),
            "reason": reason,
            "time": _now(),
        }
        pos["note"] = f"{reason}@{price} ({session})"

    save_holdings(data)
    append_trade(
        {
            "time": _now(),
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "price": price,
            "qty": qty,
            "after_qty": new_qty,
            "avg_cost": cost,
            "realized_pnl": round(pnl, 2),
            "note": note,
        }
    )
    print(
        f"卖出记录: {meta['market']}{code} {meta['name']} "
        f"{qty}股 @ {price:.2f} 实现盈亏 {pnl:.2f} → 剩余{new_qty}"
    )


def cmd_clear(args: argparse.Namespace) -> None:
    meta = _find_meta(args.code)
    code = meta["code"]
    data = load_holdings()
    pos = data["positions"].get(code)
    if not pos:
        print("无记录")
        return
    pos["qty"] = 0
    pos["cost"] = None
    pos["buy_time"] = None
    pos["available"] = None
    pos["today_cost"] = None
    pos["note"] = ""
    sticky = data.get("alert_sticky")
    if isinstance(sticky, dict):
        sticky.pop(code, None)
    save_holdings(data)
    print(f"已清空持仓: {code} {meta['name']}")


def cmd_clear_all(_: argparse.Namespace) -> None:
    """清空全部盯盘标的持仓与当日已实现、绿底粘滞。"""
    data = load_holdings()
    for w in effective_watchlist():
        data["positions"][w["code"]] = _empty_position(w)
    data["realized_today"] = {}
    data["alert_sticky"] = {}
    data["account_total"] = None
    data["account_cash"] = None
    data["account_total_open"] = None
    data["account_total_open_session"] = None
    data["last_session"] = None
    save_holdings(data)
    print(f"已清空全部持仓（{len(WATCHLIST)} 只）与当日结算记录")


def cmd_history(_: argparse.Namespace) -> None:
    if not TRADES_FILE.exists():
        print("暂无成交记录")
        return
    lines = TRADES_FILE.read_text(encoding="utf-8").strip().splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]
    if not rows:
        print("暂无成交记录")
        return
    print(pd.DataFrame(rows).to_string(index=False))


_last_auction_skip_log: float = 0.0


def _refresh_once(
    refresh_sec: int,
    *,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
    wechat: bool = False,
) -> tuple[Path, bool]:
    global _last_auction_skip_log
    rows = collect_rows(get_quote=get_quote)
    indices = fetch_indices_cached()
    path, published = publish_watch_snapshot(
        rows, indices=indices, refresh_sec=refresh_sec, get_quote=get_quote
    )
    if wechat and is_signal_window():
        try:
            from wechat_notify import notify_watch_rows

            notify_watch_rows(rows)
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 微信预警推送异常: {e}")
    elif wechat and is_auction_window():
        now_m = time.monotonic()
        if now_m - _last_auction_skip_log >= 60.0:
            _last_auction_skip_log = now_m
            ph = market_phase_label()
            print(f"[{_now()}] 早盘 {ph}；微信推送待 9:30 连续竞价")
    return path, published


def _parse_hhmm(text: str) -> tuple[int, int]:
    parts = str(text).strip().replace("：", ":").split(":")
    if len(parts) != 2:
        raise ValueError(f"时间格式应为 HH:MM，收到: {text!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"非法时间: {text!r}")
    return hour, minute


def _next_auction_milestone(
    now: datetime | None = None,
) -> tuple[datetime, str, str]:
    """下一早盘里程碑：(时刻, 标签, 动作 reseed|open|refresh)。"""
    now = now or datetime.now()
    candidates: list[tuple[datetime, str, str]] = []
    for h, m, label, action in AUCTION_MILESTONES:
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        candidates.append((t, label, action))
    return min(candidates, key=lambda x: x[0])


def _log_watchlist_opens(rows: list[dict[str, Any]]) -> None:
    by_code = {str(r.get("代码")): r for r in rows}
    print(f"[{_now()}] 开盘价定时刷新 · 盯盘 {_watchlist_codes_label()}")
    for w in effective_watchlist():
        r = by_code.get(w["code"], {})
        open_px = r.get("开盘")
        stop_px = r.get("止损")
        last_px = r.get("现价")
        print(
            f"  {w['name']}({w['code']}) "
            f"开盘={open_px if open_px is not None else '-'} "
            f"止损={stop_px if stop_px is not None else '-'} "
            f"现价={last_px if last_px is not None else '-'}"
        )


def _refresh_open_prices(
    refresh_sec: int,
    *,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[Path, bool]:
    """强制拉一次行情，用最新开盘重算买点/止损并推送 JSON 快照。"""
    rows = collect_rows(get_quote=get_quote)
    indices = fetch_indices()
    path, published = publish_watch_snapshot(
        rows, indices=indices, refresh_sec=refresh_sec, get_quote=get_quote
    )
    _log_watchlist_opens(rows)
    return path, published


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and int(code.value) == STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_watch_lock() -> dict[str, Any] | None:
    if not WATCH_PID_FILE.exists():
        return None
    try:
        raw = WATCH_PID_FILE.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            data = json.loads(raw)
            pid = int(data.get("pid") or 0)
        else:
            pid = int(raw)
            data = {"pid": pid}
        if pid and _pid_alive(pid):
            return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _acquire_watch_lock(
    *,
    host: str,
    port: int,
    ui_dev_port: int | None = None,
) -> None:
    """防止多个 watch 同时写快照，页面会来回跳变。"""
    existing = _read_watch_lock()
    if existing:
        old = int(existing.get("pid") or 0)
        if old and old != os.getpid():
            raise SystemExit(
                f"盯盘已在运行 (pid={old})。\n"
                f"请先在对应终端 Ctrl+C 停掉，再重新启动，"
                f"否则新旧进程会抢写报告。"
            )
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "host": host,
        "port": int(port),
    }
    if ui_dev_port:
        payload["uiDevPort"] = int(ui_dev_port)
    WATCH_PID_FILE.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _release_watch_lock() -> None:
    try:
        if not WATCH_PID_FILE.exists():
            return
        raw = WATCH_PID_FILE.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            cur = int(json.loads(raw).get("pid") or 0)
        else:
            cur = int(raw)
        if cur == os.getpid():
            WATCH_PID_FILE.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass


def _watch_page_url(host: str, port: int) -> str:
    return f"http://{host}:{int(port)}/"


def _tcp_port_open(host: str, port: int, *, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _watch_ui_dist_ready() -> bool:
    return (WATCH_UI_DIST / "index.html").is_file()


def _resolve_watch_ui_mode(args: argparse.Namespace) -> tuple[bool, int]:
    """是否走 Nuxt dev（:3000）及端口。无 dist 时默认 dev，无需 build。"""
    dev_port = int(getattr(args, "ui_dev_port", None) or WATCH_UI_DEV_PORT)
    force_dev = bool(getattr(args, "ui_dev", False))
    force_static = bool(getattr(args, "ui_static", False))
    env_dev = os.environ.get("WATCH_UI_DEV", "").strip().lower() in ("1", "true", "yes")
    if force_static:
        return False, dev_port
    if force_dev or env_dev or not _watch_ui_dist_ready():
        return True, dev_port
    return False, dev_port


def _start_watch_ui_dev(
    *,
    port: int,
    api_port: int,
    on_log: Callable[[str], None] | None = None,
) -> subprocess.Popen[str] | None:
    """启动 watch-ui 的 npm run dev（Nuxt 代理 /api、/ws → api_port）。"""
    if not (WATCH_UI_DIR / "package.json").is_file():
        if on_log:
            on_log("未找到 watch-ui/package.json，跳过前端 dev")
        return None
    if _tcp_port_open("127.0.0.1", port):
        if on_log:
            on_log(f"前端 dev 已在 http://127.0.0.1:{port}/ 运行（API :{api_port}）")
        return None
    if not (WATCH_UI_DIR / "node_modules").is_dir():
        if on_log:
            on_log("请先: cd holdingStocks/watch-ui && npm install")
        return None
    npm = shutil.which("npm") or shutil.which("npm.cmd") or shutil.which("npm.exe")
    if not npm:
        if on_log:
            on_log("未找到 npm，请另开终端: cd holdingStocks/watch-ui && npm run dev")
        return None
    if on_log:
        on_log(
            f"启动 Nuxt dev → http://127.0.0.1:{port}/ "
            f"（代理 /api、/ws → :{api_port}）"
        )
    env = os.environ.copy()
    env["WATCH_API_PORT"] = str(int(api_port))
    env["NUXT_PORT"] = str(int(port))
    popen_kw: dict[str, Any] = {
        "cwd": str(WATCH_UI_DIR),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "env": env,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kw["start_new_session"] = True
    try:
        proc = subprocess.Popen([npm, "run", "dev"], **popen_kw)
    except OSError as e:
        if on_log:
            on_log(f"启动 watch-ui 失败（Python API 继续）: {e}")
        return None

    def _pipe() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_log and line.strip():
                on_log(f"[watch-ui] {line.rstrip()}")

    threading.Thread(target=_pipe, daemon=True).start()
    for _ in range(60):
        if proc.poll() is not None:
            if on_log:
                on_log("watch-ui dev 进程已退出，请手动 cd watch-ui && npm run dev")
            return None
        if _tcp_port_open("127.0.0.1", port):
            return proc
        time.sleep(0.5)
    if on_log:
        on_log(f"等待 http://127.0.0.1:{port}/ 超时，请检查 watch-ui 终端输出")
    _stop_watch_ui_dev(proc)
    return None


def _stop_watch_ui_dev(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), 15)
        proc.wait(timeout=5)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired, AttributeError):
        try:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass


def _watch_browser_url(*, host: str, api_port: int, ui_dev_port: int | None) -> str:
    page_host = host if host != "0.0.0.0" else "127.0.0.1"
    if ui_dev_port:
        return _watch_page_url(page_host, ui_dev_port)
    return _watch_page_url(page_host, api_port)


def _report_url_if_watching() -> str | None:
    lock = _read_watch_lock()
    if not lock:
        return None
    host = str(lock.get("host") or "127.0.0.1")
    port = lock.get("port")
    if port is None:
        return None
    ui_dev = lock.get("uiDevPort")
    return _watch_browser_url(
        host=host,
        api_port=int(port),
        ui_dev_port=int(ui_dev) if ui_dev else None,
    )


def cmd_review(args: argparse.Namespace) -> None:
    """拉取行情，生成文字复盘，默认推送微信机器人。"""
    from market_review import (
        build_review,
        format_review_text,
        save_review,
        send_review_wechat,
    )

    rows = collect_rows()
    indices = fetch_indices()
    holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    available = _available_cash(rows, holdings_meta)
    session_for_open = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        str(pd.Timestamp.now().date()),
    )
    _ensure_account_open_session(
        holdings_meta,
        session=session_for_open,
        account_total=account_total,
    )
    holdings_meta = load_holdings()
    account_open = _account_total_open(holdings_meta)

    review = build_review(
        rows,
        indices,
        account_total=account_total,
        account_open=account_open,
        available_cash=available,
        strategy=f"{STRATEGY_NAME} · {_STRATEGY_FACTORS_LABEL}",
    )
    text = format_review_text(review)
    text_path, json_path = save_review(review, text)
    print(text)
    print("-" * 48)
    print(f"已保存: {text_path.name} / {json_path.name}")

    if getattr(args, "no_wechat", False):
        print("已跳过微信推送（--no-wechat）")
        return

    ok, detail = send_review_wechat(review, text=text)
    if ok:
        print(f"[{_now()}] 微信复盘已推送")
    else:
        print(f"[{_now()}] 微信复盘推送失败: {detail[:300]}")
        raise SystemExit(1)


def cmd_wechat_test(_: argparse.Namespace) -> None:
    from wechat_notify import send_test_alert

    ok, detail = send_test_alert()
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"

    def _out(s: str) -> None:
        print(s.encode(enc, "replace").decode(enc, "replace"))

    if ok:
        _out(f"[{_now()}] 微信自检成功")
        if detail and detail != "ok":
            _out(detail[:300])
    else:
        _out(f"[{_now()}] 微信自检失败: {(detail or '')[:400]}")
        raise SystemExit(1)


def cmd_review_schedule(args: argparse.Namespace) -> None:
    """安装/卸载/查看：周一、周五 15:00 复盘微信推送（Windows 计划任务）。"""
    action = str(getattr(args, "action", "status") or "status")
    script = ROOT / "install_review_schedule.ps1"
    if not script.is_file():
        raise SystemExit(f"缺少 {script.name}")
    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        r"System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    cmd = [
        str(ps),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        action,
    ]
    proc = subprocess.run(cmd, check=False)
    raise SystemExit(proc.returncode)


def cmd_watch(args: argparse.Namespace) -> None:
    """长驻进程：东财 SSE/新浪兜底行情 + 本地 HTTP/WS 推页。

    默认与微信套件一体：先启动 OpenClaw Gateway → 微信自检 → 再盯盘。
    """
    global _ws_hub
    interval = max(2, int(args.interval))
    host = str(args.host)
    port = int(args.port)
    use_ui_dev, ui_dev_port = _resolve_watch_ui_mode(args)
    ui_dev_proc: subprocess.Popen[str] | None = None
    wechat = not bool(getattr(args, "no_wechat", False))
    skip_wechat_check = bool(getattr(args, "skip_wechat_check", False))
    wechat_optional = bool(getattr(args, "wechat_optional", False))

    if wechat and not skip_wechat_check:
        print("=" * 48)
        print("盯盘启动套件：OpenClaw → 微信自检 → 盯盘")
        print("=" * 48)
        try:
            from wechat_notify import prepare_wechat_for_watch

            ok, detail = prepare_wechat_for_watch(
                restart_gateway=bool(getattr(args, "restart_gateway", False)),
            )
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)
        if not ok:
            print(f"[{_now()}] 微信套件失败:\n{detail[:600]}")
            if wechat_optional:
                print(f"[{_now()}] --wechat-optional：继续盯盘，但关闭微信推送")
                wechat = False
            else:
                print(
                    "中止盯盘。修好通道后重试；或临时："
                    "watch --wechat-optional / --skip-wechat-check / --no-wechat"
                )
                raise SystemExit(1)

    _acquire_watch_lock(
        host=host,
        port=port,
        ui_dev_port=ui_dev_port if use_ui_dev else None,
    )
    try:
        from stock_names import warm_name_cache

        n_names = warm_name_cache()
        print(f"[{_now()}] 股票名称缓存已预热（{n_names} 条）")
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 名称缓存预热失败（继续）: {e}")
    stop = threading.Event()
    refresh_lock = threading.Lock()
    ws_hub = LocalWsHub()
    _ws_hub = ws_hub

    sinas = [str(w["sina"]).lower() for w in effective_watchlist()]
    feed = QuoteFeedManager(
        sinas,
        on_log=lambda m: print(f"[{_now()}] {m}"),
    )

    def get_quote(sina: str) -> dict[str, Any]:
        q = feed.get_quote(sina)
        if q is None:
            q = fetch_today_quote_live(sina)
            feed.seed(sina, q)
        return q

    def reseed_live() -> int:
        return _reseed_live_batch(feed)

    def safe_refresh() -> tuple[Path, bool]:
        with refresh_lock:
            return _refresh_once(interval, get_quote=get_quote, wechat=wechat)

    def safe_open_refresh() -> tuple[Path, bool]:
        with refresh_lock:
            reseed_live()
            return _refresh_open_prices(interval, get_quote=get_quote)

    print("冷启动：新浪批量实时快照 + 预热日线…")
    try:
        t0 = time.perf_counter()
        n_fast = reseed_live()
        _daily_cache_warm()
        feed.start()
        report, _ = safe_refresh()
        elapsed = time.perf_counter() - t0
        _log_watch_snapshot_push(
            f"快照已推送: {report}（实时 {n_fast} 只 · {elapsed:.1f}s）",
            force=True,
        )
    except Exception as e:
        feed.stop()
        _ws_hub = None
        _release_watch_lock()
        print(f"首次更新失败: {e}")
        raise

    def loop() -> None:
        last = 0.0
        while not stop.is_set():
            feed.wait_update(timeout=float(interval))
            if stop.is_set():
                break
            wait_more = _MIN_WATCH_REFRESH_SEC - (time.monotonic() - last)
            if wait_more > 0 and stop.wait(wait_more):
                break
            last = time.monotonic()
            try:
                _, published = safe_refresh()
                if published:
                    _log_watch_snapshot_push(
                        f"[{_now()}] 快照已推送 → {WATCH_META_FILE.name}",
                    )
            except Exception as e:
                print(f"[{_now()}] 更新失败: {e}")

    def auction_milestone_loop() -> None:
        """每日 9:15 / 9:20 / 9:25 / 9:30 定时动作。"""
        while not stop.is_set():
            nxt, label, action = _next_auction_milestone()
            wait = (nxt - datetime.now()).total_seconds()
            print(
                f"[{_now()}] 下次早盘节点 [{label}] "
                f"@ {nxt.strftime('%Y-%m-%d %H:%M:%S')}（约 {wait:.0f}s）"
            )
            if stop.wait(max(1.0, wait)):
                break
            try:
                if action == "reseed":
                    reseed_live()
                    safe_refresh()
                elif action == "open":
                    safe_open_refresh()
                else:
                    safe_refresh()
                print(f"[{_now()}] 早盘节点 · {label}")
            except Exception as e:
                print(f"[{_now()}] 早盘节点失败 [{label}]: {e}")

    worker = threading.Thread(target=loop, name="holdings-watch", daemon=True)
    worker.start()
    milestone_worker = threading.Thread(
        target=auction_milestone_loop, name="holdings-auction-milestones", daemon=True
    )
    milestone_worker.start()

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, fmt: str, *log_args: Any) -> None:
            path = getattr(self, "path", "") or ""
            if WATCH_META_FILE.name in path or path.startswith("/api/"):
                return
            if path.split("?", 1)[0] == "/ws":
                return
            super().log_message(fmt, *log_args)

        def _send_cors_if_dev(self) -> None:
            origin = self.headers.get("Origin", "")
            if origin in ("http://127.0.0.1:3000", "http://localhost:3000"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def do_OPTIONS(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/") or path == f"/{WATCH_META_FILE.name}":
                self.send_response(204)
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self._send_cors_if_dev()
                self.end_headers()
                return
            self.send_error(404)

        def end_headers(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/") or path == f"/{WATCH_META_FILE.name}":
                self._send_cors_if_dev()
            if path in (
                f"/{WATCH_META_FILE.name}",
                "/api/snapshot",
            ):
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
            super().end_headers()

        def _send_json(self, data: Any, *, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        @staticmethod
        def _content_type(path: Path) -> str:
            ext = path.suffix.lower()
            return {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".json": "application/json; charset=utf-8",
                ".ico": "image/x-icon",
                ".png": "image/png",
                ".woff2": "font/woff2",
            }.get(ext, "application/octet-stream")

        def _serve_path(self, file_path: Path) -> None:
            if not file_path.is_file():
                self.send_error(404, "Not Found")
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", self._content_type(file_path))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _resolve_ui_file(self, path: str) -> Path | None:
            if not _watch_ui_dist_ready():
                return None
            rel = path.split("?", 1)[0].lstrip("/") or "index.html"
            candidate = (WATCH_UI_DIST / rel).resolve()
            try:
                candidate.relative_to(WATCH_UI_DIST.resolve())
            except ValueError:
                return None
            return candidate if candidate.is_file() else None

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/ws":
                self._handle_ws_upgrade()
                return
            if path.startswith("/api/sectors/"):
                status, data = _handle_sectors_api(self.path)
                self._send_json(data, status=status)
                return
            if path == "/api/strategies":
                self._send_json(_get_strategies_api_cache())
                return
            if path == "/api/factors":
                self._send_json(_get_factors_api_cache())
                return
            if path in ("/api/snapshot", f"/{WATCH_META_FILE.name}"):
                snap = _last_watch_snapshot
                if snap is None and WATCH_META_FILE.is_file():
                    try:
                        snap = json.loads(
                            WATCH_META_FILE.read_text(encoding="utf-8")
                        )
                    except (OSError, TypeError, ValueError, json.JSONDecodeError):
                        snap = None
                if snap is None:
                    self._send_json({"error": "snapshot unavailable"}, status=503)
                    return
                self._send_json(snap)
                return
            ui_file = self._resolve_ui_file(path)
            if ui_file is not None:
                self._serve_path(ui_file)
                return
            if _watch_ui_dist_ready() and path != f"/{WATCH_META_FILE.name}":
                self._serve_path(WATCH_UI_DIST / "index.html")
                return
            self.send_error(404, "Not Found")

        def _handle_ws_upgrade(self) -> None:
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self.send_error(400, "Missing Sec-WebSocket-Key")
                return
            if (self.headers.get("Upgrade") or "").lower() != "websocket":
                self.send_error(400, "Expected Upgrade: websocket")
                return
            accept = ws_accept_key(key)
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            try:
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass
            self.close_connection = True
            ws_hub.serve_client(self.connection)

    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        feed.stop()
        _ws_hub = None
        _release_watch_lock()
        raise SystemExit(
            f"端口 {host}:{port} 无法绑定（可能已有盯盘在跑）。\n"
            f"请先停掉旧进程再启动，避免抢写报告。\n{e}"
        ) from e
    url = _watch_browser_url(
        host=host,
        api_port=port,
        ui_dev_port=ui_dev_port if use_ui_dev else None,
    )
    print(f"盯盘 API 已启动: http://{host}:{port}/")
    if use_ui_dev:
        ui_dev_proc = _start_watch_ui_dev(
            port=ui_dev_port,
            api_port=port,
            on_log=lambda m: print(f"[{_now()}] {m}"),
        )
        print(
            f"前端 dev: http://127.0.0.1:{ui_dev_port}/ "
            f"（Nuxt 代理 /api、/ws → :{port}）"
        )
    elif _watch_ui_dist_ready():
        print(f"前端静态: http://{host}:{port}/ （watch-ui/dist）")
    else:
        print(
            "提示: 无 watch-ui/dist；开发请 python index.py watch --ui-dev "
            "或另开终端 cd watch-ui && npm run dev"
        )
    print(f"本地 WebSocket: ws://{host}:{port}/ws")
    print(
        f"策略同步: {STRATEGY_NAME} · {_STRATEGY_FACTORS_LABEL}"
    )
    print(
        "行情: 东财 SSE + 新浪批量实时（不拉历史分钟 K）· "
        f"刷新节流≥{_MIN_WATCH_REFRESH_SEC:.0f}s · 无推送保底 {interval}s · "
        f"快照日志每 {_WATCH_SNAPSHOT_LOG_EVERY} 次 · Ctrl+C 停止"
    )
    print(
        f"开盘价定时: 每日 9:25 锁定开盘并算阈值；里程碑 "
        f"{', '.join(f'{h:02d}:{m:02d}' for h, m, _, _ in AUCTION_MILESTONES)}"
    )
    print(
        "信号窗口: 9:15 拉竞价 · 9:25 算阈值/过门 · 9:30 起触发买卖/止损/微信；"
        "9:15–9:30 不结算止损"
    )
    print(f"当前阶段: {market_phase_label()}")
    pct_note = " / ".join(
        f"{w['code']}±{float(w['pct'])*100:.1f}%"
        for w in WATCHLIST
        if abs(float(w["pct"]) - float(DEFAULT_PCT)) > 1e-12
        or w["code"] in ("600552", "600330")
    )
    print(f"个股阈值: 默认±{DEFAULT_PCT*100:.1f}% · 焦点 {pct_note}")
    print(
        f"微信预警: {'开' if wechat else '关（--no-wechat）'} · "
        "复盘可另跑: python index.py review"
    )
    print("展示: 当日涨幅=现价/昨收；盈亏金额=持仓当日盈亏（勿与涨幅%混淆）")
    if wechat:
        try:
            from wechat_notify import send_startup_message

            ok, detail = send_startup_message(url=url)
            if ok:
                print(f"[{_now()}] 微信启动通知已推送")
            else:
                print(f"[{_now()}] 微信启动通知失败: {detail[:200]}")
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 微信启动通知异常: {e}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止盯盘")
    finally:
        stop.set()
        feed.stop()
        _ws_hub = None
        _stop_watch_ui_dev(ui_dev_proc)
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        _release_watch_lock()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="持仓记录与盯盘")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="终端查看行情+持仓（默认）")
    s.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    s.set_defaults(func=cmd_status)

    rev = sub.add_parser(
        "review",
        help="行情复盘：大盘/账户/持仓/策略事件，默认推送微信",
    )
    rev.add_argument(
        "--no-wechat",
        action="store_true",
        help="只生成本地复盘，不推送微信",
    )
    rev.set_defaults(func=cmd_review)

    wt = sub.add_parser("wechat-test", help="微信通道自检（不走大模型）")
    wt.set_defaults(func=cmd_wechat_test)

    rs = sub.add_parser(
        "review-schedule",
        help="周一/周五 15:00 复盘推送：install / uninstall / status",
    )
    rs.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("install", "uninstall", "status"),
        help="默认 status",
    )
    rs.set_defaults(func=cmd_review_schedule)

    w = sub.add_parser(
        "watch",
        help="长驻盯盘：东财SSE/新浪兜底行情 + 本地WS推页",
    )
    w.add_argument(
        "--interval",
        type=int,
        default=5,
        help="无行情时的保底刷新秒数，默认5",
    )
    w.add_argument("--host", default="127.0.0.1", help="监听地址")
    w.add_argument("--port", type=int, default=8765, help="端口，默认8765")
    w.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    w.add_argument(
        "--ui-dev",
        action="store_true",
        help="Nuxt 开发服（默认 :3000，代理 API/WS）；无 dist 时自动启用",
    )
    w.add_argument(
        "--ui-static",
        action="store_true",
        help="强制使用 watch-ui/dist 静态页（须先 npm run build）",
    )
    w.add_argument(
        "--ui-dev-port",
        type=int,
        default=WATCH_UI_DEV_PORT,
        help=f"Nuxt dev 端口，默认 {WATCH_UI_DEV_PORT}",
    )
    w.add_argument(
        "--no-wechat",
        action="store_true",
        help="关闭微信（不启 OpenClaw、不自检、不推送）",
    )
    w.add_argument(
        "--skip-wechat-check",
        action="store_true",
        help="跳过启动时的 OpenClaw/微信自检（仍推送预警）",
    )
    w.add_argument(
        "--wechat-optional",
        action="store_true",
        help="微信套件失败时仍启动盯盘（自动关推送）",
    )
    w.add_argument(
        "--restart-gateway",
        action="store_true",
        help="启动套件里强制 restart OpenClaw Gateway",
    )
    w.set_defaults(func=cmd_watch)

    b = sub.add_parser("buy", help="记录买入")
    b.add_argument("code")
    b.add_argument("price", type=float)
    b.add_argument("qty", type=int)
    b.add_argument("--note", default="")
    b.set_defaults(func=cmd_buy)

    e = sub.add_parser("sell", help="记录卖出")
    e.add_argument("code")
    e.add_argument("price", type=float)
    e.add_argument("qty", type=int)
    e.add_argument("--note", default="")
    e.set_defaults(func=cmd_sell)

    c = sub.add_parser("clear", help="清空某标的持仓")
    c.add_argument("code")
    c.set_defaults(func=cmd_clear)

    ca = sub.add_parser("clear-all", help="清空全部持仓与当日结算")
    ca.set_defaults(func=cmd_clear_all)

    sc = sub.add_parser("set-cost", help="登记/修改成本价")
    sc.add_argument("code")
    sc.add_argument("cost", type=float)
    sc.add_argument("--qty", type=int, default=None, help="可选：同时登记数量")
    sc.add_argument("--available", type=int, default=None, help="可选：可卖数量（T+1）")
    sc.add_argument(
        "--today-cost",
        type=float,
        default=None,
        help="可选：今日买入成交价（当日盈亏用，非持仓均价）",
    )
    sc.add_argument("--note", default="")
    sc.set_defaults(func=cmd_set_cost)

    sa = sub.add_parser("set-account", help="登记账户总资产")
    sa.add_argument("total", type=float, help="账户总资产（元）")
    sa.set_defaults(func=cmd_set_account)

    scash = sub.add_parser("set-cash", help="登记可用现金")
    scash.add_argument("cash", type=float, help="可用现金（元）")
    scash.set_defaults(func=cmd_set_cash)

    h = sub.add_parser("history", help="查看成交流水")
    h.set_defaults(func=cmd_history)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "cmd", None):
        # 默认走 status，并打开 HTML
        args.no_open = False
        cmd_status(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
