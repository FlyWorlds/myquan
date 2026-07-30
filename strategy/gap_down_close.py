"""低开幅度分区 — 收盘阴/阳统计。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from strategy.data import fetch_daily

# 低开幅度（正数，单位 %）：(昨收 - 开盘) / 昨收 × 100
GAP_BUCKETS: tuple[tuple[str, float, float | None], ...] = (
    ("低开0~1%", 0.0, 1.0),
    ("低开1~2%", 1.0, 2.0),
    ("低开2~3%", 2.0, 3.0),
    ("低开3~4%", 3.0, 4.0),
    ("低开4%+", 4.0, None),
)


@dataclass
class GapCloseConfig:
    symbol: str = "sh600552"
    symbol_name: str = "凯盛科技"
    start_date: str = "20100101"
    end_date: str = dt.date.today().strftime("%Y%m%d")
    by_year: bool = False
    down_wave_only: bool = False  # 仅统计 MA5<MA10<MA21 的下跌波段


def _gap_down_pct(open_px: float, prev_close: float) -> float:
    if prev_close <= 0:
        return float("nan")
    return (float(prev_close) - float(open_px)) / float(prev_close) * 100.0


def _bucket_label(gap: float) -> str | None:
    if gap <= 0:
        return None
    for label, lo, hi in GAP_BUCKETS:
        if hi is None:
            if gap > lo:
                return label
        elif lo < gap <= hi:
            return label
    return None


def mark_down_wave(daily: pd.DataFrame) -> pd.DataFrame:
    """下跌波段：MA5 < MA10 < MA21（均用收盘价）。"""
    df = daily.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    df["ma5"] = close.rolling(5).mean()
    df["ma10"] = close.rolling(10).mean()
    df["ma21"] = close.rolling(21).mean()
    df["down_wave"] = (df["ma5"] < df["ma10"]) & (df["ma10"] < df["ma21"])
    return df


def analyze_gap_down_close(
    daily: pd.DataFrame, *, down_wave_only: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = mark_down_wave(daily)
    ts = pd.to_datetime(df["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    for c in ("open", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    rows: list[dict] = []
    for i in range(1, len(df)):
        prev_c = float(df.iloc[i - 1]["close"])
        row = df.iloc[i]
        o, c = float(row["open"]), float(row["close"])
        if prev_c <= 0 or o <= 0:
            continue
        gap = _gap_down_pct(o, prev_c)
        if gap <= 0:
            continue
        if down_wave_only and not bool(row.get("down_wave", False)):
            continue
        bucket = _bucket_label(gap)
        if bucket is None:
            continue
        is_yin = c + 1e-12 < o
        rows.append(
            {
                "day": str(row["day"]),
                "year": str(row["day"])[:4],
                "prev_close": prev_c,
                "open": o,
                "close": c,
                "gap_down_pct": gap,
                "bucket": bucket,
                "close_type": "阴线" if is_yin else "阳线",
                "day_chg_pct": (c / prev_c - 1) * 100,
                "down_wave": bool(row.get("down_wave", False)),
            }
        )

    events = pd.DataFrame(rows)
    if events.empty:
        summary = pd.DataFrame(
            columns=["bucket", "total", "yin", "yang", "yin_pct", "yang_pct"]
        )
        return events, summary

    summary_rows: list[dict] = []
    order = [b[0] for b in GAP_BUCKETS]
    for label in order:
        sub = events[events["bucket"] == label]
        n = len(sub)
        if n == 0:
            summary_rows.append(
                {
                    "bucket": label,
                    "total": 0,
                    "yin": 0,
                    "yang": 0,
                    "yin_pct": float("nan"),
                    "yang_pct": float("nan"),
                }
            )
            continue
        yin = int((sub["close_type"] == "阴线").sum())
        yang = n - yin
        summary_rows.append(
            {
                "bucket": label,
                "total": n,
                "yin": yin,
                "yang": yang,
                "yin_pct": yin / n * 100,
                "yang_pct": yang / n * 100,
            }
        )
    return events, pd.DataFrame(summary_rows)


def summarize_gap_down_by_year(events: pd.DataFrame) -> pd.DataFrame:
    """按年 × 低开区间汇总阴/阳。"""
    if events.empty:
        return pd.DataFrame(
            columns=["year", "bucket", "total", "yin", "yang", "yin_pct", "yang_pct"]
        )

    order = [b[0] for b in GAP_BUCKETS]
    years = sorted(events["year"].unique())
    rows: list[dict] = []
    for year in years:
        yr = events[events["year"] == year]
        for label in order:
            sub = yr[yr["bucket"] == label]
            n = len(sub)
            if n == 0:
                rows.append(
                    {
                        "year": year,
                        "bucket": label,
                        "total": 0,
                        "yin": 0,
                        "yang": 0,
                        "yin_pct": float("nan"),
                        "yang_pct": float("nan"),
                    }
                )
                continue
            yin = int((sub["close_type"] == "阴线").sum())
            yang = n - yin
            rows.append(
                {
                    "year": year,
                    "bucket": label,
                    "total": n,
                    "yin": yin,
                    "yang": yang,
                    "yin_pct": yin / n * 100,
                    "yang_pct": yang / n * 100,
                }
            )
        yin = int((yr["close_type"] == "阴线").sum())
        n = len(yr)
        rows.append(
            {
                "year": year,
                "bucket": "全年合计",
                "total": n,
                "yin": yin,
                "yang": n - yin,
                "yin_pct": yin / n * 100 if n else float("nan"),
                "yang_pct": (n - yin) / n * 100 if n else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def print_yearly_gap_down_report(events: pd.DataFrame) -> None:
    yearly = summarize_gap_down_by_year(events)
    if yearly.empty:
        return

    print()
    print("【分年统计】")
    bucket_order = [b[0] for b in GAP_BUCKETS] + ["全年合计"]
    for year in sorted(yearly["year"].unique()):
        yr = yearly[yearly["year"] == year]
        tot = yr[yr["bucket"] == "全年合计"]
        if tot.empty:
            continue
        t = tot.iloc[0]
        print()
        print(
            f"--- {year}  低开 {int(t['total'])} 天  "
            f"阴 {int(t['yin'])}({t['yin_pct']:.1f}%)  "
            f"阳 {int(t['yang'])}({t['yang_pct']:.1f}%) ---"
        )
        print(f"  {'区间':<10} {'样本':>5} {'阴线':>5} {'阳线':>5} {'阴%':>7} {'阳%':>7}")
        for label in bucket_order:
            if label == "全年合计":
                continue
            r = yr[yr["bucket"] == label]
            if r.empty or int(r.iloc[0]["total"]) == 0:
                print(f"  {label:<10} {0:>5} {'—':>5} {'—':>5} {'—':>7} {'—':>7}")
            else:
                row = r.iloc[0]
                print(
                    f"  {label:<10} {int(row['total']):>5} {int(row['yin']):>5} "
                    f"{int(row['yang']):>5} {row['yin_pct']:>6.1f}% {row['yang_pct']:>6.1f}%"
                )


def print_gap_down_close_report(
    cfg: GapCloseConfig, summary: pd.DataFrame, events: pd.DataFrame | None = None
) -> None:
    print(f"=== {cfg.symbol_name}({cfg.symbol}) 低开幅度 × 收盘阴/阳 ===")
    print(f"区间: {cfg.start_date} ~ {cfg.end_date}")
    print("口径: 低开幅度 = (昨收-开盘)/昨收×100%；收盘阴 = 收<开，阳 = 收≥开")
    if cfg.down_wave_only:
        print("过滤: 仅下跌波段（MA5 < MA10 < MA21）")
    print()
    if summary.empty or summary["total"].sum() == 0:
        print("(无低开样本)")
        return

    total_n = int(summary["total"].sum())
    total_yin = int(summary["yin"].sum())
    total_yang = int(summary["yang"].sum())
    print(f"低开合计: {total_n} 天  |  阴线 {total_yin}({total_yin/total_n*100:.1f}%)  "
          f"阳线 {total_yang}({total_yang/total_n*100:.1f}%)")
    print()
    print(f"  {'区间':<10} {'样本':>5} {'阴线':>5} {'阳线':>5} {'阴%':>7} {'阳%':>7}")
    print(f"  {'-'*10} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*7}")
    for _, r in summary.iterrows():
        if r["total"] == 0:
            print(f"  {r['bucket']:<10} {0:>5} {'—':>5} {'—':>5} {'—':>7} {'—':>7}")
        else:
            print(
                f"  {r['bucket']:<10} {int(r['total']):>5} {int(r['yin']):>5} "
                f"{int(r['yang']):>5} {r['yin_pct']:>6.1f}% {r['yang_pct']:>6.1f}%"
            )

    if cfg.by_year and events is not None and not events.empty:
        print_yearly_gap_down_report(events)


def run_gap_down_close(cfg: GapCloseConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = fetch_daily(cfg.symbol, cfg.start_date, cfg.end_date)
    marked = mark_down_wave(daily)
    ts = pd.to_datetime(marked["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    marked["day"] = ts.dt.strftime("%Y-%m-%d")
    valid = marked["ma21"].notna()
    dw_days = int(marked.loc[valid, "down_wave"].sum())
    valid_n = int(valid.sum())
    if cfg.down_wave_only:
        print(
            f"背景: 可判定 {valid_n} 个交易日中，下跌波段 {dw_days} 天"
            f"({dw_days/valid_n*100:.1f}%)"
        )
        print()

    events, summary = analyze_gap_down_close(daily, down_wave_only=cfg.down_wave_only)
    print_gap_down_close_report(cfg, summary, events)
    return events, summary


def _max_drop_from_prev(low_px: float, prev_close: float) -> float:
    """相对昨收的最大跌幅 % = (昨收 - 最低) / 昨收 × 100。"""
    if prev_close <= 0:
        return float("nan")
    return max(0.0, (float(prev_close) - float(low_px)) / float(prev_close) * 100.0)


def collect_gap_down_days(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    ts = pd.to_datetime(df["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    df["year"] = df["day"].str[:4]
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    rows: list[dict] = []
    for i in range(1, len(df)):
        prev_c = float(df.iloc[i - 1]["close"])
        row = df.iloc[i]
        o, h, low, c = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )
        if prev_c <= 0 or o <= 0:
            continue
        gap = _gap_down_pct(o, prev_c)
        if gap <= 0:
            continue
        max_drop = _max_drop_from_prev(low, prev_c)
        rows.append(
            {
                "day": str(row["day"]),
                "year": str(row["year"]),
                "prev_close": prev_c,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "gap_down_pct": gap,
                "max_drop_pct": max_drop,
                "close_chg_pct": (c / prev_c - 1) * 100,
                "intra_from_open_pct": max(0.0, (o - low) / o * 100) if o > 0 else 0.0,
            }
        )
    return pd.DataFrame(rows)


def find_gap_down_phases(daily: pd.DataFrame) -> pd.DataFrame:
    """连续低开日组成一个「低开阶段」。"""
    df = daily.copy()
    ts = pd.to_datetime(df["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    df["year"] = df["day"].str[:4]
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    phases: list[dict] = []
    i = 1
    while i < len(df):
        prev_c = float(df.iloc[i - 1]["close"])
        row = df.iloc[i]
        o = float(row["open"])
        if prev_c <= 0 or o <= 0 or _gap_down_pct(o, prev_c) <= 0:
            i += 1
            continue

        start_i = i
        ref_prev = prev_c
        min_low = float(row["low"])
        max_single_drop = _max_drop_from_prev(min_low, ref_prev)
        end_day = str(row["day"])

        i += 1
        while i < len(df):
            prev_c2 = float(df.iloc[i - 1]["close"])
            r2 = df.iloc[i]
            o2 = float(r2["open"])
            if prev_c2 <= 0 or o2 <= 0 or _gap_down_pct(o2, prev_c2) <= 0:
                break
            low2 = float(r2["low"])
            min_low = min(min_low, low2)
            drop2 = _max_drop_from_prev(low2, ref_prev)
            max_single_drop = max(max_single_drop, drop2)
            end_day = str(r2["day"])
            i += 1

        phase_drop = _max_drop_from_prev(min_low, ref_prev)
        start_day = str(df.iloc[start_i]["day"])
        phases.append(
            {
                "start_day": start_day,
                "end_day": end_day,
                "days": i - start_i,
                "year": start_day[:4],
                "ref_prev_close": ref_prev,
                "phase_min_low": min_low,
                "phase_max_drop_pct": phase_drop,
                "max_single_day_drop_pct": max_single_drop,
            }
        )
    return pd.DataFrame(phases)


def print_gap_max_drop_report(
    cfg: GapCloseConfig,
    years: list[str] | None = None,
) -> None:
    daily = fetch_daily(cfg.symbol, cfg.start_date, cfg.end_date)
    gap_days = collect_gap_down_days(daily)
    phases = find_gap_down_phases(daily)
    years = years or sorted(gap_days["year"].unique())

    print(f"=== {cfg.symbol_name}({cfg.symbol}) 低开阶段 · 最大跌幅 ===")
    print(f"区间: {cfg.start_date} ~ {cfg.end_date}")
    print("口径: 低开 = 开盘<昨收；最大跌幅 = (昨收-最低)/昨收×100%")
    print("      低开阶段 = 连续多个低开交易日")
    print()

    for year in years:
        yd = gap_days[gap_days["year"] == year]
        yp = phases[phases["year"] == year]
        print(f"【{year}】")
        if yd.empty:
            print("  (无低开日)")
            print()
            continue

        best = yd.loc[yd["max_drop_pct"].idxmax()]
        print(f"  低开日: {len(yd)} 天  |  低开阶段: {len(yp)} 段")
        print(
            f"  单日最大跌幅: {best['max_drop_pct']:.2f}%  "
            f"({best['day']}  低={best['low']:.2f} 昨收={best['prev_close']:.2f}  "
            f"低开{best['gap_down_pct']:.2f}%)"
        )
        print(
            f"  低开日跌幅: 均{yd['max_drop_pct'].mean():.2f}% "
            f"中位{yd['max_drop_pct'].median():.2f}%  "
            f"最大{yd['max_drop_pct'].max():.2f}%  最小{yd['max_drop_pct'].min():.2f}%"
        )
        if not yp.empty:
            bp = yp.loc[yp["phase_max_drop_pct"].idxmax()]
            print(
                f"  阶段最大跌幅: {bp['phase_max_drop_pct']:.2f}%  "
                f"({bp['start_day']}~{bp['end_day']} 共{int(bp['days'])}天  "
                f"最低={bp['phase_min_low']:.2f})"
            )
        print()
        print(f"  {'日期':<12} {'低开%':>6} {'最大跌%':>7} {'收盘%':>7} {'低/收':>12}")
        for _, r in yd.sort_values("day").iterrows():
            print(
                f"  {r['day']:<12} {r['gap_down_pct']:>6.2f} {r['max_drop_pct']:>7.2f} "
                f"{r['close_chg_pct']:>+7.2f} {r['low']:.2f}/{r['close']:.2f}"
            )
        if not yp.empty:
            print()
            print(f"  {'阶段':<23} {'天数':>4} {'阶段最大跌%':>10}")
            for _, p in yp.sort_values("start_day").iterrows():
                span = f"{p['start_day']}~{p['end_day']}"
                print(
                    f"  {span:<23} {int(p['days']):>4} "
                    f"{p['phase_max_drop_pct']:>10.2f}"
                )
        print()


def run_gap_max_drop(cfg: GapCloseConfig, years: list[str] | None = None) -> None:
    print_gap_max_drop_report(cfg, years=years)

