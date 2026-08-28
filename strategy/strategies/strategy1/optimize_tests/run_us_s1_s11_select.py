"""美股联动 → 策略11 笔盈亏比 → 策略1 周频选股 · 调参 + 2025 至今验证。

流程：
  1. 美股主题 ETF 日收益（隔夜信号）过滤观察池
  2. 策略11：2020-2024 笔盈亏比 + 闭环笔数
  3. 策略1：周频价格 TopK + 因子1 开仓（样本内调参夏普）

产物：optimize_tests/us_s1_s11_select/

  python strategy/strategies/strategy1/optimize_tests/run_us_s1_s11_select.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from itertools import product
from pathlib import Path

import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.us_a_factor import (  # noqa: E402
    panel_us_a_linkage,
    weekly_allowed_from_factor,
    factor14_signal,
)
from strategy.us_a_linkage import fetch_us_theme_returns, merge_allowed, WATCHLIST_US_THEMES  # noqa: E402
from strategy.strategies.strategy1.optimize_tests.run_s1_s11_select import (  # noqa: E402
    CASH,
    DATA_CACHE,
    END,
    IS_END,
    IS_START,
    PINNED,
    VAL_START,
    active_nav,
    bi_pl_on_window,
    filter_symbols,
    load_or_fetch_daily,
    run_one_backtest,
    slice_daily,
    watch_universe,
    window_metrics,
)
from strategy.s1_price_select import panel_price_factors, weekly_topk_allowed  # noqa: E402

OUT = Path(__file__).resolve().parent / "us_s1_s11_select"

# 策略1/11 阈值网格（与 run_s1_s11_select 一致）
ENTRY_PCTS = (0.02, 0.025, 0.03)
PL_RATIO_MIN_GRID = (1.0, 1.5, 2.0)
MIN_TRADES_GRID = (3, 5)
TOP_K_GRID = (3, 5)
VALUE_COLS = ("px_composite", "px_near_high")

# 美股联动网格（样本内）
US_TOP_N_GRID = (1, 2, 3)
US_MIN_RET_GRID = (0.0, 0.003, 0.005)


def _fmt_end(end: str) -> str:
    s = str(end).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


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

    us_rets = fetch_us_theme_returns("2019-12-01", _fmt_end(END))
    us_rets.to_csv(OUT / "us_theme_daily_returns.csv")
    snap = factor14_signal(theme_returns=us_rets)
    (OUT / "latest_us_snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    panel_f14 = panel_us_a_linkage(dailies, theme_returns=us_rets)
    panel_f14.to_csv(OUT / "factor14_panel.csv", index=False)

    all_dates = sorted(
        {
            pd.Timestamp(t).tz_localize(None).normalize()
            for d in dailies.values()
            for t in pd.to_datetime(d["date"])
        }
    )

    # 策略11：样本内笔盈亏比
    bi_rows: list[dict] = []
    bi_by_pct: dict[float, dict[str, dict]] = {}
    for ep in ENTRY_PCTS:
        bi_by_pct[ep] = {}
        for sym, meta in metas.items():
            st = bi_pl_on_window(
                dailies[sym], meta, entry_pct=ep, start=IS_START, end=IS_END
            )
            bi_by_pct[ep][sym] = st
            bi_rows.append({"symbol": sym, "name": meta.name, "entry_pct": ep, **st})
    pd.DataFrame(bi_rows).to_csv(OUT / "bi_pl_is_stats.csv", index=False)

    nav_by_pct: dict[float, dict[str, pd.Series]] = {}
    for ep in ENTRY_PCTS:
        nav_by_pct[ep] = {}
        for sym, meta in metas.items():
            nav_by_pct[ep][sym] = run_one_backtest(meta, dailies[sym], entry_pct=ep)

    panel = panel_price_factors(dailies)

    trial_rows: list[dict] = []
    for ep, pl_min, min_tr, top_k, val_col, us_top, us_min in product(
        ENTRY_PCTS,
        PL_RATIO_MIN_GRID,
        MIN_TRADES_GRID,
        TOP_K_GRID,
        VALUE_COLS,
        US_TOP_N_GRID,
        US_MIN_RET_GRID,
    ):
        f14_params = {
            "top_n_themes": int(us_top),
            "min_theme_ret": float(us_min),
            "use_top_n": True,
            "use_min_ret": us_min > 0,
        }

        s11_eligible = filter_symbols(
            bi_by_pct[ep], pl_ratio_min=pl_min, min_trades=min_tr
        )
        if not s11_eligible:
            continue

        us_allowed_tmp = weekly_allowed_from_factor(
            panel_f14, theme_returns=us_rets, params=f14_params
        )
        us_syms = {s for s, d in us_allowed_tmp.items() if any(d.values())}
        linkage_eligible = s11_eligible & us_syms
        if not linkage_eligible:
            continue

        sub_panel = panel[panel["symbol"].isin(linkage_eligible)].copy()
        if sub_panel.empty:
            continue

        s1_allowed = weekly_topk_allowed(
            sub_panel, value_col=val_col, k=top_k, always=PINNED
        )
        us_allowed = weekly_allowed_from_factor(
            panel_f14[panel_f14["symbol"].isin(linkage_eligible)],
            theme_returns=us_rets,
            params=f14_params,
            always=PINNED,
        )
        merged = merge_allowed(s1_allowed, us_allowed)

        navs = {s: nav_by_pct[ep][s] for s in linkage_eligible if s in nav_by_pct[ep]}
        port = active_nav(navs, merged, always=PINNED)
        is_m = window_metrics(port, IS_START, IS_END)

        trial_rows.append(
            {
                "entry_pct": ep,
                "pl_ratio_min": pl_min,
                "min_trades": min_tr,
                "top_k": top_k,
                "value_col": val_col,
                "us_top_n": us_top,
                "us_min_ret": us_min,
                "n_s11": len(s11_eligible),
                "n_linkage": len(linkage_eligible),
                "is_ret_pct": is_m["ret_pct"],
                "is_sharpe": is_m["sharpe"],
                "is_mdd_pct": is_m["mdd_pct"],
            }
        )

    trials = pd.DataFrame(trial_rows).sort_values("is_sharpe", ascending=False, na_position="last")
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
    best_us_top = int(best["us_top_n"])
    best_us_min = float(best["us_min_ret"])
    print("best IS:", best.to_dict())

    f14_best = {
        "top_n_themes": best_us_top,
        "min_theme_ret": best_us_min,
        "use_top_n": True,
        "use_min_ret": best_us_min > 0,
    }

    bi_val: dict[str, dict] = {}
    for sym, meta in metas.items():
        bi_val[sym] = bi_pl_on_window(
            dailies[sym], meta, entry_pct=best_ep, start=IS_START, end=IS_END
        )
    s11_val = filter_symbols(bi_val, pl_ratio_min=best_pl, min_trades=best_min_tr)
    us_gate_all = weekly_allowed_from_factor(
        panel_f14,
        theme_returns=us_rets,
        params=f14_best,
        always=PINNED,
    )
    us_syms_val = {s for s, d in us_gate_all.items() if any(d.values())}
    linkage_val = s11_val & us_syms_val

    sub_panel_val = panel[panel["symbol"].isin(linkage_val)].copy()
    s1_allowed_val = weekly_topk_allowed(
        sub_panel_val, value_col=best_col, k=best_k, always=PINNED
    )
    us_allowed_val = weekly_allowed_from_factor(
        panel_f14[panel_f14["symbol"].isin(linkage_val)],
        theme_returns=us_rets,
        params=f14_best,
        always=PINNED,
    )
    merged_val = merge_allowed(s1_allowed_val, us_allowed_val)
    navs_val = {s: nav_by_pct[best_ep][s] for s in linkage_val}
    port_full = active_nav(navs_val, merged_val, always=PINNED)

    val_m = window_metrics(port_full, VAL_START, None)
    is_m_best = window_metrics(port_full, IS_START, IS_END)

    yearly_rows = []
    for year in range(2020, 2027):
        ym = window_metrics(
            port_full,
            pd.Timestamp(f"{year}-01-01"),
            pd.Timestamp(f"{year}-12-31"),
        )
        yearly_rows.append({"year": year, **ym})
    yearly_df = pd.DataFrame(yearly_rows)
    yearly_df.to_csv(OUT / "yearly_nav.csv", index=False)
    port_full.to_csv(OUT / "portfolio_nav.csv", header=["nav"])

    picks = []
    for sym in sorted(linkage_val):
        picks.append(
            {
                "symbol": sym,
                "name": metas[sym].name,
                "themes": list(WATCHLIST_US_THEMES.get(metas[sym].code, ())),
                "pl_ratio_is": bi_val[sym].get("pl_ratio"),
                "n_trades_is": bi_val[sym].get("n_trades"),
            }
        )
    picks_df = pd.DataFrame(picks).sort_values("pl_ratio_is", ascending=False)
    picks_df.to_csv(OUT / "eligible_symbols_2025.csv", index=False)

    manifest = {
        "pipeline": "factor14 -> strategy11_pl_ratio -> strategy1_weekly_topk",
        "factor14": "factor14_us_a_theme_linkage",
        "is_window": f"{IS_START.date()}~{IS_END.date()}",
        "val_window": f"{VAL_START.date()}~{END}",
        "us_data": "yfinance theme ETFs",
        "latest_us_snapshot": snap,
        "best_params": {
            "entry_pct": best_ep,
            "pl_ratio_min": best_pl,
            "min_trades": best_min_tr,
            "top_k": best_k,
            "value_col": best_col,
            "us_top_n_themes": best_us_top,
            "us_min_ret": best_us_min,
        },
        "is_metrics": is_m_best,
        "val_metrics": val_m,
        "n_linkage_val": len(linkage_val),
        "eligible_symbols": sorted(linkage_val),
        "disclaimer": "研究回测，不构成投资建议",
    }
    (OUT / "00_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    top_us = snap.get("themes", [])[:5]
    us_lines = "\n".join(
        f"  - {t['theme']} ({t['etf']}): {t['ret_pct']:+.2f}%"
        for t in top_us
    )

    report = f"""# 美股联动 → 策略11 → 策略1 联合选股

