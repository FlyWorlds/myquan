"""盯盘标的池与代码工具（唯一真源；index 从此处导入）。

当前锁定：**默认策略 = 策略十六（核心龙头） = 因子27 + 因子26 + 因子2 + 因子22**。
默认交易池：因子27 核心龙头近 3 个月冻结池 ∪ **公共自选池**（天通/凯盛/东材/金安，
`SELF_WATCHLIST_PICKS`；策略一/十五/十六与 effective 并集均并入，非仅策略十六）。
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

from strategy.akq_math import session_day_pnl
from strategy.open_break import DEFAULT_PCT, TICK_SIZE, floor_to_tick, is_t1_buy_day

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

# 集合竞价确认成交（开盘保护）：官方开盘价、时刻固定 09:30:00
OPEN_BELL_HOUR = SIGNAL_ACTIVE_HOUR
OPEN_BELL_MINUTE = SIGNAL_ACTIVE_MINUTE


def session_open_bell_ts(session: str | None) -> str:
    """竞价核/开盘保护成交时刻：YYYY-MM-DD 09:30:00。"""
    sess = str(session or "")[:10]
    clock = f"{OPEN_BELL_HOUR:02d}:{OPEN_BELL_MINUTE:02d}:00"
    return f"{sess} {clock}" if sess else clock

# 策略/账户总收益起算日（含费用、T+1；自该交易日空仓/纸面本金起算）
STRATEGY_PNL_START = "2026-09-09"
# 账户「总收益」基准日：相对 DEFAULT_ACCOUNT_TOTAL 纸面本金
PAPER_PNL_START = STRATEGY_PNL_START

# 开盘价强制刷新（与 9:25 对齐）
OPEN_PRICE_REFRESH_HOUR = AUCTION_OPEN_HOUR
OPEN_PRICE_REFRESH_MINUTE = AUCTION_OPEN_MINUTE

# watch 里程碑：(时, 分, 日志标签, 动作)
# reseed=9:15 全日状态重置 + 昨仓今日盈亏按昨收；open=9:25 开盘阈值；refresh=刷新快照
AUCTION_MILESTONES: tuple[tuple[int, int, str, str], ...] = (
    (9, 15, "竞价开始·状态重置·今日盈亏按昨收", "reseed"),
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


def last_weekday(d: Any) -> Any:
    """回落到最近周五及以前的工作日（跳过周六日）。"""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    if isinstance(d, _dt):
        day = d.date()
    elif isinstance(d, _date):
        day = d
    else:
        day = _dt.strptime(str(d)[:10], "%Y-%m-%d").date()
    while day.weekday() >= 5:
        day -= _td(days=1)
    return day


def trading_session_date(now: Any | None = None) -> Any:
    """信号交易日：周六/周日锚定上周五；周一～周五用当日。

    周一盘中「前日」仍取上周五 K（由 session=周一 + 日线 date 严格早于 session 自然得到）。
    """
    from datetime import datetime as _dt

    ts = now if isinstance(now, _dt) else _dt.now()
    return last_weekday(ts.date())


def prev_trading_day(session: Any) -> Any:
    """session 的前一交易日（周一→周五；跳过周末）。不含法定长假日历。"""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    if isinstance(session, _dt):
        day = session.date()
    elif isinstance(session, _date):
        day = session
    else:
        day = _dt.strptime(str(session)[:10], "%Y-%m-%d").date()
    day -= _td(days=1)
    return last_weekday(day)


def normalize_signal_session(session: Any | None = None, *, now: Any | None = None) -> str:
    """规范化信号 session：空/周末 → 上周五；工作日保持原日。"""
    from datetime import datetime as _dt

    raw = str(session or "").strip()
    if not raw:
        return str(trading_session_date(now))
    try:
        day = _dt.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return str(trading_session_date(now))
    return str(last_weekday(day))


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
        "open_set": "开盘价已出·可挂单（9:25–9:30）",
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


# 行情分层硬帽：热池可 SSE；叠加池永不 SSE，且不进 collect_rows
MAX_SSE_QUOTES = 48

CORE_LEADER_PICKS_PATH = _MYQUAN_ROOT / "backtest" / "strategy16_core_leader" / "picks_quarter.json"
STRATEGY16_THR_PATH = _MYQUAN_ROOT / "backtest" / "strategy16_core_leader" / "thr_2026.json"

# 公共自选池（非因子选股）：所有策略交易/盯盘宇宙均并入；可入三槽；UI 标「自选」。
# 旧名 STRATEGY16_EXTRA_PICKS 仍兼容（历史曾只挂策略十六）。
SELF_WATCHLIST_PICKS: tuple[tuple[str, str], ...] = (
    ("600330", "天通股份"),
    ("600552", "凯盛科技"),
    ("601208", "东材科技"),
    ("002636", "金安国纪"),
)
STRATEGY16_EXTRA_PICKS = SELF_WATCHLIST_PICKS

POOL_SRC_FACTOR27 = "factor27"
POOL_SRC_FACTOR28 = "factor28"
POOL_SRC_SELF = "self"
POOL_SRC_LABEL = {
    POOL_SRC_FACTOR27: "因子27",
    POOL_SRC_FACTOR28: "紫阳真君",
    POOL_SRC_SELF: "自选",
}

ZIYANG_PICKS_PATH = _MYQUAN_ROOT / "backtest" / "strategy17_ziyang" / "picks_3m.json"


def self_watchlist_pick_rows() -> list[dict[str, Any]]:
    """公共自选池原始行（不含阈值；供各策略合并）。"""
    rows: list[dict[str, Any]] = []
    for code, name in SELF_WATCHLIST_PICKS:
        rows.append(
            {
                "code": code_key(code),
                "name": name,
                "concept": "self_watch",
                "pool_src": POOL_SRC_SELF,
                "manual_add": True,  # 兼容旧字段
            }
        )
    return rows


def self_watchlist_codes() -> set[str]:
    """公共自选池代码集合（6 位）。"""
    return {
        code_key(c)
        for c, _ in SELF_WATCHLIST_PICKS
        if code_key(c) and code_key(c) != "000000"
    }


def load_core_leader_payload() -> dict[str, Any]:
    """因子27 近3个月冻结池（纯选股产物，不含自选）。"""
    if not CORE_LEADER_PICKS_PATH.is_file():
        return {}
    try:
        raw = json.loads(CORE_LEADER_PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def factor27_codes() -> set[str]:
    """仅因子27选股池。"""
    out: set[str] = set()
    for it in load_core_leader_payload().get("picks") or []:
        if not isinstance(it, dict):
            continue
        c = code_key(str(it.get("code") or it.get("symbol") or ""))
        if c and c != "000000":
            out.add(c)
    return out


def load_ziyang_payload() -> dict[str, Any]:
    """策略十七·紫阳真君池产物。"""
    if not ZIYANG_PICKS_PATH.is_file():
        return {"n_picks": 0, "picks": []}
    try:
        raw = json.loads(ZIYANG_PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"n_picks": 0, "picks": []}
    return dict(raw) if isinstance(raw, dict) else {"n_picks": 0, "picks": []}


def factor28_codes() -> set[str]:
    """仅因子28 紫阳真君席位池。"""
    out: set[str] = set()
    for it in load_ziyang_payload().get("picks") or []:
        if not isinstance(it, dict):
            continue
        c = code_key(str(it.get("code") or it.get("symbol") or ""))
        if c and c != "000000":
            out.add(c)
    return out


def ziyang_codes() -> set[str]:
    """策略十七展示宇宙 = 因子28 ∪ 公共自选池。"""
    return factor28_codes() | self_watchlist_codes()


def core_leader_codes() -> set[str]:
    """策略十六交易宇宙 = 因子27 ∪ 公共自选池。"""
    return factor27_codes() | self_watchlist_codes()


def _strategy16_extra_pick_rows() -> list[dict[str, Any]]:
    """旧名：等同公共自选池行。"""
    return self_watchlist_pick_rows()


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
    "601208": 0.025,
    "002636": 0.025,
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
    watch_item("002636", "金安国纪", pct=0.025),
]

# 切策略三：STRATEGY_ID="strategy3"; USE_FACTOR4=True; WATCHLIST=list(S7_WATCHLIST)


def self_watch_items(
    holdings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """公共自选池 → watch_item 列表（带池来源标签）。"""
    out: list[dict[str, Any]] = []
    thrs = load_strategy16_thr_map()
    for code, name in SELF_WATCHLIST_PICKS:
        c = code_key(code)
        if not c or c == "000000":
            continue
        item = meta_for_code(c, holdings)
        item["name"] = name
        item["pool_src"] = POOL_SRC_SELF
        item["池来源"] = POOL_SRC_LABEL[POOL_SRC_SELF]
        item["self_watch"] = True
        item["manual_add"] = True
        item["concept"] = "self_watch"
        thr = thrs.get(c)
        if thr is not None:
            item["pct"] = float(thr)
            item["entry_pct"] = float(thr)
            item.setdefault("stop_pct", float(DEFAULT_PCT))
        out.append(item)
    return out


def merge_self_watchlist(
    items: list[dict[str, Any]],
    holdings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """任意策略池 ∪ 公共自选池：自选置前；同码以自选标签为准。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for w in self_watch_items(holdings):
        c = code_key(w["code"])
        if c in seen:
            continue
        seen.add(c)
        out.append(w)
    for w in items:
        c = code_key(str(w.get("code") or ""))
        if not c or c in seen:
            continue
        seen.add(c)
        row = dict(w)
        # 已在自选中的不会走到这里；其余保留原标签
        out.append(row)
    return out


