"""天通股份：因子1 止损后「同日再买」研究（仅 2026）。

基线：策略一·因子1（开盘±3%，前日阴/小阳，双阳跨日过滤，仅止损，T+1）。
变体：止损清仓后，若满足条件则当日再买（跳过前日过滤，假设路径「先触止损再反抽」）。

研究用途，非投资建议。
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from strategy.costs import ENGINE_COMMISSION_RATE, SLIPPAGE_VALUE, stamp_tax_for_code  # noqa: E402
from strategy.open_break import (  # noqa: E402
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    TICK_SIZE,
    ceil_to_tick,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)

OUT_DIR = Path(__file__).resolve().parent
DAILY_CACHE = _ROOT / "data_cache" / "sh600330_daily_qfq.parquet"
EMOTION_CSV = _ROOT / "backtest" / "strategy9_limit_down_emotion" / "emotion_index_merged.csv"

SYMBOL = "sh600330"
CODE = "600330"
ENTRY_PCT = 0.03
STOP_PCT = 0.03
START = "2026-01-01"
END = "2026-12-31"
INITIAL_CASH = 100_000.0
LOT = 100
TARGET = 0.95


RebuyFn = Callable[[dict[str, Any]], tuple[bool, float | None, str]]


@dataclass
class SimResult:
    name: str
    label: str
    return_pct: float
    pnl: float
    max_dd_pct: float
    trades: int
    stops: int
    rebuys: int
    rebuy_then_stop: int
    end_equity: float
    holding: bool
    notes: str = ""
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


def _load_daily() -> pd.DataFrame:
    df = pd.read_parquet(DAILY_CACHE)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    return df.reset_index(drop=True)


def _load_emotion() -> dict[str, str]:
    if not EMOTION_CSV.is_file():
        return {}
    em = pd.read_csv(EMOTION_CSV)
    em["date"] = pd.to_datetime(em["date"]).dt.normalize()
    out: dict[str, str] = {}
    for _, r in em.iterrows():
        out[str(r["date"].date())] = str(r.get("phase") or "")
    return out


def _buy(
    cash: float,
    px: float,
) -> tuple[float, float, float] | None:
    """返回 (cash, shares, fill_px)；失败 None。"""
    fill = float(px) * (1.0 + SLIPPAGE_VALUE)
    budget = cash * TARGET
    raw = math.floor(budget / (fill * LOT)) * LOT
    if raw < LOT:
        return None
    cost = raw * fill
    fee = cost * ENGINE_COMMISSION_RATE
    if cost + fee > cash + 1e-9:
        return None
    return cash - cost - fee, float(raw), fill


def _sell(
    cash: float,
    shares: float,
    px: float,
) -> tuple[float, float]:
    fill = float(px) * (1.0 - SLIPPAGE_VALUE)
    proceeds = shares * fill
    fee = proceeds * ENGINE_COMMISSION_RATE + proceeds * stamp_tax_for_code(CODE)
    return cash + proceeds - fee, fill


def _filters_ok(prev: pd.Series, prev2: pd.Series | None) -> bool:
    allows = prev_day_allows_entry(
        float(prev["open"]),
        float(prev["close"]),
        prev_small_yang_pct=ENTRY_PCT,
        prev_entry_mode="yin_or_small_yang",
    )
    if not allows:
        return False
    if prev2 is None:
        return True
    return not should_block_entry_by_yang(
        float(prev2["open"]),
        float(prev2["close"]),
        float(prev["open"]),
        float(prev["close"]),
        tick=TICK_SIZE,
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    )


def _max_dd(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for x in equity:
        peak = max(peak, x)
        if peak > 0:
            mdd = min(mdd, x / peak - 1.0)
    return round(mdd * 100.0, 2)


def simulate(
    daily: pd.DataFrame,
    *,
    name: str,
    label: str,
    rebuy_fn: RebuyFn | None,
    emotion: dict[str, str] | None = None,
    notes: str = "",
) -> SimResult:
    start = pd.Timestamp(START)
    end = pd.Timestamp(END)
    idxs = [
        i
        for i in range(len(daily))
        if start <= pd.Timestamp(daily.iloc[i]["date"]) <= end
    ]
    cash = INITIAL_CASH
    shares = 0.0
    buy_day: pd.Timestamp | None = None
    trades = 0
    stops = 0
    rebuys = 0
    rebuy_then_stop = 0
    last_was_rebuy = False
    eq_marks: list[float] = []
    curve: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    em = emotion or {}

    for i in idxs:
        row = daily.iloc[i]
        prev = daily.iloc[i - 1] if i >= 1 else None
        prev2 = daily.iloc[i - 2] if i >= 2 else None
        if prev is None:
            continue
        day = pd.Timestamp(row["date"]).normalize()
        day_s = str(day.date())
        o = float(row["open"])
        h = float(row["high"])
        low = float(row["low"])
        c = float(row["close"])
        if o <= 0 or c <= 0:
            continue
        buy_px = entry_trigger_price(o, entry_pct=ENTRY_PCT, tick=TICK_SIZE)
        stop_px = stop_trigger_price(o, stop_pct=STOP_PCT, tick=TICK_SIZE)
        phase = em.get(day_s, "")

        ctx = {
            "day": day_s,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "buy_px": buy_px,
            "stop_px": stop_px,
            "phase": phase,
        }

        # --- 持仓：T+1 当日不卖；否则判止损，止损后可再买 ---
        if shares > 0:
            if buy_day is not None and day == buy_day:
                eq = cash + shares * c
                eq_marks.append(eq)
                curve.append({"date": day_s, "equity": round(eq, 2)})
                continue

            stopped = False
            if low <= stop_px + 1e-12:
                lim = limit_down_state(
                    prev_close=float(prev["close"]),
                    open_px=o,
                    high_px=h,
                    low_px=low,
                    close_px=c,
                    limit_down_pct=0.10,
                    tick=TICK_SIZE,
                )
                if not bool(lim["locked"]):
                    sell_raw = float(lim["limit_px"] if bool(lim["opened"]) else stop_px)
                    cash, fill = _sell(cash, shares, sell_raw)
                    events.append(
                        {
                            "date": day_s,
                            "action": "stop",
                            "px": round(fill, 3),
                            "rebuy_src": last_was_rebuy,
                        }
                    )
                    shares = 0.0
                    buy_day = None
                    trades += 1
                    stops += 1
                    if last_was_rebuy:
                        rebuy_then_stop += 1
                    last_was_rebuy = False
                    stopped = True

            if stopped and rebuy_fn is not None:
                ok, rebuy_px, reason = rebuy_fn(ctx)
                if ok and rebuy_px is not None and h + 1e-12 >= float(rebuy_px):
                    bought = _buy(cash, float(rebuy_px))
                    if bought is not None:
                        cash, shares, fill = bought
                        buy_day = day
                        trades += 1
                        rebuys += 1
                        last_was_rebuy = True
                        events.append(
                            {
                                "date": day_s,
                                "action": "rebuy",
                                "px": round(fill, 3),
                                "reason": reason,
                            }
                        )
            eq = cash + shares * c
            eq_marks.append(eq)
            curve.append({"date": day_s, "equity": round(eq, 2)})
            continue

        # --- 空仓：标准因子1 买点 ---
        if _filters_ok(prev, prev2) and (h + 1e-12 >= buy_px):
            bought = _buy(cash, buy_px)
            if bought is not None:
                cash, shares, fill = bought
                buy_day = day
                trades += 1
                last_was_rebuy = False
                events.append(
                    {"date": day_s, "action": "buy", "px": round(fill, 3), "reason": "f1"}
                )

        eq = cash + shares * c
        eq_marks.append(eq)
        curve.append({"date": day_s, "equity": round(eq, 2)})

    end_eq = eq_marks[-1] if eq_marks else INITIAL_CASH
    return SimResult(
        name=name,
        label=label,
        return_pct=round((end_eq / INITIAL_CASH - 1.0) * 100.0, 2),
        pnl=round(end_eq - INITIAL_CASH, 2),
        max_dd_pct=_max_dd(eq_marks),
        trades=trades,
        stops=stops,
        rebuys=rebuys,
        rebuy_then_stop=rebuy_then_stop,
        end_equity=round(end_eq, 2),
        holding=shares > 0,
        notes=notes,
        equity_curve=curve,
        events=events,
    )


def _rebuy_high_open_plus(k: float) -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        thr = ceil_to_tick(float(ctx["open"]) + k, TICK_SIZE)
        if float(ctx["high"]) > float(ctx["open"]) + k + 1e-12:
            return True, thr, f"high>open+{k:g}"
        return False, None, ""

    return _fn


def _rebuy_close_gt_open() -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        if float(ctx["close"]) > float(ctx["open"]) + 1e-12:
            return True, float(ctx["close"]), "close>open"
        return False, None, ""

    return _fn


def _rebuy_close_gt_open_plus(k: float) -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        thr = float(ctx["open"]) + k
        if float(ctx["close"]) > thr + 1e-12:
            return True, float(ctx["close"]), f"close>open+{k:g}"
        return False, None, ""

    return _fn


def _rebuy_close_gt_entry() -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        if float(ctx["close"]) + 1e-12 >= float(ctx["buy_px"]):
            return True, float(ctx["buy_px"]), "close>=entry"
        return False, None, ""

    return _fn


def _rebuy_emotion(phases: set[str], *, also_close_up: bool = False) -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        phase = str(ctx.get("phase") or "")
        if phase not in phases:
            return False, None, ""
        if also_close_up and not (float(ctx["close"]) > float(ctx["open"]) + 1e-12):
            return False, None, ""
        tag = "+".join(sorted(phases))
        if also_close_up:
            tag += "&close>open"
        return True, float(ctx["close"]), f"emotion:{tag}"

    return _fn


def _rebuy_high_open_pct(pct: float) -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        thr = ceil_to_tick(float(ctx["open"]) * (1.0 + pct), TICK_SIZE)
        if float(ctx["high"]) + 1e-12 >= thr:
            return True, thr, f"high>=open*(1+{pct:.0%})"
        return False, None, ""

    return _fn


def _rebuy_high_ge_entry() -> RebuyFn:
    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        thr = float(ctx["buy_px"])
        if float(ctx["high"]) + 1e-12 >= thr:
            return True, thr, "high>=entry"
        return False, None, ""

    return _fn


def _rebuy_close_from_day_low(
    pct: float,
    *,
    require_yang: bool | None = None,
) -> RebuyFn:
    """收盘确认：收盘已站上 low×(1+pct)，成交价=该阈值。

    require_yang:
      True  → 止损日须收阳 (close>open)
      False → 止损日须收阴 (close<open)
      None  → 不限阴阳
    """
    from strategy.close_momentum import rebuy_signal
    from strategy.open_break import ceil_to_tick

    candle = "any" if require_yang is None else ("yang" if require_yang else "yin")

    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        out = rebuy_signal(
            open_px=float(ctx["open"]),
            high_px=float(ctx["high"]),
            low_px=float(ctx["low"]),
            close_px=float(ctx["close"]),
            bounce_pct=pct,
            candle=candle,  # type: ignore[arg-type]
            mode="close",
            tick_ceil=lambda p: ceil_to_tick(p, TICK_SIZE),
        )
        if out.get("ok"):
            return True, float(out["fill_px"]), str(out.get("reason") or "")
        return False, None, ""

    return _fn


def _rebuy_from_day_low(pct: float) -> RebuyFn:
    """止损后以当日最低价为锚，反弹 low×(1+pct) 再买（盘中触价，日线易高估）。"""
    from strategy.close_momentum import rebuy_signal
    from strategy.open_break import ceil_to_tick

    def _fn(ctx: dict[str, Any]) -> tuple[bool, float | None, str]:
        out = rebuy_signal(
            open_px=float(ctx["open"]),
            high_px=float(ctx["high"]),
            low_px=float(ctx["low"]),
            close_px=float(ctx["close"]),
            bounce_pct=pct,
            candle="any",
            mode="intraday",
            tick_ceil=lambda p: ceil_to_tick(p, TICK_SIZE),
        )
        if out.get("ok"):
            return True, float(out["fill_px"]), str(out.get("reason") or "")
        return False, None, ""

    return _fn


def run_all() -> list[SimResult]:
    daily = _load_daily()
    emotion = _load_emotion()
    low_close_specs: list[tuple[str, str, RebuyFn, str]] = []
    for pct, tag in ((0.01, "1"), (0.02, "2"), (0.025, "2p5"), (0.03, "3")):
        pct_label = f"{pct:.1%}".replace(".0%", "%")
        low_close_specs.append(
            (
                f"low_close_{tag}",
                f"收盘≥low×{pct_label}",
                _rebuy_close_from_day_low(pct),
                f"收盘≥low×{pct_label}；成交=阈值价",
            )
        )
        low_close_specs.append(
            (
                f"low_close_{tag}_yang",
                f"收盘≥low×{pct_label}且收阳",
                _rebuy_close_from_day_low(pct, require_yang=True),
                f"收阳 + 收盘≥low×{pct_label}",
            )
        )
        low_close_specs.append(
            (
                f"low_close_{tag}_yin",
                f"收盘≥low×{pct_label}且收阴",
                _rebuy_close_from_day_low(pct, require_yang=False),
                f"收阴 + 收盘≥low×{pct_label}",
            )
        )

    specs: list[tuple[str, str, RebuyFn | None, str]] = [
        ("baseline", "基线·不止损后再买", None, "当日止损后空仓至下一买点"),
        (
            "low_bounce_2p5",
            "最低点反弹+2.5%再买",
            _rebuy_from_day_low(0.025),
            "再买价=当日low×1.025",
        ),
        (
            "low_bounce_3",
            "最低点反弹+3%再买",
            _rebuy_from_day_low(0.03),
            "再买价=当日low×1.03",
        ),
        *low_close_specs,
        ("high_open_0", "反抽 high>开盘+0元", _rebuy_high_open_plus(0.0), "再买价=开盘"),
        ("high_open_1", "反抽 high>开盘+1元", _rebuy_high_open_plus(1.0), "再买价=开盘+1"),
        ("high_open_2", "反抽 high>开盘+2元", _rebuy_high_open_plus(2.0), "再买价=开盘+2"),
        ("high_open_3", "反抽 high>开盘+3元", _rebuy_high_open_plus(3.0), "再买价=开盘+3"),
        ("high_pct_0", "反抽 high≥开盘+0%", _rebuy_high_open_pct(0.0), "再买价=开盘"),
        ("high_pct_1", "反抽 high≥开盘+1%", _rebuy_high_open_pct(0.01), "再买价=开盘×1.01"),
        ("high_pct_2", "反抽 high≥开盘+2%", _rebuy_high_open_pct(0.02), "再买价=开盘×1.02"),
        ("high_pct_3", "反抽 high≥开盘+3%(买点)", _rebuy_high_open_pct(0.03), "再买价=开盘×1.03"),
        ("high_ge_entry", "反抽触买点(+3%)再买", _rebuy_high_ge_entry(), "再买价=买点"),
        ("close_gt_open", "收盘>开盘再买", _rebuy_close_gt_open(), "再买价=收盘"),
        ("close_gt_open_1", "收盘>开盘+1元", _rebuy_close_gt_open_plus(1.0), "再买价=收盘"),
        ("close_gt_open_2", "收盘>开盘+2元", _rebuy_close_gt_open_plus(2.0), "再买价=收盘"),
        ("close_gt_entry", "收盘≥买点(+3%)", _rebuy_close_gt_entry(), "再买价=买点"),
        (
            "emotion_calm",
            "情绪平静再买",
            _rebuy_emotion({"calm"}),
            "因子18 平静；再买价=收盘",
        ),
        (
            "emotion_not_panic",
            "情绪非恐慌再买",
            _rebuy_emotion({"calm", "normal"}),
            "因子18 非恐慌；再买价=收盘",
        ),
        (
            "emotion_calm_close_up",
            "平静且收阳再买",
            _rebuy_emotion({"calm"}, also_close_up=True),
            "平静 + close>open；再买价=收盘",
        ),
    ]
    results: list[SimResult] = []
    for name, label, fn, notes in specs:
        results.append(
            simulate(
                daily,
                name=name,
                label=label,
                rebuy_fn=fn,
                emotion=emotion,
                notes=notes,
            )
        )
    return results


def _write_outputs(results: list[SimResult]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "name": r.name,
            "label": r.label,
            "return_pct": r.return_pct,
            "pnl": r.pnl,
            "max_dd_pct": r.max_dd_pct,
            "trades": r.trades,
            "stops": r.stops,
            "rebuys": r.rebuys,
            "rebuy_then_stop": r.rebuy_then_stop,
            "end_equity": r.end_equity,
            "holding": r.holding,
            "notes": r.notes,
        }
        for r in results
    ]
    pd.DataFrame(rows).to_csv(OUT_DIR / "summary.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    baseline = next(r for r in results if r.name == "baseline")
    ranked = sorted(results, key=lambda x: x.return_pct, reverse=True)

    lines = [
        "# 天通股份 · 止损后同日再买（2026）",
        "",
        "> 研究用途，非投资建议。标的 `sh600330`，因子1 阈值 ±3%，区间 "
        f"{START}～数据末日；初始资金 {INITIAL_CASH:,.0f}。",
        "",
        "## 口径",
        "",
        "- **基线**：因子1 开盘突破买入、仅开盘止损卖出、T+1；当日止损后不再买。",
        "- **再买**：止损清仓后，若条件满足则**当日**再买（跳过前日阴/小阳过滤）。",
        "- **路径假设**：日线无法区分先后，假设「先触止损、再反抽」；若实际先冲高后砸板，反抽类会**高估**。",
        "- **最低点反弹**：止损后以当日 `low` 为锚，`high≥low×(1+2.5%/3%)` 再买。",
        "- **最低点收盘确认**：`close≥low×(1+1%/2%/2.5%/3%)`，成交=阈值价；可叠加止损日收阳/收阴。",
        "- **反抽阈值（元）**：`high > 开盘 + k` 元（k=0/1/2/3）。",
        "- **反抽阈值（%）**：`high ≥ 开盘×(1+k%)`（k=0/1/2/3）；+3% 等同再触因子1买点。",
        "- **收盘条件**：以收盘价判定，成交价=收盘或买点。",
        "- **情绪**：因子18 中证1000 低开开盘跌停家数阶段（平静/正常/恐慌）。",
        "",
        "## 结果对比",
        "",
        "| 方案 | 收益% | 盈亏 | 最大回撤% | 成交笔数 | 止损次数 | 再买次数 | 再买后止损 |",
        "|------|------:|-----:|----------:|---------:|---------:|---------:|-----------:|",
    ]
    for r in ranked:
        lines.append(
            f"| {r.label} | {r.return_pct:+.2f} | {r.pnl:+.0f} | {r.max_dd_pct:.2f} | "
            f"{r.trades} | {r.stops} | {r.rebuys} | {r.rebuy_then_stop} |"
        )
    best = ranked[0]
    lines += [
        "",
        "## 相对基线",
        "",
        f"- 基线收益 **{baseline.return_pct:+.2f}%**，最大回撤 {baseline.max_dd_pct:.2f}%。",
        f"- 样本内最高：**{best.label}**（{best.return_pct:+.2f}%），"
        f"相对基线 {best.return_pct - baseline.return_pct:+.2f} pct。",
        "",
        "## 读法提示",
        "",
        "- **最低点反弹**：实盘需盘中确认「已见低点」后才能挂 +2.5%/+3%；日线用全日 low，偏乐观。",
        "- 反抽「+0」最松、再买最多；「+3」最严。",
        "- 收盘条件偏乐观（用收盘价成交），实盘难以精确挂到收盘。",
        "- 情绪「平静」在 2026 占比很高，接近「几乎总是再买」，需与收益/回撤一起看。",
        "",
        "## 产物",
        "",
        "- `summary.csv` / `summary.json`",
        "- `run.py`",
        "",
    ]
    (OUT_DIR / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    results = run_all()
    _write_outputs(results)
    print(f"wrote {OUT_DIR / 'summary.csv'}")
    for r in sorted(results, key=lambda x: x.return_pct, reverse=True):
        print(
            f"{r.name:22s} ret={r.return_pct:+7.2f}% dd={r.max_dd_pct:6.2f}% "
            f"stops={r.stops:3d} rebuys={r.rebuys:3d} rebuy_stop={r.rebuy_then_stop:3d}"
        )


if __name__ == "__main__":
    main()
