"""Strategy Signal Simulator — Layer A（与 Paper Portfolio 严格隔离）。

每 (strategy_id, symbol) 唯一 lifecycle：FLAT / LONG。
Live quote（约 2~5s）撞条件 → 状态转换；不等待 1m close。

不读写：
  account_cash / paper qty / Capital V2 / ExitDecisionEngine。
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "strategy_sim_state.json"
EVENTS_FILE = ROOT / "strategy_signal_events.json"

INITIAL_CASH = 100_000.0
LOT = 100
TARGET_PCT = 0.95
# 策略十六：隔夜仓竞价低开（今开已破卖价、按 09:30 开盘价全清）后，允许当日过门回买。
# 模拟器无「止损已记」账本，用隔夜 entry_time + 开盘保护成交近似纸面规则。
GAP_REBUY_STRATEGY_IDS = frozenset({"strategy16"})
# 正常刷新 2~5s；偶发延迟留余量。过期 quote 不产生新 transition。
LIVE_QUOTE_STALE_AFTER_SECONDS = 15.0

_LOCK = threading.RLock()
_STATE: dict[str, Any] | None = None


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _code_key(code: str) -> str:
    return str(code or "").strip().zfill(6)[-6:]


def _pos_key(strategy_id: str, symbol: str) -> str:
    return f"{strategy_id}:{_code_key(symbol)}"


def empty_state() -> dict[str, Any]:
    return {"updated_at": None, "positions": {}, "version": 1}


def empty_book(
    *,
    strategy_id: str,
    symbol: str,
    initial_cash: float = INITIAL_CASH,
) -> dict[str, Any]:
    cash = float(initial_cash)
    return {
        "strategy_id": str(strategy_id),
        "symbol": _code_key(symbol),
        "state": "FLAT",
        "entry_price": None,
        "entry_time": None,
        "exit_price": None,
        "exit_time": None,
        "virtual_cash": cash,
        "virtual_shares": 0.0,
        "initial_cash": cash,
        "trades": 0,
        "last_mark": None,
        "last_quote_ts": None,
        # NEVER_TRADED => 0；有成交后 FLAT 时为 cash/initial-1（≠自动清零）
        "cumulative_return_pct": 0.0,
        "single_return_pct": None,
        "closed_trade_return_pct": None,
        "bootstrapped": False,
        "bootstrap_cutoff": None,
        "bootstrap_source": None,
        "bootstrap_model": "daily_open_break_fixed_stop",
        "live_model": "quote_touch_row_levels",
        "exit_model": "row_sell_level_live",
        "gap_rebuy_ok": False,
    }


def needs_historical_bootstrap(book: dict[str, Any]) -> bool:
    """尚未 bootstrap 且账本仍是「从未交易」的初始态。"""
    if bool(book.get("bootstrapped")):
        return False
    try:
        trades = int(book.get("trades") or 0)
    except (TypeError, ValueError):
        trades = 0
    if trades > 0:
        return False
    if str(book.get("state") or "FLAT") == "LONG":
        return False
    try:
        shares = float(book.get("virtual_shares") or 0.0)
    except (TypeError, ValueError):
        shares = 0.0
    if shares > 0:
        return False
    init = float(book.get("initial_cash") or INITIAL_CASH)
    try:
        cash = float(book.get("virtual_cash") or init)
    except (TypeError, ValueError):
        cash = init
    # 已有非初始现金（例如手工/旧恢复）则不再 bootstrap
    if abs(cash - init) > 1e-6:
        return False
    return True


def sync_flat_cumulative(book: dict[str, Any]) -> None:
    """FLAT：cumulative = cash/initial - 1（冻结派生；绝非强制 0）。"""
    if str(book.get("state") or "FLAT") == "LONG":
        return
    init = float(book.get("initial_cash") or INITIAL_CASH)
    if init <= 0:
        return
    cash = float(book.get("virtual_cash") or 0.0)
    book["cumulative_return_pct"] = round((cash / init - 1.0) * 100.0, 2)
    book["single_return_pct"] = None


def bootstrap_book_from_daily_ohlc(
    book: dict[str, Any],
    daily: Any,
    *,
    start_date: str,
    entry_pct: float,
    stop_pct: float,
    tick: float = 0.01,
    prev_entry_mode: str = "yin_or_small_yang",
    persist: bool = True,
) -> dict[str, Any]:
    """历史日线 bootstrap → 写入同一 simulator 账本（非 Factor1 串台 SoT）。

    粒度：completed daily OHLC；触买=high>=buy_level（成交记 buy_level）；
    触卖=low<=sell_level（成交记 sell_level）；T+1；与 live touch 语义一致。
    cutoff = 末日线日期；之后由 live events 接力，不重复计数。
    """
    import pandas as pd
    from strategy.open_break import (
        entry_filters_ok,
        entry_trigger_price,
        stop_trigger_price,
    )

    out = {
        "applied": False,
        "cutoff": None,
        "trades": 0,
        "state": "FLAT",
        "cumulative_return_pct": 0.0,
    }
    if daily is None or getattr(daily, "empty", True):
        book["bootstrapped"] = True
        book["bootstrap_source"] = "daily_ohlc_empty"
        book["bootstrap_model"] = "daily_open_break_fixed_stop"
        sync_flat_cumulative(book)
        if persist:
            save_state()
        return out

    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    start = pd.Timestamp(str(start_date)[:10]).normalize()
    idxs = [
        i
        for i in range(len(df))
        if pd.Timestamp(df.iloc[i]["date"]).normalize() >= start
    ]
    if not idxs:
        book["bootstrapped"] = True
        book["bootstrap_source"] = "daily_ohlc_no_bars"
        book["bootstrap_model"] = "daily_open_break_fixed_stop"
        sync_flat_cumulative(book)
        if persist:
            save_state()
        return out

    init = float(book.get("initial_cash") or INITIAL_CASH)
    cash = init
    shares = 0.0
    state = "FLAT"
    entry_price = None
    entry_time = None
    exit_price = None
    exit_time = None
    buy_day = None
    trades = 0
    closed_ret = None
    cutoff = None

    for i in idxs:
        row = df.iloc[i]
        prev = df.iloc[i - 1] if i >= 1 else None
        prev2 = df.iloc[i - 2] if i >= 2 else None
        if prev is None:
            continue
        day = pd.Timestamp(row["date"]).normalize()
        cutoff = str(day.date())
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if o <= 0 or c <= 0:
            continue
        buy_lv = float(entry_trigger_price(o, entry_pct=entry_pct, tick=tick))
        sell_lv = float(stop_trigger_price(o, stop_pct=stop_pct, tick=tick))
        allow = entry_filters_ok(
            float(prev["open"]),
            float(prev["close"]),
            float(prev2["open"]) if prev2 is not None else None,
            float(prev2["close"]) if prev2 is not None else None,
            entry_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
            tick=tick,
        )

        if state == "LONG" and shares > 0:
            if buy_day is not None and day == buy_day:
                # T+1：当日不可卖；收盘 mark
                continue
            if l <= sell_lv + 1e-12:
                px = sell_lv
                cash = cash + shares * px
                shares = 0.0
                state = "FLAT"
                exit_price = round(px, 4)
                exit_time = f"{cutoff} 15:00:00"
                trades += 1
                if entry_price and entry_price > 0:
                    closed_ret = round((px / float(entry_price) - 1.0) * 100.0, 2)
                entry_price = None
                entry_time = None
                buy_day = None
            continue

        if state == "FLAT" and allow and (h + 1e-12 >= buy_lv):
            sh, cash_left, _ = _buy_shares(cash, buy_lv)
            if sh >= LOT:
                cash = cash_left
                shares = sh
                state = "LONG"
                entry_price = round(buy_lv, 4)
                entry_time = f"{cutoff} 09:30:00"
                exit_price = None
                exit_time = None
                buy_day = day
                closed_ret = None

    # 末日若仍 LONG：用收盘 mark 写累计（不改 cash/shares）
    last_close = float(df.iloc[idxs[-1]]["close"])
    book["state"] = state
    book["virtual_cash"] = float(cash)
    book["virtual_shares"] = float(shares)
    book["entry_price"] = entry_price
    book["entry_time"] = entry_time
    book["exit_price"] = exit_price
    book["exit_time"] = exit_time
    book["trades"] = int(trades)
    book["closed_trade_return_pct"] = closed_ret
    book["bootstrapped"] = True
    book["bootstrap_cutoff"] = cutoff
    book["bootstrap_source"] = "daily_ohlc_touch"
    book["bootstrap_model"] = "daily_open_break_fixed_stop"
    book["live_model"] = "quote_touch_row_levels"
    book["exit_model"] = "row_sell_level_live"
    if state == "LONG" and shares > 0:
        mark_book(book, last_close, quote_ts=f"{cutoff} 15:00:00" if cutoff else None)
    else:
        sync_flat_cumulative(book)
    if persist:
        save_state()
    out.update(
        {
            "applied": True,
            "cutoff": cutoff,
            "trades": trades,
            "state": state,
            "cumulative_return_pct": book.get("cumulative_return_pct"),
            "virtual_cash": book.get("virtual_cash"),
            "virtual_shares": book.get("virtual_shares"),
        }
    )
    return out


def bootstrap_book_from_factor26_replay(
    book: dict[str, Any],
    replay: dict[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Seed simulator from production factor26 1m replay trades when available."""
    out = {
        "applied": False,
        "source": replay.get("source") if isinstance(replay, dict) else None,
        "trades": 0,
        "state": str(book.get("state") or "FLAT"),
    }
    if not isinstance(replay, dict) or replay.get("source") != "1m":
        return out
    trades = [t for t in (replay.get("trades") or []) if isinstance(t, dict)]
    if not trades:
        book["bootstrapped"] = True
        book["bootstrap_source"] = "factor26_1m_empty"
        book["bootstrap_model"] = "factor26_1m_replay"
        book["live_model"] = "quote_touch_row_levels"
        book["exit_model"] = "row_sell_level_live"
        sync_flat_cumulative(book)
        if persist:
            save_state()
        out.update({"applied": True, "state": book.get("state")})
        return out

    init = float(book.get("initial_cash") or INITIAL_CASH)
    cash = init
    shares = 0.0
    state = "FLAT"
    entry_price = None
    entry_time = None
    exit_price = None
    exit_time = None
    closed_ret = None
    sells = 0
    last_mark = None
    cutoff = None

    for t in trades:
        side = str(t.get("side") or "").lower()
        try:
            px = float(t.get("px") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            continue
        ts = str(t.get("ts") or t.get("date") or "")
        cutoff = str(t.get("date") or ts)[:10] or cutoff
        if side == "buy" and state == "FLAT":
            sh, cash_left, _ = _buy_shares(cash, px)
            if sh < LOT:
                continue
            cash = cash_left
            shares = sh
            state = "LONG"
            entry_price = round(px, 4)
            entry_time = ts or (f"{cutoff} 09:30:00" if cutoff else None)
            exit_price = None
            exit_time = None
            closed_ret = None
            last_mark = px
        elif side == "sell" and state == "LONG" and shares > 0:
            sell_shares = shares
            try:
                noted_shares = float(t.get("shares") or 0)
            except (TypeError, ValueError):
                noted_shares = 0.0
            if noted_shares > 0:
                sell_shares = min(shares, noted_shares)
            cash += sell_shares * px
            shares -= sell_shares
            if shares <= 1e-9:
                shares = 0.0
                state = "FLAT"
                exit_price = round(px, 4)
                exit_time = ts or (f"{cutoff} 15:00:00" if cutoff else None)
                if entry_price and entry_price > 0:
                    closed_ret = round((px / float(entry_price) - 1.0) * 100.0, 2)
                entry_price = None
                entry_time = None
                sells += 1
            last_mark = px

    book["state"] = state
    book["virtual_cash"] = float(cash)
    book["virtual_shares"] = float(shares)
    book["entry_price"] = entry_price
    book["entry_time"] = entry_time
    book["exit_price"] = exit_price
    book["exit_time"] = exit_time
    book["trades"] = int(sells)
    book["closed_trade_return_pct"] = closed_ret
    book["bootstrapped"] = True
    book["bootstrap_cutoff"] = cutoff
    book["bootstrap_source"] = "factor26_1m_replay"
    book["bootstrap_model"] = "factor26_1m_replay"
    book["live_model"] = "quote_touch_row_levels"
    book["exit_model"] = "row_sell_level_live"
    if state == "LONG" and shares > 0 and last_mark:
        mark_book(book, float(last_mark), quote_ts=f"{cutoff} 15:00:00" if cutoff else None)
    else:
        sync_flat_cumulative(book)
    if persist:
        save_state()
    out.update(
        {
            "applied": True,
            "cutoff": cutoff,
            "trades": sells,
            "state": state,
            "cumulative_return_pct": book.get("cumulative_return_pct"),
        }
    )
    return out


def ensure_bootstrapped_from_factor26_replay(
    strategy_id: str,
    symbol: str,
    replay: dict[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    book = get_book(strategy_id, symbol)
    if not needs_historical_bootstrap(book):
        return {"applied": False, "book": book, "skipped": "already_seeded"}
    info = bootstrap_book_from_factor26_replay(book, replay, persist=persist)
    info["book"] = book
    return info


def ensure_bootstrapped(
    strategy_id: str,
    symbol: str,
    daily: Any,
    *,
    start_date: str,
    entry_pct: float,
    stop_pct: float,
    tick: float = 0.01,
    prev_entry_mode: str = "yin_or_small_yang",
    persist: bool = True,
) -> dict[str, Any]:
    """若账本仍是初始空仓，则用日线 bootstrap 一次。"""
    book = get_book(strategy_id, symbol)
    if not needs_historical_bootstrap(book):
        # 已有账本：FLAT 时对齐 cumulative←cash（防 0 漂移）
        if str(book.get("state")) != "LONG":
            sync_flat_cumulative(book)
        return {"applied": False, "book": book, "skipped": "already_seeded"}
    info = bootstrap_book_from_daily_ohlc(
        book,
        daily,
        start_date=start_date,
        entry_pct=entry_pct,
        stop_pct=stop_pct,
        tick=tick,
        prev_entry_mode=prev_entry_mode,
        persist=persist,
    )
    info["book"] = book
    return info


def load_state(*, force: bool = False) -> dict[str, Any]:
    global _STATE
    with _LOCK:
        if _STATE is not None and not force:
            return _STATE
        if not STATE_FILE.is_file():
            _STATE = empty_state()
            return _STATE
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            _STATE = empty_state()
            return _STATE
        if not isinstance(raw, dict):
            _STATE = empty_state()
            return _STATE
        if not isinstance(raw.get("positions"), dict):
            raw["positions"] = {}
        _STATE = raw
        return _STATE


def save_state(data: dict[str, Any] | None = None) -> None:
    global _STATE
    with _LOCK:
        if data is not None:
            _STATE = data
        if _STATE is None:
            _STATE = empty_state()
        _STATE["updated_at"] = _now_str()
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(_STATE, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(STATE_FILE)


def reset_all_state() -> None:
    """Reset durable simulator state and event stream for a fresh paper session."""
    global _STATE
    with _LOCK:
        _STATE = empty_state()
        _STATE["updated_at"] = _now_str()
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(_STATE, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(STATE_FILE)

        raw = {"updated_at": _now_str(), "events": []}
        ev_tmp = EVENTS_FILE.with_suffix(".json.tmp")
        ev_tmp.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ev_tmp.replace(EVENTS_FILE)


def get_book(strategy_id: str, symbol: str) -> dict[str, Any]:
    st = load_state()
    key = _pos_key(strategy_id, symbol)
    pos = st["positions"].get(key)
    if not isinstance(pos, dict):
        pos = empty_book(strategy_id=strategy_id, symbol=symbol)
        st["positions"][key] = pos
    return pos


def equity_of(book: dict[str, Any], mark: float | None = None) -> float:
    cash = float(book.get("virtual_cash") or 0.0)
    shares = float(book.get("virtual_shares") or 0.0)
    if shares <= 0:
        return cash
    px = mark
    if px is None:
        px = book.get("last_mark")
    if px is None:
        px = book.get("entry_price")
    try:
        px_f = float(px)
    except (TypeError, ValueError):
        return cash
    if px_f <= 0:
        return cash
    return cash + shares * px_f


def mark_book(book: dict[str, Any], mark: float, *, quote_ts: str | None = None) -> None:
    """LONG：随 mark 更新累计；FLAT：equity=cash，cumulative 冻结（≠清零）。"""
    try:
        m = float(mark)
    except (TypeError, ValueError):
        return
    if m <= 0:
        return
    shares = float(book.get("virtual_shares") or 0.0)
    init = float(book.get("initial_cash") or INITIAL_CASH)
    if str(book.get("state")) == "LONG" and shares > 0:
        book["last_mark"] = m
        if quote_ts:
            book["last_quote_ts"] = str(quote_ts)
        eq = equity_of(book, m)
        book["cumulative_return_pct"] = round((eq / init - 1.0) * 100.0, 2)
        entry = book.get("entry_price")
        try:
            e = float(entry) if entry is not None else 0.0
        except (TypeError, ValueError):
            e = 0.0
        if e > 0:
            book["single_return_pct"] = round((m / e - 1.0) * 100.0, 2)
    else:
        # FLAT：不因 mark 改 equity；cumulative 仅由 cash 派生并冻结
        if quote_ts:
            book["last_quote_ts"] = str(quote_ts)
        sync_flat_cumulative(book)


def _buy_shares(cash: float, px: float) -> tuple[float, float, float]:
    """返回 (shares, cash_left, fee_approx0). 整手；无印花税买入。"""
    if px <= 0 or cash <= 0:
        return 0.0, cash, 0.0
    budget = cash * TARGET_PCT
    raw = math.floor(budget / (px * LOT)) * LOT
    if raw < LOT:
        return 0.0, cash, 0.0
    cost = raw * px
    if cost > cash:
        return 0.0, cash, 0.0
    return float(raw), cash - cost, 0.0


def _append_event(event: dict[str, Any]) -> None:
    with _LOCK:
        if EVENTS_FILE.is_file():
            try:
                raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                raw = {"updated_at": None, "events": []}
        else:
            raw = {"updated_at": None, "events": []}
        if not isinstance(raw, dict):
            raw = {"updated_at": None, "events": []}
        evs = raw.get("events")
        if not isinstance(evs, list):
            evs = []
        # idempotent: same event_id skip
        eid = str(event.get("event_id") or "")
        if eid and any(str(x.get("event_id")) == eid for x in evs if isinstance(x, dict)):
            return
        evs.append(event)
        raw["events"] = evs
        raw["updated_at"] = _now_str()
        tmp = EVENTS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(EVENTS_FILE)


def _event_id(
    strategy_id: str,
    symbol: str,
    side: str,
    trigger_time: str,
    trigger_price: float,
) -> str:
    raw = f"{strategy_id}|{_code_key(symbol)}|{side}|{trigger_time}|{trigger_price:.6f}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def _session_of(ts: Any) -> str:
    return str(ts or "").replace("T", " ")[:10]


def _stamp_gap_rebuy_ok(
    *,
    strategy_id: str,
    entry_time: Any,
    session: str,
    used_open_protect: bool,
) -> bool:
    """隔夜仓 + 竞价低开按开盘价全清 → 策略十六允许当日回买。"""
    if str(strategy_id) not in GAP_REBUY_STRATEGY_IDS:
        return False
    if not used_open_protect:
        return False
    entry_day = str(entry_time or "")[:10]
    sess = str(session)[:10]
    return bool(entry_day and sess and entry_day < sess)


def quote_age_seconds(
    quote_ts: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    if not quote_ts:
        return None
    try:
        # accept "YYYY-MM-DD HH:MM:SS" or ISO
        s = str(quote_ts).replace("T", " ")[:19]
        qt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    n = now or datetime.now()
    return (n - qt).total_seconds()


def is_quote_stale(
    quote_ts: str | None,
    *,
    now: datetime | None = None,
    stale_after: float = LIVE_QUOTE_STALE_AFTER_SECONDS,
) -> bool:
    age = quote_age_seconds(quote_ts, now=now)
    if age is None:
        return False  # 无时间戳时不因 freshness 拦（兼容旧 quote）
    return age > float(stale_after)


def _session_clock(ts: str | None) -> str:
    """从 quote_ts 取 HH:MM:SS；缺则空串。"""
    s = str(ts or "").strip()
    if len(s) >= 19 and s[10] == " ":
        return s[11:19]
    if len(s) >= 8 and s[2] == ":":
        return s[:8]
    return ""


def _in_live_exec_window(quote_ts: str | None) -> bool:
    """连续竞价才允许 simulator 成交（与纸面 is_signal_window 对齐）。"""
    hms = _session_clock(quote_ts)
    if not hms:
        return False
    return ("09:30:00" <= hms <= "11:30:00") or ("13:00:00" <= hms < "15:00:00")


def pnl_start_date() -> str:
    from watch_config import STRATEGY_PNL_START

    return str(STRATEGY_PNL_START)[:10]


def session_before_pnl_start(session: str | None) -> bool:
    """起算日前不计策略累计成交（展示保持空账本 0%）。"""
    s = str(session or "")[:10]
    start = pnl_start_date()
    return bool(s) and bool(start) and s < start


def reset_strategy_books(strategy_id: str) -> int:
    """清空某策略全部虚拟账本（累计归零）。盯盘须停掉再写盘，否则内存会盖回。"""
    load_state(force=True)
    sid = str(strategy_id)
    prefix = f"{sid}:"
    n = 0
    with _LOCK:
        st = _STATE if _STATE is not None else empty_state()
        pos = st.setdefault("positions", {})
        start = pnl_start_date()
        for key in list(pos.keys()):
            if str(key).startswith(prefix):
                code = str(key).split(":", 1)[-1]
                book = empty_book(strategy_id=sid, symbol=code)
                # 防止 reset 后日线 bootstrap 把 10 月前成交又灌回来
                book["bootstrapped"] = True
                book["bootstrap_source"] = "pnl_start_reset"
                book["bootstrap_cutoff"] = start
                pos[key] = book
                n += 1
        st["updated_at"] = _now_str()
        save_state()
    return n


def archive_strategy_events(
    strategy_id: str,
    *,
    dest: Path | None = None,
    reason: str = "",
) -> int:
    """把某策略历史事件移出 live 事件流，避免 repair 重放旧成交。"""
    sid = str(strategy_id)
    dest = dest or (ROOT / f"strategy_signal_events.{sid}_archived.json")
    if not EVENTS_FILE.is_file():
        return 0
    try:
        raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0
    evs = list(raw.get("events") or []) if isinstance(raw, dict) else []
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    for e in evs:
        if not isinstance(e, dict):
            continue
        if str(e.get("strategy_id") or "") == sid:
            row = dict(e)
            if reason:
                row["archive_reason"] = reason
            moved.append(row)
        else:
            kept.append(e)
    if not moved:
        return 0
    dest.write_text(
        json.dumps(
            {"updated_at": _now_str(), "reason": reason, "events": moved},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    EVENTS_FILE.write_text(
        json.dumps(
            {"updated_at": _now_str(), "events": kept},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(moved)


def evaluate_live_transition(
    *,
    strategy_id: str,
    symbol: str,
    live_last: float,
    quote_ts: str | None,
    buy_level: float | None,
    sell_level: float | None,
    allow_entry: bool,
    evaluation_time: str | None = None,
    reason: str = "live_quote",
    persist: bool = True,
    force_book: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_after: float | None = None,
    t0: bool = False,
    day_open: float | None = None,
) -> dict[str, Any]:
    """用 live last 撞 buy/sell level；仅状态转换产生事件。

    BUY：FLAT + allow_entry + last >= buy_level，且当日未卖出过
    （策略十六例外：隔夜仓竞价低开按开盘价全清后，过门允许当日回买）
    SELL：LONG + last <= sell_level，且非买入当日（t0 标的除外）
    **买卖均仅连续竞价**（09:30–11:30 / 13:00–15:00）。竞价观察不入账；
    竞价已破卖价等到 9:30，若今开已破卖价则按开盘价、时刻 09:30:00。

    条件语义保持 touch（>= / <=），不是 cross。
    T+1 / 卖出日不再买回与回测 ``open_break`` 及日线 bootstrap 一致；
    缺这两条时买卖位交叉的票会逐 tick 买卖翻转。
    返回 {transition, book, event, telemetry}。
    """
    eval_t = evaluation_time or _now_str()
    stale_lim = (
        float(stale_after)
        if stale_after is not None
        else LIVE_QUOTE_STALE_AFTER_SECONDS
    )
    sess0 = _session_of(quote_ts or eval_t)
    if session_before_pnl_start(sess0):
        book = force_book if force_book is not None else get_book(strategy_id, symbol)
        try:
            last0 = float(live_last)
        except (TypeError, ValueError):
            last0 = 0.0
        if last0 > 0:
            mark_book(book, last0, quote_ts=quote_ts)
        if persist and force_book is None:
            save_state()
        return {
            "transition": None,
            "book": deepcopy(book),
            "event": None,
            "telemetry": {
                "quote_time": quote_ts,
                "evaluation_time": eval_t,
                "signal_time": None,
                "quote_to_eval_ms": None,
                "eval_to_signal_ms": None,
            },
            "skipped": "before_pnl_start",
        }
    out: dict[str, Any] = {
        "transition": None,
        "book": None,
        "event": None,
        "telemetry": {
            "quote_time": quote_ts,
            "evaluation_time": eval_t,
            "signal_time": None,
            "quote_to_eval_ms": None,
            "eval_to_signal_ms": None,
        },
        "skipped": None,
    }
    try:
        last = float(live_last)
    except (TypeError, ValueError):
        out["skipped"] = "bad_last"
        return out
    if last <= 0:
        out["skipped"] = "bad_last"
        return out

    if is_quote_stale(quote_ts, now=now, stale_after=stale_lim):
        out["skipped"] = "stale_quote"
        book = force_book if force_book is not None else get_book(strategy_id, symbol)
        mark_book(book, last, quote_ts=quote_ts)
        out["book"] = book
        if persist and force_book is None:
            save_state()
        return out

    age = quote_age_seconds(quote_ts, now=now)
    if age is not None:
        out["telemetry"]["quote_to_eval_ms"] = int(max(0.0, age) * 1000)

    with _LOCK:
        book = force_book if force_book is not None else get_book(strategy_id, symbol)
        state = str(book.get("state") or "FLAT")
        event: dict[str, Any] | None = None
        transition: str | None = None
        session = _session_of(quote_ts or eval_t)

        if state == "FLAT":
            try:
                buy_lv = float(buy_level) if buy_level is not None else None
            except (TypeError, ValueError):
                buy_lv = None
            touched = (
                allow_entry and buy_lv is not None and buy_lv > 0 and last + 1e-12 >= buy_lv
            )
            if touched and _session_of(book.get("exit_time")) == session:
                if not book.get("gap_rebuy_ok"):
                    out["skipped"] = "exited_today"
                    touched = False
            if touched and not _in_live_exec_window(quote_ts or eval_t):
                out["skipped"] = "wait_auction"
                touched = False
            if touched:
                shares, cash_left, _ = _buy_shares(float(book["virtual_cash"]), last)
                if shares >= LOT:
                    book["state"] = "LONG"
                    book["entry_price"] = round(last, 4)
                    book["entry_time"] = str(quote_ts or eval_t)
                    book["exit_price"] = None
                    book["exit_time"] = None
                    book["gap_rebuy_ok"] = False
                    book["virtual_shares"] = shares
                    book["virtual_cash"] = cash_left
                    book["closed_trade_return_pct"] = None
                    book["single_return_pct"] = 0.0
                    mark_book(book, last, quote_ts=quote_ts)
                    transition = "BUY"
                    event = {
                        "event_id": _event_id(
                            strategy_id, symbol, "BUY", book["entry_time"], last
                        ),
                        "strategy_id": strategy_id,
                        "symbol": _code_key(symbol),
                        "side": "BUY",
                        "trigger_price": round(last, 4),
                        "trigger_time": book["entry_time"],
                        "quote_timestamp": quote_ts,
                        "reason": reason,
                        "trading_session_date": str(book["entry_time"])[:10],
                        "buy_level": buy_lv,
                        "execution_model": "quote_touch_row_levels",
                    }
        elif state == "LONG":
            try:
                sell_lv = float(sell_level) if sell_level is not None else None
            except (TypeError, ValueError):
                sell_lv = None
            touched = sell_lv is not None and sell_lv > 0 and last <= sell_lv + 1e-12
            if touched and not t0 and _session_of(book.get("entry_time")) == session:
                out["skipped"] = "t1_locked"
                touched = False
            if touched and not _in_live_exec_window(quote_ts or eval_t):
                out["skipped"] = "wait_auction"
                touched = False
            if touched:
                shares = float(book.get("virtual_shares") or 0.0)
                entry = float(book.get("entry_price") or 0.0)
                fill_px = last
                exit_ts = str(quote_ts or eval_t)
                used_open_protect = False
                try:
                    open_f = float(day_open or 0)
                except (TypeError, ValueError):
                    open_f = 0.0
                hms = _session_clock(quote_ts or eval_t)
                if (
                    sell_lv is not None
                    and open_f > 0
                    and open_f <= float(sell_lv) + 1e-12
                    and "09:30:00" <= hms <= "09:32:59"
                ):
                    fill_px = open_f
                    exit_ts = f"{session} 09:30:00"
                    used_open_protect = True
                proceeds = shares * fill_px
                book["virtual_cash"] = float(book.get("virtual_cash") or 0.0) + proceeds
                book["virtual_shares"] = 0.0
                book["state"] = "FLAT"
                book["exit_price"] = round(fill_px, 4)
                book["exit_time"] = exit_ts
                book["gap_rebuy_ok"] = _stamp_gap_rebuy_ok(
                    strategy_id=strategy_id,
                    entry_time=book.get("entry_time"),
                    session=session,
                    used_open_protect=used_open_protect,
                )
                book["trades"] = int(book.get("trades") or 0) + 1
                if entry > 0:
                    book["closed_trade_return_pct"] = round(
                        (fill_px / entry - 1.0) * 100.0, 2
                    )
                book["single_return_pct"] = None
                init = float(book.get("initial_cash") or INITIAL_CASH)
                book["cumulative_return_pct"] = round(
                    (float(book["virtual_cash"]) / init - 1.0) * 100.0, 2
                )
                book["last_mark"] = None
                transition = "SELL"
                event = {
                    "event_id": _event_id(
                        strategy_id, symbol, "SELL", book["exit_time"], fill_px
                    ),
                    "strategy_id": strategy_id,
                    "symbol": _code_key(symbol),
                    "side": "SELL",
                    "trigger_price": round(fill_px, 4),
                    "trigger_time": book["exit_time"],
                    "quote_timestamp": quote_ts,
                    "reason": reason,
                    "trading_session_date": str(book["exit_time"])[:10],
                    "sell_level": sell_lv,
                    "execution_model": "quote_touch_row_levels",
                }
            else:
                mark_book(book, last, quote_ts=quote_ts)
        else:
            book["state"] = "FLAT"
            mark_book(book, last, quote_ts=quote_ts)

        if event is not None:
            out["telemetry"]["signal_time"] = event["trigger_time"]
            out["telemetry"]["eval_to_signal_ms"] = 0
            if persist:
                _append_event(event)

        if persist and force_book is None:
            save_state()

        out["transition"] = transition
        out["book"] = deepcopy(book)
        out["event"] = event
        return out


def apply_book_to_row(row: dict[str, Any], book: dict[str, Any]) -> None:
    """Strategy Tab 读模型：主状态来自 simulator，不覆盖 Paper 字段。"""
    state = str(book.get("state") or "FLAT")
    row["策略模拟状态"] = state
    row["策略模拟持有"] = state == "LONG"
    # 主展示状态：空仓 / 策略持有（不再用纸面 qty）
    row["策略状态"] = "策略持有" if state == "LONG" else "空仓"
    row["策略入场价"] = book.get("entry_price")
    row["策略入场时间"] = book.get("entry_time")
    row["策略出场价"] = book.get("exit_price")
    row["策略出场时间"] = book.get("exit_time")
    row["策略虚拟股数"] = book.get("virtual_shares")
    row["策略虚拟现金"] = book.get("virtual_cash")
    row["策略收益%"] = book.get("cumulative_return_pct")
    row["策略收益"] = None
    row["策略收益语义"] = "strategy_simulator_ledger"
    row["策略收益范围"] = "symbol"
    row["策略历史口径"] = book.get("bootstrap_model") or "daily_open_break_fixed_stop"
    row["策略实时口径"] = book.get("live_model") or "quote_touch_row_levels"
    row["策略退出口径"] = book.get("exit_model") or "row_sell_level_live"
    row["策略累计持有"] = state == "LONG"
    row["单笔收入%"] = book.get("single_return_pct")
    # 不覆盖 Paper 已写入的成交/预警时刻（今日平仓卡片「触发」以纸面为准）
    if not row.get("信号时间"):
        if book.get("entry_time"):
            row["信号时间"] = (
                book.get("entry_time") if state == "LONG" else book.get("exit_time")
            )


def reset_memory_for_tests() -> None:
    """测试用：清内存缓存（不删文件，由测试控制文件）。"""
    global _STATE
    with _LOCK:
        _STATE = None


def snapshot_books(strategy_id: str) -> dict[str, dict[str, Any]]:
    st = load_state()
    out: dict[str, dict[str, Any]] = {}
    prefix = f"{strategy_id}:"
    for k, v in (st.get("positions") or {}).items():
        if str(k).startswith(prefix) and isinstance(v, dict):
            out[str(k)[len(prefix) :]] = deepcopy(v)
    return out


# 供文档 / 遥测
LIVE_TRIGGER_GRANULARITY = "quote_2_to_5s"
REPLAY_TRIGGER_GRANULARITY = "historical_bar_available"
BACKTEST_TRIGGER_GRANULARITY = "akquant_bar"
LIVE_STATE_RESTORE_SOURCE = "strategy_sim_state.json+strategy_signal_events.json"
JSON_SYNC_DURABLE_FILES = (
    "holdingStocks/strategy_sim_state.json",
    "holdingStocks/strategy_signal_events.json",
)
