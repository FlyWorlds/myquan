"""盯盘标的池与代码工具（唯一真源；index 从此处导入）。

当前锁定：**默认策略 = 策略十六（核心龙头） = 因子27 + 因子26 + 因子2 + 因子22**。
默认交易池：因子27 核心龙头近 3 个月冻结池，并额外纳入天通/凯盛。
策略三（旧号策略七）三票完整配置保留为 S7_WATCHLIST（含因子4）；改 STRATEGY_ID / USE_FACTOR4 / WATCHLIST 可切换。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from strategy.open_break import DEFAULT_PCT, TICK_SIZE, is_t1_buy_day

# 默认定盘：策略十六 + 因子27/因子26/因子2/因子22
STRATEGY_ID = "strategy16"
FACTOR_ID = "factor26"
FACTOR2_ID = "factor2"
FACTOR22_ID = "factor22"
FACTOR4_ID = "factor4"
STRATEGY_NAME = "策略十六·核心龙头"
# 策略三（旧号策略七）才叠因子4；默认核心龙头关闭
USE_FACTOR4 = False

# 早盘节点（A 股集合竞价 + 连续竞价）
AUCTION_START_HOUR = 9
AUCTION_START_MINUTE = 15  # 9:15 起拉竞价行情；报单可撤
AUCTION_NO_CANCEL_HOUR = 9
AUCTION_NO_CANCEL_MINUTE = 20  # 9:20 起不可撤单
AUCTION_OPEN_HOUR = 9
AUCTION_OPEN_MINUTE = 25  # 9:25 开盘价确定 → 算过门/买点/止损
SIGNAL_ACTIVE_HOUR = 9
SIGNAL_ACTIVE_MINUTE = 30  # 9:30 连续竞价 → 触发买卖/止损结算/微信

# 策略一盯盘：单票策略收益统计起点（含费用、T+1；自该交易日起空仓起算）
STRATEGY_PNL_START = "2026-09-01"

# 开盘价强制刷新（与 9:25 对齐）
OPEN_PRICE_REFRESH_HOUR = AUCTION_OPEN_HOUR
OPEN_PRICE_REFRESH_MINUTE = AUCTION_OPEN_MINUTE

# watch 里程碑：(时, 分, 日志标签, 动作 reseed|open|refresh)
AUCTION_MILESTONES: tuple[tuple[int, int, str, str], ...] = (
    (9, 15, "竞价开始·拉行情（可撤单）", "reseed"),
    (9, 20, "竞价·不可撤单", "refresh"),
    (9, 25, "开盘价确定·算阈值/过门", "open"),
    (9, 30, "连续竞价·信号触发", "refresh"),
)

INDEX_WATCH: list[dict[str, str]] = [
    {"code": "sh000001", "name": "上证指数", "market": "上证"},
    {"code": "sz399001", "name": "深证成指", "market": "深证"},
]


def _clock_minutes(now: Any | None = None) -> int:
    from datetime import datetime as _dt

    ts = now if isinstance(now, _dt) else _dt.now()
    return int(ts.hour) * 60 + int(ts.minute)


def market_phase(now: Any | None = None) -> str:
    """盘前 / 竞价 / 连续竞价 / 午休 / 收盘。连续竞价仅 9:30–11:30、13:00–15:00。"""
    m = _clock_minutes(now)
    a15 = AUCTION_START_HOUR * 60 + AUCTION_START_MINUTE
    a20 = AUCTION_NO_CANCEL_HOUR * 60 + AUCTION_NO_CANCEL_MINUTE
    a25 = AUCTION_OPEN_HOUR * 60 + AUCTION_OPEN_MINUTE
    a30 = SIGNAL_ACTIVE_HOUR * 60 + SIGNAL_ACTIVE_MINUTE
    lunch_start = 11 * 60 + 30
    lunch_end = 13 * 60
    close_m = 15 * 60
    if m < a15:
        return "pre_auction"
    if m < a20:
        return "auction_cancel"
    if m < a25:
        return "auction_locked"
    if m < a30:
        return "open_set"
    if m < lunch_start:
        return "continuous"
    if m < lunch_end:
        return "lunch"
    if m < close_m:
        return "continuous"
    return "closed"


def market_phase_label(phase: str | None = None, *, now: Any | None = None) -> str:
    ph = phase or market_phase(now)
    labels = {
        "pre_auction": "盘前（9:15 前）",
        "auction_cancel": "集合竞价·可撤单（9:15–9:20）",
        "auction_locked": "集合竞价·不可撤单（9:20–9:25）",
        "open_set": "开盘价已出·阈值盯盘（9:25–9:30）",
        "continuous": "连续竞价·信号触发（9:30–11:30 / 13:00–15:00）",
        "lunch": "午休（11:30–13:00）",
        "closed": "收盘（15:00 后）",
    }
    return labels.get(ph, ph)


def is_auction_quote_window(now: Any | None = None) -> bool:
    """9:15 起拉竞价行情（watch 高频刷新）。"""
    return _clock_minutes(now) >= (
        AUCTION_START_HOUR * 60 + AUCTION_START_MINUTE
    )


def is_threshold_ready(now: Any | None = None) -> bool:
    """9:25 起用开盘价算过门/买点/止损（9:30 前不结算）。"""
    return _clock_minutes(now) >= (
        AUCTION_OPEN_HOUR * 60 + AUCTION_OPEN_MINUTE
    )


def is_signal_window(now: Any | None = None) -> bool:
    """仅连续竞价时段允许因子触发/止损结算/微信预警（不含午休、收盘后）。"""
    return market_phase(now) == "continuous"


def is_close_confirmed(now: Any | None = None) -> bool:
    """尾盘集合竞价后视为收盘确认（因子22 mode=close）。"""
    return _clock_minutes(now) >= 14 * 60 + 57


def is_auction_window(now: Any | None = None) -> bool:
    """是否处于集合竞价时段 09:15–09:30（不含 09:30）。"""
    t = _clock_minutes(now)
    start = AUCTION_START_HOUR * 60 + AUCTION_START_MINUTE
    end = SIGNAL_ACTIVE_HOUR * 60 + SIGNAL_ACTIVE_MINUTE
    return start <= t < end


def code_key(code: str) -> str:
    return "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]


def sina_of(code: str) -> str:
    c = code_key(code)
    return f"sh{c}" if c.startswith(("5", "6")) else f"sz{c}"


def market_of(code: str) -> str:
    return "上证" if sina_of(code).startswith("sh") else "深证"


def watch_item(
    code: str,
    name: str,
    *,
    pct: float = DEFAULT_PCT,
    entry_pct: float | None = None,
    stop_pct: float | None = None,
    tick: float = TICK_SIZE,
    t0: bool = False,
    limit_down_pct: float = 0.10,
    prev_entry_mode: str = "yin_or_small_yang",
    factor4_kind: str | None = None,
    factor4_params: dict[str, Any] | None = None,
    factor4_stop_widen_mult: float | None = None,
) -> dict[str, Any]:
    c = code_key(code)
    ep = float(entry_pct if entry_pct is not None else pct)
    sp = float(stop_pct if stop_pct is not None else pct)
    item: dict[str, Any] = {
        "code": c,
        "sina": sina_of(c),
        "market": market_of(c),
        "name": name,
        "pct": ep,  # 兼容旧字段=入场阈值
        "entry_pct": ep,
        "stop_pct": sp,
        "tick": float(tick),
        "t0": bool(t0),
        "limit_down_pct": float(limit_down_pct),
        "prev_entry_mode": prev_entry_mode,
    }
    if factor4_kind is not None:
        item["factor4_kind"] = factor4_kind
    if factor4_params is not None:
        item["factor4_params"] = dict(factor4_params)
    if factor4_stop_widen_mult is not None:
        item["factor4_stop_widen_mult"] = float(factor4_stop_widen_mult)
    return item


def limit_down_pct_of(code: str) -> float:
    """主板约10%；创业板/科创板约20%；ETF 约10%。涨停幅度相同。"""
    c = code_key(code)
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


limit_up_pct_of = limit_down_pct_of


CORE_LEADER_PICKS_PATH = _MYQUAN_ROOT / "backtest" / "strategy16_core_leader" / "picks_quarter.json"
STRATEGY16_THR_PATH = _MYQUAN_ROOT / "backtest" / "strategy16_core_leader" / "thr_2026.json"
STRATEGY16_EXTRA_PICKS: tuple[tuple[str, str], ...] = (
    ("600330", "天通股份"),
    ("600552", "凯盛科技"),
)


def _strategy16_extra_pick_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, name in STRATEGY16_EXTRA_PICKS:
        rows.append(
            {
                "code": code_key(code),
                "name": name,
                "concept": "manual_add",
                "manual_add": True,
            }
        )
    return rows


def load_core_leader_payload() -> dict[str, Any]:
    if not CORE_LEADER_PICKS_PATH.is_file():
        return {}
    try:
        raw = json.loads(CORE_LEADER_PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    payload = dict(raw)
    picks = list(payload.get("picks") or [])
    seen = {
        code_key(str(it.get("code") or it.get("symbol") or ""))
        for it in picks
        if isinstance(it, dict)
    }
    extras_added: list[str] = []
    for extra in _strategy16_extra_pick_rows():
        code = code_key(str(extra.get("code") or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        picks.append(extra)
        extras_added.append(code)
    if extras_added:
        payload["picks"] = picks
        payload["manual_additions"] = extras_added
        payload["n_picks"] = len(picks)
        payload["target_pool_with_manual_additions"] = len(picks)
    return payload


def core_leader_codes() -> set[str]:
    """策略十六滚动近3个月冻结池（因子27）。"""
    out: set[str] = set()
    for it in load_core_leader_payload().get("picks") or []:
        c = code_key(str(it.get("code") or it.get("symbol") or ""))
        if c and c != "000000":
            out.add(c)
    return out


def load_strategy16_thr_map() -> dict[str, float]:
    """策略十六开盘买入阈值（2026 至今日线 {2/2.5/3}% 夏普择优）。"""
    if not STRATEGY16_THR_PATH.is_file():
        return {}
    try:
        raw = json.loads(STRATEGY16_THR_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, float] = {}
    for code, rec in (raw.get("thrs") or {}).items():
        c = code_key(str(code))
        if not c:
            continue
        thr = rec.get("thr") if isinstance(rec, dict) else rec
        try:
            out[c] = float(thr)
        except (TypeError, ValueError):
            continue
    return out


def is_strategy16_watch_only(
    code: str,
    holdings: dict[str, Any] | None = None,
) -> bool:
    """仅核心龙头池、非策略一定盘、非用户持仓：不算三槽、不进持仓 Tab 预警。"""
    c = code_key(code)
    if c in strategy_watchlist_codes():
        return False
    if holdings is None:
        try:
            from index import load_holdings

            holdings = load_holdings()
        except Exception:  # noqa: BLE001
            holdings = {}
    if c in set(portfolio_pool_codes(holdings or {})):
        return False
    return c in core_leader_codes()


def is_mainboard_pool(code: str) -> bool:
    """策略一股票池：沪深主板（剔创业板/科创板/北交所）。"""
    c = code_key(code)
    if c.startswith(("688", "689", "300", "301")):
        return False
    if c.startswith(("8", "4")):
        return False
    return True


# ---------------------------------------------------------------------------
# 策略三默认宇宙（与 strategy.config 对齐；S7 为历史命名）
# ---------------------------------------------------------------------------
S7_WATCHLIST: list[dict[str, Any]] = [
    watch_item(
        "600552",
        "凯盛科技",
        pct=0.025,
        factor4_kind="roc",
        factor4_params={"n": 60, "enter_raw": 0.10, "exit_raw": 0.02},
        factor4_stop_widen_mult=1.5,
    ),
    watch_item(
        "600330",
        "天通股份",
        pct=0.03,
        factor4_kind="roc_ma",
        factor4_params={"n": 40, "ma_n": 60, "enter_raw": 0.0, "exit_raw": 0.0},
        factor4_stop_widen_mult=1.3,  # 牛市止损≈3.9%，避免原2x→6%过大
    ),
    watch_item(
        "589680",
        "科创综指ETF鹏华",
        entry_pct=0.025,
        stop_pct=0.035,
        tick=0.001,
        t0=False,
        limit_down_pct=0.10,
        factor4_kind="roc_ma",
        factor4_params={"n": 60, "ma_n": 60},
        factor4_stop_widen_mult=2.0,
    ),
]

# ---------------------------------------------------------------------------
# 因子13 宽宇宙换池（无置顶；及格才入池）
# ---------------------------------------------------------------------------
_FIT_WATCH: list[tuple[str, str]] = [
    ("002104", "恒宝股份"),
    ("603301", "振德医疗"),
    ("600301", "华锡有色"),
    ("002093", "国脉科技"),
    ("600552", "凯盛科技"),
    ("601020", "华钰矿业"),
    ("601609", "金田股份"),
    ("600353", "旭光电子"),
    ("002779", "中坚科技"),
    ("601068", "中铝国际"),
    ("600967", "内蒙一机"),
    ("002273", "水晶光电"),
    ("002015", "协鑫能科"),
    ("002929", "润建股份"),
    ("000581", "威孚高科"),
    ("601519", "大智慧"),
    ("002922", "伊戈尔"),
    ("002152", "广电运通"),
    ("603920", "世运电路"),
    ("002065", "东华软件"),
]

_WATCH_PCT: dict[str, float] = {
    "002093": 0.03,
    "002779": 0.03,
    "600301": 0.03,
    "600353": 0.03,
    "601020": 0.03,
    "601068": 0.03,
    "601519": 0.03,
    "603301": 0.03,
    "603920": 0.03,
    "000581": 0.02,
    "002273": 0.02,
    "002922": 0.02,
    "601609": 0.02,
}

FIT_WATCHLIST: list[dict[str, Any]] = [
    watch_item(
        c,
        n,
        pct=_WATCH_PCT.get(code_key(c), DEFAULT_PCT),
        limit_down_pct=limit_down_pct_of(c),
    )
    for c, n in _FIT_WATCH
    if is_mainboard_pool(c)
]

# 旧策略一定盘池：与契合池一致（无置顶；因子13 及格才入池）
WATCHLIST_STRATEGY1: list[dict[str, Any]] = list(FIT_WATCHLIST)

# 持仓 Tab 固定展示：实仓 + 已卖仍跟踪（因子13 熊盾研究票阈值）
PORTFOLIO_PINNED_WATCHLIST: list[dict[str, Any]] = [
    watch_item("600552", "凯盛科技", pct=0.025),
    watch_item("600330", "天通股份", pct=0.03),
    watch_item("600338", "西藏珠峰", pct=0.025),
    watch_item("601208", "东材科技", pct=0.025),
]

# 切策略三：STRATEGY_ID="strategy3"; USE_FACTOR4=True; WATCHLIST=list(S7_WATCHLIST)


def strategy16_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """默认策略池：核心龙头 picks + 手工补入天通/凯盛。"""
    payload = load_core_leader_payload()
    picks = payload.get("picks") or []
    thrs = load_strategy16_thr_map()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in picks:
        code = code_key(str(it.get("code") or it.get("symbol") or ""))
        if not code or code in seen or code == "000000":
            continue
        seen.add(code)
        item = meta_for_code(code, holdings)
        if it.get("name"):
            item["name"] = str(it.get("name"))
        item["universe"] = "strategy16"
        item["concept"] = it.get("concept")
        if bool(it.get("manual_add")):
            item["manual_add"] = True
        thr = thrs.get(code)
        if thr is not None:
            item["pct"] = float(thr)
            item["entry_pct"] = float(thr)
            item["stop_pct"] = float(DEFAULT_PCT)
        out.append(item)
    return out


WATCHLIST: list[dict[str, Any]] = []


def strategy1_watchlist() -> list[dict[str, Any]]:
    """策略一定盘池（置顶 + 13A→16 Top20）。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for w in (*PORTFOLIO_PINNED_WATCHLIST, *WATCHLIST_STRATEGY1):
        c = code_key(w["code"])
        if c in seen:
            continue
        seen.add(c)
        out.append(w)
    return out


