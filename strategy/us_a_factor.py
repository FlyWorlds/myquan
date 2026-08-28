"""因子14 · 美股隔夜主题 → A 股联动（计算与门控）。

T 日 A 股开盘前：用上一美股交易日主题 ETF 收益 + 静态主题标签，
为每只股票生成联动得分与门控信号。周频门控与因子1 开仓名单叠加使用。

不构成投资建议。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from strategy.us_a_linkage import (
    UsLinkageConfig,
    US_THEME_ETFS,
    WATCHLIST_US_THEMES,
    allowed_from_us_weekly_gate,
    fetch_us_theme_returns,
    prior_us_trading_day,
    strong_themes_on_us_day,
    symbols_for_strong_themes,
    us_gate_by_a_share_week,
)

DEFAULT_PARAMS: dict[str, Any] = {
    "top_n_themes": 2,
    "min_theme_ret": 0.005,
    "use_top_n": True,
    "use_min_ret": True,
    "score_mode": "max",  # max | mean — 映射主题收益聚合
    "timing": "us_prior_session_exec_a_open",  # 美股前收 → A 股当日开盘可用
}


def us_a_linkage_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    top_n = int(p["top_n_themes"])
    min_ret = float(p["min_theme_ret"])
    mode = str(p.get("score_mode", "max"))
    lines = [
        "================================================================================",
        "  因子14 · 美股隔夜主题 → A 股联动",
        "================================================================================",
        "数据：yfinance 主题 ETF 日收益（IGV/XLK/SMH/XLC/XLI/GDX/ARKK/QQQ）",
        "时点：A 股 T 日开盘前，取上一美股完整交易日主题涨跌",
        "映射：观察池静态主题标签（WATCHLIST_US_THEMES），非 GICS 二次映射",
        f"门控：Top{top_n} 强势主题"
        + (f" 且主题涨幅 ≥ {min_ret*100:.1f}%" if p.get("use_min_ret") else ""),
        f"得分：标的映射主题收益的 {mode}（us_link_score / us_link_exec）",
        "用途：选股门控 overlay；可与因子10/11/13 及策略11 笔盈亏比叠加",
        "================================================================================",
    ]
    return "\n".join(lines)


def linkage_config_from_params(params: dict[str, Any] | None = None) -> UsLinkageConfig:
    p = {**DEFAULT_PARAMS, **(params or {})}
    min_ret = float(p["min_theme_ret"])
    use_min = bool(p.get("use_min_ret", min_ret > 0))
    return UsLinkageConfig(
        top_n_themes=int(p["top_n_themes"]),
        min_theme_ret=min_ret,
        use_top_n=bool(p.get("use_top_n", True)),
        use_min_ret=use_min,
    )


def _stock_theme_values(
    theme_row: pd.Series,
    themes: Sequence[str],
    *,
    score_mode: str,
) -> tuple[float | None, str | None]:
    vals: list[tuple[str, float]] = []
    for t in themes:
        if t not in theme_row.index:
            continue
        v = theme_row[t]
        if pd.notna(v):
            vals.append((str(t), float(v)))
    if not vals:
        return None, None
    if score_mode == "mean":
        score = float(np.mean([v for _, v in vals]))
        best = max(vals, key=lambda x: x[1])[0]
    else:
        best, score = max(vals, key=lambda x: x[1])
    return score, best


def compute_us_a_linkage(
    daily: pd.DataFrame,
    *,
    symbol: str,
    code: str | None = None,
    themes: Sequence[str] | None = None,
    theme_returns: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    fetch_start: str = "2019-12-01",
    fetch_end: str | None = None,
) -> pd.DataFrame:
    """单票日线附加美股联动列。

    列：
      us_link_score — 映射主题在隔夜美股的最大/平均收益
      us_link_best_theme — 得分最高的主题键
      us_link_hit — 是否命中强势主题门控（周度门控在日度上展开）
      us_link_exec — 与 us_link_score 相同（已在 A 开盘前确定，无 shift）
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    cfg = linkage_config_from_params(p)
    score_mode = str(p.get("score_mode", "max"))

    c = str(code or "").zfill(6) if code else ""
    if not c and "symbol" in daily.columns:
        sym = str(daily["symbol"].iloc[0])
        c = sym[2:] if sym.startswith(("sh", "sz")) else sym
    theme_keys = tuple(themes or WATCHLIST_US_THEMES.get(c, ()))

    out = daily.copy()
    if "date" not in out.columns:
        raise ValueError("daily 缺少 date 列")

    if theme_returns is None:
        end_ts = pd.Timestamp(out["date"].max())
        end_s = end_ts.strftime("%Y-%m-%d")
        theme_returns = fetch_us_theme_returns(fetch_start, end_s)

    if theme_returns.empty:
        out["us_link_score"] = np.nan
        out["us_link_best_theme"] = None
        out["us_link_hit"] = False
        out["us_link_exec"] = np.nan
        return out

    us_dates = pd.DatetimeIndex(
        pd.to_datetime(theme_returns.index).tz_localize(None).normalize()
    )

    dates = pd.to_datetime(out["date"])
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("Asia/Shanghai")
    a_days = dates.dt.tz_localize(None).dt.normalize()

    scores: list[float | None] = []
    best_themes: list[str | None] = []
    hits: list[bool] = []

    for a_d in a_days:
        us_d = prior_us_trading_day(pd.Timestamp(a_d), us_dates)
        if us_d is None or us_d not in theme_returns.index:
            scores.append(None)
            best_themes.append(None)
            hits.append(False)
            continue
        row = theme_returns.loc[us_d]
        score, best = _stock_theme_values(row, theme_keys, score_mode=score_mode)
        strong = strong_themes_on_us_day(
            row,
            top_n=cfg.top_n_themes,
            min_ret=cfg.min_theme_ret,
            use_top_n=cfg.use_top_n,
            use_min_ret=cfg.use_min_ret,
        )
        matched = symbols_for_strong_themes(
            strong,
            code_themes={c: theme_keys},
            symbol_map={c: str(symbol)},
        )
        scores.append(score)
        best_themes.append(best)
        hits.append(str(symbol) in matched)

    out["us_link_score"] = scores
    out["us_link_best_theme"] = best_themes
    out["us_link_hit"] = hits
    out["us_link_exec"] = out["us_link_score"]
    return out


