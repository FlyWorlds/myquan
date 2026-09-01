"""策略1 ETF 选票 walk-forward：2023–2025 选参 → 2025–2026 验证 → 2026 至今回测。

口径（与 kczz_etf_589680 分析一致）：
  · 仅因子1（不开因子2）；强制 T+1（t0=False）
  · ETF 印花税 0；tick=0.001
  · 选参只看 IS 费用后夏普 + 超额；验证/回测段不参与选择

  python strategy/strategies/strategy1/run_etf_select.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

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
import akshare as ak  # noqa: E402
from strategy.etf_combo_momentum import DEFAULT_UNIVERSE as COMBO_UNIV  # noqa: E402
from strategy.industry_residual_momentum import (  # noqa: E402
    DEFAULT_COMMON_UNIVERSE,
    DEFAULT_UNIVERSE as INDUSTRY_UNIV,
)
from strategy.runner import apply_strategy_config  # noqa: E402
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402

OUT = Path(__file__).resolve().parent / "etf_select"
WARM_START = "20220101"
IS_START, IS_END = "2023-01-02", "2025-12-31"
VAL_START, VAL_END = "2025-01-02", "2026-12-31"
BT_START = "2026-01-02"
BT_END = pd.Timestamp.today().strftime("%Y-%m-%d")
CASH = 100_000.0
MIN_IS_BARS = 500  # 约 2 年交易日，避免 2025 上市票用短样本刷高 IS 夏普
TOP_N = 5

# 宽基 + 行业 + 商品/跨境代理；去重保序
_EXTRA: tuple[tuple[str, str], ...] = (
    ("sh510050", "上证50ETF"),
    ("sh589680", "科创综指ETF鹏华"),
    ("sz159949", "创业板50ETF"),
    ("sh588080", "科创板50ETF"),
    ("sh512000", "券商ETF"),
    ("sh512760", "芯片ETF"),
    ("sz159819", "人工智能ETF"),
    ("sh515790", "光伏ETF"),
    ("sh516160", "新能源ETF"),
)


def _etf_universe() -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for sym, name in (*COMBO_UNIV, *INDUSTRY_UNIV, *DEFAULT_COMMON_UNIVERSE, *_EXTRA):
        code = sym[2:]
        if code in seen:
            continue
        seen.add(code)
        rows.append((sym, code, name))
    return rows


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


def _stats_window(nav: pd.Series, bh: pd.Series, start: str, end: str) -> dict[str, float]:
    nav = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))]
    bh = bh.reindex(nav.index).ffill()
    if len(nav) < 5:
        return {
            "ret_pct": float("nan"),
            "excess_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "n_days": int(len(nav)),
        }
    m = window_metrics(nav, start=start, end=end)
    bh_m = window_metrics(bh, start=start, end=end)
    return {
        "ret_pct": m["ret_pct"],
        "excess_pct": m["ret_pct"] - bh_m["ret_pct"],
        "sharpe": m["sharpe"],
        "mdd_pct": m["mdd_pct"],
        "n_days": int(len(nav)),
    }


def _run_sym(
    cfg: BacktestConfig,
    daily: pd.DataFrame,
    label: str,
) -> tuple[dict[str, Any], Any]:
    r, d = run_open_break(cfg, show_report=False, verbose=False)
    nav = _nav_series(r)
    bh = _bh_nav(d)
    row = {
        "label": label,
        "entry_pct": float(cfg.resolved_entry_pct()),
        "stop_pct": float(cfg.resolved_stop_pct()),
        "prev_entry_mode": cfg.prev_entry_mode,
        "ban_double_yang": bool(cfg.ban_double_yang),
        "is": _stats_window(nav, bh, IS_START, IS_END),
        "val": _stats_window(nav, bh, VAL_START, VAL_END),
        "bt": _stats_window(nav, bh, BT_START, BT_END),
        "closed_trades": int(metric(r.metrics_df, "closed_trade_count")),
    }
    return row, r


def _run_asym(
    base: BacktestConfig,
    daily: pd.DataFrame,
    *,
    entry: float,
    stop: float,
    label: str,
    **cfg_kw: Any,
) -> tuple[dict[str, Any], Any]:
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
    row = {
        "label": label,
        "entry_pct": entry,
        "stop_pct": stop,
        "prev_entry_mode": c.prev_entry_mode,
        "ban_double_yang": bool(c.ban_double_yang),
        "is": _stats_window(nav, bh, IS_START, IS_END),
        "val": _stats_window(nav, bh, VAL_START, VAL_END),
        "bt": _stats_window(nav, bh, BT_START, BT_END),
        "closed_trades": int(metric(r.metrics_df, "closed_trade_count")),
    }
    return row, r


def _base_cfg(sym: str, code: str, name: str, start: str) -> BacktestConfig:
    cache = _DAILY_CACHE_DIR / f"{sym}_daily_qfq.parquet"
    return BacktestConfig(
        symbol=sym,
        symbol_name=name,
        em_symbol=code,
        threshold_pct=0.025,
        start_date=start,
        end_date=BT_END.replace("-", ""),
        initial_cash=CASH,
        stamp_tax_rate=0.0,
        tick=0.001,
        t0=False,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        daily_cache=cache,
    )


def _param_jobs(base: BacktestConfig, daily: pd.DataFrame) -> list[tuple[str, Callable[[], tuple]]]:
    jobs: list[tuple[str, Callable[[], tuple]]] = []
    for pct in (0.02, 0.025, 0.03):
        jobs.append(
            (
                f"sym±{pct*100:g}%",
                lambda p=pct: _run_sym(replace(base, threshold_pct=p), daily, f"sym±{p*100:g}%"),
            )
        )
    jobs.append(
        (
            "sym±2.5%仅阴",
            lambda: _run_sym(
                replace(base, threshold_pct=0.025, prev_entry_mode="yin_only"),
                daily,
                "sym±2.5%仅阴",
            ),
        )
    )
    jobs.append(
        (
            "sym±2.5%不限前日",
            lambda: _run_sym(
                replace(base, threshold_pct=0.025, prev_entry_mode="any"),
                daily,
                "sym±2.5%不限前日",
            ),
        )
    )
    for entry, stop, tag in (
        (0.02, 0.03, "买2/止3"),
        (0.025, 0.035, "买2.5/止3.5"),
        (0.03, 0.025, "买3/止2.5"),
        (0.02, 0.025, "买2/止2.5"),
    ):
        jobs.append(
            (
                tag,
                lambda e=entry, s=stop, t=tag: _run_asym(base, daily, entry=e, stop=s, label=t),
            )
        )
    return jobs


def _score_is(row: dict[str, Any]) -> float:
    is_m = row["is"]
    ex = float(is_m.get("excess_pct") or float("nan"))
    sh = float(is_m.get("sharpe") or float("nan"))
    if ex != ex or sh != sh:
        return -1e9
    if ex <= 0:
        return -1e6 + ex
    return 3.0 * sh + 2.0 * ex / 100.0


def _pick_best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=_score_is)


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


def _load_daily(sym: str, code: str) -> pd.DataFrame | None:
    try:
        df = _fetch_etf_sina(sym, WARM_START, BT_END.replace("-", ""))
    except Exception:
        return None
    if df is None or df.empty:
        return None
    dates = pd.to_datetime(df["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    is_start = pd.Timestamp(IS_START)
    is_end = pd.Timestamp(IS_END)
    is_mask = (dates >= is_start) & (dates <= is_end)
    if int(is_mask.sum()) < MIN_IS_BARS:
        return None
    list_date = dates.min()
    if list_date > pd.Timestamp(IS_START) + pd.Timedelta(days=30):
        return None
    return df


def _fmt_pct(v: float) -> str:
    if v != v:
        return "—"
    return f"{v:.2f}"


def _report_md(
    ranked: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    *,
    n_tested: int,
) -> str:
    lines = [
        "# 策略1 ETF 选票 walk-forward",
        "",
        "研究用途，不构成投资建议。",
        "",
        "## 协议",
        "",
        f"- 选参（IS）：{IS_START}～{IS_END}，按 IS 费用后夏普×3 + 超额×2 打分",
        f"- 验证：{VAL_START}～{VAL_END}（不参与选参）",
        f"- 回测：{BT_START}～{BT_END}（不参与选参）",
        "- 引擎：因子1 开盘突破/止损；ETF 强制 T+1；印花 0；tick=0.001",
        "",
        f"- 候选池：{n_tested} 只（上市/样本不足跳过 {len(skipped)} 只）",
        "",
        "## Top 选票（冻结 IS 最优参数）",
        "",
        "| 排名 | 代码 | 名称 | IS参数 | IS超额% | IS夏普 | 验证超额% | 验证夏普 | 2026+超额% | 2026+夏普 | IS闭环 |",
        "|-----:|------|------|--------|--------:|-------:|----------:|---------:|-----------:|----------:|-------:|",
    ]
    for i, r in enumerate(ranked[:TOP_N], 1):
        is_m, val_m, bt_m = r["is"], r["val"], r["bt"]
        lines.append(
            f"| {i} | {r['code']} | {r['name']} | {r['label']} | "
            f"{_fmt_pct(is_m['excess_pct'])} | {_fmt_pct(is_m['sharpe'])} | "
            f"{_fmt_pct(val_m['excess_pct'])} | {_fmt_pct(val_m['sharpe'])} | "
            f"{_fmt_pct(bt_m['excess_pct'])} | {_fmt_pct(bt_m['sharpe'])} | {r['closed_trades']} |"
        )
    if ranked:
        best = ranked[0]
        lines += [
            "",
            "## 推荐",
            "",
            f"**首选**：`{best['code']}` {best['name']} · 参数 `{best['label']}` "
            f"(买 {best['entry_pct']*100:g}% / 止 {best['stop_pct']*100:g}%)",
            "",
            f"- IS（{IS_START}～{IS_END}）：策略 {_fmt_pct(best['is']['ret_pct'])}%，"
            f"超额 {_fmt_pct(best['is']['excess_pct'])}%，夏普 {_fmt_pct(best['is']['sharpe'])}",
            f"- 验证（{VAL_START}～{VAL_END}）：超额 {_fmt_pct(best['val']['excess_pct'])}%，"
            f"夏普 {_fmt_pct(best['val']['sharpe'])}",
            f"- 2026至今：超额 {_fmt_pct(best['bt']['excess_pct'])}%，"
            f"夏普 {_fmt_pct(best['bt']['sharpe'])}",
        ]
    if skipped:
        lines += ["", "## 跳过标的", ""]
        for s in skipped[:20]:
            lines.append(f"- `{s['code']}` {s['name']}：{s['reason']}")
        if len(skipped) > 20:
            lines.append(f"- … 另有 {len(skipped) - 20} 只")
    lines += [
        "",
        "## 解读",
        "",
        "- 选参段与验证段在 2025 年有重叠；解读验证段时勿与 IS 混淆。",
        "- ETF 上市日晚于 IS 起点的标的样本偏短，排名靠后或已跳过。",
        "- 实盘需核对流动性、跟踪误差与申赎规则；本脚本不含因子2/13/16 组合层。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    universe = _etf_universe()
    all_rows: list[dict[str, Any]] = []
    param_detail: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    print(f"ETF universe {len(universe)} · IS {IS_START}~{IS_END} · VAL {VAL_START}~{VAL_END} · BT {BT_START}~{BT_END}")

    for sym, code, name in universe:
        daily = _load_daily(sym, code)
        if daily is None:
            skipped.append({"code": code, "name": name, "reason": "IS样本不足或上市晚于2023"})
            print(f"  skip {code} {name}")
            continue
        trade_start = pd.Timestamp(daily["date"].iloc[0]).strftime("%Y%m%d")
        base = _base_cfg(sym, code, name, trade_start)
        jobs = _param_jobs(base, daily)
        sym_rows: list[dict[str, Any]] = []
        for label, fn in jobs:
            try:
                row, _ = fn()
            except Exception as exc:
                row = {"label": label, "error": str(exc)}
            row.update({"symbol": sym, "code": code, "name": name})
            sym_rows.append(row)
            param_detail.append(row)
        viable = [r for r in sym_rows if "error" not in r and _score_is(r) > -1e8]
        if not viable:
            skipped.append({"code": code, "name": name, "reason": "全部参数组合失败或无正超额"})
            print(f"  skip {code} {name} (no viable params)")
            continue
        best = _pick_best(viable)
        all_rows.append(best)
        print(
            f"  ok {code} {name} -> {best['label']} "
            f"IS ex={best['is']['excess_pct']:.1f}% sh={best['is']['sharpe']:.2f}"
        )

    ranked = sorted(all_rows, key=_score_is, reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    summary = {
        "protocol": {
            "is": [IS_START, IS_END],
            "val": [VAL_START, VAL_END],
            "bt": [BT_START, BT_END],
        },
        "n_universe": len(universe),
        "n_tested": len(all_rows),
        "n_skipped": len(skipped),
        "top": ranked[:TOP_N],
        "skipped": skipped,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(param_detail).to_csv(OUT / "param_sweep_all.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ranked).to_csv(OUT / "etf_ranked.csv", index=False, encoding="utf-8-sig")
    (OUT / "report.md").write_text(
        _report_md(ranked, skipped, n_tested=len(universe)), encoding="utf-8"
    )
    print(f"\nWrote {OUT}/report.md · top={ranked[0]['code'] if ranked else 'none'}")


if __name__ == "__main__":
    main()