def strategy_watchlist() -> list[dict[str, Any]]:
    """当前默认策略池。"""
    if STRATEGY_ID == "strategy16":
        return strategy16_watchlist({})
    return strategy1_watchlist()


def strategy_watchlist_codes() -> set[str]:
    return {code_key(w["code"]) for w in strategy_watchlist()}


def _position_user_designated(
    pos: dict[str, Any],
    explicit: set[str],
    code: str,
) -> bool:
    """holdings.json 中由用户登记/指定的票（非策略池自动占位）。"""
    c = code_key(code)
    if c in explicit:
        return True
    if pos.get("pool"):
        return True
    if int(pos.get("qty") or 0) > 0:
        return True
    if pos.get("cost") is not None:
        return True
    if pos.get("buy_time"):
        return True
    return False


def portfolio_pool_codes(holdings: dict[str, Any]) -> list[str]:
    """持仓池代码：portfolio_pool 显式列表 + 用户登记仓位 + 当日已实现。"""
    explicit_raw = holdings.get("portfolio_pool")
    explicit = (
        {code_key(str(c)) for c in explicit_raw}
        if isinstance(explicit_raw, list)
        else set()
    )
    codes = set(explicit)
    for code, pos in (holdings.get("positions") or {}).items():
        if isinstance(pos, dict) and _position_user_designated(pos, explicit, str(code)):
            codes.add(code_key(str(code)))
    for code, rec in (holdings.get("realized_today") or {}).items():
        if rec:
            codes.add(code_key(str(code)))
    return sorted(codes)