def panel_us_a_linkage(
    dailies: Mapping[str, pd.DataFrame],
    *,
    theme_returns: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    code_themes: Mapping[str, Sequence[str]] = WATCHLIST_US_THEMES,
) -> pd.DataFrame:
    """多票面板：date × symbol 联动得分与门控。"""
    rows: list[pd.DataFrame] = []
    for sym, daily in dailies.items():
        code = str(sym)[2:] if str(sym).startswith(("sh", "sz")) else str(sym)
        df = compute_us_a_linkage(
            daily,
            symbol=str(sym),
            code=code,
            themes=code_themes.get(code, ()),
            theme_returns=theme_returns,
            params=params,
        )
        part = df[
            ["date", "us_link_score", "us_link_best_theme", "us_link_hit", "us_link_exec"]
        ].copy()
        part["symbol"] = str(sym)
        rows.append(part)
    if not rows:
        return pd.DataFrame()
    panel = pd.concat(rows, ignore_index=True)
    panel["_d"] = pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize()
    panel["us_link_cs_rank"] = panel.groupby("_d")["us_link_exec"].rank(
        pct=True, method="average"
    )
    return panel.drop(columns=["_d"])


def weekly_allowed_from_factor(
    panel: pd.DataFrame,
    *,
    theme_returns: pd.DataFrame,
    params: dict[str, Any] | None = None,
    always: set[str] | None = None,
) -> dict[str, dict[str, bool]]:
    """因子14 周频门控 → 日度 allowed（与 run_us_s1_s11_select 一致）。"""
    cfg = linkage_config_from_params(params)
    dates = sorted(
        pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize().unique()
    )
    weekly_gate = us_gate_by_a_share_week(dates, theme_returns, cfg=cfg)
    symbols = sorted(panel["symbol"].astype(str).unique())
    return allowed_from_us_weekly_gate(
        symbols, dates, weekly_gate, always=always or set()
    )


def topk_allowed_by_us_score(
    panel: pd.DataFrame,
    *,
    k: int = 5,
    min_hit: bool = True,
) -> dict[str, dict[str, bool]]:
    """按日截面 us_link_exec TopK（须 us_link_hit=True 时 min_hit）。"""
    df = panel.copy()
    df["_d"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    if min_hit and "us_link_hit" in df.columns:
        df = df[df["us_link_hit"].astype(bool)]
    allowed: dict[str, dict[str, bool]] = {}
    k = max(1, int(k))
    for day, g in df.groupby("_d"):
        g = g.dropna(subset=["us_link_exec"])
        if g.empty:
            continue
        n = max(1, min(k, len(g)))
        picked = set(g.nlargest(n, "us_link_exec")["symbol"].astype(str))
        for sym in g["symbol"].astype(str).unique():
            allowed.setdefault(str(sym), {})[str(day)] = str(sym) in picked
    return allowed


def factor14_signal(
    *,
    theme_returns: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    snapshot: bool = True,
) -> dict[str, Any]:
    """因子元数据 + 最近美股主题快照（供 agent / 盯盘读取）。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    out: dict[str, Any] = {
        "factor_id": "factor14",
        "params": p,
        "rules": us_a_linkage_rules_text(p),
        "theme_etfs": dict(US_THEME_ETFS),
    }
    if snapshot:
        if theme_returns is None or theme_returns.empty:
            theme_returns = fetch_us_theme_returns(
                "2019-12-01",
                pd.Timestamp.today().strftime("%Y-%m-%d"),
            )
        if len(theme_returns) >= 1:
            last = theme_returns.index[-1]
            row = theme_returns.loc[last]
            ranked = row.sort_values(ascending=False)
            cfg = linkage_config_from_params(p)
            strong = strong_themes_on_us_day(
                row,
                top_n=cfg.top_n_themes,
                min_ret=cfg.min_theme_ret,
                use_top_n=cfg.use_top_n,
                use_min_ret=cfg.use_min_ret,
            )
            out["us_date"] = str(pd.Timestamp(last).date())
            out["strong_themes"] = sorted(strong)
            out["theme_returns_pct"] = {
                str(k): round(float(v) * 100, 2) for k, v in ranked.items() if pd.notna(v)
            }
    return out


__all__ = [
    "DEFAULT_PARAMS",
    "us_a_linkage_rules_text",
    "linkage_config_from_params",
    "compute_us_a_linkage",
    "panel_us_a_linkage",
    "weekly_allowed_from_factor",
    "topk_allowed_by_us_score",
    "factor14_signal",
]
