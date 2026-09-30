"""持仓记录与盯盘：与默认核心策略（strategy16）同步。

策略锁定 · 策略十六：
  · 买（因子26）：开盘阈值 ceil(open×(1+entry))；前日阴/小阳；禁双阳；T+1
  · 卖（因子26）：硬保护2.5%；中赚3–10%回落一半与0.5×20日日频σ谁先到走谁；阶梯10%/15%；未到3%次日峰值回落2.5%；1 分钟 path-dependent
  · 因子2：账户回撤加减仓预警（不自动改现金）
  · 因子22：收盘动量路径保留研究；**三槽执行：当日止损/已记卖出的标的当日禁再买**
  · **仓位**：物理 4 槽（盘中/隔夜均可持 4）；当日最多买 4；每槽约 25%；**先平再买**；平仓前已触买且现价≤买点+1% 优先（成交价=现价），否则其后新触发按时间（成交价=买点）
  · 9:15 清空非实仓盯盘状态；**9:15–9:30 竞价不算买卖/动态止盈、不回写峰值**；9:25 起算阈值并可挂单；9:30 起触发结算
  · 策略回放触止损 → 信号「已触止损」；有纸面持有则收敛为空仓/已平仓侧（不再「策略持有」）；当日已卖出该票不可再待买入
  · 默认交易宇宙：因子27 选股池 ∪ **公共自选池**（天通/凯盛/东材/金安，全策略共用，见 watch_config.SELF_WATCHLIST_PICKS）
  · 可选切策略七：watch_config.USE_FACTOR4=True + S7_WATCHLIST
  · 运行时分叉：本文件 collect_rows() **不**调用 get_decision_engine()；
    registry/bindings 供回测。改 bindings 后须同步本文件 FACTOR_ID 分支
    （levels / signal / replay / first_session_exit_fill）。

功能：
  · 拉取当日实时行情（SSE 热池=持仓+默认策略；新浪批量=全池含叠加观察；叠加池延后）
  · 因子26 实仓：按成本+持仓峰值算动态止盈价；1 分钟顺序判触达
  · 阈值与信号：因子26 多层止盈（与 pullback_wave_stop 同源）
  · 因子2 与 strategy/dd_alert 同源
  · 有仓：动态止盈触达自动结算；**阶梯 10% 减半**（持仓记 tp_stage + last_tp_ts，半仓后从触达分钟下一根继续盯 15%/峰值回落）。不接券商，本地只记信号与纸面数量。
  · **信号≠入槽**：触买预警见 `watch_buy_signal.py`（须过门）；槽满仍发「已触买·槽满」；未过门不算触买、不预警；自动入槽才是成交
  · 本地 JSON 记录持仓（含 peak_high / peak_high_at）；T+1 买入日不可卖
  · **时间完整性**（系统级，非个股补丁）：见 docs/TEMPORAL_INTEGRITY.md
    与 temporal_integrity.py — NO LOOK-AHEAD / HWM CAUSALITY /
    EVENT IMMUTABILITY / STALE DATA；回归 run_regression_tests.py

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
  python index.py holdings-push   # 本机账本推到 origin/holdings-ledger（给另一台 Mac/Win）
  python index.py holdings-pull   # 拉取远程账本；丢掉本机 holdings_watch.json 旧缓存
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
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, quote, unquote, urlparse

import akshare as ak
import pandas as pd
import requests

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from holdings_store import HoldingsStore, reset_container
from quote_feed import (
    LocalWsHub,
    QuoteFeedManager,
    fetch_sina_batch,
    fill_preopen_ohlc,
)
try:
    from trading_day import (  # noqa: E402
        SETTLE_KIND_POSITION,
        build_position_settlement_marks,
        current_trading_session,
        needs_session_rollover,
        overnight_preopen_quote,
        previous_trading_session,
        promote_quote_session,
        sanitize_day_change_for_session,
    )
except ImportError:  # pragma: no cover - package import path
    from holdingStocks.trading_day import (  # noqa: E402
        SETTLE_KIND_POSITION,
        build_position_settlement_marks,
        current_trading_session,
        needs_session_rollover,
        overnight_preopen_quote,
        previous_trading_session,
        promote_quote_session,
        sanitize_day_change_for_session,
    )
from strategy.akq_math import mark_unrealized, price_chg_pct, session_day_pnl, simple_return
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
    REASON_EOD_RESERVE,
    REASON_HALF,
    REASON_STOP,
    TICK_SIZE,
    bar_shape,
    entry_filters_ok,
    format_trigger_md,
    cannot_buy_limit_up,
    is_t1_buy_day,
    is_yang,
    limit_down_state,
    prev_day_allows_entry,
    replay_last_factor_triggers as _replay_f1,
    replay_strategy_return_since,
    _merge_live_daily_bar,
    should_block_entry_by_yang,
    strategy_levels as _levels_f1,
    strategy_signal as _signal_f1,
)
from strategy.pullback_wave_stop import (
    DEFAULT_ALLOW_ATTACK,
    DEFAULT_GIVEBACK_ARM_PCT,
    DEFAULT_PULLBACK_PCT,
    DEFAULT_T1_PEAK_TRAIL_PCT,
    cost_hard_stop_px,
    first_session_exit_fill,
    hit_stop_alert,
    is_half_stop_kind,
    lot_half_shares,
    overnight_open_protect_px,
    overnight_peak_px,
    overnight_session_high_ok,
    session_high_never_printed_stop,
    usable_session_high,
    path_dependent_buy_hit,
    path_dependent_pullback_hit,
    pnl_exceeds,
    pullback_stop_price,
    raise_position_peak_high,
    realized_vol_daily,
    replay_factor26_1m,
    replay_last_factor_triggers as _replay_f26,
    resolve_t1_overnight_note,
    stop_note_invalidated_by_recovery,
    strategy_levels as _levels_f26,
    strategy_signal as _signal_f26,
    t1_trail_stop_px,
    working_stop_price,
)
from strategy.data import AKSHARE_CALL_LOCK, fetch_daily, latest_completed_weekday

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
    STRATEGY_PNL_START,
    PAPER_PNL_START,
    USE_FACTOR4,
    WATCHLIST,
    effective_watchlist,
    overlay_watchlist,
    primary_watchlist,
    normalize_signal_session,
    trading_session_date,
    calc_day_pnl as _calc_day_pnl,
    code_key as _code_key,
    empty_position as _empty_position,
    find_meta as _find_meta,
    is_auction_observe,
    is_auction_quote_window,
    is_auction_result,
    is_auction_window,
    is_exit_executable,
    is_signal_window,
    is_auction_quote_ts,
    timestamp_in_signal_window,
    trust_quote_day_high,
    is_threshold_ready,
    market_phase,
    market_phase_label,
    pre_continuous_stop_ui,
    sellable_qty as _sellable_qty,
    unlock_overnight_available,
    session_open_bell_ts,
    sina_of as _sina_of,
    watchlist_codes_label as _watchlist_codes_label,
    _clock_minutes,
    SIGNAL_ACTIVE_HOUR,
    SIGNAL_ACTIVE_MINUTE,
    MAX_PORTFOLIO_SLOTS,
    MAX_OVERNIGHT_SLOTS,
    MAX_ACTIVE_SLOTS,
    MAX_BUYS_PER_DAY,
    MAX_NEW_SYMBOLS_PER_SESSION,
    MAX_POSITION_WEIGHT,
    MAX_POSITION_SYMBOLS,
    ALLOW_NEGATIVE_CASH_FOR_BUY,
    ALLOW_PYRAMIDING,
    LOT_SIZE,
    RESERVE_EMPTY_SLOTS,
    SLOT_WEIGHT,
    DEFAULT_ACCOUNT_TOTAL,
    SLOT_FIRST_TIER_MAX_OVERSHOOT,
    capital_buy_qty,
    free_slot_count,
    free_buy_slot_count,
    is_reserve_slot_window,
    occupied_slot_codes,
    slot_meta as _slot_meta_from_holdings,
    slot_fill_decision,
    peek_slot_freed_at,
    append_slot_freed_at,
    pop_slot_freed_at,
    target_position_notional,
)
from watch_snapshot import (
    SNAPSHOT_VERSION,
    account_today_return_pct,
    apply_day_linked_account_equity,
    apply_feed_health,
    build_watch_snapshot,
    clone_snapshot_for_quote_patch,
    patch_snapshot_live_quotes,
    rebase_snapshot_day_pnl,
    retain_last_snapshot,
    should_keep_last_snapshot,
    snapshot_needs_day_pnl_rebase,
)
from watch_buy_signal import (
    ALERT_FILLED,
    ALERT_HIT_BUY,
    ALERT_NOT_SLOTTED,
    ALERT_PRICE_NO_GATE,
    ALERT_SLOT_FULL,
    annotate_unfilled_buy_signals as _annotate_buy_signals_core,
    enrich_signal_single_return,
    is_actionable_unfilled_buy,
    is_buy_hit as _row_hit_buy,
    is_buy_signal_active as _buy_signal_active,
)

# 盯盘与回测共用：默认策略十六 = 因子27 + 因子26 + 因子2 + 因子22
# 默认交易池唯一真源：watch_config.WATCHLIST
FACTOR2_ID = "factor2"

_STRATEGY_FACTORS_LABEL = (
    "因子1买卖 + 因子4牛市持股"
    if USE_FACTOR4
    else "因子27核心龙头池 + 因子26多层止盈 + 因子2回撤预警 + 因子22收盘动量"
)
_STRATEGY_SYNC_NOTE = (
    "与 strategy3/strategy4 bindings / bull_regime 同源"
    if USE_FACTOR4
    else "与 strategy16 bindings / pullback_wave_stop 同源"
)


def strategy_levels(
    open_px: float,
    *,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float = DEFAULT_PCT,
    tick: float = TICK_SIZE,
    high_px: float | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """默认策略因子26：有仓按成本+峰值算动态止盈价；其它仍用开盘±。"""
    if str(FACTOR_ID) == "factor26":
        return _levels_f26(
            open_px,
            entry_pct=entry_pct,
            stop_pct=stop_pct,
            pullback_pct=stop_pct,
            high_px=high_px,
            tick=tick,
            **kw,
        )
    return _levels_f1(
        open_px, entry_pct=entry_pct, stop_pct=stop_pct, tick=tick
    )


def strategy_signal(**kw: Any) -> dict[str, Any]:
    if str(FACTOR_ID) == "factor26":
        return _signal_f26(**kw)
    kw.pop("hit_stop", None)  # 因子1 无此覆盖参
    kw.pop("hit_buy", None)
    return _signal_f1(**kw)


def replay_last_factor_triggers(*args: Any, **kw: Any) -> dict[str, Any]:
    if str(FACTOR_ID) == "factor26":
        return _replay_f26(*args, **kw)
    return _replay_f1(*args, **kw)


# 策略回放：因子26 近 N 交易日用 1m（与定盘池短窗回测一致）
_REPLAY_1M_DAYS = 7


def _m1_lookback_bars(sina: str, *, session: str) -> pd.DataFrame:
    """近若干日 1 分钟（东财一次返回约 5～8 日），供 7 日回放。"""
    key = f"lookback:{str(sina).lower()}"
    now = time.monotonic()
    hit = _M1_CACHE.get(key)
    if (
        hit
        and hit[1] == session
        and (now - hit[0]) < _M1_CACHE_TTL_SEC
        and hit[2] is not None
        and not hit[2].empty
    ):
        return hit[2]
    sk = str(sina).lower()
    em_code = sk[2:] if len(sk) >= 8 and sk[:2] in ("sh", "sz") else sk
    try:
        df = pull_akshare_1m(em_symbol=em_code, sina_symbol=sk, adjust="")
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 1m lookback 失败 {sk}: {e}")
        df = pd.DataFrame()
    if df is None or df.empty:
        _M1_CACHE[key] = (now, str(session), pd.DataFrame())
        return pd.DataFrame()
    out = df.dropna(subset=["open", "high", "low", "close"]).copy()
    out = out[
        (out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)
    ]
    if "ts" in out.columns:
        out = out.sort_values("ts")
    _M1_CACHE[key] = (now, str(session), out)
    return out


ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / "holdings.json"
TRADES_FILE = ROOT / "trades.jsonl"
WATCH_META_FILE = ROOT / "holdings_watch.json"
WATCH_PID_FILE = ROOT / "holdings_watch.pid"
WATCH_UI_DIST = ROOT / "watch-ui" / "dist"
WATCH_UI_DIR = ROOT / "watch-ui"
WATCH_UI_DEV_PORT = 3000

# 持仓态：三槽当日纸面卖出 →「今日平仓」（旧文案「已平仓/已止损」仍兼容）
STATUS_STOP_CLOSED = "今日平仓"
_STOP_CLOSED_STATUSES = frozenset(
    {STATUS_STOP_CLOSED, "已平仓", "已止损", "已触止损平仓"}
)
SIGNAL_STOP_HIT = "已触止损"
SIGNAL_HALF_HIT = "半仓止盈"


def _is_stop_closed_status(pos: str | None) -> bool:
    return str(pos or "") in _STOP_CLOSED_STATUSES


# watch 模式本地 WebSocket 广播（/ws）；非 watch 为 None
_ws_hub: LocalWsHub | None = None
_watch_feed: Any = None
_WATCH_SNAP_LOCK = threading.RLock()
_WATCH_FRONT_READY = threading.Event()
# 首屏只用热池；冷启动后再扫紫阳等叠加池，避免拖慢持仓/默认策略
_WATCH_OVERLAY_READY = threading.Event()
_last_watch_snapshot: dict[str, Any] | None = None
_last_snapshot_digest: str | None = None
_STRATEGY16B_LOCK = threading.RLock()
_STRATEGY16B_DYNAMIC: dict[str, Any] = {
    "params": {},
    "pool": {},
    "watchlist": [],
}
_HOLDINGS_CACHE: dict[str, Any] = {"data": None, "mtime": 0.0}
# 账本唯一持有者：进程内同一对象、串行写、写前版本检查、原子落盘（见 holdings_store.py）
_HOLDINGS_STORE = HoldingsStore(
    _HOLDINGS_CACHE,
    path=lambda: HOLDINGS_FILE,
    normalize=lambda d: _normalize_holdings(d),
    log=lambda m: print(f"[{_now()}] {m}"),
)


_WATCH_BOOT_STAGE = "full"  # full | primary | holdings


def _set_watch_boot_primary_only(on: bool) -> None:
    """盯盘冷启动分层：True 时信号扫描只走热池，策略一池后台补齐后再并入。"""
    _set_watch_boot_stage("primary" if on else "full")


def _set_watch_boot_stage(stage: str) -> None:
    """盯盘冷启动分层：holdings 首屏 → primary 默认策略 → full 全量。"""
    global _WATCH_BOOT_STAGE
    if stage not in {"holdings", "primary", "full"}:
        stage = "full"
    _WATCH_BOOT_STAGE = stage


def _watch_include_strategy_panels() -> bool:
    return _WATCH_BOOT_STAGE == "full"


def _holding_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """只返回持仓/今日已实现池，用于最快首屏。"""
    try:
        from watch_config import meta_for_code, portfolio_pool_codes
    except Exception:  # noqa: BLE001
        return []
    holdings = holdings or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for code in portfolio_pool_codes(holdings):
        c = _code_key(str(code))
        if not c or c in seen:
            continue
        seen.add(c)
        item = meta_for_code(c, holdings)
        item.setdefault("pool_src", "portfolio")
        item.setdefault("池来源", "持仓")
        out.append(item)
    return out


def _scan_watchlist(
    holdings: dict[str, Any] | None = None, *, full: bool = False
) -> list[dict[str, Any]]:
    """信号扫描：热池（默认交易）∪ 策略一盯盘池。

    紫阳等大观察池不进此名单（独立轻量行情）。
    冷启动阶段（``_WATCH_BOOT_PRIMARY_ONLY``）只返回热池，``full=True`` 强制全量。
    """
    from watch_config import strategy1_watchlist

    base = primary_watchlist(holdings)
    if not full and _WATCH_BOOT_STAGE == "holdings":
        return _holding_watchlist(holdings)
    if not full and _WATCH_BOOT_STAGE == "primary":
        return list(base)
    seen = {_code_key(w["code"]) for w in base}
    out = list(base)
    for w in strategy1_watchlist(holdings):
        c = _code_key(w["code"])
        if not c or c in seen:
            continue
        seen.add(c)
        item = dict(w)
        item["universe"] = "strategy1"
        item.setdefault("pool_src", "strategy1_pool")
        item.setdefault("池来源", "策略池")
        out.append(item)
    for w in _strategy16b_watchlist():
        c = _code_key(str(w.get("code") or ""))
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(dict(w))
    return out
_REPLAY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_STRATEGY_PNL_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_MIN_WATCH_REFRESH_SEC = 1.0
_INDEX_CACHE: dict[str, Any] = {"t": 0.0, "data": []}
_INDEX_CACHE_TTL_SEC = 15.0
_DAILY_WARM_WORKERS = max(4, int(os.environ.get("WATCH_DAILY_WARM_WORKERS", "12")))
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


def _factor22_binding_params() -> dict[str, Any] | None:
    """策略一绑定的因子22；未挂或关闭则 None。"""
    try:
        for b in get_strategy_bindings(STRATEGY_ID):
            if b.factor_id == "factor22" and b.enabled:
                return dict(b.params)
    except Exception:
        pass
    return None


def _factor22_rebuy_ok(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    tick: float,
) -> dict[str, Any] | None:
    """止损后收盘动量是否可再买；不可则 None。"""
    params = _factor22_binding_params()
    if not params:
        return None
    from strategy.close_momentum import rebuy_signal
    from strategy.open_break import ceil_to_tick

    out = rebuy_signal(
        open_px=float(open_px),
        high_px=float(high_px),
        low_px=float(low_px),
        close_px=float(close_px),
        bounce_pct=float(params.get("bounce_pct") or 0.01),
        candle=str(params.get("candle") or "any"),  # type: ignore[arg-type]
        mode=str(params.get("mode") or "close"),  # type: ignore[arg-type]
        tick_ceil=lambda p: ceil_to_tick(p, tick),
    )
    return out if out.get("ok") else None


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
WATCH_LIVE_TAB_IDS = frozenset(
    {"strategy1", "strategy3", "strategy8", "strategy15", "strategy16", "strategy16b", "strategy17"}
)

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
    if sid == "strategy16b":
        return "16B"
    return sid


def _strategy_tab_sort_value(strategy_id: str, meta: Mapping[str, Any] | None) -> float:
    try:
        return float((meta or {}).get("tab_order"))
    except (TypeError, ValueError):
        pass
    sid = str(strategy_id)
    if sid.startswith("strategy") and sid[8:].isdigit():
        return float(sid[8:])
    if sid == "strategy16b":
        return 16.1
    return 999.0


def _strategy_tab_primary_order(strategy_id: str, is_default: bool) -> float:
    if is_default:
        return 0.0
    if str(strategy_id) == "strategy16b":
        return 0.1
    return 1.0


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
        if spec.id == "strategy15":
            tabs[-1]["reportPath"] = "docs/STRATEGY.md"
        if spec.id == "strategy16":
            tabs[-1]["reportPath"] = "docs/FACTOR27.md"
        if spec.id == "strategy16b":
            tabs[-1]["reportPath"] = "docs/FACTOR27.md"
        if spec.id == "strategy17":
            tabs[-1]["reportPath"] = "docs/FACTOR28.md"
        from strategy_picks_loader import load_strategy_picks

        tabs[-1]["picks"] = load_strategy_picks(spec.id)
    tabs.sort(
        key=lambda t: (
            _strategy_tab_primary_order(str(t["id"]), bool(t.get("is_watch_default"))),
            _strategy_tab_sort_value(str(t["id"]), t.get("meta") if isinstance(t.get("meta"), dict) else None),
        )
    )
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
        lite = _api_bool(qs, "lite")
        try:
            data = get_concept_detail(name, months=months, refresh=refresh, lite=lite)
            if data.get("error"):
                return 404, data
            return 200, data
        except Exception as e:
            return 500, {"error": str(e)}
    return 404, {"error": "not found"}


def _calendar_signal_session() -> str:
    """账户日初/结算用的日历信号日（周一～周五为当日；周末锚定上周五）。"""
    return current_trading_session()


def _promote_quote_session(session: Any) -> str:
    """行情盘前常仍标上一交易日；信号/账户日与日历对齐。"""
    return promote_quote_session(session)


def _row_session_day(row: dict[str, Any]) -> str:
    return str(row.get("交易日") or "")[:10]


def _row_counts_in_watch_pnl(
    row: dict[str, Any],
    *,
    session: str | None = None,
) -> bool:
    """账户今日盈亏：仅实仓 + 当日真实纸面卖出（已实现/三槽平仓）。不含策略回放假平仓。

    ``session`` 给定时：隔日平仓留痕不计入（盘前行情交易日滞后时尤甚）。
    """
    if row.get("error"):
        return False
    try:
        qty = int(row.get("持仓") or 0)
    except (TypeError, ValueError):
        qty = 0
    day = str(session or "")[:10]
    row_day = _row_session_day(row)
    if qty > 0:
        return True
    if bool(row.get("已实现")) or bool(row.get("三槽平仓")):
        if day and row_day and row_day != day:
            return False
        return True
    return False


def _paper_equity_base(data: dict[str, Any] | None = None) -> float:
    """总收益基准本金：自 PAPER_PNL_START 起相对 DEFAULT_ACCOUNT_TOTAL。"""
    book = data if data is not None else load_holdings()
    locked = _as_money(book.get("paper_equity_base"))
    if locked is not None and locked > 0:
        return float(locked)
    return float(DEFAULT_ACCOUNT_TOTAL)


def _ensure_paper_equity_base(data: dict[str, Any]) -> bool:
    """首次锁定纸面本金与起算日（不覆盖已有）。返回是否改写。"""
    changed = False
    if _as_money(data.get("paper_equity_base")) is None:
        data["paper_equity_base"] = round(float(DEFAULT_ACCOUNT_TOTAL), 2)
        changed = True
    if not data.get("paper_pnl_start"):
        data["paper_pnl_start"] = str(PAPER_PNL_START)[:10]
        changed = True
    return changed


def record_daily_settlement(
    *,
    session: str,
    account: dict[str, Any],
    rows: list[dict[str, Any]] | None = None,
    force: bool = False,
) -> bool:
    """每个交易日最多记一次终稿结算核对（收盘后或次日 9:15 补记）。

    盘中可写/更新草稿（不刷屏）；已有 final 且非 force 则跳过。
    """
    day = str(session or "")[:10]
    if len(day) < 10:
        return False
    data = load_holdings()
    if _ensure_paper_equity_base(data):
        pass  # 与结算一并落盘
    book = data.get("daily_settlements")
    if not isinstance(book, dict):
        book = {}
    existing = book.get(day) if isinstance(book.get(day), dict) else None
    if existing and existing.get("final") and not force:
        return False
    phase = market_phase()
    is_final = phase == "closed" or force

    pos_lines: list[dict[str, Any]] = []
    closed_lines: list[dict[str, Any]] = []
    for r in rows or []:
        try:
            qty = int(r.get("持仓") or 0)
        except (TypeError, ValueError):
            qty = 0
        code = _code_key(str(r.get("代码") or ""))
        if not code:
            continue
        if qty > 0:
            pos_lines.append(
                {
                    "code": code,
                    "name": r.get("名称"),
                    "qty": qty,
                    "cost": r.get("成本"),
                    "last": r.get("现价"),
                    "day_pnl": r.get("当日盈亏"),
                    "upnl": r.get("浮盈"),
                }
            )
        elif bool(r.get("已实现")):
            closed_lines.append(
                {
                    "code": code,
                    "name": r.get("名称"),
                    "qty": r.get("卖出数量"),
                    "price": r.get("成交价") or r.get("平仓价"),
                    "cost": r.get("成本"),
                    "day_pnl": r.get("当日盈亏"),
                    "pnl": r.get("浮盈"),
                }
            )
    day_pnl = account.get("dayPnl")
    equity_day = account.get("equityDayPnl")
    delta = None
    if day_pnl is not None and equity_day is not None:
        delta = round(float(day_pnl) - float(equity_day), 2)
    rec = {
        "session": day,
        "recorded_at": _now(),
        "final": bool(is_final),
        "draft": not is_final,
        # POSITION_SETTLEMENT：收盘盯市；绝非 POSITION_EXIT / SELL
        "settle_kind": SETTLE_KIND_POSITION,
        "account_total": account.get("accountTotal"),
        "account_open": account.get("accountOpen"),
        "paper_equity_base": account.get("paperEquityBase") or _paper_equity_base(data),
        "paper_pnl_start": account.get("totalPnlStart") or PAPER_PNL_START,
        "day_pnl": day_pnl,
        "day_pnl_pct": account.get("dayPnlPct"),
        "equity_day_pnl": equity_day,
        "day_pnl_vs_equity": delta,
        "total_pnl": account.get("totalPnl"),
        "total_pnl_pct": account.get("totalPnlPct"),
        "settled_count": account.get("settledCount") or 0,
        "settled_day_pnl": account.get("settledDayPnl"),
        "positions": pos_lines,
        "closing_marks": build_position_settlement_marks(rows),
        "closed_today": closed_lines,
    }
    # 草稿无变化则不写盘
    if existing and not is_final:
        keys = (
            "day_pnl",
            "equity_day_pnl",
            "total_pnl",
            "account_total",
            "settled_count",
        )
        if all(existing.get(k) == rec.get(k) for k in keys):
            return False
    book[day] = rec
    data["daily_settlements"] = book
    save_holdings(data)
    if is_final:
        print(
            f"[{_now()}] 日结算终稿 {day} · 今日盈亏={day_pnl} · "
            f"权益日变={equity_day} · 差额={delta} · 总收益={account.get('totalPnl')}"
        )
    return True


def maybe_record_daily_settlement(
    rows: list[dict[str, Any]],
    account: dict[str, Any],
    *,
    session: str | None = None,
) -> None:
    """收盘后记终稿；盘中仅在数字变化时更新草稿。"""
    sess = normalize_signal_session(session or trading_session_date())
    record_daily_settlement(session=sess, account=account, rows=rows, force=False)


def settle_previous_session_if_needed(*, session: str | None = None) -> None:
    """9:15 重置前：若上一交易日无终稿结算，用草稿/账本补记一笔 final。"""
    sess = normalize_signal_session(session or trading_session_date())
    data = load_holdings()
    book = data.get("daily_settlements")
    if not isinstance(book, dict):
        book = {}
    candidates: list[str] = []
    open_sess = str(data.get("account_total_open_session") or "")[:10]
    last_sess = str(data.get("last_session") or "")[:10]
    for s in (open_sess, last_sess):
        if len(s) >= 10 and s < sess:
            candidates.append(s)
    for day, rec in book.items():
        if isinstance(rec, dict) and not rec.get("final") and str(day)[:10] < sess:
            candidates.append(str(day)[:10])
    prev = max(candidates) if candidates else None
    if not prev:
        return
    existing = book.get(prev)
    if isinstance(existing, dict) and existing.get("final"):
        return
    acc = {
        "accountTotal": data.get("account_total"),
        "accountOpen": data.get("account_total_open"),
        "paperEquityBase": _paper_equity_base(data),
        "totalPnlStart": data.get("paper_pnl_start") or PAPER_PNL_START,
        "dayPnl": (existing or {}).get("day_pnl") if isinstance(existing, dict) else None,
        "dayPnlPct": (existing or {}).get("day_pnl_pct") if isinstance(existing, dict) else None,
        "equityDayPnl": (existing or {}).get("equity_day_pnl")
        if isinstance(existing, dict)
        else None,
        "totalPnl": (existing or {}).get("total_pnl") if isinstance(existing, dict) else None,
        "totalPnlPct": (existing or {}).get("total_pnl_pct")
        if isinstance(existing, dict)
        else None,
        "settledCount": (existing or {}).get("settled_count")
        if isinstance(existing, dict)
        else 0,
        "settledDayPnl": (existing or {}).get("settled_day_pnl")
        if isinstance(existing, dict)
        else None,
    }
    if acc["totalPnl"] is None and acc["accountTotal"] is not None:
        base = float(acc["paperEquityBase"] or DEFAULT_ACCOUNT_TOTAL)
        acc["totalPnl"] = round(float(acc["accountTotal"]) - base, 2)
        acc["totalPnlPct"] = round(acc["totalPnl"] / base * 100.0, 2) if base else None
    record_daily_settlement(session=prev, account=acc, rows=[], force=True)


def _day_pnl_for_account_row(
    row: dict[str, Any],
    *,
    session: str,
) -> float | None:
    """账户加总用的单票当日盈亏：隔日平仓不计；昨仓交易日滞后时按昨收重算。"""
    if not _row_counts_in_watch_pnl(row, session=session):
        return None
    try:
        qty = int(row.get("持仓") or 0)
    except (TypeError, ValueError):
        qty = 0
    row_day = _row_session_day(row)
    if qty > 0 and row_day and row_day < str(session)[:10]:
        try:
            last_f = float(row["现价"]) if row.get("现价") is not None else None
            cost_f = float(row["成本"]) if row.get("成本") is not None else None
        except (TypeError, ValueError):
            return None
        day_pnl, _, _ = session_day_pnl(
            mark=last_f,
            qty=qty,
            cost=cost_f,
            prev_close=row.get("昨收"),
            bought_today=False,
            fallback=None,
        )
        return float(day_pnl) if day_pnl is not None else None
    if row.get("当日盈亏") is None:
        return None
    try:
        return float(row["当日盈亏"])
    except (TypeError, ValueError):
        return None


def _build_watch_account_summary(
    rows: list[dict[str, Any]],
    *,
    session: str | None = None,
) -> dict[str, Any]:
    """账户合计（JSON 快照 / CLI 共用口径）。

    · 今日盈亏：实仓 session_day_pnl + 当日已实现 day_pnl（只认今日平仓）
    · 总资产：日初锁定 + 今日盈亏（与分票加总同动；回退现金+市值）
    · 总收益：总资产 − 纸面本金（自 PAPER_PNL_START / 默认 9/9）
    · 日初锚 session 默认用日历信号日，不用行情滞后的行上「交易日」
    """
    session_for_open = (
        str(session)[:10] if session else _calendar_signal_session()
    )
    total_day_pnl = 0.0
    total_mv = 0.0
    total_mv_no_cost = 0.0
    total_cost = 0.0
    settled_pnl = 0.0
    settled_day = 0.0
    settled_n = 0
    has_day = False
    for r in rows:
        qty = int(r.get("持仓") or 0)
        realized = bool(r.get("已实现"))
        in_pnl = _row_counts_in_watch_pnl(r, session=session_for_open)
        day_v = _day_pnl_for_account_row(r, session=session_for_open)
        if day_v is not None and in_pnl:
            total_day_pnl += day_v
            has_day = True
        if realized and in_pnl:
            settled_n += 1
            if r.get("浮盈") is not None:
                settled_pnl += float(r["浮盈"])
            if day_v is not None:
                settled_day += day_v
        if r.get("市值") is not None and qty > 0:
            mv = float(r["市值"])
            total_mv += mv
            if r.get("成本额") is None:
                total_mv_no_cost += mv
        # 账户「成本」= 当前剩余持仓成本额，不含今日已平仓成本。
        if r.get("成本额") is not None and qty > 0:
            total_cost += float(r["成本额"])
    holdings_meta = load_holdings()
    if _ensure_paper_equity_base(holdings_meta):
        save_holdings(holdings_meta)
        holdings_meta = load_holdings()
    account_total = _account_total(rows, holdings_meta)
    available_cash = _available_cash(rows, holdings_meta)
    _ensure_account_open_session(
        holdings_meta,
        session=session_for_open,
        account_total=account_total,
    )
    holdings_meta = load_holdings()
    account_open = _account_total_open(holdings_meta)
    equity_base = _paper_equity_base(holdings_meta)
    total_pnl = (
        round(float(account_total) - float(equity_base), 2)
        if account_total is not None and equity_base > 0
        else None
    )
    total_pnl_pct = (
        round(float(total_pnl) / float(equity_base) * 100.0, 2)
        if total_pnl is not None and equity_base > 0
        else None
    )
    # 有日初锁定时，用权益日变化做结算核对（展示仍用分票加总）
    equity_day = None
    if (
        account_total is not None
        and account_open is not None
        and str(holdings_meta.get("account_total_open_session") or "")[:10]
        == str(session_for_open)[:10]
    ):
        equity_day = round(float(account_total) - float(account_open), 2)
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
    day_pnl_out = round(total_day_pnl, 2) if has_day else None
    summary = {
        "totalPnl": total_pnl,
        "totalPnlPct": total_pnl_pct,
        "totalPnlStart": str(
            holdings_meta.get("paper_pnl_start") or PAPER_PNL_START
        )[:10],
        "paperEquityBase": equity_base,
        "dayPnl": day_pnl_out,
        "dayPnlPct": account_today_return_pct(day_pnl_out, account_open),
        "equityDayPnl": equity_day,
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
    # 日初已锁定时：总资产/总收益 = 日初 + 今日盈亏（动态并入）
    open_sess = str(holdings_meta.get("account_total_open_session") or "")[:10]
    if (
        day_pnl_out is not None
        and account_open is not None
        and open_sess == str(session_for_open)[:10]
    ):
        summary = apply_day_linked_account_equity(summary)
    return summary


def _snapshot_business_digest(snapshot: dict[str, Any]) -> str:
    """快照业务指纹（不含 clock/ts，用于去重写盘/WS）。"""
    payload = {
        "account": snapshot.get("account"),
        "indices": snapshot.get("indices"),
        "holdings": snapshot.get("holdings"),
        "strategy1": snapshot.get("strategy1"),
        "strategy3": snapshot.get("strategy3"),
        "strategy8": (
            {k: v for k, v in snapshot["strategy8"].items() if k != "themeUpdatedAt"}
            if isinstance(snapshot.get("strategy8"), dict)
            else snapshot.get("strategy8")
        ),
        "strategy15": snapshot.get("strategy15"),
        "strategy16": snapshot.get("strategy16"),
        "strategy16b": snapshot.get("strategy16b"),
        "strategy17": snapshot.get("strategy17"),
        "phaseKey": snapshot.get("phaseKey"),
        "strategy": snapshot.get("strategy"),
        "strategyTabs": [
            str(t.get("id") or "")
            for t in (snapshot.get("strategies") or [])
            if isinstance(t, dict)
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_WATCH_TABS_CACHE: dict[str, Any] = {"t": 0.0, "tabs": []}


def _watch_tabs_with_live_s8(strategy8: dict[str, Any]) -> list[dict[str, Any]]:
    from strategy8_watch import live_picks_from_payload
    from strategy_picks_loader import merge_public_self_picks

    now_m = time.monotonic()
    cached = _WATCH_TABS_CACHE.get("tabs") or []
    if (not cached) or (now_m - float(_WATCH_TABS_CACHE.get("t") or 0)) > 60.0:
        cached = [dict(t) for t in _get_strategies_api_cache() if t.get("watch_tab")]
        _WATCH_TABS_CACHE["t"] = now_m
        _WATCH_TABS_CACHE["tabs"] = cached
    tabs = [dict(t) for t in cached]
    for t in tabs:
        if t.get("id") == "strategy8":
            t["picks"] = merge_public_self_picks(
                live_picks_from_payload(strategy8), "strategy8"
            )
    return tabs


def _query_bool(qs: Mapping[str, list[str]], key: str, default: bool) -> bool:
    raw = (qs.get(key) or [str(default)])[0]
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "y")


def _query_int(
    qs: Mapping[str, list[str]],
    key: str,
    default: int,
    *,
    lo: int,
    hi: int,
) -> int:
    try:
        val = int((qs.get(key) or [default])[0])
    except (TypeError, ValueError):
        val = int(default)
    return max(int(lo), min(int(hi), val))


def _query_float_or_none(
    qs: Mapping[str, list[str]],
    key: str,
    default: float | None,
    *,
    lo: float,
    hi: float,
) -> float | None:
    raw = (qs.get(key) or [default])[0]
    if raw is None or str(raw).strip().lower() in ("", "none", "null", "0", "不限"):
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    return max(float(lo), min(float(hi), val))


def _strategy16b_select_params(path: str) -> dict[str, Any]:
    qs = parse_qs(urlparse(path).query)
    return {
        "horizon_months": _query_int(qs, "horizonMonths", 3, lo=1, hi=12),
        "max_concepts": _query_int(qs, "maxConcepts", 40, lo=5, hi=120),
        "per_concept": _query_int(qs, "perConcept", 2, lo=1, hi=5),
        "target_pool": _query_int(qs, "targetPool", 30, lo=5, hi=100),
        "price_max": _query_float_or_none(qs, "priceMax", 100.0, lo=1.0, hi=1000.0),
        "exclude_st": _query_bool(qs, "excludeSt", True),
        "exclude_chinext": _query_bool(qs, "excludeChinext", True),
        "exclude_star": _query_bool(qs, "excludeStar", True),
        "exclude_bse": _query_bool(qs, "excludeBse", True),
    }


def _strategy16b_picks_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for i, it in enumerate(payload.get("picks") or [], 1):
        if not isinstance(it, Mapping):
            continue
        code = _code_key(str(it.get("code") or ""))
        if not code:
            continue
        items.append(
            {
                "rank": int(it.get("rank") or i),
                "symbol": code,
                "code": code,
                "name": str(it.get("name") or ""),
                "category": "条件选股",
                "分类": "条件选股",
                "pool_src": "strategy16b",
                "concept": it.get("concepts") or it.get("concept"),
                "price": it.get("price"),
                "chg_pct": it.get("chg_pct"),
                "amount": it.get("amount"),
            }
        )
    return {
        "kind": "pool",
        "asOf": payload.get("as_of") or payload.get("label"),
        "source": str(payload.get("source") or "strategy16b_dynamic"),
        "note": str(payload.get("note") or ""),
        "items": items,
    }


def _strategy16b_watch_items_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        from watch_config import load_strategy16_thr_map, meta_for_code
    except Exception:  # noqa: BLE001
        return []
    thrs = load_strategy16_thr_map()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in payload.get("picks") or []:
        if not isinstance(it, Mapping):
            continue
        code = _code_key(str(it.get("code") or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        item = meta_for_code(code)
        if it.get("name"):
            item["name"] = str(it.get("name") or "")
        item["universe"] = "strategy16b"
        item["pool_src"] = "strategy16b"
        item["池来源"] = "条件选股"
        item["concept"] = it.get("concepts") or it.get("concept")
        thr = thrs.get(code)
        if thr is not None:
            item["pct"] = float(thr)
            item["entry_pct"] = float(thr)
            item["stop_pct"] = float(DEFAULT_PCT)
        out.append(item)
    return out


def _set_strategy16b_dynamic(params: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    global _last_snapshot_digest
    with _STRATEGY16B_LOCK:
        _STRATEGY16B_DYNAMIC["params"] = dict(params)
        _STRATEGY16B_DYNAMIC["pool"] = dict(payload)
        _STRATEGY16B_DYNAMIC["watchlist"] = _strategy16b_watch_items_from_payload(payload)
    _last_snapshot_digest = None


def _strategy16b_watchlist() -> list[dict[str, Any]]:
    with _STRATEGY16B_LOCK:
        return [dict(w) for w in (_STRATEGY16B_DYNAMIC.get("watchlist") or [])]


def _strategy16b_codes() -> set[str]:
    return {_code_key(str(w.get("code") or "")) for w in _strategy16b_watchlist()}


def _strategy16b_rows_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    codes = _strategy16b_codes()
    if not codes:
        return []
    meta_by_code = {
        _code_key(str(w.get("code") or "")): w
        for w in _strategy16b_watchlist()
    }
    out: list[dict[str, Any]] = []
    for r in rows:
        code = _code_key(str(r.get("代码") or ""))
        if code not in codes:
            continue
        row = dict(r)
        meta = meta_by_code.get(code) or {}
        row["pool_src"] = "strategy16b"
        row["池来源"] = "条件选股"
        if meta.get("concept"):
            row["concept"] = meta.get("concept")
        out.append(row)
    return out


def _handle_strategy16b_api(path: str) -> tuple[int, Any]:
    try:
        from strategy.core_leader_universe import build_quarter_pool

        params = _strategy16b_select_params(path)
        payload = build_quarter_pool(fetch=True, **params)
        _set_strategy16b_dynamic(params, payload)
        return 200, {
            "strategyId": "strategy16b",
            "params": params,
            "pool": payload,
            "picks": _strategy16b_picks_from_payload(payload),
        }
    except Exception as exc:  # noqa: BLE001
        return 500, {"error": "strategy16b select failed", "detail": str(exc)}


def _current_feed_health() -> dict[str, Any]:
    feed = _watch_feed
    if feed is None:
        return {"feedOk": True, "quoteStale": False, "quoteAt": None, "quoteAgeSec": None}
    try:
        return feed.quote_health()
    except Exception:  # noqa: BLE001
        return {"feedOk": False, "quoteStale": True, "quoteAt": None, "quoteAgeSec": None}


def _stamp_snapshot_liveness(snap: dict[str, Any], *, clock: str | None = None) -> dict[str, Any]:
    """刷新进程时钟，并按行情源是否还在收外网数据打 quoteStale。"""
    clock_now = clock or _now()
    snap["clock"] = clock_now
    snap["updatedAt"] = clock_now
    snap["ts"] = int(datetime.now().timestamp() * 1000)
    return apply_feed_health(snap, _current_feed_health())


def _broadcast_watch_snapshot(snap: dict[str, Any]) -> None:
    body = json.dumps(snap, ensure_ascii=False)
    hub = _ws_hub
    if hub is None:
        return
    try:
        hub.broadcast_text(body)
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] WS 广播失败: {e}")


_QUOTE_PATCH_MIN_SEC = 0.4


def _peak_at_clock(raw: Any) -> str | None:
    """peak_high_at → HH:MM:SS（仅展示）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) >= 19 and s[10] in (" ", "T"):
        return s[11:19]
    if len(s) == 8 and s[2] == ":" and s[5] == ":":
        return s
    return s


def _sanitize_quote_session_high(
    q: dict[str, Any],
    *,
    path_running_high: float = 0.0,
) -> dict[str, Any]:
    """就地清洗 quote.high：竞价/开盘脏窗丢掉 API 虚高，改用已印出最高。"""
    if not isinstance(q, dict):
        return q
    try:
        raw = float(q.get("high") or 0)
    except (TypeError, ValueError):
        raw = 0.0
    try:
        open_px = float(q.get("open") or 0)
    except (TypeError, ValueError):
        open_px = 0.0
    try:
        last_px = float(q.get("last") or 0)
    except (TypeError, ValueError):
        last_px = 0.0
    ts = q.get("last_ts") or q.get("ts") or q.get("time")
    q["high"] = usable_session_high(
        quote_high=raw,
        open_px=open_px,
        last_px=last_px,
        path_running_high=path_running_high,
        trust_api_high=trust_quote_day_high(ts),
    )
    return q


def _peak_high_usable_for_overnight(
    pos: dict[str, Any] | None,
    session: str,
) -> float | None:
    """隔夜峰值不得用「今日竞价戳」的 peak_high（竞价虚高）。"""
    if not isinstance(pos, dict):
        return None
    at = str(pos.get("peak_high_at") or "")
    sess = str(session or "")[:10]
    if sess and at[:10] == sess and is_auction_quote_ts(at):
        return None
    try:
        peak = float(pos.get("peak_high") or 0)
    except (TypeError, ValueError):
        peak = 0.0
    return peak if peak > 0 else None


def _clamp_auction_stamped_hwm(
    pos: dict[str, Any],
    *,
    session: str,
    cost: float = 0.0,
    prev_close: float = 0.0,
    open_px: float = 0.0,
    last_px: float = 0.0,
) -> bool:
    """今日竞价窗口抬上去的 peak_high 压回已印出价（只此例外允许 HWM 下降）。"""
    if not isinstance(pos, dict):
        return False
    sess = str(session or "")[:10]
    at = str(pos.get("peak_high_at") or "")
    if not sess or at[:10] != sess or not is_auction_quote_ts(at):
        return False
    try:
        peak = float(pos.get("peak_high") or 0)
    except (TypeError, ValueError):
        peak = 0.0
    cap = 0.0
    for x in (cost, prev_close, open_px, last_px):
        try:
            v = float(x or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > cap:
            cap = v
    if cap <= 0 or peak <= cap + 1e-9:
        return False
    pos["peak_high"] = round(float(cap), 4)
    pos["peak_high_at"] = f"{sess} 09:30:00"
    return True


def _stamp_position_peak_high(
    pos: dict[str, Any],
    new_peak: float,
    *,
    at: str | None = None,
    decision_at: str | None = None,
) -> bool:
    """持仓 HWM 只升不降；抬升时原子写入 peak_high + peak_high_at。

    新抬升必须带 at；禁止未卜先知（at > decision_at → FUTURE_DATA_VIOLATION）。
    """
    from temporal_integrity import (
        TemporalIntegrityError,
        migrate_legacy_peak_high_at,
        stamp_peak_high_atomic,
    )

    migrate_legacy_peak_high_at(pos)
    at_s = str(at or "").strip()
    if not at_s:
        # 兼容旧调用：用 decision_at / now，但不得静默缺时间
        at_s = str(decision_at or _now()).strip()
    try:
        return stamp_peak_high_atomic(
            pos, new_peak, at=at_s, decision_at=decision_at or at_s
        )
    except TemporalIntegrityError:
        raise


def _attach_hwm_row_fields(
    row: dict[str, Any],
    pos: dict[str, Any] | None,
    *,
    px_digits: int,
) -> None:
    """写入今日最高 / 持仓最高 / 持仓最高时间。禁止前端重算。

    · 最高 / 今日最高 = API dayHigh（行情）
    · 持仓最高 / 峰值 = positions.peak_high（trailing SoT）
    """
    day_h = row.get("最高")
    if day_h is not None:
        try:
            row["今日最高"] = round(float(day_h), px_digits)
        except (TypeError, ValueError):
            row["今日最高"] = day_h
    ph = 0.0
    if isinstance(pos, dict):
        try:
            from temporal_integrity import migrate_legacy_peak_high_at

            migrate_legacy_peak_high_at(pos)
        except Exception:  # noqa: BLE001
            pass
        try:
            ph = float(pos.get("peak_high") or 0)
        except (TypeError, ValueError):
            ph = 0.0
    if ph <= 0:
        try:
            ph = float(row.get("持仓最高") or row.get("峰值") or 0)
        except (TypeError, ValueError):
            ph = 0.0
    if ph > 0:
        px = round(ph, px_digits)
        row["持仓最高"] = px
        row["峰值"] = px
        at_raw = (pos or {}).get("peak_high_at") if isinstance(pos, dict) else None
        if not at_raw:
            at_raw = row.get("持仓最高时间")
        clock = _peak_at_clock(at_raw)
        if clock:
            row["持仓最高时间"] = clock
    else:
        row.setdefault("持仓最高", None)
        row.setdefault("峰值", None)


def _iter_snapshot_price_rows(snap: dict[str, Any]):
    for key in ("holdings", "strategy1", "strategy16", "strategy17"):
        for r in snap.get(key) or []:
            if isinstance(r, dict):
                yield r
    s15 = snap.get("strategy15")
    if isinstance(s15, list):
        for r in s15:
            if isinstance(r, dict):
                yield r
    elif isinstance(s15, dict):
        for r in s15.get("rows") or s15.get("stocks") or []:
            if isinstance(r, dict):
                yield r


def _sync_snapshot_hwm_from_quotes(
    snap: dict[str, Any],
    *,
    get_quote: Callable[[str], dict[str, Any] | None],
) -> bool:
    """快刷路径：用与 collect 相同的 raise_position_peak_high 抬升 HWM，并刷新卖出侧展示价。

    不触发 paper 卖出；只保证 UI 的持仓最高 / 卖出侧价与 holdings.peak_high 同源。
    """
    from watch_config import sina_of

    # 快刷线程与扫描线程并发改同一账本对象：改+写整段串行
    with _HOLDINGS_STORE.transaction():
        return _sync_snapshot_hwm_locked(snap, get_quote=get_quote, sina_of=sina_of)


def _sync_snapshot_hwm_locked(
    snap: dict[str, Any],
    *,
    get_quote: Callable[[str], dict[str, Any] | None],
    sina_of: Callable[[str], str],
) -> bool:
    data = load_holdings()
    positions = data.get("positions")
    if not isinstance(positions, dict):
        positions = data["positions"] = {}
    dirty = False
    changed = False
    for r in _iter_snapshot_price_rows(snap):
        code = _code_key(str(r.get("代码") or ""))
        if not code:
            continue
        pos = positions.get(code)
        if not isinstance(pos, dict):
            pos = {}
        try:
            px_digits = int(r.get("价位小数") or 2)
        except (TypeError, ValueError):
            px_digits = 2
        day_h = r.get("最高")
        if day_h is not None:
            try:
                r["今日最高"] = round(float(day_h), px_digits)
            except (TypeError, ValueError):
                r["今日最高"] = day_h
        try:
            qty = int(pos.get("qty") or r.get("持仓") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            before = r.get("持仓最高")
            _attach_hwm_row_fields(r, pos if pos else None, px_digits=px_digits)
            if r.get("持仓最高") != before:
                changed = True
            continue
        try:
            q = get_quote(sina_of(code)) or {}
        except Exception:  # noqa: BLE001
            q = {}
        try:
            last_h = float(q.get("last") or r.get("现价") or 0)
        except (TypeError, ValueError):
            last_h = 0.0
        try:
            snap_h = float(q.get("high") or r.get("最高") or 0)
        except (TypeError, ValueError):
            snap_h = 0.0
        try:
            cost_h = float(pos.get("cost") or r.get("成本") or 0)
        except (TypeError, ValueError):
            cost_h = 0.0
        try:
            old_peak = float(pos.get("peak_high") or 0)
        except (TypeError, ValueError):
            old_peak = 0.0
        sess = str(q.get("session") or r.get("交易日") or "")[:10]
        t1_today = is_t1_buy_day(pos.get("buy_time"), sess) if sess else False
        quote_at = _bar_ts_str(q.get("last_ts")) or _now()
        decision_at = quote_at
        last_q_at = pos.get("last_quote_at")
        try:
            from temporal_integrity import (
                TemporalIntegrityError,
                assert_quote_usable,
                migrate_legacy_peak_high_at,
            )

            migrate_legacy_peak_high_at(pos)
            assert_quote_usable(
                quote_at=quote_at,
                decision_at=decision_at,
                last_accepted_quote_at=last_q_at,
            )
        except TemporalIntegrityError as te:
            print(f"[{_now()}] {te.code} quote skipped {code}: {te}")
            before_hwm = r.get("持仓最高")
            _attach_hwm_row_fields(r, pos, px_digits=px_digits)
            if r.get("持仓最高") != before_hwm:
                changed = True
            continue
        try:
            open_h = float(q.get("open") or r.get("开盘") or 0)
        except (TypeError, ValueError):
            open_h = 0.0
        try:
            prev_h = float(q.get("prev_close") or r.get("昨收") or 0)
        except (TypeError, ValueError):
            prev_h = 0.0
        if _clamp_auction_stamped_hwm(
            pos,
            session=sess,
            cost=cost_h,
            prev_close=prev_h,
            open_px=open_h,
            last_px=last_h,
        ):
            dirty = True
            changed = True
            positions[code] = pos
            old_peak = float(pos.get("peak_high") or 0)
        # 竞价虚拟价不得抬 HWM；开盘后前几秒 API high 仍可能是竞价残留
        quote_in_cont = timestamp_in_signal_window(quote_at)
        if is_signal_window() and quote_in_cont:
            snap_h = usable_session_high(
                quote_high=snap_h,
                open_px=open_h,
                last_px=last_h,
                trust_api_high=trust_quote_day_high(quote_at),
            )
            new_peak = raise_position_peak_high(
                persisted_peak=old_peak,
                entry_price=cost_h if cost_h > 0 else None,
                quote_last=last_h,
                quote_day_high=snap_h,
                path_running_high=old_peak,
                allow_quote_day_high=not bool(t1_today),
            )
            try:
                if _stamp_position_peak_high(
                    pos, new_peak, at=quote_at, decision_at=decision_at
                ):
                    dirty = True
                    changed = True
                    positions[code] = pos
            except TemporalIntegrityError as te:
                print(f"[{_now()}] {te.code} HWM raise blocked {code}: {te}")
        pos["last_quote_at"] = quote_at
        before_hwm = r.get("持仓最高")
        _attach_hwm_row_fields(r, pos, px_digits=px_digits)
        if r.get("持仓最高") != before_hwm:
            changed = True
    if dirty:
        save_holdings(data)
    return changed


def publish_live_quote_patch() -> bool:
    """盘中行情快刷：现价/涨跌幅/持仓盈亏，不重跑 collect_rows。

    与全量扫描并行；若扫描已换了更新快照则丢弃本轮 patch，避免旧信号盖新。
    """
    global _last_watch_snapshot
    feed = _watch_feed
    if feed is None:
        return False
    base = _last_watch_snapshot
    if not isinstance(base, dict) or base.get("type") != "snapshot":
        return False
    snap = clone_snapshot_for_quote_patch(base)
    try:
        from watch_config import sina_of

        changed = patch_snapshot_live_quotes(
            snap, get_quote=feed.get_quote, sina_of=sina_of
        )
        if _sync_snapshot_hwm_from_quotes(snap, get_quote=feed.get_quote):
            changed = True
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 行情快刷失败: {e}")
        return False
    if not changed:
        return False
    # 叠加池独立缓存：有新行情则替换 strategy17 行
    try:
        from strategy17_watch import cached_strategy17_rows

        s17 = cached_strategy17_rows()
        if s17:
            snap["strategy17"] = s17
    except Exception:  # noqa: BLE001
        pass
    _stamp_snapshot_liveness(snap)
    # 竞态：全量扫描已写入更新快照 → 放弃本轮
    if _last_watch_snapshot is not base:
        return False
    _last_watch_snapshot = snap
    _broadcast_watch_snapshot(snap)
    return True


def _deferred_sectors_placeholder(*, error: str | None = None) -> dict[str, Any]:
    return {
        "source": "",
        "spotAt": None,
        "conceptToday": {},
        "deferred": True,
        "error": error,
    }


def _sectors_for_snapshot(*, fetch_sectors: bool) -> dict[str, Any]:
    """盯盘主循环只读缓存，不在首屏同步拉通达信全市场概念。"""
    from sectors_watch import build_sectors_live_payload, peek_sectors_live_payload

    peek = peek_sectors_live_payload()
    if peek and (peek.get("conceptToday") or not peek.get("deferred")):
        return peek
    if fetch_sectors:
        try:
            return build_sectors_live_payload()
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 板块快照失败（继续盯盘）: {e}")
            return peek or _deferred_sectors_placeholder(error=str(e))
    prev = _last_watch_snapshot or {}
    prev_s = prev.get("sectors") if isinstance(prev.get("sectors"), dict) else None
    if prev_s and (prev_s.get("conceptToday") or not prev_s.get("deferred")):
        return prev_s
    return peek or _deferred_sectors_placeholder()


def _mark_watch_front_ready(snap: dict[str, Any]) -> None:
    if snap.get("boot") or _WATCH_FRONT_READY.is_set():
        return
    _WATCH_FRONT_READY.set()
    print(f"[{_now()}] 盯盘/策略首屏已推送，后台开始拉板块轮动")


def _heartbeat_watch_clock() -> None:
    """刷新线程卡住时仍推时钟；外网行情停了则标 quoteStale 给顶栏红字。"""
    global _last_watch_snapshot
    with _WATCH_SNAP_LOCK:
        prev = _last_watch_snapshot
        if not prev or prev.get("type") != "snapshot":
            return
        try:
            last_ts = int(prev.get("ts") or 0)
        except (TypeError, ValueError):
            last_ts = 0
        now_ms = int(datetime.now().timestamp() * 1000)
        if last_ts and now_ms - last_ts < 1500:
            return
        snap = _stamp_snapshot_liveness(dict(prev))
        _last_watch_snapshot = snap
    _broadcast_watch_snapshot(snap)


def publish_sectors_live_patch() -> None:
    """板块行情独立刷新并推 WS，不跟 collect_rows 绑死。"""
    global _last_watch_snapshot
    from sectors_watch import build_sectors_live_payload

    try:
        sectors = build_sectors_live_payload()
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 板块实时刷新失败: {e}")
        return
    with _WATCH_SNAP_LOCK:
        prev = _last_watch_snapshot
        if not prev or prev.get("type") != "snapshot":
            return
        snap = dict(prev)
        snap["sectors"] = sectors
        _stamp_snapshot_liveness(snap)
        _last_watch_snapshot = snap
    _broadcast_watch_snapshot(snap)


def publish_watch_snapshot(
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]] | None = None,
    *,
    refresh_sec: int = 5,
    get_quote: Callable[[str], dict[str, Any]] | None = None,
    fetch_sectors: bool = True,
    include_strategy_panels: bool = True,
) -> tuple[Path, bool]:
    """推送 JSON 快照（WebSocket + holdings_watch.json），盯盘模式不写 HTML。

    fetch_sectors=False：首屏不拉板块，只用已缓存的 conceptToday。
    返回 (路径, 是否已写盘并广播)；业务数据未变时跳过写盘，仍广播时钟与行情健康度。
    """
    global _last_watch_snapshot, _last_snapshot_digest
    indices = indices or []
    clock_now = _now()
    phase_key = market_phase()
    phase_label = market_phase_label(phase_key)
    holdings_meta = load_holdings()
    from watch_config import code_key, portfolio_pool_codes, strategy_watchlist_codes

    portfolio_codes = set(portfolio_pool_codes(holdings_meta))
    account = _build_watch_account_summary(rows)
    # 账户/结算 session 跟日历；行上交易日盘前常滞后，不得拖慢日初锚
    session_today = _calendar_signal_session()
    row_sess = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        "",
    )
    if row_sess and str(row_sess)[:10] > session_today:
        session_today = str(row_sess)[:10]
    try:
        maybe_record_daily_settlement(
            rows, account, session=session_today or None
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 日结算记录失败（继续）: {e}")
    def _batch_quote(sinas: list[str]) -> dict[str, dict[str, Any]]:
        batch = fetch_sina_batch([s.lower() for s in sinas])
        out: dict[str, dict[str, Any]] = {}
        for s in sinas:
            spot = batch.get(s.lower())
            if spot:
                out[s.lower()] = _quote_from_sina_spot(spot)
        return out

    strategy3: dict[str, Any] = {}
    strategy8: dict[str, Any] = {}
    strategy15: dict[str, Any] = {}
    strategy17_rows: list[dict[str, Any]] = []
    if include_strategy_panels:
        from strategy3_watch import build_strategy3_payload
        from strategy8_watch import build_strategy8_payload

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
    sectors = _sectors_for_snapshot(fetch_sectors=fetch_sectors)
    if include_strategy_panels:
        try:
            from strategy15_watch import build_strategy15_payload

            strategy15 = build_strategy15_payload(
                session=session_today or None,
                strategy1_rows=[
                    r
                    for r in rows
                    if not r.get("error")
                ],
            )
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 策略十五快照失败（继续盯盘）: {e}")
            strategy15 = {"error": str(e), "rows": []}
        try:
            from strategy17_watch import cached_strategy17_rows

            strategy17_rows = cached_strategy17_rows()
        except Exception:  # noqa: BLE001
            strategy17_rows = []
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
        strategies=_watch_tabs_with_live_s8(strategy8),
        strategy3=strategy3,
        strategy8=strategy8,
        strategy15=strategy15,
        strategy16b=_strategy16b_rows_from_rows(rows),
        strategy17=strategy17_rows,
        sectors=sectors,
        refresh_sec=refresh_sec,
        portfolio_codes=portfolio_codes,
        strategy_codes=strategy_watchlist_codes(),
    )
    apply_feed_health(snapshot, _current_feed_health())
    keep_last = False
    published = False
    to_send: dict[str, Any]
    with _WATCH_SNAP_LOCK:
        if should_keep_last_snapshot(
            rows=rows, snapshot=snapshot, prev=_last_watch_snapshot
        ):
            snap = retain_last_snapshot(
                _last_watch_snapshot,
                clock=clock_now,
                phase=phase_label,
                phase_key=phase_key,
                session=session_today or None,
            )
            apply_feed_health(snap, _current_feed_health(), keep_stale=True)
            _last_watch_snapshot = snap
            to_send = snap
            keep_last = True
        else:
            digest = _snapshot_business_digest(snapshot)
            if digest == _last_snapshot_digest and _last_watch_snapshot is not None:
                snap = dict(_last_watch_snapshot)
                snap["sectors"] = sectors
                snap["strategies"] = (
                    snapshot.get("strategies") or snap.get("strategies") or []
                )
                snap["strategy16"] = (
                    snapshot.get("strategy16")
                    if "strategy16" in snapshot
                    else snap.get("strategy16") or []
                )
                snap["strategy16b"] = (
                    snapshot.get("strategy16b")
                    if "strategy16b" in snapshot
                    else snap.get("strategy16b") or []
                )
                if session_today and snapshot_needs_day_pnl_rebase(
                    snap, session=session_today
                ):
                    snap = rebase_snapshot_day_pnl(snap, session=session_today)
                    _last_snapshot_digest = None
                _stamp_snapshot_liveness(snap, clock=clock_now)
                _last_watch_snapshot = snap
                to_send = snap
            else:
                _last_snapshot_digest = digest
                _last_watch_snapshot = snapshot
                to_send = snapshot
                published = True
    _broadcast_watch_snapshot(to_send)
    _mark_watch_front_ready(to_send)
    if keep_last:
        _log_watch_snapshot_push(
            f"[{_now()}] 行情未就绪，沿用上次快照（不置空）",
        )
        return WATCH_META_FILE, False
    if published:
        _atomic_write_text(
            WATCH_META_FILE,
            json.dumps(to_send, ensure_ascii=False),
            encoding="utf-8",
        )
    return WATCH_META_FILE, published


def _seed_boot_watch_snapshot() -> None:
    """HTTP/WS 先于冷启动就绪：复用上次快照，没有则占位，避免前端 503。

    若 holdings.json 比 holdings_watch.json 新，视为本机展示缓存过期
    （Win/Mac 各一份），不得用旧快照当持仓真源。
    """
    global _last_watch_snapshot
    if _last_watch_snapshot is not None:
        return
    from holdings_sync import snapshot_cache_stale

    if snapshot_cache_stale():
        if WATCH_META_FILE.is_file():
            print(f"[{_now()}] 丢弃过期 holdings_watch.json（账本更新）")
            try:
                WATCH_META_FILE.unlink()
            except OSError:
                pass
    elif WATCH_META_FILE.is_file():
        try:
            snap = json.loads(WATCH_META_FILE.read_text(encoding="utf-8"))
            if isinstance(snap, dict) and snap.get("type") == "snapshot":
                try:
                    s8 = snap.get("strategy8") if isinstance(snap.get("strategy8"), dict) else {}
                    snap["strategies"] = _watch_tabs_with_live_s8(s8)
                except Exception:  # noqa: BLE001
                    pass
                snap.setdefault("strategy16", [])
                try:
                    sess = str(trading_session_date())
                    if snapshot_needs_day_pnl_rebase(snap, session=sess):
                        snap = rebase_snapshot_day_pnl(snap, session=sess)
                        print(f"[{_now()}] 启动：跨日快照今日盈亏已按昨收重算 session={sess}")
                except Exception as e:  # noqa: BLE001
                    print(f"[{_now()}] 启动盈亏重算跳过: {e}")
                _last_watch_snapshot = snap
                return
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    clock = _now()
    _last_watch_snapshot = {
        "v": SNAPSHOT_VERSION,
        "type": "snapshot",
        "ts": int(datetime.now().timestamp() * 1000),
        "updatedAt": clock,
        "clock": clock,
        "phase": market_phase_label(),
        "phaseKey": market_phase(),
        "refreshSec": 5,
        "boot": True,
        "strategy": {
            "id": STRATEGY_ID,
            "name": STRATEGY_NAME,
            "factorsLabel": _STRATEGY_FACTORS_LABEL,
        },
        "account": {},
        "slotMeta": {
            "max": 4,
            "weight": 0.25,
            "occupied": [],
            "occupiedCount": 0,
            "free": 4,
        },
        "indices": [],
        "holdings": [],
        "strategy1": [],
        "strategy3": {},
        "strategy8": {},
        "strategy15": {},
        "strategy16": [],
        "strategy17": [],
        "sectors": {},
        "strategies": _watch_tabs_with_live_s8({}),
    }


# 兼容旧名
_strategy1_factor1_params = _factor1_binding_params


def _index_codes_match(raw: str, wanted: str) -> bool:
    a = str(raw or "").strip().lower()
    b = str(wanted or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    da = "".join(ch for ch in a if ch.isdigit())
    db = "".join(ch for ch in b if ch.isdigit())
    return bool(da) and da == db


def _index_from_sina_spot(item: dict[str, str], spot: dict[str, Any]) -> dict[str, Any] | None:
    try:
        last = float(spot.get("last") or 0)
        prev = float(spot.get("prev_close") or 0)
    except (TypeError, ValueError):
        return None
    if last <= 0 or prev <= 0:
        return None
    chg = last - prev
    return {
        "code": item["code"],
        "name": item["name"],
        "market": item["market"],
        "price": last,
        "chg_points": chg,
        "chg_pct": chg / prev * 100.0,
        "error": None,
    }


def _merge_index_keep_last(
    fresh: list[dict[str, Any]],
    prev: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """单边失败时沿用上次点数，避免上证/深证整卡「获取失败」。"""
    last_map = {
        str(x.get("code") or ""): x
        for x in (prev or [])
        if isinstance(x, dict) and x.get("price") and not x.get("error")
    }
    out: list[dict[str, Any]] = []
    for item in fresh:
        ok = item.get("price") and not item.get("error")
        if ok:
            out.append(item)
            continue
        kept = last_map.get(str(item.get("code") or ""))
        out.append(dict(kept) if kept else item)
    return out


def fetch_indices_cached(*, ttl_sec: float = _INDEX_CACHE_TTL_SEC) -> list[dict[str, Any]]:
    """盯盘高频刷新时缓存大盘指数，避免每次重拉拖慢推送。"""
    now = time.monotonic()
    cached = _INDEX_CACHE.get("data") or []
    if cached and (now - float(_INDEX_CACHE.get("t") or 0.0)) < float(ttl_sec):
        return list(cached)
    data = _merge_index_keep_last(fetch_indices(), cached)
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
    sess = promote_quote_session(spot.get("session"))
    day_chg = sanitize_day_change_for_session(
        quote_session=spot.get("session"),
        calendar_session=sess,
        mark=last,
        previous_close=prev,
        day_chg_pct=price_chg_pct(last, prev),
    )
    return {
        "session": sess,
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


def _quote_from_daily_prev(daily: pd.DataFrame | None) -> dict[str, Any] | None:
    """无实时成交时用最近日线收盘垫现价（盘前/新浪失败）。"""
    if daily is None or getattr(daily, "empty", True):
        return None
    if "close" not in daily.columns:
        return None
    last = daily.iloc[-1]
    try:
        close = float(last.get("close") or 0)
    except (TypeError, ValueError):
        return None
    if close <= 0:
        return None
    date = str(last.get("date") or "")
    sess = str(trading_session_date())
    q = overnight_preopen_quote(
        calendar_session=sess,
        previous_close=close,
        last_ts=f"{date} 15:00:00" if date else _now(),
    )
    q["_day_bars"] = pd.DataFrame()
    q["_quote_source"] = "daily_prev"
    q["name"] = ""
    return q


def _reseed_sina_batch(
    feed: QuoteFeedManager,
    watchlist: list[dict[str, Any]] | None = None,
    *,
    daily_fallback: bool = True,
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
    # 盘前新浪/批量失败时用已预热日线昨收垫上，避免 collect_rows 逐只 8s 超时。
    # 冷启动首屏会并行预热日线；此处可关闭，避免 seed 阶段串行卡住。
    if not daily_fallback:
        return n
    for w in items:
        if feed.get_quote(w["sina"]):
            continue
        q = _quote_from_daily_prev(_watch_daily(w["sina"]))
        if q is None:
            continue
        feed.seed(w["sina"], q)
        n += 1
    return n


def fetch_today_quote_live(sina: str) -> dict[str, Any]:
    """盯盘专用：仅新浪实时快照，不请求东财历史分钟 K。"""
    spot = fetch_sina_spot(sina)
    if spot is not None:
        return _quote_from_sina_spot(spot)
    q = _quote_from_daily_prev(_watch_daily(sina))
    if q is not None:
        return q
    raise RuntimeError(f"无实时行情: {sina}")


def _reseed_live_batch(
    feed: QuoteFeedManager,
    watchlist: list[dict[str, Any]] | None = None,
    *,
    daily_fallback: bool = True,
) -> int:
    """刷新当日实时快照（新浪批量）。"""
    return _reseed_sina_batch(feed, watchlist, daily_fallback=daily_fallback)


def _daily_cache_warm(
    watchlist: list[dict[str, Any]] | None = None, *, force: bool = False
) -> None:
    """并行预热日线缓存，避免首屏 collect_rows 串行等 IO。"""
    items = watchlist if watchlist is not None else effective_watchlist()
    if not items:
        return
    workers = min(_DAILY_WARM_WORKERS, max(1, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda w: _watch_daily(w["sina"], force=force), items))


# 日线缓存：按信号交易日缓存；缺上一完整交易日则强制补拉（供前日过滤与最近因子触发）
_DAILY_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}
_SIGNAL_CACHE_DAY: str | None = None
# 1 分钟缓存：实仓/近止损触达判定（path-dependent）；ttl 秒
_M1_CACHE: dict[str, tuple[float, str, pd.DataFrame]] = {}
_M1_CACHE_TTL_SEC = 45.0
_VOL20_CACHE: dict[str, tuple[str, float | None]] = {}
_M1_EMPTY_TTL_SEC = 15.0  # 拉空/失败：短负缓存，避免每轮狂打接口


def _daily_last_trade_date(daily: pd.DataFrame) -> Any | None:
    """日线末根交易日（date）。"""
    if daily is None or getattr(daily, "empty", True) or "date" not in daily.columns:
        return None
    try:
        return pd.to_datetime(daily["date"]).dt.tz_localize(None).dt.normalize().max().date()
    except Exception:  # noqa: BLE001
        return None


def _invalidate_date_signal_caches(*, reason: str = "") -> None:
    """跨日/启动：清日线与依赖过门/前日的派生缓存。"""
    global _DAILY_CACHE, _VOL20_CACHE, _REPLAY_CACHE, _STRATEGY_PNL_CACHE, _M1_CACHE
    global _SIGNAL_CACHE_DAY
    _DAILY_CACHE.clear()
    _VOL20_CACHE.clear()
    _REPLAY_CACHE.clear()
    _STRATEGY_PNL_CACHE.clear()
    _M1_CACHE.clear()
    _SIGNAL_CACHE_DAY = None
    note = f" · {reason}" if reason else ""
    print(f"[{_now()}] 已清空日期相关信号缓存（日线/回放/1m）{note}")


def _ensure_signal_day_caches(*, force: bool = False) -> str:
    """信号交易日变化或强制时清空缓存。返回规范化 session 日。"""
    global _SIGNAL_CACHE_DAY
    day = str(trading_session_date())
    if force or _SIGNAL_CACHE_DAY != day:
        _invalidate_date_signal_caches(
            reason=("启动强制" if force else f"跨日 {_SIGNAL_CACHE_DAY}→{day}")
        )
        _SIGNAL_CACHE_DAY = day
    return day


def _today_1m_bars(sina: str, session: str, *, force: bool = False) -> pd.DataFrame:
    """拉取并缓存当日 1 分钟 K（未复权），供因子26 多层止盈 path-dependent 判定。"""
    key = str(sina).lower()
    now = time.monotonic()
    hit = _M1_CACHE.get(key)
    if (not force) and hit and hit[1] == session and hit[2] is not None:
        ttl = _M1_CACHE_TTL_SEC if not hit[2].empty else _M1_EMPTY_TTL_SEC
        if (now - hit[0]) < ttl:
            return hit[2]
    em_code = key[2:] if len(key) >= 8 and key[:2] in ("sh", "sz") else key
    try:
        df = pull_akshare_1m(em_symbol=em_code, sina_symbol=key, adjust="")
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 1m 拉取失败 {key}: {e}")
        df = pd.DataFrame()
    day = pd.DataFrame()
    if df is not None and not df.empty and "ts" in df.columns:
        day_keys = _day_key_series(df["ts"])
        day = df[day_keys == str(session)].copy()
        if not day.empty:
            day = day.dropna(subset=["open", "high", "low", "close"]).sort_values("ts")
            day = day[
                (day["open"] > 0)
                & (day["high"] > 0)
                & (day["low"] > 0)
                & (day["close"] > 0)
            ]
    _M1_CACHE[key] = (now, str(session), day)
    return day


def _bars_cover_current_minute(bars: pd.DataFrame, *, now: Any | None = None) -> bool:
    """末根 1m 已是当前分钟（含未走完 K）时，勿再用 last 去撞抬升后的卖价。"""
    if bars is None or getattr(bars, "empty", True) or "ts" not in bars.columns:
        return False
    try:
        last_ts = pd.Timestamp(bars.sort_values("ts").iloc[-1]["ts"])
        if getattr(last_ts, "tzinfo", None) is not None:
            last_ts = last_ts.tz_convert("Asia/Shanghai").tz_localize(None)
        clock = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
        if getattr(clock, "tzinfo", None) is not None:
            clock = clock.tz_convert("Asia/Shanghai").tz_localize(None)
        return last_ts.floor("min") >= clock.floor("min")
    except Exception:  # noqa: BLE001
        return False


def _vol20_daily_for(sina: str, session: str) -> float | None:
    """截至 session 前一交易日的近 20 日日频实现波动（点时点）。"""
    key = str(sina).lower()
    hit = _VOL20_CACHE.get(key)
    if hit and hit[0] == str(session):
        return hit[1]
    vol: float | None = None
    try:
        end = pd.Timestamp(str(session))
        start = (end - pd.Timedelta(days=80)).strftime("%Y%m%d")
        end_excl = (end - pd.Timedelta(days=1)).strftime("%Y%m%d")
        df = fetch_daily(key, start, end_excl)
        if df is not None and not df.empty and "close" in df.columns:
            closes = pd.to_numeric(df["close"], errors="coerce").dropna().tolist()
            vol = realized_vol_daily(closes)
    except Exception:  # noqa: BLE001
        vol = None
    _VOL20_CACHE[key] = (str(session), vol)
    return vol


def _resolve_hit_stop_path_dependent(
    *,
    sina: str,
    session: str,
    quote: dict[str, Any],
    pullback_pct: float,
    tick: float,
    need_accurate: bool,
    stop_px: float,
    since_ts: str | None = None,
    seed_high: float | None = None,
    cost_px: float | None = None,
    vol20_daily: float | None = None,
    overnight_armed: bool = False,
    day_open: float | None = None,
    shares: int = 1000,
    tp_stage: int = 0,
    since_exclusive: bool = False,
) -> dict[str, Any]:
    """动态止盈触达：优先 1 分钟顺序；无分钟时仅 last≤当前卖价。

    since_ts：实仓从买入时刻起算；半仓后改 last_tp_ts 且 since_exclusive。
    seed_high：持仓峰值初值（成本/隔夜已记 peak；不含当日快照 high）。
    cost_px：买入成本（浮盈回落一半锚；勿把 peak 当成本）。
    shares / tp_stage：对齐 eval_multi_tp_bar，10% 只减半。
    """
    bars = quote.get("_day_bars")
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        bars = pd.DataFrame()
    if need_accurate and bars.empty:
        bars = _today_1m_bars(sina, session)
        quote["_day_bars"] = bars

    try:
        last = float(quote["last"])
        high = float(quote.get("high") or 0)
    except (TypeError, ValueError, KeyError):
        last, high = 0.0, 0.0

    if bars is not None and not bars.empty:
        forming = _bars_cover_current_minute(bars)
        pd_hit = path_dependent_pullback_hit(
            bars,
            pullback_pct=pullback_pct,
            tick=tick,
            live_high=None,
            live_low=(None if forming else (last if last > 0 else None)),
            since_ts=since_ts,
            seed_high=seed_high,
            cost_px=cost_px if cost_px is not None else None,
            vol20_daily=vol20_daily,
            overnight_armed=bool(overnight_armed),
            day_open=day_open,
            shares=max(0, int(shares or 0)),
            tp_stage=max(0, int(tp_stage or 0)),
            since_exclusive=bool(since_exclusive),
        )
        touch = float(pd_hit.get("touch_stop") or 0)
        if bool(pd_hit.get("hit_stop")) and touch <= 0:
            touch = float(pd_hit.get("stop_px") or 0)
        return {
            "hit_stop": bool(pd_hit.get("hit_stop")),
            "bars": bars,
            "touch_stop": touch,
            "stop_px": float(pd_hit.get("stop_px") or stop_px or 0),
            "running_high": float(pd_hit.get("running_high") or 0),
            "source": str(pd_hit.get("source") or "1m"),
            "stop_kind": str(pd_hit.get("stop_kind") or ""),
            "action_kind": str(pd_hit.get("action_kind") or ""),
            "sell_shares": int(pd_hit.get("sell_shares") or 0),
            "touch_ts": pd_hit.get("touch_ts"),
        }

    stop_now = float(stop_px or 0)
    # 无分钟：仅现价破卖价才算（更严，防误报）
    hit = bool(stop_now > 0 and last <= stop_now + 1e-12)
    return {
        "hit_stop": hit,
        "bars": bars,
        "touch_stop": stop_now if hit else 0.0,
        "stop_px": stop_now,
        "running_high": float(seed_high or 0),
        "source": "last_vs_stop",
        "stop_kind": "",
        "action_kind": "full" if hit else "",
        "sell_shares": 0,
        "touch_ts": None,
    }


def _watch_daily(
    sina: str, *, lookback_days: int | None = None, force: bool = False
) -> pd.DataFrame:
    """日线缓存；缺最新已收盘交易日则补拉（过门/前日依赖）。"""
    days = int(lookback_days) if lookback_days is not None else (280 if USE_FACTOR4 else 90)
    cache_day = str(trading_session_date())
    expected = latest_completed_weekday()
    cached = _DAILY_CACHE.get(sina)
    if (not force) and cached and cached[0] == cache_day and cached[1] is not None:
        last = _daily_last_trade_date(cached[1])
        if last is not None and last >= expected and not cached[1].empty:
            return cached[1]
    start = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")
    df = pd.DataFrame()
    try:
        df = fetch_daily(sina, start, end)
    except Exception:  # noqa: BLE001
        df = pd.DataFrame()
    last = _daily_last_trade_date(df)
    if last is None or last < expected:
        try:
            df = fetch_daily(sina, start, end, force_refresh=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 日线强制刷新失败 {sina}: {e}")
    _DAILY_CACHE[sina] = (cache_day, df)
    return df


def _daily_frame_sig(daily: pd.DataFrame) -> str:
    if daily is None or daily.empty:
        return "empty"
    last = daily.iloc[-1]
    return f"{len(daily)}:{last.get('date', '')}"


def _strategy_pnl_since_cached(
    sina: str,
    daily: pd.DataFrame,
    *,
    q: dict[str, Any],
    code: str,
    entry_pct: float,
    stop_pct: float,
    tick: float,
    prev_entry_mode: str,
    limit_down_pct: float,
) -> dict[str, Any]:
    """自 STRATEGY_PNL_START 起的单票策略收益（日线+盘中末 bar）。"""
    today = str(trading_session_date())
    live_sig = (
        f"{q.get('session')}:{q.get('open')}:{q.get('high')}:"
        f"{q.get('low')}:{q.get('last')}"
    )
    key = (
        str(sina).lower(),
        today,
        STRATEGY_PNL_START,
        _daily_frame_sig(daily),
        live_sig,
        float(entry_pct),
        float(stop_pct),
        float(tick),
        str(prev_entry_mode),
        float(limit_down_pct),
    )
    hit = _STRATEGY_PNL_CACHE.get(key)
    if hit is not None:
        return hit
    merged = _merge_live_daily_bar(
        daily,
        session=str(q["session"]),
        open_px=float(q["open"]),
        high_px=float(q["high"]),
        low_px=float(q["low"]),
        close_px=float(q["last"]),
    )
    out = replay_strategy_return_since(
        merged,
        start_date=STRATEGY_PNL_START,
        entry_pct=entry_pct,
        stop_pct=stop_pct,
        tick=tick,
        prev_entry_mode=prev_entry_mode,
        limit_down_pct=limit_down_pct,
        code=code,
    )
    if len(_STRATEGY_PNL_CACHE) > 512:
        _STRATEGY_PNL_CACHE.clear()
    _STRATEGY_PNL_CACHE[key] = out
    return out


def _attach_strategy_pnl_fields(
    row: dict[str, Any],
    *,
    w: dict[str, Any],
    daily: pd.DataFrame,
    q: dict[str, Any],
    entry_pct: float,
    stop_pct: float,
    tick: float,
    prev_entry_mode: str,
    limit_down_pct: float,
) -> None:
    """写入策略累计 / 单笔收入：权威源 = Strategy Simulator（非 Paper、非 Factor1 串台）。

    Layer A：strategy_id+symbol 虚拟账本；与纸面 qty / Capital V2 无关。
    Live：用 q.last 撞买/卖位；FLAT 累计冻结，LONG 可 mark。
    """
    from strategy_simulator import (
        apply_book_to_row,
        ensure_bootstrapped,
        ensure_bootstrapped_from_factor26_replay,
        evaluate_live_transition,
        get_book,
        mark_book,
        sync_flat_cumulative,
    )

    row["策略起算"] = STRATEGY_PNL_START
    sid = str(STRATEGY_ID)
    code = str(w.get("code") or row.get("代码") or "")
    if row.get("error") or not q.get("session") or not code:
        row["策略收益%"] = None
        row["策略收益"] = None
        row["策略累计持有"] = False
        row["策略累计笔数"] = None
        row["策略模拟状态"] = "FLAT"
        row["策略状态"] = "空仓"
        row["策略收益语义"] = "strategy_simulator_ledger"
        row["策略收益范围"] = "symbol"
        row["策略历史口径"] = "daily_open_break_fixed_stop"
        row["策略实时口径"] = "quote_touch_row_levels"
        row["策略退出口径"] = "row_sell_level_live"
        return

    replay_info: dict[str, Any] | None = None
    if str(FACTOR_ID).lower() in ("factor26", "f26", "26"):
        try:
            replay_info = _replay_last_factor_triggers_cached(
                w["sina"],
                daily,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                tick=tick,
                prev_entry_mode=prev_entry_mode,
                limit_down_pct=limit_down_pct,
            )
            ensure_bootstrapped_from_factor26_replay(
                sid,
                code,
                replay_info,
                persist=True,
            )
        except Exception:  # noqa: BLE001
            replay_info = None

    # 历史 bootstrap → 同一账本；优先 factor26 1m replay，缺分钟时退回日线简化模型。
    try:
        ensure_bootstrapped(
            sid,
            code,
            daily,
            start_date=str(STRATEGY_PNL_START),
            entry_pct=float(entry_pct),
            stop_pct=float(stop_pct),
            tick=float(tick),
            prev_entry_mode=str(prev_entry_mode),
            persist=True,
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        last = float(q["last"])
    except (TypeError, ValueError, KeyError):
        last = 0.0
    buy_lv = row.get("买点")
    if buy_lv is None:
        buy_lv = row.get("买入侧价")
    sell_lv = row.get("止损")
    if sell_lv is None:
        sell_lv = row.get("卖出侧价")
    allow_entry = bool(row.get("过门OK"))
    # 已触买粘滞：允许 simulator 在仍 FLAT 时补登（与展示一致）
    if str(row.get("已触买") or "") == "是":
        allow_entry = True
    quote_ts = None
    if q.get("ts"):
        quote_ts = str(q.get("ts"))
    elif q.get("time"):
        quote_ts = str(q.get("time"))
    else:
        # 无源时间戳：用会话日 + 当前时钟（仅作 evaluation 标记）
        from datetime import datetime as _dt

        quote_ts = f"{str(q['session'])[:10]} {_dt.now().strftime('%H:%M:%S')}"

    if last > 0:
                evaluate_live_transition(
                    strategy_id=sid,
                    symbol=code,
                    live_last=last,
                    quote_ts=quote_ts,
                    buy_level=float(buy_lv) if buy_lv is not None else None,
                    sell_level=float(sell_lv) if sell_lv is not None else None,
                    allow_entry=allow_entry,
                    reason="collect_rows",
                    persist=True,
                    t0=bool(w.get("t0")),
                    day_open=q.get("open"),
                )
    book = get_book(sid, code)
    if last > 0:
        mark_book(book, last, quote_ts=quote_ts)
    else:
        sync_flat_cumulative(book)
    apply_book_to_row(row, book)
    try:
        row["策略累计笔数"] = int(book.get("trades") or 0)
    except (TypeError, ValueError):
        row["策略累计笔数"] = None
    # debug：保留 Factor1 对照字段名但不作为主状态（避免 UI 双真相）
    row["策略回放对照%"] = None
    try:
        rec = replay_info or _strategy_pnl_since_cached(
            w["sina"],
            daily,
            q=q,
            code=code,
            entry_pct=entry_pct,
            stop_pct=stop_pct,
            tick=tick,
            prev_entry_mode=prev_entry_mode,
            limit_down_pct=limit_down_pct,
        )
        row["策略回放对照%"] = rec.get("return_pct")
        row["策略回放对照持有"] = bool(rec.get("holding"))
        row["策略回放触发侧"] = rec.get("last_trigger_side")
        row["策略回放触发价"] = rec.get("last_trigger_px")
        row["策略回放来源"] = rec.get("source")
    except Exception:  # noqa: BLE001
        pass


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
    """因子26：近 7 日 1m 路径回放；失败则退回日线（有同 bar 偏差）。"""
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
        "1m" if str(FACTOR_ID) == "factor26" else "daily",
        int(_REPLAY_1M_DAYS),
    )
    hit = _REPLAY_CACHE.get(key)
    if hit is not None:
        return hit
    if str(FACTOR_ID) == "factor26":
        mins_all = _m1_lookback_bars(str(sina), session=today)
        if mins_all is not None and not mins_all.empty:
            out = replay_factor26_1m(
                daily,
                mins_all,
                entry_pct=entry_pct,
                pullback_pct=stop_pct,
                tick=tick,
                prev_entry_mode=prev_entry_mode,
                last_n_days=int(_REPLAY_1M_DAYS),
            )
        else:
            out = dict(
                replay_last_factor_triggers(
                    daily,
                    entry_pct=entry_pct,
                    stop_pct=stop_pct,
                    tick=tick,
                    prev_entry_mode=prev_entry_mode,
                    limit_down_pct=limit_down_pct,
                )
            )
            out["source"] = "daily_fallback"
    else:
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
    """返回 (prev_open, prev_close, prev2_open, prev2_close)。

    session 先规范化（周末→上周五）；取严格早于 session 的末两根，
    故周一自然落到上周五 / 上上周四。
    """
    if daily is None or daily.empty:
        return None, None, None, None
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
    d = d.dropna(subset=["open", "close"]).sort_values("date")
    sess = pd.Timestamp(normalize_signal_session(session)).normalize()
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
        dpct = price_chg_pct(last_px, px)
        if dpct is None:
            return None, None
        dpct = round(float(dpct), 2)
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
        and (
            str(row.get("预警") or "") in EXIT_REASONS
            or _is_stop_closed_status(row.get("持仓状态"))
            or "止损" in str(row.get("预警") or "")
        )
    )
    mem = _factor_memory(code) if code else {}
    # 日线回放仍处「买入未平」：本地未登记仓位时，双距按策略持有展示（勿用更早的卖出因子）
    # 回放已触止损 → 不当策略持有
    paper_holding = bool(replay.get("holding")) and qty <= 0 and not hit_stop
    row["策略回放持有"] = bool(paper_holding)
    # 实仓触止损但仍持有（含 T+1 暂不可卖）≠ 已平仓；仅已卖出/纸面触止损算「当日退出」
    hit_stop_while_held = bool(qty > 0 and hit_stop)
    paper_stopped = bool(replay.get("holding")) and qty <= 0 and hit_stop
    # 仅三槽真实卖出禁买；回放止损不当当日禁买，否则天通等自选票触买进不了预警栏
    stop_exit_today = bool(sold_today)
    row["当日禁买"] = bool(sold_today)
    if paper_stopped and not sold_today and not hit_buy:
        row["持仓状态"] = STATUS_STOP_CLOSED
        if str(row.get("预警") or "") in ("", "-", "空仓", "待买入", "策略持有"):
            row["预警"] = "策略回放·今日已止损"

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
        stop_exit_today
        or hit_stop_while_held
        or (pos_st == "待卖出" and hit_txt == "已触发")
    )
    just_bought = bool(
        allow_entry
        and (not stop_exit_today)
        and (not hit_stop_while_held)
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
        if code and sell_mem_px is not None and sold_today:
            # 只在三槽真实卖出后写卖出记忆；持仓未平时禁止记 last_sell
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

    # 当日禁买（过门未过）：未触发侧若是买入则清空（不展示下一买点）
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

    # 盘中预警：已触发/接近 + 今日日期（过门未过的禁买不进待买入文案）
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

    # 有仓 / 策略回放持有 / 当日止损后（且过门未过禁买）：展示买入日，止损日单独标注
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
                    "今日已止损·过门未过"
                    if sold_today
                    else "策略持有·今日触止损·过门未过"
                )
            # 强制不挂买单
            row["建议挂单"] = None
            row["近买点"] = False
            # 已真实平仓 → 持仓态「已平仓」；信号用「已触止损」
            if sold_today:
                row["持仓状态"] = STATUS_STOP_CLOSED
                a0 = str(row.get("预警") or "")
                if a0 in (
                    "",
                    "-",
                    "空仓",
                    "待买入",
                    "止损成交",
                    "已平仓",
                    "已触止损平仓",
                    "今日已止损·过门未过",
                ):
                    row["预警"] = SIGNAL_STOP_HIT
            elif str(row.get("持仓状态") or "") == "待买入":
                row["持仓状态"] = "空仓"
            if str(row.get("因子侧") or "") == "买入":
                row["因子侧"] = "空仓"
        elif hit_buy and md and md == today_md:
            # 今日触买（含已入槽 / T+1）：优先标已触发，不被「不可用」盖掉
            row["因子触发"] = f"已触发 {md}"
            if qty > 0 and str(row.get("持仓状态") or "") in (
                "",
                "空仓",
                "待买入",
                "持有",
            ):
                row["持仓状态"] = "已经买入"
        elif hit_stop_while_held and today_md and qty > 0:
            # 仍持仓：保留买入日；止损仅在预警/待卖出侧体现
            if md:
                row["因子触发"] = md
            if str(row.get("持仓状态") or "") in ("", "空仓", "待买入", "持有"):
                row["持仓状态"] = "已经买入"
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


def _normalize_holdings(data: dict[str, Any]) -> None:
    # effective_watchlist 必须显式传入 holdings：不传会回调 load_holdings，
    # 缓存未写入前无限递归直到 RecursionError（被 primary_watchlist 吞掉），单次 60s+。
    positions = data.setdefault("positions", {})
    for w in effective_watchlist(data):
        positions.setdefault(w["code"], _empty_position(w))
    data.setdefault("realized_today", {})
    data.setdefault("closed_today", {})
    data.setdefault("daily_settlements", {})
    data.setdefault("account_total", None)
    data.setdefault("account_cash", None)
    data.setdefault("account_total_open", None)
    data.setdefault("account_total_open_session", None)
    data.setdefault("paper_equity_base", None)
    data.setdefault("paper_pnl_start", None)
    data.setdefault("alert_sticky", {})


def load_holdings() -> dict[str, Any]:
    """进程内唯一账本对象（身份稳定）；外部改盘后原地合并，不换绑。"""
    data = _HOLDINGS_STORE.load()
    if data is not None:
        return data
    if not HOLDINGS_FILE.exists():
        data = {
            "updated_at": None,
            "account_total": None,
            "account_cash": None,
            "positions": {},
            "realized_today": {},
            "closed_today": {},
        }
        data["positions"] = {
            w["code"]: _empty_position(w)
            for w in effective_watchlist(data)
        }
        save_holdings(data)
    loaded = _HOLDINGS_STORE.load()
    if loaded is not None:
        return loaded
    return data if data is not None else {}


def _account_total_open(data: dict[str, Any] | None = None) -> float | None:
    data = data if data is not None else load_holdings()
    return _as_money(data.get("account_total_open"))


def _account_has_open_qty(data: dict[str, Any] | None = None) -> bool:
    data = data if data is not None else load_holdings()
    for pos in (data.get("positions") or {}).values():
        if not isinstance(pos, dict):
            continue
        try:
            if int(pos.get("qty") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _equity_is_cash_only(
    data: dict[str, Any],
    account_total: float | None,
) -> bool:
    """有实仓但总资产≈现金：行情市值没进来，不能当日子/总资产真源。"""
    cash = _account_cash(data)
    if cash is None or account_total is None:
        return False
    if abs(float(account_total) - float(cash)) > 1.0:
        return False
    return _account_has_open_qty(data)


def _prev_settlement_account_total(
    data: dict[str, Any],
    session: str,
) -> float | None:
    """上一交易日结算总资产（优先终稿），作今日日初锚。"""
    day = str(session or "")[:10]
    book = data.get("daily_settlements")
    if not isinstance(book, dict) or len(day) < 10:
        return None
    prev_days = [str(d)[:10] for d in book if str(d)[:10] < day]
    if not prev_days:
        return None
    prev = max(prev_days)
    rec = book.get(prev)
    if not isinstance(rec, dict):
        # key 可能带完整日期外格式
        for k, v in book.items():
            if str(k)[:10] == prev and isinstance(v, dict):
                rec = v
                break
    if not isinstance(rec, dict):
        return None
    return _as_money(rec.get("account_total"))


def _ensure_account_open_session(
    data: dict[str, Any],
    *,
    session: str,
    account_total: float | None,
) -> None:
    """跨日或首次：锁定日初总资产。优先昨收结算；有实仓时禁止「仅现金」日初。"""
    open_session = str(data.get("account_total_open_session") or "")
    existing = _account_total_open(data)
    if open_session == session and existing is not None:
        if _equity_is_cash_only(data, existing):
            data["account_total_open"] = round(float(DEFAULT_ACCOUNT_TOTAL), 2)
            save_holdings(data)
        return
    lock_total = _prev_settlement_account_total(data, session)
    if lock_total is None or lock_total <= 0:
        lock_total = account_total
    if lock_total is None or lock_total <= 0:
        return
    if _equity_is_cash_only(data, lock_total):
        return
    data["account_total_open"] = round(float(lock_total), 2)
    data["account_total_open_session"] = session
    save_holdings(data)


def purge_fake_slot_closed(data: dict[str, Any], session: str) -> int:
    """清掉冒充三槽平仓的 closed_today：当日没有 realized_today 卖出的一律删。

    例：东材仅有历史买档 + 今日策略回放止损，从未纸面占槽卖出。
    """
    day = str(session or "")[:10]
    traces = data.get("closed_today")
    if not isinstance(traces, dict) or len(day) < 10:
        return 0
    real = _realized_today_codes(day, data=data)
    drop = [
        code
        for code, rec in list(traces.items())
        if isinstance(rec, dict)
        and str(rec.get("session") or "")[:10] == day
        and _code_key(str(code)) not in real
    ]
    for code in drop:
        del traces[code]
    return len(drop)


def heal_watch_ledger(*, session: str | None = None) -> dict[str, Any]:
    """每轮自愈：隔夜解锁、修复仅现金日初、清掉非法「止损已记」/假三槽平仓。不改 qty / 成本 / 买入时间。

    跨日（含盘前，不依赖正好 9:15 在线）：
    · 补记上一交易日 POSITION_SETTLEMENT 终稿（若缺）
    · 清非当日 realized/closed（今日平仓归零）
    · 日初锚滚到昨收结算 closing_equity
    同日重复执行幂等，不二次 rollover。
    """
    data = load_holdings()
    sess = normalize_signal_session(session or trading_session_date())
    if needs_session_rollover(data, session=sess):
        settle_previous_session_if_needed(session=sess)
        data = load_holdings()
    changed = unlock_overnight_available(data, sess)
    n_real = len(data.get("realized_today") or {})
    n_closed = len(data.get("closed_today") or {})
    _purge_stale_realized(data, sess)
    if (
        len(data.get("realized_today") or {}) != n_real
        or len(data.get("closed_today") or {}) != n_closed
    ):
        changed = True
    if purge_illegal_t1_stop_notes(data) > 0:
        changed = True
    if heal_missing_overnight_t1_trail_notes(data, session=sess) > 0:
        changed = True
    if purge_fake_slot_closed(data, sess) > 0:
        changed = True
    existing = _account_total_open(data)
    if _equity_is_cash_only(data, existing):
        data["account_total_open"] = round(float(DEFAULT_ACCOUNT_TOTAL), 2)
        if not data.get("account_total_open_session"):
            data["account_total_open_session"] = sess
        changed = True
    q = data.get("slot_queue")
    if not isinstance(q, dict) or str(q.get("session") or "")[:10] != str(sess)[:10]:
        reset_container(data, "slot_queue", {"session": str(sess)[:10], "freed_at": []})
        changed = True
    if str(data.get("last_session") or "")[:10] != str(sess)[:10]:
        data["last_session"] = str(sess)[:10]
        changed = True
    if changed:
        save_holdings(data)
        data = load_holdings()
    open_sess = str(data.get("account_total_open_session") or "")[:10]
    if open_sess != str(sess)[:10]:
        _ensure_account_open_session(
            data,
            session=sess,
            account_total=_as_money(data.get("account_total")),
        )
        data = load_holdings()
    return data


def _position_quotes_ready(rows: list[dict[str, Any]]) -> bool:
    """实仓都有现价/市值才允许回写总资产、自动入槽。"""
    pos = [
        r
        for r in rows
        if int(r.get("持仓") or 0) > 0
    ]
    if not pos:
        return True
    return all(
        (not r.get("error")) and r.get("市值") is not None and r.get("现价") is not None
        for r in pos
    )


def _as_money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _as_cash(v: Any) -> float | None:
    """纸面现金：允许 0 与负值（超配）。缺省/非有限数字才是 None。"""
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _prev_close_from_snapshot(code: str) -> float | None:
    """CLI 卖出无行情时，用最近盯盘快照的昨收，避免昨仓今日盈亏误用成本。"""
    if not WATCH_META_FILE.is_file():
        return None
    try:
        snap = json.loads(WATCH_META_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    key = _code_key(code)
    for r in snap.get("holdings") or []:
        if not isinstance(r, dict):
            continue
        if _code_key(str(r.get("代码") or "")) == key:
            return _as_money(r.get("昨收"))
    return None


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
    reset_container(data, "alert_sticky", kept)
    save_holdings(data)


def reset_watch_status_at_auction(*, session: str | None = None) -> dict[str, Any]:
    """每日 9:15：清空非实仓盯盘状态，只保留 qty>0 持仓。

    · 清 alert_sticky / 非当日 realized / 回放与策略收益缓存
    · 清日线相关缓存并在后续预热中按最新交易日重拉（过门/前日）
    · 清微信预警防抖状态（当日重新推）
    · 标记 watch_status_reset_session，持仓 Tab 在 9:30 前仅展示实仓
    · 跨日快照：昨仓今日盈亏按昨收重算（不再沿用买入日相对成本）
    """
    global _last_watch_snapshot, _last_snapshot_digest
    data = load_holdings()
    sess = normalize_signal_session(session)
    settle_previous_session_if_needed(session=sess)
    _purge_stale_realized(data, sess)
    reset_container(data, "alert_sticky", {})
    data["watch_status_reset_session"] = sess
    # 非实仓仓位：清掉策略展示用粘滞字段（不改 qty>0）
    for code, pos in list((data.get("positions") or {}).items()):
        if not isinstance(pos, dict):
            continue
        if int(pos.get("qty") or 0) <= 0:
            pos["available"] = None
            pos["today_cost"] = None
            continue
        # 新交易日：隔夜仓可卖=持仓（对齐券商 T+1 交收后）
        if not is_t1_buy_day(pos.get("buy_time"), sess):
            pos["available"] = int(pos.get("qty") or 0)
        # 冻结隔夜峰值：盘中 peak_high 抬升不得再进开盘保护
        if int(pos.get("qty") or 0) > 0:
            try:
                cost_f = float(pos.get("cost") or 0)
            except (TypeError, ValueError):
                cost_f = 0.0
            if cost_f > 0:
                freeze_overnight_peak_for_session(
                    pos,
                    session=sess,
                    cost=cost_f,
                    prev_close=None,
                    open_px=None,
                    t0=False,
                    persist=False,
                )
    unlock_overnight_available(data, sess)
    save_holdings(data)
    _ensure_signal_day_caches(force=True)
    # 微信防抖：跨日/早盘重置，避免旧「已触止损」键挡住新信号
    try:
        from wechat_notify import STATE_FILE

        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 清微信预警状态失败（继续）: {e}")
    # 9:15：沿用快照里的昨仓「今日盈亏」改按昨收；强制下一轮重新写盘
    with _WATCH_SNAP_LOCK:
        if _last_watch_snapshot and snapshot_needs_day_pnl_rebase(
            _last_watch_snapshot, session=sess
        ):
            _last_watch_snapshot = rebase_snapshot_day_pnl(
                _last_watch_snapshot, session=sess
            )
            _stamp_snapshot_liveness(_last_watch_snapshot)
            _last_snapshot_digest = None
            try:
                _broadcast_watch_snapshot(_last_watch_snapshot)
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 9:15 盈亏重置广播失败（继续）: {e}")
        elif _last_watch_snapshot:
            # 交易日已对齐也清 digest，促使下一轮用新行情重算
            _last_snapshot_digest = None
    print(f"[{_now()}] 9:15 状态重置 · 仅保留实仓 · session={sess}")
    return data


def ensure_watch_status_reset_today(*, session: str | None = None) -> None:
    """启动时若已过 9:15 且本日未重置，则补跑一次。"""
    from watch_config import AUCTION_START_HOUR, AUCTION_START_MINUTE, _clock_minutes

    sess = normalize_signal_session(session)
    data = load_holdings()
    if str(data.get("watch_status_reset_session") or "") == sess:
        return
    a15 = int(AUCTION_START_HOUR) * 60 + int(AUCTION_START_MINUTE)
    if _clock_minutes() < a15:
        return
    reset_watch_status_at_auction(session=sess)


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
        _sticky_put(
            sticky,
            code,
            session,
            {
                "bg_class": "warn-sell",
                "alert": alert,
                "pending_sell": True,
                "建议挂单": sig.get("建议挂单"),
                "挂单说明": sig.get("挂单说明"),
                "near_stop": bool(sig.get("near_stop")),
            },
        )
        return sig

    # 当前已非卖出预警：若仍处于近止损缓冲带，则保持上一帧绿底
    if prev and prev.get("bg_class") == "warn-sell":
        keep = False
        prev_alert = str(prev.get("alert") or "")
        # 现价已明显高于止损：立即解除粘滞（涨停/强反弹）
        if stop_px > 0 and float(last_px) > float(stop_px) * 1.005:
            _sticky_drop_sell_keep_buy(sticky, code, session)
            return sig
        # 将止损：距止损因子价仍在 near+0.5% 内则保持
        if "将止损" in prev_alert or prev.get("near_stop"):
            if stop_px > 0:
                r = simple_return(last_px, stop_px)
                dist_pct = None if r is None else abs(r) * 100.0
                if dist_pct is not None and dist_pct <= (near_points + 0.5) + 1e-12:
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
            _sticky_put(
                sticky,
                code,
                session,
                {
                    "bg_class": "warn-sell",
                    "alert": out["alert"],
                    "pending_sell": True,
                    "建议挂单": out.get("建议挂单"),
                    "挂单说明": out.get("挂单说明"),
                    "near_stop": bool(prev.get("near_stop")),
                },
            )
            return out

        _sticky_drop_sell_keep_buy(sticky, code, session)

    return sig


def _should_demote_pre_signal(phase: str) -> bool:
    """非连续竞价时：9:30 前把已触发降成将买入/将止损；午休/收盘保留盘中已触达。"""
    return str(phase or "") not in ("lunch", "closed", "continuous")


def _merge_path_buy_hit(
    hit_open: bool,
    bars_buy: Any,
    *,
    open_px: float,
    entry_pct: float,
    tick: float,
) -> tuple[bool, float | None, Any]:
    """有分钟线走路径；日线最高已触开盘买点时，1m 不全或回退也不把已触买打成未触。"""
    if bars_buy is None or getattr(bars_buy, "empty", True):
        return bool(hit_open), None, None
    buy_path = path_dependent_buy_hit(
        bars_buy,
        open_px=float(open_px),
        entry_pct=float(entry_pct),
        tick=tick,
        allow_attack=DEFAULT_ALLOW_ATTACK,
    )
    hit = bool(buy_path.get("hit_buy"))
    px = None
    if hit and buy_path.get("buy_px"):
        try:
            px = float(buy_path["buy_px"])
        except (TypeError, ValueError):
            px = None
    ts = buy_path.get("touch_ts") if hit else None
    return bool(hit_open or hit), px, ts


def _sticky_same_session(sticky: dict[str, Any], code: str, session: str) -> dict[str, Any]:
    """仅返回同一 session 的粘滞；跨日旧记录一律视为空。

    9:15 清空前加载的扫描若继承昨日 buy_touched/buy_hit_ts 并改写 session，
    会伪造「今日已触买」→ 入槽现价买入且 buy_time 记成昨日、绕过 T+1。
    """
    prev = sticky.get(code)
    if not isinstance(prev, dict):
        return {}
    if str(prev.get("session") or "") != str(session):
        return {}
    return prev


def _sticky_put(
    sticky: dict[str, Any],
    code: str,
    session: str,
    payload: dict[str, Any],
) -> None:
    """写粘滞时保留当日 buy_touched / stop_touched，避免卖出防抖把已触买抹掉。"""
    prev = _sticky_same_session(sticky, code, session)
    st = dict(prev)
    st.update(payload)
    st["session"] = str(session)
    _keep_first_signal_ts(prev, st)
    if bool(prev.get("buy_touched")) or bool(st.get("buy_touched")):
        st["buy_touched"] = True
    if bool(prev.get("stop_touched")) or bool(st.get("stop_touched")):
        st["stop_touched"] = True
        if prev.get("touch_stop") and not st.get("touch_stop"):
            st["touch_stop"] = prev.get("touch_stop")
    sticky[code] = st


def _sticky_drop_sell_keep_buy(
    sticky: dict[str, Any],
    code: str,
    session: str,
) -> None:
    """解除卖出绿底时，当日已触买标记仍留到次日 9:15。"""
    prev = sticky.get(code) if isinstance(sticky.get(code), dict) else None
    if (
        isinstance(prev, dict)
        and bool(prev.get("buy_touched"))
        and str(prev.get("session") or "") == str(session)
    ):
        kept: dict[str, Any] = {"session": str(session), "buy_touched": True}
        if prev.get("buy_hit_ts"):
            kept["buy_hit_ts"] = prev.get("buy_hit_ts")
        sticky[code] = kept
        return
    sticky.pop(code, None)


def _restore_session_buy_hit(
    hit_buy_raw: bool,
    *,
    qty: int,
    sticky_row: dict[str, Any] | None,
    session: str,
) -> bool:
    """当日已触买粘滞：有分钟线、现价离开买点也不摘。次日 9:15 才清。"""
    if int(qty or 0) > 0:
        return bool(hit_buy_raw)
    if not isinstance(sticky_row, dict):
        return bool(hit_buy_raw)
    if str(sticky_row.get("session") or "") != str(session):
        return bool(hit_buy_raw)
    if bool(sticky_row.get("buy_touched")):
        return True
    return bool(hit_buy_raw)


def _stamp_buy_touched(
    sticky: dict[str, Any],
    code: str,
    *,
    session: str,
    ts: Any = None,
    quote: dict[str, Any] | None = None,
) -> None:
    """当日已触买粘滞；第一次记下时分秒。"""
    prev = _sticky_same_session(sticky, code, session)
    payload: dict[str, Any] = {"buy_touched": True}
    if not prev.get("buy_hit_ts"):
        payload["buy_hit_ts"] = _signal_ts_text(ts, quote=quote)
    _sticky_put(sticky, code, session, payload)


def _stamp_stop_touched(
    sticky: dict[str, Any],
    code: str,
    *,
    session: str,
    ts: Any = None,
    quote: dict[str, Any] | None = None,
    touch_stop: float | None = None,
    force_ts: str | None = None,
) -> None:
    """当日已触止损粘滞；第一次记下时分秒。开盘保护可强制写成 09:30。"""
    prev = _sticky_same_session(sticky, code, session)
    payload: dict[str, Any] = {"stop_touched": True}
    if touch_stop:
        payload["touch_stop"] = float(touch_stop)
    forced = str(force_ts or "").strip()
    old_ts = prev.get("stop_hit_ts")
    if forced:
        payload["stop_hit_ts"] = forced
    elif not old_ts:
        payload["stop_hit_ts"] = _signal_ts_text(ts, quote=quote)
    _sticky_put(sticky, code, session, payload)


def _fill_row_signal_times(
    row: dict[str, Any],
    sticky: dict[str, Any],
    code: str,
    *,
    hit_buy: bool = False,
    hit_stop: bool = False,
    buy_time: Any = None,
    realized: dict[str, Any] | None = None,
) -> None:
    """写入 信号时间（时分秒）供盯盘卡片/策略表展示。"""
    st = sticky.get(code) if isinstance(sticky.get(code), dict) else {}
    # 已入槽后本轮未必再算触买：买时分秒仍用粘滞 / 入槽 buy_time
    buy_full = (
        (st or {}).get("buy_hit_ts")
        or buy_time
        or row.get("信号时刻")
        or row.get("_path_buy_ts")
    )
    stop_full = (st or {}).get("stop_hit_ts") or row.get("_path_ts")
    if not stop_full and realized:
        stop_full = (
            realized.get("first_hit_ts")
            or realized.get("time")
        )
    sess = str(row.get("交易日") or (realized or {}).get("session") or "")[:10]
    fill_px = row.get("成交价")
    if fill_px is None and realized:
        fill_px = realized.get("price")
    bell_ts = _open_protect_hit_ts(
        session=sess,
        fill_px=fill_px,
        open_px=row.get("开盘"),
        existing=stop_full,
        open_bell=bool(row.get("_open_bell")),
        exit_kind=str(
            row.get("exit_kind")
            or (realized or {}).get("exit_kind")
            or ""
        ),
    )
    if bell_ts:
        stop_full = bell_ts
    buy_hms = _signal_hms(buy_full)
    stop_hms = _signal_hms(stop_full)
    if buy_hms:
        row["买信号时间"] = buy_hms
    if stop_hms:
        row["卖信号时间"] = stop_hms
    if hit_stop and stop_hms:
        row["信号时间"] = stop_hms
        row["信号时刻"] = str(stop_full)
    elif (hit_buy or str(row.get("已触买") or "") == "是") and buy_hms:
        row["信号时间"] = buy_hms
        row["信号时刻"] = str(buy_full)
    elif stop_hms:
        row["信号时间"] = stop_hms
        row["信号时刻"] = str(stop_full)
    elif buy_hms:
        row["信号时间"] = buy_hms
        row["信号时刻"] = str(buy_full)


def _demote_pre_signal_window(
    sig: dict[str, Any],
    *,
    phase: str | None = None,
) -> dict[str, Any]:
    """9:30 连续竞价前：禁止『已触发』记账/结算，也禁止「待卖出」冒充可执行 SELL。

    · 09:15–09:25 → 竞价观察（持仓仍「已经买入」）
    · 09:25–09:30 → 竞价止损/买入预警（仍「已经买入」/「待买入」）
    """
    out = dict(sig)
    out["hit_buy"] = False
    out["hit_stop"] = False
    ph = str(phase or market_phase() or "")
    alert = str(out.get("alert") or "").strip()
    trig = str(out.get("因子触发") or "").strip()
    if alert == "已触买" or alert.startswith("已触买"):
        out["alert"] = "将买入"
        out["pending_buy"] = True
        out["near_buy"] = True
        out["bg_class"] = out.get("bg_class") or "warn-buy"
        out["持仓状态"] = "待买入"
        out["因子触发"] = "接近"
        note = str(out.get("挂单说明") or "")
        if "可挂单" not in note and "竞价" not in note:
            out["挂单说明"] = (
                (note + "；" if note else "") + "9:25 可挂单；9:30 起才计已触发"
            )
    elif (
        alert == "已触止损"
        or alert.startswith("已触止损")
        or alert == "半仓止盈"
        or alert.startswith("半仓止盈")
        or alert.endswith("待盘中结算")
    ):
        half = alert.startswith("半仓") or "半仓" in alert
        ui = pre_continuous_stop_ui(phase=ph, half=half)
        out["alert"] = ui["alert"]
        out["pending_sell"] = True
        out["near_stop"] = True
        out["bg_class"] = ui["bg_class"]
        out["持仓状态"] = ui["持仓状态"]  # 已经买入，不是待卖出
        out["因子触发"] = ui["因子触发"]
        out["可执行"] = False
        note = str(out.get("挂单说明") or "")
        suffix = str(ui.get("挂单说明") or "")
        if suffix and suffix not in note:
            out["挂单说明"] = (note + "；" if note else "") + suffix
    elif trig == "已触发" or trig.startswith("已触发"):
        out["因子触发"] = "接近"
    return out


# _buy_signal_active / _row_hit_buy：见 watch_buy_signal（信号≠入槽）


def _annotate_unfilled_buy_signals(
    rows: list[dict[str, Any]],
    slot_meta: dict[str, Any],
) -> None:
    """委托 watch_buy_signal；槽满仍发触买预警。"""

    def _log(n_hit: int, n_gate: int) -> None:
        print(
            f"[{_now()}] 买入信号标注: 未入槽触买 {n_hit}"
            + (f" · 已忽略未过门弱信号 {n_gate}" if n_gate else "")
        )

    _annotate_buy_signals_core(
        rows,
        slot_meta,
        is_stop_closed=_is_stop_closed_status,
        log=_log,
    )


def _overlay_buy_signal_on_hold(
    sig: dict[str, Any],
    *,
    hit_buy: bool,
    allow_entry: bool,
    paper_active: bool,
    qty: int,
    buy_time: str | None,
    session: str,
    buy_trigger: float,
    stop_px: float,
    last_px: float,
    px_digits: int,
    near_points: float = NEAR_FACTOR_PCT,
) -> dict[str, Any]:
    """策略回放持有时，若今日仍触买或近买点，叠加买入信号（防漏单）。

    实仓 qty>0 已入槽：保持「已经买入/待卖出」，绝不改回「待买入」。
    """
    if not allow_entry:
        return sig
    # 真仓已占用槽位：不再叠「待买入」文案
    if qty > 0:
        return sig
    if not paper_active:
        return sig

    pf = f"{{:.{px_digits}f}}"
    buy_fmt = pf.format(buy_trigger)
    stop_fmt = pf.format(stop_px)
    hold_tag = "策略回放持有"
    sig = dict(sig)

    dist_pct = None
    if float(buy_trigger) > 0:
        r = simple_return(last_px, buy_trigger)
        dist_pct = None if r is None else abs(r) * 100.0
    near_buy = dist_pct is not None and dist_pct <= near_points + 1e-12

    if hit_buy:
        sig.update(
            {
                "alert": "已触买",
                "bg_class": "warn-buy",
                "pending_buy": True,
                "near_buy": True,
                "持仓状态": "待买入",
                "因子侧": "买入",
                "因子价": round(float(buy_trigger), px_digits),
                "因子触发": "已触发",
                "建议挂单": round(float(buy_trigger), px_digits),
                "挂单说明": (
                    f"{hold_tag}·买入侧@{buy_fmt}；"
                    f"卖出侧(止损)@{stop_fmt}"
                ),
                "hit_buy": True,
            }
        )
        return sig

    if near_buy:
        dist_txt = f"{dist_pct:+.2f}%" if dist_pct is not None else "-"
        sig.update(
            {
                "alert": "将买入",
                "bg_class": "warn-buy",
                "pending_buy": True,
                "near_buy": True,
                "持仓状态": "待买入",
                "因子侧": "买入",
                "因子价": round(float(buy_trigger), px_digits),
                "因子触发": "接近",
                "建议挂单": round(float(buy_trigger), px_digits),
                "挂单说明": (
                    f"{hold_tag}·近买入侧@{buy_fmt}（现差{dist_txt}）；"
                    f"卖出侧(止损)@{stop_fmt}"
                ),
            }
        )
    return sig


def _freeze_closed_exit_levels(row: dict[str, Any]) -> None:
    """已平仓：卖出侧/止损冻结为成交价，不用盘中抬高后的工作止损。"""
    if row.get("error"):
        return
    if not (
        _is_stop_closed_status(str(row.get("持仓状态") or "")) or bool(row.get("已实现"))
    ):
        return
    fill = _as_money(row.get("成交价"))
    if fill is None:
        return
    pdg = int(row.get("价位小数") or 2)
    px = round(float(fill), pdg)
    row["止损"] = px
    row["基础止损"] = px
    row["卖出侧价"] = px


def _enrich_side_price_fields(row: dict[str, Any]) -> None:
    """写入买入侧/卖出侧展示价，并在说明中标注两侧挂单价。"""
    _freeze_closed_exit_levels(row)
    if row.get("error") or not row.get("阈值就绪"):
        return
    pdg = int(row.get("价位小数") or 2)
    pf = f"{{:.{pdg}f}}"
    buy = row.get("买点")
    stop = row.get("止损")
    if buy is not None:
        row["买入侧价"] = round(float(buy), pdg)
    if stop is not None:
        row["卖出侧价"] = round(float(stop), pdg)
    note = str(row.get("挂单说明") or "")
    if buy is None or stop is None:
        return
    if "买入侧" in note or "卖出侧" in note:
        return
    side_note = f"买入侧@{pf.format(float(buy))} · 卖出侧@{pf.format(float(stop))}"
    row["挂单说明"] = f"{side_note}；{note}" if note else side_note


def _account_cash(data: dict[str, Any] | None = None) -> float | None:
    data = data if data is not None else load_holdings()
    return _as_cash(data.get("account_cash"))


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
    """总资产：优先 现金+市值；有实仓但市值未到则沿用登记值，不退回仅现金。"""
    data = data if data is not None else load_holdings()
    cash = _account_cash(data)
    registered = _as_money(data.get("account_total"))
    if cash is not None and rows is not None:
        mv = _holdings_market_value(rows)
        if mv > 0 or not _account_has_open_qty(data):
            return round(cash + mv, 2)
        return registered if registered is not None else round(float(cash), 2)
    return registered


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
    mv = _holdings_market_value(rows)
    if _account_has_open_qty(data) and mv <= 0:
        return _as_money(data.get("account_total"))
    total = round(cash + mv, 2)
    if data.get("account_total") != total:
        data["account_total"] = total
        save_holdings(data)
    return total


def save_holdings(data: dict[str, Any]) -> None:
    from holdings_sync import current_host

    host = current_host()

    def _stamp(d: dict[str, Any]) -> None:
        d["updated_at"] = _now()
        d["updated_host"] = host

    _stamp(data)
    _HOLDINGS_STORE.save(data, stamp=_stamp)


def _purge_stale_realized(data: dict[str, Any], session: str) -> None:
    """清除非当日已实现记录 / 三槽平仓留痕，避免隔日污染合计。"""
    realized = data.setdefault("realized_today", {})
    stale = [k for k, v in realized.items() if str(v.get("session") or "") != session]
    for k in stale:
        del realized[k]
    traces = data.get("closed_today")
    if isinstance(traces, dict):
        reset_container(
            data,
            "closed_today",
            {
                k: v
                for k, v in traces.items()
                if isinstance(v, dict) and str(v.get("session") or "") == session
            },
        )
    q = data.get("slot_queue")
    if not isinstance(q, dict) or str(q.get("session") or "")[:10] != str(session)[:10]:
        reset_container(
            data, "slot_queue", {"session": str(session)[:10], "freed_at": []}
        )


def _slot_closed_map(
    data: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    raw = (data if data is not None else load_holdings()).get("closed_today")
    return raw if isinstance(raw, dict) else {}


def _forget_slot_closed(code: str) -> None:
    """再入槽后允许下一笔平仓重新记当日留痕。"""
    ck = _code_key(code)
    if not ck:
        return
    data = load_holdings()
    traces = data.get("closed_today")
    if not isinstance(traces, dict) or ck not in traces:
        return
    del traces[ck]
    save_holdings(data)


def _remember_slot_closed(row: dict[str, Any]) -> None:
    """记下今日三槽平仓；下一交易日用 session 对不上来清空展示。"""
    sess = str(row.get("交易日") or "")[:10]
    code = _code_key(str(row.get("代码") or ""))
    if not sess or not code:
        return
    try:
        qty = int(row.get("卖出数量") or 0)
    except (TypeError, ValueError):
        qty = 0
    rec = {
        "session": sess,
        "name": row.get("名称"),
        "qty": qty,
        "price": row.get("成交价"),
        "day_pnl": row.get("当日盈亏"),
        "day_pnl_pct": row.get("当日盈亏%"),
    }
    data = load_holdings()
    traces = data.setdefault("closed_today", {})
    old = traces.get(code) if isinstance(traces.get(code), dict) else None
    if old == rec:
        return
    traces[code] = rec
    save_holdings(data)


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


def apply_paper_slot_buy(
    *,
    code: str,
    meta: dict[str, Any],
    price: float,
    qty: int,
    note: str = "槽位触买(自动)",
    buy_time: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """纸面自动入仓：写 qty/成本/buy_time；扣减 account_cash（若有）。

    buy_time 用触发时刻（1m 触达或 5s 行情 last_ts），不是进程扫到的现在。
    成交价：新触发=买点；平仓前已触买的第一梯队=现价（不得超过买点 +1%）。
    Capital V2：不允许加仓；不允许把现金买成负数（ALLOW_NEGATIVE_CASH_FOR_BUY=False）。
    传 session 时 buy_time 必须落在该交易日，否则拒买（跨日 buy_time 会绕过 T+1）。
    """
    price = float(price)
    qty = int(qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")
    if session:
        bt = str(buy_time or "").strip()
        if bt and not bt.startswith("9999"):
            bt_day = (_bar_ts_str(bt) or bt)[:10]
            if bt_day != str(session)[:10]:
                raise ValueError("STALE_BUY_TRIGGER")
    data = load_holdings()
    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    if old_qty > 0:
        # NO PYRAMIDING：已有仓位不加仓
        return pos
    cash = _account_cash(data)
    notional = round(price * qty, 2)
    if cash is not None and not ALLOW_NEGATIVE_CASH_FOR_BUY:
        if cash < 0:
            raise ValueError("NEGATIVE_CASH")
        if cash + 1e-9 < notional:
            raise ValueError("INSUFFICIENT_CASH")
    pos["qty"] = qty
    pos["cost"] = round(price, 4)
    pos["today_cost"] = round(price, 4)
    pos["peak_high"] = round(price, 4)
    pos["peak_high_at"] = None  # filled below with buy_time
    pos["available"] = 0
    raw_ts = str(buy_time or "").strip()
    if raw_ts.startswith("9999"):
        raw_ts = ""
    hit_ts = _bar_ts_str(raw_ts) if raw_ts else None
    hit_ts = hit_ts or _now()
    pos["buy_time"] = hit_ts
    pos["peak_high_at"] = hit_ts
    pos["tp_stage"] = 0
    pos["last_tp_ts"] = None
    pos["note"] = note
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if cash is not None:
        data["account_cash"] = round(cash - notional, 2)
    # 负现金也要记交割余额（历史卖出路径）；新 BUY 上面已拦截
    try:
        cash_after = float(data.get("account_cash")) if data.get("account_cash") is not None else None
    except (TypeError, ValueError):
        cash_after = None
    pool = data.get("portfolio_pool")
    if isinstance(pool, list):
        ck = _code_key(code)
        if ck not in {_code_key(str(c)) for c in pool}:
            pool.append(ck)
            data["portfolio_pool"] = pool
    traces = data.get("closed_today")
    if isinstance(traces, dict):
        traces.pop(_code_key(code), None)
    session = str(hit_ts)[:10]
    pop_slot_freed_at(data, session)
    save_holdings(data)
    append_trade(
        {
            "time": hit_ts,
            "side": "buy",
            "code": code,
            "name": meta["name"],
            "market": meta.get("market") or "",
            "price": price,
            "qty": qty,
            "after_qty": qty,
            "avg_cost": pos["cost"],
            "cost": pos["cost"],
            "amount": notional,
            "account_cash_after": cash_after,
            "session": session,
            "reason": "买入入槽",
            "note": note,
            "reason_detail": note,
        }
    )
    try:
        from wechat_notify import notify_trade_fill

        notify_trade_fill(
            side="buy",
            code=code,
            name=str(meta.get("name") or code),
            price=float(price),
            qty=int(qty),
            reason=note or "买入入槽",
            before_qty=0,
            after_qty=int(qty),
            strategy_id=str(STRATEGY_ID),
            # 开盘突破入槽：成交价即策略买点；若 meta 带买点则优先
            target_px=float(
                meta.get("buy")
                or meta.get("买点")
                or meta.get("entry_px")
                or price
            ),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 买入微信推送跳过: {e}")
    return pos


def _buy_distance_pct(row: dict[str, Any]) -> float:
    """距买点还差多少%（0=已到/越过）；无法计算返回很大值。"""
    buy = row.get("买点")
    if buy is None:
        buy = row.get("买入侧价")
    last = row.get("现价")
    try:
        buy_f = float(buy) if buy is not None else 0.0
        last_f = float(last) if last is not None else 0.0
    except (TypeError, ValueError):
        return 9_999.0
    if buy_f <= 0 or last_f <= 0:
        return 9_999.0
    if last_f >= buy_f:
        return 0.0
    return round((buy_f - last_f) / buy_f * 100.0, 4)


def _slot_notional_budget(
    account_total: float | None,
    rows: list[dict[str, Any]],
    occupied: list[str],
) -> float | None:
    """单票目标金额：总权益 × MAX_POSITION_WEIGHT（V2=20%）。"""
    if account_total is not None and float(account_total) > 0:
        return target_position_notional(float(account_total))
    if DEFAULT_ACCOUNT_TOTAL and float(DEFAULT_ACCOUNT_TOTAL) > 0:
        return target_position_notional(float(DEFAULT_ACCOUNT_TOTAL))
    mv = _holdings_market_value(rows)
    n = len(occupied)
    if n > 0 and mv > 0:
        return round(mv / float(n), 2)
    return None


def _paper_slot_qty(
    price: float,
    *,
    account_total: float | None = None,
    cash: float | None = None,
) -> int:
    """纸面单票目标股数：权益×权重 / 价，向下取整到一手；可选现金约束。"""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return 0
    if px <= 0:
        return 0
    try:
        equity = float(account_total) if account_total is not None else 0.0
    except (TypeError, ValueError):
        equity = 0.0
    if equity <= 0:
        equity = float(DEFAULT_ACCOUNT_TOTAL)
    qty, _reason = capital_buy_qty(
        price=px,
        equity=equity,
        cash=cash,
        weight=float(SLOT_WEIGHT),
        allow_negative_cash=bool(ALLOW_NEGATIVE_CASH_FOR_BUY),
        lot=int(LOT_SIZE),
    )
    return int(qty)


def today_slot_buy_ranks(
    session: str,
    *,
    text: str | None = None,
) -> dict[str, int]:
    """当日槽位触买先后：trades.jsonl 里每只票第一次「槽位触买」的出现序。

    用于空槽入队：先买先占槽，不按现距买点重排。
    """
    ranks: dict[str, int] = {}
    day = str(session or "")[:10]
    if len(day) < 10:
        return ranks
    raw = text
    if raw is None:
        if not TRADES_FILE.exists():
            return ranks
        raw = TRADES_FILE.read_text(encoding="utf-8")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if str(rec.get("side") or "").lower() not in ("buy", "买入"):
            continue
        note = str(rec.get("note") or "")
        if "槽位触买" not in note:
            continue
        t = str(rec.get("time") or "")
        if not t.startswith(day):
            continue
        code = _code_key(str(rec.get("code") or ""))
        if not code or code in ranks:
            continue
        ranks[code] = len(ranks)
    return ranks


def today_new_symbol_codes(
    session: str,
    *,
    text: str | None = None,
) -> list[str]:
    """当日新开仓 unique symbols（从 trades.jsonl BUY 重建；restart 可恢复）。

    第一版禁止加仓，故每条 BUY 即一次 NEW POSITION。SELL 不删除当日额度计数。
    """
    day = str(session or "")[:10]
    if len(day) < 10:
        return []
    raw = text
    if raw is None:
        try:
            tp = Path(__file__).resolve().parent / "trades.jsonl"
            raw = tp.read_text(encoding="utf-8") if tp.exists() else ""
        except OSError:
            raw = ""
    seen: list[str] = []
    seen_set: set[str] = set()
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if str(rec.get("side") or "").lower() not in ("buy", "买入"):
            continue
        ts = str(rec.get("time") or rec.get("ts") or "")
        sess = str(rec.get("session") or "")[:10]
        if not (ts.startswith(day) or sess == day):
            continue
        code = _code_key(str(rec.get("code") or ""))
        if not code or code in seen_set:
            continue
        seen_set.add(code)
        seen.append(code)
    return seen


def today_slot_buy_count(session: str, *, text: str | None = None) -> int:
    """当日新开仓 unique symbol 数（= daily new symbols；非 BUY call 次数）。"""
    return len(today_new_symbol_codes(session, text=text))


def _apply_portfolio_slots(
    rows: list[dict[str, Any]],
    *,
    account_total: float | None,
    phase_now: str,
) -> dict[str, Any]:
    """Capital V2：最多同时 MAX_POSITION_SYMBOLS；当日最多新增 MAX_NEW_SYMBOLS_PER_SESSION。

    · 用户实仓 qty>0 占槽；可买空槽见 free_buy_slot_count
    · 入槽顺序：先平再买；平仓前已触买且现价≤买点+1% 优先、按触发先后、成交价=现价；否则平仓后新触发按时间、成交价=买点
    · 单票目标 = 决策时权益 × MAX_POSITION_WEIGHT，再受 available cash 约束；不得负现金买入
    · 止损平仓后释放总槽位，但当日新增额度不因 SELL 恢复；该票当日不可再买
    """
    data = load_holdings()
    try:
        from watch_config import code_key, prune_portfolio_pool

        before_pool = sorted(code_key(str(c)) for c in (data.get("portfolio_pool") or []))
        pruned = prune_portfolio_pool(data)
        if pruned != before_pool:
            save_holdings(data)
    except Exception:  # noqa: BLE001
        pass
    occupied = occupied_slot_codes(data)
    free = free_buy_slot_count(data)
    occupied_set = set(occupied)
    # 额度绑定 trading_session_date（与日结同源），不是自然日午夜
    session = str(trading_session_date())
    for r in rows:
        day = str(r.get("交易日") or "")
        if day and day != "-" and len(day) >= 10:
            # 展示仍可用行情日；配额以日历交易日为准
            break
    buy_ranks = today_slot_buy_ranks(session)
    new_today = today_new_symbol_codes(session)
    buys_done = len(new_today)
    buys_left = max(0, int(MAX_NEW_SYMBOLS_PER_SESSION) - buys_done)

    try:
        from watch_config import strategy_watchlist_codes

        strategy_codes = set(strategy_watchlist_codes())
    except Exception:  # noqa: BLE001
        strategy_codes = set()

    for r in rows:
        code = _code_key(str(r.get("代码") or ""))
        r["槽位占用"] = code in occupied_set and int(r.get("持仓") or 0) > 0
        r["槽位候选"] = False
        r["距买点%"] = _buy_distance_pct(r)

    candidates: list[tuple[int, float, str, dict[str, Any]]] = []
    for r in rows:
        if r.get("error"):
            continue
        code = _code_key(str(r.get("代码") or ""))
        if int(r.get("持仓") or 0) > 0 or code in occupied_set:
            continue
        if bool(r.get("当日禁买")):
            continue
        # 只从当前默认策略池入场（strategy16=核心龙头）；旧 portfolio_pool 遗留票不买
        if code not in strategy_codes:
            continue
        pos = str(r.get("持仓状态") or "")
        if pos in ("当日禁买",) or _is_stop_closed_status(pos):
            continue
        if r.get("过门OK") is False:
            continue
        dist = float(r.get("距买点%") if r.get("距买点%") is not None else 9_999.0)
        if dist >= 9_000:
            continue
        rank = int(buy_ranks.get(code, 10_000))
        candidates.append((rank, dist, code, r))
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    # 展示：空槽附近票标候选；已触买信号无论能否入槽都标候选（预警≠成交）
    selected = candidates[: max(0, free)]
    selected_codes = {c for _, _, c, _ in selected}
    for _, _, _c, r in selected:
        r["槽位候选"] = True
    for _rank, _dist, _c, r in candidates:
        if _row_hit_buy(r):
            r["槽位候选"] = True

    bought_codes: list[str] = []
    skipped: list[dict[str, Any]] = []
    if phase_now == "continuous" and free > 0 and buys_left > 0:
        # 入槽：只吃「已触买」。先平再买；第一梯队现价、其后新触发买点
        hit_queue = [
            (rank, dist, code, r)
            for rank, dist, code, r in candidates
            if _row_hit_buy(r)
        ]
        equity = float(account_total) if account_total and float(account_total) > 0 else float(
            DEFAULT_ACCOUNT_TOTAL
        )
        used: set[str] = set()
        while True:
            data = load_holdings()
            if free_buy_slot_count(data) <= 0:
                break
            opened = today_new_symbol_codes(session)
            if len(opened) >= int(MAX_NEW_SYMBOLS_PER_SESSION):
                break
            freed_at = peek_slot_freed_at(data, session)

            def _fill_of(row: dict[str, Any]) -> dict[str, Any] | None:
                try:
                    signal = float(
                        row.get("买点")
                        or row.get("已触发因子价")
                        or row.get("买入侧价")
                        or 0
                    )
                    last = float(row.get("现价") or 0)
                except (TypeError, ValueError):
                    return None
                return slot_fill_decision(
                    signal_px=signal,
                    last_px=last,
                    trigger_ts=_row_trigger_ts(row, side="buy"),
                    freed_at=freed_at,
                    overshoot=SLOT_FIRST_TIER_MAX_OVERSHOOT,
                )

            ranked: list[tuple[str, str, str, dict[str, Any], dict[str, Any]]] = []
            for _rank, _dist, code, r in hit_queue:
                if code in used:
                    continue
                if bool(r.get("当日禁买")):
                    continue
                if int((data.get("positions") or {}).get(code, {}).get("qty") or 0) > 0:
                    continue
                trig = _row_trigger_ts(r, side="buy")
                if not trig.startswith("9999") and trig[:10] != str(session)[:10]:
                    skipped.append({"code": code, "reason": "STALE_BUY_TRIGGER", "trigger_ts": trig})
                    used.add(code)
                    continue
                dec = _fill_of(r)
                if dec is None:
                    continue
                tier = "0" if dec.get("kind") == "last" else "1"
                ranked.append((tier, trig, code, r, dec))
            ranked.sort(key=lambda x: (x[0], x[1], x[2]))
            if not ranked:
                break
            _tier, _trig, code, r, dec = ranked[0]
            try:
                if cannot_buy_limit_up(
                    prev_close=r.get("昨收"),
                    open_px=float(r.get("开盘") or 0),
                    high_px=float(r.get("最高") or 0),
                    low_px=float(r.get("最低") or 0),
                    close_px=float(r.get("现价") or 0),
                ):
                    used.add(code)
                    continue
            except (TypeError, ValueError):
                pass
            price = float(dec.get("fill_px") or 0)
            if price <= 0:
                used.add(code)
                continue
            cash_now = _account_cash(data)
            qty, skip_reason = capital_buy_qty(
                price=price,
                equity=equity,
                cash=cash_now,
                weight=float(MAX_POSITION_WEIGHT),
                allow_negative_cash=bool(ALLOW_NEGATIVE_CASH_FOR_BUY),
                lot=int(LOT_SIZE),
            )
            if qty < int(LOT_SIZE) or skip_reason:
                reason = skip_reason or "INSUFFICIENT_CASH"
                skipped.append({"code": code, "reason": reason})
                note = str(r.get("挂单说明") or "")
                tag = f"资金规则未开仓:{reason}"
                r["挂单说明"] = f"{tag}；{note}" if note else tag
                r["资金规则"] = reason
                used.add(code)
                continue
            meta = {
                "code": code,
                "name": str(r.get("名称") or code),
                "market": str(r.get("市场") or ""),
            }
            fill_kind = "现价" if dec.get("kind") == "last" else "买点"
            try:
                pos = apply_paper_slot_buy(
                    code=code,
                    meta=meta,
                    price=price,
                    qty=qty,
                    note=f"槽位触买(自动·{fill_kind})",
                    buy_time=_row_trigger_ts(r, side="buy"),
                    session=str(session)[:10],
                )
            except ValueError as e:
                reason = str(e) or "INSUFFICIENT_CASH"
                skipped.append({"code": code, "reason": reason})
                note = str(r.get("挂单说明") or "")
                tag = f"资金规则未开仓:{reason}"
                r["挂单说明"] = f"{tag}；{note}" if note else tag
                r["资金规则"] = reason
                used.add(code)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 槽位自动买入失败 {code}: {e}")
                used.add(code)
                continue
            # 加仓短路：apply 返回原仓且 qty 未变
            if int(pos.get("qty") or 0) <= 0:
                used.add(code)
                continue
            used.add(code)
            bought_codes.append(code)
            r["持仓"] = int(pos.get("qty") or qty)
            r["成本"] = pos.get("cost")
            r["可用"] = int(pos.get("available") or 0)
            r["槽位占用"] = True
            r["槽位候选"] = False
            r["已实现"] = False
            r["持仓状态"] = "已经买入"
            r["预警"] = ALERT_FILLED
            r["因子侧"] = "持有"
            px_digits = int(r.get("价位小数") or 2)
            last = r.get("现价")
            fill_qty = int(pos.get("qty") or qty)
            if last is not None and pos.get("cost") is not None:
                try:
                    last_f = float(last)
                    cost_f = float(pos["cost"])
                    pnl, pnl_pct = mark_unrealized(last_f, cost_f, fill_qty)
                    r["浮盈"] = pnl
                    r["浮盈%"] = pnl_pct
                    r["市值"] = round(last_f * fill_qty, 2)
                    r["成本额"] = round(cost_f * fill_qty, 2)
                    day_pnl, day_pct, day_base = session_day_pnl(
                        mark=last_f,
                        qty=fill_qty,
                        cost=cost_f,
                        prev_close=r.get("昨收"),
                        bought_today=True,
                        fallback=r.get("开盘"),
                    )
                    r["当日盈亏"] = day_pnl
                    r["当日盈亏%"] = day_pct
                    r["当日基数"] = day_base
                except (TypeError, ValueError):
                    pass
            note = str(r.get("挂单说明") or "")
            fill_note = f"槽位自动买入{fill_qty}股@{price:.{px_digits}f}（{fill_kind}）"
            r["挂单说明"] = f"{fill_note}；{note}" if note else fill_note
            remember_factor_trigger(
                code,
                side="buy",
                px=price,
                session=str(r.get("交易日") or session),
            )
    elif phase_now == "continuous":
        # 记录为何整轮无法买：总槽满 or 日新增额度满
        if free <= 0:
            block = "MAX_POSITION_SYMBOLS"
        elif buys_left <= 0:
            block = "DAILY_NEW_SYMBOL_LIMIT"
        else:
            block = None
        if block:
            for _rank, _dist, code, r in candidates:
                if _row_hit_buy(r) and int(r.get("持仓") or 0) <= 0:
                    note = str(r.get("挂单说明") or "")
                    tag = f"资金规则未开仓:{block}"
                    if tag not in note:
                        r["挂单说明"] = f"{tag}；{note}" if note else tag
                    r["资金规则"] = block
                    skipped.append({"code": code, "reason": block})

    meta = _slot_meta_from_holdings(load_holdings())
    meta["candidates"] = sorted(selected_codes)
    meta["bought"] = bought_codes
    meta["skipped"] = skipped
    opened_now = today_new_symbol_codes(session)
    meta["buysToday"] = len(opened_now)
    meta["buysLeft"] = max(0, int(MAX_NEW_SYMBOLS_PER_SESSION) - len(opened_now))
    meta["newSymbolsToday"] = opened_now
    meta["newSymbolsLeft"] = meta["buysLeft"]
    meta["session"] = session
    return meta


def _bar_ts_str(ts: Any) -> str | None:
    """1m 触达时刻 → 可比较的本地时间串（半仓后 since_ts）。"""
    if ts is None:
        return None
    try:
        t = pd.Timestamp(ts)
        if getattr(t, "tzinfo", None) is not None:
            t = t.tz_convert("Asia/Shanghai").tz_localize(None)
        return t.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        s = str(ts).strip()
        return s or None


def _signal_ts_text(ts: Any = None, *, quote: dict[str, Any] | None = None) -> str:
    """触发时刻：优先 1m/传入 ts，否则行情 last_ts，再否则现在。含时分秒。"""
    s = _bar_ts_str(ts) if ts is not None else None
    if s:
        return s
    if quote:
        last_ts = str(quote.get("last_ts") or quote.get("time") or "").strip()
        parsed = _bar_ts_str(last_ts) if last_ts else None
        if parsed:
            return parsed
        if last_ts:
            return last_ts
    return _now()


def _signal_hms(full: Any) -> str | None:
    """YYYY-MM-DD HH:MM:SS → HH:MM:SS。"""
    if full is None:
        return None
    s = str(full).strip()
    if not s:
        return None
    clock = s.split()[-1] if " " in s else s
    if len(clock) >= 8 and clock[2:3] == ":":
        return clock[:8]
    return clock or None


def _row_trigger_ts(row: dict[str, Any], *, side: str = "buy") -> str:
    """入槽/平仓排序用的触发时刻。5s 行情或 1m 触达，缺则排最后。"""
    sess = str(row.get("交易日") or "")[:10]
    if side == "sell":
        keys = ("信号时刻", "卖信号时间", "_path_ts")
    else:
        keys = ("信号时刻", "买信号时间", "_path_buy_ts")
    for k in keys:
        v = row.get(k)
        if v is None or v == "":
            continue
        s = str(v).strip()
        if not s:
            continue
        if " " not in s and sess and len(s) >= 8 and s[2:3] == ":":
            return f"{sess} {s[:8]}"
        parsed = _bar_ts_str(s)
        if parsed:
            return parsed
        return s
    return "9999-99-99 99:99:99"


def _is_open_bell_ts(ts: Any) -> bool:
    hms = _signal_hms(ts) or ""
    return hms[:5] == "09:30"


def _is_early_open_1m_label(ts: Any) -> bool:
    """缺 09:30 时的首根 1m 常见标签 09:31/09:32；不可把 09:58 PATH 当此类标签。"""
    hms = _signal_hms(ts) or ""
    return hms[:5] in ("09:31", "09:32")


def _is_auction_or_early_open_ts(ts: Any) -> bool:
    """09:15–09:32：竞价观察戳 / 缺 09:30 的首根。开盘铃可覆盖成 09:30。"""
    hms = _signal_hms(ts) or ""
    if len(hms) < 5:
        return False
    return "09:15:00" <= hms <= "09:32:59"


def _open_protect_hit_ts(
    *,
    session: str,
    fill_px: Any = None,
    open_px: Any = None,
    existing: Any = None,
    open_bell: bool = False,
    exit_kind: str | None = None,
) -> str | None:
    """开盘保护成交时刻：仅 open_bell / exit_kind=open_protect 才固定 09:30。

    EVENT IMMUTABILITY / NO LOOK-AHEAD（docs/TEMPORAL_INTEGRITY.md）：
    **禁止**用 fill≈open 反推开盘时刻（PATH 触达价碰巧等于今开时不得改写成 09:30）。
    fill_px / open_px 参数保留以兼容旧调用，不再参与推断。
    """
    del fill_px, open_px  # 明确不参与时间推断
    bell = session_open_bell_ts(session)
    if open_bell or str(exit_kind or "") == "open_protect":
        return bell
    return _bar_ts_str(existing) if existing else None


def _keep_first_signal_ts(prev: dict[str, Any], st: dict[str, Any]) -> None:
    for key in ("buy_hit_ts", "stop_hit_ts"):
        old = prev.get(key)
        if not old:
            continue
        new = st.get(key)
        # 仅允许：真正开盘铃 09:30 覆盖竞价观察戳 / 缺 bar 的 09:31/09:32
        if (
            key == "stop_hit_ts"
            and new
            and _is_open_bell_ts(new)
            and (
                _is_early_open_1m_label(old) or _is_auction_or_early_open_ts(old)
            )
        ):
            continue
        st[key] = old


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
    action_kind: str = "",
    first_hit_ts: str | None = None,
    exit_kind: str = "",
) -> dict[str, Any]:
    """卖出视为已成交：按成交价锁定盈亏；可只卖可用股，剩余仓继续持有。

    半仓（action_kind=half / reason=半仓止盈）后允许当日再卖剩余；
    全清记录才短路。旧记录无 after_qty 一律当全清。
    """
    data = load_holdings()
    _purge_stale_realized(data, session)
    realized = data.setdefault("realized_today", {})
    existing = realized.get(code)
    if (
        existing
        and str(existing.get("session") or "") == session
        and existing.get("reason") in EXIT_REASONS
    ):
        after = existing.get("after_qty")
        full_exit = existing.get("full_exit")
        if full_exit is True:
            return existing
        if after is None:
            return existing
        try:
            if int(after) <= 0:
                return existing
        except (TypeError, ValueError):
            return existing

    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    sell_qty = max(0, min(int(qty), old_qty))
    if sell_qty <= 0:
        return existing or {}

    fill_px = float(fill_px)
    cost_f = float(cost) if cost is not None else None
    pnl, pnl_pct = mark_unrealized(fill_px, cost_f, sell_qty)
    bought_today = is_t1_buy_day(buy_time, session)
    day_pnl, day_pnl_pct, day_base = session_day_pnl(
        mark=fill_px,
        qty=sell_qty,
        cost=cost_f,
        prev_close=prev_close,
        bought_today=bool(bought_today),
        fallback=float(open_px) if open_px is not None else None,
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
        "time": _bar_ts_str(first_hit_ts) or _now(),
        "first_hit_ts": _bar_ts_str(first_hit_ts),
        "triggered_at": _bar_ts_str(first_hit_ts) or _now(),
        "filled_at": _bar_ts_str(first_hit_ts) or _now(),
        "decision_at": _bar_ts_str(first_hit_ts) or _now(),
        "exit_kind": str(exit_kind or ""),
        "action_kind": str(action_kind or ""),
    }
    # 时间链：禁止事后用价格反推；immutable 一旦写入不再因日K/新行情改写
    from temporal_integrity import assert_event_time_chain

    try:
        assert_event_time_chain(
            decision_at=rec["decision_at"],
            triggered_at=rec["triggered_at"],
            filled_at=rec["filled_at"],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] TEMPORAL reject exit fill {code}: {e}")
        return existing or {}
    realized[code] = rec

    new_qty = old_qty - sell_qty
    rec["after_qty"] = int(new_qty)
    rec["full_exit"] = bool(new_qty <= 0)
    pos["qty"] = new_qty
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    if new_qty <= 0:
        pos["qty"] = 0
        pos["cost"] = None
        pos["buy_time"] = None
        pos["available"] = None
        pos["today_cost"] = None
        pos["tp_stage"] = 0
        pos["last_tp_ts"] = None
        pos["stop_noted"] = False
        pos["stop_noted_px"] = None
        pos["stop_noted_session"] = None
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
        half = bool(
            str(action_kind or "") == "half"
            or reason == REASON_HALF
            or is_half_stop_kind(str(action_kind or ""), action_kind)
        )
        if half:
            pos["tp_stage"] = 1
            ts = _bar_ts_str(first_hit_ts) or _now()
            pos["last_tp_ts"] = ts
        # 已兑现止损备注则清已记
        if reason in (REASON_STOP, REASON_HALF):
            pos["stop_noted"] = False
            pos["stop_noted_px"] = None
            pos["stop_noted_session"] = None

    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash + fill_px * sell_qty, 2)
    try:
        cash_after = (
            float(data.get("account_cash"))
            if data.get("account_cash") is not None
            else None
        )
    except (TypeError, ValueError):
        cash_after = None

    if new_qty <= 0:
        append_slot_freed_at(data, session, rec.get("time") or rec.get("first_hit_ts"))

    save_holdings(data)
    append_trade(
        {
            "time": rec["time"],
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "market": meta.get("market") or "",
            "price": rec["price"],
            "qty": sell_qty,
            "after_qty": int(pos["qty"]),
            "cost": rec["cost"],
            "pnl": rec["pnl"],
            "pnl_pct": rec.get("pnl_pct"),
            "day_pnl": rec.get("day_pnl"),
            "day_pnl_pct": rec.get("day_pnl_pct"),
            "amount": round(float(rec["price"]) * sell_qty, 2),
            "account_cash_after": cash_after,
            "session": str(session)[:10],
            "action_kind": str(action_kind or ""),
            "buy_time": str(buy_time or "") or None,
            "reason": reason,
            "note": trade_note,
            "reason_detail": trade_note,
        }
    )
    try:
        from wechat_notify import notify_trade_fill

        notify_trade_fill(
            side="sell",
            code=code,
            name=str(meta.get("name") or code),
            price=float(rec["price"]),
            qty=int(sell_qty),
            reason=trade_note or reason,
            pnl=rec.get("pnl"),
            pnl_pct=rec.get("pnl_pct"),
            before_qty=int(old_qty),
            after_qty=int(pos["qty"]),
            action_kind=str(action_kind or ""),
            exit_kind=str(exit_kind or ""),
            quantity_ratio=(
                float(sell_qty) / float(old_qty) if old_qty > 0 else None
            ),
            target_px=float(
                meta.get("stop")
                or meta.get("止损")
                or meta.get("卖出价")
                or meta.get("exit_px")
                or fill_px
            ),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 卖出微信推送跳过: {e}")
    if reason in (REASON_STOP, REASON_HALF):
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
    action_kind: str = "",
    stop_kind: str = "",
    first_hit_ts: str | None = None,
    exit_kind: str = "",
) -> dict[str, Any]:
    """止损/止盈视为已成交：10% 半仓只卖一半，其余全清。"""
    sell_qty = int(qty)
    half = is_half_stop_kind(stop_kind, action_kind)
    if half:
        sell_qty = lot_half_shares(sell_qty)
    reason = REASON_HALF if half else REASON_STOP
    return apply_exit_fill(
        code=code,
        meta=meta,
        fill_px=float(stop_px),
        qty=sell_qty,
        cost=cost,
        session=session,
        buy_time=buy_time,
        prev_close=prev_close,
        open_px=open_px,
        px_digits=px_digits,
        reason=reason,
        trade_note=f"{reason}(自动)",
        action_kind="half" if half else "full",
        first_hit_ts=first_hit_ts,
        exit_kind=str(exit_kind or ""),
    )


def force_eod_reserve_slot(
    rows: list[dict[str, Any]],
    *,
    session: str,
    now: Any | None = None,
) -> list[str]:
    """尾盘窗口：持仓超过隔夜上限时，强制卖出可卖仓中浮盈最差一只（纸面）。

    对齐回测 eod_reserve_slot：盘中可持 3，隔夜最多 MAX_OVERNIGHT_SLOTS。
    """
    if not is_reserve_slot_window(now):
        return []
    sold: list[str] = []
    while True:
        data = load_holdings()
        occupied = occupied_slot_codes(data)
        if len(occupied) <= int(MAX_OVERNIGHT_SLOTS):
            break
        cands: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
        for r in rows:
            code = _code_key(str(r.get("代码") or ""))
            if code not in occupied:
                continue
            pos = (data.get("positions") or {}).get(code) or {}
            qty = int(pos.get("qty") or 0)
            if qty <= 0:
                continue
            buy_time = pos.get("buy_time")
            sellable = _sellable_qty(pos, qty, buy_time, session, t0=False)
            if sellable <= 0:
                continue
            try:
                px = float(r.get("现价") or pos.get("cost") or 0)
                cost = float(pos.get("cost") or 0)
            except (TypeError, ValueError):
                continue
            if px <= 0 or cost <= 0:
                continue
            ret = simple_return(px, cost)
            if ret is None:
                continue
            cands.append((ret, code, r, pos))
        if not cands:
            break
        cands.sort(key=lambda x: x[0])
        _pnl, code, r, pos = cands[0]
        try:
            fill_px = float(r.get("现价") or 0)
        except (TypeError, ValueError):
            break
        if fill_px <= 0:
            break
        qty = int(pos.get("qty") or 0)
        sellable = _sellable_qty(pos, qty, pos.get("buy_time"), session, t0=False)
        meta = {
            "code": code,
            "name": str(r.get("名称") or pos.get("name") or code),
            "market": str(r.get("市场") or pos.get("market") or ""),
        }
        apply_exit_fill(
            code=code,
            meta=meta,
            fill_px=fill_px,
            qty=sellable,
            cost=float(pos.get("cost")) if pos.get("cost") is not None else None,
            session=session,
            buy_time=pos.get("buy_time"),
            prev_close=r.get("昨收"),
            open_px=float(r.get("开盘") or fill_px),
            px_digits=2,
            reason=REASON_EOD_RESERVE,
            trade_note=f"{REASON_EOD_RESERVE}(自动·隔夜预留)",
            exit_kind="eod_reserve",
        )
        sold.append(code)
        # 刷新行持仓展示，避免同轮再判
        for row in rows:
            if _code_key(str(row.get("代码") or "")) == code:
                row["持仓"] = 0
                row["可用"] = 0
                row["当日禁买"] = True
                row["持仓状态"] = STATUS_STOP_CLOSED
                break
    return sold


def persist_stop_noted(
    code: str,
    *,
    stop_px: float,
    session: str,
    px_digits: int = 2,
    reason: str = "",
    last_px: float | None = None,
    cost_px: float | None = None,
    prev_close: float | None = None,
    limit_up_pct: float = 0.10,
) -> bool:
    """T+1「止损已记」唯一落库口。

    只接受 hard_from_cost / t1_trail。已记价不得高于成本（拒绝中段/抬高卖价）。
    现价盈≥3%、涨停、已收回 → 拒绝。展示层不得再写账本。
    """
    data = load_holdings()
    pos = data.get("positions", {}).get(code)
    if not pos or int(pos.get("qty") or 0) <= 0:
        return False
    try:
        cost = float(cost_px if cost_px is not None else (pos.get("cost") or 0))
    except (TypeError, ValueError):
        cost = 0.0
    if not t1_stop_note_allowed(
        reason=reason,
        stop_px=stop_px,
        cost_px=cost,
        last_px=last_px,
        prev_close=prev_close,
        limit_up_pct=limit_up_pct,
    ):
        return False
    px = round(float(stop_px), max(2, int(px_digits)))
    prev = pos.get("stop_noted_px")
    try:
        if prev is not None and float(prev) > 0:
            px = min(px, float(prev))
    except (TypeError, ValueError):
        pass
    if not t1_stop_note_px_is_legal(stop_px=px, cost_px=cost):
        return False
    pos["stop_noted"] = True
    pos["stop_noted_px"] = px
    pos["stop_noted_session"] = str(session)
    save_holdings(data)
    return True


def clear_stop_noted(code: str) -> None:
    """现价已收回/涨停：作废 T+1 落库已记，避免次日仍隔夜武装。"""
    data = load_holdings()
    pos = data.get("positions", {}).get(code)
    if not pos:
        return
    if not (pos.get("stop_noted") or pos.get("stop_noted_px")):
        return
    pos["stop_noted"] = False
    pos["stop_noted_px"] = None
    pos["stop_noted_session"] = None
    save_holdings(data)


def resolve_stop_noted_hit(
    pos: dict[str, Any],
    *,
    open_px: float,
    low_px: float,
    last_px: float,
    sellable: int,
    t1_buy_day: bool,
    locked: bool = False,
    now: Any | None = None,
    dump_pct: float | None = None,
    cost_px: float | None = None,
    high_px: float | None = None,
    giveback_arm_pct: float | None = None,
    overnight_high_ok: bool = True,
) -> dict[str, Any]:
    """隔夜仓：昨日 T+1 已记 → 次日可卖后的离场。

    · 浮盈尚未 >3%：次日动态峰值回落 2.5% 全清
    · 浮盈 >3%：不强制峰值回落 2.5%，交给波动回落 / 档位
    · 一字跌停封死：locked=True 则等开板
    · overnight_high_ok=False（今日新买）不走隔夜峰值回落
    """
    out = {"hit": False, "fill_px": 0.0, "kind": ""}
    if t1_buy_day or (not overnight_high_ok) or int(sellable or 0) <= 0:
        return out
    if not bool(pos.get("stop_noted")):
        return out
    try:
        noted = float(pos.get("stop_noted_px") or 0)
    except (TypeError, ValueError):
        noted = 0.0
    if noted <= 0:
        return out
    if locked:
        return out
    o = float(open_px or 0)
    last = float(last_px or 0)
    lo = float(low_px or 0)
    if o <= 0:
        return out
    try:
        cost = float(
            cost_px if cost_px is not None else (pos.get("cost") or 0)
        )
    except (TypeError, ValueError):
        cost = 0.0
    try:
        hi = float(high_px or 0)
    except (TypeError, ValueError):
        hi = 0.0
    arm = (
        float(giveback_arm_pct)
        if giveback_arm_pct is not None
        else DEFAULT_GIVEBACK_ARM_PCT
    )
    if pnl_exceeds(max(o, hi, last, cost if cost > 0 else 0), cost, arm):
        return out
    hard = cost_hard_stop_px(cost)
    if hard > 0 and o <= hard + 1e-12:
        return {"hit": True, "fill_px": o, "kind": "hard_from_cost"}
    try:
        peak_pos = float(pos.get("peak_high") or 0)
    except (TypeError, ValueError):
        peak_pos = 0.0
    peaks = [x for x in (o, hi, last, peak_pos, cost) if x > 0]
    sess_peak = max(peaks) if peaks else 0.0
    k = float(dump_pct) if dump_pct is not None else DEFAULT_T1_PEAK_TRAIL_PCT
    trail_stop = t1_trail_stop_px(
        sess_peak,
        cost_px=cost,
        t1_trail_pct=k,
        hard_pct=DEFAULT_PULLBACK_PCT,
    )
    if trail_stop <= 0:
        return out
    if (lo > 0 and lo <= trail_stop + 1e-12) or (last > 0 and last <= trail_stop + 1e-12):
        fill = o if o <= trail_stop + 1e-12 else trail_stop
        kind = "hard_from_cost" if abs(trail_stop - hard) <= 1e-9 and hard > 0 else "t1_peak_trail"
        return {"hit": True, "fill_px": fill, "kind": kind}
    return out


def overnight_stop_should_fill(
    *,
    last: float,
    low: float,
    stop: float,
    sticky_touched: bool = False,
) -> bool:
    """现价打到当前卖价才平。全日最低不与抬高后的止损比较（避免早盘低点假触）。"""
    try:
        stop_px = float(stop or 0)
    except (TypeError, ValueError):
        return False
    if stop_px <= 0:
        return False
    try:
        last_px = float(last or 0)
    except (TypeError, ValueError):
        last_px = 0.0
    if last_px > 0 and last_px <= stop_px + 1e-12:
        return True
    if bool(sticky_touched) and last_px > 0 and last_px <= stop_px * 1.003 + 1e-12:
        return True
    return False


def t1_buy_day_should_void_stop_note(
    *,
    last_px: float,
    cost_px: float | None,
    prev_close: float | None,
    noted_px: float | None,
    limit_up_pct: float = 0.10,
    reason: str | None = None,
) -> bool:
    """买入日：现价盈≥3%、涨停、或已远离硬保护已记价 → 不得落库/展示「止损已记」。

    t1_trail 哨兵=成本：小幅浮盈不 void（否则无法隔夜武装峰值回落）。
    """
    try:
        last = float(last_px or 0)
    except (TypeError, ValueError):
        last = 0.0
    try:
        cost = float(cost_px or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if last > 0 and cost > 0 and pnl_exceeds(last, cost, DEFAULT_GIVEBACK_ARM_PCT):
        return True
    return bool(
        stop_note_invalidated_by_recovery(
            last_px=last,
            noted_px=noted_px,
            prev_close=prev_close,
            limit_up_pct=float(limit_up_pct or 0.10),
            cost_px=cost if cost > 0 else None,
            reason=reason,
        )
    )


def t1_stop_note_px_is_legal(*, stop_px: float, cost_px: float | None) -> bool:
    """已记价只能 ≤ 成本：硬保护在成本下，T1 哨兵=成本。中段/抬高卖价非法。"""
    try:
        px = float(stop_px or 0)
        cost = float(cost_px or 0)
    except (TypeError, ValueError):
        return False
    if px <= 0 or cost <= 0:
        return False
    return px <= cost + 1e-6


def t1_stop_note_allowed(
    *,
    reason: str,
    stop_px: float,
    cost_px: float | None,
    last_px: float | None = None,
    prev_close: float | None = None,
    limit_up_pct: float = 0.10,
) -> bool:
    """唯一门禁：原因合法 + 已记价≤成本 + 现价未涨停/未盈≥3%/未收回。"""
    if str(reason or "") not in ("hard_from_cost", "t1_trail"):
        return False
    if not t1_stop_note_px_is_legal(stop_px=stop_px, cost_px=cost_px):
        return False
    try:
        last = float(last_px or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last > 0 and t1_buy_day_should_void_stop_note(
        last_px=last,
        cost_px=cost_px,
        prev_close=prev_close,
        noted_px=stop_px,
        limit_up_pct=limit_up_pct,
        reason=str(reason or ""),
    ):
        return False
    return True


def purge_illegal_t1_stop_notes(data: dict[str, Any]) -> int:
    """清掉已记价高于成本的账（中段卖价误写入）。返回清理条数。"""
    n = 0
    positions = data.get("positions") or {}
    if not isinstance(positions, dict):
        return 0
    for pos in positions.values():
        if not isinstance(pos, dict):
            continue
        if not (pos.get("stop_noted") or pos.get("stop_noted_px")):
            continue
        if t1_stop_note_px_is_legal(
            stop_px=float(pos.get("stop_noted_px") or 0),
            cost_px=pos.get("cost"),
        ):
            continue
        pos["stop_noted"] = False
        pos["stop_noted_px"] = None
        pos["stop_noted_session"] = None
        n += 1
    return n


def heal_missing_overnight_t1_trail_notes(
    data: dict[str, Any],
    *,
    session: str,
) -> int:
    """隔夜仓缺 stop_noted：补 t1_trail 哨兵（=成本），启用峰值回落 2.5%。

    仅当：有仓、非买入当日、昨收相对成本未达 3%、尚未合法已记。
    修复「小幅浮盈误 void 哨兵 → 次日卖出侧锁死硬保护」的历史账本。
    """
    from strategy.open_break import floor_to_tick
    from strategy.pullback_wave_stop import (
        DEFAULT_GIVEBACK_ARM_PCT,
        TICK_SIZE,
        pnl_exceeds,
    )

    sess = str(session or "")[:10]
    if not sess:
        return 0
    positions = data.get("positions") or {}
    if not isinstance(positions, dict):
        return 0
    n = 0
    for code, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        if bool(pos.get("t0")):
            continue
        buy_time = pos.get("buy_time")
        if not buy_time:
            continue
        if is_t1_buy_day(buy_time, sess):
            continue
        if bool(pos.get("stop_noted")) and t1_stop_note_px_is_legal(
            stop_px=float(pos.get("stop_noted_px") or 0),
            cost_px=pos.get("cost"),
        ):
            continue
        try:
            cost = float(pos.get("cost") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        if cost <= 0:
            continue
        # 昨收已 ≥3%：本应按中段，不补 t1 哨兵
        try:
            prev_c = float(pos.get("prev_close_at_note") or 0)
        except (TypeError, ValueError):
            prev_c = 0.0
        # 无昨收快照时用 overnight 不依赖；用 peak 粗判是否早已过 3%
        try:
            peak = float(pos.get("peak_high") or 0)
        except (TypeError, ValueError):
            peak = 0.0
        if prev_c > 0 and pnl_exceeds(prev_c, cost, DEFAULT_GIVEBACK_ARM_PCT):
            continue
        # peak 相对成本已 >3%：交给中段，不强制 t1
        if peak > 0 and pnl_exceeds(peak, cost, DEFAULT_GIVEBACK_ARM_PCT):
            continue
        arm_px = floor_to_tick(cost, TICK_SIZE)
        if arm_px <= 0:
            arm_px = round(cost, 2)
        pos["stop_noted"] = True
        pos["stop_noted_px"] = float(arm_px)
        pos["stop_noted_session"] = sess
        n += 1
    return n


def _paper_exit_decision_legacy(
    *,
    qty: int,
    sellable: int,
    t1_today: bool,
    hold_locked: bool = False,
    stop_locked: bool = False,
    last: float = 0.0,
    open_px: float = 0.0,
    day_high: float = 0.0,
    prev_close: float | None = None,
    cost: float | None = None,
    peak_high: float | None = None,
    working_stop: float = 0.0,
    path_hit: bool = False,
    path_fill_px: float = 0.0,
    path_action_kind: str = "",
    path_stop_kind: str = "",
    signal_ok: bool = True,
    overnight_high_ok: bool | None = None,
    buy_time: Any = None,
    session: str = "",
) -> dict[str, Any]:
    """纸面止损唯一口径（legacy 真源实现；勿直接改成交语义）。

    开盘保护 / 1m 路径 / 5s 现价破卖价。展示 hit_show 与结算 hit 同源。
    """
    empty = {
        "hit": False,
        "hit_show": False,
        "fill_px": 0.0,
        "kind": "",
        "action_kind": "",
        "stop_kind": "",
        "reason": "",
        "open_bell": False,
    }
    try:
        qty_i = int(qty or 0)
        sell_i = int(sellable or 0)
    except (TypeError, ValueError):
        return empty
    if qty_i <= 0:
        return empty

    try:
        last_px = float(last or 0)
    except (TypeError, ValueError):
        last_px = 0.0
    try:
        open_f = float(open_px or 0)
    except (TypeError, ValueError):
        open_f = 0.0
    try:
        stop_f = float(working_stop or 0)
    except (TypeError, ValueError):
        stop_f = 0.0
    try:
        cost_f = float(cost or 0)
    except (TypeError, ValueError):
        cost_f = 0.0
    try:
        path_px = float(path_fill_px or 0)
    except (TypeError, ValueError):
        path_px = 0.0

    protect = 0.0
    if cost_f > 0:
        # 开盘保护只用隔夜峰值。调用方应传 freeze_overnight_peak_for_session 的结果。
        # 兜底：高开且 peak≥今开 → 峰值含今日（黑猫），回退 max(成本, 昨收)；
        # 低开仍保留昨高（真缺口保护，如中天）。
        peak_for_open = None
        try:
            raw_peak = float(peak_high) if peak_high is not None else 0.0
        except (TypeError, ValueError):
            raw_peak = 0.0
        prev_f = 0.0
        try:
            prev_f = float(prev_close) if prev_close is not None else 0.0
        except (TypeError, ValueError):
            prev_f = 0.0
        if raw_peak > 0:
            gap_up = bool(open_f > 0 and prev_f > 0 and open_f > prev_f + 1e-12)
            if gap_up and raw_peak + 1e-12 >= open_f:
                peak_for_open = max(x for x in (cost_f, prev_f) if x > 0) or None
            else:
                peak_for_open = raw_peak
        protect = float(
            overnight_open_protect_px(
                cost_f,
                prev_close,
                peak_high=peak_for_open,
                overnight_high_ok=overnight_high_ok,
                buy_time=buy_time,
                session=session,
                qty=qty_i,
            )
            or 0
        )
    open_hit = bool(open_f > 0 and protect > 0 and open_f <= protect + 1e-12)
    last_hit = bool(stop_f > 0 and last_px > 0 and last_px <= stop_f + 1e-12)
    path_ok = bool(path_hit and path_px > 0)
    open_bell = bool(open_hit)
    if t1_today and cost_f > 0:
        hard = float(cost_hard_stop_px(cost_f) or 0)
        open_hit = False
        open_bell = False
        last_hit = bool(hard > 0 and last_px > 0 and last_px <= hard + 1e-12)
        path_ok = bool(
            path_hit
            and path_px > 0
            and hard > 0
            and path_px <= hard + 1e-6
            and last_px > 0
            and last_px <= hard * 1.003 + 1e-12
        )
    # 今开已破工作卖价，且当日最高从未印到该价 → 按开盘成交，禁止记从未成交的卖点
    if (not t1_today) and (not open_hit) and last_hit:
        try:
            day_hi = float(day_high or 0)
        except (TypeError, ValueError):
            day_hi = 0.0
        if session_high_never_printed_stop(
            open_px=open_f,
            last_px=last_px,
            working_stop=stop_f,
            day_high=day_hi,
        ):
            open_hit = True
            open_bell = True
    hit_show = bool(open_hit or last_hit or path_ok)
    if not hit_show:
        return empty

    out = dict(empty)
    out["hit_show"] = True
    out["open_bell"] = bool(open_bell)
    if t1_today:
        out["reason"] = "t1"
        return out
    if hold_locked:
        out["reason"] = "hold_lock"
        return out
    if stop_locked:
        out["reason"] = "limit_down"
        return out
    if sell_i <= 0:
        out["reason"] = "not_sellable"
        return out
    if not signal_ok:
        out["reason"] = "wait_auction"
        return out

    if open_hit:
        out.update(
            {
                "hit": True,
                "fill_px": open_f,
                "kind": "open_protect",
                "action_kind": "full",
                "reason": "open_protect",
            }
        )
        return out
    if path_ok:
        half = is_half_stop_kind(path_stop_kind, path_action_kind)
        out.update(
            {
                "hit": True,
                "fill_px": path_px,
                "kind": "path",
                "action_kind": "half" if half else (path_action_kind or "full"),
                "stop_kind": str(path_stop_kind or ""),
                "reason": "path",
            }
        )
        return out
    out.update(
        {
            "hit": True,
            "fill_px": stop_f,
            "kind": "last",
            "action_kind": "full",
            "reason": "last",
        }
    )
    return out


def paper_exit_decision(
    *,
    qty: int,
    sellable: int,
    t1_today: bool,
    hold_locked: bool = False,
    stop_locked: bool = False,
    last: float = 0.0,
    open_px: float = 0.0,
    day_high: float = 0.0,
    prev_close: float | None = None,
    cost: float | None = None,
    peak_high: float | None = None,
    working_stop: float = 0.0,
    path_hit: bool = False,
    path_fill_px: float = 0.0,
    path_action_kind: str = "",
    path_stop_kind: str = "",
    signal_ok: bool = True,
    overnight_high_ok: bool | None = None,
    buy_time: Any = None,
    session: str = "",
    symbol: str = "",
) -> dict[str, Any]:
    """纸面止损口径：默认走 legacy；可选 Shadow / 统一引擎（默认关）。

    USE_UNIFIED_EXIT_ENGINE=False 时成交语义与历史完全一致。
    SHADOW_UNIFIED_EXIT_ENGINE=True 时并行跑 ExitDecisionEngine，只记比较、不成交。
    """
    kw = dict(
        qty=qty,
        sellable=sellable,
        t1_today=t1_today,
        hold_locked=hold_locked,
        stop_locked=stop_locked,
        last=last,
        open_px=open_px,
        day_high=day_high,
        prev_close=prev_close,
        cost=cost,
        peak_high=peak_high,
        working_stop=working_stop,
        path_hit=path_hit,
        path_fill_px=path_fill_px,
        path_action_kind=path_action_kind,
        path_stop_kind=path_stop_kind,
        signal_ok=signal_ok,
        overnight_high_ok=overnight_high_ok,
        buy_time=buy_time,
        session=session,
        symbol=symbol,
    )
    # Snapshot Unified Context *before* Legacy, from the same kwargs.
    # Flags 全关时不建 context，避免盯盘热路径多余分配。
    ctx = None
    shadow_mod = None
    try:
        from strategy.exit_rules import shadow as shadow_mod

        if bool(shadow_mod.USE_UNIFIED_EXIT_ENGINE) or bool(
            shadow_mod.SHADOW_UNIFIED_EXIT_ENGINE
        ):
            ctx = shadow_mod.build_exit_context_from_paper_kwargs(**kw)
    except Exception:  # noqa: BLE001
        shadow_mod = None
        ctx = None
    legacy = _paper_exit_decision_legacy(
        qty=qty,
        sellable=sellable,
        t1_today=t1_today,
        hold_locked=hold_locked,
        stop_locked=stop_locked,
        last=last,
        open_px=open_px,
        day_high=day_high,
        prev_close=prev_close,
        cost=cost,
        peak_high=peak_high,
        working_stop=working_stop,
        path_hit=path_hit,
        path_fill_px=path_fill_px,
        path_action_kind=path_action_kind,
        path_stop_kind=path_stop_kind,
        signal_ok=signal_ok,
        overnight_high_ok=overnight_high_ok,
        buy_time=buy_time,
        session=session,
    )
    if shadow_mod is None:
        return legacy
    try:
        return shadow_mod.maybe_shadow_and_select(legacy, paper_kwargs=kw, ctx=ctx)
    except Exception:  # noqa: BLE001
        return legacy


def correct_realized_open_protect_fill(
    *,
    code: str,
    session: str,
    open_px: float,
    prev_close: float | None,
    cost: float | None,
    peak_high: float | None,
    px_digits: int,
    day_high: float = 0.0,
) -> dict[str, Any] | None:
    """已记账卖出若本应按开盘保护成交、却写成了抬高后的止损，纠回开盘价。

    不改 qty。现金按价差轧差。远东今开=24.10 已是开盘保护，不会动。
    含：工作卖价从未被当日最高印到（竞价脏峰抬止损）→ 按开盘纠价。
    """
    data = load_holdings()
    _purge_stale_realized(data, session)
    rec = (data.get("realized_today") or {}).get(code)
    if not isinstance(rec, dict):
        return None
    if str(rec.get("session") or "") != str(session)[:10]:
        return None
    if rec.get("full_exit") is not True:
        return None
    try:
        old_px = float(rec.get("price") or 0)
        qty = int(rec.get("qty") or 0)
        cost_f = float(cost if cost is not None else rec.get("cost") or 0)
        open_f = float(open_px or 0)
    except (TypeError, ValueError):
        return None
    if old_px <= 0 or qty <= 0 or cost_f <= 0 or open_f <= 0:
        return None
    dec = paper_exit_decision(
        qty=qty,
        sellable=qty,
        t1_today=False,
        last=old_px,
        open_px=open_f,
        day_high=day_high,
        prev_close=prev_close,
        cost=cost_f,
        peak_high=peak_high,
        working_stop=old_px,
        path_hit=False,
        signal_ok=True,
        overnight_high_ok=True,
    )
    if str(dec.get("kind") or "") != "open_protect":
        return None
    try:
        new_px = round(float(dec.get("fill_px") or 0), int(px_digits or 2))
    except (TypeError, ValueError):
        return None
    if new_px <= 0 or abs(new_px - old_px) <= 5e-3:
        return rec
    pnl, pnl_pct = mark_unrealized(new_px, cost_f, qty)
    bought_today = False
    day_pnl, day_pnl_pct, day_base = session_day_pnl(
        mark=new_px,
        qty=qty,
        cost=cost_f,
        prev_close=prev_close,
        bought_today=bought_today,
        fallback=open_f,
    )
    rec["price"] = new_px
    rec["pnl"] = None if pnl is None else round(float(pnl), 2)
    rec["pnl_pct"] = None if pnl_pct is None else round(float(pnl_pct), 2)
    rec["day_base"] = None if day_base is None else round(float(day_base), 2)
    rec["day_pnl"] = None if day_pnl is None else round(float(day_pnl), 2)
    rec["day_pnl_pct"] = None if day_pnl_pct is None else round(float(day_pnl_pct), 2)
    rec["note_fix"] = "开盘保护纠价"
    rec["exit_kind"] = "open_protect"
    rec["action_kind"] = "full"
    bell = session_open_bell_ts(str(session)[:10])
    rec["time"] = bell
    rec["first_hit_ts"] = bell
    rec["triggered_at"] = bell
    rec["filled_at"] = bell
    rec["decision_at"] = bell
    pos = (data.get("positions") or {}).get(code)
    if isinstance(pos, dict):
        pos["note"] = f"止损成交@{new_px} ({session})"
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash + (new_px - old_px) * qty, 2)
    traces = data.get("closed_today")
    if isinstance(traces, dict) and isinstance(traces.get(code), dict):
        traces[code]["price"] = new_px
        traces[code]["day_pnl"] = rec.get("day_pnl")
        traces[code]["day_pnl_pct"] = rec.get("day_pnl_pct")
    mem = data.setdefault("factor_memory", {})
    mem_rec = mem.setdefault(code, {})
    if isinstance(mem_rec, dict):
        mem_rec["last_sell_factor_px"] = new_px
        mem_rec["last_sell_factor_date"] = str(session)[:10]
    sticky = data.get("alert_sticky")
    if isinstance(sticky, dict) and isinstance(sticky.get(code), dict):
        sticky[code]["touch_stop"] = new_px
        sticky[code]["stop_hit_ts"] = bell
    save_holdings(data)
    meta_name = str((pos or {}).get("name") or rec.get("name") or code)
    append_trade(
        {
            "time": _now(),
            "side": "sell",
            "code": code,
            "name": meta_name,
            "price": new_px,
            "qty": qty,
            "after_qty": 0,
            "cost": round(cost_f, 4),
            "pnl": rec.get("pnl"),
            "note": f"开盘保护纠价 {old_px}->{new_px}（原按抬高止损记账）",
        }
    )
    return rec


def correct_realized_false_open_to_path_ladder(
    *,
    code: str,
    session: str,
    cost: float,
    prev_close: float,
    open_px: float,
    half_px: float,
    half_ts: str,
    half_qty: int,
    clear_px: float,
    clear_ts: str,
    clear_qty: int,
    peak_high: float,
    old_fill_px: float,
    old_total_qty: int,
    px_digits: int = 2,
    name: str = "",
    market: str = "深证",
) -> dict[str, Any]:
    """假开盘保护全清 → 纠成因子26路径：10% 半仓 + 峰值回落 2% 全清。

    现金按新旧成交额轧差。用于黑猫 002068（2026-09-17）一类事故。
    """
    sess = str(session or "")[:10]
    code = _code_key(code)
    data = load_holdings()
    _purge_stale_realized(data, sess)
    pos = (data.get("positions") or {}).get(code)
    if not isinstance(pos, dict):
        pos = _empty_position({"name": name or code, "market": market})
        data.setdefault("positions", {})[code] = pos

    half_px_r = round(float(half_px), int(px_digits))
    clear_px_r = round(float(clear_px), int(px_digits))
    half_q = int(half_qty)
    clear_q = int(clear_qty)
    cost_f = float(cost)
    prev_f = float(prev_close)
    open_f = float(open_px)
    old_px = float(old_fill_px)
    old_q = int(old_total_qty)

    old_proceeds = old_px * old_q
    new_proceeds = half_px_r * half_q + clear_px_r * clear_q
    # account_cash 可为负；_account_cash/_as_money 会把 ≤0 当成无现金
    try:
        raw_cash = float(data.get("account_cash"))
        data["account_cash"] = round(raw_cash + (new_proceeds - old_proceeds), 2)
    except (TypeError, ValueError):
        pass

    half_pnl, half_pnl_pct = mark_unrealized(half_px_r, cost_f, half_q)
    clear_pnl, clear_pnl_pct = mark_unrealized(clear_px_r, cost_f, clear_q)
    half_day, half_day_pct, half_base = session_day_pnl(
        mark=half_px_r,
        qty=half_q,
        cost=cost_f,
        prev_close=prev_f,
        bought_today=False,
        fallback=open_f,
    )
    clear_day, clear_day_pct, clear_base = session_day_pnl(
        mark=clear_px_r,
        qty=clear_q,
        cost=cost_f,
        prev_close=prev_f,
        bought_today=False,
        fallback=open_f,
    )
    tot_pnl = float(half_pnl or 0) + float(clear_pnl or 0)
    tot_day = float(half_day or 0) + float(clear_day or 0)
    tot_base = float(half_base or 0) + float(clear_base or 0)
    tot_qty = half_q + clear_q
    avg_px = (new_proceeds / tot_qty) if tot_qty > 0 else clear_px_r
    pnl_pct = (avg_px / cost_f - 1.0) * 100.0 if cost_f > 0 else None
    day_pct = (tot_day / tot_base * 100.0) if tot_base > 0 else None

    disp_name = str(name or pos.get("name") or code)
    disp_mkt = str(market or pos.get("market") or "深证")
    rec = {
        "session": sess,
        "name": disp_name,
        "market": disp_mkt,
        "qty": int(clear_q),
        "price": clear_px_r,
        "cost": round(cost_f, 4),
        "pnl": round(float(clear_pnl or 0), 2),
        "pnl_pct": None if clear_pnl_pct is None else round(float(clear_pnl_pct), 2),
        "day_base": None if clear_base is None else round(float(clear_base), 2),
        "day_pnl": None if clear_day is None else round(float(clear_day), 2),
        "day_pnl_pct": None if clear_day_pct is None else round(float(clear_day_pct), 2),
        "reason": REASON_STOP,
        "time": str(clear_ts),
        "first_hit_ts": str(clear_ts),
        "action_kind": "full",
        "after_qty": 0,
        "full_exit": True,
        "note_fix": "假开盘保护→路径半仓+峰值回落纠价",
        "path_half_px": half_px_r,
        "path_half_ts": str(half_ts),
        "path_half_qty": half_q,
        "path_clear_px": clear_px_r,
        "path_clear_ts": str(clear_ts),
        "path_clear_qty": clear_q,
        "path_total_pnl": round(tot_pnl, 2),
        "path_total_day_pnl": round(tot_day, 2),
        "path_avg_px": round(avg_px, px_digits),
        "path_pnl_pct": None if pnl_pct is None else round(float(pnl_pct), 2),
        "path_day_pnl_pct": None if day_pct is None else round(float(day_pct), 2),
        "peak_high": round(float(peak_high), 4),
    }
    # 今日平仓栏展示用合计口径（两笔）
    rec["qty"] = tot_qty
    rec["price"] = round(avg_px, px_digits)
    rec["pnl"] = round(tot_pnl, 2)
    rec["pnl_pct"] = None if pnl_pct is None else round(float(pnl_pct), 2)
    rec["day_base"] = round(tot_base, 2)
    rec["day_pnl"] = round(tot_day, 2)
    rec["day_pnl_pct"] = None if day_pct is None else round(float(day_pct), 2)

    data.setdefault("realized_today", {})[code] = rec
    pos["qty"] = 0
    pos["cost"] = None
    pos["buy_time"] = None
    pos["available"] = None
    pos["today_cost"] = None
    pos["name"] = disp_name
    pos["market"] = disp_mkt
    pos["peak_high"] = round(float(peak_high), 4)
    pos["tp_stage"] = 0
    pos["last_tp_ts"] = str(half_ts)
    pos["note"] = (
        f"半仓止盈@{half_px_r}+峰值回落@{clear_px_r} ({sess}·纠假开盘保护)"
    )
    for bad_k in ("high_after_stop", "low_after_stop", "rebound_pct", "miss_pnl"):
        rec.pop(bad_k, None)

    traces = data.setdefault("closed_today", {})
    if isinstance(traces, dict):
        traces[code] = {
            "session": sess,
            "name": disp_name,
            "market": disp_mkt,
            "qty": tot_qty,
            "price": rec["price"],
            "cost": round(cost_f, 4),
            "day_pnl": rec["day_pnl"],
            "day_pnl_pct": rec["day_pnl_pct"],
            "reason": REASON_STOP,
            "time": str(clear_ts),
            "已实现": True,
            "三槽平仓": True,
            "note_fix": rec["note_fix"],
        }

    mem = data.setdefault("factor_memory", {})
    mem_rec = mem.setdefault(code, {})
    if isinstance(mem_rec, dict):
        mem_rec["last_sell_factor_px"] = clear_px_r
        mem_rec["last_sell_factor_date"] = sess
        mem_rec["last_half_px"] = half_px_r

    save_holdings(data)
    append_trade(
        {
            "time": str(half_ts),
            "side": "sell",
            "code": code,
            "name": disp_name,
            "price": half_px_r,
            "qty": half_q,
            "after_qty": clear_q,
            "cost": round(cost_f, 4),
            "pnl": None if half_pnl is None else round(float(half_pnl), 2),
            "note": f"{REASON_HALF}(纠假开盘保护·路径)",
        }
    )
    append_trade(
        {
            "time": str(clear_ts),
            "side": "sell",
            "code": code,
            "name": disp_name,
            "price": clear_px_r,
            "qty": clear_q,
            "after_qty": 0,
            "cost": round(cost_f, 4),
            "pnl": None if clear_pnl is None else round(float(clear_pnl), 2),
            "note": f"{REASON_STOP}(纠假开盘保护·峰值回落)",
        }
    )
    append_trade(
        {
            "time": _now(),
            "side": "sell",
            "code": code,
            "name": disp_name,
            "price": round(avg_px, px_digits),
            "qty": tot_qty,
            "after_qty": 0,
            "cost": round(cost_f, 4),
            "pnl": round(tot_pnl, 2),
            "note": (
                f"纠假开盘保护 {old_px}×{old_q}→半仓{half_px_r}+回落{clear_px_r}"
                f"（现金轧差{new_proceeds - old_proceeds:+.2f}）"
            ),
        }
    )
    return rec


def _reconcile_realized_open_protects(
    rows: list[dict[str, Any]],
    *,
    session: str,
) -> int:
    """已平仓票按开盘保护对账；错价当场改账本并回写当前行。"""
    if not session:
        return 0
    data = load_holdings()
    positions = data.get("positions") or {}
    realized_map = data.get("realized_today") or {}
    by_code: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = _code_key(str(r.get("代码") or ""))
        if code:
            by_code[code] = r
    n = 0
    for code, rec in list(realized_map.items()):
        if not isinstance(rec, dict):
            continue
        ck = _code_key(code)
        row = by_code.get(ck)
        if not row or row.get("error"):
            continue
        pos = positions.get(ck) if isinstance(positions.get(ck), dict) else {}
        try:
            open_px = float(row.get("开盘") or 0)
        except (TypeError, ValueError):
            continue
        cost = rec.get("cost")
        if cost is None:
            cost = row.get("成本")
        old_px = rec.get("price")
        try:
            cost_f = float(cost) if cost is not None else 0.0
        except (TypeError, ValueError):
            cost_f = 0.0
        try:
            day_hi = float(row.get("最高") or row.get("今日最高") or 0)
        except (TypeError, ValueError):
            day_hi = 0.0
        peak_for_fix = freeze_overnight_peak_for_session(
            pos if isinstance(pos, dict) else {},
            session=session,
            cost=cost_f if cost_f > 0 else None,
            prev_close=row.get("昨收"),
            open_px=open_px,
            code=ck,
            persist=False,
        )
        fixed = correct_realized_open_protect_fill(
            code=ck,
            session=session,
            open_px=open_px,
            prev_close=row.get("昨收"),
            cost=float(cost) if cost is not None else None,
            peak_high=peak_for_fix if peak_for_fix > 0 else (pos or {}).get("peak_high"),
            px_digits=int(row.get("价位小数") or 2),
            day_high=day_hi,
        )
        if not isinstance(fixed, dict):
            continue
        try:
            new_px = float(fixed.get("price") or 0)
            old_f = float(old_px or 0)
        except (TypeError, ValueError):
            continue
        if new_px <= 0:
            continue
        if abs(new_px - old_f) > 5e-3:
            n += 1
        row["成交价"] = new_px
        if fixed.get("day_pnl") is not None:
            row["当日盈亏"] = fixed.get("day_pnl")
        if fixed.get("day_pnl_pct") is not None:
            row["当日盈亏%"] = fixed.get("day_pnl_pct")
        if fixed.get("pnl") is not None:
            row["浮盈"] = fixed.get("pnl")
        if fixed.get("pnl_pct") is not None:
            row["浮盈%"] = fixed.get("pnl_pct")
        _freeze_closed_exit_levels(row)
    n += _heal_open_protect_hit_times(rows, session=session)
    return n


def _heal_open_protect_hit_times(
    rows: list[dict[str, Any]],
    *,
    session: str,
) -> int:
    """仅对 exit_kind=open_protect / open_bell 纠成 09:30；禁止 fill≈open 事后改写 PATH。"""
    if not session:
        return 0
    bell = session_open_bell_ts(session)
    data = load_holdings()
    realized_map = data.get("realized_today") or {}
    sticky = data.get("alert_sticky") if isinstance(data.get("alert_sticky"), dict) else {}
    traces = data.get("closed_today") if isinstance(data.get("closed_today"), dict) else {}
    by_code: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = _code_key(str(r.get("代码") or ""))
        if code:
            by_code[code] = r
    n = 0
    changed = False
    for code, rec in list(realized_map.items()):
        if not isinstance(rec, dict):
            continue
        if str(rec.get("session") or "")[:10] != str(session)[:10]:
            continue
        ck = _code_key(code)
        row = by_code.get(ck) or {}
        exit_kind = str(rec.get("exit_kind") or row.get("exit_kind") or "")
        open_bell = bool(row.get("_open_bell")) or exit_kind == "open_protect"
        if not open_bell:
            # 历史已写入的 PATH/其它原因：immutable，不得因 fill≈open 改时间
            continue
        new_ts = _open_protect_hit_ts(
            session=session,
            fill_px=rec.get("price"),
            open_px=_as_money(row.get("开盘")),
            existing=rec.get("first_hit_ts") or rec.get("time"),
            open_bell=True,
            exit_kind="open_protect",
        )
        if not new_ts or new_ts != bell:
            continue
        if str(rec.get("time") or "") != bell or str(rec.get("first_hit_ts") or "") != bell:
            # 竞价观察戳 / 缺 09:30 的 09:31/09:32 可纠；09:32 之后的 PATH 不改
            existing_hms = _signal_hms(rec.get("first_hit_ts") or rec.get("time")) or ""
            if existing_hms[:8] > "09:32:59":
                continue
            rec["time"] = bell
            rec["first_hit_ts"] = bell
            rec["triggered_at"] = bell
            rec["filled_at"] = bell
            rec["decision_at"] = bell
            rec["exit_kind"] = "open_protect"
            changed = True
            n += 1
        st = sticky.get(ck) if isinstance(sticky.get(ck), dict) else None
        if st is not None and str(st.get("stop_hit_ts") or "") != bell:
            st["stop_hit_ts"] = bell
            changed = True
        tr = traces.get(ck) if isinstance(traces.get(ck), dict) else None
        if tr is not None and str(tr.get("time") or "") != bell:
            tr["time"] = bell
            changed = True
        if row:
            row["_open_bell"] = True
            row["信号时刻"] = bell
            row["信号时间"] = "09:30:00"
            row["卖信号时间"] = "09:30:00"
    if changed:
        save_holdings(data)
    return n


def settle_due_paper_stops(
    rows: list[dict[str, Any]],
    *,
    session: str,
    signal_ok: bool,
) -> int:
    """扫全部实仓：决策要平就平。不依赖单票分支有没有走到 apply_stop_fill。"""
    n = 0
    if session:
        n += _reconcile_realized_open_protects(rows, session=session)
    if not signal_ok or not session:
        return n
    data = load_holdings()
    positions = data.get("positions") or {}
    by_code: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = _code_key(str(r.get("代码") or ""))
        if code:
            by_code[code] = r
    due: list[tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any], int]] = []
    for code, pos in list(positions.items()):
        if not isinstance(pos, dict):
            continue
        qty = int(pos.get("qty") or 0)
        if qty <= 0:
            continue
        row = by_code.get(_code_key(code))
        if not row or row.get("error"):
            continue
        t0 = False
        t1_today = bool(pos.get("buy_time") and is_t1_buy_day(pos.get("buy_time"), session))
        sellable = _sellable_qty(pos, qty, pos.get("buy_time"), session, t0=t0)
        try:
            last = float(row.get("现价") or 0)
            open_px = float(row.get("开盘") or 0)
            stop = float(row.get("止损") or 0)
        except (TypeError, ValueError):
            continue
        try:
            path_px = float(row.get("_path_fill_px") or 0)
        except (TypeError, ValueError):
            path_px = 0.0
        path_hit = bool(row.get("_path_hit")) or (
            str(row.get("已触止损") or "") == "是" and path_px > 0
        )
        try:
            cost_px = float(
                pos.get("cost") if pos.get("cost") is not None else (row.get("成本") or 0)
            )
        except (TypeError, ValueError):
            cost_px = 0.0
        peak_for_exit = freeze_overnight_peak_for_session(
            pos,
            session=session,
            cost=cost_px if cost_px > 0 else None,
            prev_close=row.get("昨收"),
            open_px=open_px,
            qty=qty,
            code=code,
            persist=True,
        )
        try:
            day_hi = float(row.get("最高") or row.get("今日最高") or 0)
        except (TypeError, ValueError):
            day_hi = 0.0
        dec = paper_exit_decision(
            qty=qty,
            sellable=sellable,
            t1_today=t1_today,
            hold_locked=bool(pos.get("hold_lock")),
            last=last,
            open_px=open_px,
            day_high=day_hi,
            prev_close=row.get("昨收"),
            cost=pos.get("cost") if pos.get("cost") is not None else row.get("成本"),
            peak_high=peak_for_exit if peak_for_exit > 0 else pos.get("peak_high"),
            working_stop=stop,
            path_hit=path_hit,
            path_fill_px=path_px,
            path_action_kind=str(row.get("_path_action_kind") or ""),
            path_stop_kind=str(row.get("_path_stop_kind") or ""),
            signal_ok=True,
            buy_time=pos.get("buy_time"),
            session=session,
        )
        if not dec.get("hit") or float(dec.get("fill_px") or 0) <= 0:
            continue
        ts_key = _row_trigger_ts(row, side="sell")
        due.append((ts_key, _code_key(code), pos, row, dec, sellable))
    due.sort(key=lambda x: (x[0], x[1]))
    for ts_key, code, pos, row, dec, sellable in due:
        try:
            open_px = float(row.get("开盘") or 0)
        except (TypeError, ValueError):
            open_px = 0.0
        first_ts = ts_key if not str(ts_key).startswith("9999") else None
        if str(dec.get("kind") or "") == "open_protect" or dec.get("open_bell"):
            first_ts = session_open_bell_ts(session)
        apply_stop_fill(
            code=code,
            meta={
                "code": code,
                "name": str(row.get("名称") or pos.get("name") or code),
                "market": str(row.get("市场") or pos.get("market") or ""),
            },
            stop_px=float(dec["fill_px"]),
            qty=sellable,
            cost=float(pos["cost"]) if pos.get("cost") is not None else None,
            session=session,
            buy_time=pos.get("buy_time"),
            prev_close=row.get("昨收"),
            open_px=open_px,
            px_digits=int(row.get("价位小数") or 2),
            action_kind=str(dec.get("action_kind") or "full"),
            stop_kind=str(dec.get("stop_kind") or ""),
            first_hit_ts=first_ts or _bar_ts_str(row.get("_path_ts")),
            exit_kind=str(dec.get("kind") or ""),
        )
        if str(dec.get("kind") or "") == "open_protect" or dec.get("open_bell"):
            row["_open_bell"] = True
            row["信号时刻"] = session_open_bell_ts(session)
            row["信号时间"] = "09:30:00"
            row["卖信号时间"] = "09:30:00"
        row["持仓"] = 0
        row["可用"] = 0
        row["当日禁买"] = True
        n += 1
    return n


def append_trade(record: dict[str, Any]) -> None:
    with TRADES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        from trade_ledger import record_trade_ledger

        record_trade_ledger(record)
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 交割账本写入失败（继续）: {e}")


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

    filled = fill_preopen_ohlc(
        open_px=_f(1),
        high_px=_f(4),
        low_px=_f(5),
        last_px=_f(3),
        bid=_f(6),
        ask=_f(7),
        prev_close=_f(2),
    )
    if filled is None:
        return None
    open_px, high_px, low_px, last_px = filled
    prev_close = _f(2)
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
    session / 涨跌幅一律相对 ``trading_session_date``，禁止沿用上一交易日 day change。
    """
    today = str(trading_session_date())
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

    spot_sess = promote_quote_session(spot.get("session") if spot else None)
    spot_ok = spot is not None and spot_sess == today

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
        day_chg = sanitize_day_change_for_session(
            quote_session=today,
            calendar_session=today,
            mark=last_px,
            previous_close=prev_close,
        )
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
        prev_close = float(spot["prev_close"])
        last_px = float(spot["last"])
        day_chg = sanitize_day_change_for_session(
            quote_session=today,
            calendar_session=today,
            mark=last_px,
            previous_close=prev_close,
        )
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

    # 非交易时段 / 新交易日盘前：退回最近一个交易日全日分钟线，
    # 但涨跌幅必须清零（现价=昨收），禁止沿用上一交易日 day change。
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
    last_px = float(day.iloc[-1]["close"])
    last_ts = str(day.iloc[-1]["ts"])
    if str(last_day) < today:
        # 新 session 尚无有效现价：昨收盯市，涨跌幅=0
        return overnight_preopen_quote(
            calendar_session=today,
            previous_close=last_px,
            last_ts=last_ts,
        ) | {"_day_bars": pd.DataFrame()}
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
    day_chg = sanitize_day_change_for_session(
        quote_session=last_day,
        calendar_session=today,
        mark=last_px,
        previous_close=prev_close,
    )
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


def points_vs_open(open_px: float, px: float) -> float:
    r = simple_return(px, open_px)
    return float("nan") if r is None else r * 100.0


def pct_vs_open(open_px: float, px: float) -> float | None:
    """较开盘涨幅% = (现价/开盘-1)×100。"""
    v = points_vs_open(open_px, px)
    if v != v:
        return None
    return round(float(v), 2)


def fetch_indices() -> list[dict[str, Any]]:
    """拉取上证指数 / 深证成指：最新点数、涨跌点数、涨跌幅。

    优先新浪批量（与个股同一通道）；akshare 表代码常不带 sh/sz 前缀，对不上就「未找到」。
    """
    blanks = [
        {
            "code": x["code"],
            "name": x["name"],
            "market": x["market"],
            "price": None,
            "chg_points": None,
            "chg_pct": None,
            "error": None,
        }
        for x in INDEX_WATCH
    ]
    batch: dict[str, dict[str, Any]] = {}
    try:
        batch = fetch_sina_batch([x["code"] for x in INDEX_WATCH])
    except Exception:  # noqa: BLE001
        batch = {}
    out: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for item, blank in zip(INDEX_WATCH, blanks, strict=True):
        spot = batch.get(str(item["code"]).lower())
        parsed = _index_from_sina_spot(item, spot) if spot else None
        if parsed is not None:
            out.append(parsed)
        else:
            missing.append(item)
            out.append(dict(blank, error="未找到指数"))
    if not missing:
        return out

    try:
        with AKSHARE_CALL_LOCK:
            spot_df = ak.stock_zh_index_spot_sina()
    except Exception as e:  # noqa: BLE001
        if not any(x.get("price") for x in out):
            return [dict(b, error=str(e)) for b in blanks]
        return out
    if spot_df is None or getattr(spot_df, "empty", True):
        return out
    code_col = "代码" if "代码" in spot_df.columns else spot_df.columns[0]
    by_code = {str(item["code"]): i for i, item in enumerate(INDEX_WATCH)}
    for item in missing:
        row = spot_df[
            spot_df[code_col].astype(str).map(lambda c: _index_codes_match(c, item["code"]))
        ]
        idx = by_code[item["code"]]
        if row.empty:
            continue
        r = row.iloc[0]
        price = pd.to_numeric(r.get("最新价"), errors="coerce")
        chg_pts = pd.to_numeric(r.get("涨跌额"), errors="coerce")
        chg_pct = pd.to_numeric(r.get("涨跌幅"), errors="coerce")
        if pd.isna(price):
            continue
        out[idx] = {
            "code": item["code"],
            "name": item["name"],
            "market": item["market"],
            "price": float(price),
            "chg_points": None if pd.isna(chg_pts) else float(chg_pts),
            "chg_pct": None if pd.isna(chg_pct) else float(chg_pct),
            "error": None,
        }
    return out


def _pos_overnight_high_ok(
    pos: dict[str, Any] | None,
    session: str,
    *,
    t0: bool = False,
    replay: dict[str, Any] | None = None,
    qty: int | None = None,
) -> bool:
    """实仓：昨日策略持有或策略买入才允许用昨高。"""
    pos = pos if isinstance(pos, dict) else {}
    replay = replay if isinstance(replay, dict) else {}
    try:
        q = int(qty if qty is not None else (pos.get("qty") or 0))
    except (TypeError, ValueError):
        q = 0
    return overnight_session_high_ok(
        qty=q,
        buy_time=pos.get("buy_time"),
        session=str(session or "")[:10],
        t0=bool(t0),
        replay_holding=bool(replay.get("holding")),
        last_buy_date=str(replay.get("last_buy_date") or "") or None,
        last_sell_date=str(replay.get("last_sell_date") or "") or None,
    )


def freeze_overnight_peak_for_session(
    pos: dict[str, Any],
    *,
    session: str,
    cost: float | None = None,
    prev_close: float | None = None,
    open_px: float | None = None,
    t0: bool = False,
    qty: int | None = None,
    code: str | None = None,
    persist: bool = False,
) -> float:
    """冻结当日「隔夜峰值」，供开盘保护 / 1m seed 使用。

    盘中 path 会把今日新高写进 ``peak_high``；若再用它算开盘保护，会出现
    「涨停次日高开 → 盘中冲高 → 回用抬高峰值把保护抬到今开之上 → 假开盘保护」
    （黑猫 002068）。9:15 或当日首次结算时冻结一次，全日不变。

    高开且冻结值已 ≥ 今开：视为含今日行情，回退 max(成本, 昨收)。
    低开仍保留昨高（真缺口保护）。
    """
    sess = str(session or "")[:10]
    if not isinstance(pos, dict) or not sess:
        return 0.0
    try:
        q = int(qty if qty is not None else (pos.get("qty") or 0))
    except (TypeError, ValueError):
        q = 0
    try:
        cost_f = float(cost if cost is not None else (pos.get("cost") or 0))
    except (TypeError, ValueError):
        cost_f = 0.0
    if cost_f <= 0:
        return 0.0

    frozen_ok = str(pos.get("overnight_peak_session") or "") == sess
    at_peak = str(pos.get("peak_high_at") or "")
    # 今日竞价戳抬上去的脏峰：作废已冻 overnight，按昨收/成本重算
    if frozen_ok and at_peak[:10] == sess and is_auction_quote_ts(at_peak):
        frozen_ok = False
    seed = 0.0
    if frozen_ok:
        try:
            seed = float(pos.get("overnight_peak") or 0)
        except (TypeError, ValueError):
            seed = 0.0
    if seed <= 0:
        peak_h = _peak_high_usable_for_overnight(pos, sess)
        seed = float(
            overnight_peak_px(
                cost_f,
                prev_close,
                peak_h,
                buy_time=pos.get("buy_time"),
                session=sess,
                qty=q,
                t0=bool(t0),
            )
            or 0
        )
        if seed <= 0:
            seed = cost_f
            if peak_h and peak_h > 0:
                seed = max(seed, float(peak_h))
        pos["overnight_peak"] = round(float(seed), 4)
        pos["overnight_peak_session"] = sess
        if persist:
            ck = _code_key(str(code or ""))
            if ck:
                try:
                    data = load_holdings()
                    p = (data.get("positions") or {}).get(ck)
                    if isinstance(p, dict):
                        p["overnight_peak"] = pos["overnight_peak"]
                        p["overnight_peak_session"] = sess
                        save_holdings(data)
                except Exception:  # noqa: BLE001
                    pass

    try:
        open_f = float(open_px or 0)
    except (TypeError, ValueError):
        open_f = 0.0
    try:
        prev_f = float(prev_close or 0)
    except (TypeError, ValueError):
        prev_f = 0.0
    # 高开且峰值已到/超过今开 → 含今日；开盘保护只用成本/昨收，并回写冻结值防再污染
    if open_f > 0 and prev_f > 0 and open_f > prev_f + 1e-12 and seed + 1e-12 >= open_f:
        clean = max(x for x in (cost_f, prev_f) if x > 0)
        if clean > 0 and abs(clean - seed) > 1e-9:
            seed = clean
            pos["overnight_peak"] = round(float(seed), 4)
            pos["overnight_peak_session"] = sess
            if persist:
                ck = _code_key(str(code or ""))
                if ck:
                    try:
                        data = load_holdings()
                        p = (data.get("positions") or {}).get(ck)
                        if isinstance(p, dict):
                            p["overnight_peak"] = pos["overnight_peak"]
                            p["overnight_peak_session"] = sess
                            save_holdings(data)
                    except Exception:  # noqa: BLE001
                        pass
    return float(seed) if seed > 0 else 0.0


def collect_rows(
    get_quote: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """拉取行情并合并持仓；已触止损视为成交并锁定当日收益。

    get_quote: 可选行情供给（watch 传入 QuoteHub）；默认 fetch_today_quote。
    """
    _ensure_signal_day_caches(force=False)
    quote_fn = get_quote or fetch_today_quote
    holdings = heal_watch_ledger()
    positions = holdings.get("positions", {})
    realized_map = holdings.get("realized_today", {})
    sticky = _alert_sticky_map(holdings)
    from watch_config import is_close_confirmed, portfolio_pool_codes

    portfolio_codes = {_code_key(c) for c in portfolio_pool_codes(holdings)}
    rows: list[dict[str, Any]] = []
    session_today: str | None = None
    phase_now = market_phase()
    phase_label = market_phase_label(phase_now)
    threshold_ok = is_threshold_ready()
    signal_ok_global = is_signal_window()
    stopped_this_scan = False

    for w in _scan_watchlist(holdings):
        code = w["code"]
        pool_src = str(w.get("pool_src") or "")
        if not pool_src:
            if w.get("self_watch") or w.get("manual_add"):
                pool_src = "self"
            elif str(w.get("universe") or "") == "strategy16":
                pool_src = "factor27"
            elif str(w.get("universe") or "") == "strategy1":
                pool_src = "strategy1_pool"
            elif str(w.get("universe") or "") == "strategy17":
                pool_src = "factor28"
        pool_label = str(
            w.get("池来源")
            or (
                "自选"
                if pool_src == "self"
                else (
                    "因子27"
                    if pool_src == "factor27"
                    else (
                        "策略池"
                        if pool_src == "strategy1_pool"
                        else ("紫阳真君" if pool_src == "factor28" else "")
                    )
                )
            )
        )
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
            q = dict(quote_fn(w["sina"]) or {})
            q["session"] = _promote_quote_session(q.get("session"))
            _sanitize_quote_session_high(q)
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
            pos_early = positions.get(code, {})
            qty_early = int(pos_early.get("qty") or 0)
            buy_time_early = pos_early.get("buy_time")
            cost_early = pos_early.get("cost")
            peak_early = pos_early.get("peak_high")
            cost_h = None
            seed_h = None
            since_stop = None
            since_exclusive = False
            path_action_kind = ""
            path_touch_ts = None
            path_touch_stop = 0.0
            hit_path_settle = False
            tp_stage_early = 0
            try:
                tp_stage_early = max(0, int(pos_early.get("tp_stage") or 0))
            except (TypeError, ValueError):
                tp_stage_early = 0
            if qty_early > 0:
                last_tp_early = pos_early.get("last_tp_ts")
                if last_tp_early:
                    since_stop = str(last_tp_early)
                    since_exclusive = True
                else:
                    since_stop = str(buy_time_early) if buy_time_early else None
                try:
                    cost_h = float(cost_early) if cost_early is not None else None
                except (TypeError, ValueError):
                    cost_h = None
                try:
                    peak_h = float(peak_early) if peak_early is not None else None
                except (TypeError, ValueError):
                    peak_h = None
                if cost_h and cost_h > 0:
                    seed_h = freeze_overnight_peak_for_session(
                        pos_early,
                        session=str(q["session"]),
                        cost=cost_h,
                        prev_close=q.get("prev_close"),
                        open_px=q.get("open"),
                        t0=bool(w.get("t0")),
                        qty=qty_early,
                        code=code,
                        persist=True,
                    )
                    if seed_h <= 0:
                        seed_h = overnight_peak_px(
                            cost_h,
                            q.get("prev_close"),
                            peak_h,
                            buy_time=buy_time_early,
                            session=str(q["session"]),
                            qty=qty_early,
                            t0=bool(w.get("t0")),
                        )
                    if seed_h <= 0:
                        seed_h = cost_h
                        if peak_h and peak_h > 0:
                            seed_h = max(seed_h, peak_h)
                    # 禁止把当日快照 high 种进 seed：否则早盘低点会撞上尚未走完的高点
                    # （天通 600330 曾因此被误剔仓）。今日高点只经 1m 顺序抬升。
            # 买入当日 T+1：已记只武装次日，不当作今日已触止损
            t1_today_early = bool(
                qty_early > 0
                and buy_time_early
                and (not bool(w.get("t0")))
                and is_t1_buy_day(buy_time_early, str(q["session"]))
            )
            overnight_armed_lv = bool(pos_early.get("stop_noted")) and _pos_overnight_high_ok(
                pos_early,
                str(q["session"]),
                t0=bool(w.get("t0")),
                qty=qty_early,
            )
            # 有仓：卖价锚也不用当日快照 high（否则 lv.stop 被抬高，无 1m 时 last 会假触）
            # 无 1m 时禁止把昨收垫成峰值；昨收只经 overnight_peak_px。
            snap_high = float(q["high"]) if threshold_ok else float(
                seed_h or cost_h or 0
            )
            high_for_lv = float(seed_h) if (qty_early > 0 and seed_h) else snap_high
            low_for_lv = float(q["low"]) if threshold_ok else float(
                cost_h or q.get("prev_close") or 0
            )
            open_for_lv = float(q["open"]) if threshold_ok else float(
                q.get("prev_close") or q.get("open") or 0
            )
            lv = strategy_levels(
                open_for_lv if open_for_lv > 0 else float(q["open"]),
                entry_pct=entry_pct,
                stop_pct=stop_pct_for_levels,
                tick=tick,
                high_px=high_for_lv if high_for_lv > 0 else None,
                low_px=low_for_lv if low_for_lv > 0 else None,
                cost_px=cost_h,
                peak_high=seed_h,
                vol20_daily=_vol20_daily_for(str(w["sina"]), str(q["session"]))
                if qty_early > 0
                else None,
                overnight_armed=overnight_armed_lv,
                allow_attack=DEFAULT_ALLOW_ATTACK,
            )
            lv_base = strategy_levels(
                open_for_lv if open_for_lv > 0 else float(q["open"]),
                entry_pct=entry_pct,
                stop_pct=base_stop_pct,
                tick=tick,
                high_px=high_for_lv if high_for_lv > 0 else None,
                low_px=low_for_lv if low_for_lv > 0 else None,
                cost_px=cost_h,
                peak_high=seed_h,
                allow_attack=DEFAULT_ALLOW_ATTACK,
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
            overnight_armed_lv = bool(pos_early.get("stop_noted")) and _pos_overnight_high_ok(
                pos_early,
                str(q["session"]),
                t0=bool(w.get("t0")),
                replay=replay,
                qty=qty_early,
            )
            open_buy = float(lv.get("open_buy") or lv["buy_trigger"])
            hit_open = q["high"] + 1e-12 >= open_buy
            hit_buy_raw = hit_open
            path_buy_px = None
            path_buy_ts = None
            if (
                str(FACTOR_ID).lower() in ("factor26", "f26", "26")
                and threshold_ok
                and hit_buy_raw
                and qty_early <= 0
            ):
                bars_buy = q.get("_day_bars")
                if not isinstance(bars_buy, pd.DataFrame) or bars_buy.empty:
                    bars_buy = _today_1m_bars(str(w["sina"]), str(q["session"]))
                    q["_day_bars"] = bars_buy
                hit_buy_raw, path_buy_px, path_buy_ts = _merge_path_buy_hit(
                    hit_open,
                    bars_buy,
                    open_px=float(q["open"]),
                    entry_pct=float(entry_pct),
                    tick=tick,
                )
            # 当日粘滞：已触买进预警后整天保留（有 1m / 现价离开买点也不摘）
            _st_buy = sticky.get(code) if isinstance(sticky.get(code), dict) else None
            hit_buy_raw = _restore_session_buy_hit(
                hit_buy_raw,
                qty=qty_early,
                sticky_row=_st_buy,
                session=str(q["session"]),
            )
            hit_buy = bool(allow_entry) and hit_buy_raw
            _replay_holding_early = bool(replay.get("holding")) and qty_early <= 0
            # 因子26：止损必须 1 分钟 path-dependent；禁止全日 low × 抬高后止损
            path_touch_stop = 0.0
            if str(FACTOR_ID).lower() in ("factor26", "f26", "26"):
                # 9:15–9:25 竞价：不拉分钟、不判触达、不回写峰值（开盘价未定）
                if not threshold_ok:
                    hit_eff_stop = False
                    hit_base_stop = False
                    path_touch_stop = 0.0
                elif qty_early <= 0 and not _replay_holding_early:
                    # 空仓无止损语义：勿用「现价≤开盘派生卖价」标已触止损
                    hit_eff_stop = False
                    hit_base_stop = False
                    path_touch_stop = 0.0
                else:
                    # 仅实仓/纸面持仓拉 1m。空仓勿拉（akshare 单票超时可达 ~90s）。
                    need_m1 = True
                    path_res = _resolve_hit_stop_path_dependent(
                        sina=str(w["sina"]),
                        session=str(q["session"]),
                        quote=q,
                        pullback_pct=float(stop_pct),
                        tick=tick,
                        need_accurate=need_m1,
                        stop_px=float(lv["stop"]),
                        since_ts=since_stop,
                        seed_high=seed_h,
                        cost_px=cost_h,
                        vol20_daily=_vol20_daily_for(str(w["sina"]), str(q["session"])),
                        overnight_armed=overnight_armed_lv,
                        day_open=float(q.get("open") or 0) or None,
                        shares=int(qty_early or 0) or 1000,
                        tp_stage=tp_stage_early,
                        since_exclusive=since_exclusive,
                    )
                    hit_eff_stop = bool(path_res.get("hit_stop"))
                    path_touch_stop = float(path_res.get("touch_stop") or 0)
                    path_action_kind = str(path_res.get("action_kind") or "")
                    path_touch_ts = path_res.get("touch_ts")
                    # 有仓：展示卖价与 path 一致（1m 峰值可能高于快照 high）
                    if qty_early > 0:
                        try:
                            path_stop = float(path_res.get("stop_px") or 0)
                            if path_stop > 0:
                                lv["stop"] = path_stop
                                lv_base["stop"] = path_stop
                            sk = str(path_res.get("stop_kind") or "")
                            if sk:
                                lv["stop_kind"] = sk
                        except (TypeError, ValueError):
                            pass
                    # 刷新持仓峰值（lifecycle HWM，只升不降）
                    # · 1m running_high：主路径
                    # · 隔夜仓才并入 API dayHigh：补漏 tick；买入当日禁止
                    #   （dayHigh 可能发生在建仓前）
                    # · 不把 dayHigh 写进 overnight_peak / seed_h（开盘保护冻结）
                    if qty_early > 0:
                        try:
                            rh = float(path_res.get("running_high") or 0)
                            _sanitize_quote_session_high(q, path_running_high=rh)
                            try:
                                snap_h = float(q.get("high") or 0)
                            except (TypeError, ValueError):
                                snap_h = 0.0
                            try:
                                last_h = float(q.get("last") or 0)
                            except (TypeError, ValueError):
                                last_h = 0.0
                            old_peak = float(pos_early.get("peak_high") or 0)
                            quote_at_h = _bar_ts_str(q.get("last_ts")) or ""
                            live_hwm = bool(
                                is_signal_window()
                                and timestamp_in_signal_window(quote_at_h)
                            )
                            try:
                                open_h = float(q.get("open") or 0)
                            except (TypeError, ValueError):
                                open_h = 0.0
                            try:
                                prev_h = float(q.get("prev_close") or 0)
                            except (TypeError, ValueError):
                                prev_h = 0.0
                            if _clamp_auction_stamped_hwm(
                                pos_early,
                                session=str(q.get("session") or ""),
                                cost=cost_h,
                                prev_close=prev_h,
                                open_px=open_h,
                                last_px=last_h,
                            ):
                                old_peak = float(pos_early.get("peak_high") or 0)
                            snap_h = usable_session_high(
                                quote_high=snap_h,
                                open_px=open_h,
                                last_px=last_h,
                                path_running_high=rh,
                                trust_api_high=trust_quote_day_high(quote_at_h),
                            )
                            new_peak = raise_position_peak_high(
                                persisted_peak=old_peak,
                                entry_price=cost_h,
                                quote_last=last_h if live_hwm else None,
                                quote_day_high=snap_h if live_hwm else None,
                                path_running_high=max(float(seed_h or 0), rh),
                                allow_quote_day_high=bool(
                                    live_hwm and (not t1_today_early)
                                ),
                            )
                            if new_peak > old_peak + 1e-9:
                                at_ts = (
                                    _bar_ts_str(q.get("last_ts"))
                                    or _bar_ts_str(path_res.get("touch_ts"))
                                    or _now()
                                )
                                decision_at = at_ts
                                try:
                                    from temporal_integrity import (
                                        TemporalIntegrityError,
                                        assert_quote_usable,
                                        assert_hwm_causal,
                                    )

                                    assert_quote_usable(
                                        quote_at=at_ts, decision_at=decision_at
                                    )
                                    assert_hwm_causal(
                                        peak_high_at=at_ts, decision_at=decision_at
                                    )
                                    if not _stamp_position_peak_high(
                                        pos_early,
                                        new_peak,
                                        at=at_ts,
                                        decision_at=decision_at,
                                    ):
                                        pass
                                    else:
                                        _holdings_data = load_holdings()
                                        _p = (
                                            _holdings_data.get("positions") or {}
                                        ).get(code)
                                        if isinstance(_p, dict):
                                            _stamp_position_peak_high(
                                                _p,
                                                new_peak,
                                                at=at_ts,
                                                decision_at=decision_at,
                                            )
                                            save_holdings(_holdings_data)
                                except TemporalIntegrityError as te:
                                    print(
                                        f"[{_now()}] {te.code} peak raise blocked "
                                        f"{code}: {te}"
                                    )
                                    # 阻断后不得用未落库的 new_peak 算卖价（禁绕过 guard）
                                    new_peak = float(pos_early.get("peak_high") or old_peak)
                            # dayHigh/last 抬升后，工作卖价与 UI/成交同源重算
                            # 只用已落库（或未抬升）的 peak，禁止未来数据抬 HWM 后仍用 ephemeral new_peak
                            peak_for_stop = float(pos_early.get("peak_high") or 0)
                            if peak_for_stop <= 0:
                                peak_for_stop = float(new_peak or 0)
                            if (
                                peak_for_stop > 0
                                and cost_h
                                and cost_h > 0
                                and (
                                    peak_for_stop > max(float(seed_h or 0), rh) + 1e-9
                                    or bool(overnight_armed_lv)
                                )
                            ):
                                sk2, stop2 = working_stop_price(
                                    cost_px=float(cost_h),
                                    peak_high=float(peak_for_stop),
                                    session_peak=max(
                                        float(peak_for_stop),
                                        float(q.get("open") or 0),
                                    ),
                                    day_open=float(q.get("open") or 0),
                                    overnight_armed=bool(overnight_armed_lv),
                                    hard_pct=float(stop_pct),
                                    tick=tick,
                                    vol20_daily=_vol20_daily_for(
                                        str(w["sina"]), str(q["session"])
                                    ),
                                )
                                if stop2 > 0:
                                    lv["stop"] = float(stop2)
                                    lv_base["stop"] = float(stop2)
                                    if sk2:
                                        lv["stop_kind"] = sk2
                        except (TypeError, ValueError, KeyError):
                            pass
                    if USE_FACTOR4:
                        base_res = _resolve_hit_stop_path_dependent(
                            sina=str(w["sina"]),
                            session=str(q["session"]),
                            quote=q,
                            pullback_pct=float(base_stop_pct),
                            tick=tick,
                            need_accurate=need_m1,
                            stop_px=float(lv_base["stop"]),
                            since_ts=since_stop,
                            seed_high=seed_h,
                            cost_px=cost_h,
                        )
                        hit_base_stop = bool(base_res.get("hit_stop"))
                    else:
                        hit_base_stop = hit_eff_stop
            else:
                if not threshold_ok:
                    hit_base_stop = False
                    hit_eff_stop = False
                    path_touch_stop = 0.0
                else:
                    hit_base_stop = q["low"] <= lv_base["stop"] + 1e-12
                    hit_eff_stop = q["low"] <= lv["stop"] + 1e-12
                    path_touch_stop = float(lv["stop"]) if hit_eff_stop else 0.0
            # 因子4（可选）：牛市暂停止损 → 不自动结算；放宽 → 仅触放宽价才结算
            if USE_FACTOR4 and f4_mode == "suppressed":
                hit_stop = False
            else:
                hit_stop = hit_eff_stop
            # 今日买入 T+1：盈利≥3%不记；其余收到日末才落库武装次日。
            # 盘中「盈<3%」只是预告，不得把 hit_stop 打成真（否则假已触止损）。
            if (
                qty_early > 0
                and buy_time_early
                and (not bool(w.get("t0")))
                and is_t1_buy_day(buy_time_early, str(q["session"]))
            ):
                try:
                    last_n = float(q["last"])
                    stop_n = float(lv["stop"] or 0)
                except (TypeError, ValueError):
                    last_n, stop_n = 0.0, 0.0
                try:
                    low_n = float(q.get("low") or 0)
                except (TypeError, ValueError):
                    low_n = 0.0
                peak_n = float(seed_h or cost_h or 0)
                try:
                    rh_n = float(path_res.get("running_high") or 0) if (
                        str(FACTOR_ID).lower() in ("factor26", "f26", "26")
                        and threshold_ok
                    ) else 0.0
                    peak_n = max(peak_n, rh_n)
                except (TypeError, ValueError, NameError):
                    pass
                dec = resolve_t1_overnight_note(
                    cost_px=float(cost_h or 0),
                    peak_high=peak_n,
                    close_px=last_n,
                    hard_pct=float(stop_pct),
                    bar_low=low_n if low_n > 0 else None,
                )
                note_reason = str(dec.get("reason") or "")
                allow_note = dec.get("noted_px") is not None
                try:
                    prev_c_n = float(q.get("prev_close") or 0)
                except (TypeError, ValueError):
                    prev_c_n = 0.0
                if note_reason == "profit_ge_3pct":
                    clear_stop_noted(code)
                    hit_stop = False
                    hit_eff_stop = False
                    if isinstance(sticky, dict):
                        sticky.pop(code, None)
                elif allow_note:
                    # 硬亏当日可记；t1_trail 仅收盘确认后落库。一律不把「盈<3%」抬成今日 hit_stop。
                    if note_reason == "hard_from_cost" or is_close_confirmed():
                        persisted = persist_stop_noted(
                            code,
                            stop_px=float(dec["noted_px"]),
                            session=str(q["session"]),
                            px_digits=px_digits,
                            reason=note_reason,
                            last_px=last_n,
                            cost_px=float(cost_h or 0),
                            prev_close=prev_c_n if prev_c_n > 0 else None,
                            limit_up_pct=float(limit_down_pct or 0.10),
                        )
                        if persisted:
                            pos_early["stop_noted"] = True
                            pos_early["stop_noted_px"] = float(dec["noted_px"])
                            pos_early["stop_noted_session"] = str(q["session"])
                try:
                    noted_n = float(pos_early.get("stop_noted_px") or 0)
                except (TypeError, ValueError):
                    noted_n = 0.0
                sealed_limit_up = stop_note_invalidated_by_recovery(
                    last_px=last_n,
                    noted_px=noted_n if noted_n > 0 else None,
                    prev_close=prev_c_n if prev_c_n > 0 else None,
                    limit_up_pct=float(limit_down_pct or 0.10),
                    cost_px=float(cost_h or 0) if cost_h else None,
                    reason=note_reason or (
                        "t1_trail"
                        if noted_n > 0
                        and cost_h
                        and abs(noted_n - float(cost_h)) <= 1e-6
                        else None
                    ),
                )
                if sealed_limit_up:
                    clear_stop_noted(code)
                    hit_stop = False
                    hit_eff_stop = False
                    path_touch_stop = 0.0
                    if isinstance(sticky, dict):
                        sticky.pop(code, None)
            f4_tag = (
                format_factor4_tag(bull=bull, mode=f4_mode, widen_mult=f4_widen)
                if USE_FACTOR4
                else "-"
            )
            # 9:25 前：仅竞价参考；9:25–9:30：算阈值/过门/接近预警，不触发；
            # 9:30 起才「已触发」买卖与止损结算
            # 展示与结算拆开：路径/现价破卖价 → 始终可显示「已触止损」；
            # 仅连续竞价才自动结算（午休/收盘后不再把展示清成「否」）。
            # 已触买同理：午休/收盘保留盘中触达，9:30 前仍可降成「将买入」。
            preview_ok = threshold_ok
            signal_ok = signal_ok_global
            hit_path_settle = bool(hit_stop)  # 仅 1m/路径；现价旁路只用于展示
            hit_path = bool(hit_stop)
            try:
                _last_chk = float(q["last"])
                _stop_chk = float(lv.get("stop") or 0)
            except (TypeError, ValueError):
                _last_chk, _stop_chk = 0.0, 0.0
            # 有仓：现价已破当前卖价 → 立即标展示触达（不限时段；结算仍要路径+连续竞价）
            if (
                qty_early > 0
                and _stop_chk > 0
                and _last_chk > 0
                and _last_chk <= _stop_chk + 1e-12
            ):
                hit_path = True
                if path_touch_stop <= 0:
                    path_touch_stop = _stop_chk
            # 当日粘滞：盘中已触过后，午休/收盘后仍保持「已触止损」展示
            _st_prev = sticky.get(code) if isinstance(sticky.get(code), dict) else None
            if (
                qty_early > 0
                and _st_prev
                and str(_st_prev.get("session") or "") == str(q["session"])
                and bool(_st_prev.get("stop_touched"))
            ):
                if _stop_chk <= 0 or _last_chk <= _stop_chk * 1.003 + 1e-12:
                    hit_path = True
                    if path_touch_stop <= 0:
                        try:
                            path_touch_stop = float(
                                _st_prev.get("touch_stop") or _stop_chk or 0
                            )
                        except (TypeError, ValueError):
                            path_touch_stop = _stop_chk
            if not preview_ok:
                hit_buy = False
            elif not signal_ok and _should_demote_pre_signal(phase_now):
                hit_buy = False
            # 用户确认仍持有：不自动止损清槽（天通误剔后曾按 3 空槽补仓）
            hold_locked = bool(qty_early > 0 and pos_early.get("hold_lock"))
            if hold_locked:
                hit_path = False
                hit_path_settle = False
                hit_eff_stop = False
                hit_base_stop = False
                path_touch_stop = 0.0
            # 买入日：中段/抬高卖价触达不记、不展示已触止损；只认硬保护
            if t1_today_early and qty_early > 0 and not hold_locked:
                try:
                    hard_px = float(cost_hard_stop_px(float(cost_h or 0)) or 0)
                except (TypeError, ValueError):
                    hard_px = 0.0
                hard_now = bool(
                    hard_px > 0
                    and _last_chk > 0
                    and _last_chk <= hard_px * 1.003 + 1e-12
                )
                if not hard_now:
                    hit_path = False
                    hit_path_settle = False
                    path_touch_stop = 0.0
                    st_clr = sticky.get(code) if isinstance(sticky, dict) else None
                    if isinstance(st_clr, dict):
                        st_clr.pop("stop_touched", None)
                        st_clr.pop("touch_stop", None)
            hit_stop_show = bool(hit_path)
            hit_stop_settle = bool(
                hit_path_settle and preview_ok and signal_ok and (not hold_locked)
            )
            hit_stop = hit_stop_settle  # 下文结算 / 纸面逻辑用结算口径
            if hit_stop_show:
                _open_bell_ts = None
                try:
                    _o_chk = float(q.get("open") or 0)
                    _c_chk = float(cost_h or 0)
                except (TypeError, ValueError):
                    _o_chk, _c_chk = 0.0, 0.0
                # 开盘保护开盘铃：须 09:25 后开盘价确定；竞价指示价不得伪写成 09:30
                if (
                    preview_ok
                    and qty_early > 0
                    and _o_chk > 0
                    and _c_chk > 0
                ):
                    _prot_chk = float(
                        overnight_open_protect_px(
                            _c_chk,
                            q.get("prev_close"),
                            peak_high=seed_h,
                            buy_time=buy_time_early,
                            session=str(q["session"]),
                            qty=qty_early,
                            t0=bool(w.get("t0")),
                            replay_holding=bool(replay.get("holding")),
                            last_buy_date=str(replay.get("last_buy_date") or "")
                            or None,
                            last_sell_date=str(replay.get("last_sell_date") or "")
                            or None,
                        )
                        or 0
                    )
                    if _prot_chk > 0 and _o_chk <= _prot_chk + 1e-12:
                        _open_bell_ts = session_open_bell_ts(str(q["session"]))
                _force_bell = _open_bell_ts if signal_ok else None
                _stamp_stop_touched(
                    sticky,
                    code,
                    session=str(q["session"]),
                    ts=_force_bell or path_touch_ts,
                    quote=q,
                    touch_stop=float(path_touch_stop or _stop_chk or 0) or None,
                    force_ts=_force_bell,
                )
            if hit_stop_show and qty_early > 0:
                _half_sticky = is_half_stop_kind(
                    str(lv.get("stop_kind") or ""),
                    path_action_kind,
                )
                if _should_demote_pre_signal(phase_now):
                    _sticky_alert = pre_continuous_stop_ui(
                        phase=phase_now, half=_half_sticky
                    )["alert"]
                else:
                    _sticky_alert = hit_stop_alert(
                        str(lv.get("stop_kind") or ""),
                        path_action_kind,
                    )
                _sticky_put(
                    sticky,
                    code,
                    str(q["session"]),
                    {
                        "bg_class": "warn-sell",
                        "alert": _sticky_alert,
                        "pending_sell": True,
                        "stop_touched": True,
                        "touch_stop": float(path_touch_stop or _stop_chk or 0) or None,
                        "near_stop": True,
                    },
                )
            # 当日止损/已结算卖出 → 三槽规则下当日禁再买（含因子22）
            _realized_pre = realized_map.get(code)
            _sold_today_pre = bool(
                _realized_pre
                and str(_realized_pre.get("session") or "") == q["session"]
                and _realized_pre.get("reason") in EXIT_REASONS
            )
            _replay_holding = bool(replay.get("holding")) and int(
                (positions.get(code) or {}).get("qty") or 0
            ) <= 0
            # 回放触止损：不再当策略持有（避免「策略持有+已触止损」）
            _paper_hold = bool(
                _replay_holding and not (hit_stop_show and (signal_ok or hit_path))
            )
            _f22_pre = None
            if _sold_today_pre or (_replay_holding and hit_stop_show):
                # 因子22：收盘确认后才允许再买（盘中 last 不当收盘）
                if is_close_confirmed():
                    _f22_pre = _factor22_rebuy_ok(
                        open_px=float(q["open"]),
                        high_px=float(q["high"]),
                        low_px=float(q["low"]),
                        close_px=float(q["last"]),
                        tick=tick,
                    )
                    if _f22_pre:
                        allow_entry = True
                        if signal_ok:
                            hit_buy = True
                    # 9:30 前仅预览收盘动量，不算已触发
                # 不再因「当日已卖」清空 allow_entry / hit_buy（门禁打开）
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
            # 隔夜：昨日 T+1 已记 → 次日浮盈未过 3% 则峰值回落 2.5%；过 3% 走中段（一半/波动）/档位
            t1_today = bool(
                qty > 0
                and buy_time
                and (not t0)
                and is_t1_buy_day(buy_time, str(q["session"]))
            )
            try:
                hi_q = float(q.get("high") or 0)
            except (TypeError, ValueError):
                hi_q = 0.0
            try:
                cost_q = float(cost or 0)
            except (TypeError, ValueError):
                cost_q = 0.0
            noted_hit = resolve_stop_noted_hit(
                pos,
                open_px=float(q["open"]),
                low_px=float(q["low"]),
                last_px=float(q["last"]),
                high_px=hi_q,
                cost_px=cost_q,
                sellable=sellable,
                t1_buy_day=t1_today,
                locked=stop_locked,
                overnight_high_ok=_pos_overnight_high_ok(
                    pos, str(q["session"]), t0=t0, replay=replay, qty=qty
                ),
            )
            if (
                bool(noted_hit.get("hit"))
                and not bool(pos.get("hold_lock"))
            ):
                hit_stop_show = True
                path_touch_stop = float(
                    noted_hit.get("fill_px") or path_touch_stop or 0
                )
                if signal_ok:
                    hit_stop_settle = True
                    hit_stop = True
            # 结算价：优先 path 触达当时止损；跌停开板则用跌停价
            if bool(limit_state["opened"]):
                stop_base_px = float(limit_state["limit_px"])
            elif path_touch_stop > 0 and hit_stop_show:
                stop_base_px = float(path_touch_stop)
            else:
                stop_base_px = float(lv["stop"])
            # 盯盘按人工/云条件单的触发价记录，不对买卖触发价额外加滑点。
            stop_fill_px = stop_base_px
            # 纸面止损唯一口径：开盘保护 / 1m 路径 / 现价破卖价（不用全日最低撞抬高止损）
            # 09:25 前开盘价未定：禁止用竞价指示价跑 OPEN_PROTECT candidate
            _open_for_exit = float(q.get("open") or 0) if preview_ok else 0.0
            try:
                _day_hi = float(q.get("high") or 0) if preview_ok else 0.0
            except (TypeError, ValueError):
                _day_hi = 0.0
            _day_hi = usable_session_high(
                quote_high=_day_hi,
                open_px=_open_for_exit,
                last_px=float(_last_chk or 0),
                trust_api_high=trust_quote_day_high(q.get("last_ts")),
            )
            _exit_dec = paper_exit_decision(
                qty=qty,
                sellable=sellable,
                t1_today=t1_today,
                hold_locked=hold_locked,
                stop_locked=stop_locked,
                last=_last_chk,
                open_px=_open_for_exit,
                day_high=_day_hi,
                prev_close=q.get("prev_close"),
                cost=cost,
                peak_high=seed_h if seed_h else (pos.get("peak_high")),
                working_stop=float(_stop_chk or stop_fill_px or 0),
                path_hit=bool(hit_path_settle),
                path_fill_px=float(path_touch_stop or stop_fill_px or 0),
                path_action_kind=path_action_kind,
                path_stop_kind=str(lv.get("stop_kind") or ""),
                signal_ok=bool(preview_ok and signal_ok),
                buy_time=buy_time,
                session=str(q["session"]),
            )
            # open_bell sticky / 09:30 时刻仅连续竞价后写入，避免竞价期伪触发时间
            if _exit_dec.get("open_bell") and signal_ok:
                _bell = session_open_bell_ts(str(q["session"]))
                row["_open_bell"] = True
                _stamp_stop_touched(
                    sticky,
                    code,
                    session=str(q["session"]),
                    ts=_bell,
                    quote=q,
                    touch_stop=float(_exit_dec.get("fill_px") or path_touch_stop or 0)
                    or None,
                    force_ts=_bell,
                )
            if _exit_dec.get("hit_show"):
                hit_stop_show = True
            if _exit_dec.get("hit"):
                hit_stop_settle = True
                hit_stop = True
                if float(_exit_dec.get("fill_px") or 0) > 0:
                    stop_fill_px = float(_exit_dec["fill_px"])
                if _exit_dec.get("action_kind"):
                    path_action_kind = str(_exit_dec["action_kind"])
                # 开盘保护=全清；勿把 path 残留的 ladder_half_10 带进半仓
                _exit_kind = str(_exit_dec.get("kind") or "")
                _exit_sk = str(_exit_dec.get("stop_kind") or "")
            else:
                _exit_kind = ""
                _exit_sk = str(lv.get("stop_kind") or "")
            # 买入日涨停/盈≥3%/现价已收回：作废已记，禁止后面再 persist 写回
            if t1_today and qty > 0:
                try:
                    _void_noted = float(
                        pos.get("stop_noted_px")
                        or path_touch_stop
                        or lv.get("stop")
                        or 0
                    )
                except (TypeError, ValueError):
                    _void_noted = 0.0
                try:
                    _void_prev = float(q.get("prev_close") or 0)
                except (TypeError, ValueError):
                    _void_prev = 0.0
                if t1_buy_day_should_void_stop_note(
                    last_px=_last_chk,
                    cost_px=cost,
                    prev_close=_void_prev if _void_prev > 0 else None,
                    noted_px=_void_noted if _void_noted > 0 else None,
                    limit_up_pct=float(limit_down_pct or 0.10),
                    reason=(
                        "t1_trail"
                        if cost
                        and _void_noted > 0
                        and abs(_void_noted - float(cost)) <= 1e-6
                        else "hard_from_cost"
                        if _void_noted > 0
                        else None
                    ),
                ):
                    hit_stop_show = False
                    hit_stop_settle = False
                    hit_stop = False
                    clear_stop_noted(code)
                    if isinstance(sticky, dict):
                        sticky.pop(code, None)
            # 已触止损且可卖 → 本票先平（卡片走已实现分支）；漏平由 settle_due 按 5s/1m 补
            if qty > 0 and hit_stop_settle and sellable > 0 and not stop_locked:
                _fill_ak = path_action_kind
                _fill_sk = _exit_sk if _exit_kind else str(lv.get("stop_kind") or "")
                if _exit_kind == "open_protect" or _exit_dec.get("open_bell"):
                    _fill_ak = "full"
                    _fill_sk = ""
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
                    action_kind=_fill_ak,
                    stop_kind=_fill_sk,
                    first_hit_ts=_open_protect_hit_ts(
                        session=str(q["session"]),
                        fill_px=stop_fill_px,
                        open_px=q.get("open"),
                        existing=_bar_ts_str(path_touch_ts) or _bar_ts_str(q.get("last_ts")),
                        open_bell=bool(_exit_dec.get("open_bell")),
                        exit_kind=_exit_kind,
                    )
                    or _bar_ts_str(path_touch_ts)
                    or _bar_ts_str(q.get("last_ts")),
                    exit_kind=_exit_kind,
                )
                stopped_this_scan = True
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
                f22 = _factor22_rebuy_ok(
                    open_px=float(q["open"]),
                    high_px=float(q["high"]),
                    low_px=float(q["low"]),
                    close_px=float(q["last"]),
                    tick=tick,
                )
                # 三槽：当日已止损/已记卖出 → 禁止同日再买（含因子22）
                f26_rebuy = bool(allow_entry and hit_buy and (not _sold_today_pre))
                rebuy_ok = bool(
                    allow_entry and (not _sold_today_pre) and (f26_rebuy or f22)
                )
                f22_px = (
                    round(float(f22["fill_px"]), px_digits)
                    if f22 and f22.get("fill_px") is not None
                    else None
                )
                buy_show = float(lv.get("open_buy") or lv["buy_trigger"])
                if _sold_today_pre:
                    note += "；当日已卖出·禁再买"
                elif f22 and not f26_rebuy:
                    buy_show = f22_px if f22_px is not None else buy_show
                    note += f"；收盘动量可再买@{buy_show:.{px_digits}f}"
                elif f26_rebuy:
                    note += f"；卖出后再触买点@{buy_show:.{px_digits}f}"
                rebuy_hit = bool(rebuy_ok and signal_ok)
                # 已清仓：因子侧/持仓状态按空仓规则重算（可再进待买入）
                sig0 = strategy_signal(
                    open_px=q["open"],
                    high_px=q["high"],
                    low_px=q["low"],
                    last_px=q["last"],
                    session=q["session"],
                    buy_trigger=float(buy_show),
                    stop_px=lv["stop"],
                    qty=0,
                    buy_time=None,
                    vs_open_pts=vs,
                    entry_pct=entry_pct,
                    stop_pct=stop_pct,
                    px_digits=px_digits,
                    t0=t0,
                    allow_entry=bool(rebuy_ok) and preview_ok,
                    hit_stop=False,
                    allow_attack=DEFAULT_ALLOW_ATTACK,
                )
                if not signal_ok:
                    sig0 = _demote_pre_signal_window(sig0)
                    rebuy_hit = False
                if rebuy_hit:
                    pos_st0 = "待买入"
                    alert0 = (
                        "止损后·收盘动量可再买"
                        if (f22 and not f26_rebuy)
                        else "卖出后再触买"
                    )
                    bg0 = "status-buy"
                    hang0 = float(buy_show) if buy_show is not None else None
                    note0 = note
                else:
                    pos_st0 = STATUS_STOP_CLOSED
                    # 信号=已触止损；持仓态=已平仓
                    alert0 = (
                        SIGNAL_STOP_HIT
                        if reason == REASON_STOP
                        else (reason or SIGNAL_STOP_HIT)
                    )
                    bg0 = sig0.get("bg_class") or "status-flat"
                    hang0 = None
                    note0 = (
                        note + "；当日禁再买"
                        if _sold_today_pre
                        else (note + "；可再买·待触买点" if allow_entry else note)
                    )
                row0 = {
                        "市场": str(pos.get("market") or w["market"]),
                        "代码": code,
                        "名称": str(pos.get("name") or w["name"]),
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
                        "池来源": pool_label or None,
                        "pool_src": pool_src or None,
                        "买点": buy_show,
                        "止损": round(fill_px, px_digits) if not rebuy_hit else lv["stop"],
                        "基础止损": (
                            round(fill_px, px_digits) if not rebuy_hit else lv_base["stop"]
                        ),
                        "因子4": f4_tag,
                        "牛市": ("是" if bull else "否") if USE_FACTOR4 else "-",
                        "已触买": "是" if rebuy_hit else "否",
                        "已触止损": "是" if hit_stop or reason == REASON_STOP else "否",
                        "因子侧": "买入" if rebuy_hit else "空仓",
                        "因子价": buy_show if rebuy_hit else sig0.get("因子价"),
                        "因子触发": (
                            (
                                f"收盘动量 {q['session'][5:7]}月{q['session'][8:10]}日"
                                if (f22 and not f26_rebuy)
                                else f"再触买 {q['session'][5:7]}月{q['session'][8:10]}日"
                            )
                            if rebuy_hit and len(str(q["session"])) >= 10
                            else sig0.get("因子触发")
                        ),
                        "持仓状态": pos_st0,
                        "已触发因子侧": "买入" if rebuy_hit else sig0.get("已触发因子侧"),
                        "已触发因子价": buy_show if rebuy_hit else sig0.get("已触发因子价"),
                        "未触发因子侧": sig0.get("未触发因子侧"),
                        "未触发因子价": sig0.get("未触发因子价"),
                        "距已触发价差": sig0.get("距已触发价差"),
                        "距已触发%": sig0.get("距已触发%"),
                        "距未触发价差": sig0.get("距未触发价差"),
                        "距未触发%": sig0.get("距未触发%"),
                        "距因子价差": sig0.get("距因子价差"),
                        "距因子%": sig0.get("距因子%"),
                        "形态": sig0.get("形态") or bar_shape(q["open"], q["last"]),
                        "预警": alert0,
                        "建议挂单": hang0,
                        "挂单说明": note0,
                        "近买点": bool(rebuy_ok and not rebuy_hit and preview_ok)
                        or bool(rebuy_hit),
                        "近止损": False,
                        "bg_class": bg0,
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
                    allow_entry=bool(allow_entry),
                )
                # 再买信号：仅当日本票未因止损/已记卖出时放行
                if rebuy_hit and not _sold_today_pre:
                    row0["持仓状态"] = "待买入"
                    row0["当日禁买"] = False
                    row0["预警"] = alert0
                    row0["建议挂单"] = hang0
                    row0["近买点"] = True
                    row0["已触买"] = "是"
                    row0["bg_class"] = "status-buy"
                elif _sold_today_pre:
                    row0["当日禁买"] = True
                    if str(row0.get("持仓状态") or "") in ("", "空仓", "待买入"):
                        row0["持仓状态"] = STATUS_STOP_CLOSED
                elif allow_entry:
                    row0["当日禁买"] = False
                    if _is_stop_closed_status(row0.get("持仓状态")):
                        row0["挂单说明"] = note + "；可再买·待触买点"
                _fill_row_signal_times(
                    row0,
                    sticky,
                    code,
                    hit_buy=bool(rebuy_hit or str(row0.get("已触买") or "") == "是"),
                    hit_stop=True,
                    buy_time=None,
                    realized=realized if isinstance(realized, dict) else None,
                )
                _attach_strategy_pnl_fields(
                    row0,
                    w=w,
                    daily=daily,
                    q=q,
                    entry_pct=entry_pct,
                    stop_pct=base_stop_pct,
                    tick=tick,
                    prev_entry_mode=prev_entry_mode,
                    limit_down_pct=limit_down_pct,
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
                buy_trigger=path_buy_px
                if path_buy_px
                else float(lv.get("open_buy") or lv["buy_trigger"]),
                stop_px=lv["stop"],
                qty=sig_qty,
                buy_time=sig_buy_time,
                vs_open_pts=vs,
                entry_pct=entry_pct,
                stop_pct=stop_pct,
                px_digits=px_digits,
                t0=t0,
                # 纸面仓禁止买入预警；9:30 前允许接近预警，已触买由下方 demote
                allow_entry=False if paper_active else (allow_entry and preview_ok),
                hit_stop=bool(hit_stop_show),
                hit_buy=bool(hit_buy),
                allow_attack=DEFAULT_ALLOW_ATTACK,
                cost_px=cost_h if cost_h else None,
                peak_high=seed_h if seed_h else None,
                stop_kind=str(lv.get("stop_kind") or "") or None,
            )
            if not signal_ok:
                if qty > 0 and hit_stop_show:
                    # 午休/收盘：保留盘中已触达「待卖出」；竞价/开盘前：只预警不冒充待卖出
                    _half_show = is_half_stop_kind(
                        str(lv.get("stop_kind") or ""),
                        path_action_kind,
                    )
                    sig = dict(sig)
                    if _should_demote_pre_signal(phase_now):
                        # 09:15–09:30：竞价观察 / 竞价止损预警
                        seed = {
                            "alert": (
                                "半仓止盈·待盘中结算"
                                if _half_show
                                else "已触止损·待盘中结算"
                            ),
                            "挂单说明": str(sig.get("挂单说明") or ""),
                        }
                        sig.update(_demote_pre_signal_window(seed, phase=phase_now))
                        sig["hit_stop"] = True
                        sig["pending_sell"] = True
                        sig["near_stop"] = True
                        sig["bg_class"] = "warn-sell"
                    else:
                        # lunch / closed：保留可执行语义展示（待卖出）
                        sig["hit_stop"] = True
                        sig["pending_sell"] = True
                        sig["near_stop"] = True
                        sig["bg_class"] = "warn-sell"
                        sig["持仓状态"] = "待卖出"
                        sig["因子触发"] = "已触发" if preview_ok else "接近"
                        if preview_ok:
                            sig["alert"] = (
                                "半仓止盈·待盘中结算"
                                if _half_show
                                else "已触止损·待盘中结算"
                            )
                            note = str(sig.get("挂单说明") or "")
                            if "连续竞价" not in note:
                                sig["挂单说明"] = (
                                    (note + "；" if note else "")
                                    + (
                                        "已触10%半仓，待 9:30–11:30 / 13:00–15:00 记减半"
                                        if _half_show
                                        else "已破止损价，待 9:30–11:30 / 13:00–15:00 自动结算"
                                    )
                                )
                elif _should_demote_pre_signal(phase_now):
                    sig = _demote_pre_signal_window(sig, phase=phase_now)
                if _should_demote_pre_signal(phase_now):
                    hit_buy = False
                # 结算口径保持 False；展示口径 hit_stop_show / hit_buy 不变
                hit_stop = False
            if qty > 0 and hit_stop_show and stop_locked:
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
                        "hit_stop": True,
                    }
                )
            elif qty > 0 and hit_stop_show and sellable <= 0 and not stop_locked:
                # 典型：买入当日 T+1；持仓状态仍「已经买入」，预警提示明日可卖
                sig = dict(sig)
                t1_today = (not t0) and is_t1_buy_day(buy_time, q["session"])
                touch_show = (
                    float(path_touch_stop)
                    if path_touch_stop > 0
                    else float(lv["stop"])
                )
                if t1_today:
                    # 三槽：当日不可卖 → 不进「待卖出」。展示已记只认账本，禁止再用中段卖价写回。
                    try:
                        _led_px = float(pos.get("stop_noted_px") or 0)
                    except (TypeError, ValueError):
                        _led_px = 0.0
                    try:
                        _led_last = float(q.get("last") or 0)
                    except (TypeError, ValueError):
                        _led_last = 0.0
                    ledger_ok = bool(pos.get("stop_noted")) and t1_stop_note_px_is_legal(
                        stop_px=_led_px,
                        cost_px=cost,
                    ) and not t1_buy_day_should_void_stop_note(
                        last_px=_led_last,
                        cost_px=cost,
                        prev_close=q.get("prev_close"),
                        noted_px=_led_px if _led_px > 0 else None,
                        limit_up_pct=float(limit_down_pct or 0.10),
                    )
                    if not ledger_ok:
                        if pos.get("stop_noted") or pos.get("stop_noted_px"):
                            clear_stop_noted(code)
                        sig.update(
                            {
                                "alert": "持有·T+1",
                                "bg_class": "status-hold",
                                "pending_sell": False,
                                "持仓状态": "已经买入",
                                "建议挂单": None,
                                "hit_stop": False,
                            }
                        )
                        if isinstance(sticky, dict):
                            sticky.pop(code, None)
                    else:
                        show_px = _led_px if _led_px > 0 else touch_show
                        sig.update(
                            {
                                "alert": "持有·T+1·止损已记",
                                "bg_class": "status-hold",
                                "pending_sell": False,
                                "持仓状态": "已经买入",
                                "建议挂单": None,
                                "挂单说明": (
                                    f"今日买入不可卖；买入后曾触硬保护"
                                    f"@{show_px:.{px_digits}f}。"
                                    "下一交易日：浮盈未过3%则动态峰值回落2.5%全清；"
                                    "过3%走中段（回落一半与波动回落谁先到走谁），过10%走档位/回落2个点"
                                ),
                                "因子触发": format_trigger_md(buy_time)
                                or format_trigger_md(q["session"])
                                or "持有",
                                "hit_stop": True,
                            }
                        )
                else:
                    sig.update(
                        {
                            "alert": "已触止损·暂不可卖",
                            "bg_class": "warn-sell",
                            "pending_sell": True,
                            "持仓状态": "待卖出",
                            "建议挂单": None,
                            "挂单说明": "无可卖数量，请核对 available / 买入日",
                            "因子触发": "已触发",
                            "hit_stop": True,
                        }
                    )
            # T+1 实仓未触止损：强制持有态并清卖出粘滞
            elif (
                qty > 0
                and sellable <= 0
                and (not t0)
                and is_t1_buy_day(buy_time, q["session"])
                and not hit_stop_show
            ):
                sig = dict(sig)
                alert0 = str(sig.get("alert") or "")
                if (
                    not alert0.startswith("持有")
                    and "已触买" not in alert0
                    and "将买入" not in alert0
                ):
                    sig["alert"] = "持有·T+1"
                sig["bg_class"] = "status-hold"
                sig["pending_sell"] = False
                sig["持仓状态"] = "已经买入"
                sig["hit_stop"] = False
                if isinstance(sticky, dict):
                    sticky.pop(code, None)
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
                        "alert": "已经买入·因子4牛市暂停止损",
                        "bg_class": "status-hold",
                        "pending_sell": False,
                        "持仓状态": "已经买入",
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
            # 稳定化后仍保留「当日已触止损」粘滞标记，避免午休被洗掉
            if hit_stop_show and qty > 0 and isinstance(sticky.get(code), dict):
                sticky[code]["stop_touched"] = True
                if path_touch_stop > 0:
                    sticky[code]["touch_stop"] = float(path_touch_stop)
            if hit_buy and preview_ok:
                _stamp_buy_touched(
                    sticky,
                    code,
                    session=str(q["session"]),
                    ts=path_buy_ts or (buy_time if qty > 0 else None),
                    quote=q,
                )
            elif (
                qty > 0
                and buy_time
                and str(buy_time).startswith(str(q["session"])[:10])
            ):
                _stamp_buy_touched(
                    sticky,
                    code,
                    session=str(q["session"]),
                    ts=buy_time,
                    quote=q,
                )
            entry_for_overlay = bool(allow_entry and preview_ok and signal_ok)
            if not (_paper_hold and hit_stop_show):
                sig = _overlay_buy_signal_on_hold(
                    sig,
                    hit_buy=hit_buy if (signal_ok or not _should_demote_pre_signal(phase_now)) else False,
                    allow_entry=entry_for_overlay,
                    paper_active=paper_active,
                    qty=qty,
                    buy_time=buy_time,
                    session=str(q["session"]),
                    buy_trigger=float(lv.get("open_buy") or lv["buy_trigger"]),
                    stop_px=float(lv["stop"]),
                    last_px=float(q["last"]),
                    px_digits=px_digits,
                )
                # 已触止损展示中：勿再 demote 成「持有」；午休/收盘勿把已触买降成将买入
                if (
                    not signal_ok
                    and not (qty > 0 and hit_stop_show)
                    and _should_demote_pre_signal(phase_now)
                ):
                    sig = _demote_pre_signal_window(sig)
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
                pnl, pnl_pct = mark_unrealized(q["last"], cost, qty)
                cost_value = float(cost) * qty

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
                    "市场": str(pos.get("market") or w["market"]),
                    "代码": code,
                    "名称": str(pos.get("name") or w["name"]),
                    "交易日": q["session"],
                    "开盘": round(q["open"], px_digits),
                    "最高": round(q["high"], px_digits),
                    "今日最高": round(q["high"], px_digits),
                    "最低": round(q["low"], px_digits),
                    "现价": round(q["last"], px_digits),
                    "昨收": None
                    if q.get("prev_close") is None
                    else round(float(q["prev_close"]), px_digits),
                    "当日涨幅": None if day_chg is None else round(float(day_chg), 2),
                    "较开盘点": vs,
                    "较开盘涨幅": vs_pct,
                    "阈值%": pct_pct,
                    "池来源": pool_label or None,
                    "pool_src": pool_src or None,
                    "买点": float(lv.get("open_buy") or lv["buy_trigger"]),
                    "止损": lv["stop"],
                    "基础止损": lv_base["stop"],
                    "因子4": f4_tag,
                    "牛市": ("是" if bull else "否") if USE_FACTOR4 else "-",
                    "已触买": "是" if sig.get("hit_buy") else "否",
                    "已触止损": "是" if hit_stop_show else (
                        "触基础·暂停"
                        if (USE_FACTOR4 and f4_mode == "suppressed" and hit_base_stop)
                        else "否"
                    ),
                    "因子侧": sig.get("因子侧"),
                    "因子价": sig.get("因子价"),
                    "因子触发": sig.get("因子触发"),
                    "持仓状态": sig.get("持仓状态") or (
                        "已经买入" if qty > 0 else "空仓"
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
                    "买入时间": buy_time,
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
            _attach_hwm_row_fields(row, pos if isinstance(pos, dict) else None, px_digits=px_digits)
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
            _fill_row_signal_times(
                row,
                sticky,
                code,
                hit_buy=bool(hit_buy or str(row.get("已触买") or "") == "是"),
                hit_stop=bool(hit_stop_show),
                buy_time=buy_time,
                realized=realized if isinstance(realized, dict) else None,
            )
            row["_path_hit"] = bool(hit_path_settle)
            try:
                row["_path_fill_px"] = float(path_touch_stop or 0)
            except (TypeError, ValueError, NameError):
                row["_path_fill_px"] = 0.0
            row["_path_ts"] = _bar_ts_str(path_touch_ts) if path_touch_ts else None
            row["_path_buy_ts"] = _bar_ts_str(path_buy_ts) if path_buy_ts else None
            row["_path_action_kind"] = str(path_action_kind or "")
            try:
                row["_path_stop_kind"] = str(lv.get("stop_kind") or "")
            except (TypeError, NameError):
                row["_path_stop_kind"] = ""
            if (
                realized
                and str(realized.get("session") or "") == q["session"]
                and realized.get("reason") in EXIT_REASONS
            ):
                row["当日禁买"] = True
            _attach_strategy_pnl_fields(
                row,
                w=w,
                daily=daily,
                q=q,
                entry_pct=entry_pct,
                stop_pct=base_stop_pct,
                tick=tick,
                prev_entry_mode=prev_entry_mode,
                limit_down_pct=limit_down_pct,
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
                    "市场": str(pos.get("market") or w["market"]),
                    "代码": code,
                    "名称": str(pos.get("name") or w["name"]),
                    "交易日": "-",
                    "开盘": None,
                    "最高": None,
                    "最低": None,
                    "现价": None,
                    "当日涨幅": None,
                    "较开盘点": None,
                    "较开盘涨幅": None,
                    "阈值%": pct_pct,
                    "池来源": pool_label or None,
                    "pool_src": pool_src or None,
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
        n_due = settle_due_paper_stops(
            rows, session=session_today, signal_ok=bool(signal_ok_global)
        )
        if n_due:
            stopped_this_scan = True
            print(f"[{_now()}] 扫仓补平 {n_due} 只（5s触发/1m路径/开盘保护，按时刻先后）")
            holdings = load_holdings()
            positions = holdings.get("positions", {})
            realized_map = holdings.get("realized_today", {})
        data = load_holdings()
        before = dict(data.get("realized_today") or {})
        _purge_stale_realized(data, session_today)
        if data.get("realized_today") != before:
            save_holdings(data)
        _save_alert_sticky(session_today, sticky)

    for r in rows:
        code_hwm = _code_key(str(r.get("代码") or ""))
        pos_hwm = positions.get(code_hwm) if code_hwm else None
        try:
            pdg_hwm = int(r.get("价位小数") or 2)
        except (TypeError, ValueError):
            pdg_hwm = 2
        _attach_hwm_row_fields(
            r, pos_hwm if isinstance(pos_hwm, dict) else None, px_digits=pdg_hwm
        )
        _enrich_side_price_fields(r)
        _finalize_position_row(r)
        enrich_signal_single_return(r)
        code = _code_key(str(r.get("代码") or ""))
        if code in portfolio_codes:
            _enrich_float_pnl(r)
        else:
            r["浮盈"] = None
            r["浮盈%"] = None
            r["盈亏状态"] = None
            r["盈亏说明"] = None

    total_mv = sum(
        float(r["市值"])
        for r in rows
        if r.get("市值") is not None and int(r.get("持仓") or 0) > 0
    )
    quotes_ok = _position_quotes_ready(rows)
    if quotes_ok:
        account_total = _sync_account_total(rows)
    else:
        account_total = _account_total(rows, load_holdings())
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
    f2_raw = (
        data_f2.get("factor2")
        if isinstance(data_f2.get("factor2"), dict)
        else {}
    )
    if quotes_ok:
        f2_status = sync_factor2(
            data_f2,
            equity=account_total,
            session=str(session_f2),
            strategy_id=STRATEGY_ID,
        )
        save_holdings(data_f2)
    else:
        f2_status = f2_raw
    for r in rows:
        r["因子2动作"] = f2_status.get("action")
        r["因子2"] = f2_status.get("label")
        r["因子2建议额"] = f2_status.get("suggest_amount")
        r["因子2回撤%"] = f2_status.get("dd_pct")
        r["因子2档位"] = f2_status.get("layers")

    # 尾盘空槽：持仓>隔夜上限时强制卖最弱可卖仓（纸面）
    eod_sold: list[str] = []
    if quotes_ok:
        eod_sold = force_eod_reserve_slot(
            rows, session=str(session_f2), now=pd.Timestamp.now()
        )
        if eod_sold:
            stopped_this_scan = True

    if (not quotes_ok) or phase_now != "continuous":
        slot_info = _slot_meta_from_holdings(load_holdings())
        slot_info["candidates"] = []
        slot_info["bought"] = []
        sess_q = str(trading_session_date())
        opened_q = today_new_symbol_codes(sess_q)
        slot_info["session"] = sess_q
        slot_info["buysToday"] = len(opened_q)
        slot_info["buysLeft"] = max(
            0, int(MAX_NEW_SYMBOLS_PER_SESSION) - len(opened_q)
        )
        slot_info["newSymbolsToday"] = opened_q
        slot_info["newSymbolsLeft"] = slot_info["buysLeft"]
        if eod_sold:
            slot_info["eodReserveSold"] = eod_sold
        if not quotes_ok:
            slot_info["deferred"] = "quotes_not_ready"
        else:
            slot_info["deferred"] = "not_continuous"
    else:
        # 本轮已平也立刻补槽：先平再买，不隔一轮 5s
        slot_info = _apply_portfolio_slots(
            rows, account_total=account_total, phase_now=phase_now
        )
        if stopped_this_scan:
            slot_info["closedThenBuy"] = True
    # 自动入仓后重算仓位%
    if slot_info.get("bought"):
        holdings = load_holdings()
        portfolio_codes.update(occupied_slot_codes(holdings))
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
            code = _code_key(str(r.get("代码") or ""))
            if code in portfolio_codes:
                _enrich_float_pnl(r)

    for r in rows:
        r["槽位信息"] = (
            f"{slot_info.get('occupiedCount', 0)}/{slot_info.get('max', MAX_PORTFOLIO_SLOTS)}"
        )
    # 信号层（触买预警）在成交层（入槽）之后；finalize 再收敛持仓态
    _annotate_unfilled_buy_signals(rows, slot_info)
    for r in rows:
        _finalize_position_row(r)
        enrich_signal_single_return(r)
    for r in rows:
        if int(r.get("持仓") or 0) > 0:
            _forget_slot_closed(str(r.get("代码") or ""))
        _enrich_closed_day_pnl(r)
        _finalize_position_row(r)
        enrich_signal_single_return(r)
    if rows:
        rows[0]["_slot_meta"] = slot_info
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
        pnl, pnl_pct = mark_unrealized(last_f, cost, qty)
        row["浮盈"] = pnl
        row["浮盈%"] = pnl_pct
        row["盈亏状态"] = "浮盈"
        return

    paper = bool(row.get("策略回放持有")) or str(row.get("持仓状态") or "") == "策略持有"
    if paper and qty <= 0:
        buy_px = row.get("已触发因子价")
        if buy_px is None:
            buy_px = row.get("因子价")
        if buy_px is not None:
            pnl, pnl_pct = mark_unrealized(last_f, buy_px, 1)
            if pnl is not None:
                row["浮盈"] = pnl
                row["浮盈%"] = pnl_pct
                row["盈亏状态"] = "浮盈"
                row["盈亏说明"] = "策略买入价·单股"
        return

    if qty <= 0:
        if _is_closed_trace_row(row):
            _enrich_closed_day_pnl(row)
            return
        row["浮盈"] = None
        row["浮盈%"] = None
        row["盈亏状态"] = None


_LOTS_CACHE: dict[str, Any] = {"mtime": None, "lots": {}}


def _realized_today_codes(
    session: str,
    *,
    data: dict[str, Any] | None = None,
) -> set[str]:
    """当日纸面真实卖出（realized_today）代码集。"""
    day = str(session or "")[:10]
    if len(day) < 10:
        return set()
    book = data if data is not None else load_holdings()
    out: set[str] = set()
    for code, rec in (book.get("realized_today") or {}).items():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("session") or "")[:10] != day:
            continue
        ck = _code_key(str(code))
        if ck:
            out.add(ck)
    return out


def _is_closed_trace_row(
    row: dict[str, Any],
    *,
    lots: dict[str, dict[str, Any]] | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """三槽实仓清仓留痕：仅当日、仅真实占槽后卖出。

    只认「已实现」或 closed_today 且当日有 realized_today。
    禁止：成交流水旧买档 + 今日策略回放止损 → 冒充三槽平仓（东材 601208）。
    """
    _ = lots  # 旧调用方仍可传；不再用未平买档推断平仓
    if int(row.get("持仓") or 0) > 0:
        return False
    if bool(row.get("已实现")):
        return True
    code = _code_key(str(row.get("代码") or ""))
    if not code:
        return False
    sess = str(row.get("交易日") or "")[:10]
    book_traces = traces if traces is not None else _slot_closed_map()
    rec = book_traces.get(code) if isinstance(book_traces, dict) else None
    rec_sess = str((rec or {}).get("session") or "")[:10]
    if not sess or rec_sess != sess:
        return False
    return code in _realized_today_codes(sess)


def _parse_open_lots(text: str) -> dict[str, dict[str, Any]]:
    """成交流水推到当前未平买档：code → {qty, cost, time}。"""
    lots: dict[str, dict[str, Any]] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        note = str(rec.get("note") or "")
        if "非实盘" in note:
            continue
        code = _code_key(str(rec.get("code") or ""))
        if not code:
            continue
        side = str(rec.get("side") or "").lower()
        if side in ("buy", "买入"):
            try:
                qty = int(rec.get("after_qty") if rec.get("after_qty") is not None else rec.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            cost = rec.get("avg_cost")
            if cost is None:
                cost = rec.get("price")
            try:
                cost_f = float(cost) if cost is not None else 0.0
            except (TypeError, ValueError):
                cost_f = 0.0
            if qty > 0 and cost_f > 0:
                lots[code] = {
                    "qty": qty,
                    "cost": cost_f,
                    "time": rec.get("time"),
                }
        elif side in ("sell", "卖出", "stop"):
            after = rec.get("after_qty")
            try:
                after_n = int(after) if after is not None else 0
            except (TypeError, ValueError):
                after_n = 0
            if after_n <= 0:
                lots.pop(code, None)
            elif code in lots:
                lots[code]["qty"] = after_n
    return lots


def _last_open_lots_from_trades(*, text: str | None = None) -> dict[str, dict[str, Any]]:
    """昨仓未记账卖出时，用 trades.jsonl 最后一档买量估已平仓当日盈亏。"""
    if text is not None:
        return _parse_open_lots(text)
    try:
        mtime = TRADES_FILE.stat().st_mtime if TRADES_FILE.exists() else None
    except OSError:
        return {}
    if _LOTS_CACHE.get("mtime") == mtime and isinstance(_LOTS_CACHE.get("lots"), dict):
        return _LOTS_CACHE["lots"]
    raw = ""
    if TRADES_FILE.exists():
        try:
            raw = TRADES_FILE.read_text(encoding="utf-8")
        except OSError:
            return {}
    lots = _parse_open_lots(raw)
    _LOTS_CACHE["mtime"] = mtime
    _LOTS_CACHE["lots"] = lots
    return lots


def _row_overnight_high_ok(row: dict[str, Any]) -> bool:
    """已平仓/实仓行：昨日策略持有或策略买入才允许用昨高。

    旧已平仓行可能没有买入时间，默认按隔夜仓；今日新买必须带买入时间。
    """
    buy_time = row.get("买入时间") or row.get("buy_time")
    session = str(row.get("交易日") or row.get("session") or "")[:10]
    if not buy_time:
        return True
    try:
        qty = int(row.get("持仓") or row.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    return overnight_session_high_ok(
        qty=qty,
        buy_time=buy_time,
        session=session,
        replay_holding=bool(row.get("策略回放持有")),
        last_buy_date=str(row.get("last_buy_date") or "") or None,
        last_sell_date=str(row.get("last_sell_date") or "") or None,
    )


def _closed_open_protect_px(
    cost: float | None,
    prev_close: float | None,
    peak_high: float | None = None,
    *,
    overnight_high_ok: bool = False,
) -> float:
    """开盘时刻保护价：委托因子26 overnight_open_protect_px。"""
    try:
        cost_f = float(cost or 0)
    except (TypeError, ValueError):
        return 0.0
    return overnight_open_protect_px(
        cost_f,
        prev_close,
        peak_high=peak_high,
        overnight_high_ok=bool(overnight_high_ok),
    )


def _peek_cached_today_1m(sina: str, session: str) -> pd.DataFrame | None:
    """只读 1m 缓存，不拉网（单测/无缓存时返回 None）。"""
    key = str(sina or "").lower()
    sess = str(session or "")[:10]
    if not key or not sess:
        return None
    hit = _M1_CACHE.get(key)
    if hit and str(hit[1])[:10] == sess and isinstance(hit[2], pd.DataFrame) and not hit[2].empty:
        return hit[2]
    look = _M1_CACHE.get(f"lookback:{key}")
    if look and isinstance(look[2], pd.DataFrame) and not look[2].empty and "ts" in look[2].columns:
        day = look[2][_day_key_series(look[2]["ts"]) == sess]
        if not day.empty:
            return day
    return None


def _closed_1m_bars(row: dict[str, Any]) -> pd.DataFrame | None:
    bars = row.get("_day_bars")
    if isinstance(bars, pd.DataFrame) and not bars.empty:
        return bars
    code = _code_key(str(row.get("代码") or ""))
    sess = str(row.get("交易日") or "")[:10]
    if not code or not sess:
        return None
    sina = _sina_of(code)
    cached = _peek_cached_today_1m(sina, sess)
    if cached is not None:
        return cached
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    day = _today_1m_bars(sina, sess)
    if isinstance(day, pd.DataFrame) and not day.empty:
        return day
    return None


def _closed_path_fill(
    row: dict[str, Any],
    *,
    cost: float,
    bars: pd.DataFrame | None,
) -> float | None:
    """已平仓成交价：因子26 first_session_exit_fill（1 分钟第一次触达）。"""
    sina = _sina_of(_code_key(str(row.get("代码") or "")))
    sess = str(row.get("交易日") or "")[:10]
    vol = None
    if sina and sess and not os.environ.get("PYTEST_CURRENT_TEST"):
        vol = _vol20_daily_for(sina, sess)
    return first_session_exit_fill(
        bars,
        cost_px=cost,
        prev_close=_as_money(row.get("昨收")),
        day_open=_as_money(row.get("开盘")),
        vol20_daily=vol,
        overnight_high_ok=_row_overnight_high_ok(row),
        peak_high=_as_money(row.get("峰值")) or _as_money(row.get("peak_high")),
        buy_time=row.get("买入时间") or row.get("buy_time"),
        session=sess,
    )


def _closed_mark_px(
    row: dict[str, Any],
    *,
    cost: float | None = None,
    bars: pd.DataFrame | None = None,
) -> float | None:
    """已平仓价：与 paper_exit_decision 同序——开盘保护优先，再 1m 触达。"""
    cost_f = cost if cost is not None else _as_money(row.get("成本"))
    try:
        cost_n = float(cost_f) if cost_f else 0.0
    except (TypeError, ValueError):
        cost_n = 0.0
    open_px = _as_money(row.get("开盘"))
    prev = _as_money(row.get("昨收"))
    peak = _as_money(row.get("峰值")) or _as_money(row.get("peak_high"))
    overnight_ok = _row_overnight_high_ok(row)
    open_prot = (
        _closed_open_protect_px(
            cost_n, prev, peak_high=peak, overnight_high_ok=overnight_ok
        )
        if cost_n > 0
        else 0.0
    )
    if open_px is not None and open_prot > 0 and open_px <= open_prot + 1e-12:
        return open_px
    path_fill = _closed_path_fill(row, cost=cost_n, bars=bars) if cost_n > 0 else None
    if path_fill is not None:
        return path_fill
    stop = _as_money(row.get("止损"))
    low = _as_money(row.get("最低"))
    hit = str(row.get("已触止损") or "") == "是"
    hard = cost_hard_stop_px(cost_n) if cost_n > 0 else 0.0
    # 展示止损 ≤ 开盘：才是开盘时刻就能碰到的下行保护；高于开盘的是盘中抬高后的价，禁止拿去撞今开。
    display_ok = bool(stop) and open_px is not None and float(stop) <= float(open_px) + 1e-12
    prot = None
    if display_ok:
        prot = max(x for x in (float(stop), hard) if x > 0)
    elif hard > 0:
        prot = hard
    protective_fill = None
    if hit and prot is not None:
        if open_px is not None and open_px <= prot + 1e-12:
            protective_fill = open_px
        elif low is not None and low <= prot + 1e-12:
            protective_fill = prot
        elif display_ok:
            protective_fill = prot
    existing = _as_money(row.get("成交价"))
    fake_gap = bool(
        existing is not None
        and open_px is not None
        and abs(float(existing) - float(open_px)) <= 1e-6
        and open_prot > 0
        and float(existing) > open_prot + 1e-12
    )
    if fake_gap:
        existing = None
    if existing is not None and protective_fill is not None:
        if existing + 1e-9 < float(protective_fill):
            return protective_fill
        return existing
    if existing is not None:
        return existing
    return protective_fill


def _enrich_closed_day_pnl(
    row: dict[str, Any],
    *,
    lots: dict[str, dict[str, Any]] | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
) -> None:
    """已平仓卡片：今买相对买入价、昨仓相对昨收；已实现优先用 realized_today 记账。"""
    if row.get("error") or not _is_closed_trace_row(row, lots=lots, traces=traces):
        return
    code = _code_key(str(row.get("代码") or ""))
    sess = str(row.get("交易日") or "")[:10]
    book = load_holdings()
    realized_rec = (book.get("realized_today") or {}).get(code)
    if (
        isinstance(realized_rec, dict)
        and str(realized_rec.get("session") or "")[:10] == sess
        and realized_rec.get("reason") in EXIT_REASONS
    ):
        # 账本已有纸面卖出：必须打上「已实现」，否则 UI 今日平仓栏 / 账户合计都会漏掉
        row["已实现"] = True
        row["三槽平仓"] = True
        row["持仓"] = 0
        try:
            sold = int(realized_rec.get("qty") or 0)
        except (TypeError, ValueError):
            sold = 0
        if sold > 0:
            row["卖出数量"] = sold
        if realized_rec.get("price") is not None:
            row["成交价"] = realized_rec.get("price")
        if realized_rec.get("cost") is not None:
            row["成本"] = realized_rec.get("cost")
        if realized_rec.get("pnl") is not None:
            row["浮盈"] = realized_rec.get("pnl")
        if realized_rec.get("pnl_pct") is not None:
            row["浮盈%"] = realized_rec.get("pnl_pct")
        if realized_rec.get("day_pnl") is not None:
            row["当日盈亏"] = realized_rec.get("day_pnl")
            row["当日盈亏%"] = realized_rec.get("day_pnl_pct")
            row["当日基数"] = realized_rec.get("day_base")
        if not _is_stop_closed_status(str(row.get("持仓状态") or "")):
            row["持仓状态"] = STATUS_STOP_CLOSED
        _freeze_closed_exit_levels(row)
        _remember_slot_closed(row)
        return

    lot = (lots if lots is not None else _last_open_lots_from_trades()).get(code) or {}
    cost = lot.get("cost")
    try:
        cost_f = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_f = None
    if cost_f is None:
        cost_f = _as_money(row.get("成本"))
    try:
        qty_lot = int(lot.get("qty") or row.get("卖出数量") or 0)
    except (TypeError, ValueError):
        qty_lot = 0
    # 已实现成交：用记账股数，不要被 30 万×30% 纸面槽位覆盖
    if bool(row.get("已实现")):
        qty = qty_lot if qty_lot > 0 else int(row.get("卖出数量") or 0)
        if qty > 0:
            row["卖出数量"] = qty
        row["三槽平仓"] = True
        if row.get("当日盈亏") is not None:
            if row.get("成本") is None and cost_f is not None:
                row["成本"] = cost_f
            _freeze_closed_exit_levels(row)
            _remember_slot_closed(row)
            return
        qty_slot = 0
    else:
        # 无 realized_today 时不要用假槽位股数冒充三槽平仓（会漏「已实现」且盈亏错）
        qty_slot = 0
        qty = qty_lot
        if qty <= 0:
            return
    if qty <= 0:
        return
    bars = row.pop("_day_bars", None)
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        bars = _closed_1m_bars(row)
    path_fill = _closed_path_fill(row, cost=float(cost_f), bars=bars)
    fill = _closed_mark_px(row, cost=cost_f, bars=bars)
    if fill is None:
        open_px = _as_money(row.get("开盘"))
        existing = _as_money(row.get("成交价"))
        open_prot = _closed_open_protect_px(
            float(cost_f),
            _as_money(row.get("昨收")),
            overnight_high_ok=_row_overnight_high_ok(row),
        )
        if (
            existing is not None
            and open_px is not None
            and abs(float(existing) - float(open_px)) <= 1e-6
            and open_prot > 0
            and float(existing) > open_prot + 1e-12
        ):
            row["成交价"] = None
        return
    row["成交价"] = fill
    if path_fill is not None:
        row["止损"] = fill
    _freeze_closed_exit_levels(row)
    prev = _as_money(row.get("昨收"))
    open_px = _as_money(row.get("开盘"))
    lot_day = str(lot.get("time") or "")[:10]
    bought_today = bool(lot_day and sess and lot_day == sess)
    day_pnl, day_pct, day_base = session_day_pnl(
        mark=fill,
        qty=qty,
        cost=cost_f,
        prev_close=prev,
        bought_today=bought_today,
        fallback=open_px,
    )
    if day_pnl is None:
        return
    row["当日盈亏"] = day_pnl
    row["当日盈亏%"] = day_pct
    row["当日基数"] = day_base
    row["卖出数量"] = qty
    row["三槽平仓"] = True
    if row.get("成本") is None and cost_f is not None:
        row["成本"] = cost_f
    if cost_f is not None:
        upnl, upct = mark_unrealized(fill, cost_f, qty)
        row["浮盈"] = upnl
        row["浮盈%"] = upct
        row["盈亏状态"] = "结算"
        base_note = "买入价" if bought_today else "昨收"
        row["盈亏说明"] = (
            f"已平仓·相对{base_note}；槽位股数"
            if qty_slot > 0
            else f"已平仓·相对{base_note}"
        )
    _remember_slot_closed(row)


def _finalize_position_row(row: dict[str, Any]) -> None:
    """收敛持仓状态：已经买入 / 待卖出 / 已平仓；信号「已触止损」另见预警/角标。"""
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
        # 当日已平仓/禁买：持仓态「已平仓」；信号「已触止损」
        row["持仓状态"] = STATUS_STOP_CLOSED
        row["因子侧"] = "空仓"
        row["建议挂单"] = None
        row["近买点"] = False
        row["可执行"] = False
        row["bg_class"] = "status-flat"
        if alert in (
            "",
            "-",
            "空仓",
            "待买入",
            "当日禁买",
            "止损成交",
            "已平仓",
            "已触止损平仓",
        ) or (
            (bool(row.get("已实现")) or bool(row.get("三槽平仓")) or int(row.get("卖出数量") or 0) > 0)
            and alert.startswith("策略回放")
        ):
            row["预警"] = SIGNAL_STOP_HIT
        # 主展示价：保留上次买入触发价
        if row.get("已触发因子侧") == "买入" and row.get("已触发因子价") is not None:
            row["因子价"] = row["已触发因子价"]
        return

    if paper and qty <= 0:
        # 已触止损：禁止再标策略持有
        if (
            str(row.get("已触止损") or "") == "是"
            or "已触止损" in alert
            or "今日已止损" in alert
            or "策略回放·今日已止损" in alert
        ):
            row["策略回放持有"] = False
            row["持仓状态"] = STATUS_STOP_CLOSED
            row["因子侧"] = "空仓"
            row["建议挂单"] = None
            row["近买点"] = False
            row["可执行"] = False
            row["bg_class"] = "status-flat"
            if alert in ("", "-", "空仓", "待买入", "策略持有", "已触止损"):
                row["预警"] = "策略回放·今日已止损"
            return
        if _buy_signal_active(row):
            row["可执行"] = is_actionable_unfilled_buy(row) or alert.startswith(
                ALERT_HIT_BUY
            )
            if str(row.get("bg_class") or "") in ("", "status-hold", "status-flat"):
                row["bg_class"] = "warn-buy"
            if row.get("买点") is not None:
                row["因子价"] = row["买点"]
            return
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
                r = simple_return(last, stop_px)
                dist_pct = None if r is None else abs(r) * 100.0
                if dist_pct is not None and (
                    dist_pct <= float(NEAR_FACTOR_PCT) + 1e-12
                    or str(row.get("已触止损") or "") == "是"
                ):
                    near_stop = True
                    row["近止损"] = True
        except (TypeError, ValueError):
            pass
        row["bg_class"] = "warn-sell" if near_stop else "status-hold"
        return

    if qty > 0:
        sellable = int(row.get("可用") or 0)
        hit_stop = str(row.get("已触止损") or "") == "是"
        buy_time = row.get("买入时间")
        session = str(row.get("交易日") or "")
        t1_day = bool(
            session
            and buy_time
            and is_t1_buy_day(buy_time, session)
            and not bool(row.get("t0"))
        )
        # T+1 当日不可卖：三槽状态固定「已经买入」，不进待卖出/已止损
        if t1_day and sellable <= 0:
            row["持仓状态"] = "已经买入"
            row["可执行"] = False
            row["因子侧"] = "持有"
            if hit_stop:
                if "止损已记" not in alert and "持有·T+1" not in alert:
                    row["预警"] = "持有·T+1·止损已记"
                row["bg_class"] = "status-hold"
            else:
                if (
                    alert in ("", "-", "空仓", "待买入", "待卖出", "已触止损", "将止损", "已经买入")
                    or "已触止损" in alert
                    or alert.startswith("将止损")
                ):
                    row["预警"] = "持有·T+1"
                row["已触止损"] = "否"
                row["bg_class"] = "status-hold"
            return
        # 实仓：仅连续竞价可执行止损 →「待卖出」；
        # 竞价/开盘前即使已触也保持「已经买入」（预警字段另标竞价观察）。
        # 午休/收盘保留盘中已形成的待卖出展示。
        _ph = market_phase()
        _exec_ok = is_exit_executable() or _ph in ("lunch", "closed")
        if hit_stop and sellable > 0 and "不可卖" not in alert and not t1 and _exec_ok:
            row["持仓状态"] = "待卖出"
            pos = "待卖出"
        else:
            row["持仓状态"] = "已经买入"
            pos = "已经买入"
        row["可执行"] = (
            pos == "待卖出"
            and is_exit_executable()
            and (not t1)
            and sellable > 0
            and "不可卖" not in alert
        )
        if hit_stop and sellable <= 0 and "不可卖" not in alert and not t1:
            row["可执行"] = False
            if alert in (
                "",
                "-",
                "待卖出",
                "已触止损",
                "已经买入",
                "持有",
                ALERT_HIT_BUY,
                ALERT_FILLED,
            ) or alert.startswith("已触买"):
                row["预警"] = "已触止损·暂不可卖"
        elif (
            alert in ("", "-", "空仓", "待买入", ALERT_HIT_BUY, ALERT_FILLED)
            or alert.startswith("已触买")
        ) and pos == "已经买入":
            row["预警"] = "已经买入"
        row["因子侧"] = "持有" if pos == "已经买入" else row.get("因子侧") or "卖出"
        return

    # 真·空仓：保留 annotate 后的触买信号，勿冲回空仓（未过门不算触买）
    if alert.startswith("已触买·") and alert != ALERT_FILLED:
        row["持仓状态"] = "待买入"
        row["可执行"] = True
        row["bg_class"] = row.get("bg_class") or "warn-buy"
        return
    if ALERT_PRICE_NO_GATE in alert or alert.startswith("触买价"):
        # 废弃弱信号：恢复空仓，不预警
        row["预警"] = "空仓"
        row["持仓状态"] = "空仓"
        row["可执行"] = False
        row["近买点"] = False
        row["槽位候选"] = False
        row["当日预警"] = False
        if str(row.get("bg_class") or "") == "warn-buy":
            row["bg_class"] = ""
        return
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
    """策略一排序：实仓 → 当日留痕 → 槽位候选 → 其余按距买点升序（最近在前）。"""

    def _tier(r: dict[str, Any]) -> int:
        qty = int(r.get("持仓") or 0)
        if qty > 0:
            return 0
        if bool(r.get("已实现")):
            return 1
        if bool(r.get("槽位候选")):
            return 2
        return 3

    def _urgency(r: dict[str, Any]) -> int:
        hit = str(r.get("因子触发") or "")
        pos = str(r.get("持仓状态") or "")
        if pos == "待卖出" or hit.startswith("已触发") or hit.startswith("策略止损"):
            return 0
        if _row_hit_buy(r) or pos == "待买入":
            return 1
        if r.get("近买点") or r.get("近止损") or hit == "接近":
            return 2
        return 3

    def key(r: dict[str, Any]) -> tuple[int, int, float, str]:
        code = _code_key(str(r.get("代码") or ""))
        dist = r.get("距买点%")
        if dist is None:
            dist = _buy_distance_pct(r)
        try:
            dist_f = float(dist)
        except (TypeError, ValueError):
            dist_f = 9_999.0
        return (_tier(r), _urgency(r), dist_f, code)

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
    for r in show_rows:
        raw = next((x for x in rows if x["代码"] == r["代码"]), {})
        if r["当日盈亏"] != "-" and (
            int(raw.get("持仓") or 0) > 0 or raw.get("已实现")
        ):
            try:
                day_total += float(r["当日盈亏"])
                day_n += 1
            except (TypeError, ValueError):
                pass
    acc = _build_watch_account_summary(rows)
    if acc.get("totalPnl") is not None:
        start = acc.get("totalPnlStart") or PAPER_PNL_START
        print(
            f"总收益(自{start}): {acc['totalPnl']:+.2f}  "
            f"[总资产−纸面本金{acc.get('paperEquityBase')}]"
        )
    if day_n:
        print(f"今日盈亏: {day_total:+.2f}  [持仓+今日平仓]")
    else:
        print("今日盈亏: -")

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
    print("     当日盈亏: 今买=(现价或平仓价-买入价)×股数；昨仓=(现价或平仓价-昨收)×股数")
    print("     已平仓浮亏: 昨仓=(平仓价-昨收)×卖出股数；今买当日=(平仓价-成本)×股数；成交价锁定后不再随现价")
    print("     因子26卖出: 多层止盈；10%半仓止盈（减半留仓）；其余止损/止盈全清")
    print("     买入过滤: 前日阴/小阳 + 禁双阳跨日≥5%；T+1 当日不可卖")
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
    if old_qty <= 0:
        pos["tp_stage"] = 0
        pos["last_tp_ts"] = None
    if args.note:
        pos["note"] = args.note
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash - price * qty, 2)
    try:
        cash_after = (
            float(data.get("account_cash"))
            if data.get("account_cash") is not None
            else None
        )
    except (TypeError, ValueError):
        cash_after = None
    save_holdings(data)
    append_trade(
        {
            "time": _now(),
            "side": "buy",
            "code": code,
            "name": meta["name"],
            "market": meta.get("market") or "",
            "price": price,
            "qty": qty,
            "after_qty": new_qty,
            "avg_cost": pos["cost"],
            "cost": pos["cost"],
            "amount": round(price * qty, 2),
            "account_cash_after": cash_after,
            "session": str(_now())[:10],
            "reason": "买入入槽",
            "note": args.note or "手动买入",
            "reason_detail": args.note or "手动买入",
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
    pnl, pnl_pct = mark_unrealized(price, cost, qty)
    pnl = 0.0 if pnl is None else pnl
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
        pos["tp_stage"] = 0
        pos["last_tp_ts"] = None
    else:
        # 人工减半后必须落 stage，否则下一轮 1m 回放会在同一根 10% K 上清剩余
        pos["tp_stage"] = 1
        pos["last_tp_ts"] = _now()
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash + price * qty, 2)
    try:
        cash_after = (
            float(data.get("account_cash"))
            if data.get("account_cash") is not None
            else None
        )
    except (TypeError, ValueError):
        cash_after = None

    # 全清或半仓都写入当日已实现：禁同日再买；半仓后允许再卖剩余
    session = str(pd.Timestamp.now().date())
    note = args.note or ""
    _purge_stale_realized(data, session)
    if new_qty == 0:
        reason = REASON_STOP if "止损" in note else "手动卖出"
    else:
        reason = REASON_HALF
    bought_today = is_t1_buy_day(buy_time, session)
    day_pnl, day_pnl_pct, day_base = session_day_pnl(
        mark=price,
        qty=qty,
        cost=cost,
        prev_close=_prev_close_from_snapshot(code),
        bought_today=bool(bought_today),
        fallback=None if not bought_today else cost,
    )
    px_digits = 3 if abs(price) < 10 else 2
    rec_day_base = 0.0 if day_base is None else day_base
    rec_day_pnl = 0.0 if day_pnl is None else day_pnl
    data.setdefault("realized_today", {})[code] = {
        "session": session,
        "name": meta["name"],
        "market": meta["market"],
        "qty": int(qty),
        "price": round(price, px_digits),
        "cost": round(cost, 4),
        "pnl": round(pnl, 2),
        "pnl_pct": pnl_pct,
        "day_base": round(rec_day_base, 2),
        "day_pnl": round(rec_day_pnl, 2),
        "day_pnl_pct": day_pnl_pct,
        "reason": reason,
        "time": _now(),
        "after_qty": int(new_qty),
        "full_exit": bool(new_qty <= 0),
        "action_kind": "half" if new_qty > 0 else "full",
    }
    if new_qty == 0:
        pos["note"] = f"{reason}@{price} ({session})"
        append_slot_freed_at(data, session, _now())
    else:
        pos["note"] = f"{reason}@{price}×{qty} 剩{new_qty} ({session})"

    save_holdings(data)
    append_trade(
        {
            "time": _now(),
            "side": "sell",
            "code": code,
            "name": meta["name"],
            "market": meta.get("market") or "",
            "price": price,
            "qty": qty,
            "after_qty": new_qty,
            "cost": cost,
            "avg_cost": cost,
            "pnl": round(pnl, 2),
            "pnl_pct": pnl_pct,
            "day_pnl": round(rec_day_pnl, 2),
            "day_pnl_pct": day_pnl_pct,
            "amount": round(price * qty, 2),
            "account_cash_after": cash_after,
            "session": session,
            "action_kind": "half" if new_qty > 0 else "full",
            "buy_time": str(buy_time or "") or None,
            "reason": reason,
            "note": note or reason,
            "reason_detail": note or reason,
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
    """清仓并重置全部盯盘状态，便于当日重新执行默认策略三槽。

    · 全部 positions → 空仓；realized / alert_sticky / factor_memory 清空
    · strategy 纸面持有复位；portfolio_pool 对齐默认策略池
    · 当日 trades.jsonl 买卖行归档，避免「日最多买 / 当日禁买」挡住重跑
    · 账户总资产回到默认纸面资金；清内存缓存与微信防抖
    """
    from watch_config import (
        DEFAULT_ACCOUNT_TOTAL,
        prune_portfolio_pool,
        strategy_watchlist_codes,
    )

    global _HOLDINGS_CACHE

    data = load_holdings()
    sess = str(trading_session_date())
    # 1) 所有票空仓（含非当前池遗留代码）
    positions = data.setdefault("positions", {})
    for code, pos in list(positions.items()):
        name = ""
        market = "深证"
        if isinstance(pos, dict):
            name = str(pos.get("name") or "")
            market = str(pos.get("market") or market)
        meta = {"code": _code_key(code), "name": name or _code_key(code), "market": market}
        try:
            meta = _find_meta(code) if code else meta
        except Exception:  # noqa: BLE001
            pass
        positions[_code_key(code)] = _empty_position(meta)
    for w in effective_watchlist(data):
        positions[w["code"]] = _empty_position(w)

    for key in ("realized_today", "closed_today", "alert_sticky", "factor_memory"):
        reset_container(data, key, {})
    data["account_total"] = float(DEFAULT_ACCOUNT_TOTAL)
    data["account_cash"] = float(DEFAULT_ACCOUNT_TOTAL)
    data["account_total_open"] = float(DEFAULT_ACCOUNT_TOTAL)
    data["account_total_open_session"] = sess
    data["paper_equity_base"] = float(DEFAULT_ACCOUNT_TOTAL)
    data["paper_pnl_start"] = str(PAPER_PNL_START)[:10]
    data["daily_settlements"] = data.get("daily_settlements") or {}
    data["last_session"] = None
    data["watch_status_reset_session"] = sess

    # 策略纸面持有复位
    strat = data.get("strategy")
    if isinstance(strat, dict):
        for code, st in list(strat.items()):
            if isinstance(st, dict):
                st["holding"] = False
                st["buy_time"] = None
            else:
                strat[code] = {"holding": False, "buy_time": None}

    # 持仓池只留默认策略池
    data["portfolio_pool"] = sorted(strategy_watchlist_codes())
    prune_portfolio_pool(data)

    # 2) 当日成交行移出 trades.jsonl（保留历史），否则日买次数仍占满
    n_archived = 0
    if TRADES_FILE.exists():
        try:
            lines = TRADES_FILE.read_text(encoding="utf-8").splitlines()
            keep: list[str] = []
            archived: list[str] = []
            for line in lines:
                s = line.strip()
                if not s:
                    continue
                try:
                    rec = json.loads(s)
                except json.JSONDecodeError:
                    keep.append(line)
                    continue
                ts = str(rec.get("time") or rec.get("ts") or "")
                if ts.startswith(sess):
                    archived.append(s)
                else:
                    keep.append(s)
            if archived:
                stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
                arch = ROOT / f"trades_reset_{stamp}.jsonl"
                arch.write_text("\n".join(archived) + "\n", encoding="utf-8")
                n_archived = len(archived)
            TRADES_FILE.write_text(("\n".join(keep) + ("\n" if keep else "")), encoding="utf-8")
        except OSError as e:
            print(f"归档当日成交失败（继续）: {e}")

    save_holdings(data)
    _HOLDINGS_CACHE.clear()
    _ensure_signal_day_caches(force=True)
    try:
        from wechat_notify import STATE_FILE

        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception as e:  # noqa: BLE001
        print(f"清微信预警状态失败（继续）: {e}")
    try:
        import strategy_simulator

        strategy_simulator.reset_all_state()
    except Exception as e:  # noqa: BLE001
        print(f"清策略模拟账本失败（继续）: {e}")

    print(
        f"已清仓并重置全部状态 · session={sess} · "
        f"池 {len(data.get('portfolio_pool') or [])} 只 · "
        f"归档当日成交 {n_archived} 笔 · 账户 {DEFAULT_ACCOUNT_TOTAL:.0f}"
    )
    print(f"盯盘下一轮将按默认策略重新扫描入槽（日最多买 {int(MAX_BUYS_PER_DAY)}）。")

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
    include_strategy_panels: bool = True,
) -> tuple[Path, bool]:
    global _last_auction_skip_log
    rows = collect_rows(get_quote=get_quote)
    indices = fetch_indices_cached()
    path, published = publish_watch_snapshot(
        rows,
        indices=indices,
        refresh_sec=refresh_sec,
        get_quote=get_quote,
        fetch_sectors=False,
        include_strategy_panels=include_strategy_panels,
    )
    if wechat and is_signal_window():
        try:
            from wechat_notify import (
                notify_watch_rows,
                filter_default_strategy_alert_rows,
            )

            notify_rows = filter_default_strategy_alert_rows(rows)
            pushed = notify_watch_rows(notify_rows)
            if pushed:
                print(f"[{_now()}] 微信本轮推送 {len(pushed)} 条")
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 微信预警推送异常: {e}")
    elif wechat and is_auction_window():
        now_m = time.monotonic()
        if now_m - _last_auction_skip_log >= 60.0:
            _last_auction_skip_log = now_m
            ph = market_phase_label()
            print(f"[{_now()}] 早盘 {ph}；微信推送待 9:30 连续竞价")
    elif wechat:
        # 收盘后/午休：扫描不推；成交即时推送见 notify_trade_fill
        pass
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
    """下一早盘里程碑：(时刻, 标签, 动作 reseed|open|refresh)。

    跳过周六日（A 股休市）；与 ``trading_session_date`` 对齐。
    """
    now = now or datetime.now()
    candidates: list[tuple[datetime, str, str]] = []
    for h, m, label, action in AUCTION_MILESTONES:
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        # 落到下一交易日（跳过周末）
        while t.weekday() >= 5:
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
        rows,
        indices=indices,
        refresh_sec=refresh_sec,
        get_quote=get_quote,
        fetch_sectors=False,
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
    force: bool = False,
) -> None:
    """防止多个 watch 同时写快照，页面会来回跳变。"""
    from watch_process import (
        clear_lock,
        describe_listeners,
        read_lock,
        reclaim_ports,
        stop_watch,
    )

    ports = [int(port)]
    if ui_dev_port:
        ports.append(int(ui_dev_port))
    existing = read_lock()
    blocked = describe_listeners(host, ports)

    if force and (existing or blocked):
        stop_watch(
            api_port=int(port),
            ui_port=int(ui_dev_port or WATCH_UI_DEV_PORT),
            host=host,
            force=True,
        )
        existing = None
        blocked = describe_listeners(host, ports)

    if existing:
        old = int(existing.get("pid") or 0)
        if old and old != os.getpid():
            raise SystemExit(
                f"盯盘已在运行 (pid={old})。\n"
                f"请先运行: python start_watch.py --stop\n"
                f"或强制: python index.py watch --force / python start_watch.py --force"
            )

    clear_lock(only_if_stale=False)
    if blocked:
        reclaim_ports(list(blocked.keys()), host=host, force=True)
        blocked = describe_listeners(host, ports)
        if blocked:
            parts = [f":{p}→pid{'/'.join(str(x) for x in ps)}" for p, ps in blocked.items()]
            raise SystemExit(
                "端口仍被占用: " + ", ".join(parts) + "\n"
                "请运行: python start_watch.py --stop"
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
    no_ui_dev = bool(getattr(args, "no_ui_dev", False))
    env_dev = os.environ.get("WATCH_UI_DEV", "").strip().lower() in ("1", "true", "yes")
    if no_ui_dev or force_static:
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
        "encoding": "utf-8",
        "errors": "replace",
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
    session_for_open = _calendar_signal_session()
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


def cmd_watch_stop(_: argparse.Namespace) -> None:
    from watch_process import format_stop_report, stop_watch

    report = stop_watch(
        api_port=8765,
        ui_port=WATCH_UI_DEV_PORT,
        force=True,
    )
    print(format_stop_report(report))
    if report.get("remaining"):
        raise SystemExit(1)


def cmd_holdings_push(args: argparse.Namespace) -> None:
    from holdings_sync import push_holdings

    push_holdings(force=bool(getattr(args, "force", False)))


def cmd_holdings_pull(args: argparse.Namespace) -> None:
    from holdings_sync import pull_holdings

    global _HOLDINGS_CACHE
    result = pull_holdings(force=bool(getattr(args, "force", False)))
    _HOLDINGS_CACHE.clear()
    if result == "missing-remote":
        raise SystemExit(2)


def cmd_watch(args: argparse.Namespace) -> None:
    """长驻进程：东财 SSE/新浪兜底行情 + 本地 HTTP/WS 推页。

    默认与微信套件一体：先启动 OpenClaw Gateway → 微信自检 → 再盯盘。
    """
    import atexit

    atexit.register(_release_watch_lock)
    if not bool(getattr(args, "no_ledger_pull", False)):
        try:
            from holdings_sync import pull_holdings

            result = pull_holdings(quiet=False)
            if result == "pulled":
                _HOLDINGS_CACHE.clear()
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 远程持仓拉取失败（继续用本机账本）: {e}")
    global _ws_hub, _watch_feed
    interval = max(2, int(args.interval))
    host = str(args.host)
    port = int(args.port)
    use_ui_dev, ui_dev_port = _resolve_watch_ui_mode(args)
    ui_dev_proc: subprocess.Popen[str] | None = None
    wechat = not bool(getattr(args, "no_wechat", False))
    skip_wechat_check = bool(getattr(args, "skip_wechat_check", False))
    wechat_optional = bool(getattr(args, "wechat_optional", False))
    try:
        from wechat_notify import set_watch_wechat_enabled

        set_watch_wechat_enabled(wechat)
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] 微信运行时开关设置失败（继续）: {e}")

    def _run_wechat_prepare() -> bool:
        try:
            from wechat_notify import prepare_wechat_for_watch

            ok, detail = prepare_wechat_for_watch(
                restart_gateway=bool(getattr(args, "restart_gateway", False)),
                force_login=bool(getattr(args, "wechat_login", False)),
            )
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)
        if ok:
            print(f"[{_now()}] 微信套件就绪")
            return True
        print(f"[{_now()}] 微信套件失败:\n{detail[:600]}")
        if wechat_optional:
            # 通道「running」≠能发：prepare failed 时常因会话 token 过期。
            # 仍保持 wechat=True，盘中买卖/预警可在 token 恢复后发出；
            # 不要静默关掉推送（否则通道修好了也不发）。
            print(
                f"[{_now()}] --wechat-optional：继续盯盘并保留微信推送。"
                "请用微信给机器人发一条消息刷新会话；之后买卖/预警会自动推。"
            )
        return False

    # --wechat-optional（start_watch 默认）：OpenClaw/微信自检与行情、API 并行，
    # 不再挡在端口监听之前；严格模式仍同步，失败即中止。
    wechat_prepare_async = bool(wechat and not skip_wechat_check and wechat_optional)
    wechat_prepare_thread: threading.Thread | None = None
    if wechat and not skip_wechat_check:
        if not wechat_prepare_async:
            print("=" * 48)
            print("盯盘启动套件：OpenClaw → 微信自检 → 盯盘")
            print("=" * 48)
            if not _run_wechat_prepare():
                print(
                    "中止盯盘。修好通道后重试；或临时："
                    "watch --wechat-optional / --skip-wechat-check / --no-wechat"
                )
                raise SystemExit(1)
    elif wechat:
        try:
            from wechat_notify import start_wechat_delivery_worker

            start_wechat_delivery_worker()
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 微信投递 worker 启动失败（继续）: {e}")

    _acquire_watch_lock(
        host=host,
        port=port,
        ui_dev_port=ui_dev_port if use_ui_dev else None,
        force=bool(getattr(args, "force", False)),
    )
    if wechat_prepare_async:
        # 拿到锁之后再动 Gateway，避免抢占已在跑的实例
        print(f"[{_now()}] 盯盘启动套件：OpenClaw → 微信自检 后台并行（行情/API 不等待）")
        wechat_prepare_thread = threading.Thread(
            target=_run_wechat_prepare, name="wechat-prepare", daemon=True
        )
        wechat_prepare_thread.start()
    stop = threading.Event()
    refresh_lock = threading.Lock()
    ws_hub = LocalWsHub()
    _ws_hub = ws_hub

    from watch_config import MAX_SSE_QUOTES, primary_watchlist, strategy1_watchlist

    primary = primary_watchlist()
    s1_wl = strategy1_watchlist()
    # SSE 只挂热池；新浪批量 = 热池 ∪ 策略一（信号 Tab 需要对齐池名单）
    sinas_sse = [str(w["sina"]).lower() for w in primary][: int(MAX_SSE_QUOTES)]
    seen_s = set(sinas_sse)
    sinas_batch = list(sinas_sse)
    for w in s1_wl:
        s = str(w["sina"]).lower()
        if s in seen_s:
            continue
        seen_s.add(s)
        sinas_batch.append(s)
    feed = QuoteFeedManager(
        sinas_batch,
        sse_sinas=sinas_sse,
        on_log=lambda m: print(f"[{_now()}] {m}"),
        sina_interval=1.0,
    )
    _watch_feed = feed
    _WATCH_OVERLAY_READY.clear()
    print(
        f"[{_now()}] 行情分层: SSE热池 {len(sinas_sse)} 只"
        f"（帽 {MAX_SSE_QUOTES}）· 新浪批量 {len(sinas_batch)} 只"
        f"（含策略一）· 紫阳等大池独立轮询"
    )

    def get_quote(sina: str) -> dict[str, Any]:
        q = feed.get_quote(sina)
        if q is not None:
            return q
        # 盘前先垫昨收，避免新浪单只 8s×N 卡住首屏
        if market_phase() == "pre_auction":
            q = _quote_from_daily_prev(_watch_daily(sina))
            if q is not None:
                feed.seed(sina, q)
                return q
        q = fetch_today_quote_live(sina)
        feed.seed(sina, q)
        return q

    def reseed_live(
        watchlist: list[dict[str, Any]] | None = None,
        *,
        daily_fallback: bool = True,
    ) -> int:
        return _reseed_live_batch(feed, watchlist, daily_fallback=daily_fallback)

    def safe_refresh(*, include_strategy_panels: bool = True) -> tuple[Path, bool]:
        with refresh_lock:
            return _refresh_once(
                interval,
                get_quote=get_quote,
                wechat=wechat,
                include_strategy_panels=include_strategy_panels,
            )

    def safe_open_refresh() -> tuple[Path, bool]:
        with refresh_lock:
            reseed_live()
            return _refresh_open_prices(interval, get_quote=get_quote)

    def safe_auction_reset(*, only_if_due: bool = False) -> None:
        # 与扫描互斥：扫描中途被清空的账本状态会被扫描尾部整份写回（09-29 粘滞复活）
        with refresh_lock:
            if only_if_due:
                ensure_watch_status_reset_today()
            else:
                reset_watch_status_at_auction()

    def clock_heartbeat_loop() -> None:
        while not stop.is_set():
            if stop.wait(2.0):
                break
            try:
                _heartbeat_watch_clock()
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 时钟心跳失败: {e}")

    def sectors_live_loop() -> None:
        while not stop.is_set() and not _WATCH_FRONT_READY.is_set():
            if stop.wait(0.25):
                return
        if stop.is_set():
            return
        print(f"[{_now()}] 板块轮动：盯盘已就绪，开始后台加载")
        while not stop.is_set():
            try:
                publish_sectors_live_patch()
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 板块实时刷新失败: {e}")
            if stop.wait(5.0):
                break

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
                _, published = safe_refresh(
                    include_strategy_panels=_watch_include_strategy_panels()
                )
                if published:
                    _log_watch_snapshot_push(
                        f"[{_now()}] 快照已推送 → {WATCH_META_FILE.name}",
                    )
            except Exception as e:
                print(f"[{_now()}] 更新失败: {e}")

    def quote_patch_loop() -> None:
        """现价/涨跌幅快刷：不跑 collect_rows，跟 SSE/新浪 tick 走。"""
        last = 0.0
        while not stop.is_set():
            feed.wait_update(timeout=1.0)
            if stop.is_set():
                break
            wait_more = _QUOTE_PATCH_MIN_SEC - (time.monotonic() - last)
            if wait_more > 0 and stop.wait(wait_more):
                break
            last = time.monotonic()
            try:
                publish_live_quote_patch()
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 行情快刷异常: {e}")

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
                    safe_auction_reset()
                    try:
                        _daily_cache_warm(force=True)
                    except Exception as e:  # noqa: BLE001
                        print(f"[{_now()}] 9:15 日线重拉失败（继续）: {e}")
                    reseed_live()
                    safe_refresh()
                    print(
                        f"[{_now()}] 早盘节点 · {label} · "
                        "状态重置 + 昨仓今日盈亏按昨收重算"
                    )
                elif action == "open":
                    safe_open_refresh()
                    print(f"[{_now()}] 早盘节点 · {label}")
                else:
                    safe_refresh()
                    print(f"[{_now()}] 早盘节点 · {label}")
            except Exception as e:
                print(f"[{_now()}] 早盘节点失败 [{label}]: {e}")

    worker = threading.Thread(target=loop, name="holdings-watch", daemon=True)
    quote_patch_worker = threading.Thread(
        target=quote_patch_loop, name="holdings-quote-patch", daemon=True
    )
    milestone_worker = threading.Thread(
        target=auction_milestone_loop, name="holdings-auction-milestones", daemon=True
    )
    heartbeat_worker = threading.Thread(
        target=clock_heartbeat_loop, name="holdings-clock-heartbeat", daemon=True
    )
    sectors_worker = threading.Thread(
        target=sectors_live_loop, name="holdings-sectors-live", daemon=True
    )

    from transport.http import build_watch_request_handler

    def _get_last_snap() -> Any:
        return _last_watch_snapshot

    _Handler = build_watch_request_handler(
        root=ROOT,
        watch_meta_file=WATCH_META_FILE,
        watch_ui_dist=WATCH_UI_DIST,
        ws_hub=ws_hub,
        snap_lock=_WATCH_SNAP_LOCK,
        get_last_snapshot=_get_last_snap,
        get_strategies_api=_get_strategies_api_cache,
        get_factors_api=_get_factors_api_cache,
        handle_strategy16b_api=_handle_strategy16b_api,
        handle_sectors_api=_handle_sectors_api,
        watch_ui_dist_ready=_watch_ui_dist_ready,
    )

    _seed_boot_watch_snapshot()
    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        feed.stop()
        _ws_hub = None
        _watch_feed = None
        _release_watch_lock()
        raise SystemExit(
            f"端口 {host}:{port} 无法绑定（可能已有盯盘在跑）。\n"
            f"请先停掉旧进程再启动，避免抢写报告。\n{e}"
        ) from e
    http_thread = threading.Thread(
        target=server.serve_forever, name="watch-http", daemon=True
    )
    http_thread.start()
    heartbeat_worker.start()
    sectors_worker.start()
    url = _watch_browser_url(
        host=host,
        api_port=port,
        ui_dev_port=ui_dev_port if use_ui_dev else None,
    )
    print(f"盯盘 API 已启动: http://{host}:{port}/")
    print("冷启动放到后台：新浪批量 + 预热日线 + 东财 SSE（页面可先连上）")

    def _warm_reference_data() -> None:
        try:
            from stock_names import warm_name_cache

            n_names = warm_name_cache()
            print(f"[{_now()}] 股票名称缓存后台预热完成（{n_names} 条）")
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 名称缓存后台预热失败（继续）: {e}")
        try:
            from stock_profile import warm_profile_index

            n_rev = warm_profile_index()
            print(f"[{_now()}] 个股画像板块反查后台预热完成（{n_rev} 只）")
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 个股画像后台预热失败（继续）: {e}")

    def _watch_cold_boot() -> None:
        threading.Thread(
            target=_warm_reference_data, name="watch-reference-warmup", daemon=True
        ).start()
        # 分层冷启动：首屏只扫持仓，随后默认策略，最后策略一池/其它面板后台补齐。
        # 必须在 worker 启动前置位，否则 loop 首轮就会全量串行拉日线。
        _set_watch_boot_stage("holdings")
        # 先起刷新线程 + 行情源：日线预热常因缺 panda_data/网络挂住，
        # 若堵在 feed.start() 之前，worker 一直 wait_update，快照永不更新。
        if not worker.is_alive():
            worker.start()
        if not quote_patch_worker.is_alive():
            quote_patch_worker.start()
        if not milestone_worker.is_alive():
            milestone_worker.start()
        print("冷启动：先上持仓首屏，再加载默认策略，最后异步补齐其它策略")
        feed_started = False

        try:
            safe_auction_reset(only_if_due=True)
            t0 = time.perf_counter()
            # 启动强制清缓存放最前：原先放在首屏之后，热池日线会被拉两遍
            _ensure_signal_day_caches(force=True)
            holdings_meta = load_holdings()
            holdings_first = _holding_watchlist(holdings_meta)
            feed.start()
            feed_started = True
            n_holdings = 0
            with ThreadPoolExecutor(max_workers=2) as pool:
                live_f = pool.submit(reseed_live, holdings_first, daily_fallback=False)
                daily_f = pool.submit(_daily_cache_warm, holdings_first, force=True)
                try:
                    n_holdings = int(live_f.result() or 0)
                except Exception as e:  # noqa: BLE001
                    print(f"[{_now()}] 持仓新浪快照 seed 失败（继续按票补拉）: {e}")
                try:
                    daily_f.result()
                except Exception as e:  # noqa: BLE001
                    print(f"[{_now()}] 持仓日线预热失败（继续按票补拉）: {e}")
            report, _ = safe_refresh(include_strategy_panels=False)
            elapsed = time.perf_counter() - t0
            _log_watch_snapshot_push(
                f"持仓首屏已推送: {report}（持仓 {n_holdings}/{len(holdings_first)} 只 · {elapsed:.1f}s）",
                force=True,
            )
            _set_watch_boot_stage("primary")
            t_primary = time.perf_counter()
            primary = primary_watchlist(load_holdings())
            primary_rest = [
                w
                for w in primary
                if _code_key(w["code"]) not in {_code_key(x["code"]) for x in holdings_first}
            ]
            n_primary = 0
            if primary_rest:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    live_f = pool.submit(reseed_live, primary_rest, daily_fallback=False)
                    daily_f = pool.submit(_daily_cache_warm, primary_rest, force=True)
                    try:
                        n_primary = int(live_f.result() or 0)
                    except Exception as e:  # noqa: BLE001
                        print(f"[{_now()}] 默认策略新浪快照 seed 失败（继续按票补拉）: {e}")
                    try:
                        daily_f.result()
                    except Exception as e:  # noqa: BLE001
                        print(f"[{_now()}] 默认策略日线预热失败（继续按票补拉）: {e}")
            report1, _ = safe_refresh(include_strategy_panels=False)
            _log_watch_snapshot_push(
                f"默认策略快照已推送: {report1}（新增 {n_primary}/{len(primary_rest)} 只 · {time.perf_counter() - t_primary:.1f}s）",
                force=True,
            )
            # 叠加池：后台独立轮询，不挡首屏、不进 collect_rows
            try:
                from strategy17_watch import start_overlay_poller

                start_overlay_poller(
                    stop=stop,
                    on_log=lambda m: print(f"[{_now()}] {m}"),
                )
                _WATCH_OVERLAY_READY.set()
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 叠加池轮询未启动（继续）: {e}")
                _WATCH_OVERLAY_READY.set()
            try:
                t1 = time.perf_counter()
                primary_codes = {_code_key(w["code"]) for w in primary}
                rest = [
                    w
                    for w in _scan_watchlist(full=True)
                    if _code_key(w["code"]) not in primary_codes
                ]
                print(
                    f"[{_now()}] 后台补齐策略一池 {len(rest)} 只"
                    f"（session={trading_session_date()} · "
                    f"已收盘日线截至 {latest_completed_weekday()}）…"
                )
                if rest:
                    # 先并行预热：reseed 缺新浪快照时逐只 _watch_daily 垫昨收
                    _daily_cache_warm(rest, force=True)
                    reseed_live(rest)
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 策略一池补齐失败（并入后按票补拉）: {e}")
            finally:
                _set_watch_boot_stage("full")
            report2, _ = safe_refresh()
            _log_watch_snapshot_push(
                f"全量快照已推送: {report2}（补齐 {time.perf_counter() - t1:.1f}s）",
                force=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] 首次更新失败（API 已就绪，继续后台刷新）: {e}")
            _set_watch_boot_stage("full")
            _WATCH_OVERLAY_READY.set()
            if not feed_started:
                try:
                    feed.start()
                    feed_started = True
                except Exception as e2:  # noqa: BLE001
                    print(f"[{_now()}] 行情源启动失败: {e2}")
        if stop.is_set():
            return
        if not worker.is_alive():
            worker.start()
        if not quote_patch_worker.is_alive():
            quote_patch_worker.start()
        if not milestone_worker.is_alive():
            milestone_worker.start()

    threading.Thread(
        target=_watch_cold_boot, name="watch-cold-boot", daemon=True
    ).start()
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
    elif bool(getattr(args, "no_ui_dev", False)):
        print("前端: 由 start_watch / 外部 Nuxt 提供 http://127.0.0.1:3000/")
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
        "行情: 热池（持仓+默认策略，≤48）SSE+新浪；"
        "叠加观察池（紫阳等，可至数百只）独立新浪分块轮询、不进信号扫描/不挡启动；"
        "因子26 实仓 1m path-dependent 止损 · "
        f"现价快刷≥{_QUOTE_PATCH_MIN_SEC:.1f}s · "
        f"信号扫描节流≥{_MIN_WATCH_REFRESH_SEC:.0f}s · 无推送保底 {interval}s · "
        "时钟心跳 2s · 板块在盯盘首屏之后后台加载 · "
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

        def _send_wechat_startup() -> None:
            if wechat_prepare_thread is not None:
                wechat_prepare_thread.join()
            try:
                from wechat_notify import send_startup_message

                ok, detail = send_startup_message(url=url)
                if ok:
                    print(f"[{_now()}] 微信启动通知已推送")
                else:
                    print(f"[{_now()}] 微信启动通知失败: {detail[:200]}")
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 微信启动通知异常: {e}")

        threading.Thread(
            target=_send_wechat_startup, name="wechat-startup-msg", daemon=True
        ).start()
    if not args.no_open:
        webbrowser.open(url)
    try:
        while not stop.wait(1.0):
            pass
    except KeyboardInterrupt:
        print("\n已停止盯盘")
    finally:
        stop.set()
        try:
            from wechat_notify import stop_wechat_delivery_worker

            stop_wechat_delivery_worker()
        except Exception:  # noqa: BLE001
            pass
        feed.stop()
        _ws_hub = None
        _watch_feed = None
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
        "--no-ui-dev",
        action="store_true",
        help="不在 watch 进程内启动 Nuxt（start_watch.py 会自己开前端）",
    )
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
        help="关闭微信（预警与买卖成交都不推；不影响 paper execution）",
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
    w.add_argument(
        "--wechat-login",
        action="store_true",
        help="启动前强制 openclaw channels login --channel openclaw-weixin（交互扫码）",
    )
    w.add_argument(
        "--force",
        action="store_true",
        help="强制停止旧实例并回收端口后启动（Windows Ctrl+C 遗留进程时有用）",
    )
    w.add_argument(
        "--no-ledger-pull",
        action="store_true",
        help="启动时不拉取 origin/holdings-ledger（离线或本机为准）",
    )
    w.set_defaults(func=cmd_watch)

    ws = sub.add_parser(
        "watch-stop",
        help="停止盯盘并释放 8765/3000 端口",
    )
    ws.set_defaults(func=cmd_watch_stop)

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

    ca = sub.add_parser(
        "clear-all",
        help="清仓并重置全部状态（含当日成交归档），便于重新执行策略三槽",
    )
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

    hp = sub.add_parser(
        "holdings-push",
        help="把本机 holdings.json/trades.jsonl 推到 origin/holdings-ledger（Win↔Mac）",
    )
    hp.add_argument(
        "--force",
        action="store_true",
        help="即使远程更新也覆盖推送",
    )
    hp.set_defaults(func=cmd_holdings_push)

    hl = sub.add_parser(
        "holdings-pull",
        help="拉取远程账本并丢掉本机 holdings_watch.json 旧缓存",
    )
    hl.add_argument(
        "--force",
        action="store_true",
        help="即使本机更新也覆盖为远程",
    )
    hl.set_defaults(func=cmd_holdings_pull)
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