def meta_for_code(code: str, holdings: dict[str, Any] | None = None) -> dict[str, Any]:
    """任意 A 股代码 → watch_item；名称优先 holdings.json。"""
    c = code_key(code)
    for w in (*PORTFOLIO_PINNED_WATCHLIST, *WATCHLIST_STRATEGY1):
        if w["code"] == c:
            return w
    pos: dict[str, Any] = {}
    if holdings:
        pos = (holdings.get("positions") or {}).get(c) or {}
    name = str(pos.get("name") or "").strip()
    if not name:
        try:
            from stock_names import resolve_stock_name

            name = resolve_stock_name(code=c) or c
        except Exception:  # noqa: BLE001
            name = c
    market = str(
        pos.get("market")
        or ("上证" if c.startswith(("5", "6", "9")) else "深证")
    )
    pct = _WATCH_PCT.get(c, DEFAULT_PCT)
    return watch_item(c, name, pct=pct, limit_down_pct=limit_down_pct_of(c))


WATCHLIST = strategy_watchlist()


def effective_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """盯盘拉行情/算信号：默认策略池 + 其余核心龙头补集 + 用户持仓池（去重）。"""
    if holdings is None:
        try:
            from index import load_holdings

            holdings = load_holdings()
        except Exception:  # noqa: BLE001
            holdings = {}
    base = strategy16_watchlist(holdings) if STRATEGY_ID == "strategy16" else strategy_watchlist()
    seen = {code_key(w["code"]) for w in base}
    out = list(base)
    for code in core_leader_codes():
        if code in seen:
            continue
        seen.add(code)
        item = meta_for_code(code, holdings)
        item["universe"] = "strategy16"
        thr = load_strategy16_thr_map().get(code)
        if thr is not None:
            item["pct"] = float(thr)
            item["entry_pct"] = float(thr)
            item["stop_pct"] = float(DEFAULT_PCT)
        out.append(item)
    for code in portfolio_pool_codes(holdings):
        if code in seen:
            continue
        seen.add(code)
        out.append(meta_for_code(code, holdings))
    return out


