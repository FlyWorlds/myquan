"""美股板块/主题 → A 股标的联动映射（研究用）。

用美股主题 ETF 日收益刻画隔夜外盘强弱，再按静态主题标签过滤 A 股观察池。
数据默认 yfinance；与 us-sector-rotation skill 的 ETF 代理口径一致。

不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

# 主题键 → 美股 ETF（yfinance）
US_THEME_ETFS: dict[str, str] = {
    "software": "IGV",
    "semiconductor": "SMH",
    "tech": "XLK",
    "comm": "XLC",
    "industrial": "XLI",
    "mining": "GDX",
    "innovation": "ARKK",
    "nasdaq": "QQQ",
}

# A 股代码 → 主题键（可多标签；观察池静态映射，非 GICS）
WATCHLIST_US_THEMES: dict[str, tuple[str, ...]] = {
    "301600": ("tech", "industrial"),
    "001389": ("semiconductor"),
    "002290": ("tech"),
    "301392": ("semiconductor"),
    "301205": ("semiconductor", "comm"),
    "600552": ("semiconductor", "tech"),
    "601208": ("industrial", "semiconductor"),
    "301550": ("semiconductor", "industrial"),
    "002636": ("industrial"),
    "301678": ("semiconductor"),
    "600105": ("comm"),
    "603083": ("comm", "semiconductor"),
    "001339": ("software", "tech"),
    "600330": ("semiconductor"),
    "600206": ("semiconductor", "mining"),
    "002979": ("tech", "industrial"),
    "301389": ("semiconductor"),
    "002378": ("mining"),
    "002738": ("mining"),
    "603119": ("industrial"),
    "603306": ("industrial"),
    "601020": ("mining"),
    "301458": ("semiconductor"),
    "002335": ("software", "tech"),
    "002747": ("industrial", "innovation"),
    "589680": ("nasdaq", "tech"),
}


@dataclass(frozen=True)
class UsLinkageConfig:
    top_n_themes: int = 2
    min_theme_ret: float = 0.0  # 小数，如 0.003 = 0.3%
    use_top_n: bool = True
    use_min_ret: bool = False


def _yf_symbol(etf: str) -> str:
    return str(etf)


def _to_yf_date(s: str) -> str:
    t = pd.Timestamp(str(s))
    return t.strftime("%Y-%m-%d")


def fetch_us_theme_returns(
    start: str,
    end: str,
    *,
    themes: Sequence[str] | None = None,
) -> pd.DataFrame:
    """拉取主题 ETF 日收益（列=主题键，索引=美股交易日 date）。"""
    import yfinance as yf

    keys = list(themes or US_THEME_ETFS.keys())
    etf_map = {k: US_THEME_ETFS[k] for k in keys if k in US_THEME_ETFS}
    tickers = list(dict.fromkeys(etf_map.values()))
    if not tickers:
        return pd.DataFrame()

    raw = yf.download(
        tickers,
        start=_to_yf_date(start),
        end=_to_yf_date(end),
        auto_adjust=False,
        progress=False,
    )
    if raw.empty:
        return pd.DataFrame()

    closes = raw["Close"]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(tickers[0])
    closes.index = pd.to_datetime(closes.index)
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)
    closes = closes.sort_index()
    rets = closes.pct_change()

    out = pd.DataFrame(index=rets.index)
    for theme, etf in etf_map.items():
        col = etf if etf in rets.columns else None
        if col is None and len(rets.columns) == 1:
            col = rets.columns[0]
        if col is not None:
            out[theme] = rets[col]
    return out.dropna(how="all")


def prior_us_trading_day(a_share_date: pd.Timestamp, us_dates: pd.DatetimeIndex) -> pd.Timestamp | None:
    """A 股交易日开盘前，取最近一个已完成的美股交易日。"""
    a = pd.Timestamp(a_share_date).normalize()
    if a.tzinfo is not None:
        a = a.tz_localize(None)
    prior = us_dates[us_dates < a]
    if len(prior) == 0:
        return None
    return pd.Timestamp(prior[-1])


def strong_themes_on_us_day(
    theme_rets: pd.Series,
    *,
    top_n: int,
    min_ret: float,
    use_top_n: bool,
    use_min_ret: bool,
) -> set[str]:
    s = theme_rets.dropna()
    if s.empty:
        return set()
    picked: set[str] = set()
    if use_top_n and top_n > 0:
        n = min(int(top_n), len(s))
        picked |= set(s.nlargest(n).index.astype(str))
    if use_min_ret:
        picked |= set(s.index[s >= float(min_ret)].astype(str))
    if not picked and not use_top_n and not use_min_ret:
        picked = set(s.index.astype(str))
    return picked


def symbols_for_strong_themes(
    strong: set[str],
    *,
    code_themes: Mapping[str, Sequence[str]] = WATCHLIST_US_THEMES,
    symbol_map: Mapping[str, str] | None = None,
) -> set[str]:
    """主题集合 → 带 sh/sz 前缀的 symbol 集合。"""
    if symbol_map is None:
        from holdingStocks.watch_config import sina_of

        symbol_map = {code: sina_of(code) for code in code_themes}

    out: set[str] = set()
    for code, themes in code_themes.items():
        if strong and any(t in strong for t in themes):
            sym = symbol_map.get(code) or symbol_map.get(str(code).zfill(6))
            if sym:
                out.add(str(sym))
    return out


def us_gate_by_a_share_week(
    a_share_dates: Sequence[pd.Timestamp],
    theme_returns: pd.DataFrame,
    *,
    cfg: UsLinkageConfig,
    code_themes: Mapping[str, Sequence[str]] = WATCHLIST_US_THEMES,
    symbol_map: Mapping[str, str] | None = None,
) -> dict[str, set[str]]:
    """每个 A 股周（周一为起点）→ 该周允许交易的 symbol 集合（美股联动门控）。"""
    if theme_returns.empty:
        return {}

    us_dates = pd.DatetimeIndex(
        pd.to_datetime(theme_returns.index).tz_localize(None).normalize()
    )
    days = pd.to_datetime(list(a_share_dates))
    if getattr(days.tz, "tz", None) is not None or days.tz is not None:
        days = days.tz_localize(None)
    days = pd.DatetimeIndex(days.normalize()).unique().sort_values()
    week_starts = days - pd.to_timedelta(days.dayofweek, unit="D")

    gate: dict[str, set[str]] = {}
    for w in sorted(set(week_starts)):
        week_days = days[week_starts == w]
        if len(week_days) == 0:
            continue
        first_a = pd.Timestamp(week_days[0])
        us_d = prior_us_trading_day(first_a, us_dates)
        key = pd.Timestamp(w).strftime("%Y-%m-%d")
        if us_d is None or us_d not in theme_returns.index:
            gate[key] = set()
            continue
        row = theme_returns.loc[us_d]
        strong = strong_themes_on_us_day(
            row,
            top_n=cfg.top_n_themes,
            min_ret=cfg.min_theme_ret,
            use_top_n=cfg.use_top_n,
            use_min_ret=cfg.use_min_ret,
        )
        gate[key] = symbols_for_strong_themes(
            strong, code_themes=code_themes, symbol_map=symbol_map
        )
    return gate


def allowed_from_us_weekly_gate(
    symbols: Sequence[str],
    a_share_dates: Sequence[pd.Timestamp],
    weekly_gate: dict[str, set[str]],
    *,
    always: set[str] | None = None,
) -> dict[str, dict[str, bool]]:
    """把周度美股门控展开为日度 allowed[sym][date]。"""
    always_set = {str(x) for x in (always or set())}
    days = pd.to_datetime(list(a_share_dates))
    if days.tz is not None:
        days = days.tz_localize(None)
    days = sorted(set(days.normalize()))
    allowed: dict[str, dict[str, bool]] = {str(s): {} for s in symbols}
    for d in days:
        w = d - pd.Timedelta(days=int(d.dayofweek))
        wkey = pd.Timestamp(w).strftime("%Y-%m-%d")
        picked = weekly_gate.get(wkey, set()) | always_set
        dkey = pd.Timestamp(d).strftime("%Y-%m-%d")
        for sym in symbols:
            allowed[str(sym)][dkey] = str(sym) in picked
    return allowed


def merge_allowed(
    a: dict[str, dict[str, bool]],
    b: dict[str, dict[str, bool]],
) -> dict[str, dict[str, bool]]:
    """两日度门控取交集。"""
    syms = set(a.keys()) | set(b.keys())
    out: dict[str, dict[str, bool]] = {}
    for sym in syms:
        da = a.get(sym, {})
        db = b.get(sym, {})
        days = set(da.keys()) | set(db.keys())
        out[sym] = {d: bool(da.get(d, False) and db.get(d, False)) for d in days}
    return out


def latest_us_theme_snapshot(
    *,
    lookback_days: int = 10,
) -> dict[str, Any]:
    """最近美股交易日主题涨跌快照（用于报告）。"""
    import datetime as dt

    end = dt.date.today()
    start = end - dt.timedelta(days=int(lookback_days) + 30)
    rets = fetch_us_theme_returns(
        start.strftime("%Y-%m-%d"),
        (end + dt.timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    if rets.empty or len(rets) < 2:
        return {"us_date": None, "themes": []}
    last = rets.index[-1]
    prev = rets.index[-2]
    row = rets.loc[last]
    ranked = row.sort_values(ascending=False)
    themes = [
        {
            "theme": str(k),
            "etf": US_THEME_ETFS.get(str(k), ""),
            "ret_pct": round(float(v) * 100, 2),
        }
        for k, v in ranked.items()
        if pd.notna(v)
    ]
    return {
        "us_date": str(last.date()),
        "prev_us_date": str(prev.date()),
        "themes": themes,
    }


__all__ = [
    "US_THEME_ETFS",
    "WATCHLIST_US_THEMES",
    "UsLinkageConfig",
    "fetch_us_theme_returns",
    "prior_us_trading_day",
    "strong_themes_on_us_day",
    "symbols_for_strong_themes",
    "us_gate_by_a_share_week",
    "allowed_from_us_weekly_gate",
    "merge_allowed",
    "latest_us_theme_snapshot",
]
