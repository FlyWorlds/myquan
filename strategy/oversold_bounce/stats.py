"""超跌反弹形态 — 历史样本扫描与次日统计。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from strategy.data import append_today_if_missing, fetch_daily
from strategy.oversold_bounce.rules import (
    MAX_BODY_ABS,
    MAX_BODY_DROP_PCT,
    MIN_DAY_DROP_PCT,
    body_abs,
    body_drop_pct,
    day_change_pct,
    low_drop_pct,
    lower_shadow,
    match_oversold_hammer_yin,
)


@dataclass
class ScanConfig:
    symbol: str = "sh600552"
    symbol_name: str = "凯盛科技"
    start_date: str = "20200101"
    end_date: str = dt.date.today().strftime("%Y%m%d")
    min_day_drop_pct: float = MIN_DAY_DROP_PCT
    max_body_drop_pct: float = MAX_BODY_DROP_PCT
    max_body_abs: float = MAX_BODY_ABS
    body_mode: str = "pct"  # pct | abs


def scan_oversold_bounce(
    daily: pd.DataFrame, cfg: ScanConfig
) -> tuple[pd.DataFrame, list[dict]]:
    df = daily.copy()
    ts = pd.to_datetime(df["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    rows: list[dict] = []
    pending: list[dict] = []

    def _append_signal(i: int, *, has_next: bool) -> None:
        prev = df.iloc[i - 1]
        row = df.iloc[i]
        prev_c = float(prev["close"])
        o, h, low, c = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )
        if not match_oversold_hammer_yin(
            open_px=o,
            high_px=h,
            low_px=low,
            close_px=c,
            prev_close=prev_c,
            min_day_drop_pct=cfg.min_day_drop_pct,
            max_body_drop_pct=cfg.max_body_drop_pct,
            max_body_abs=cfg.max_body_abs,
            body_mode=cfg.body_mode,
        ):
            return

        rec = {
            "signal_day": str(row["day"]),
            "prev_close": prev_c,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "day_chg_pct": day_change_pct(c, prev_c),
            "low_drop_pct": low_drop_pct(low, prev_c),
            "body_drop_pct": body_drop_pct(o, c),
            "body_abs": body_abs(o, c),
            "lower_shadow": lower_shadow(o, c, low),
            "gap_open_pct": (o / prev_c - 1) * 100,
        }
        if has_next:
            nxt = df.iloc[i + 1]
            no, nh, nc = float(nxt["open"]), float(nxt["high"]), float(nxt["close"])
            sig_close = c
            rec.update(
                {
                    "next_day": str(nxt["day"]),
                    "next_open": no,
                    "next_high": nh,
                    "next_close": nc,
                    "next_open_vs_sig_pct": (no / sig_close - 1) * 100,
                    "next_high_vs_sig_pct": (nh / sig_close - 1) * 100,
                    "next_close_vs_sig_pct": (nc / sig_close - 1) * 100,
                }
            )
            rows.append(rec)
        else:
            pending.append(rec)

    for i in range(1, len(df) - 1):
        _append_signal(i, has_next=True)
    if len(df) >= 2:
        _append_signal(len(df) - 1, has_next=False)

    return pd.DataFrame(rows), pending


def print_scan_report(
    cfg: ScanConfig, events: pd.DataFrame, pending: list[dict] | None = None
) -> None:
    pending = pending or []
    print(f"=== {cfg.symbol_name}({cfg.symbol}) 超跌反弹形态 · 次日统计 ===")
    print(f"区间: {cfg.start_date} ~ {cfg.end_date}")
    body_label = (
        f"实体跌<{cfg.max_body_drop_pct}%"
        if cfg.body_mode == "pct"
        else f"实体<{cfg.max_body_abs}元"
    )
    print(
        f"条件: 盘中低>{cfg.min_day_drop_pct}% + 低开 + 下引线小阴 + {body_label}"
    )
    print(f"可统计样本: {len(events)} 次", end="")
    if pending:
        print(f"  |  待验信号: {len(pending)} 次（尚无次日）", end="")
    print()
    print()

    if events.empty and not pending:
        print("(无匹配日)")
        return

    if pending:
        print("【待验信号 · 尚无次日数据】")
        for r in pending:
            print(
                f"  {r['signal_day']}  低={r['low_drop_pct']:+.2f}%  "
                f"收={r['day_chg_pct']:+.2f}%  实体={r['body_drop_pct']:.2f}%  "
                f"下影={r['lower_shadow']:.2f}  O/H/L/C="
                f"{r['open']:.2f}/{r['high']:.2f}/{r['low']:.2f}/{r['close']:.2f}"
            )
        print()

    if events.empty:
        return

    print("【汇总 · 次日相对信号日收盘】")
    for col, label in [
        ("next_open_vs_sig_pct", "开盘"),
        ("next_high_vs_sig_pct", "最高"),
        ("next_close_vs_sig_pct", "收盘"),
    ]:
        s = events[col]
        win = (s > 0).sum()
        print(
            f"  次日{label}: 均{ s.mean():+.2f}%  中位{s.median():+.2f}%  "
            f"最大{s.max():+.2f}%  最小{s.min():+.2f}%  "
            f"收涨{win}/{len(s)}({win/len(s)*100:.1f}%)"
        )
    print()

    print("【明细】")
    body_hdr = "实体%" if cfg.body_mode == "pct" else "实体"
    print(
        f"  {'信号日':<12} {'低%':>6} {'收%':>6} {body_hdr:>5} {'下影':>5} "
        f"{'次日':<12} {'次开%':>7} {'次高%':>7} {'次收%':>7}  次开/高/收"
    )
    for _, r in events.iterrows():
        body_val = (
            r["body_drop_pct"] if cfg.body_mode == "pct" else r["body_abs"]
        )
        print(
            f"  {r['signal_day']:<12} {r['low_drop_pct']:>+6.2f} "
            f"{r['day_chg_pct']:>+6.2f} {body_val:>5.2f} "
            f"{r['lower_shadow']:>5.2f} {r['next_day']:<12} "
            f"{r['next_open_vs_sig_pct']:>+7.2f} {r['next_high_vs_sig_pct']:>+7.2f} "
            f"{r['next_close_vs_sig_pct']:>+7.2f}  "
            f"{r['next_open']:.2f}/{r['next_high']:.2f}/{r['next_close']:.2f}"
        )


def run_scan(cfg: ScanConfig) -> pd.DataFrame:
    from strategy.oversold_bounce.backtest import print_backtest_report

    daily = append_today_if_missing(
        fetch_daily(cfg.symbol, cfg.start_date, cfg.end_date), cfg.symbol
    )
    events, pending = scan_oversold_bounce(daily, cfg)
    print_scan_report(cfg, events, pending)
    print_backtest_report(cfg, events, daily)
    return events
