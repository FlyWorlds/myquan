"""持仓记录与盯盘：与默认核心策略（strategy16）同步。

策略锁定 · 策略十六：
  · 买（因子26）：开盘阈值 ceil(open×(1+entry))；前日阴/小阳；禁双阳；T+1
  · 卖（因子26）：硬保护2.5%；中赚3–10%回落一半与0.5×20日日频σ谁先到走谁；阶梯10%/15%；未到3%次日峰值回落2.5%；1 分钟 path-dependent
  · 因子2：账户回撤加减仓预警（不自动改现金）
  · 因子22：收盘动量路径保留研究；**三槽执行：当日止损/已记卖出的标的当日禁再买**
  · **仓位**：物理 3 槽（盘中/隔夜均可持 3）；当日最多买 3；**先平再买**；平仓前已触买且现价≤买点+1% 优先（成交价=现价），否则其后新触发按时间（成交价=买点）
  · 9:15 清空非实仓盯盘状态；**9:15–9:25 竞价不算买卖/动态止盈**；9:25 起算阈值并可挂单；9:30 起触发结算
  · 策略回放触止损 → 信号「已触止损」；有纸面持有则收敛为空仓/已平仓侧（不再「策略持有」）；当日已卖出该票不可再待买入
  · 默认交易宇宙：因子27 选股池 ∪ **公共自选池**（天通/凯盛/东材/金安，全策略共用，见 watch_config.SELF_WATCHLIST_PICKS）
  · 可选切策略七：watch_config.USE_FACTOR4=True + S7_WATCHLIST
  · 运行时分叉：本文件 collect_rows() **不**调用 get_decision_engine()；
    registry/bindings 供回测。改 bindings 后须同步本文件 FACTOR_ID 分支
    （levels / signal / replay / first_session_exit_fill）。

功能：
  · 拉取当日实时行情（东财 SSE + 新浪批量；全池不串行拉历史分钟）
  · 因子26 实仓：按成本+持仓峰值算动态止盈价；1 分钟顺序判触达
  · 阈值与信号：因子26 多层止盈（与 pullback_wave_stop 同源）
  · 因子2 与 strategy/dd_alert 同源
  · 有仓：动态止盈触达自动结算；**阶梯 10% 减半**（持仓记 tp_stage + last_tp_ts，半仓后从触达分钟下一根继续盯 15%/峰值回落）。不接券商，本地只记信号与纸面数量。
  · **信号≠入槽**：触买预警见 `watch_buy_signal.py`（须过门）；槽满仍发「已触买·槽满」；未过门不算触买、不预警；自动入槽才是成交
  · 本地 JSON 记录持仓（含 peak_high）；T+1 买入日不可卖

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

from quote_feed import (
    LocalWsHub,
    QuoteFeedManager,
    fetch_sina_batch,
    fill_preopen_ohlc,
    ws_accept_key,
    ws_pack_text,
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
    path_dependent_buy_hit,
    path_dependent_pullback_hit,
    pnl_exceeds,
    pullback_stop_price,
    realized_vol_daily,
    replay_factor26_1m,
    replay_last_factor_triggers as _replay_f26,
    resolve_t1_overnight_note,
    stop_note_invalidated_by_recovery,
    strategy_levels as _levels_f26,
    strategy_signal as _signal_f26,
    t1_trail_stop_px,
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
    USE_FACTOR4,
    WATCHLIST,
    effective_watchlist,
    normalize_signal_session,
    trading_session_date,
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
    RESERVE_EMPTY_SLOTS,
    SLOT_WEIGHT,
    DEFAULT_ACCOUNT_TOTAL,
    SLOT_FIRST_TIER_MAX_OVERSHOOT,
    free_slot_count,
    free_buy_slot_count,
    is_reserve_slot_window,
    occupied_slot_codes,
    slot_meta as _slot_meta_from_holdings,
    slot_fill_decision,
    peek_slot_freed_at,
    append_slot_freed_at,
    pop_slot_freed_at,
)
from watch_snapshot import (
    SNAPSHOT_VERSION,
    apply_feed_health,
    build_watch_snapshot,
    retain_last_snapshot,
    should_keep_last_snapshot,
)
from watch_buy_signal import (
    ALERT_FILLED,
    ALERT_HIT_BUY,
    ALERT_NOT_SLOTTED,
    ALERT_PRICE_NO_GATE,
    ALERT_SLOT_FULL,
    annotate_unfilled_buy_signals as _annotate_buy_signals_core,
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

# 止损已平仓展示态（旧文案「已止损」仍兼容识别）
# 持仓态：止损后已平仓（与信号「已触止损」分离）
STATUS_STOP_CLOSED = "已平仓"
_STOP_CLOSED_STATUSES = frozenset(
    {STATUS_STOP_CLOSED, "已止损", "已触止损平仓"}  # 后两者兼容旧文案
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
_last_watch_snapshot: dict[str, Any] | None = None
_last_snapshot_digest: str | None = None
_HOLDINGS_CACHE: dict[str, Any] = {"data": None, "mtime": 0.0}
_REPLAY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_STRATEGY_PNL_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
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
WATCH_LIVE_TAB_IDS = frozenset({"strategy1", "strategy3", "strategy8", "strategy15", "strategy16"})

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
        if spec.id == "strategy15":
            tabs[-1]["reportPath"] = "docs/STRATEGY.md"
        if spec.id == "strategy16":
            tabs[-1]["reportPath"] = "docs/FACTOR27.md"
        from strategy_picks_loader import load_strategy_picks

        tabs[-1]["picks"] = load_strategy_picks(spec.id)
    tabs.sort(
        key=lambda t: (
            0 if t.get("is_watch_default") else 1,
            int(_strategy_tab_number(str(t["id"]))),
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


def _row_counts_in_watch_pnl(row: dict[str, Any]) -> bool:
    """账户今日/合计：实仓 + 已实现成交 + 当日三槽平仓。"""
    if row.get("error"):
        return False
    try:
        qty = int(row.get("持仓") or 0)
    except (TypeError, ValueError):
        qty = 0
    return qty > 0 or bool(row.get("已实现")) or bool(row.get("三槽平仓"))


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
    closed_extra = 0.0
    has_pos = False
    has_day = False
    for r in rows:
        qty = int(r.get("持仓") or 0)
        realized = bool(r.get("已实现"))
        slot_closed = bool(r.get("三槽平仓"))
        in_pnl = _row_counts_in_watch_pnl(r)
        if r.get("浮盈") is not None and in_pnl:
            total_pnl += float(r["浮盈"])
            has_pos = True
        if r.get("当日盈亏") is not None and in_pnl:
            total_day_pnl += float(r["当日盈亏"])
            has_day = True
            db = r.get("当日基数")
            if db is not None and float(db) > 0:
                total_day_base += float(db)
            else:
                dpct = r.get("当日盈亏%")
                if dpct is not None and abs(float(dpct)) > 1e-12:
                    total_day_base += float(r["当日盈亏"]) / (float(dpct) / 100.0)
                elif r.get("市值") is not None and qty > 0:
                    total_day_base += float(r["市值"]) - float(r["当日盈亏"])
                elif slot_closed:
                    prev = _as_money(r.get("昨收"))
                    open_px = _as_money(r.get("开盘"))
                    base_px = prev if prev is not None and prev > 0 else open_px
                    try:
                        sold = int(r.get("卖出数量") or 0)
                    except (TypeError, ValueError):
                        sold = 0
                    if base_px is not None and base_px > 0 and sold > 0:
                        total_day_base += float(base_px) * sold
        if realized or slot_closed:
            settled_n += 1
            if r.get("浮盈") is not None:
                settled_pnl += float(r["浮盈"])
            if r.get("当日盈亏") is not None:
                settled_day += float(r["当日盈亏"])
            if r.get("成本") is not None and r.get("卖出数量"):
                total_cost += float(r["成本"]) * int(r["卖出数量"])
            if slot_closed and not realized and r.get("浮盈") is not None:
                closed_extra += float(r["浮盈"])
        if r.get("市值") is not None and qty > 0:
            mv = float(r["市值"])
            total_mv += mv
            if r.get("成本额") is None:
                total_mv_no_cost += mv
        if r.get("成本额") is not None and qty > 0:
            total_cost += float(r["成本额"])
    total_pnl_pct = (
        round(total_pnl / total_cost * 100.0, 2) if total_cost > 0 else None
    )
    total_day_pct = (
        round(total_day_pnl / total_day_base * 100.0, 2)
        if has_day and total_day_base > 0
        else None
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
        "dayPnl": round(total_day_pnl, 2) if has_day else None,
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
        "strategy8": (
            {k: v for k, v in snapshot["strategy8"].items() if k != "themeUpdatedAt"}
            if isinstance(snapshot.get("strategy8"), dict)
            else snapshot.get("strategy8")
        ),
        "strategy15": snapshot.get("strategy15"),
        "strategy16": snapshot.get("strategy16"),
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
    session_today = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        "",
    )
    from strategy3_watch import build_strategy3_payload
    from strategy8_watch import build_strategy8_payload

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
    sectors = _sectors_for_snapshot(fetch_sectors=fetch_sectors)
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
            "max": 3,
            "weight": 0.3,
            "occupied": [],
            "occupiedCount": 0,
            "free": 3,
        },
        "indices": [],
        "holdings": [],
        "strategy1": [],
        "strategy3": {},
        "strategy8": {},
        "strategy15": {},
        "strategy16": [],
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
    day_chg = price_chg_pct(last, prev)
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
    return {
        "session": str(pd.Timestamp.now().date()),
        "open": close,
        "high": close,
        "low": close,
        "last": close,
        "prev_close": close,
        "day_chg_pct": 0.0,
        "last_ts": f"{date} 15:00:00" if date else _now(),
        "name": "",
        "_day_bars": pd.DataFrame(),
        "_quote_source": "daily_prev",
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
    # 盘前新浪/批量失败时用已预热日线昨收垫上，避免 collect_rows 逐只 8s 超时
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
) -> int:
    """刷新当日实时快照（新浪批量）。"""
    return _reseed_sina_batch(feed, watchlist)


def _daily_cache_warm(
    watchlist: list[dict[str, Any]] | None = None, *, force: bool = False
) -> None:
    """并行预热日线缓存，避免首屏 collect_rows 串行等 IO。"""
    items = watchlist if watchlist is not None else effective_watchlist()
    with ThreadPoolExecutor(max_workers=4) as pool:
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
    today = str(pd.Timestamp.now().date())
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
    row["策略起算"] = STRATEGY_PNL_START
    if row.get("error") or not q.get("session"):
        row["策略收益%"] = None
        row["策略收益"] = None
        return
    rec = _strategy_pnl_since_cached(
        w["sina"],
        daily,
        q=q,
        code=str(w["code"]),
        entry_pct=entry_pct,
        stop_pct=stop_pct,
        tick=tick,
        prev_entry_mode=prev_entry_mode,
        limit_down_pct=limit_down_pct,
    )
    row["策略收益%"] = rec.get("return_pct")
    row["策略收益"] = rec.get("pnl")


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
            "closed_today": {},
        }
        save_holdings(data)
        return data
    with HOLDINGS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    positions = data.setdefault("positions", {})
    for w in effective_watchlist():
        positions.setdefault(w["code"], _empty_position(w))
    data.setdefault("realized_today", {})
    data.setdefault("closed_today", {})
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


def _ensure_account_open_session(
    data: dict[str, Any],
    *,
    session: str,
    account_total: float | None,
) -> None:
    """跨日或首次：锁定日初总资产。有实仓时禁止把「仅现金」写成日初。"""
    open_session = str(data.get("account_total_open_session") or "")
    existing = _account_total_open(data)
    if open_session == session and existing is not None:
        if _equity_is_cash_only(data, existing):
            data["account_total_open"] = round(float(DEFAULT_ACCOUNT_TOTAL), 2)
            save_holdings(data)
        return
    if account_total is None or account_total <= 0:
        return
    if _equity_is_cash_only(data, account_total):
        return
    data["account_total_open"] = round(float(account_total), 2)
    data["account_total_open_session"] = session
    save_holdings(data)


def heal_watch_ledger(*, session: str | None = None) -> dict[str, Any]:
    """每轮自愈：隔夜解锁、修复仅现金日初、清掉非法「止损已记」。不改 qty / 成本 / 买入时间。"""
    data = load_holdings()
    sess = normalize_signal_session(session or trading_session_date())
    changed = unlock_overnight_available(data, sess)
    if purge_illegal_t1_stop_notes(data) > 0:
        changed = True
    existing = _account_total_open(data)
    if _equity_is_cash_only(data, existing):
        data["account_total_open"] = round(float(DEFAULT_ACCOUNT_TOTAL), 2)
        if not data.get("account_total_open_session"):
            data["account_total_open_session"] = sess
        changed = True
    q = data.get("slot_queue")
    if not isinstance(q, dict) or str(q.get("session") or "")[:10] != str(sess)[:10]:
        data["slot_queue"] = {"session": str(sess)[:10], "freed_at": []}
        changed = True
    if changed:
        save_holdings(data)
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
    data["alert_sticky"] = kept
    save_holdings(data)


def reset_watch_status_at_auction(*, session: str | None = None) -> dict[str, Any]:
    """每日 9:15：清空非实仓盯盘状态，只保留 qty>0 持仓。

    · 清 alert_sticky / 非当日 realized / 回放与策略收益缓存
    · 清日线相关缓存并在后续预热中按最新交易日重拉（过门/前日）
    · 清微信预警防抖状态（当日重新推）
    · 标记 watch_status_reset_session，持仓 Tab 在 9:30 前仅展示实仓
    """
    data = load_holdings()
    sess = normalize_signal_session(session)
    _purge_stale_realized(data, sess)
    data["alert_sticky"] = {}
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


def _sticky_put(
    sticky: dict[str, Any],
    code: str,
    session: str,
    payload: dict[str, Any],
) -> None:
    """写粘滞时保留当日 buy_touched / stop_touched，避免卖出防抖把已触买抹掉。"""
    prev = sticky.get(code) if isinstance(sticky.get(code), dict) else {}
    if not isinstance(prev, dict):
        prev = {}
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
    prev = sticky.get(code) if isinstance(sticky.get(code), dict) else {}
    payload: dict[str, Any] = {"buy_touched": True}
    if not (isinstance(prev, dict) and prev.get("buy_hit_ts")):
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
    prev = sticky.get(code) if isinstance(sticky.get(code), dict) else {}
    payload: dict[str, Any] = {"stop_touched": True}
    if touch_stop:
        payload["touch_stop"] = float(touch_stop)
    forced = str(force_ts or "").strip()
    old_ts = prev.get("stop_hit_ts") if isinstance(prev, dict) else None
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


def _demote_pre_signal_window(sig: dict[str, Any]) -> dict[str, Any]:
    """9:30 连续竞价前：9:25 起可挂单预览，禁止『已触发』记账/结算。"""
    out = dict(sig)
    out["hit_buy"] = False
    out["hit_stop"] = False
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
        if "可挂单" not in note:
            out["挂单说明"] = (
                (note + "；" if note else "") + "9:25 可挂单；9:30 起才计已触发"
            )
    elif alert == "已触止损" or alert.startswith("已触止损"):
        out["alert"] = "将止损"
        out["pending_sell"] = True
        out["near_stop"] = True
        out["bg_class"] = out.get("bg_class") or "warn-sell"
        out["持仓状态"] = "待卖出"
        out["因子触发"] = "接近"
        note = str(out.get("挂单说明") or "")
        if "可挂单" not in note:
            out["挂单说明"] = (
                (note + "；" if note else "") + "9:25 可挂单；9:30 起才结算止损"
            )
    elif alert == "半仓止盈" or alert.startswith("半仓止盈"):
        out["alert"] = "将半仓"
        out["pending_sell"] = True
        out["near_stop"] = True
        out["bg_class"] = out.get("bg_class") or "warn-sell"
        out["持仓状态"] = "待卖出"
        out["因子触发"] = "接近"
        note = str(out.get("挂单说明") or "")
        if "可挂单" not in note:
            out["挂单说明"] = (
                (note + "；" if note else "") + "9:25 可挂单；9:30 起才结算半仓"
            )
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
    data["updated_at"] = _now()
    from holdings_sync import current_host

    data["updated_host"] = current_host()
    with HOLDINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _HOLDINGS_CACHE["data"] = data
    _HOLDINGS_CACHE["mtime"] = _holdings_file_mtime()


def _purge_stale_realized(data: dict[str, Any], session: str) -> None:
    """清除非当日已实现记录 / 三槽平仓留痕，避免隔日污染合计。"""
    realized = data.setdefault("realized_today", {})
    stale = [k for k, v in realized.items() if str(v.get("session") or "") != session]
    for k in stale:
        del realized[k]
    traces = data.get("closed_today")
    if isinstance(traces, dict):
        data["closed_today"] = {
            k: v
            for k, v in traces.items()
            if isinstance(v, dict) and str(v.get("session") or "") == session
        }
    q = data.get("slot_queue")
    if not isinstance(q, dict) or str(q.get("session") or "")[:10] != str(session)[:10]:
        data["slot_queue"] = {"session": str(session)[:10], "freed_at": []}


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
) -> dict[str, Any]:
    """纸面自动入仓：写 qty/成本/buy_time；扣减 account_cash（若有）。

    buy_time 用触发时刻（1m 触达或 5s 行情 last_ts），不是进程扫到的现在。
    成交价：新触发=买点；平仓前已触买的第一梯队=现价（不得超过买点 +1%）。
    """
    price = float(price)
    qty = int(qty)
    if qty <= 0 or price <= 0:
        raise ValueError("价格/数量必须 > 0")
    data = load_holdings()
    pos = data["positions"].setdefault(code, _empty_position(meta))
    old_qty = int(pos.get("qty") or 0)
    if old_qty > 0:
        return pos
    pos["qty"] = qty
    pos["cost"] = round(price, 4)
    pos["today_cost"] = round(price, 4)
    pos["peak_high"] = round(price, 4)
    pos["available"] = 0
    raw_ts = str(buy_time or "").strip()
    if raw_ts.startswith("9999"):
        raw_ts = ""
    hit_ts = _bar_ts_str(raw_ts) if raw_ts else None
    hit_ts = hit_ts or _now()
    pos["buy_time"] = hit_ts
    pos["tp_stage"] = 0
    pos["last_tp_ts"] = None
    pos["note"] = note
    pos["name"] = meta["name"]
    pos["market"] = meta["market"]
    cash = _account_cash(data)
    if cash is not None:
        data["account_cash"] = round(cash - price * qty, 2)
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
            "price": price,
            "qty": qty,
            "after_qty": qty,
            "avg_cost": pos["cost"],
            "note": note,
        }
    )
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
    """单槽目标金额：总权益×30%；无总权益时默认按 DEFAULT_ACCOUNT_TOTAL×30%。"""
    if account_total is not None and float(account_total) > 0:
        return round(float(account_total) * float(SLOT_WEIGHT), 2)
    if DEFAULT_ACCOUNT_TOTAL and float(DEFAULT_ACCOUNT_TOTAL) > 0:
        return round(float(DEFAULT_ACCOUNT_TOTAL) * float(SLOT_WEIGHT), 2)
    mv = _holdings_market_value(rows)
    n = len(occupied)
    if n > 0 and mv > 0:
        return round(mv / float(n), 2)
    return None


def _paper_slot_qty(price: float, *, account_total: float | None = None) -> int:
    """纸面单槽股数：30 万×30% / 价，向下取整到 100 股（与入槽成交同一口径）。"""
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
    budget = equity * float(SLOT_WEIGHT)
    if budget <= 0:
        return 0
    return int(budget // (px * 100.0)) * 100


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



def today_slot_buy_count(session: str, *, text: str | None = None) -> int:
    """当日纸面/槽位买入次数（trades.jsonl side=buy）。"""
    day = str(session or "")[:10]
    if len(day) < 10:
        return 0
    raw = text
    if raw is None:
        try:
            tp = Path(__file__).resolve().parent / "trades.jsonl"
            raw = tp.read_text(encoding="utf-8") if tp.exists() else ""
        except OSError:
            raw = ""
    n = 0
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(rec.get("side") or "") != "buy":
            continue
        ts = str(rec.get("time") or rec.get("ts") or "")
        if ts.startswith(day):
            n += 1
    return n


def _apply_portfolio_slots(
    rows: list[dict[str, Any]],
    *,
    account_total: float | None,
    phase_now: str,
) -> dict[str, Any]:
    """三槽：盘中可持 3；当日最多买 3；尾盘窗口按隔夜上限（现同为 3）。

    · 用户实仓 qty>0 占槽；可买空槽见 free_buy_slot_count（盘中/隔夜均为 3）
    · 入槽顺序：先平再买；平仓前已触买且现价≤买点+1% 优先、按触发先后、成交价=现价；否则平仓后新触发按时间、成交价=买点
    · 止损平仓后释放槽位，但该票当日不可再买
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
    session = next(
        (str(r.get("交易日")) for r in rows if r.get("交易日") and r.get("交易日") != "-"),
        str(pd.Timestamp.now().date()),
    )
    buy_ranks = today_slot_buy_ranks(session)
    buys_done = today_slot_buy_count(session)
    buys_left = max(0, int(MAX_BUYS_PER_DAY) - buys_done)

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
        # 三槽只从当前默认策略池入场（strategy16=核心龙头）；旧 portfolio_pool 遗留票不买
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
    if phase_now == "continuous" and free > 0 and buys_left > 0:
        # 入槽：只吃「已触买」。先平再买；第一梯队现价、其后新触发买点
        hit_queue = [
            (rank, dist, code, r)
            for rank, dist, code, r in candidates
            if _row_hit_buy(r)
        ]
        budget = _slot_notional_budget(account_total, rows, occupied)
        used: set[str] = set()
        while True:
            data = load_holdings()
            if free_buy_slot_count(data) <= 0:
                break
            if today_slot_buy_count(session) >= int(MAX_BUYS_PER_DAY):
                break
            if budget is None or budget <= 0:
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
                dec = _fill_of(r)
                if dec is None:
                    continue
                trig = _row_trigger_ts(r, side="buy")
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
            qty = int(budget // (price * 100.0)) * 100
            if qty < 100:
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
                )
            except Exception as e:  # noqa: BLE001
                print(f"[{_now()}] 槽位自动买入失败 {code}: {e}")
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
            if last is not None and pos.get("cost") is not None:
                try:
                    last_f = float(last)
                    cost_f = float(pos["cost"])
                    pnl, pnl_pct = mark_unrealized(last_f, cost_f, qty)
                    r["浮盈"] = pnl
                    r["浮盈%"] = pnl_pct
                    r["市值"] = round(last_f * qty, 2)
                    r["成本额"] = round(cost_f * qty, 2)
                    day_pnl, day_pct, day_base = session_day_pnl(
                        mark=last_f,
                        qty=qty,
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
            fill_note = f"槽位自动买入{qty}股@{price:.{px_digits}f}（{fill_kind}）"
            r["挂单说明"] = f"{fill_note}；{note}" if note else fill_note
            remember_factor_trigger(
                code,
                side="buy",
                px=price,
                session=str(r.get("交易日") or pd.Timestamp.now().date()),
            )

    meta = _slot_meta_from_holdings(load_holdings())
    meta["candidates"] = sorted(selected_codes)
    meta["bought"] = bought_codes
    meta["buysToday"] = today_slot_buy_count(session)
    meta["buysLeft"] = max(0, int(MAX_BUYS_PER_DAY) - int(meta["buysToday"]))
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


def _keep_first_signal_ts(prev: dict[str, Any], st: dict[str, Any]) -> None:
    for key in ("buy_hit_ts", "stop_hit_ts"):
        old = prev.get(key)
        if not old:
            continue
        new = st.get(key)
        # 开盘保护纠成 09:30 时，允许覆盖首根 1m 的 09:31/09:32
        if (
            key == "stop_hit_ts"
            and new
            and _is_open_bell_ts(new)
            and not _is_open_bell_ts(old)
        ):
            continue
        st[key] = old


def _is_open_bell_ts(ts: Any) -> bool:
    hms = _signal_hms(ts) or ""
    return hms[:5] == "09:30"


def _open_protect_hit_ts(
    *,
    session: str,
    fill_px: Any = None,
    open_px: Any = None,
    existing: Any = None,
    open_bell: bool = False,
) -> str | None:
    """竞价核成交时刻：开盘价成交固定 09:30；09:31/09:32 的 1m 标签纠回开盘铃。"""
    bell = session_open_bell_ts(session)
    if open_bell:
        return bell
    fill = _as_money(fill_px)
    o = _as_money(open_px)
    if fill is None or o is None or abs(float(fill) - float(o)) > 5e-3:
        return _bar_ts_str(existing) if existing else None
    hms = _signal_hms(existing) or ""
    if not hms or hms[:5] in ("09:30", "09:31", "09:32"):
        return bell
    return _bar_ts_str(existing) if existing else bell


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
        "action_kind": str(action_kind or ""),
    }
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

    if new_qty <= 0:
        append_slot_freed_at(data, session, rec.get("time") or rec.get("first_hit_ts"))

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
