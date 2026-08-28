"""策略1 + 策略11 联合选股：笔盈亏比过滤 + 周频价格选股，样本内调参，2025 至今验证。

策略11：在样本内窗口上计算因子1费用后笔盈亏比，过滤标的池。
策略1：周频价格 composite / near_high TopK，下一周允许因子1开仓。

产物目录：optimize_tests/s1_s11_select/

  python strategy/strategies/strategy1/optimize_tests/run_s1_s11_select.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from holdingStocks.watch_config import (  # noqa: E402
    WATCHLIST,
    limit_down_pct_of,
    sina_of,
)
from strategy import BacktestConfig  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.bi_pl_ratio import analyze_bi_pl_ratio  # noqa: E402
from strategy.costs import stamp_tax_for_code  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.runner import run_open_break_backtest  # noqa: E402
from strategy.s1_price_select import panel_price_factors, weekly_topk_allowed  # noqa: E402

OUT = Path(__file__).resolve().parent / "s1_s11_select"
DATA_CACHE = _MYQUAN / "data_cache"
IS_START = pd.Timestamp("2020-01-01")
IS_END = pd.Timestamp("2024-12-31")
VAL_START = pd.Timestamp("2025-01-01")
END = "20260827"
CASH = 100_000.0
PINNED = {"sh600552", "sh600330"}

ENTRY_PCTS = (0.02, 0.025, 0.03)
PL_RATIO_MIN_GRID = (0.8, 1.0, 1.2, 1.5, 2.0)
MIN_TRADES_GRID = (3, 5)
TOP_K_GRID = (3, 5)
VALUE_COLS = ("px_composite", "px_near_high")


@dataclass(frozen=True)
class StockMeta:
    symbol: str
    code: str
    name: str
    entry_pct: float
    stop_pct: float
    tick: float
    t0: bool
    limit_down_pct: float
    stamp_tax_rate: float


def watch_universe() -> list[StockMeta]:
    rows: list[StockMeta] = []
    seen: set[str] = set()
    for item in list(WATCHLIST):
        code = str(item["code"]).zfill(6)
        sym = sina_of(code)
        if sym in seen:
            continue
        seen.add(sym)
        ep = float(item.get("entry_pct") or item.get("pct") or DEFAULT_PCT)
        sp = float(item.get("stop_pct") or item.get("pct") or DEFAULT_PCT)
        rows.append(
            StockMeta(
                symbol=sym,
                code=code,
                name=str(item["name"]),
                entry_pct=ep,
                stop_pct=sp,
                tick=float(item.get("tick") or 0.01),
                t0=bool(item.get("t0", False)),
                limit_down_pct=float(item.get("limit_down_pct") or limit_down_pct_of(code)),
                stamp_tax_rate=stamp_tax_for_code(code),
            )
        )
    return rows


def load_or_fetch_daily(meta: StockMeta) -> pd.DataFrame | None:
    cache = DATA_CACHE / f"{meta.symbol}_daily_qfq.parquet"
    try:
        df = fetch_daily(
            meta.symbol,
            "20200101",
            END,
            cache_path=cache,
            force_refresh=not cache.exists(),
        )
    except Exception:
        return None
    if df is None or df.empty or len(df) < 120:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
    else:
        df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["symbol"] = meta.symbol
    return df.reset_index(drop=True)


def _tz_ts(ts: pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("Asia/Shanghai")
    return t.tz_convert("Asia/Shanghai")


def slice_daily(daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    start_ts = _tz_ts(start)
    end_ts = _tz_ts(end) + pd.Timedelta(hours=15)
    mask = (d["date"] >= start_ts) & (d["date"] <= end_ts)
    return d.loc[mask].reset_index(drop=True)


def _nav_series(result) -> pd.Series:
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
    return pd.Series(
        pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize()
    ).dropna().sort_index()


def run_one_backtest(
    meta: StockMeta,
    daily: pd.DataFrame,
    *,
    entry_pct: float,
    allowed: dict[str, bool] | None = None,
) -> pd.Series:
    start = pd.Timestamp(daily["date"].iloc[0]).strftime("%Y%m%d")
    end = pd.Timestamp(daily["date"].iloc[-1]).strftime("%Y%m%d")
    cfg = BacktestConfig(
        symbol=meta.symbol,
        symbol_name=meta.name,
        em_symbol=meta.code,
        threshold_pct=float(entry_pct),
        entry_pct=float(entry_pct),
        stop_pct=float(entry_pct),
        start_date=start,
        end_date=end,
        initial_cash=CASH,
        tick=float(meta.tick),
        t0=bool(meta.t0),
        limit_down_pct=float(meta.limit_down_pct),
        stamp_tax_rate=float(meta.stamp_tax_rate),
        energy_allowed_by_date=dict(allowed or {}),
    )
    result = run_open_break_backtest(cfg, daily)
    return _nav_series(result)


def window_metrics(eq: pd.Series, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict:
    s = eq.dropna().astype(float).sort_index()
    if start is not None:
        s = s[s.index >= pd.Timestamp(start).tz_localize(None)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end).tz_localize(None)]
    if len(s) < 5:
        return {
            "ret_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "ann_pct": float("nan"),
            "n_days": int(len(s)),
        }
    tot = float(s.iloc[-1] / s.iloc[0] - 1.0)
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    rets = s.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    dd = 1.0 - s / s.cummax()
    return {
        "ret_pct": tot * 100.0,
        "sharpe": sharpe,
        "mdd_pct": float(dd.max()) * 100.0,
        "ann_pct": ann * 100.0,
        "n_days": int(len(s)),
    }


def active_nav(
    navs: dict[str, pd.Series],
    allowed: dict[str, dict[str, bool]] | None,
    *,
    always: set[str] | None = None,
) -> pd.Series:
    df = pd.concat(navs, axis=1).sort_index().ffill()
    rets = df.pct_change()
    always_set = {str(x) for x in (always or set())}
    out: list[float] = []
    for ts, row in rets.iterrows():
        key = pd.Timestamp(ts).strftime("%Y-%m-%d")
        names: list[str] = []
        if allowed is None:
            names = [c for c in rets.columns if pd.notna(row.get(c))]
        else:
            for c in rets.columns:
                if c in always_set or bool((allowed.get(c) or {}).get(key, False)):
                    if pd.notna(row.get(c)):
                        names.append(c)
        out.append(float(row[names].mean()) if names else 0.0)
    nav = (1.0 + pd.Series(out, index=rets.index)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def bi_pl_on_window(
    daily: pd.DataFrame,
    meta: StockMeta,
    *,
    entry_pct: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    sub = slice_daily(daily, start, end)
    if len(sub) < 80:
        return {"pl_ratio": None, "n_trades": 0, "compound_pct": None}
    try:
        res = analyze_bi_pl_ratio(
            sub,
            symbol=meta.symbol,
            symbol_name=meta.name,
            entry_pct=float(entry_pct),
        )
        s = res.summary
        return {
            "pl_ratio": s.get("pl_ratio"),
            "n_trades": int(s.get("n_trades") or 0),
            "compound_pct": s.get("factor1_compound_net_pct"),
            "win_rate": s.get("win_rate_net"),
        }
    except Exception:
        return {"pl_ratio": None, "n_trades": 0, "compound_pct": None}


def filter_symbols(
    bi_stats: dict[str, dict],
    *,
    pl_ratio_min: float,
    min_trades: int,
) -> set[str]:
    ok: set[str] = set()
    for sym, st in bi_stats.items():
        pl = st.get("pl_ratio")
        n = int(st.get("n_trades") or 0)
        if pl is None or n < min_trades:
            continue
        if float(pl) >= pl_ratio_min:
            ok.add(sym)
    return ok


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metas = {m.symbol: m for m in watch_universe()}
    dailies: dict[str, pd.DataFrame] = {}
    for sym, meta in metas.items():
        daily = load_or_fetch_daily(meta)
        if daily is not None:
            dailies[sym] = daily
    metas = {k: v for k, v in metas.items() if k in dailies}
    print(f"universe loaded: {len(dailies)}")

    # --- 策略11：样本内笔盈亏比（2020-2024）---
    bi_rows: list[dict] = []
    bi_by_pct: dict[float, dict[str, dict]] = {}
    for ep in ENTRY_PCTS:
        bi_by_pct[ep] = {}
        for sym, meta in metas.items():
            st = bi_pl_on_window(
                dailies[sym],
                meta,
                entry_pct=ep,
                start=IS_START,
                end=IS_END,
            )
            bi_by_pct[ep][sym] = st
            bi_rows.append(
                {
                    "symbol": sym,
                    "name": meta.name,
                    "entry_pct": ep,
                    **st,
                }
            )
    bi_df = pd.DataFrame(bi_rows)
    bi_df.to_csv(OUT / "bi_pl_is_stats.csv", index=False)

    # --- 策略1：全区间回测净值（按 entry_pct）---
    nav_by_pct: dict[float, dict[str, pd.Series]] = {}
    for ep in ENTRY_PCTS:
        nav_by_pct[ep] = {}
        for sym, meta in metas.items():
            nav_by_pct[ep][sym] = run_one_backtest(meta, dailies[sym], entry_pct=ep)

    panel = panel_price_factors(dailies)

    # --- 样本内网格 ---
    trial_rows: list[dict] = []
    for ep, pl_min, min_tr, top_k, val_col in product(
        ENTRY_PCTS, PL_RATIO_MIN_GRID, MIN_TRADES_GRID, TOP_K_GRID, VALUE_COLS
    ):
        eligible = filter_symbols(
            bi_by_pct[ep],
            pl_ratio_min=pl_min,
            min_trades=min_tr,
        )
        if not eligible:
            continue
        sub_panel = panel[panel["symbol"].isin(eligible)].copy()
        if sub_panel.empty:
            continue
        allowed = weekly_topk_allowed(
            sub_panel,
            value_col=val_col,
            k=top_k,
            always=PINNED,
        )
        navs = {s: nav_by_pct[ep][s] for s in eligible if s in nav_by_pct[ep]}
        port = active_nav(navs, allowed, always=PINNED)
        is_m = window_metrics(port, IS_START, IS_END)
        trial_rows.append(
            {
                "entry_pct": ep,
                "pl_ratio_min": pl_min,
                "min_trades": min_tr,
                "top_k": top_k,
                "value_col": val_col,
                "n_eligible": len(eligible),
                "is_ret_pct": is_m["ret_pct"],
                "is_sharpe": is_m["sharpe"],
                "is_mdd_pct": is_m["mdd_pct"],
                "is_ann_pct": is_m["ann_pct"],
            }
        )

    trials = pd.DataFrame(trial_rows)
    trials = trials.sort_values("is_sharpe", ascending=False, na_position="last")
    trials.to_csv(OUT / "tune_trials_is.csv", index=False)

    if trials.empty:
        print("no valid trials")
        return

    best = trials.iloc[0]
    best_ep = float(best["entry_pct"])
    best_pl = float(best["pl_ratio_min"])
    best_min_tr = int(best["min_trades"])
    best_k = int(best["top_k"])
    best_col = str(best["value_col"])
    print("best IS:", best.to_dict())

    # --- 验证：用 2020-2024 笔盈亏比过滤，交易 2025 至今 ---
    val_filter_end = IS_END
    bi_val: dict[str, dict] = {}
    for sym, meta in metas.items():
        bi_val[sym] = bi_pl_on_window(
            dailies[sym],
            meta,
            entry_pct=best_ep,
            start=IS_START,
            end=val_filter_end,
        )
    eligible_val = filter_symbols(
        bi_val,
        pl_ratio_min=best_pl,
        min_trades=best_min_tr,
    )
    sub_panel_val = panel[panel["symbol"].isin(eligible_val)].copy()
    allowed_val = weekly_topk_allowed(
        sub_panel_val,
        value_col=best_col,
        k=best_k,
        always=PINNED,
    )
    navs_val = {s: nav_by_pct[best_ep][s] for s in eligible_val}
    port_full = active_nav(navs_val, allowed_val, always=PINNED)
    val_m = window_metrics(port_full, VAL_START, None)
    is_m_best = window_metrics(port_full, IS_START, IS_END)

    # 分年
    yearly_rows: list[dict] = []
    for year in range(2020, 2027):
        y_start = pd.Timestamp(f"{year}-01-01")
        y_end = pd.Timestamp(f"{year}-12-31")
        ym = window_metrics(port_full, y_start, y_end)
        yearly_rows.append({"year": year, **ym})
    yearly_df = pd.DataFrame(yearly_rows)
    yearly_df.to_csv(OUT / "yearly_nav.csv", index=False)

    eligible_list = sorted(eligible_val)
    picks_rows = []
    for sym in eligible_list:
        st = bi_val[sym]
        picks_rows.append(
            {
                "symbol": sym,
                "name": metas[sym].name,
                "pl_ratio_is": st.get("pl_ratio"),
                "n_trades_is": st.get("n_trades"),
                "compound_pct_is": st.get("compound_pct"),
            }
        )
    picks_df = pd.DataFrame(picks_rows).sort_values("pl_ratio_is", ascending=False)
    picks_df.to_csv(OUT / "eligible_symbols_2025.csv", index=False)

    port_full.to_csv(OUT / "portfolio_nav.csv", header=["nav"])

    manifest = {
        "is_window": f"{IS_START.date()}~{IS_END.date()}",
        "val_window": f"{VAL_START.date()}~{END}",
        "select_metric": "IS portfolio Sharpe (strategy1 gates + s11 pl_ratio filter)",
        "best_params": {
            "entry_pct": best_ep,
            "pl_ratio_min": best_pl,
            "min_trades": best_min_tr,
            "top_k": best_k,
            "value_col": best_col,
        },
        "is_metrics": is_m_best,
        "val_metrics": val_m,
        "n_eligible_val": len(eligible_val),
        "eligible_symbols": eligible_list,
        "fee_note": "strategy1 round-trip incl stamp; portfolio equal-weight weekly gate",
        "disclaimer": "研究回测，不构成投资建议",
    }
    (OUT / "00_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = f"""# 策略1 + 策略11 联合选股 · 调参与 2025 至今验证

