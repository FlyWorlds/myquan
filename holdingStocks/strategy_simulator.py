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
) -> dict[str, Any]:
    """用 live last 撞 buy/sell level；仅状态转换产生事件。

    BUY：FLAT + allow_entry + last >= buy_level
    SELL：LONG + last <= sell_level

    条件语义保持 touch（>= / <=），不是 cross。
    返回 {transition, book, event, telemetry}。
    """
    eval_t = evaluation_time or _now_str()
    stale_lim = (
        float(stale_after)
        if stale_after is not None
        else LIVE_QUOTE_STALE_AFTER_SECONDS
    )
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

        if state == "FLAT":
            try:
                buy_lv = float(buy_level) if buy_level is not None else None
            except (TypeError, ValueError):
                buy_lv = None
            if allow_entry and buy_lv is not None and buy_lv > 0 and last + 1e-12 >= buy_lv:
                shares, cash_left, _ = _buy_shares(float(book["virtual_cash"]), last)
                if shares >= LOT:
                    book["state"] = "LONG"
                    book["entry_price"] = round(last, 4)
                    book["entry_time"] = str(quote_ts or eval_t)
                    book["exit_price"] = None
                    book["exit_time"] = None
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
                    }
        elif state == "LONG":
            try:
                sell_lv = float(sell_level) if sell_level is not None else None
            except (TypeError, ValueError):
                sell_lv = None
            if sell_lv is not None and sell_lv > 0 and last <= sell_lv + 1e-12:
                shares = float(book.get("virtual_shares") or 0.0)
                entry = float(book.get("entry_price") or 0.0)
                proceeds = shares * last
                book["virtual_cash"] = float(book.get("virtual_cash") or 0.0) + proceeds
                book["virtual_shares"] = 0.0
                book["state"] = "FLAT"
                book["exit_price"] = round(last, 4)
                book["exit_time"] = str(quote_ts or eval_t)
                book["trades"] = int(book.get("trades") or 0) + 1
                if entry > 0:
                    book["closed_trade_return_pct"] = round((last / entry - 1.0) * 100.0, 2)
                book["single_return_pct"] = None
                init = float(book.get("initial_cash") or INITIAL_CASH)
                book["cumulative_return_pct"] = round(
                    (float(book["virtual_cash"]) / init - 1.0) * 100.0, 2
                )
                book["last_mark"] = None
                transition = "SELL"
                event = {
                    "event_id": _event_id(
                        strategy_id, symbol, "SELL", book["exit_time"], last
                    ),
                    "strategy_id": strategy_id,
                    "symbol": _code_key(symbol),
                    "side": "SELL",
                    "trigger_price": round(last, 4),
                    "trigger_time": book["exit_time"],
                    "quote_timestamp": quote_ts,
                    "reason": reason,
                    "trading_session_date": str(book["exit_time"])[:10],
                    "sell_level": sell_lv,
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
    row["策略累计持有"] = state == "LONG"
    row["单笔收入%"] = book.get("single_return_pct")
    if book.get("entry_time"):
        row["信号时间"] = book.get("entry_time") if state == "LONG" else book.get("exit_time")


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