研究回测，不构成投资建议。

## 流水线
1. **美股隔夜**：前一美股交易日主题 ETF 涨跌（yfinance），取 Top{best_us_top} 主题
   {f'且主题涨幅 ≥ {best_us_min*100:.1f}%' if best_us_min > 0 else ''}
2. **策略11**：{IS_START.date()}～{IS_END.date()} 笔盈亏比 ≥ {best_pl}，闭环 ≥ {best_min_tr}
3. **策略1**：周频 `{best_col}` Top{best_k}，entry_pct={best_ep}

最近美股快照（{snap.get('us_date', 'N/A')}）：
{us_lines}

## 样本内最优
| 参数 | 值 |
|------|-----|
| us_top_n | {best_us_top} |
| us_min_ret | {best_us_min} |
| pl_ratio_min | {best_pl} |
| entry_pct | {best_ep} |
| top_k | {best_k} |
| value_col | {best_col} |
| 联动后池子 | {int(best['n_linkage'])} |

样本内：累计 {is_m_best['ret_pct']:.1f}%，夏普 {is_m_best['sharpe']:.2f}，回撤 {is_m_best['mdd_pct']:.1f}%

## 2025 至今验证（OOS）
- 累计 **{val_m['ret_pct']:.1f}%**
- 夏普 **{val_m['sharpe']:.2f}**
- 最大回撤 **{val_m['mdd_pct']:.1f}%**
- 合格标的 **{len(linkage_val)}** 只

## 当前合格池（美股主题 ∩ 笔盈亏比）
```
{picks_df.head(15).to_string(index=False)}
```

## 分年
```
{yearly_df.to_string(index=False)}
```

## 与纯 A 股 s1+s11 对比
纯 A 股流水线（无美股门控）见 `s1_s11_select/report.md`；本报告在同样策略1/11 前增加**美股主题过滤**。

免责声明：映射为静态主题标签 + ETF 代理，不构成投资建议。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
