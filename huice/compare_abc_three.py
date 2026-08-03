"""三标的 A/B/C 策略对比：今日开盘 / 小阳前日开盘 / 小阳次日不买。"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import HANGTIANDIANZI, KAICHENG, XIEXINNENGKE, run_open_break

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent

VARIANTS = [
    {
        "key": "A",
        "label": "A今日开盘",
        "entry_ref": "today_open",
        "prev_entry_mode": "yin_or_small_yang",
        "suffix": "",
    },
    {
        "key": "B",
        "label": "B小阳前日开",
        "entry_ref": "prev_open_on_small_yang",
        "prev_entry_mode": "yin_or_small_yang",
        "suffix": "_prevOpen买点",
    },
    {
        "key": "C",
        "label": "C小阳次日不买",
        "entry_ref": "today_open",
        "prev_entry_mode": "yin_only",
        "suffix": "_仅阴后买",
    },
]

SYMBOLS = [
    (KAICHENG, "sh600552_1m_qfq.parquet"),
    (HANGTIANDIANZI, "sh600879_1m_qfq.parquet"),
    (XIEXINNENGKE, "sz002015_1m_qfq.parquet"),
]

METRIC_KEYS = [
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "win_rate",
    "closed_trade_count",
    "profit_factor",
    "calmar_ratio",
    "end_market_value",
]


def _get(m, k: str) -> float | None:
    if k not in m.index:
        return None
    return float(m.loc[k].iloc[0])


def run_one(base, cache: Path, variant: dict) -> dict[str, float | None]:
    report = ROOT / f"{base.symbol_name}{variant['suffix']}_report.html"
    cfg = replace(
        base,
        entry_ref=variant["entry_ref"],
        prev_entry_mode=variant["prev_entry_mode"],
        min1_cache=cache,
        report_path=report,
    )
    result, _ = run_open_break(cfg, show_report=False, verbose=False)
    out = {k: _get(result.metrics_df, k) for k in METRIC_KEYS}
    print(
        f"  {variant['key']} {base.symbol_name}: "
        f"收益={out['total_return_pct']:.2f}% "
        f"回撤={out['max_drawdown_pct']:.2f}% "
        f"夏普={out['sharpe_ratio']:.3f} "
        f"闭环={out['closed_trade_count']:.0f}"
    )
    return out


def _winner(vals: dict[str, float], *, higher_better: bool, is_dd: bool = False) -> str:
    items = [(k, float(v)) for k, v in vals.items() if v is not None]
    if not items:
        return "—"
    if is_dd:
        best = min(items, key=lambda x: abs(x[1]))
        tied = [k for k, v in items if abs(abs(v) - abs(best[1])) < 1e-9]
    elif higher_better:
        best = max(items, key=lambda x: x[1])
        tied = [k for k, v in items if abs(v - best[1]) < 1e-9]
    else:
        best = min(items, key=lambda x: x[1])
        tied = [k for k, v in items if abs(v - best[1]) < 1e-9]
    return "/".join(tied) if len(tied) > 1 else tied[0]


def main() -> None:
    all_rows: dict[str, dict[str, dict[str, float | None]]] = {}
    for base, cache_name in SYMBOLS:
        cache = ROOT / cache_name
        print("=" * 72)
        print(f"{base.symbol_name} ({base.em_symbol})")
        print("=" * 72)
        all_rows[base.symbol_name] = {}
        for v in VARIANTS:
            all_rows[base.symbol_name][v["key"]] = run_one(base, cache, v)

    rows = [
        ("累计收益%", "total_return_pct", True, False),
        ("最大回撤%", "max_drawdown_pct", False, True),
        ("夏普", "sharpe_ratio", True, False),
        ("胜率%", "win_rate", True, False),
        ("闭环", "closed_trade_count", None, False),
        ("盈亏比", "profit_factor", True, False),
        ("Calmar", "calmar_ratio", True, False),
        ("期末权益", "end_market_value", True, False),
    ]

    print("\n" + "=" * 72)
    print("三策略对比汇总（A今日开盘 / B小阳前日开盘算买点 / C小阳次日不买）")
    print("=" * 72)

    for name, data in all_rows.items():
        print(f"\n【{name}】")
        header = f"{'指标':<12}" + "".join(f"{v['label']:>14}" for v in VARIANTS) + f"{'更好':>10}"
        print(header)
        for label, key, hb, is_dd in rows:
            vals = {v["key"]: data[v["key"]].get(key) for v in VARIANTS}
            cells = "".join(
                f"{float(vals[v['key']]):>14.4f}" if vals[v["key"]] is not None else f"{'n/a':>14}"
                for v in VARIANTS
            )
            if hb is None:
                w = "—"
            else:
                w = _winner(vals, higher_better=bool(hb), is_dd=is_dd)
            print(f"{label:<12}{cells}{w:>10}")


if __name__ == "__main__":
    main()
