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
        "cumulative_return_pct": 0.0,
        "single_return_pct": None,
        "closed_trade_return_pct": None,
    }


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
    """LONG：随 mark 更新累计；FLAT：equity=cash，cumulative 冻结。"""
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
        # FLAT：不因 mark 改 cumulative
        book["single_return_pct"] = None
        if quote_ts:
            book["last_quote_ts"] = str(quote_ts)


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
