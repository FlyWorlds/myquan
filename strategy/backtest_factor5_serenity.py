"""策略三回测：因子5事件建仓、因子1止损、五槽位每日补仓。"""

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


def _zz500_1000_mainboard_codes() -> set[str]:
    """加载中证500/1000主板并集，并额外剔除名称含 ST 的成分。"""
    from backtest.zz1000_momentum_select import load_zz500_1000_mainboard

    universe = load_zz500_1000_mainboard()
    names = universe["name"].astype(str).str.upper()
    return set(universe.loc[~names.str.contains("ST", regex=False), "code"].astype(str).str.zfill(6))


def _theme_by_code() -> dict[str, str]:
    return {
        code: theme
        for theme, meta in THEME_MAP.items()
        for code in meta["symbols"]
    }


def _load_panel(
    *,
    start: str,
    end: str,
    eligible_codes: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """读取/补齐主题代理池行情，返回开盘、最低、收盘宽表。"""
    opens: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    name_map: dict[str, str] = {}
    for meta in THEME_MAP.values():
        for code, name in meta["symbols"].items():
            if code not in eligible_codes:
                continue
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
    eligible_codes: set[str],
    max_per_theme: int,
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
        candidates = build_candidates(
            posts_path,
            asof=day.date(),
            lookback_days=0,
            eligible_codes=eligible_codes,
            max_per_theme=max_per_theme,
        )
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
    use_factor1_stop: bool = False,
    hold_days: int | None = 5,
    max_per_theme: int = 1,
    initial_cash: float = 1_000_000.0,
    posts_path: str | Path = DEFAULT_POSTS,
) -> dict[str, Any]:
    """运行因子5事件回测并落盘结果。

    重要：这是主题代理池的历史研究。A股主题映射当前是静态配置，不能消除
    映射名单随时间变化产生的前视偏差，因此结果只能用于机制诊断。
    """
    from strategy.strategies.strategy3.portfolio import simulate_factor5_event_slots_f1_stop

    eligible_codes = _zz500_1000_mainboard_codes()
    warm_start = (pd.Timestamp(start) - pd.Timedelta(days=35)).strftime("%Y%m%d")
    opens, lows, closes, name_map = _load_panel(
        start=warm_start,
        end=end,
        eligible_codes=eligible_codes,
    )
    common = opens.columns.intersection(lows.columns).intersection(closes.columns)
    opens, lows, closes = opens[common], lows[common], closes[common]
    dates = closes.index
    picks = _event_picks(
        dates,
        posts_path=Path(posts_path),
        start=start,
        end=end,
        max_themes=max_themes,
        eligible_codes=eligible_codes,
        max_per_theme=max_per_theme,
    )
    equity, trades, slots, stats = simulate_factor5_event_slots_f1_stop(
        opens=opens,
        lows=lows,
        closes=closes,
        picks={day: [code for code in codes if code in common] for day, codes in picks.items()},
        bt_start=pd.Timestamp(start),
        max_positions=int(max_positions),
        stop_pct=float(stop_pct),
        use_factor1_stop=bool(use_factor1_stop),
        hold_days=hold_days,
        code_themes=_theme_by_code(),
        initial_cash=float(initial_cash),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stop_tag = "f1" if use_factor1_stop else "nof1"
    hold_tag = f"h{hold_days}" if hold_days is not None else "hNone"
    stem = (
        f"strategy7_factor5_slots_{start}_{end}_n{max_positions}_"
        f"{stop_tag}_{hold_tag}_pt{max_per_theme}"
    )
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
        "execution": (
            "post date -> next trading-day open; "
            f"{'factor1 stop' if use_factor1_stop else 'no factor1 stop'}; "
            f"{'fixed hold exit' if hold_days is not None else 'no fixed hold exit'}; "
            "daily empty-slot replenishment"
        ),
        "max_themes_per_event": max_themes,
        "max_positions": max_positions,
        "stop_pct": stop_pct,
        "use_factor1_stop": use_factor1_stop,
        "hold_days": hold_days,
        "max_per_theme": max_per_theme,
        "event_rebalance": "same-theme replaces prior holding; new theme replaces oldest holding when full",
        "universe": "CSI500 + CSI1000 current mainboard constituents, excluding ST names",
        "eligible_universe_size": len(eligible_codes),
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
    parser.add_argument("--use-factor1-stop", action="store_true")
    parser.add_argument("--hold-days", type=int, default=5)
    parser.add_argument("--max-per-theme", type=int, default=1)
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
                use_factor1_stop=args.use_factor1_stop,
                hold_days=args.hold_days,
                max_per_theme=args.max_per_theme,
                initial_cash=args.initial_cash,
                posts_path=args.posts,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