def empty_position(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": meta["name"],
        "market": meta["market"],
        "qty": 0,
        "available": None,
        "cost": None,
        "today_cost": None,
        "buy_time": None,
        "note": "",
    }


def sellable_qty(
    pos: dict[str, Any],
    qty: int,
    buy_time: str | None,
    session: str,
    *,
    t0: bool = False,
) -> int:
    """可卖数量。

    - T+0：整仓可卖
    - 买入当日（T+1）：以 available 为准（通常 0）；未填则整仓不可卖
    - 非买入日（隔夜仓）：available>0 取其与 qty 较小值；
      available 为 0 视为不可卖（对齐券商）；未填 available 才回退整仓
    """
    if qty <= 0:
        return 0
    if t0:
        return int(qty)
    t1 = is_t1_buy_day(buy_time, session)
    raw = pos.get("available")
    try:
        avail = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        avail = None

    if t1:
        if avail is None:
            return 0
        return max(0, min(avail, int(qty)))

    if avail is None:
        return int(qty)
    return max(0, min(avail, int(qty)))


def calc_day_pnl(
    *,
    last: float,
    qty: int,
    available: int,
    cost: float | None,
    prev_close: float | None,
    open_px: float,
    today_cost: float | None = None,
    buy_time: str | None = None,
    session: str | None = None,
    t0: bool = False,
) -> tuple[float | None, float | None, float | None]:
    """当日盈亏 = 现价盯市盈亏。"""
    if qty <= 0:
        return None, None, None
    last = float(last)
    open_px = float(open_px)
    cost_f = float(cost) if cost is not None else None
    today_f = float(today_cost) if today_cost is not None else None
    prev = float(prev_close) if prev_close is not None and float(prev_close) > 0 else None
    bought_today = (not t0) and bool(session) and is_t1_buy_day(buy_time, str(session))

    if not bought_today:
        base = prev if prev is not None else open_px
        day_pnl = (last - base) * int(qty)
        day_base = base * int(qty)
        if day_base <= 0:
            return round(day_pnl, 2), None, None
        return (
            round(day_pnl, 2),
            round(day_pnl / day_base * 100.0, 2),
            round(day_base, 2),
        )

    avail = max(0, min(int(available), int(qty)))
    locked = int(qty) - avail
    day_pnl = 0.0
    day_base = 0.0
    if avail > 0:
        base_ov = prev if prev is not None else open_px
        day_pnl += (last - base_ov) * avail
        day_base += base_ov * avail
    if locked > 0:
        base_td = (
            today_f
            if today_f is not None
            else (cost_f if cost_f is not None else open_px)
        )
        day_pnl += (last - base_td) * locked
        day_base += base_td * locked
    if day_base <= 0:
        return round(day_pnl, 2), None, None
    return round(day_pnl, 2), round(day_pnl / day_base * 100.0, 2), round(day_base, 2)


