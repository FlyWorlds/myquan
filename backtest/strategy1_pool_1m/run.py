"""策略一定盘池 · 近 7 交易日 1 分钟路径回测（三槽组合）。

选股/过滤：日线（前日阴/小阳、双阳禁买）；组合回撤看因子2 预警（不注资）。
成交：池内票近 7 日用 1 分钟 path-dependent（开盘突破/攻击波买 + 回落波止损）。

组合约束（对齐盯盘三槽）：
  · 每天最多同时持有 max_slots 只（默认 3）
  · 先触发买点的先买；槽满后触买进入等待队列，止损释放槽后再按触发先后补仓
  · T+1：买入当日不可卖；每槽约 3 成仓（权益×slot_weight）
  · 当日卖出后仍可再买（重新武装开盘/攻击波买点）

用法：
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/run.py
  PYTHONPATH=. python3 backtest/strategy1_pool_1m/run.py --days 7 --refresh --max-slots 3

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
    MAX_PORTFOLIO_SLOTS,
    SLOT_WEIGHT,
    strategy_watchlist,
)
from strategy.data import fetch_daily  # noqa: E402
from strategy.dd_alert import derive_thresholds, format_rules  # noqa: E402
from strategy.minute import pull_akshare_1m  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    floor_to_tick,
    is_t1_buy_day,
    prev_day_allows_entry,
    should_block_entry_by_yang,
)
from strategy.pullback_wave_stop import (  # noqa: E402
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
    DEFAULT_NOTED_DUMP_PCT,
    NOTED_MODE_GAP_DUMP,
    attack_buy_trigger_price,
    delayed_t1_stop_fill_px,
    entry_trigger_price,
    is_one_word_bar,
    noted_next_day_fill,
    pullback_stop_price,
    replay_factor26_1m,
)

OUT = Path(__file__).resolve().parent
CACHE = OUT / "cache_1m"
CACHE.mkdir(parents=True, exist_ok=True)


def _sina(code: str) -> str:
    c = str(code).zfill(6)
    return f"sh{c}" if c.startswith(("5", "6", "9")) else f"sz{c}"


def _em(code: str) -> str:
    return str(code).zfill(6)


def _load_pool() -> list[dict]:
    return list(strategy_watchlist())


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


@dataclass
class _DayState:
    running_high: float = 0.0
    running_low: float = field(default_factory=lambda: float("inf"))
    buy_armed: bool = True  # 当日尚未错过/成交买点前可持续扫描
    pending_buy: dict[str, Any] | None = None
    sold_today: bool = False
    noted_lock_wait: bool = False
    noted_first_exec: bool = True


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
) -> dict[str, Any]:
    """三槽组合：1m 路径，先触发买点先买，最多同时持有 max_slots 只。

    exit_mode:
      - half_gain：浮盈相对持仓最高回落一半止盈（因子26 默认；未浮盈用成本回撤保护）
      - peak_pct：旧版峰值回落阈值（对照）
    noted_mode / noted_dump_pct：T+1 止损已记后的次日规则
    """
    max_slots = max(1, int(max_slots))
    exit_mode = str(exit_mode or "half_gain")
    nmode = str(noted_mode or NOTED_MODE_GAP_DUMP)
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

    def _equity_now() -> float:
        return _mark_equity(cash, positions, last_px)

    def _try_fill_from_queue(sess: str, at_ts: str) -> None:
        nonlocal cash
        wait_q.sort(key=lambda x: (str(x["ts"]), str(x["code"])))
        while wait_q and len(positions) < max_slots:
            cand = wait_q.pop(0)
            code = cand["code"]
            if code in positions:
                continue
            if cand.get("day") != sess:
                # 隔日失效（当日未排到则作废，避免用过期触发价）
                skipped.append(
                    {
                        **cand,
                        "reason": "queue_expired_next_day",
                    }
                )
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
                    "source": "queue_fill",
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
            )
            last_px[s["code"]] = float(close_px)

        # 清空隔日等待队列
        if wait_q:
            for cand in wait_q:
                skipped.append({**cand, "reason": "queue_expired_next_day"})
            wait_q.clear()

        states: dict[str, _DayState] = {c: _DayState() for c in day_map}
        # 已持仓：分时最高从今日开盘路径起算；买入当日 T+1 不可卖
        for code, pos in positions.items():
            if code not in states:
                continue
            # 持仓票不再找新买点
            states[code].buy_armed = False

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
                if can_sell and (not st.sold_today):
                    # 先兑现「止损已记」：T+1 推迟市价离场（低开按开盘，不是已记价）
                    if noted > 0:
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
                        day_o = (
                            float(bar_o)
                            if st.noted_lock_wait
                            else float(sd.open_px)
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
                            st.buy_armed = True
                            st.pending_buy = None
                            last_px[code] = float(fill)
                            _try_fill_from_queue(sess, str(ts))
                            continue
                    can_eval = (exit_mode == "half_gain" and ph > 0) or (
                        exit_mode != "half_gain" and rh > 0
                    )
                    if can_eval:
                        stop, reason = _exit_stop_px(
                            mode=exit_mode,
                            running_high=rh if rh > 0 else ph,
                            buy_px=float(pos.buy_px),
                            peak_high=ph,
                            pullback_pct=sd.pullback_pct,
                        )
                        if stop > 0 and lo <= stop + 1e-12:
                            proceeds = float(stop) * int(pos.shares)
                            cash += proceeds
                            trades.append(
                                {
                                    "date": sess,
                                    "ts": str(ts),
                                    "side": "sell",
                                    "code": code,
                                    "name": pos.name,
                                    "px": float(stop),
                                    "shares": int(pos.shares),
                                    "pnl_pct": round(float(stop) / pos.buy_px - 1.0, 4)
                                    if pos.buy_px
                                    else None,
                                    "exit_reason": reason,
                                    "slots_after": len(positions) - 1,
                                }
                            )
                            del positions[code]
                            st.sold_today = True
                            # 当日卖出后仍可再买：重新武装买点扫描
                            st.buy_armed = True
                            st.pending_buy = None
                            last_px[code] = float(stop)
                            _try_fill_from_queue(sess, str(ts))
                            continue
                elif (not can_sell) and (not st.sold_today):
                    # T+1：触止损只记，不卖
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
                    st.running_high = max(rh, h)
                    last_px[code] = (h + lo) / 2.0

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
                if st.pending_buy is not None:
                    continue
                st.running_low = min(st.running_low, lo)
                open_buy = entry_trigger_price(sd.open_px, entry_pct=sd.entry_pct)
                attack = attack_buy_trigger_price(
                    st.running_low, entry_pct=sd.entry_pct
                )
                hit_open = h + 1e-12 >= open_buy
                hit_attack = attack > 0 and (h + 1e-12 >= attack)
                if not (hit_open or hit_attack):
                    st.running_high = max(st.running_high, h)
                    continue
                if hit_attack and (not hit_open or attack <= open_buy + 1e-12):
                    buy_px, buy_kind = float(attack), "attack"
                else:
                    buy_px, buy_kind = float(open_buy), "open"
                st.pending_buy = {
                    "day": sess,
                    "ts": str(ts),
                    "code": code,
                    "name": sd.name,
                    "px": buy_px,
                    "kind": buy_kind,
                    "source": "trigger",
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
                if len(positions) < max_slots:
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
                            "source": "trigger",
                            "slots_after": len(positions),
                        }
                    )
                else:
                    wait_q.append({**cand, "queued_at": str(ts)})

        # 日末：未成交等待作废；持仓市值按收盘
        for cand in wait_q:
            skipped.append({**cand, "reason": "slots_full_unfilled_eod"})
        wait_q.clear()
        for code, sd in day_map.items():
            if sd.close_px:
                last_px[code] = float(sd.close_px)
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
            "n_buys": sum(1 for t in trades if t["side"] == "buy"),
            "n_sells": sum(1 for t in trades if t["side"] == "sell"),
            "n_closed": len(closed),
            "avg_closed_pnl_pct": avg_closed,
            "n_open": len(positions),
            "n_skipped_or_queued": len(skipped),
            "exit_mode": exit_mode,
        },
    }


def run(
    *,
    days: int = 7,
    refresh: bool = False,
    entry_pct: float | None = None,
    max_slots: int = MAX_PORTFOLIO_SLOTS,
    source: str = "auto",
) -> dict:
    entry = float(entry_pct if entry_pct is not None else DEFAULT_ENTRY_PCT)
    pb = float(DEFAULT_PULLBACK_PCT)
    pool = _load_pool()
    rows: list[dict] = []
    stock_payload: list[dict[str, Any]] = []
    print(
        f"定盘池 {len(pool)} 只 · 近 {days} 交易日 1m · source={source} · "
        f"三槽≤{max_slots} · 先触发先买 · entry/pb={entry*100:.1f}%"
    )

    for w in pool:
        code = str(w.get("code") or "").zfill(6)
        name = str(w.get("name") or code)
        sina = str(w.get("sina") or _sina(code)).lower()
        ep = float(w.get("entry_pct") or w.get("pct") or entry)
        sp = float(w.get("stop_pct") or w.get("pct") or pb)
        print(f"· {code} {name} …", flush=True)
        daily = _daily(sina)
        mins = _minutes(sina, refresh=refresh, days=int(days), source=source)
        rep = replay_factor26_1m(
            daily,
            mins,
            entry_pct=ep,
            pullback_pct=sp,
            last_n_days=int(days),
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
        "n_pool": len(pool),
        "n_with_rounds": int(len(finished)),
        "equal_weight_pnl_pct": eq_pnl,
        "portfolio": ps,
        "max_slots": int(max_slots),
        "slot_weight": float(SLOT_WEIGHT),
        "priority": "first_trigger_first_buy",
        "factor2_alert": th.as_dict(),
        "factor2_label": th.label(),
        "factor2_rules": format_rules(th),
        "factor2_note": "样本过短，回撤预警仅作阈值展示",
        "disclaimer": "研究用途，非投资建议；1m 约近数日；未计费/滑点；三槽先触发先买。",
    }

    out_csv = OUT / "pool_1m_7d.csv"
    out_json = OUT / "pool_1m_7d.json"
    out_trades = OUT / "portfolio_trades.csv"
    out_eq = OUT / "portfolio_equity.csv"
    out_md = OUT / "REPORT.md"

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
    lines = [
        "# 策略一定盘池 · 近 7 日 1 分钟路径回测（三槽）",
        "",
        "> 研究用途，非投资建议。",
        "",
        "## 规则",
        "",
        "- **选股/过滤**：日线（前日阴/小阳、双阳禁买）；因子2 回撤仅预警阈值，不注资",
        "- **成交**：池内票近 N 交易日 **1 分钟** path-dependent（买=开盘突破或攻击波；卖=分时最高回落）",
        f"- **组合**：最多同时持有 **{max_slots}** 只；**先触发买点的先买**；"
        f"每槽约 {SLOT_WEIGHT*100:.0f}% 仓；T+1；槽满触买入队，释放后再按触发先后补；"
        f"**当日卖出后仍可再买**",
        f"- 窗长：{days} 交易日；日历：{', '.join(cal) if cal else '—'}",
        f"- 默认阈值 ±{entry*100:.1f}%（个股可覆盖）",
        "",
        "## 三槽组合摘要",
        "",
        f"- 初始资金：{ps.get('initial_cash', DEFAULT_ACCOUNT_TOTAL):,.0f}",
        f"- 期末权益：{ps.get('final_equity', '—')}（{ps.get('return_pct', '—')}%）",
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
            note = f"pnl {float(t['pnl_pct'])*100:.2f}%"
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
            "| 代码 | 名称 | 天数 | 成交笔数 | 回合 | 收益% | 持有 | 末次 |",
            "|------|------|------|----------|------|-------|------|------|",
        ]
    )
    for r in rows:
        lines.append(
            f"| {r['code']} | {r['name']} | {r['days_used']} | {r['n_trades']} | "
            f"{r['n_rounds']} | {r['pnl_pct'] if r['pnl_pct'] is not None else '—'} | "
            f"{'Y' if r['holding'] else ''} | {r['last_side'] or ''} |"
        )
    lines.extend(
        [
            "",
            f"产物：`{out_csv.name}` / `{out_json.name}` / `{out_trades.name}` / `{out_eq.name}`",
            "",
            summary["disclaimer"],
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n写入 {out_csv}")
    print(f"写入 {out_md}")
    print(
        f"三槽组合：{ps.get('return_pct', '—')}%  "
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
    args = ap.parse_args()
    run(
        days=int(args.days),
        refresh=bool(args.refresh),
        entry_pct=args.entry_pct,
        max_slots=int(args.max_slots),
        source=str(args.source),
    )


if __name__ == "__main__":
    main()
