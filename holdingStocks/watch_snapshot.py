"""盯盘 JSON 快照（WatchSnapshot v1）— 供 Vue 前端 / WebSocket 使用。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Callable


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


def _retag_strategy1_row(row: dict[str, Any]) -> dict[str, Any]:
    """策略一 Tab：非自选统一标「策略池」，避免热池因子27标签串台。"""
    out = dict(row)
    src = str(out.get("pool_src") or "")
    label = str(out.get("池来源") or "")
    if src == "self" or label == "自选":
        out["pool_src"] = "self"
        out["池来源"] = "自选"
    else:
        out["pool_src"] = "strategy1_pool"
        out["池来源"] = "策略池"
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

    排序：实仓置顶（最多 MAX_PORTFOLIO_SLOTS）→ 当日已平仓（不占槽）→ 预警/候选。
    平仓 = 纸面实仓止损/止盈卖出清仓；当日留痕（槽位留痕=True）不占槽，下一交易日清空。
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

    def _alert_trigger_sort_ts(r: dict[str, Any]) -> str:
        """预警栏：按触发时刻升序（早→晚）；无时刻排最后。"""
        sess = str(r.get("交易日") or "")[:10]
        for k in ("信号时刻", "买信号时间", "卖信号时间", "信号时间"):
            v = r.get(k)
            if v is None or v == "":
                continue
            s = str(v).strip()
            if not s:
                continue
            if " " not in s and sess and len(s) >= 8 and s[2:3] == ":":
                return f"{sess} {s[:8]}"
            if len(s) >= 19 and s[4:5] == "-" and " " in s:
                return s[:19]
            return s
        return "9999-99-99 99:99:99"

    def _sort_key(r: dict[str, Any]) -> tuple:
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
        if tier == 2:
            return (tier, _pos_rank(pos), _alert_trigger_sort_ts(r), str(r.get("代码") or ""))
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
        old_sess = str(row.get("交易日") or "")[:10]
        row["交易日"] = sess
        if qty <= 0:
            # 隔日平仓留痕：清空当日盈亏，避免盘前仍计入账户「今日」
            if old_sess and old_sess != sess:
                row["当日盈亏"] = None
                row["当日盈亏%"] = None
                row["当日基数"] = None
            out.append(row)
            continue
        try:
            from watch_config import infer_bought_today
        except ImportError:  # pragma: no cover
            from holdingStocks.watch_config import infer_bought_today

        bought_today = infer_bought_today(
            buy_time=row.get("买入时间") or row.get("buy_time"),
            session=sess,
            qty=qty,
            available=row.get("可用"),
            cost=row.get("成本"),
            day_base=row.get("当日基数"),
            prev_close=row.get("昨收"),
        )
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


def account_today_return_pct(day_pnl: Any, account_open: Any) -> float | None:
    """账户级今日收益率：day_pnl / 日初权益。分母缺省/非正/非有限 → None。

    不用 Σ逐票当日基数，避免同日先卖后买把资金重复计入分母。
    """
    if day_pnl is None or account_open is None or account_open == "":
        return None
    try:
        day = float(day_pnl)
        open_f = float(account_open)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(day) or not math.isfinite(open_f) or open_f <= 0:
        return None
    return round(day / open_f * 100.0, 2)


def apply_day_linked_account_equity(account: dict[str, Any]) -> dict[str, Any]:
    """总资产/总收益随今日盈亏滚动：总资产 = 日初锁定 + 今日盈亏。

    日初 `accountOpen` 应为昨收（或跨日结算）总资产；避免现金账本漂移时
    总收益卡在昨收不动。账户今日收益率分母同为日初权益。
    """
    acc = dict(account or {})
    day = acc.get("dayPnl")
    open_eq = acc.get("accountOpen")
    acc["dayPnlPct"] = account_today_return_pct(day, open_eq)
    if day is None or open_eq is None:
        return acc
    try:
        day_f = float(day)
        open_f = float(open_eq)
    except (TypeError, ValueError):
        return acc
    total = round(open_f + day_f, 2)
    acc["accountTotal"] = total
    acc["equityDayPnl"] = round(day_f, 2)
    base = acc.get("paperEquityBase")
    try:
        base_f = float(base) if base is not None else 0.0
    except (TypeError, ValueError):
        base_f = 0.0
    if base_f > 0:
        tp = round(total - base_f, 2)
        acc["totalPnl"] = tp
        acc["totalPnlPct"] = round(tp / base_f * 100.0, 2)
    mv = acc.get("marketValue")
    if mv is not None:
        try:
            acc["availableCash"] = round(total - float(mv), 2)
        except (TypeError, ValueError):
            pass
    if total and total > 0 and mv is not None:
        try:
            mv_f = float(mv)
            if mv_f > 0:
                acc["positionPct"] = round(mv_f / total * 100.0, 1)
        except (TypeError, ValueError):
            pass
    return acc


def _as_px_digits(row: dict[str, Any]) -> int:
    try:
        return max(0, int(row.get("价位小数") or 2))
    except (TypeError, ValueError):
        return 2


def _quote_last(q: dict[str, Any] | None) -> float | None:
    if not q:
        return None
    try:
        last = float(q.get("last"))
    except (TypeError, ValueError):
        return None
    return last if last > 0 else None


def patch_row_live_quote(
    row: dict[str, Any],
    quote: dict[str, Any] | None,
    *,
    enrich_hold_pnl: bool = False,
    strategy_id: str | None = None,
) -> bool:
    """用最新 tick 覆盖现价/涨跌幅（可选实仓当日盈亏）。已实现平仓不改盈亏。

    若 strategy_id 给定：同步 Strategy Simulator live 评估（Layer A，不碰 Paper）。
    """
    last = _quote_last(quote)
    if last is None:
        return False
    digits = _as_px_digits(row)
    prev_last = row.get("现价")
    try:
        same = prev_last is not None and abs(float(prev_last) - last) < 1e-9
    except (TypeError, ValueError):
        same = False
    changed = not same
    row["现价"] = round(last, digits)

    open_px = _as_pos_float(quote.get("open") if quote else None) or _as_pos_float(
        row.get("开盘")
    )
    prev = _as_pos_float(quote.get("prev_close") if quote else None) or _as_pos_float(
        row.get("昨收")
    )
    high = _as_pos_float(quote.get("high") if quote else None)
    low = _as_pos_float(quote.get("low") if quote else None)
    if open_px is not None and row.get("开盘") is None:
        row["开盘"] = round(open_px, digits)
        changed = True
    if prev is not None:
        old_prev = row.get("昨收")
        row["昨收"] = round(prev, digits)
        if old_prev != row["昨收"]:
            changed = True
        try:
            from trading_day import current_trading_session, sanitize_day_change_for_session
        except ImportError:  # pragma: no cover
            from holdingStocks.trading_day import (
                current_trading_session,
                sanitize_day_change_for_session,
            )

        q_sess = None
        if quote:
            q_sess = quote.get("session")
        chg = sanitize_day_change_for_session(
            quote_session=q_sess or row.get("交易日"),
            calendar_session=current_trading_session(),
            mark=last,
            previous_close=prev,
        )
        if row.get("当日涨幅") != chg:
            row["当日涨幅"] = chg
            changed = True
    if open_px is not None and open_px > 0:
        vs = round((last / open_px - 1.0) * 100.0, 2)
        if row.get("较开盘涨幅") != vs:
            row["较开盘涨幅"] = vs
            changed = True
        pts = round(last - open_px, digits)
        if row.get("较开盘点") != pts:
            row["较开盘点"] = pts
            changed = True
    if high is not None:
        ts = None
        if quote:
            ts = quote.get("last_ts") or quote.get("ts") or quote.get("time")
        try:
            from watch_config import trust_quote_day_high
            from strategy.pullback_wave_stop import usable_session_high
        except ImportError:  # pragma: no cover
            from holdingStocks.watch_config import trust_quote_day_high
            from strategy.pullback_wave_stop import usable_session_high

        printed = usable_session_high(
            quote_high=high,
            open_px=float(open_px or 0),
            last_px=last,
            trust_api_high=trust_quote_day_high(ts),
        )
        if printed <= 0:
            printed = last
        day_high = round(printed, digits)
        if day_high > 0:
            row["最高"] = day_high
            row["今日最高"] = day_high
    if low is not None and low > 0:
        row["最低"] = round(min(low, last), digits)

    buy = _as_pos_float(row.get("买点"))
    if buy is not None and buy > 0:
        dist = round((last / buy - 1.0) * 100.0, 2)
        if row.get("距买点%") != dist:
            row["距买点%"] = dist
            changed = True

    if row.get("已实现"):
        return changed

    try:
        qty = int(row.get("持仓") or 0)
    except (TypeError, ValueError):
        qty = 0
    if qty > 0:
        mv = round(last * qty, 2)
        if row.get("市值") != mv:
            row["市值"] = mv
            changed = True
        if enrich_hold_pnl:
            cost = _as_pos_float(row.get("成本"))
            sess = str(row.get("交易日") or "")[:10]
            try:
                from watch_config import infer_bought_today
            except ImportError:  # pragma: no cover
                from holdingStocks.watch_config import infer_bought_today

            bought_today = infer_bought_today(
                buy_time=row.get("买入时间") or row.get("buy_time"),
                session=sess,
                qty=qty,
                available=row.get("可用"),
                cost=cost,
                day_base=row.get("当日基数"),
                prev_close=prev,
            )
            try:
                from strategy.akq_math import mark_unrealized, session_day_pnl

                if cost is not None:
                    pnl, pnl_pct = mark_unrealized(last, cost, qty)
                    if row.get("浮盈") != pnl:
                        row["浮盈"] = pnl
                        row["浮盈%"] = pnl_pct
                        changed = True
                day_pnl, day_pct, day_base = session_day_pnl(
                    mark=last,
                    qty=qty,
                    cost=cost,
                    prev_close=prev,
                    bought_today=bought_today,
                    fallback=open_px,
                )
                if day_pnl is not None and row.get("当日盈亏") != day_pnl:
                    row["当日盈亏"] = day_pnl
                    row["当日盈亏%"] = day_pct
                    row["当日基数"] = day_base
                    changed = True
            except Exception:  # noqa: BLE001
                pass
    # 现价变了：重算策略信号「单笔收入%」（触发价冻结，不写 ledger）
    try:
        from watch_buy_signal import enrich_signal_single_return

        before = row.get("单笔收入%")
        enrich_signal_single_return(row)
        if row.get("单笔收入%") != before:
            changed = True
    except Exception:  # noqa: BLE001
        pass

    # Layer A：Strategy Simulator — 每次 fresh quote 评估（不改 Paper）
    if strategy_id:
        try:
            from strategy_simulator import (
                apply_book_to_row,
                evaluate_live_transition,
                get_book,
            )

            code = str(row.get("代码") or "")
            if code:
                q_ts = None
                if quote:
                    q_ts = quote.get("ts") or quote.get("time") or quote.get("timestamp")
                if not q_ts:
                    from datetime import datetime as _dt

                    sess = str(row.get("交易日") or "")[:10]
                    q_ts = f"{sess} {_dt.now().strftime('%H:%M:%S')}" if sess else _dt.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                buy_lv = row.get("买点") if row.get("买点") is not None else row.get("买入侧价")
                sell_lv = row.get("止损") if row.get("止损") is not None else row.get("卖出侧价")
                allow = bool(row.get("过门OK")) or str(row.get("已触买") or "") == "是"
                before_st = row.get("策略模拟状态")
                before_ret = row.get("策略收益%")
                before_single = row.get("单笔收入%")
                evaluate_live_transition(
                    strategy_id=str(strategy_id),
                    symbol=code,
                    live_last=float(last),
                    quote_ts=str(q_ts) if q_ts else None,
                    buy_level=float(buy_lv) if buy_lv is not None else None,
                    sell_level=float(sell_lv) if sell_lv is not None else None,
                    allow_entry=allow,
                    reason="quote_patch",
                    persist=True,
                    t0=bool(row.get("t0")),
                    day_open=row.get("开盘")
                    or (quote.get("open") if isinstance(quote, dict) else None),
                )
                book = get_book(str(strategy_id), code)
                apply_book_to_row(row, book)
                if (
                    row.get("策略模拟状态") != before_st
                    or row.get("策略收益%") != before_ret
                    or row.get("单笔收入%") != before_single
                ):
                    changed = True
        except Exception:  # noqa: BLE001
            pass
    return changed


def _clone_row_list(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(r) for r in (rows or []) if isinstance(r, dict)]


def clone_snapshot_for_quote_patch(snap: dict[str, Any]) -> dict[str, Any]:
    """浅拷贝快照 + 深拷贝行情相关行，避免与全量扫描互相踩踏。"""
    out = dict(snap)
    for key in (
        "holdings",
        "strategy1",
        "strategy3",
        "strategy15",
        "strategy16",
        "strategy17",
    ):
        val = snap.get(key)
        if isinstance(val, list):
            out[key] = _clone_row_list(val)
        elif isinstance(val, dict) and key == "strategy3":
            # strategy3 可能是 dict 包 rows
            out[key] = dict(val)
            if isinstance(val.get("rows"), list):
                out[key]["rows"] = _clone_row_list(val.get("rows"))
            if isinstance(val.get("boards"), list):
                out[key]["boards"] = _clone_row_list(val.get("boards"))
        elif isinstance(val, dict) and key in ("strategy8", "strategy15"):
            out[key] = dict(val)
    if isinstance(snap.get("strategy8"), dict):
        s8 = dict(snap["strategy8"])
        themes = s8.get("themes")
        if isinstance(themes, list):
            s8["themes"] = [dict(t) if isinstance(t, dict) else t for t in themes]
        out["strategy8"] = s8
    if isinstance(snap.get("account"), dict):
        out["account"] = dict(snap["account"])
    if isinstance(snap.get("indices"), list):
        out["indices"] = [dict(x) if isinstance(x, dict) else x for x in snap["indices"]]
    return out


def patch_snapshot_live_quotes(
    snap: dict[str, Any],
    *,
    get_quote: Callable[[str], dict[str, Any] | None],
    sina_of: Callable[[str], str] | None = None,
) -> bool:
    """盘中快刷：现价/涨跌幅；策略 Tab 同步 Layer A Simulator（不改 Paper 成交）。"""
    if sina_of is None:
        from watch_config import sina_of as _sina_of

        sina_of = _sina_of

    def _q_for(row: dict[str, Any]) -> dict[str, Any] | None:
        code = str(row.get("代码") or "")
        if not code:
            return None
        try:
            return get_quote(sina_of(code))
        except Exception:  # noqa: BLE001
            return None

    changed = False
    holdings = list(snap.get("holdings") or [])
    for r in holdings:
        if patch_row_live_quote(r, _q_for(r), enrich_hold_pnl=True):
            changed = True
    snap["holdings"] = holdings

    for key in ("strategy1", "strategy16", "strategy17"):
        rows = list(snap.get(key) or [])
        if not rows:
            continue
        for r in rows:
            if patch_row_live_quote(
                r, _q_for(r), enrich_hold_pnl=False, strategy_id=key
            ):
                changed = True
        snap[key] = rows

    # strategy15 可能是 list 或 dict.rows
    s15 = snap.get("strategy15")
    if isinstance(s15, list):
        for r in s15:
            if isinstance(r, dict) and patch_row_live_quote(
                r, _q_for(r), enrich_hold_pnl=False, strategy_id="strategy15"
            ):
                changed = True
    elif isinstance(s15, dict):
        rows = list(s15.get("rows") or s15.get("stocks") or [])
        for r in rows:
            if isinstance(r, dict) and patch_row_live_quote(
                r, _q_for(r), enrich_hold_pnl=False, strategy_id="strategy15"
            ):
                changed = True

    # 账户：按持仓行重加今日盈亏，并日初+今日滚动总收益
    day_sum = 0.0
    has_day = False
    total_mv = 0.0
    for r in holdings:
        try:
            qty = int(r.get("持仓") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0 and not r.get("已实现"):
            continue
        if r.get("当日盈亏") is not None:
            has_day = True
            day_sum += float(r["当日盈亏"])
        if qty > 0 and r.get("市值") is not None:
            total_mv += float(r["市值"])
    acc = dict(snap.get("account") or {})
    if has_day:
        acc["dayPnl"] = round(day_sum, 2)
        changed = True
    if total_mv > 0:
        acc["marketValue"] = round(total_mv, 2)
    snap["account"] = apply_day_linked_account_equity(acc)
    return changed


def rebase_snapshot_day_pnl(snap: dict[str, Any], *, session: str) -> dict[str, Any]:
    """对整份快照重算持仓今日盈亏，并刷新账户合计 dayPnl/总收益。"""
    out = dict(snap)
    holdings = rebase_holdings_day_pnl(list(out.get("holdings") or []), session=session)
    out["holdings"] = holdings
    day_sum = 0.0
    has_day = False
    for r in holdings:
        try:
            qty = int(r.get("持仓") or 0)
        except (TypeError, ValueError):
            qty = 0
        # 与账户合计口径一致：实仓 + 当日已实现平仓
        if qty <= 0 and not r.get("已实现"):
            continue
        if r.get("当日盈亏") is None:
            continue
        has_day = True
        day_sum += float(r["当日盈亏"])
    acc = dict(out.get("account") or {})
    if has_day:
        acc["dayPnl"] = round(day_sum, 2)
    else:
        acc["dayPnl"] = None
    out["account"] = apply_day_linked_account_equity(acc)
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
    strategy17: list[dict[str, Any]] | None = None,
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
        if src == "factor28" or label == "紫阳真君":
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
    try:
        from watch_config import strategy1_codes as _s1_codes_fn

        s1_codes = _s1_codes_fn()
    except Exception:  # noqa: BLE001
        s1_codes = set(strategy_codes)
    strategy1_rows = _sort_pool_rows(
        [
            _retag_strategy1_row(_strip_holdings_pnl(r))
            for r in rows
            if code_key(str(r.get("代码") or "")) in s1_codes
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
    try:
        from watch_config import ziyang_codes

        s17_codes = ziyang_codes()
    except Exception:  # noqa: BLE001
        s17_codes = set()
    if strategy17 is not None:
        strategy17_rows = list(strategy17)
    else:
        strategy17_rows = _sort_pool_rows(
            [
                _strip_holdings_pnl(r)
                for r in rows
                if code_key(str(r.get("代码") or "")) in s17_codes
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
            from watch_config import MAX_PORTFOLIO_SLOTS as _max_slots
            from watch_config import SLOT_WEIGHT as _slot_w

            slot_meta = {
                "max": int(_max_slots),
                "weight": float(_slot_w),
                "occupied": [],
                "occupiedCount": 0,
                "free": int(_max_slots),
            }
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
        "strategy17": strategy17_rows,
        "sectors": sectors or {},
        "strategies": strategies or [],
    }