def find_meta(code: str, watchlist: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    key = code_key(code)
    items = watchlist if watchlist is not None else strategy_watchlist()
    for item in items:
        if item["code"] == key:
            return item
    if watchlist is not None:
        codes = "/".join(w["code"] for w in items)
        raise KeyError(f"不在监控列表: {code}（仅支持 {codes}）")
    try:
        from index import load_holdings

        return meta_for_code(code, load_holdings())
    except Exception:  # noqa: BLE001
        return meta_for_code(code, {})


def watchlist_codes_label(watchlist: list[dict[str, Any]] | None = None) -> str:
    items = watchlist if watchlist is not None else strategy_watchlist()
    return " / ".join(w["code"] for w in items)


# ── 三槽持仓（策略一实盘）──────────────────────────────────────────
MAX_PORTFOLIO_SLOTS = 3  # 盘中/隔夜均可同时持 3
RESERVE_EMPTY_SLOTS = 0  # 不再尾盘强制空槽
MAX_OVERNIGHT_SLOTS = MAX_PORTFOLIO_SLOTS - RESERVE_EMPTY_SLOTS  # 隔夜最多 3
# 兼容旧名：曾误作「盘中也最多2」；现仅表示隔夜上限
MAX_ACTIVE_SLOTS = MAX_OVERNIGHT_SLOTS
MAX_BUYS_PER_DAY = 2  # 当日最多买入次数
RESERVE_SLOT_HOUR = 14
RESERVE_SLOT_MINUTE = 50  # 14:50 起按隔夜上限控新开仓（现与盘中同为 3）
SLOT_WEIGHT = 0.30  # 每槽约 3 成仓
DEFAULT_ACCOUNT_TOTAL = 100_000.0  # 无登记总资产时按 10 万估槽金额


def occupied_slot_codes(holdings: dict[str, Any]) -> list[str]:
    """仅 qty>0 占槽；当日已清仓（realized_today）不占槽。"""
    out: list[str] = []
    for code, pos in (holdings.get("positions") or {}).items():
        if not isinstance(pos, dict):
            continue
        if int(pos.get("qty") or 0) > 0:
            out.append(code_key(str(code)))
    return sorted(set(out))


def free_slot_count(holdings: dict[str, Any]) -> int:
    """物理空槽数（相对 MAX_PORTFOLIO_SLOTS）。"""
    return max(0, int(MAX_PORTFOLIO_SLOTS) - len(occupied_slot_codes(holdings)))


def is_reserve_slot_window(now: Any | None = None) -> bool:
    """尾盘预留空槽窗口：此后新开仓按隔夜上限，日末须空出 RESERVE_EMPTY_SLOTS。"""
    return _clock_minutes(now) >= (
        int(RESERVE_SLOT_HOUR) * 60 + int(RESERVE_SLOT_MINUTE)
    )


def free_buy_slot_count(
    holdings: dict[str, Any],
    *,
    reserve_for_close: bool | None = None,
    now: Any | None = None,
) -> int:
    """可买入空槽。

    · 盘中：最多占满 MAX_PORTFOLIO_SLOTS（3）
    · 尾盘窗口（默认 14:50 后）或 reserve_for_close=True：按隔夜上限 MAX_OVERNIGHT_SLOTS（现为 3）
    """
    if reserve_for_close is None:
        reserve_for_close = is_reserve_slot_window(now)
    cap = int(MAX_OVERNIGHT_SLOTS if reserve_for_close else MAX_PORTFOLIO_SLOTS)
    return max(0, cap - len(occupied_slot_codes(holdings)))


def slot_meta(holdings: dict[str, Any], *, now: Any | None = None) -> dict[str, Any]:
    occupied = occupied_slot_codes(holdings)
    n = len(occupied)
    reserve_mode = is_reserve_slot_window(now)
    return {
        "max": int(MAX_PORTFOLIO_SLOTS),
        "reserve": int(RESERVE_EMPTY_SLOTS),
        "overnightMax": int(MAX_OVERNIGHT_SLOTS),
        "activeMax": int(MAX_OVERNIGHT_SLOTS),  # 兼容旧字段=隔夜上限
        "maxBuysPerDay": int(MAX_BUYS_PER_DAY),
        "reserveWindow": bool(reserve_mode),
        "weight": float(SLOT_WEIGHT),
        "occupied": occupied,
        "occupiedCount": n,
        "free": max(0, int(MAX_PORTFOLIO_SLOTS) - n),
        "freeBuy": free_buy_slot_count(holdings, now=now),
    }