def strategy16_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """策略十六：因子27选股池 ∪ 公共自选池。"""
    thrs = load_strategy16_thr_map()
    factor_rows: list[dict[str, Any]] = []
    seen_f: set[str] = set()
    for it in load_core_leader_payload().get("picks") or []:
        if not isinstance(it, dict):
            continue
        code = code_key(str(it.get("code") or it.get("symbol") or ""))
        if not code or code in seen_f or code == "000000":
            continue
        seen_f.add(code)
        item = meta_for_code(code, holdings)
        if it.get("name"):
            item["name"] = str(it.get("name"))
        item["universe"] = "strategy16"
        item["pool_src"] = POOL_SRC_FACTOR27
        item["池来源"] = POOL_SRC_LABEL[POOL_SRC_FACTOR27]
        item["concept"] = it.get("concept")
        thr = thrs.get(code)
        if thr is not None:
            item["pct"] = float(thr)
            item["entry_pct"] = float(thr)
            item["stop_pct"] = float(DEFAULT_PCT)
        factor_rows.append(item)
    return merge_self_watchlist(factor_rows, holdings)


WATCHLIST: list[dict[str, Any]] = []


def strategy1_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """策略一定盘池（置顶 + 13A→16 Top20）∪ 公共自选池。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for w in (*PORTFOLIO_PINNED_WATCHLIST, *WATCHLIST_STRATEGY1):
        c = code_key(w["code"])
        if c in seen:
            continue
        seen.add(c)
        item = dict(w)
        item["universe"] = "strategy1"
        item.setdefault("pool_src", "strategy1_pool")
        item.setdefault("池来源", "策略池")
        out.append(item)
    return merge_self_watchlist(out, holdings)


def strategy1_codes(holdings: dict[str, Any] | None = None) -> set[str]:
    """策略一 Tab 宇宙（定盘池 ∪ 公共自选）。"""
    return {code_key(w["code"]) for w in strategy1_watchlist(holdings)}


def strategy_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """当前默认策略池（始终含公共自选池）。"""
    if STRATEGY_ID == "strategy16":
        return strategy16_watchlist(holdings)
    return strategy1_watchlist(holdings)


def strategy_watchlist_codes(holdings: dict[str, Any] | None = None) -> set[str]:
    return {code_key(w["code"]) for w in strategy_watchlist(holdings)}


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
    for code, rec in (holdings.get("closed_today") or {}).items():
        if rec:
            codes.add(code_key(str(code)))
    return sorted(codes)


def is_default_strategy_pool_code(code: str) -> bool:
    """是否属于当前默认策略交易池（strategy16 时=核心龙头 watchlist）。"""
    return code_key(code) in strategy_watchlist_codes()


def prune_portfolio_pool(holdings: dict[str, Any]) -> list[str]:
    """对齐默认策略池：剔除旧策略遗留空壳；保留实仓 / 当日已实现 / 用户有成本登记。

    返回新的 portfolio_pool 列表（已写回 holdings）。
    """
    sw = strategy_watchlist_codes()
    positions = holdings.get("positions") or {}
    realized = holdings.get("realized_today") or {}
    keep: set[str] = set()
    for raw in holdings.get("portfolio_pool") or []:
        c = code_key(str(raw))
        if not c:
            continue
        pos = positions.get(c) if isinstance(positions.get(c), dict) else {}
        if c in sw:
            keep.add(c)
        elif int((pos or {}).get("qty") or 0) > 0:
            keep.add(c)
        elif c in realized and realized.get(c):
            keep.add(c)
        elif (pos or {}).get("cost") is not None or (pos or {}).get("buy_time"):
            keep.add(c)
    # 实仓 / 当日已实现即使未写进列表也保留
    for code, pos in positions.items():
        if isinstance(pos, dict) and int(pos.get("qty") or 0) > 0:
            keep.add(code_key(str(code)))
    for code, rec in realized.items():
        if rec:
            keep.add(code_key(str(code)))
    pruned = sorted(keep)
    holdings["portfolio_pool"] = pruned
    return pruned


def _name_for_code(code: str, holdings: dict[str, Any] | None = None) -> tuple[str, str]:
    """(名称, 市场)；名称优先 holdings，其次置顶名单。"""
    c = code_key(code)
    pos: dict[str, Any] = {}
    if holdings:
        pos = (holdings.get("positions") or {}).get(c) or {}
    name = str(pos.get("name") or "").strip()
    if not name:
        for w in PORTFOLIO_PINNED_WATCHLIST:
            if w["code"] == c:
                name = str(w.get("name") or "").strip()
                break
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
    return name, market


def meta_for_code(code: str, holdings: dict[str, Any] | None = None) -> dict[str, Any]:
    """任意 A 股代码 → watch_item。

    默认策略十六：开盘阈值只认 ``thr_2026.json``，否则 ``DEFAULT_PCT``。
    不走策略一遗留池 ``WATCHLIST_STRATEGY1`` / ``_WATCH_PCT`` / 置顶名单里的 pct。
    """
    c = code_key(code)
    if STRATEGY_ID == "strategy16":
        name, _market = _name_for_code(c, holdings)
        thrs = load_strategy16_thr_map()
        pct = float(thrs[c]) if c in thrs else float(DEFAULT_PCT)
        return watch_item(c, name, pct=pct, limit_down_pct=limit_down_pct_of(c))
    for w in (*PORTFOLIO_PINNED_WATCHLIST, *WATCHLIST_STRATEGY1):
        if w["code"] == c:
            return w
    name, _market = _name_for_code(c, holdings)
    pct = _WATCH_PCT.get(c, DEFAULT_PCT)
    return watch_item(c, name, pct=pct, limit_down_pct=limit_down_pct_of(c))


WATCHLIST = strategy_watchlist()


def primary_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """热池：默认策略 + 公共自选 + 用户持仓。行情 SSE / 首屏优先。"""
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
    return merge_self_watchlist(out, holdings)


def overlay_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """叠加观察池（如紫阳真君）：仅新浪批量行情，不占东财 SSE。"""
    primary_codes = {code_key(w["code"]) for w in primary_watchlist(holdings)}
    out: list[dict[str, Any]] = []
    for code in factor28_codes():
        if code in primary_codes:
            continue
        item = meta_for_code(code, holdings)
        item["universe"] = "strategy17"
        item["pool_src"] = POOL_SRC_FACTOR28
        item["池来源"] = POOL_SRC_LABEL[POOL_SRC_FACTOR28]
        item["quote_tier"] = "overlay"
        out.append(item)
    return out


def effective_watchlist(holdings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """全量盯盘宇宙 = 热池 ∪ 叠加池（信号扫描）；SSE 只用 primary_watchlist。"""
    base = primary_watchlist(holdings)
    seen = {code_key(w["code"]) for w in base}
    out = list(base)
    for w in overlay_watchlist(holdings):
        c = code_key(w["code"])
        if c in seen:
            continue
        seen.add(c)
        out.append(w)
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
        "tp_stage": 0,
        "last_tp_ts": None,
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
    - 非买入日（隔夜仓）：纸面 T+1 已过，可卖=持仓。
      available=0 视为买入日残留锁，不当券商不可卖。
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

    if avail is None or avail <= 0:
        return int(qty)
    return max(0, min(avail, int(qty)))


def unlock_overnight_available(data: dict[str, Any], session: str) -> bool:
    """隔夜仓：把买入日残留的 available=0 改成可卖=持仓。"""
    changed = False
    sess = str(session or "")[:10]
    if not sess:
        return False
    for pos in (data.get("positions") or {}).values():
        if not isinstance(pos, dict):
            continue
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        if is_t1_buy_day(pos.get("buy_time"), sess):
            continue
        raw = pos.get("available")
        if raw is None:
            pos["available"] = qty
            changed = True
            continue
        try:
            avail = int(raw)
        except (TypeError, ValueError):
            pos["available"] = qty
            changed = True
            continue
        if avail <= 0 or avail > qty:
            pos["available"] = qty
            changed = True
    return changed


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
    """当日盈亏：唯一入口 ``strategy.akq_math.session_day_pnl``（akquant 权益日变化）。

    昨仓只用昨收（无昨收则空，不回退开盘/成本，避免跨日「今日浮亏」挂成本）。
    今买相对买入价；无成本时才回退开盘。
    """
    del available, t0  # 口径按买日整仓，不再拆可卖/锁定
    bought_today = bool(session) and is_t1_buy_day(buy_time, str(session))
    cost_use = today_cost if today_cost is not None else cost
    if bought_today:
        fb = float(open_px) if open_px is not None else None
    else:
        fb = None
    return session_day_pnl(
        mark=last,
        qty=qty,
        cost=cost_use,
        prev_close=prev_close,
        bought_today=bought_today,
        fallback=fb,
    )


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


# ── 四槽持仓（盯盘纸面）──────────────────────────────────────────
MAX_PORTFOLIO_SLOTS = 4  # 盘中/隔夜均可同时持 4
RESERVE_EMPTY_SLOTS = 0  # 不再尾盘强制空槽
MAX_OVERNIGHT_SLOTS = MAX_PORTFOLIO_SLOTS - RESERVE_EMPTY_SLOTS  # 隔夜最多 4
# 兼容旧名：曾误作「盘中也最多2」；现仅表示隔夜上限
MAX_ACTIVE_SLOTS = MAX_OVERNIGHT_SLOTS
MAX_BUYS_PER_DAY = 4  # 当日最多买入次数（与四槽对齐，可买满 4）
RESERVE_SLOT_HOUR = 14
RESERVE_SLOT_MINUTE = 50  # 14:50 起按隔夜上限控新开仓（现与盘中同为 4）
SLOT_WEIGHT = 0.25  # 每槽约 2.5 成仓（4×25%）
DEFAULT_ACCOUNT_TOTAL = 300_000.0  # 纸面默认总资产；clear-all / 无登记时按此估槽金额
# 平仓腾槽后：第一梯队（平仓前已触买）用现价成交，现价不得超过买点 +1%；其后新触发仍按买点
SLOT_FIRST_TIER_MAX_OVERSHOOT = 0.01


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

    · 盘中：最多占满 MAX_PORTFOLIO_SLOTS（4）
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


def _slot_ts_key(ts: Any) -> str:
    s = str(ts or "").strip()
    if not s or s.startswith("9999"):
        return ""
    if len(s) >= 19 and s[4:5] == "-" and s[10:11] == " ":
        return s[:19]
    return s


def slot_fill_decision(
    *,
    signal_px: float,
    last_px: float | None,
    trigger_ts: str = "",
    freed_at: str | None = None,
    overshoot: float = SLOT_FIRST_TIER_MAX_OVERSHOOT,
    tick: float = TICK_SIZE,
) -> dict[str, Any] | None:
    """空槽成交价：平仓腾出 vs 新触发。

    · 无平仓时刻（开盘空槽/从未腾槽）：按买点成交
    · 触发早于平仓（第一梯队）：现价成交，且现价 ≤ 买点×(1+overshoot)；超限本轮不买
    · 平仓后才触发：按买点成交
    """
    try:
        sig = float(signal_px or 0)
    except (TypeError, ValueError):
        return None
    try:
        last = float(last_px or 0)
    except (TypeError, ValueError):
        last = 0.0
    if sig <= 0 or last <= 0:
        return None
    trig = _slot_ts_key(trigger_ts)
    freed = _slot_ts_key(freed_at)
    cap = sig * (1.0 + float(overshoot))
    if freed and trig and trig < freed:
        if last > cap + 1e-12:
            return None
        px = floor_to_tick(last, tick)
        if px <= 0:
            return None
        return {"fill_px": round(float(px), 4), "kind": "last"}
    px = floor_to_tick(sig, tick)
    if px <= 0:
        return None
    return {"fill_px": round(float(px), 4), "kind": "signal"}


def _slot_queue_blob(holdings: dict[str, Any], session: str) -> dict[str, Any]:
    day = str(session or "")[:10]
    raw = holdings.get("slot_queue")
    if not isinstance(raw, dict) or str(raw.get("session") or "")[:10] != day:
        blob = {"session": day, "freed_at": []}
        holdings["slot_queue"] = blob
        return blob
    times = raw.get("freed_at")
    if not isinstance(times, list):
        raw["freed_at"] = []
    return raw


def peek_slot_freed_at(holdings: dict[str, Any], session: str) -> str | None:
    """下一笔入槽对应的平仓腾槽时刻；没有则空槽按新触发买点成交。"""
    times = _slot_queue_blob(holdings, session).get("freed_at") or []
    for ts in times:
        key = _slot_ts_key(ts)
        if key:
            return key
    return None


def append_slot_freed_at(
    holdings: dict[str, Any],
    session: str,
    ts: Any,
) -> None:
    """全清腾出一槽：记下平仓时刻，供后续入槽分第一梯队 / 新触发。"""
    key = _slot_ts_key(ts)
    if not key:
        return
    blob = _slot_queue_blob(holdings, session)
    blob.setdefault("freed_at", []).append(key)


def pop_slot_freed_at(holdings: dict[str, Any], session: str) -> str | None:
    """入槽成交后消费一笔腾槽时刻。"""
    blob = _slot_queue_blob(holdings, session)
    times = blob.get("freed_at") or []
    if not times:
        return None
    return times.pop(0)
