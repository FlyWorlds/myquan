"""盯盘 JSON 快照（WatchSnapshot v1）— 供 Vue 前端 / WebSocket 使用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


SNAPSHOT_VERSION = 1


def _row_json(row: dict[str, Any]) -> dict[str, Any]:
    """collect_rows 行 → JSON 可序列化 dict（保留中文键，与现有逻辑一致）。"""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if str(k).startswith("_"):
            continue
        if k == "bg_class":
            out["bgClass"] = v
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _strip_holdings_pnl(row: dict[str, Any]) -> dict[str, Any]:
    """策略 Tab 用：去掉持仓口径浮盈/结算金额，仅保留信号与策略收益%。"""
    out = _row_json(row)
    for k in ("浮盈", "浮盈%", "盈亏状态", "盈亏说明", "策略收益", "市值", "成本额", "当日基数"):
        out.pop(k, None)
    return out


def _index_json(ix: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": ix.get("code"),
        "name": ix.get("name"),
        "market": ix.get("market"),
        "price": ix.get("price"),
        "chgPoints": ix.get("chg_points"),
        "chgPct": ix.get("chg_pct"),
        "error": ix.get("error"),
    }


from watch_buy_signal import (
    is_buy_hit as _is_buy_hit,
    is_holdings_tab_signal_row as _is_holdings_tab_signal_row,
    is_paper_strategy_hold as _is_paper_strategy_hold,
    is_replay_stop_signal as _is_replay_stop_signal,
)


def filter_portfolio_holdings(
    rows: list[dict[str, Any]],
    portfolio_codes: set[str] | None = None,
    *,
    phase: str | None = None,
    strategy_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """持仓 Tab：实仓 + 当日已平仓留痕 + 默认策略池当日买点预警。

    排序：实仓置顶（最多 MAX_PORTFOLIO_SLOTS=4）→ 当日已平仓（不占槽）→ 预警/候选。
    平仓 = 四槽实仓止损/止盈卖出清仓；当日留痕（槽位留痕=True）不占槽，下一交易日清空。
    买点预警仅默认策略池（strategy16=核心龙头）；旧 portfolio_pool 空壳不进持仓 Tab。
    竞价：仍展示实仓 + 当日已平仓；其它空仓预警不进持仓 Tab。
    连续竞价与午休：当日买点预警进持仓 Tab。
    收盘：当日已触买仍留在预警栏（当天不摘），将买入等接近信号不留。
    """
    from watch_config import (
        MAX_PORTFOLIO_SLOTS,
        code_key,
        market_phase,
        portfolio_pool_codes,
        strategy_watchlist_codes,
    )

    if portfolio_codes is None:
        try:
            from index import load_holdings

            portfolio_codes = set(portfolio_pool_codes(load_holdings()))
        except Exception:  # noqa: BLE001
            portfolio_codes = set()
    # 兼容旧参数：展示宇宙改由 strategy_codes + 实仓/已平仓决定
    _ = portfolio_codes
    if strategy_codes is None:
        try:
            strategy_codes = set(strategy_watchlist_codes())
        except Exception:  # noqa: BLE001
            strategy_codes = set()

    def _slot_sold_qty(r: dict[str, Any]) -> int:
        try:
            return int(r.get("卖出数量") or 0)
        except (TypeError, ValueError):
            return 0

    def _is_closed_trace(r: dict[str, Any]) -> bool:
        """三槽实仓清仓留痕：已实现成交，或昨仓/今仓有卖出股数。不含策略回放未入槽。"""
        if bool(r.get("已实现")) or bool(r.get("三槽平仓")):
            return True
        return _slot_sold_qty(r) > 0

    phase_now = phase if phase is not None else market_phase()
    # 竞价只留实仓+已平仓；连续竞价/午休展示当日买点预警；收盘只留已触买
    holdings_only = phase_now not in ("continuous", "lunch", "closed")

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        c = code_key(str(r.get("代码") or ""))
        qty = int(r.get("持仓") or 0)
        closed_trace = qty <= 0 and _is_closed_trace(r)
        # 行情失败仍留实仓/当日平仓留痕；空仓 error 行不进持仓 Tab
        if r.get("error") and qty <= 0 and not closed_trace:
            continue
        # 买点预警：仅默认策略池；不把旧池空壳/别的策略票灌进持仓 Tab
        keep_empty_alert = phase_now in ("continuous", "lunch") or (
            phase_now == "closed" and _is_buy_hit(r)
        )
        alert_only = (
            keep_empty_alert
            and qty <= 0
            and (not closed_trace)
            and c in strategy_codes
            and _is_holdings_tab_signal_row(r)
        )
        if qty <= 0 and not closed_trace and not alert_only:
            continue
        if c in seen:
            continue
        seen.add(c)
        out = dict(r)
        if closed_trace:
            out["当日预警"] = False
            out["槽位候选"] = False
            out["槽位占用"] = False
            out["槽位留痕"] = True
            out["持仓"] = 0
            out.setdefault("持仓状态", "今日平仓")
            alert0 = str(out.get("预警") or "").strip()
            if (not alert0) or alert0 in (
                "-",
                "持有",
                "已经买入",
                "空仓",
                "止损成交",
                "今日平仓",
                "已平仓",
                "已触止损平仓",
            ):
                out["预警"] = "已触止损"  # 信号；持仓态另见「今日平仓」
        elif alert_only:
            out["当日预警"] = True
            out["槽位留痕"] = False
            out["持仓"] = 0
            out["浮盈"] = None
            out["浮盈%"] = None
            out["盈亏状态"] = None
            if _is_paper_strategy_hold(r):
                out["盈亏说明"] = "策略持有·未登记仓"
            elif _is_replay_stop_signal(r):
                out["盈亏说明"] = "策略回放止损·未入三槽"
            else:
                out["盈亏说明"] = "当日预警·未登记持仓"
            out["市值"] = None
            out["成本额"] = None
            out["仓位%"] = None
        else:
            out.setdefault("当日预警", False)
            out["槽位留痕"] = False
        if holdings_only and qty > 0:
            out["当日预警"] = False
            out["槽位候选"] = False
        picked.append(out)

    def _pos_rank(pos: str) -> int:
        if pos == "待卖出":
            return 0
        if pos in ("已经买入", "持有", "持有·T+1"):
            return 1
        if pos == "策略持有":
            return 2
        if pos in ("今日平仓", "已平仓", "已止损", "已触止损平仓", "当日禁买"):
            return 3
        return 4

    def _sort_key(r: dict[str, Any]) -> tuple[int, int, float, str]:
        qty = int(r.get("持仓") or 0)
        pos = str(r.get("持仓状态") or "")
        if qty > 0 or bool(r.get("槽位占用")):
            tier = 0
        elif bool(r.get("槽位留痕")) or bool(r.get("已实现")):
            tier = 1
        elif bool(r.get("当日预警")) or bool(r.get("槽位候选")) or pos == "待买入":
            tier = 2
        else:
            tier = 3
        try:
            dist = float(r.get("距买点%") if r.get("距买点%") is not None else 9_999.0)
        except (TypeError, ValueError):
            dist = 9_999.0
        return (tier, _pos_rank(pos), dist, str(r.get("代码") or ""))

    ordered = sorted(picked, key=_sort_key)
    pinned = 0
    max_pin = int(MAX_PORTFOLIO_SLOTS)
    for r in ordered:
        qty = int(r.get("持仓") or 0)
        if qty > 0 and pinned < max_pin:
            r["置顶"] = True
            r["槽位占用"] = True
            r["槽位留痕"] = False
            pinned += 1
        else:
            r["置顶"] = False
            if bool(r.get("槽位留痕")):
                r["槽位占用"] = False
            else:
                r["槽位占用"] = bool(qty > 0)
    return ordered


def _occupied_codes(snap: dict[str, Any] | None) -> set[str]:
    if not snap:
        return set()
    occ = (snap.get("slotMeta") or {}).get("occupied") or []
    return {str(c).zfill(6) for c in occ if c}


def _holding_session_dates(snap: dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    for r in (snap or {}).get("holdings") or []:
        day = str(r.get("交易日") or "")[:10]
        if len(day) >= 10:
            out.add(day)
    return out


def _as_pos_float(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x <= 0:  # NaN / non-positive
        return None
    return x


def rebase_holdings_day_pnl(
    holdings: list[dict[str, Any]],
    *,
    session: str,
) -> list[dict[str, Any]]:
    """新交易日：昨仓今日盈亏按昨收重算；今买仍相对成本。

    跨日沿用快照时，昨仓若仍挂着买入日「相对成本」的当日盈亏会错成「今日浮亏」。
    """
    sess = str(session or "")[:10]
    if len(sess) < 10:
        return [dict(r) for r in holdings]
    out: list[dict[str, Any]] = []
    for r in holdings:
        row = dict(r)
        qty = int(row.get("持仓") or 0)
        row["交易日"] = sess
        if qty <= 0:
            out.append(row)
            continue
        buy = str(row.get("买入时间") or "")[:10]
        bought_today = bool(buy and buy == sess)
        last = _as_pos_float(row.get("现价"))
        if last is None:
            out.append(row)
            continue
        if bought_today:
            cost = _as_pos_float(row.get("成本"))
            if cost is None:
                out.append(row)
                continue
            pnl = (last - cost) * qty
            pct = (last / cost - 1.0) * 100.0
            row["当日盈亏"] = round(pnl, 2)
            row["当日盈亏%"] = round(pct, 2)
            row["当日基数"] = round(cost * qty, 2)
            row["盈亏说明"] = f"今买 {cost} × {qty} 股，现价相对买入价"
        else:
            prev = _as_pos_float(row.get("昨收"))
            if prev is None:
                # 无昨收时宁可清空，避免沿用买入日相对成本的旧「今日」数字
                row["当日盈亏"] = None
                row["当日盈亏%"] = None
                row["当日基数"] = None
                row["盈亏说明"] = "昨仓待昨收：9:15 后按昨收重算"
            else:
                pnl = (last - prev) * qty
                pct = (last / prev - 1.0) * 100.0
                row["当日盈亏"] = round(pnl, 2)
                row["当日盈亏%"] = round(pct, 2)
                row["当日基数"] = round(prev * qty, 2)
                row["盈亏说明"] = f"昨收 {prev} × {qty} 股，现价相对昨收"
        out.append(row)
    return out


def rebase_snapshot_day_pnl(snap: dict[str, Any], *, session: str) -> dict[str, Any]:
    """对整份快照重算持仓今日盈亏，并刷新账户合计 dayPnl。"""
    out = dict(snap)
    holdings = rebase_holdings_day_pnl(list(out.get("holdings") or []), session=session)
    out["holdings"] = holdings
    day_sum = 0.0
    day_base = 0.0
    has_day = False
    for r in holdings:
        if int(r.get("持仓") or 0) <= 0:
            continue
        if r.get("当日盈亏") is None:
            continue
        has_day = True
        day_sum += float(r["当日盈亏"])
        db = r.get("当日基数")
        if db is not None and float(db) > 0:
            day_base += float(db)
    acc = dict(out.get("account") or {})
    if has_day:
        acc["dayPnl"] = round(day_sum, 2)
        acc["dayPnlPct"] = (
            round(day_sum / day_base * 100.0, 2) if day_base > 0 else None
        )
    else:
        acc["dayPnl"] = None
        acc["dayPnlPct"] = None
    out["account"] = acc
    return out


def snapshot_needs_day_pnl_rebase(
    snap: dict[str, Any] | None,
    *,
    session: str,
) -> bool:
    """持仓行交易日与当前 session 不一致 → 需按昨收重算今日盈亏。"""
    sess = str(session or "")[:10]
    if len(sess) < 10 or not snap:
        return False
    days = _holding_session_dates(snap)
    if not days:
        return False
    return days != {sess}


def should_keep_last_snapshot(
    *,
    rows: list[dict[str, Any]],
    snapshot: dict[str, Any],
    prev: dict[str, Any] | None,
) -> bool:
    """先记录再更新：新快照未就绪时不得把上一份可用表置空。

    账本槽位变了必须出新快照（成交优先于行情）。
    启动占位 / 上一份本身是空表则不保留。
    """
    if not prev or prev.get("type") != "snapshot" or prev.get("boot"):
        return False
    prev_h = prev.get("holdings") or []
    prev_s16 = prev.get("strategy16") or []
    if not prev_h and not prev_s16:
        return False
    if _occupied_codes(snapshot) != _occupied_codes(prev):
        return False
    new_h = snapshot.get("holdings") or []
    new_s16 = snapshot.get("strategy16") or []
    live = [r for r in rows if not r.get("error")]
    if rows and not live:
        return True
    if _occupied_codes(snapshot) and prev_h and not new_h:
        return True
    if prev_s16 and not new_s16:
        return True
    return False


def retain_last_snapshot(
    prev: dict[str, Any],
    *,
    clock: str,
    phase: str,
    phase_key: str,
    session: str | None = None,
) -> dict[str, Any]:
    """沿用上一份表，只刷新时钟/相位，并标行情未就绪。

    跨交易日时按昨收重算今日盈亏（避免昨仓仍显示买入日相对成本的浮亏）。
    """
    snap = dict(prev)
    prev_quote_at = prev.get("quoteAt") or prev.get("clock")
    snap["clock"] = clock
    snap["updatedAt"] = clock
    snap["ts"] = int(datetime.now().timestamp() * 1000)
    snap["phase"] = phase
    snap["phaseKey"] = phase_key
    snap["quoteStale"] = True
    snap["feedOk"] = False
    if prev_quote_at:
        snap["quoteAt"] = prev_quote_at
    snap.pop("boot", None)
    sess = str(session or "")[:10]
    if len(sess) >= 10 and snapshot_needs_day_pnl_rebase(snap, session=sess):
        snap = rebase_snapshot_day_pnl(snap, session=sess)
    return snap


def apply_feed_health(
    snap: dict[str, Any],
    health: dict[str, Any] | None,
    *,
    keep_stale: bool = False,
) -> dict[str, Any]:
    """把行情源健康度打进快照。keep_stale 用于沿用旧表时强制 quoteStale。"""
    health = health or {}
    if "feedOk" in health:
        snap["feedOk"] = bool(health.get("feedOk"))
    if keep_stale or health.get("quoteStale"):
        snap["quoteStale"] = True
    else:
        snap["quoteStale"] = False
    quote_at = health.get("quoteAt")
    if quote_at:
        snap["quoteAt"] = quote_at
    elif snap.get("quoteStale") and not snap.get("quoteAt"):
        snap["quoteAt"] = snap.get("clock")
    if health.get("quoteAgeSec") is not None:
        snap["quoteAgeSec"] = health.get("quoteAgeSec")
    return snap


def build_watch_snapshot(
    *,
    rows: list[dict[str, Any]],
    indices: list[dict[str, Any]],
    account: dict[str, Any],
    meta: dict[str, Any],
    strategies: list[dict[str, Any]] | None = None,
    strategy3: dict[str, Any] | None = None,
    strategy8: dict[str, Any] | None = None,
    strategy15: dict[str, Any] | None = None,
    sectors: dict[str, Any] | None = None,
    refresh_sec: int = 5,
    portfolio_codes: set[str] | None = None,
    strategy_codes: set[str] | None = None,
) -> dict[str, Any]:
    """构建 WatchSnapshot v1。"""
    from watch_config import code_key, strategy_watchlist_codes

    if strategy_codes is None:
        strategy_codes = strategy_watchlist_codes()

    def _pool_cat_tier(r: dict[str, Any]) -> int:
        src = str(r.get("pool_src") or "")
        label = str(r.get("池来源") or "")
        if src == "self" or label == "自选":
            return 0
        if src == "factor27" or label == "因子27":
            return 1
        return 2

    def _dist(r: dict[str, Any]) -> float:
        try:
            return float(r.get("距买点%") if r.get("距买点%") is not None else 9_999.0)
        except (TypeError, ValueError):
            return 9_999.0

    def _sort_pool_rows(xs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            xs,
            key=lambda r: (
                _pool_cat_tier(r),
                _dist(r),
                code_key(str(r.get("代码") or "")),
            ),
        )

    holdings = [
        _row_json(r)
        for r in filter_portfolio_holdings(rows, portfolio_codes=portfolio_codes)
    ]
    strategy1_rows = _sort_pool_rows(
        [
            _strip_holdings_pnl(r)
            for r in rows
            if code_key(str(r.get("代码") or "")) in strategy_codes
        ]
    )
    try:
        from watch_config import core_leader_codes

        s16_codes = core_leader_codes()
    except Exception:  # noqa: BLE001
        s16_codes = set()
    strategy16_rows = _sort_pool_rows(
        [
            _strip_holdings_pnl(r)
            for r in rows
            if code_key(str(r.get("代码") or "")) in s16_codes
        ]
    )
    slot_meta = None
    for r in rows:
        if isinstance(r.get("_slot_meta"), dict):
            slot_meta = r["_slot_meta"]
            break
    if slot_meta is None:
        try:
            from watch_config import slot_meta as _sm
            from index import load_holdings

            slot_meta = _sm(load_holdings())
        except Exception:  # noqa: BLE001
            slot_meta = {"max": 4, "weight": 0.25, "occupied": [], "occupiedCount": 0, "free": 4}
    return {
        "v": SNAPSHOT_VERSION,
        "type": "snapshot",
        "ts": int(datetime.now().timestamp() * 1000),
        "updatedAt": meta.get("clock") or "",
        "clock": meta.get("clock") or "",
        "phase": meta.get("phase") or "",
        "phaseKey": meta.get("phaseKey") or "",
        "refreshSec": int(refresh_sec),
        "quoteStale": False,
        "feedOk": True,
        "quoteAt": meta.get("quoteAt") or meta.get("clock") or "",
        "strategy": {
            "id": meta.get("strategyId") or "",
            "name": meta.get("strategyName") or "",
            "factorsLabel": meta.get("factorsLabel") or "",
        },
        "account": account,
        "slotMeta": slot_meta,
        "indices": [_index_json(ix) for ix in indices],
        "holdings": holdings,
        "strategy1": strategy1_rows,
        "strategy3": strategy3 or {},
        "strategy8": strategy8 or {},
        "strategy15": strategy15 or {},
        "strategy16": strategy16_rows,
        "sectors": sectors or {},
        "strategies": strategies or [],
    }
