"""策略四 · 累计评分可买 Top20 池。

规则:
  1) 股票池：中证500+1000 主板
  2) 用因子1 累计指标截面打分（超额/夏普/收益/回撤改善）
  3) 开盘可买资格：
     - 非策略持有（昨日或更早已买入、尚未止损卖出的，不进 Top20）
     - 今日满足因子1 买入前置（阴/小阳、禁双阳等）；冲到阈值但前置不过的也不进 Top20
  4) 在资格票里取评分 TopN（默认 20）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy.data import fetch_daily
from strategy.open_break import (
    DEFAULT_PCT,
    entry_filters_ok,
    replay_last_factor_triggers,
)

_MYQUAN = Path(__file__).resolve().parents[3]
METRICS_PARQUET = (
    _MYQUAN / "backtest" / "factor1_monthly_top3" / "month_symbol_threshold_metrics.parquet"
)
DAILY_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"

POOL_DEFAULTS: dict[str, Any] = {
    "score_mode": "cum2020",  # 累计：超额/夏普/收益/回撤
    "top_n": 20,
    "universe": "zz500_1000_mainboard",
    "w_excess": 5.0,
    "w_sharpe": 3.0,
    "w_return": 2.0,
    "w_dd": 2.0,
    "exclude_holding": True,
    "require_entry_filters": True,
    "entry_pct": DEFAULT_PCT,
    "metrics_path": str(METRICS_PARQUET),
}


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def _latest_score_frame(
    *,
    score_mode: str,
    metrics_path: Path | str,
) -> tuple[str, pd.DataFrame]:
    """取最新评分月、每票择优阈值后的累计指标表。"""
    path = Path(metrics_path)
    if not path.exists():
        raise FileNotFoundError(
            f"缺少评分缓存 {path}，请先跑 backtest/factor1_monthly_top3.py"
        )
    m = pd.read_parquet(path)
    ok = f"{score_mode}_ok"
    ex = f"{score_mode}_excess_return_pct"
    sh = f"{score_mode}_sharpe_ratio"
    ret = f"{score_mode}_total_return_pct"
    dd = f"{score_mode}_dd_improve_pct"
    for col in (ok, ex, sh, ret, dd):
        if col not in m.columns:
            raise KeyError(f"指标缺列 {col}")

    sub = m[m[ok] == 1].copy()
    if sub.empty:
        raise RuntimeError(f"{score_mode} 无可用评分行")
    score_month = str(sub["score_month"].max())
    sub = sub[sub["score_month"].astype(str) == score_month].copy()

    best_rows: list[pd.Series] = []
    for _, g in sub.groupby("symbol"):
        g = g.copy()
        # 票内阈值择优：超额/夏普/回撤改善（收益一并进入 thr，弱权重）
        for col in (ex, sh, dd, ret):
            v = g[col].astype(float)
            if v.nunique() <= 1 or float(v.std(ddof=0) or 0) == 0:
                g[f"r_{col}"] = 0.5
            else:
                g[f"r_{col}"] = (v - v.min()) / (v.max() - v.min())
        g["thr_score"] = (
            5.0 * g[f"r_{ex}"]
            + 3.0 * g[f"r_{sh}"]
            + 2.0 * g[f"r_{dd}"]
            + 1.0 * g[f"r_{ret}"]
        )
        best_rows.append(g.loc[g["thr_score"].idxmax()])
    best = pd.DataFrame(best_rows).reset_index(drop=True)
    best["excess"] = best[ex].astype(float)
    best["sharpe"] = best[sh].astype(float)
    best["total_return"] = best[ret].astype(float)
    best["dd_improve"] = best[dd].astype(float)
    return score_month, best


def score_universe(
    best: pd.DataFrame,
    *,
    w_excess: float,
    w_sharpe: float,
    w_return: float,
    w_dd: float,
) -> pd.DataFrame:
    g = best.copy()
    g["score"] = (
        w_excess * _pct_rank(g["excess"])
        + w_sharpe * _pct_rank(g["sharpe"])
        + w_return * _pct_rank(g["total_return"])
        + w_dd * _pct_rank(g["dd_improve"])
    )
    return g.sort_values("score", ascending=False).reset_index(drop=True)


def _load_daily(symbol: str, refresh: bool = False) -> pd.DataFrame | None:
    cache = DAILY_CACHE / f"{symbol}_daily_qfq.parquet"
    end = pd.Timestamp.today().strftime("%Y%m%d")
    try:
        if cache.exists() and not refresh:
            d = pd.read_parquet(cache)
        else:
            d = fetch_daily(symbol, "20190101", end, cache_path=cache)
        if d is None or d.empty:
            return None
        out = d.copy()
        out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
        return out.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    except Exception:
        return None


def eligibility_for_symbol(
    symbol: str,
    *,
    entry_pct: float = DEFAULT_PCT,
    exclude_holding: bool = True,
    require_entry_filters: bool = True,
    daily: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """开盘可买资格：非持有 + 买入前置通过。"""
    d = daily if daily is not None else _load_daily(symbol)
    info: dict[str, Any] = {
        "symbol": symbol,
        "eligible": False,
        "holding": None,
        "entry_ok": None,
        "reason": "",
        "asof": None,
    }
    if d is None or len(d) < 3:
        info["reason"] = "无日线/不足"
        return info

    asof = pd.Timestamp(d.iloc[-1]["date"]).normalize()
    info["asof"] = asof.date().isoformat()

    holding = False
    if exclude_holding:
        rep = replay_last_factor_triggers(d, entry_pct=entry_pct, stop_pct=entry_pct)
        holding = bool(rep.get("holding"))
        info["holding"] = holding
        if holding:
            info["reason"] = "策略持有中(已触发买入未止损)"
            info["last_buy_date"] = rep.get("last_buy_date")
            return info

    entry_ok = True
    if require_entry_filters:
        prev = d.iloc[-2]
        prev2 = d.iloc[-3]
        entry_ok = entry_filters_ok(
            float(prev["open"]),
            float(prev["close"]),
            float(prev2["open"]),
            float(prev2["close"]),
            entry_pct=entry_pct,
            prev_entry_mode="yin_or_small_yang",
        )
        info["entry_ok"] = entry_ok
        if not entry_ok:
            info["reason"] = "买入前置未过(阴/小阳或双阳过滤)"
            return info

    info["eligible"] = True
    info["entry_ok"] = entry_ok
    info["holding"] = holding
    info["reason"] = "可新开仓"
    return info


@dataclass
class PoolResult:
    score_month: str
    asof: str | None
    top: pd.DataFrame
    scored: pd.DataFrame
    excluded: pd.DataFrame
    config: dict[str, Any]


def build_tradable_top_pool(**overrides: Any) -> PoolResult:
    """构建「可新开仓」累计评分 TopN。"""
    cfg = dict(POOL_DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})

    score_month, best = _latest_score_frame(
        score_mode=str(cfg["score_mode"]),
        metrics_path=cfg["metrics_path"],
    )
    # 限制在中证500+1000 主板并集（指标表本身多来自该池；再与成分对齐）
    try:
        from backtest.zz1000_momentum_select import load_zz500_1000_mainboard

        univ = load_zz500_1000_mainboard()
        allow = set(univ["symbol"].tolist())
        name_map = dict(zip(univ["symbol"], univ["name"]))
        best = best[best["symbol"].isin(allow)].copy()
        best["name"] = best["symbol"].map(name_map)
    except Exception:
        best["name"] = best.get("name", "")

    scored = score_universe(
        best,
        w_excess=float(cfg["w_excess"]),
        w_sharpe=float(cfg["w_sharpe"]),
        w_return=float(cfg["w_return"]),
        w_dd=float(cfg["w_dd"]),
    )
    scored["raw_rank"] = np.arange(1, len(scored) + 1)

    # 按评分从高到低检查资格，凑满 TopN 即可（避免全市场逐票读日线）
    top_n = int(cfg["top_n"])
    elig_rows: list[dict[str, Any]] = []
    excl_rows: list[dict[str, Any]] = []
    asof: str | None = None
    checked = 0
    for _, row in scored.iterrows():
        if len(elig_rows) >= top_n:
            break
        checked += 1
        sym = str(row["symbol"])
        elig = eligibility_for_symbol(
            sym,
            entry_pct=float(cfg["entry_pct"]),
            exclude_holding=bool(cfg["exclude_holding"]),
            require_entry_filters=bool(cfg["require_entry_filters"]),
        )
        if elig.get("asof"):
            asof = str(elig["asof"])
        pack = {
            **row.to_dict(),
            "eligible": elig["eligible"],
            "holding": elig.get("holding"),
            "entry_ok": elig.get("entry_ok"),
            "reason": elig.get("reason"),
            "last_buy_date": elig.get("last_buy_date"),
        }
        if elig["eligible"]:
            elig_rows.append(pack)
        else:
            excl_rows.append(pack)

    elig_df = pd.DataFrame(elig_rows)
    if elig_df.empty:
        top = elig_df
    else:
        top = elig_df.copy()
        top["pool_rank"] = np.arange(1, len(top) + 1)
    cfg = dict(cfg)
    cfg["checked"] = checked

    return PoolResult(
        score_month=score_month,
        asof=asof,
        top=top,
        scored=scored,
        excluded=pd.DataFrame(excl_rows),
        config=cfg,
    )


def run_strategy4_pool(
    *,
    verbose: bool = True,
    save_dir: Path | str | None = None,
    **overrides: Any,
) -> PoolResult:
    result = build_tradable_top_pool(**overrides)
    cfg = result.config
    if verbose:
        print(
            f"[策略四] 评分月={result.score_month} asof={result.asof} "
            f"mode={cfg['score_mode']} top={cfg['top_n']} "
            f"权重 超额{cfg['w_excess']}/夏普{cfg['w_sharpe']}/"
            f"收益{cfg['w_return']}/回撤{cfg['w_dd']}"
        )
        print(
            f"  评分样本 {len(result.scored)} | 资格检查 {result.config.get('checked')} | "
            f"排除(已查) {len(result.excluded)} | 可买Top {len(result.top)}"
        )
        if not result.top.empty:
            cols = [
                c
                for c in (
                    "pool_rank",
                    "symbol",
                    "name",
                    "score",
                    "excess",
                    "sharpe",
                    "total_return",
                    "dd_improve",
                    "threshold_pct",
                    "raw_rank",
                )
                if c in result.top.columns
            ]
            print(result.top[cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    out = Path(save_dir) if save_dir else _MYQUAN / "backtest" / "strategy4_out"
    out.mkdir(parents=True, exist_ok=True)
    if not result.top.empty:
        result.top.to_csv(out / "top20_tradable.csv", index=False, encoding="utf-8-sig")
    result.excluded.to_csv(out / "excluded.csv", index=False, encoding="utf-8-sig")
    result.scored.head(50).to_csv(out / "scored_head50.csv", index=False, encoding="utf-8-sig")
    if verbose:
        print(f"产物: {out}")
    return result
