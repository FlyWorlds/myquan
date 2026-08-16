"""策略七回测：因子5事件建仓、因子1止损、五槽位每日补仓。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from strategy.data import fetch_daily
from strategy.serenity_factor5 import DEFAULT_POSTS, THEME_MAP, build_candidates


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "backtest" / "universe_zz500_1000" / "daily_cache"
OUT_DIR = ROOT / "strategy" / "runs"


def _symbol(code: str) -> str:
    return ("sh" if code.startswith(("6", "688")) else "sz") + code


def _load_panel(
    *,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """读取/补齐主题代理池行情，返回开盘、最低、收盘宽表。"""
    opens: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    name_map: dict[str, str] = {}
    for meta in THEME_MAP.values():
        for code, name in meta["symbols"].items():
            symbol = _symbol(code)
            try:
                daily = fetch_daily(
                    symbol,
                    start,
                    end,
                    cache_path=CACHE_DIR / f"{symbol}_daily_qfq.parquet",
                )
            except Exception:
                continue
            if daily.empty:
                continue
            daily = daily.copy()
            daily["date"] = pd.to_datetime(daily["date"]).dt.tz_localize(None).dt.normalize()
            daily = daily.drop_duplicates("date").set_index("date").sort_index()
            opens[code] = daily["open"].astype(float)
            lows[code] = daily["low"].astype(float)
            closes[code] = daily["close"].astype(float)
            name_map[code] = name
    return (
        pd.DataFrame(opens).sort_index(),
        pd.DataFrame(lows).sort_index(),
        pd.DataFrame(closes).sort_index(),
        name_map,
    )


def _event_picks(
    dates: pd.DatetimeIndex,
    *,
    posts_path: Path,
    start: str,
    end: str,
    max_themes: int,
) -> dict[pd.Timestamp, list[str]]:
    """将每个发帖日映射至随后一个交易日的前一根信号日。

    以当天新帖构建主题池；周日会合并周六、周日帖子。没有帖子（或帖子不够
    前瞻）就不会生成 picks。
    """
    date_set = {pd.Timestamp(day).date() for day in dates}
    signals: dict[pd.Timestamp, list[str]] = {}
    for day in pd.date_range(start, end, freq="D"):
        if day.weekday() == 5:
            # 周末统一由周日聚合，避免周六和周日重复触发同一周一开仓事件。
            continue
        if day.date() not in date_set and day.weekday() < 5:
            # 交易日无新帖是主路径，跳过文件扫描。
            continue
        candidates = build_candidates(posts_path, asof=day.date(), lookback_days=0)
        if not candidates:
            continue
        theme_order: list[str] = []
        for row in candidates:
            if row["theme"] not in theme_order:
                theme_order.append(row["theme"])
        active_themes = set(theme_order[:max_themes])
        picks = [row["code"] for row in candidates if row["theme"] in active_themes]

        # 当天收盘后/周末发布，均保守地使用下一交易日开盘；
        # simulate() 要在交易日序列中用前一根信号日表达这一时点。
        prior = [d for d in dates if d.date() <= day.date()]
        if not prior:
            continue
        signal_day = pd.Timestamp(prior[-1])
        signals[signal_day] = picks
    return signals


def run_backtest(
    *,
    start: str = "20260101",
    end: str = "20260815",
    max_themes: int = 3,
    max_positions: int = 5,
    stop_pct: float = 0.025,
    initial_cash: float = 1_000_000.0,
    posts_path: str | Path = DEFAULT_POSTS,
) -> dict[str, Any]:
    """运行因子5事件回测并落盘结果。

    重要：这是主题代理池的历史研究。A股主题映射当前是静态配置，不能消除
    映射名单随时间变化产生的前视偏差，因此结果只能用于机制诊断。
    """
    from strategy.strategies.strategy7.portfolio import simulate_factor5_event_slots_f1_stop

    opens, lows, closes, name_map = _load_panel(start="20251201", end=end)
    common = opens.columns.intersection(lows.columns).intersection(closes.columns)
    opens, lows, closes = opens[common], lows[common], closes[common]
    dates = closes.index
    picks = _event_picks(
        dates,
        posts_path=Path(posts_path),
        start=start,
        end=end,
        max_themes=max_themes,
    )
    equity, trades, slots, stats = simulate_factor5_event_slots_f1_stop(
        opens=opens,
        lows=lows,
        closes=closes,
        picks={day: [code for code in codes if code in common] for day, codes in picks.items()},
        bt_start=pd.Timestamp(start),
        max_positions=int(max_positions),
        stop_pct=float(stop_pct),
        initial_cash=float(initial_cash),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"strategy7_factor5_slots_{start}_{end}_n{max_positions}"
    equity.to_csv(OUT_DIR / f"{stem}_equity.csv", index=False)
    trades.to_csv(OUT_DIR / f"{stem}_trades.csv", index=False)
    slots.to_csv(OUT_DIR / f"{stem}_slots.csv", index=False)
    event_rows = []
    for signal_day, codes in sorted(picks.items()):
        event_rows.append(
            {
                "signal_date": signal_day.date().isoformat(),
                "codes": ",".join(codes),
                "names": ",".join(name_map.get(code, code) for code in codes),
                "candidate_count": len(codes),
            }
        )
    pd.DataFrame(event_rows).to_csv(OUT_DIR / f"{stem}_events.csv", index=False)

    summary = {
        **{key: value for key, value in stats.items() if key != "picks"},
        "signal_event_count": len(event_rows),
        "no_event_days_may_replenish_from_last_pool": True,
        "execution": "post date -> next trading-day open; factor1 stop; daily empty-slot replenishment",
        "max_themes_per_event": max_themes,
        "max_positions": max_positions,
        "stop_pct": stop_pct,
        "posts_path": str(posts_path),
        "mapping_warning": "A-share theme proxy map is static and may contain look-ahead bias.",
        "output_stem": stem,
    }
    (OUT_DIR / f"{stem}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="因子5 Serenity 事件驱动主题回测")
    parser.add_argument("--start", default="20260101")
    parser.add_argument("--end", default="20260815")
    parser.add_argument("--max-themes", type=int, default=3)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--stop-pct", type=float, default=0.025)
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--posts", type=Path, default=DEFAULT_POSTS)
    args = parser.parse_args()
    print(
        json.dumps(
            run_backtest(
                start=args.start,
                end=args.end,
                max_themes=args.max_themes,
                max_positions=args.max_positions,
                stop_pct=args.stop_pct,
                initial_cash=args.initial_cash,
                posts_path=args.posts,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
