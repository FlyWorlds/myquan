"""策略1 · 科创板 ETF 全阶段回测选参。

对 sh588/sh589 科创板股票指数类 ETF（排除债/创业/双创主题），
在**各票可用全历史**上扫因子1 参数并择优；选参与评估同区间（全阶段）。

  python strategy/strategies/strategy1/run_kcb_etf_select.py
  python strategy/strategies/strategy1/run_kcb_etf_select.py --min-bars 120
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import akshare as ak
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy import BacktestConfig, run_open_break  # noqa: E402
from strategy.backtest import OpenBreak3Strategy, metric  # noqa: E402
from strategy.base import run_backtest_pipeline  # noqa: E402
from strategy.config import _DAILY_CACHE_DIR  # noqa: E402
from strategy.data import AKSHARE_CALL_LOCK, _normalize_daily  # noqa: E402
from strategy.runner import apply_strategy_config  # noqa: E402
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402

OUT = Path(__file__).resolve().parent / "kcb_etf_select"
END = pd.Timestamp.today().strftime("%Y-%m-%d")
CASH = 100_000.0
MIN_BARS_DEFAULT = 60
TOP_N = 10

_EXCLUDE_NAME = ("债", "创业", "双创", "央企科创")


def _discover_kcb_etfs() -> list[tuple[str, str, str]]:
    with AKSHARE_CALL_LOCK:
        df = ak.fund_etf_category_sina(symbol="ETF基金")
    rows: list[tuple[str, str, str]] = []
    for _, r in df.iterrows():
        sym = str(r["代码"]).strip().lower()
        name = str(r["名称"]).strip()
        if any(x in name for x in _EXCLUDE_NAME):
            continue
        if not (sym.startswith("sh588") or sym.startswith("sh589")):
            continue
        code = sym[2:]
        rows.append((sym, code, name))
    return rows


def _fetch_etf_sina(sym: str, start: str, end: str) -> pd.DataFrame:
    cache = _DAILY_CACHE_DIR / f"{sym}_daily_qfq.parquet"
    if cache.exists():
        try:
            cached = pd.read_parquet(cache)
            if not cached.empty:
                return _normalize_daily(cached, symbol=sym, start=start, end=end)
        except Exception:
            pass
    with AKSHARE_CALL_LOCK:
        raw = ak.fund_etf_hist_sina(symbol=sym)
    df = _normalize_daily(raw, symbol=sym, start=start, end=end)
    if not df.empty:
        _DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)
    return df


def _nav_series(result: Any) -> pd.Series:
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return pd.Series(dtype=float)
    if isinstance(eq, pd.DataFrame):
        col = "equity" if "equity" in eq.columns else eq.columns[0]
        s = eq[col]
    else:
        s = eq
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return (
        pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize())
        .dropna()
        .sort_index()
    )


def _bh_nav(daily: pd.DataFrame) -> pd.Series:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    if d["date"].dt.tz is not None:
        d["date"] = d["date"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    close = d.set_index("date")["close"].astype(float).sort_index()
    close.index = close.index.normalize()
    return (close / close.iloc[0]) * CASH


def _full_stats(nav: pd.Series, bh: pd.Series) -> dict[str, Any]:
    if len(nav) < 5:
        return {
            "ret_pct": float("nan"),
            "excess_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "start": None,
            "end": None,
            "n_days": int(len(nav)),
        }
    m = window_metrics(nav)
    bh_m = window_metrics(bh.reindex(nav.index).ffill())
    return {
        "ret_pct": m["ret_pct"],
        "excess_pct": m["ret_pct"] - bh_m["ret_pct"],
        "sharpe": m["sharpe"],
        "mdd_pct": m["mdd_pct"],
        "start": m.get("start"),
        "end": m.get("end"),
        "n_days": int(len(nav)),
    }


def _base_cfg(sym: str, code: str, name: str, start: str) -> BacktestConfig:
    return BacktestConfig(
        symbol=sym,
        symbol_name=name,
        em_symbol=code,
        threshold_pct=0.025,
        start_date=start,
        end_date=END.replace("-", ""),
        initial_cash=CASH,
        stamp_tax_rate=0.0,
        tick=0.001,
        t0=False,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        daily_cache=_DAILY_CACHE_DIR / f"{sym}_daily_qfq.parquet",
    )


def _run_sym(cfg: BacktestConfig, label: str) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    r, d = run_open_break(cfg, show_report=False, verbose=False)
    nav = _nav_series(r)
    bh = _bh_nav(d)
    return (
        {
            "label": label,
            "entry_pct": float(cfg.resolved_entry_pct()),
            "stop_pct": float(cfg.resolved_stop_pct()),
            "prev_entry_mode": cfg.prev_entry_mode,
            "ban_double_yang": bool(cfg.ban_double_yang),
            "full": _full_stats(nav, bh),
            "closed_trades": int(metric(r.metrics_df, "closed_trade_count")),
            "win_rate": float(metric(r.metrics_df, "win_rate")),
        },
        r,
        d,
    )


def _run_asym(
    base: BacktestConfig,
    *,
    entry: float,
    stop: float,
    label: str,
    **cfg_kw: Any,
) -> tuple[dict[str, Any], Any, pd.DataFrame]:
    c = replace(base, threshold_pct=entry, **cfg_kw)

    def configure(strategy: OpenBreak3Strategy, params: Any) -> None:
        apply_strategy_config(strategy, params)
        strategy.entry_pct = entry
        strategy.stop_pct = stop
        strategy.prev_small_yang_pct = entry

    r, d = run_backtest_pipeline(
        params=c,
        strategy_cls=OpenBreak3Strategy,
        configure=configure,
        print_summary_fn=None,
        show_report=False,
        verbose=False,
    )
    nav = _nav_series(r)
    bh = _bh_nav(d)
    return (
        {
            "label": label,
            "entry_pct": entry,
            "stop_pct": stop,
            "prev_entry_mode": c.prev_entry_mode,
            "ban_double_yang": bool(c.ban_double_yang),
            "full": _full_stats(nav, bh),
            "closed_trades": int(metric(r.metrics_df, "closed_trade_count")),
            "win_rate": float(metric(r.metrics_df, "win_rate")),
        },
        r,
        d,
    )


def _param_jobs(base: BacktestConfig) -> list[tuple[str, Callable[[], tuple]]]:
    jobs: list[tuple[str, Callable[[], tuple]]] = []
    for pct in (0.02, 0.025, 0.03):
        jobs.append(
            (
                f"sym±{pct*100:g}%",
                lambda p=pct: _run_sym(replace(base, threshold_pct=p), f"sym±{p*100:g}%"),
            )
        )
    jobs.append(
        (
            "sym±2.5%仅阴",
            lambda: _run_sym(
                replace(base, threshold_pct=0.025, prev_entry_mode="yin_only"),
                "sym±2.5%仅阴",
            ),
        )
    )
    jobs.append(
        (
            "sym±2.5%不限前日",
            lambda: _run_sym(
                replace(base, threshold_pct=0.025, prev_entry_mode="any"),
                "sym±2.5%不限前日",
            ),
        )
    )
    jobs.append(
        (
            "sym±2.5%不禁双阳",
            lambda: _run_sym(
                replace(base, threshold_pct=0.025, ban_double_yang=False),
                "sym±2.5%不禁双阳",
            ),
        )
    )
    for entry, stop, tag in (
        (0.02, 0.03, "买2/止3"),
        (0.025, 0.035, "买2.5/止3.5"),
        (0.03, 0.025, "买3/止2.5"),
        (0.02, 0.025, "买2/止2.5"),
        (0.03, 0.04, "买3/止4"),
    ):
        jobs.append(
            (tag, lambda e=entry, s=stop, t=tag: _run_asym(base, entry=e, stop=s, label=t))
        )
    return jobs


def _score_full(row: dict[str, Any]) -> float:
    m = row["full"]
    ex = float(m.get("excess_pct") or float("nan"))
    sh = float(m.get("sharpe") or float("nan"))
    if ex != ex or sh != sh:
        return -1e9
    if ex <= 0:
        return -1e6 + ex
    return 3.0 * sh + 2.0 * ex / 100.0


def _fmt(v: float) -> str:
    return "—" if v != v else f"{v:.2f}"


def _report_md(ranked: list[dict[str, Any]], skipped: list[dict[str, str]], n_pool: int) -> str:
    lines = [
        "# 策略1 · 科创板 ETF 全阶段回测选参",
        "",
        "研究用途，不构成投资建议。",
        "",
        "## 协议",
        "",
        "- 宇宙：上交所 sh588/sh589 科创板股票指数类 ETF（排除科创债、科创创业、双创、央企科创）",
        "- **选参 = 评估**：各票自上市日至今日的**全可用历史**上扫因子1 参数，取全段得分最高者",
        "- 得分：全段超额>0 时，3×夏普 + 2×超额/100；否则置底",
        "- 引擎：因子1 开盘突破/止损；ETF 强制 T+1；印花 0；tick=0.001",
        "",
        f"- 候选 {n_pool} 只，有效 {len(ranked)} 只，跳过 {len(skipped)} 只",
        "",
        "## Top 选票（全阶段冻结最优参数）",
        "",
        "| 排名 | 代码 | 名称 | 区间 | 参数 | 全段收益% | 全段超额% | 夏普 | 回撤% | 闭环 | 胜率% |",
        "|-----:|------|------|------|------|----------:|----------:|-----:|------:|-----:|------:|",
    ]
    for i, r in enumerate(ranked[:TOP_N], 1):
        m = r["full"]
        span = f"{m.get('start','?')}~{m.get('end','?')}"
        lines.append(
            f"| {i} | {r['code']} | {r['name']} | {span} | {r['label']} | "
            f"{_fmt(m['ret_pct'])} | {_fmt(m['excess_pct'])} | {_fmt(m['sharpe'])} | "
            f"{_fmt(m['mdd_pct'])} | {r['closed_trades']} | {_fmt(r['win_rate'])} |"
        )
    if ranked:
        b = ranked[0]
        m = b["full"]
        lines += [
            "",
            "## 推荐",
            "",
            f"**首选**：`{b['code']}` {b['name']}",
            f"- 参数：`{b['label']}`（买 {b['entry_pct']*100:g}% / 止 {b['stop_pct']*100:g}%）",
            f"- 全段 {m.get('start')}～{m.get('end')}：收益 {_fmt(m['ret_pct'])}%，"
            f"超额 {_fmt(m['excess_pct'])}%，夏普 {_fmt(m['sharpe'])}，回撤 {_fmt(m['mdd_pct'])}%",
            "",
            "## 宽基对照（同协议内排名）",
            "",
        ]
        idx_names = ("科创50", "科创100", "科创200", "科创综指", "科创板50")
        for key in idx_names:
            hits = [r for r in ranked if key in r["name"]]
            if hits:
                h = hits[0]
                hm = h["full"]
                lines.append(
                    f"- {h['code']} {h['name']} · {h['label']} · "
                    f"超额 {_fmt(hm['excess_pct'])}% · 夏普 {_fmt(hm['sharpe'])}"
                )
    if skipped:
        lines += ["", "## 跳过", ""]
        for s in skipped[:15]:
            lines.append(f"- `{s['code']}` {s['name']}：{s['reason']}")
        if len(skipped) > 15:
            lines.append(f"- … 另有 {len(skipped) - 15} 只")
    lines += [
        "",
        "## 解读",
        "",
        "- 全阶段选参有样本内过拟合风险；新上市 ETF 交易次数少，排名波动大。",
        "- 同名指数多只 ETF 应优先看流动性（成交额），本脚本未做流动性过滤。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-bars", type=int, default=MIN_BARS_DEFAULT)
    args = ap.parse_args()
    min_bars = int(args.min_bars)

    OUT.mkdir(parents=True, exist_ok=True)
    universe = _discover_kcb_etfs()
    ranked: list[dict[str, Any]] = []
    param_all: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    print(f"科创板 ETF {len(universe)} 只 · 全阶段选参 · min_bars={min_bars}")

    for sym, code, name in universe:
        try:
            df = _fetch_etf_sina(sym, "20190101", END.replace("-", ""))
        except Exception as exc:
            skipped.append({"code": code, "name": name, "reason": f"拉取失败: {exc}"})
            continue
        if df is None or df.empty or len(df) < min_bars:
            skipped.append({"code": code, "name": name, "reason": f"样本<{min_bars}日"})
            continue
        trade_start = pd.Timestamp(df["date"].iloc[0]).strftime("%Y%m%d")
        base = _base_cfg(sym, code, name, trade_start)
        sym_rows: list[dict[str, Any]] = []
        for label, fn in _param_jobs(base):
            try:
                row, _, _ = fn()
            except Exception as exc:
                row = {"label": label, "error": str(exc)}
            row.update({"symbol": sym, "code": code, "name": name})
            sym_rows.append(row)
            param_all.append(row)
        viable = [r for r in sym_rows if "error" not in r and _score_full(r) > -1e8]
        if not viable:
            skipped.append({"code": code, "name": name, "reason": "无正超额参数组合"})
            continue
        best = max(viable, key=_score_full)
        ranked.append(best)
        m = best["full"]
        print(
            f"  {code} {name[:12]:12s} -> {best['label']:14s} "
            f"ex={m['excess_pct']:+.1f}% sh={m['sharpe']:.2f} n={best['closed_trades']}"
        )

    ranked.sort(key=_score_full, reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    summary = {
        "mode": "full_period",
        "end": END,
        "min_bars": min_bars,
        "n_pool": len(universe),
        "n_ranked": len(ranked),
        "n_skipped": len(skipped),
        "top": ranked[:TOP_N],
        "skipped": skipped,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(param_all).to_csv(OUT / "param_sweep_all.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ranked).to_csv(OUT / "kcb_etf_ranked.csv", index=False, encoding="utf-8-sig")
    (OUT / "report.md").write_text(_report_md(ranked, skipped, len(universe)), encoding="utf-8")
    print(f"\nWrote {OUT}/report.md · top={ranked[0]['code'] if ranked else 'none'}")


if __name__ == "__main__":
    main()