研究回测，不构成投资建议。

## 方法
- **策略11**：在 {IS_START.date()}～{IS_END.date()} 计算因子1费用后**笔盈亏比**，过滤标的池（`pl_ratio ≥ 阈值` 且闭环笔数 ≥ `min_trades`）。
- **策略1**：周频 `{best_col}` Top{best_k}（置顶凯盛+天通），下一周允许因子1开仓；阈值 `entry_pct={best_ep}`。
- **选参**：仅样本内夏普最大化；2025 起为样本外验证。

## 样本内最优参数
| 参数 | 值 |
|------|-----|
| entry_pct | {best_ep} |
| pl_ratio_min | {best_pl} |
| min_trades | {best_min_tr} |
| top_k | {best_k} |
| value_col | {best_col} |
| 合格池数量 | {int(best['n_eligible'])} |

样本内：累计 {is_m_best['ret_pct']:.1f}%，夏普 {is_m_best['sharpe']:.2f}，回撤 {is_m_best['mdd_pct']:.1f}%

## 2025 至今验证（OOS）
- 过滤仍基于 2020-2024 笔盈亏比（无前视）
- 合格标的 {len(eligible_val)} 只：{", ".join(eligible_list[:8])}{"…" if len(eligible_list)>8 else ""}
- 累计收益 **{val_m['ret_pct']:.1f}%**
- 夏普 **{val_m['sharpe']:.2f}**
- 最大回撤 **{val_m['mdd_pct']:.1f}%**
- 年化 **{val_m['ann_pct']:.1f}%**

## 分年组合净值
```
{yearly_df.to_string(index=False)}
```

## 当前合格池（笔盈亏比，IS 窗口）
```
{picks_df.head(15).to_string(index=False)}
```

## 数据说明
- 标的：watch_config WATCHLIST（{len(dailies)} 只载入）
- 日线：AkShare 前复权，缓存 data_cache/
- 费用：strategy1 同口径（佣金+杂费+印花+滑点）

免责声明：本报告仅作数据整理与规则化回测，不构成投资建议。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
