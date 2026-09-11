"""策略一定盘池 · 近 7 交易日 1 分钟路径回测（三槽组合）。

选股/过滤：日线（前日阴/小阳、双阳禁买）；组合回撤看因子2 预警（不注资）。
成交：池内票近 7 日用 1 分钟 path-dependent（开盘阈值买 + 多层止盈：中赚回落一半与波动回落谁先到走谁）。

组合约束（对齐盯盘三槽）：
  · 物理槽 max_slots=3：盘中/隔夜均可同时持仓 3
  · 当日最多买入 3 次（MAX_BUYS_PER_DAY，与三槽对齐）
  · 尾盘不再强制空槽（RESERVE_EMPTY_SLOTS=0 → 隔夜最多 3）
  · 先触发买点的先买；槽满后触买进入等待队列，释放后再按触发先后补仓
  · T+1：买入当日不可卖；每槽约 3 成仓（权益×slot_weight）
  · 当日止损/已记卖出的标的：当日禁止再买

用法：
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/run.py
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/run.py --days 7 --refresh --max-slots 3
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/run.py --buy-mode open_or_attack   # 研究：加回攻击波
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/run.py --pool strategy16 --days 7 --fit-thr

研究用途，非投资建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdingStocks.watch_config import (  # noqa: E402
    DEFAULT_ACCOUNT_TOTAL,
    MAX_BUYS_PER_DAY,
    MAX_OVERNIGHT_SLOTS,
    MAX_PORTFOLIO_SLOTS,
    RESERVE_EMPTY_SLOTS,
    RESERVE_SLOT_HOUR,
    RESERVE_SLOT_MINUTE,
    SLOT_WEIGHT,
    load_core_leader_payload,
    load_strategy16_thr_map,
    meta_for_code,
    strategy1_watchlist,
    strategy_watchlist,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.dd_alert import derive_thresholds, format_rules  # noqa: E402
from strategy.minute import pull_akshare_1m  # noqa: E402
from strategy.close_momentum import rebuy_signal  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    TICK_SIZE,
    ceil_to_tick,
    floor_to_tick,
    is_t1_buy_day,
    prev_day_allows_entry,
    should_block_entry_by_yang,
)
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
    DEFAULT_NOTED_DUMP_PCT,
    DEFAULT_GIVEBACK_ARM_PCT,
    HARD_GAP_IMMEDIATE,
    HARD_GAP_OPEN_DUMP,
    HARD_GAP_MODES,
    DEFAULT_HARD_GAP_DUMP_PCT,
    NOTED_MODE_GAP_DUMP,
    attack_buy_trigger_price,
    delayed_t1_stop_fill_px,
    entry_trigger_price,
    eval_multi_tp_bar,
    is_one_word_bar,
    noted_next_day_fill,
    pnl_exceeds,
    pullback_stop_price,
    realized_vol_daily,
    replay_factor26_1m,
    resolve_t1_overnight_note,
    stop_note_invalidated_by_recovery,
)

OUT = Path(__file__).resolve().parent
CACHE = OUT / "cache_1m"
CACHE.mkdir(parents=True, exist_ok=True)

BUY_MODE_OPEN_OR_ATTACK = "open_or_attack"
BUY_MODE_OPEN = "open"
BUY_MODE_DEFAULT = BUY_MODE_OPEN
BUY_MODES = (BUY_MODE_OPEN, BUY_MODE_OPEN_OR_ATTACK)


def _sina(code: str) -> str:
    c = str(code).zfill(6)
    return f"sh{c}" if c.startswith(("5", "6", "9")) else f"sz{c}"


def _em(code: str) -> str:
    return str(code).zfill(6)


POOL_STRATEGY1 = "strategy1"
POOL_STRATEGY16 = "strategy16"
POOL_CHOICES = (POOL_STRATEGY1, POOL_STRATEGY16)


def _load_pool(pool: str = POOL_STRATEGY1) -> list[dict]:
    name = str(pool or POOL_STRATEGY1).strip().lower()
    if name in ("s16", "core_leader"):
        name = POOL_STRATEGY16
    if name == POOL_STRATEGY16:
        picks = strategy_watchlist()
        if not picks:
            raise SystemExit(
                "策略十六池为空。请先: python strategy/run_core_leader_pool.py"
            )
        return [dict(w) for w in picks]
    return list(strategy1_watchlist())


def _daily(sina: str, lookback_cal_days: int = 40) -> pd.DataFrame:
    end = pd.Timestamp.now().strftime("%Y%m%d")
    start = (pd.Timestamp.now() - pd.Timedelta(days=lookback_cal_days)).strftime(
        "%Y%m%d"
    )
    try:
        return fetch_daily(sina, start, end)
    except Exception as e:  # noqa: BLE001
        print(f"  日线失败 {sina}: {e}")
        return pd.DataFrame()


def _minutes(sina: str, *, refresh: bool, days: int = 7, source: str = "auto") -> pd.DataFrame:
    """拉 1m：优先本地缓存；akshare 约近 5 日；source=panda/auto 时用 Pandadata 拉长窗实盘分钟。"""
    path = CACHE / f"{sina}_1m.parquet"
    cached = pd.DataFrame()
    if path.exists() and not refresh:
        try:
            cached = pd.read_parquet(path)
        except Exception:  # noqa: BLE001
            cached = pd.DataFrame()

    need_days = max(1, int(days))
    src = str(source or "auto").lower()
    frames: list[pd.DataFrame] = []
    if not cached.empty and "ts" in cached.columns:
        frames.append(cached)

    # Pandadata 长历史（实盘库）；失败则退回 akshare
    use_panda = src in ("panda", "pandadata", "auto") and need_days > 5
    if use_panda or src in ("panda", "pandadata"):
        try:
            import os
            from pathlib import Path as _P

            env = _P.home() / ".pandadata" / "pandadata.env"
            if env.exists():
                for raw in env.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if line.startswith("export "):
                        line = line[len("export ") :]
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            import panda_data

            panda_data.init_token()
            code = sina[2:] if len(sina) >= 8 else sina
            market = "SH" if str(sina).lower().startswith("sh") else "SZ"
            symbol = f"{code}.{market}"
            end = pd.Timestamp.today().strftime("%Y%m%d")
            start = (pd.Timestamp.today() - pd.Timedelta(days=max(need_days * 2, 20))).strftime(
                "%Y%m%d"
            )
            raw = panda_data.get_stock_min(
                symbol=symbol,
                start_date=start,
                end_date=end,
                frequency="1m",
            )
            if raw is not None and not getattr(raw, "empty", True):
                pdf = raw.copy()
                if "datetime" in pdf.columns:
                    pdf["ts"] = pd.to_datetime(pdf["datetime"])
                elif "date" in pdf.columns and "minute" in pdf.columns:
                    pdf["ts"] = pd.to_datetime(
                        pdf["date"].astype(str) + " " + pdf["minute"].astype(str)
                    )
                for c in ("open", "high", "low", "close"):
                    if c in pdf.columns:
                        pdf[c] = pd.to_numeric(pdf[c], errors="coerce")
                pdf = pdf.dropna(subset=["ts", "open", "high", "low", "close"])
                frames.append(pdf[["ts", "open", "high", "low", "close"]].copy())
                print(f"  [panda] {sina} 1m rows={len(pdf)}")
        except Exception as e:  # noqa: BLE001
            if src in ("panda", "pandadata"):
                print(f"  [panda] {sina} 失败: {e}")

    if src in ("auto", "ak", "akshare") and (not frames or need_days <= 7):
        em = _em(sina[2:] if len(sina) >= 8 else sina)
        try:
            df = pull_akshare_1m(em_symbol=em, sina_symbol=sina, adjust="")
            if df is not None and not df.empty:
                frames.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"  1m 失败 {sina}: {e}")

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["ts"] = pd.to_datetime(out["ts"])
    out = out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
    except Exception:  # noqa: BLE001
        pass
    return out


def _prep_minutes(minutes: pd.DataFrame) -> pd.DataFrame:
    if minutes is None or getattr(minutes, "empty", True):
        return pd.DataFrame()
    m = minutes.copy()
    m["ts"] = pd.to_datetime(m["ts"])
    if getattr(m["ts"].dt, "tz", None) is not None:
        m["ts"] = m["ts"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    m["day"] = m["ts"].dt.strftime("%Y-%m-%d")
    m = m.dropna(subset=["open", "high", "low", "close"])
    m = m[(m["high"] > 0) & (m["low"] > 0)]
    return m.sort_values("ts")


def _prep_daily(daily: pd.DataFrame) -> pd.DataFrame:
    if daily is None or daily.empty:
        return pd.DataFrame()
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    df["day"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def _trade_pnl(trades: list[dict]) -> tuple[float | None, int]:
    """简单成对买→卖收益（未计费）；未平仓不算。"""
    buy_px = None
    rets: list[float] = []
    for t in trades:
        if t.get("side") == "buy":
            buy_px = float(t["px"])
        elif t.get("side") == "sell" and buy_px and buy_px > 0:
            rets.append(float(t["px"]) / buy_px - 1.0)
            buy_px = None
    if not rets:
        return None, 0
    nav = 1.0
    for r in rets:
        nav *= 1.0 + r
    return nav - 1.0, len(rets)


@dataclass
class _Pos:
    code: str
    name: str
    buy_day: str
    buy_px: float
    buy_ts: str
    shares: int
    cost: float
    kind: str | None = None
    peak_high: float = 0.0  # 持仓以来最高（用于收益回落一半）
    stop_noted_px: float | None = None  # T+1 止损已触发（次日市价离场，不是按该价成交）
    tp_stage: int = 0  # 0=未半仓；1=已阶梯/峰值半仓
    tp_marked: bool = False  # 当日触止盈条件（含 T+1 未卖）
    yday_loss: bool = False  # 昨收相对成本亏损 → 次日隔夜武装
    held_low: float = field(default_factory=lambda: float("inf"))  # 买入后最低（不含买前）


def _exit_stop_px(
    *,
    mode: str,
    running_high: float,
    buy_px: float,
    peak_high: float,
    pullback_pct: float,
) -> tuple[float, str]:
    """计算出场价。返回 (止盈/止损价, 原因标签)。

    - peak_pct：峰值回落阈值（因子26）= floor(当日分时最高×(1−pb))
    - half_gain：浮盈回落一半 = floor(成本 + 0.5×(持仓最高−成本))；
      尚未浮盈时退化为成本回撤阈值保护 floor(成本×(1−pb))
    """
    from strategy.open_break import floor_to_tick

    pb = float(pullback_pct)
    mode = str(mode or "peak_pct")
    rh = float(running_high)
    bp = float(buy_px)
    ph = max(float(peak_high), rh, bp)

    if mode == "half_gain":
        if ph <= bp + 1e-12:
            return floor_to_tick(bp * (1.0 - pb)), "hard_from_cost"
        return floor_to_tick(bp + 0.5 * (ph - bp)), "half_gain"
    # default: peak_pct（当日波）
    if rh <= 0:
        return 0.0, "peak_pct"
    return pullback_stop_price(rh, pullback_pct=pb), "peak_pct"


@dataclass
class _StockDay:
    code: str
    name: str
    entry_pct: float
    pullback_pct: float
    open_px: float
    allow_entry: bool
    bars: pd.DataFrame
    close_px: float | None = None
    prev_close: float | None = None
    vol20_daily: float | None = None


@dataclass
class _DayState:
    running_high: float = 0.0
    running_low: float = field(default_factory=lambda: float("inf"))
    buy_armed: bool = True  # 当日尚未错过/成交买点前可持续扫描
    pending_buy: dict[str, Any] | None = None
    sold_today: bool = False
    noted_lock_wait: bool = False
    noted_first_exec: bool = True
    overnight_armed: bool = False  # 买入日收盘未到 3% → 次日峰值回落 2.5%
    overnight_first: bool = True
    session_high: float = 0.0


def _lot_shares(budget: float, price: float) -> int:
    if budget <= 0 or price <= 0:
        return 0
    return int(budget // (price * 100.0)) * 100


def _mark_equity(
    cash: float,
    positions: dict[str, _Pos],
    last_px: dict[str, float],
) -> float:
    eq = float(cash)
    for code, pos in positions.items():
        px = float(last_px.get(code) or pos.buy_px)
        eq += px * int(pos.shares)
    return eq


def simulate_portfolio_3slots(
    stocks: list[dict[str, Any]],
    *,
    days: int = 7,
    max_slots: int = MAX_PORTFOLIO_SLOTS,
    initial_cash: float = DEFAULT_ACCOUNT_TOTAL,
    slot_weight: float = SLOT_WEIGHT,
    exit_mode: str = "half_gain",
    noted_mode: str = NOTED_MODE_GAP_DUMP,
    noted_dump_pct: float | None = None,
    reserve_empty: int = RESERVE_EMPTY_SLOTS,
    max_buys_per_day: int = MAX_BUYS_PER_DAY,
    buy_mode: str = BUY_MODE_DEFAULT,
    allow_f22_rebuy: bool = False,
    f22_bounce_pct: float = 0.01,
    hard_gap_mode: str = HARD_GAP_IMMEDIATE,
    hard_gap_dump_pct: float = DEFAULT_HARD_GAP_DUMP_PCT,
    allow_open_rebuy_after_sell: bool = False,
) -> dict[str, Any]:
    """三槽组合：1m 路径，先触发买点先买，最多同时持有 max_slots 只。

    exit_mode:
      - half_gain：浮盈相对持仓最高回落一半止盈（因子26 默认；未浮盈用成本回撤保护）
      - peak_pct：旧版峰值回落阈值（对照）
    noted_mode / noted_dump_pct：T+1 止损已记后的次日规则
    buy_mode：open=只认开盘涨到阈值（默认）；open_or_attack=开盘突破或攻击波（对照）
    allow_f22_rebuy：研究对照——当日卖出后若收盘≥当日最低×(1+bounce) 允许同日再买（生产默认 False）
    hard_gap_mode：immediate=低开破硬保护立刻卖；open_dump=再等开盘下杀 dump%（研究）
    allow_open_rebuy_after_sell：研究对照——当日全清后仍允许再触开盘阈值买入（生产默认 False）
    """
    max_slots = max(1, int(max_slots))
    reserve = max(0, min(int(reserve_empty), max_slots - 1))
    max_overnight = max(1, max_slots - reserve)
    max_buys = max(1, int(max_buys_per_day))
    exit_mode = str(exit_mode or "half_gain")
    nmode = str(noted_mode or NOTED_MODE_GAP_DUMP)
    bmode = str(buy_mode or BUY_MODE_DEFAULT).strip().lower()
    if bmode not in BUY_MODES:
        bmode = BUY_MODE_DEFAULT
    allow_attack = bmode == BUY_MODE_OPEN_OR_ATTACK
    allow_f22 = bool(allow_f22_rebuy)
    f22_bounce = float(f22_bounce_pct)
    hgap = str(hard_gap_mode or HARD_GAP_IMMEDIATE).strip().lower()
    if hgap not in HARD_GAP_MODES:
        hgap = HARD_GAP_IMMEDIATE
    allow_open_rebuy = bool(allow_open_rebuy_after_sell)
    prepared: list[dict[str, Any]] = []
    all_days: set[str] = set()

    for s in stocks:
        raw_daily = s.get("daily")
        raw_mins = s.get("minutes")
        if raw_daily is None or not isinstance(raw_daily, pd.DataFrame):
            raw_daily = pd.DataFrame()
        if raw_mins is None or not isinstance(raw_mins, pd.DataFrame):
            raw_mins = pd.DataFrame()
        daily = _prep_daily(raw_daily)
        mins = _prep_minutes(raw_mins)
        if daily.empty or mins.empty:
            continue
        m_days = sorted(mins["day"].unique())
        use = set(m_days[-max(1, int(days)) :])
        all_days |= use
        prepared.append(
            {
                "code": s["code"],
                "name": s["name"],
                "entry_pct": float(s["entry_pct"]),
                "pullback_pct": float(s["pullback_pct"]),
                "daily": daily,
                "minutes": mins,
                "use_days": use,
            }
        )

    if not prepared or not all_days:
        return {
            "trades": [],
            "equity": [],
            "skipped_buys": [],
            "summary": {"error": "no_data"},
        }

    # 交易日取「池内任一票有 1m」的最近 N 日，再与各票 use_days 求交时逐日处理
    calendar = sorted(all_days)[-max(1, int(days)) :]
    positions: dict[str, _Pos] = {}
    cash = float(initial_cash)
    last_px: dict[str, float] = {}
    trades: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    wait_q: list[dict[str, Any]] = []  # 触买但当时无槽：按触发时间排队
    buys_today = 0

    def _equity_now() -> float:
        return _mark_equity(cash, positions, last_px)

    def _buy_cap_at(ts: pd.Timestamp | None = None) -> int:
        """盘中最多 max_slots；尾盘窗口起按隔夜上限。"""
        if ts is None:
            return max_slots
        try:
            mins = int(ts.hour) * 60 + int(ts.minute)
        except Exception:
            return max_slots
        reserve_mins = int(RESERVE_SLOT_HOUR) * 60 + int(RESERVE_SLOT_MINUTE)
        if mins >= reserve_mins:
            return max_overnight
        return max_slots

    def _can_open_buy(ts: pd.Timestamp | None = None) -> bool:
        return len(positions) < _buy_cap_at(ts) and buys_today < max_buys

    def _try_fill_from_queue(sess: str, at_ts: str) -> None:
        nonlocal cash, buys_today
        wait_q.sort(key=lambda x: (str(x["ts"]), str(x["code"])))
        while wait_q and _can_open_buy(pd.Timestamp(at_ts)):
            cand = wait_q.pop(0)
            code = cand["code"]
            if code in positions:
                continue
            st_q = states.get(code)
            if st_q is not None and st_q.sold_today and (not allow_open_rebuy):
                skipped.append({**cand, "reason": "sold_today_no_rebuy"})
                continue
            if cand.get("day") != sess:
                skipped.append({**cand, "reason": "queue_expired_next_day"})
                continue
            px = float(cand["px"])
            eq = _equity_now()
            budget = eq * float(slot_weight)
            shares = _lot_shares(budget, px)
            if shares < 100:
                skipped.append({**cand, "reason": "budget_too_small"})
                continue
            cost = shares * px
            if cost > cash + 1e-6:
                shares = _lot_shares(cash, px)
                cost = shares * px
            if shares < 100:
                skipped.append({**cand, "reason": "cash_too_small"})
                continue
            cash -= cost
            buys_today += 1
            positions[code] = _Pos(
                code=code,
                name=str(cand["name"]),
                buy_day=sess,
                buy_px=px,
                buy_ts=str(at_ts),
                shares=shares,
                cost=cost,
                kind=cand.get("kind"),
                peak_high=px,
                held_low=px,
            )
            trades.append(
                {
                    "date": sess,
                    "ts": str(at_ts),
                    "trigger_ts": str(cand["ts"]),
                    "side": "buy",
                    "code": code,
                    "name": cand["name"],
                    "px": px,
                    "shares": shares,
                    "kind": cand.get("kind"),
                    # 保留 pending 来源（如 open_rebuy_after_sell）；无则记排队成交
                    "source": cand.get("source") or "queue_fill",
                    "slots_after": len(positions),
                }
            )

    for sess in calendar:
        # 日线过滤 + 当日分钟
        day_map: dict[str, _StockDay] = {}
        for s in prepared:
            if sess not in s["use_days"]:
                continue
            daily: pd.DataFrame = s["daily"]
            mins: pd.DataFrame = s["minutes"]
            day_bars = mins[mins["day"] == sess].sort_values("ts")
            if day_bars.empty:
                continue
            day_list = list(daily["day"].astype(str))
            prev_c: float | None = None
            if sess not in day_list:
                # 无日线时仍可用分钟开盘，但缺前日过滤 → 仅允许已持仓卖出
                allow = False
                o = float(day_bars.iloc[0]["open"])
                close_px = float(day_bars.iloc[-1]["close"])
            else:
                i = day_list.index(sess)
                if i < 1:
                    allow = False
                else:
                    prev = daily.iloc[i - 1]
                    prev2 = daily.iloc[i - 2] if i >= 2 else None
                    prev_c = float(prev["close"])
                    allow = prev_day_allows_entry(
                        float(prev["open"]),
                        float(prev["close"]),
                        prev_small_yang_pct=float(s["entry_pct"]),
                        prev_entry_mode="yin_or_small_yang",
                    )
                    if prev2 is not None and should_block_entry_by_yang(
                        float(prev2["open"]),
                        float(prev2["close"]),
                        float(prev["open"]),
                        float(prev["close"]),
                        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
                        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
                        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
                        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
                    ):
                        allow = False
                o = float(daily.iloc[i]["open"])
                close_px = float(daily.iloc[i]["close"])
                try:
                    o1 = float(day_bars.iloc[0]["open"])
                    if o1 > 0:
                        o = o1
                except (TypeError, ValueError, IndexError):
                    pass
            vol20 = None
            try:
                prior = daily[daily["day"].astype(str) < str(sess)]
                vol20 = realized_vol_daily(prior["close"].tolist())
            except Exception:  # noqa: BLE001
                vol20 = None
            day_map[s["code"]] = _StockDay(
                code=s["code"],
                name=s["name"],
                entry_pct=float(s["entry_pct"]),
                pullback_pct=float(s["pullback_pct"]),
                open_px=o,
                allow_entry=bool(allow),
                bars=day_bars,
                close_px=close_px,
                prev_close=prev_c,
                vol20_daily=vol20,
            )
            last_px[s["code"]] = float(close_px)

        # 清空隔日等待队列
        if wait_q:
            for cand in wait_q:
                skipped.append({**cand, "reason": "queue_expired_next_day"})
            wait_q.clear()

        states: dict[str, _DayState] = {c: _DayState() for c in day_map}
        buys_today = 0
        # 已持仓：分时最高从今日开盘路径起算；买入当日 T+1 不可卖
        for code, pos in positions.items():
            if code not in states:
                continue
            # 持仓票不再找新买点
            states[code].buy_armed = False
            # 买入日收盘未到 3% 已记 → 次日峰值回落 2.5%；不再用昨亏武装开盘−1%
            noted0 = float(pos.stop_noted_px or 0) if pos.stop_noted_px else 0.0
            states[code].overnight_armed = bool(noted0 > 0)
            pos.tp_marked = False  # 当日重新累计；武装已吃进 overnight_armed

        # 合并时间线
        timeline: list[tuple[pd.Timestamp, str, float, float, float]] = []
        for code, sd in day_map.items():
            for _, row in sd.bars.iterrows():
                try:
                    bar_o = float(row["open"]) if "open" in sd.bars.columns else float(sd.open_px)
                except (TypeError, ValueError):
                    bar_o = float(sd.open_px)
                timeline.append(
                    (
                        pd.Timestamp(row["ts"]),
                        code,
                        float(row["high"]),
                        float(row["low"]),
                        bar_o if bar_o > 0 else float(sd.open_px),
                    )
                )
        timeline.sort(key=lambda x: (x[0], x[1]))

        i = 0
        n = len(timeline)
        while i < n:
            ts = timeline[i][0]
            # 同一分钟内：先处理全部卖，再处理全部新触发买（先触发=时间戳相同则按代码稳定序，已按 code 排）
            bucket: list[tuple[pd.Timestamp, str, float, float, float]] = []
            while i < n and timeline[i][0] == ts:
                bucket.append(timeline[i])
                i += 1

            # —— 卖 ——
            for _, code, h, lo, bar_o in bucket:
                if code not in positions:
                    # 更新空仓扫描用的高低
                    st = states.get(code)
                    sd = day_map.get(code)
                    if st is None or sd is None:
                        continue
                    st.running_low = min(st.running_low, lo)
                    st.running_high = max(st.running_high, h)
                    last_px[code] = (h + lo) / 2.0
                    continue

                st = states[code]
                sd = day_map[code]
                pos = positions[code]
                st.running_low = min(st.running_low, lo)
                can_sell = not is_t1_buy_day(pos.buy_day, sess)
                rh = float(st.running_high or 0.0)
                ph = max(float(pos.peak_high or 0.0), rh)
                noted = float(pos.stop_noted_px or 0.0) if pos.stop_noted_px else 0.0
                # 一字跌停封死等开板；生产不再走开盘−1%，改由 eval T1 峰值回落
                if can_sell and (not st.sold_today) and noted > 0:
                    locked = False
                    pc = float(sd.prev_close or 0)
                    if pc > 0:
                        limit_px = floor_to_tick(pc * 0.9, 0.01)
                        locked = is_one_word_bar(bar_o, h, lo) and (
                            abs(float(bar_o) - limit_px) <= 0.01 + 1e-9
                        )
                    if locked:
                        st.noted_lock_wait = True
                        st.running_low = min(st.running_low, lo)
                        st.running_high = max(st.running_high, h)
                        last_px[code] = (h + lo) / 2.0
                        continue
                    if nmode != NOTED_MODE_GAP_DUMP:
                        day_o = (
                            float(bar_o) if st.noted_lock_wait else float(sd.open_px)
                        )
                        dump = (
                            float(noted_dump_pct)
                            if noted_dump_pct is not None
                            else DEFAULT_NOTED_DUMP_PCT
                        )
                        nxt = noted_next_day_fill(
                            mode=nmode,
                            noted_px=noted,
                            day_open=day_o,
                            bar_low=lo,
                            dump_pct=dump,
                            tick=0.01,
                            first_executable=bool(st.noted_first_exec),
                            cost_px=float(pos.buy_px),
                            bar_high=float(h),
                        )
                        st.noted_first_exec = False
                        if nxt.get("hit") and float(nxt.get("fill_px") or 0) > 0:
                            fill = float(nxt["fill_px"])
                            proceeds = float(fill) * int(pos.shares)
                            cash += proceeds
                            trades.append(
                                {
                                    "date": sess,
                                    "ts": str(ts),
                                    "side": "sell",
                                    "code": code,
                                    "name": pos.name,
                                    "px": float(fill),
                                    "shares": int(pos.shares),
                                    "pnl_pct": round(float(fill) / pos.buy_px - 1.0, 4)
                                    if pos.buy_px
                                    else None,
                                    "exit_reason": str(nxt.get("reason") or "stop_noted"),
                                    "slots_after": len(positions) - 1,
                                }
                            )
                            del positions[code]
                            st.sold_today = True
                            st.buy_armed = bool(allow_open_rebuy)
                            st.pending_buy = None
                            last_px[code] = float(fill)
                            _try_fill_from_queue(sess, str(ts))
                            continue

                # 多层止盈：可卖则成交；T+1 只记 tp_marked / stop_noted
                if code in positions and exit_mode in ("half_gain", "multi_tp"):
                    dump = (
                        float(noted_dump_pct)
                        if noted_dump_pct is not None
                        else DEFAULT_NOTED_DUMP_PCT
                    )
                    armed = bool(st.overnight_armed)
                    ev = eval_multi_tp_bar(
                        bar_open=float(bar_o),
                        bar_high=float(h),
                        bar_low=float(lo),
                        cost_px=float(pos.buy_px),
                        peak_before=float(ph),
                        shares=int(pos.shares),
                        tp_stage=int(pos.tp_stage or 0),
                        can_sell=bool(can_sell) and (not st.sold_today),
                        overnight_armed=armed and can_sell,
                        day_open=float(sd.open_px),
                        hard_pct=float(sd.pullback_pct),
                        dump_pct=dump,
                        vol20_daily=sd.vol20_daily,
                        session_peak_before=float(st.session_high or 0),
                        hard_gap_mode=hgap,
                        hard_gap_dump_pct=float(hard_gap_dump_pct),
                    )
                    st.session_high = float(
                        ev.get("session_peak_after") or st.session_high or 0
                    )
                    if armed and pnl_exceeds(
                        max(float(h), float(sd.open_px), float(bar_o)),
                        float(pos.buy_px),
                        DEFAULT_GIVEBACK_ARM_PCT,
                    ):
                        st.overnight_armed = False
                        pos.stop_noted_px = None
                    if ev.get("tp_marked"):
                        pos.tp_marked = True
                    if (not can_sell) and ev.get("noted_px"):
                        prev_n = (
                            float(pos.stop_noted_px or 0) if pos.stop_noted_px else 0.0
                        )
                        npx = float(ev["noted_px"])
                        pos.stop_noted_px = npx if prev_n <= 0 else min(prev_n, npx)
                    act = ev.get("action")
                    if can_sell and act and code in positions:
                        fill = float(act["fill_px"])
                        sell_n = max(0, min(int(act["shares"]), int(pos.shares)))
                        if sell_n > 0:
                            proceeds = float(fill) * sell_n
                            cash += proceeds
                            left_after = int(pos.shares) - sell_n
                            full_exit = left_after <= 0 or str(act.get("kind")) == "full"
                            trades.append(
                                {
                                    "date": sess,
                                    "ts": str(ts),
                                    "side": "sell",
                                    "code": code,
                                    "name": pos.name,
                                    "px": float(fill),
                                    "shares": sell_n,
                                    "pnl_pct": round(float(fill) / pos.buy_px - 1.0, 4)
                                    if pos.buy_px
                                    else None,
                                    "exit_reason": str(act.get("reason") or "multi_tp"),
                                    "slots_after": len(positions) - (1 if full_exit else 0),
                                }
                            )
                            # sold_today：生产禁同日再买；半仓后仍可继续止盈剩余仓
                            st.sold_today = True
                            st.buy_armed = bool(allow_open_rebuy) and full_exit
                            if full_exit:
                                del positions[code]
                                st.pending_buy = None
                                st.overnight_armed = False
                            else:
                                pos.shares = left_after
                                pos.tp_stage = 1
                                st.buy_armed = False
                            last_px[code] = float(fill)
                            if code not in positions:
                                _try_fill_from_queue(sess, str(ts))
                                continue
                elif (
                    can_sell
                    and (not st.sold_today)
                    and exit_mode not in ("half_gain", "multi_tp")
                ):
                    can_eval = rh > 0
                    if can_eval:
                        stop, reason = _exit_stop_px(
                            mode=exit_mode,
                            running_high=rh if rh > 0 else ph,
                            buy_px=float(pos.buy_px),
                            peak_high=ph,
                            pullback_pct=sd.pullback_pct,
                        )
                        if stop > 0 and lo <= stop + 1e-12:
                            fill = (
                                float(bar_o)
                                if bar_o > 0 and bar_o <= stop + 1e-12
                                else float(stop)
                            )
                            proceeds = float(fill) * int(pos.shares)
                            cash += proceeds
                            trades.append(
                                {
                                    "date": sess,
                                    "ts": str(ts),
                                    "side": "sell",
                                    "code": code,
                                    "name": pos.name,
                                    "px": float(fill),
                                    "shares": int(pos.shares),
                                    "pnl_pct": round(float(fill) / pos.buy_px - 1.0, 4)
                                    if pos.buy_px
                                    else None,
                                    "exit_reason": reason,
                                    "slots_after": len(positions) - 1,
                                }
                            )
                            del positions[code]
                            st.sold_today = True
                            st.buy_armed = bool(allow_open_rebuy)
                            st.pending_buy = None
                            last_px[code] = float(fill)
                            _try_fill_from_queue(sess, str(ts))
                            continue
                elif (
                    (not can_sell)
                    and exit_mode not in ("half_gain", "multi_tp")
                ):
                    stop, _reason = _exit_stop_px(
                        mode=exit_mode,
                        running_high=max(rh, ph, float(pos.buy_px)),
                        buy_px=float(pos.buy_px),
                        peak_high=max(ph, float(pos.buy_px)),
                        pullback_pct=sd.pullback_pct,
                    )
                    if stop > 0 and lo <= stop + 1e-12:
                        prev_n = float(pos.stop_noted_px or 0) if pos.stop_noted_px else 0.0
                        pos.stop_noted_px = stop if prev_n <= 0 else min(prev_n, stop)
                # 更新持仓峰值
                if code in positions:
                    positions[code].peak_high = max(ph, h)
                    positions[code].held_low = min(float(positions[code].held_low), lo)
                    st.running_high = max(rh, h)
                    last_px[code] = (h + lo) / 2.0
                    # T+1 已记后，后续分钟低点仍远高于已记 → 作废（涨停封死/收回）
                    if not can_sell:
                        pos_n = positions[code]
                        noted2 = (
                            float(pos_n.stop_noted_px or 0)
                            if pos_n.stop_noted_px
                            else 0.0
                        )
                        if noted2 > 0 and lo > noted2 * 1.005 + 1e-12:
                            pos_n.stop_noted_px = None
                            pos_n.tp_marked = False

            # —— 买：本分钟新触达 ——
            new_hits: list[dict[str, Any]] = []
            for _, code, h, lo, bar_o in bucket:
                if code in positions:
                    continue
                st = states.get(code)
                sd = day_map.get(code)
                if st is None or sd is None:
                    continue
                if (not st.buy_armed) or (not sd.allow_entry):
                    continue
                if st.sold_today and (not allow_open_rebuy):
                    continue
                if st.pending_buy is not None:
                    continue
                st.running_low = min(st.running_low, lo) if allow_attack else st.running_low
                open_buy = entry_trigger_price(sd.open_px, entry_pct=sd.entry_pct)
                hit_open = h + 1e-12 >= open_buy
                hit_attack = False
                attack = 0.0
                if allow_attack:
                    attack = attack_buy_trigger_price(
                        st.running_low, entry_pct=sd.entry_pct
                    )
                    hit_attack = attack > 0 and (h + 1e-12 >= attack)
                if not (hit_open or hit_attack):
                    st.running_high = max(st.running_high, h)
                    continue
                if hit_attack and (not hit_open or attack <= open_buy + 1e-12):
                    buy_px, buy_kind = float(attack), "attack"
                else:
                    buy_px, buy_kind = float(open_buy), "open"
                rebuy = bool(st.sold_today and allow_open_rebuy)
                st.pending_buy = {
                    "day": sess,
                    "ts": str(ts),
                    "code": code,
                    "name": sd.name,
                    "px": buy_px,
                    "kind": buy_kind,
                    "source": "open_rebuy_after_sell" if rebuy else "trigger",
                }
                st.buy_armed = False
                new_hits.append(st.pending_buy)
                st.running_high = max(st.running_high, h)

            # 先触发先买：同一分钟内按代码稳定序（时间戳已相同）
            new_hits.sort(key=lambda x: (str(x["ts"]), str(x["code"])))
            for cand in new_hits:
                code = cand["code"]
                if code in positions:
                    continue
                st_c = states.get(code)
                if st_c is not None and st_c.sold_today and (not allow_open_rebuy):
                    skipped.append({**cand, "reason": "sold_today_no_rebuy"})
                    continue
                if _can_open_buy(ts):
                    px = float(cand["px"])
                    eq = _equity_now()
                    budget = eq * float(slot_weight)
                    shares = _lot_shares(budget, px)
                    if shares < 100:
                        skipped.append({**cand, "reason": "budget_too_small"})
                        continue
                    cost = shares * px
                    if cost > cash + 1e-6:
                        shares = _lot_shares(cash, px)
                        cost = shares * px
                    if shares < 100:
                        skipped.append({**cand, "reason": "cash_too_small"})
                        continue
                    cash -= cost
                    buys_today += 1
                    positions[code] = _Pos(
                        code=code,
                        name=str(cand["name"]),
                        buy_day=sess,
                        buy_px=px,
                        buy_ts=str(cand["ts"]),
                        shares=shares,
                        cost=cost,
                        kind=cand.get("kind"),
                        peak_high=px,
                        held_low=px,
                    )
                    trades.append(
                        {
                            "date": sess,
                            "ts": str(cand["ts"]),
                            "side": "buy",
                            "code": code,
                            "name": cand["name"],
                            "px": px,
                            "shares": shares,
                            "kind": cand.get("kind"),
                            "source": cand.get("source") or "trigger",
                            "slots_after": len(positions),
                        }
                    )
                else:
                    if buys_today >= max_buys:
                        skipped.append({**cand, "reason": "max_buys_per_day"})
                    else:
                        wait_q.append({**cand, "queued_at": str(ts)})

        # 日末：未成交等待作废；持仓市值按收盘
        # 尾盘空槽：隔夜最多 max_overnight；超出则强制卖出可卖仓中浮盈最差一只
        while len(positions) > max_overnight:
            cands: list[tuple[float, str, float]] = []
            for code, pos in list(positions.items()):
                if is_t1_buy_day(pos.buy_day, sess):
                    continue
                sd = day_map.get(code)
                px = float(last_px.get(code) or (sd.close_px if sd and sd.close_px else pos.buy_px))
                if px <= 0 or not pos.buy_px:
                    continue
                cands.append((float(px) / float(pos.buy_px) - 1.0, code, px))
            if not cands:
                break
            cands.sort(key=lambda x: x[0])
            _pnl, code, fill = cands[0]
            pos = positions[code]
            proceeds = float(fill) * int(pos.shares)
            cash += proceeds
            trades.append(
                {
                    "date": sess,
                    "ts": f"{sess} 14:57:00",
                    "side": "sell",
                    "code": code,
                    "name": pos.name,
                    "px": float(fill),
                    "shares": int(pos.shares),
                    "pnl_pct": round(float(fill) / pos.buy_px - 1.0, 4) if pos.buy_px else None,
                    "exit_reason": "eod_reserve_slot",
                    "slots_after": len(positions) - 1,
                }
            )
            del positions[code]
            st = states.get(code)
            if st is not None:
                st.sold_today = True
                st.buy_armed = bool(allow_open_rebuy)
            last_px[code] = float(fill)

        for cand in wait_q:
            skipped.append({**cand, "reason": "slots_full_unfilled_eod"})
        wait_q.clear()
        for code, sd in day_map.items():
            if sd.close_px:
                last_px[code] = float(sd.close_px)

        # 研究：因子22 日末同日再买（生产默认关闭；须当日已卖且收盘确认）
        if allow_f22 and buys_today < max_buys:
            f22_cands: list[dict[str, Any]] = []
            for code, st in states.items():
                if code in positions or not st.sold_today:
                    continue
                sd = day_map.get(code)
                if sd is None or not sd.close_px or not sd.open_px:
                    continue
                bars = sd.bars
                if bars is None or getattr(bars, "empty", True):
                    day_hi = float(sd.close_px)
                    day_lo = float(sd.close_px)
                else:
                    day_hi = float(bars["high"].max())
                    day_lo = float(bars["low"].min())
                sig = rebuy_signal(
                    open_px=float(sd.open_px),
                    high_px=day_hi,
                    low_px=day_lo,
                    close_px=float(sd.close_px),
                    bounce_pct=f22_bounce,
                    candle="any",
                    mode="close",
                    tick_ceil=lambda p: ceil_to_tick(p, TICK_SIZE),
                )
                if not sig.get("ok") or sig.get("fill_px") is None:
                    continue
                f22_cands.append(
                    {
                        "day": sess,
                        "ts": f"{sess} 14:57:00",
                        "code": code,
                        "name": sd.name,
                        "px": float(sig["fill_px"]),
                        "kind": "factor22",
                        "source": "f22_close_rebuy",
                    }
                )
            f22_cands.sort(key=lambda x: (str(x["ts"]), str(x["code"])))
            for cand in f22_cands:
                if not _can_open_buy(pd.Timestamp(cand["ts"])):
                    skipped.append({**cand, "reason": "f22_no_slot_or_buy_cap"})
                    continue
                code = cand["code"]
                if code in positions:
                    continue
                px = float(cand["px"])
                eq = _equity_now()
                budget = eq * float(slot_weight)
                shares = _lot_shares(budget, px)
                if shares < 100:
                    skipped.append({**cand, "reason": "f22_budget_too_small"})
                    continue
                cost = shares * px
                if cost > cash + 1e-6:
                    shares = _lot_shares(cash, px)
                    cost = shares * px
                if shares < 100:
                    skipped.append({**cand, "reason": "f22_cash_too_small"})
                    continue
                cash -= cost
                buys_today += 1
                positions[code] = _Pos(
                    code=code,
                    name=str(cand["name"]),
                    buy_day=sess,
                    buy_px=px,
                    buy_ts=str(cand["ts"]),
                    shares=shares,
                    cost=cost,
                    kind="factor22",
                    peak_high=px,
                    held_low=px,
                )
                st = states.get(code)
                if st is not None:
                    st.sold_today = True  # 仍记当日已交易，防开盘阈值再买叠仓
                    st.buy_armed = False
                trades.append(
                    {
                        "date": sess,
                        "ts": str(cand["ts"]),
                        "side": "buy",
                        "code": code,
                        "name": cand["name"],
                        "px": px,
                        "shares": shares,
                        "kind": "factor22",
                        "source": "f22_close_rebuy",
                        "slots_after": len(positions),
                    }
                )
                last_px[code] = px
        # 日末：买入日按盈利/亏损门槛决定是否把已记带到次日
        for code, pos in list(positions.items()):
            px = float(last_px.get(code) or pos.buy_px or 0)
            sd = day_map.get(code)
            hard = float(sd.pullback_pct) if sd else DEFAULT_PULLBACK_PCT
            if is_t1_buy_day(pos.buy_day, sess):
                day_lo = (
                    float(pos.held_low)
                    if pos.held_low < float("inf")
                    else None
                )
                dec = resolve_t1_overnight_note(
                    cost_px=float(pos.buy_px),
                    peak_high=float(pos.peak_high or pos.buy_px),
                    close_px=px,
                    hard_pct=hard,
                    bar_low=day_lo,
                )
                pos.stop_noted_px = dec.get("noted_px")
                pos.tp_marked = bool(dec.get("noted_px"))
                pos.yday_loss = str(dec.get("reason") or "") == "hard_from_cost"
            else:
                pos.yday_loss = bool(px > 0 and pos.buy_px > 0 and px < float(pos.buy_px))
        eq = _equity_now()
        equity_rows.append(
            {
                "date": sess,
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "n_pos": len(positions),
                "codes": ",".join(sorted(positions.keys())),
                "ret_pct": round((eq / float(initial_cash) - 1.0) * 100.0, 2),
            }
        )

    # 未平仓浮盈
    open_pnl = []
    for code, pos in positions.items():
        px = float(last_px.get(code) or pos.buy_px)
        open_pnl.append(
            {
                "code": code,
                "name": pos.name,
                "buy_day": pos.buy_day,
                "buy_px": pos.buy_px,
                "last_px": px,
                "shares": pos.shares,
                "pnl_pct": round(px / pos.buy_px - 1.0, 4) if pos.buy_px else None,
            }
        )

    final_eq = equity_rows[-1]["equity"] if equity_rows else float(initial_cash)
    closed = [t for t in trades if t["side"] == "sell" and t.get("pnl_pct") is not None]
    avg_closed = (
        round(sum(float(t["pnl_pct"]) for t in closed) / len(closed) * 100.0, 2)
        if closed
        else None
    )
    peak = float(initial_cash)
    max_dd = 0.0
    last_peak_date = None
    dd_peak_date = None
    trough_date = None
    for e in equity_rows:
        v = float(e.get("equity") or 0)
        d = e.get("date")
        if v > peak:
            peak = v
            last_peak_date = d
        if peak > 0:
            dd = v / peak - 1.0
            if dd < max_dd:
                max_dd = dd
                dd_peak_date = last_peak_date
                trough_date = d
    return {
        "trades": trades,
        "equity": equity_rows,
        "skipped_buys": skipped,
        "open_positions": open_pnl,
        "summary": {
            "window_days": len(calendar),
            "calendar": calendar,
            "max_slots": max_slots,
            "slot_weight": slot_weight,
            "initial_cash": initial_cash,
            "final_equity": final_eq,
            "return_pct": round((final_eq / float(initial_cash) - 1.0) * 100.0, 2),
            "max_dd_pct": round(max_dd * 100.0, 2),
            "dd_peak_date": dd_peak_date,
            "dd_trough_date": trough_date,
            "n_buys": sum(1 for t in trades if t["side"] == "buy"),
            "n_sells": sum(1 for t in trades if t["side"] == "sell"),
            "n_closed": len(closed),
            "avg_closed_pnl_pct": avg_closed,
            "n_open": len(positions),
            "n_skipped_or_queued": len(skipped),
            "exit_mode": exit_mode,
            "buy_mode": bmode,
            "reserve_empty": reserve,
            "max_overnight": max_overnight,
            "max_buys_per_day": max_buys,
        },
    }


LEDGER_REASON_ZH = {
    "attack": "攻击波买",
    "open": "开盘突破买",
    "queue_fill": "排队补仓",
    "t1_peak_trail": "未到3%·次日动态峰值回落2.5%全清",
    "vol_giveback": "中赚（3–10%）动态高点回落0.5×20日日频σ全清（与回落一半谁先到走谁）",
    "noted_open_dump": "已记·开盘下杀1%全清（研究对照）",
    "noted_gap_open": "已记·低开按开盘卖（研究模式）",
    "noted_open": "已记·次日开盘市价卖（研究模式）",
    "half_gain": "中赚（3–10%）浮盈回落一半全清（与波动回落谁先到走谁）",
    "hard_from_cost": "成本硬保护（亏≥2.5%）",
    "ladder_half_10": "大赚·浮盈10%卖一半",
    "ladder_half_10_clear": "已半仓后再触10%·剩余全清",
    "ladder_full_15": "大赚·浮盈15%全清",
    "peak_pullback_clear": "大赚后峰值回落2%清仓",
    "overnight_open_dump": "隔夜武装·开盘下杀1%全清（研究对照）",
    "eod_reserve_slot": "尾盘空槽强制卖",
}


def _ledger_buy_logic(t: dict[str, Any]) -> str:
    kind = str(t.get("kind") or "attack")
    src = str(t.get("source") or "")
    base = LEDGER_REASON_ZH.get(kind, kind or "买入")
    if src == "queue_fill":
        trig = str(t.get("trigger_ts") or "")
        hhmm = trig[11:16] if len(trig) >= 16 else trig
        return f"{base}·排队补仓（触{hhmm}）" if hhmm else f"{base}·排队补仓"
    return base


def _ledger_sell_logic(t: dict[str, Any]) -> str:
    er = str(t.get("exit_reason") or "")
    return LEDGER_REASON_ZH.get(er, er or "卖出")


def _annotate_ledger_trades(
    trades: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """FIFO 配对买卖，半仓留下余股。"""
    lots: dict[str, list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []
    for t in trades:
        row = dict(t)
        code = str(t.get("code") or "")
        sh = int(t.get("shares") or 0)
        try:
            px = float(t.get("px") or 0)
        except (TypeError, ValueError):
            px = 0.0
        row["amount"] = round(px * sh, 2) if px > 0 and sh > 0 else 0.0
        side = str(t.get("side") or "")
        if side == "buy":
            lots.setdefault(code, []).append(
                {
                    "ts": t.get("ts"),
                    "px": px,
                    "shares": sh,
                    "name": t.get("name"),
                    "code": code,
                }
            )
            row["matched_buy"] = ""
            row["logic"] = _ledger_buy_logic(t)
            row["left_after_lot"] = sh
        else:
            need = sh
            matched: list[tuple[dict[str, Any], int]] = []
            q = lots.setdefault(code, [])
            while need > 0 and q:
                lot = q[0]
                take = min(int(lot["shares"]), need)
                matched.append((lot, take))
                lot["shares"] = int(lot["shares"]) - take
                need -= take
                if int(lot["shares"]) <= 0:
                    q.pop(0)
            if matched:
                lot0, _ = matched[0]
                try:
                    bpx = float(lot0["px"])
                    bpx_s = f"{bpx:g}"
                except (TypeError, ValueError):
                    bpx = 0.0
                    bpx_s = str(lot0.get("px") or "")
                row["matched_buy"] = f"{lot0.get('ts') or ''} @{bpx_s}".strip()
                row["matched_buy_px"] = bpx
                left = sum(int(x["shares"]) for x in q)
                row["left_after_lot"] = left
                if bpx > 0:
                    row["realized_pnl"] = round((px - bpx) * sh, 2)
                else:
                    row["realized_pnl"] = None
            else:
                row["matched_buy"] = ""
                row["matched_buy_px"] = None
                row["left_after_lot"] = 0
                row["realized_pnl"] = None
            row["logic"] = _ledger_sell_logic(t)
        out.append(row)
    return out, lots


def write_trade_ledger(
    *,
    path: Path,
    trades: list[dict[str, Any]],
    equity: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    summary: dict[str, Any],
    buy_label: str,
    n_pool: int,
    title: str = "策略一定盘池",
) -> None:
    """写出详细交割单（研究用途，非投资建议）。"""
    ps = summary.get("portfolio") or summary
    cal = ps.get("calendar") or []
    cal_s = "～".join([str(cal[0]), str(cal[-1])]) if len(cal) >= 2 else "、".join(str(x) for x in cal)
    annotated, leftover = _annotate_ledger_trades(list(trades or []))
    n_buy = sum(1 for t in annotated if t.get("side") == "buy")
    n_sell = sum(1 for t in annotated if t.get("side") == "sell")
    lines = [
        f"# 交割单 · {title} 1m 三槽",
        "",
        "> 研究用途，非投资建议。未计佣金/印花税/滑点。",
        "",
        "## 摘要",
        "",
        f"- 池：{n_pool} 只；窗：{cal_s}（{ps.get('window_days', len(cal))} 个交易日）",
        f"- 买 {n_buy} / 卖 {n_sell}；期末权益 {ps.get('final_equity', '—')}（{ps.get('return_pct', '—')}%）",
        f"- 最大回撤 {ps.get('max_dd_pct', '—')}%"
        + (
            f"（{ps.get('dd_peak_date')} → {ps.get('dd_trough_date')}）"
            if ps.get("dd_peak_date")
            else ""
        ),
        f"- 已平仓回合 {ps.get('n_closed', 0)}（均收益 {ps.get('avg_closed_pnl_pct', '—')}%）；期末持仓 {ps.get('n_open', 0)} 只",
        f"- 组合：物理 {ps.get('max_slots', 3)} 槽（隔夜可持 {ps.get('max_overnight', 3)}）；日最多买 {ps.get('max_buys_per_day', 2)}；每槽约 {float(ps.get('slot_weight') or 0.3)*100:.0f}%",
        f"- 买={buy_label}；卖=硬保护2.5% / 中赚3–10%回落一半与0.5×20日日频σ谁先到走谁 / 阶梯10%·15% / 大赚后回落2% / 买入日未到3%则次日峰值回落2.5%",
        f"- T+1：买入日盈利≥3%不记、其余都记（次日走峰值回落2.5%，到3%改中段，到10%改分段）；当日卖出禁再买该票",
        "",
        "## 标签速查",
        "",
        "| 标签 | 含义 |",
        "|------|------|",
        "| `attack` | 攻击波买 |",
        "| `open` | 开盘突破买 |",
        "| `queue_fill` | 槽满后排队，释放再补 |",
        "| `t1_peak_trail` | 买入日未到 3% 已记且当日尚未 >3% → 次日动态峰值回落 2.5% 全清 |",
        "| `vol_giveback` | 中赚 >3% 且 <10% → 峰值回落 0.5×近20日日频σ 全清（与回落一半谁先到走谁） |",
        "| `noted_open_dump` | 研究对照：已记开盘下杀 1%（生产不用） |",
        "| `half_gain` | 中赚 >3% 且 <10% → 浮盈回落一半全清（与波动回落谁先到走谁） |",
        "| `ladder_half_10` | 浮盈 ≥10% → 卖一半 |",
        "| `ladder_full_15` | 浮盈 ≥15% → 全清 |",
        "| `peak_pullback_clear` | 峰值浮盈 ≥10% 后再回落 2 个点 → 清仓 |",
        "| `hard_from_cost` | 相对成本亏 ≥2.5% → 硬保护 |",
        "| `overnight_open_dump` | 研究对照：隔夜武装开盘下杀 1% |",
        "",
        "## 交割明细（时间序）",
        "",
        "| # | 时间 | 方向 | 代码 | 名称 | 价 | 股 | 金额 | 槽后 | 盈亏% | 余股 | 对应买入 | 逻辑 |",
        "|---|------|------|------|------|----|----|------|------|-------|------|----------|------|",
    ]
    for i, t in enumerate(annotated, 1):
        pnl = t.get("pnl_pct")
        pnl_s = "" if pnl is None else f"{float(pnl) * 100:.2f}%"
        amt = t.get("amount") or 0.0
        left = t.get("left_after_lot")
        left_s = "" if left is None else str(int(left))
        if str(t.get("side")) == "buy":
            left_s = str(int(t.get("shares") or 0))
        lines.append(
            f"| {i} | {t.get('ts', '')} | {t.get('side')} | {t.get('code')} | {t.get('name')} | "
            f"{t.get('px')} | {t.get('shares')} | {amt:,.0f} | {t.get('slots_after', '')} | "
            f"{pnl_s} | {left_s} | {t.get('matched_buy') or ''} | {t.get('logic') or ''} |"
        )
    if not annotated:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | 无成交 |")

    # 按标的回合
    by_code: dict[str, list[dict[str, Any]]] = {}
    for t in annotated:
        by_code.setdefault(str(t.get("code")), []).append(t)
    lines.extend(["", "## 按标的拆解", ""])
    for code, rows in by_code.items():
        name = rows[0].get("name") or ""
        lines.append(f"### {code} {name}")
        lines.append("")
        realized = 0.0
        has_pnl = False
        for t in rows:
            side = "买" if t.get("side") == "buy" else "卖"
            extra = t.get("logic") or ""
            pnl = t.get("pnl_pct")
            pnl_s = "" if pnl is None else f"，盈亏 {float(pnl)*100:.2f}%"
            rp = t.get("realized_pnl")
            if rp is not None:
                has_pnl = True
                realized += float(rp)
            mb = t.get("matched_buy") or ""
            mb_s = f"；对 {mb}" if mb else ""
            lines.append(
                f"- {t.get('ts')} {side} {t.get('shares')}股 @ {t.get('px')}（{t.get('amount', 0):,.0f}）"
                f"{pnl_s}{mb_s}。{extra}"
            )
        left_lots = leftover.get(code) or []
        shown_left = False
        for lot in left_lots:
            if int(lot.get("shares") or 0) <= 0:
                continue
            shown_left = True
            lines.append(
                f"- 期末余 {int(lot['shares'])}股，成本 {lot.get('px')}（买于 {lot.get('ts')}）"
            )
        if has_pnl:
            lines.append(f"- 本窗已实现盈亏约 {realized:,.0f} 元")
        lines.append("")

    lines.extend(
        [
            "## 日末持仓",
            "",
            "| 日期 | 权益 | 现金 | 持仓数 | 持仓 | 累计% |",
            "|------|------|------|--------|------|-------|",
        ]
    )
    for e in equity or []:
        eq = e.get("equity")
        cash = e.get("cash")
        try:
            eq_s = f"{float(eq):,.0f}"
        except (TypeError, ValueError):
            eq_s = str(eq)
        try:
            cash_s = f"{float(cash):,.0f}"
        except (TypeError, ValueError):
            cash_s = str(cash)
        lines.append(
            f"| {e.get('date')} | {eq_s} | {cash_s} | {e.get('n_pos')} | "
            f"{e.get('codes') or '—'} | {e.get('ret_pct')} |"
        )

    if open_positions:
        lines.extend(
            [
                "",
                "## 期末未平仓",
                "",
                "| 代码 | 名称 | 买日 | 买价 | 现价 | 股数 | 市值 | 浮盈额 | 浮盈% |",
                "|------|------|------|------|------|------|------|--------|-------|",
            ]
        )
        for p in open_positions:
            try:
                last = float(p.get("last_px") or 0)
                cost = float(p.get("buy_px") or 0)
                sh = int(p.get("shares") or 0)
            except (TypeError, ValueError):
                last, cost, sh = 0.0, 0.0, 0
            mkt = round(last * sh, 2)
            u_pnl = round((last - cost) * sh, 2)
            pp = p.get("pnl_pct")
            pp_s = "" if pp is None else f"{float(pp) * 100:.2f}"
            lines.append(
                f"| {p.get('code')} | {p.get('name')} | {p.get('buy_day')} | {p.get('buy_px')} | "
                f"{p.get('last_px')} | {sh} | {mkt:,.0f} | {u_pnl:,.0f} | {pp_s} |"
            )

    lines.extend(["", "研究用途，非投资建议。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    *,
    days: int = 7,
    refresh: bool = False,
    entry_pct: float | None = None,
    max_slots: int = MAX_PORTFOLIO_SLOTS,
    source: str = "auto",
    buy_mode: str = BUY_MODE_DEFAULT,
    tag: str | None = None,
    pool: str = POOL_STRATEGY1,
    fit_thr: bool = False,
) -> dict:
    entry = float(entry_pct if entry_pct is not None else DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    bmode = str(buy_mode or BUY_MODE_DEFAULT).strip().lower()
    if bmode not in BUY_MODES:
        bmode = BUY_MODE_DEFAULT
    allow_attack = bmode == BUY_MODE_OPEN_OR_ATTACK
    pool_id = str(pool or POOL_STRATEGY1).strip().lower()
    if pool_id in ("s16", "core_leader"):
        pool_id = POOL_STRATEGY16
    is_s16 = pool_id == POOL_STRATEGY16
    suffix = str(tag or "").strip()
    if not suffix and bmode != BUY_MODE_DEFAULT:
        suffix = "attack" if bmode == BUY_MODE_OPEN_OR_ATTACK else bmode
    pool_rows = _load_pool(pool_id)
    if is_s16:
        need_fit = bool(fit_thr) or not load_strategy16_thr_map()
        if need_fit:
            import importlib.util

            _fit_py = _ROOT / "backtest" / "strategy16_core_leader" / "fit_thr.py"
            spec = importlib.util.spec_from_file_location("s16_fit_thr", _fit_py)
            if spec is None or spec.loader is None:
                raise SystemExit(f"无法加载 {_fit_py}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.fit_strategy16_thresholds()
            pool_rows = _load_pool(pool_id)
    out_dir = (
        _ROOT / "backtest" / "strategy16_core_leader" if is_s16 else OUT
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    strat_title = (
        "策略十六·核心龙头（因子27 池 + 天通/凯盛）"
        if is_s16
        else "策略一定盘池"
    )
    rows: list[dict] = []
    stock_payload: list[dict[str, Any]] = []
    buy_label = "开盘突破" if bmode == BUY_MODE_OPEN else "开盘突破或攻击波"
    s16_thr_note = ""
    if is_s16:
        n_fitted = sum(
            1
            for w in pool_rows
            if abs(float(w.get("entry_pct") or entry) - float(entry)) > 1e-12
        )
        s16_thr_note = (
            f" · 开盘阈值=2026至今个股择优（{n_fitted}/{len(pool_rows)} 只非默认）"
        )
    print(
        f"{strat_title} {len(pool_rows)} 只 · 近 {days} 交易日 1m · source={source} · "
        f"三槽≤{max_slots} · 先触发先买 · 买={buy_label}{s16_thr_note}"
    )

    for w in pool_rows:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        sp = float(pb) if is_s16 else float(w.get("stop_pct") or w.get("pct") or pb)
        print(f"· {code} {name} 开盘±{ep*100:.1f}% …", flush=True)
        daily = _daily(sina)
        mins = _minutes(sina, refresh=refresh, days=int(days), source=source)
        rep = replay_factor26_1m(
            daily,
            mins,
            entry_pct=ep,
            pullback_pct=sp,
            last_n_days=int(days),
            allow_attack=allow_attack,
        )
        pnl, n_round = _trade_pnl(list(rep.get("trades") or []))
        rows.append(
            {
                "code": code,
                "name": name,
                "sina": sina,
                "entry_pct": ep,
                "pullback_pct": sp,
                "days_used": rep.get("days_used"),
                "holding": bool(rep.get("holding")),
                "n_trades": len(rep.get("trades") or []),
                "n_rounds": n_round,
                "pnl_pct": None if pnl is None else round(pnl * 100.0, 2),
                "last_side": rep.get("last_trigger_side"),
                "last_px": rep.get("last_trigger_px"),
                "last_date": (
                    str(rep.get("last_trigger_date"))[:10]
                    if rep.get("last_trigger_date") is not None
                    else None
                ),
                "trades": rep.get("trades") or [],
            }
        )
        stock_payload.append(
            {
                "code": code,
                "name": name,
                "entry_pct": ep,
                "pullback_pct": sp,
                "daily": daily,
                "minutes": mins,
            }
        )

    print("\n组合三槽回放…", flush=True)
    port = simulate_portfolio_3slots(
        stock_payload,
        days=int(days),
        max_slots=int(max_slots),
        initial_cash=float(DEFAULT_ACCOUNT_TOTAL),
        slot_weight=float(SLOT_WEIGHT),
        buy_mode=bmode,
    )
    ps = port.get("summary") or {}

    df = pd.DataFrame(rows)
    finished = df[df["pnl_pct"].notna()] if not df.empty else df
    eq_pnl = float(finished["pnl_pct"].mean()) if len(finished) else None
    if eq_pnl is not None:
        eq_pnl = round(eq_pnl, 2)
    th = derive_thresholds()
    summary = {
        "window_days": int(days),
        "n_pool": len(pool_rows),
        "pool": pool_id,
        "n_with_rounds": int(len(finished)),
        "equal_weight_pnl_pct": eq_pnl,
        "portfolio": ps,
        "max_slots": int(max_slots),
        "slot_weight": float(SLOT_WEIGHT),
        "priority": "first_trigger_first_buy",
        "buy_mode": bmode,
        "entry_by_code": {
            str(w.get("code")): float(w.get("entry_pct") or w.get("pct") or entry)
            for w in pool_rows
        }
        if is_s16
        else None,
        "factor2_alert": th.as_dict(),
        "factor2_label": th.label(),
        "factor2_rules": format_rules(th),
        "factor2_note": "样本过短，回撤预警仅作阈值展示",
        "disclaimer": "研究用途，非投资建议；1m 约近数日；未计费/滑点；三槽先触发先买。",
    }

    stem = f"_{suffix}" if suffix else ""
    out_csv = out_dir / f"pool_1m_7d{stem}.csv"
    out_json = out_dir / f"pool_1m_7d{stem}.json"
    out_trades = out_dir / f"portfolio_trades{stem}.csv"
    out_eq = out_dir / f"portfolio_equity{stem}.csv"
    out_md = out_dir / (f"REPORT{stem}.md" if stem else "REPORT.md")
    out_ledger = out_dir / (f"TRADE_LEDGER{stem}.md" if stem else "TRADE_LEDGER.md")

    df.drop(columns=["trades"], errors="ignore").to_csv(out_csv, index=False)
    pd.DataFrame(port.get("trades") or []).to_csv(out_trades, index=False)
    pd.DataFrame(port.get("equity") or []).to_csv(out_eq, index=False)
    out_json.write_text(
        json.dumps(
            {
                "summary": summary,
                "rows": rows,
                "portfolio_trades": port.get("trades") or [],
                "portfolio_equity": port.get("equity") or [],
                "open_positions": port.get("open_positions") or [],
                "skipped_buys": port.get("skipped_buys") or [],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    cal = ps.get("calendar") or []
    rule_universe = (
        [
            "- **选股**：因子27 核心龙头滚动近3个月冻结池（约30只），并额外纳入天通/凯盛；本回测独立开 3 槽",
            "- **过滤**：日线（前日阴/小阳、双阳禁买）；因子2 回撤仅预警阈值，不注资",
            "- **开盘阈值**：非固定；2026-01-01 至今回测日线开盘突破，在 {2%, 2.5%, 3%} 按夏普择优（买/止损拟合同 thr）；"
            "1m 组合只用该 thr **买入**，卖出仍因子26（硬保护 2.5%）。拟合窗含本周则近 7 日有样本内重叠",
        ]
        if is_s16
        else [
            "- **选股/过滤**：日线（前日阴/小阳、双阳禁买）；因子2 回撤仅预警阈值，不注资",
        ]
    )
    lines = [
        f"# {strat_title} · 近 {days} 日 1 分钟路径回测（三槽）",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 规则",
        "",
        *rule_universe,
        "- **成交**：池内票近 N 交易日 **1 分钟** path-dependent（"
        f"买={buy_label}；"
        "卖=多层止盈：阶梯10%/15% + 中赚3–10%回落一半与波动回落谁先到走谁 + 大赚后回落2%清 + 未到3%次日峰值回落2.5%；"
        "买入日盈利≥3%不记、其余都记）",
        f"- **组合**：物理 **{max_slots}** 槽（盘中/隔夜均可持 {max_slots}）；当日最多买 **{MAX_BUYS_PER_DAY}**；"
        + (
            f"隔夜最多 **{MAX_OVERNIGHT_SLOTS}**；"
            if int(RESERVE_EMPTY_SLOTS) <= 0
            else f"尾盘空 **{RESERVE_EMPTY_SLOTS}**（隔夜最多 {MAX_OVERNIGHT_SLOTS}）；"
        )
        + "**先触发买点的先买**；"
        f"每槽约 {SLOT_WEIGHT*100:.0f}% 仓；T+1；槽满触买入队，释放后再按触发先后补；"
        f"**当日止损/已记卖出禁再买**",
        f"- 窗长：{days} 交易日；日历：{', '.join(cal) if cal else '—'}",
        (
            "- **个股开盘阈值**（2026至今夏普择优）："
            + "；".join(
                f"{r['code']}±{float(r['entry_pct'])*100:.1f}%"
                for r in rows
            )
            if is_s16
            else f"- 默认阈值 ±{entry*100:.1f}%（个股可覆盖）"
        ),
        "",
        "## 三槽组合摘要",
        "",
        f"- 初始资金：{ps.get('initial_cash', DEFAULT_ACCOUNT_TOTAL):,.0f}",
        f"- 期末权益：{ps.get('final_equity', '—')}（{ps.get('return_pct', '—')}%）",
        f"- 最大回撤：{ps.get('max_dd_pct', '—')}%"
        + (
            f"（峰值 {ps.get('dd_peak_date')} → 谷值 {ps.get('dd_trough_date')}）"
            if ps.get("dd_peak_date")
            else ""
        ),
        f"- 买入 {ps.get('n_buys', 0)} / 卖出 {ps.get('n_sells', 0)} / "
        f"已平仓回合 {ps.get('n_closed', 0)}（均收益 {ps.get('avg_closed_pnl_pct', '—')}%）",
        f"- 期末持仓：{ps.get('n_open', 0)} 只",
        f"- 因槽满排队/跳过记录：{ps.get('n_skipped_or_queued', 0)}",
        "",
        "## 组合成交",
        "",
        "| 时间 | 方向 | 代码 | 名称 | 价格 | 股数 | 备注 |",
        "|------|------|------|------|------|------|------|",
    ]
    for t in port.get("trades") or []:
        note = t.get("kind") or t.get("source") or ""
        if t.get("source") == "queue_fill" and t.get("trigger_ts"):
            note = f"排队补仓(触{str(t['trigger_ts'])[11:16]})"
        if t.get("pnl_pct") is not None:
            er = t.get("exit_reason") or ""
            note = f"{er} pnl {float(t['pnl_pct'])*100:.2f}%".strip()
        lines.append(
            f"| {t.get('ts', '')} | {t.get('side')} | {t.get('code')} | {t.get('name')} | "
            f"{t.get('px')} | {t.get('shares')} | {note} |"
        )
    if not port.get("trades"):
        lines.append("| — | — | — | — | — | — | 无成交 |")

    lines.extend(
        [
            "",
            "## 日末权益",
            "",
            "| 日期 | 权益 | 现金 | 持仓数 | 持仓 | 累计% |",
            "|------|------|------|--------|------|-------|",
        ]
    )
    for e in port.get("equity") or []:
        lines.append(
            f"| {e.get('date')} | {e.get('equity')} | {e.get('cash')} | "
            f"{e.get('n_pos')} | {e.get('codes') or '—'} | {e.get('ret_pct')} |"
        )

    if port.get("open_positions"):
        lines.extend(
            [
                "",
                "## 期末未平仓",
                "",
                "| 代码 | 名称 | 买日 | 买价 | 现价 | 浮盈% |",
                "|------|------|------|------|------|-------|",
            ]
        )
        for p in port["open_positions"]:
            pp = p.get("pnl_pct")
            lines.append(
                f"| {p['code']} | {p['name']} | {p['buy_day']} | {p['buy_px']} | "
                f"{p['last_px']} | {'' if pp is None else round(pp*100, 2)} |"
            )

    lines.extend(
        [
            "",
            "## 个股独立回放（无槽位约束，对照）",
            "",
            f"- 池子：{summary['n_pool']} 只；有完整买卖回合：{summary['n_with_rounds']}",
            f"- 等权已平仓收益：{eq_pnl if eq_pnl is not None else '—'}%",
            f"- 因子2：{summary['factor2_label']}",
            "",
            "| 代码 | 名称 | 开盘阈值 | 天数 | 成交笔数 | 回合 | 收益% | 持有 | 末次 |",
            "|------|------|----------|------|----------|------|-------|------|------|",
        ]
    )
    for r in rows:
        lines.append(
            f"| {r['code']} | {r['name']} | ±{float(r['entry_pct'])*100:.1f}% | "
            f"{r['days_used']} | {r['n_trades']} | "
            f"{r['n_rounds']} | {r['pnl_pct'] if r['pnl_pct'] is not None else '—'} | "
            f"{'Y' if r['holding'] else ''} | {r['last_side'] or ''} |"
        )
    lines.extend(
        [
            "",
            f"产物：`{out_csv.name}` / `{out_json.name}` / `{out_trades.name}` / `{out_eq.name}`"
            f" / `{out_ledger.name}`",
            "",
            summary["disclaimer"],
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    write_trade_ledger(
        path=out_ledger,
        trades=list(port.get("trades") or []),
        equity=list(port.get("equity") or []),
        open_positions=list(port.get("open_positions") or []),
        summary=summary,
        buy_label=buy_label,
        n_pool=int(summary.get("n_pool") or 0),
        title=strat_title,
    )
    print(f"\n写入 {out_csv}")
    print(f"写入 {out_md}")
    print(f"写入 {out_ledger}")
    print(
        f"三槽组合：{ps.get('return_pct', '—')}%  "
        f"回撤{ps.get('max_dd_pct', '—')}%  "
        f"买{ps.get('n_buys', 0)}/卖{ps.get('n_sells', 0)}  "
        f"期末持仓{ps.get('n_open', 0)}"
    )
    if eq_pnl is not None:
        print(f"个股等权已平仓（无槽约束）{eq_pnl:.2f}%（{len(finished)} 只）")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="策略一定盘池 1m 三槽回测（对齐实盘 T+1 止损已记）")
    ap.add_argument("--days", type=int, default=7, help="近 N 个有 1m 的交易日（长窗请 --source panda）")
    ap.add_argument("--refresh", action="store_true", help="强制重拉 1m")
    ap.add_argument(
        "--source",
        default="auto",
        choices=("auto", "panda", "ak"),
        help="1m 数据源：auto=长窗优先 Pandadata；ak=仅东财/新浪近约5日",
    )
    ap.add_argument("--entry-pct", type=float, default=None)
    ap.add_argument(
        "--max-slots",
        type=int,
        default=MAX_PORTFOLIO_SLOTS,
        help="每天最多同时持有票数（默认 3）",
    )
    ap.add_argument(
        "--buy-mode",
        default=BUY_MODE_DEFAULT,
        choices=BUY_MODES,
        help="open=只买开盘涨到阈值（默认）；open_or_attack=开盘突破或攻击波（对照）",
    )
    ap.add_argument(
        "--pool",
        default=POOL_STRATEGY1,
        choices=POOL_CHOICES,
        help="strategy1=定盘池；strategy16=因子27 核心龙头池（产物写 backtest/strategy16_core_leader/）",
    )
    ap.add_argument(
        "--fit-thr",
        action="store_true",
        help="策略十六：先按 2026 至今日线 {2/2.5/3}% 夏普重拟合开盘阈值",
    )
    ap.add_argument(
        "--tag",
        default=None,
        help="产物后缀；非默认买点会自动加 tag，避免覆盖 REPORT.md",
    )
    args = ap.parse_args()
    run(
        days=int(args.days),
        refresh=bool(args.refresh),
        entry_pct=args.entry_pct,
        max_slots=int(args.max_slots),
        source=str(args.source),
        buy_mode=str(args.buy_mode),
        tag=args.tag,
        pool=str(args.pool),
        fit_thr=bool(args.fit_thr),
    )


if __name__ == "__main__":
    main()
