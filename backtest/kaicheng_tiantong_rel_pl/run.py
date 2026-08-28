"""凯盛科技 / 天通股份 · 策略1 三段测试（传统盈亏比口径）。

与 ``backtest/ai_s1_s11_periods.py`` 同一套三段划分与模拟逻辑；
FIT 网格择优 thr ∈ {2%, 2.5%, 3%}，按**传统盈亏比**（avg win / avg loss）排序。
另附历史固定阈值（凯盛 2.5%、天通 3.0%）对照。

  python backtest/kaicheng_tiantong_rel_pl/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[2]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

import backtest.ai_s1_s11_periods as s11  # noqa: E402
from strategy.config import KAICHENG, TIANTONG  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
CACHE_DIR = OUT_DIR / "cache"
OOS_END = "20260827"

STOCKS = [
    (KAICHENG, 0.025),
    (TIANTONG, 0.03),
]


def tune_thr_pl(daily: pd.DataFrame) -> tuple[float, dict[str, float]]:
    """FIT 段择优：超额>0 优先，再比传统盈亏比、夏普。"""
    best_thr = 0.025
    best: dict[str, float] | None = None
    best_key = (-1e18, -1e18, -1e18)

    for thr in s11.THR_GRID:
        m = s11.eval_s1(daily, s11.FIT_START, s11.FIT_END, thr)
        if int(m.get("n_bars") or 0) < s11.MIN_BARS:
            continue
        excess = float(m["excess"]) if m["excess"] == m["excess"] else -1e9
        pl = float(m["pl_ratio"]) if m.get("pl_ratio") == m.get("pl_ratio") else -1e9
        if pl == float("inf"):
            pl = 1e6
        sh = float(m["sharpe"]) if m["sharpe"] == m["sharpe"] else -1e9
        flag = 1.0 if excess > 0 else 0.0
        key = (flag, pl, excess, sh)
        if key > best_key:
            best_key = key
            best_thr = thr
            best = m
    return best_thr, best or s11.eval_s1(daily, s11.FIT_START, s11.FIT_END, best_thr)


def _ensure_cache(cfg, end: str) -> None:
    cache = CACHE_DIR / f"{cfg.symbol}_daily_qfq.parquet"
    fetch_daily(cfg.symbol, s11.FULL_START, end, cache_path=cache)


def _prefix_block(prefix: str, m: dict) -> dict:
    return {f"{prefix}_{k}": v for k, v in m.items()}


def run_one(cfg, pinned_thr: float) -> dict:
    symbol, name, code = cfg.symbol, cfg.symbol_name, cfg.em_symbol
    daily = s11.load_daily(symbol)
    if daily is None:
        raise RuntimeError(f"no cache for {symbol}")

    thr, fit_tune = tune_thr_pl(daily)
    val_tune = s11.eval_s1(daily, s11.VAL_START, s11.VAL_END, thr)
    oos_tune = s11.eval_s1(daily, s11.OOS_START, OOS_END, thr)
    full_tune = s11.eval_s1(daily, s11.FULL_START, OOS_END, thr)

    fit_pin = s11.eval_s1(daily, s11.FIT_START, s11.FIT_END, pinned_thr)
    val_pin = s11.eval_s1(daily, s11.VAL_START, s11.VAL_END, pinned_thr)
    oos_pin = s11.eval_s1(daily, s11.OOS_START, OOS_END, pinned_thr)
    full_pin = s11.eval_s1(daily, s11.FULL_START, OOS_END, pinned_thr)

    rec: dict = {
        "code": code,
        "name": name,
        "symbol": symbol,
        "pinned_thr": pinned_thr,
        "tuned_thr": thr,
    }
    for prefix, block in (
        ("fit_tune", fit_tune),
        ("val_tune", val_tune),
        ("oos_tune", oos_tune),
        ("full_tune", full_tune),
        ("fit_pin", fit_pin),
        ("val_pin", val_pin),
        ("oos_pin", oos_pin),
        ("full_pin", full_pin),
    ):
        rec.update(_prefix_block(prefix, block))

    for seg, start, end in (
        ("fit", s11.FIT_START, s11.FIT_END),
        ("val", s11.VAL_START, s11.VAL_END),
        ("oos", s11.OOS_START, OOS_END),
        ("full", s11.FULL_START, OOS_END),
    ):
        s11m = s11.eval_s11(daily, start, end, thr, symbol, name)
        for k, v in s11m.items():
            rec[f"s11_{seg}_{k}"] = v
    return rec


def _fmt(v: object, nd: int = 2, pct: bool = False) -> str:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"
    if x != x:
        return "-"
    if pct:
        return f"{x:.{nd}f}%"
    if x == float("inf"):
        return "inf"
    return f"{x:.{nd}f}"


def write_report(df: pd.DataFrame) -> None:
    lines = [
        "# 凯盛科技 / 天通股份 · 策略1 传统盈亏比测试",
        "",
        f"数据截至 {OOS_END}；FIT {s11.FIT_START}–{s11.FIT_END}，"
        f"VAL {s11.VAL_START}–{s11.VAL_END}，OOS {s11.OOS_START}–{OOS_END}。",
        "",
        "## 传统盈亏比口径",
        "- **盈亏比** = 盈利笔平均收益 ÷ |亏损笔平均收益|（avg win / avg loss，越大越好）",
        "- FIT 网格择优 thr∈{2%, 2.5%, 3%}，按超额>0 → 传统盈亏比 → 夏普排序",
        "",
        "## 网格择优阈值",
        "",
        "| 标的 | 择优阈值 | 段 | 策略收益 | 持股收益 | 超额 | 最大回撤 | 胜率 | 盈亏比 | 利润因子 | 笔数 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in df.iterrows():
        for seg, label in (
            ("fit_tune", "FIT"),
            ("val_tune", "VAL"),
            ("oos_tune", "OOS"),
            ("full_tune", "全段"),
        ):
            lines.append(
                f"| {r['name']} | {float(r['tuned_thr'])*100:.1f}% | {label} | "
                f"{_fmt(r[f'{seg}_ret'], pct=True)} | {_fmt(r[f'{seg}_bh_ret'], pct=True)} | "
                f"{_fmt(r[f'{seg}_excess'], pct=True)} | {_fmt(r[f'{seg}_mdd'], pct=True)} | "
                f"{_fmt(r[f'{seg}_win_rate'], pct=True)} | {_fmt(r[f'{seg}_pl_ratio'])} | "
                f"{_fmt(r[f'{seg}_profit_factor'])} | {int(r[f'{seg}_n_trades'])} |"
            )

    lines += [
        "",
        "## 历史固定阈值（凯盛2.5% / 天通3.0%）",
        "",
        "| 标的 | 固定阈值 | 段 | 超额 | 盈亏比 | 胜率 | 笔数 |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for _, r in df.iterrows():
        for seg, label in (
            ("fit_pin", "FIT"),
            ("val_pin", "VAL"),
            ("oos_pin", "OOS"),
            ("full_pin", "全段"),
        ):
            lines.append(
                f"| {r['name']} | {float(r['pinned_thr'])*100:.1f}% | {label} | "
                f"{_fmt(r[f'{seg}_excess'], pct=True)} | {_fmt(r[f'{seg}_pl_ratio'])} | "
                f"{_fmt(r[f'{seg}_win_rate'], pct=True)} | {int(r[f'{seg}_n_trades'])} |"
            )

    lines += [
        "",
        "## 策略11（笔归因，与择优阈值一致）",
        "",
        "| 标的 | 段 | S11盈亏比 | 胜率 | 笔数 | 因子1复利% |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, r in df.iterrows():
        for seg, label in (
            ("fit", "FIT"),
            ("val", "VAL"),
            ("oos", "OOS"),
            ("full", "全段"),
        ):
            lines.append(
                f"| {r['name']} | {label} | {_fmt(r[f's11_{seg}_pl_ratio'])} | "
                f"{_fmt(r[f's11_{seg}_win_rate'], pct=True)} | "
                f"{int(r[f's11_{seg}_n_trades'] or 0)} | "
                f"{_fmt(r[f's11_{seg}_compound_net_pct'], pct=True)} |"
            )

    lines += ["", "> 研究用途，不构成投资建议。"]
    (OUT_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    s11.CACHE_DIR = CACHE_DIR
    for cfg, _ in STOCKS:
        _ensure_cache(cfg, OOS_END)

    rows = [run_one(cfg, pin) for cfg, pin in STOCKS]
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "metrics.csv", index=False, encoding="utf-8-sig")
    write_report(df)

    print("=== OOS 摘要（传统盈亏比）===")
    for _, r in df.iterrows():
        print(
            f"{r['name']}: thr={float(r['tuned_thr'])*100:.1f}% "
            f"OOS超额={_fmt(r['oos_tune_excess'], pct=True)} "
            f"盈亏比={_fmt(r['oos_tune_pl_ratio'])} "
            f"胜率={_fmt(r['oos_tune_win_rate'], pct=True)}"
        )
    print(f"\nWrote {OUT_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
