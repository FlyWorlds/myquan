"""竞价一字联动选股（因子14 / 策略十二）。

口径（与 B6 一字板 / 题材分组同源）：
  1. 当日识别「竞价一字」龙头：开盘贴涨停且低价也贴板（可买不进，仅作题材锚）。
  2. 在同代表题材（PIT 概念成分）内，找开盘高开、但未一字涨停、仍可参与的联动标的。
  3. 按「高开幅度 × 题材内一字龙头数」排序，取 TopK；T 开盘等权买入，持有 hold_days 日。

回测代理：无 09:25 快照时用日线 open/low/limit_up；有 opn_auc 时优先作竞价价。
研究模拟，不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from strategy.open_break import cannot_buy_limit_up, limit_down_state

LIMIT_TOL = 0.999


DEFAULT_PARAMS: dict[str, Any] = {
    "min_open_gap": 0.03,
    "max_open_gap": 0.095,
    "top_k": 5,
    "hold_days": 1,
    "min_leaders_per_concept": 1,
    "block_limit_up_buy": True,
    "block_limit_down_sell": True,
    "exclude_st": True,
    "start": "20200102",
    "end": "20260820",
}


def limit_rate_of(code: str, name: str = "") -> float:
    c = str(code).upper()
    is_st = "ST" in str(name).upper()
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    if c.endswith(".BJ") or c.startswith(("8", "4")):
        return 0.30
    return 0.05 if is_st else 0.10


def eff_limit_up(pre_close: float, limit_up: float | None, code: str, name: str = "") -> float:
    if limit_up is not None and float(limit_up) > 0:
        return float(limit_up)
    rate = limit_rate_of(code, name)
    return round(float(pre_close) * (1.0 + rate), 2)


def is_one_word_at_open(
    open_px: float,
    low_px: float,
    limit_up_px: float,
    *,
    auction_px: float | None = None,
) -> bool:
    """竞价/开盘一字：价贴涨停且低价也贴板。"""
    if limit_up_px <= 0 or not np.isfinite(limit_up_px):
        return False
    ref = float(auction_px) if auction_px is not None and np.isfinite(auction_px) and auction_px > 0 else float(open_px)
    if ref <= 0 or low_px <= 0:
        return False
    lim = float(limit_up_px)
    return ref >= lim * LIMIT_TOL and float(low_px) >= lim * LIMIT_TOL


def factor14_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
因子14 · 竞价一字联动选股
================================================================================
锚点：当日竞价/开盘一字（open/opn_auc 与 low 均贴涨停价）。
联动：同代表题材（PIT 概念成分）内，开盘高开 {p['min_open_gap']:.1%}–{p['max_open_gap']:.1%}、
      非一字涨停、非 ST；按 高开×题材内一字龙头数 排序取 Top{p['top_k']}。
成交：T 开盘等权买入，持有 {p['hold_days']} 个交易日；一字涨停开盘不买、一字跌停封单不卖。
时点：T 日开盘前仅可用 T-1 及以前概念成分；竞价价优先 opn_auc，否则 open。
研究模拟，不构成投资建议，不承诺收益。
================================================================================
""".strip()


def build_stock_concepts(concepts: pd.DataFrame, asof: pd.Timestamp) -> dict[str, set[str]]:
    """概念成分 PIT：in_date <= asof。"""
    if concepts is None or concepts.empty:
        return {}
    df = concepts.copy()
    if "concept_stock" in df.columns and "ts_code" not in df.columns:
        df = df.rename(columns={"concept_stock": "ts_code"})
    if "in_date" in df.columns:
        df["in_date"] = pd.to_datetime(df["in_date"], errors="coerce")
        df = df[df["in_date"].isna() | (df["in_date"] <= asof)]
    out: dict[str, set[str]] = {}
    for _, row in df.dropna(subset=["concept", "ts_code"]).iterrows():
        sym = str(row["ts_code"]).strip()
        concept = str(row["concept"]).strip()
        if not sym or not concept:
            continue
        out.setdefault(sym, set()).add(concept)
    return out


def daily_linkage_picks(
    day_rows: pd.DataFrame,
    stock_concepts: dict[str, set[str]],
    *,
    params: dict[str, Any] | None = None,
) -> list[str]:
    """单日联动选股名单（已排序）。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if day_rows.empty:
        return []

    leaders: list[str] = []
    concept_leader_count: dict[str, int] = {}

    for _, r in day_rows.iterrows():
        sym = str(r.get("symbol") or r.get("ts_code") or "")
        name = str(r.get("name") or "")
        if p["exclude_st"] and "ST" in name.upper():
            continue
        pre = float(r.get("pre_close") or 0)
        if pre <= 0:
            continue
        lim = eff_limit_up(pre, r.get("limit_up"), sym, name)
        opn = float(r.get("open") or 0)
        low = float(r.get("low") or opn)
        auc = r.get("opn_auc")
        auction_px = float(auc) if auc is not None and np.isfinite(float(auc)) and float(auc) > 0 else None
        if not is_one_word_at_open(opn, low, lim, auction_px=auction_px):
            continue
        leaders.append(sym)

    if not leaders:
        return []

    # 统计各题材一字龙头数
    for sym in leaders:
        for c in stock_concepts.get(sym, set()):
            concept_leader_count[c] = concept_leader_count.get(c, 0) + 1

    min_leaders = int(p["min_leaders_per_concept"])
    hot_concepts = {c for c, n in concept_leader_count.items() if n >= min_leaders}
    if not hot_concepts:
        return []

    candidates: list[tuple[str, float]] = []
    leader_set = set(leaders)
    for _, r in day_rows.iterrows():
        sym = str(r.get("symbol") or r.get("ts_code") or "")
        if sym in leader_set:
            continue
        name = str(r.get("name") or "")
        if p["exclude_st"] and "ST" in name.upper():
            continue
        pre = float(r.get("pre_close") or 0)
        opn = float(r.get("open") or 0)
        if pre <= 0 or opn <= 0:
            continue
        gap = opn / pre - 1.0
        if gap < float(p["min_open_gap"]) or gap > float(p["max_open_gap"]):
            continue
        lim = eff_limit_up(pre, r.get("limit_up"), sym, name)
        low = float(r.get("low") or opn)
        auc = r.get("opn_auc")
        auction_px = float(auc) if auc is not None and np.isfinite(float(auc)) and float(auc) > 0 else None
        if is_one_word_at_open(opn, low, lim, auction_px=auction_px):
            continue
        if p["block_limit_up_buy"] and cannot_buy_limit_up(
            prev_close=pre,
            open_px=opn,
            high_px=float(r.get("high") or opn),
            low_px=low,
            close_px=float(r.get("close") or opn),
            limit_up_pct=limit_rate_of(sym, name),
        ):
            continue
        sc = stock_concepts.get(sym, set())
        shared = sc & hot_concepts
        if not shared:
            continue
        anchor_count = max(concept_leader_count.get(c, 0) for c in shared)
        score = gap * (1.0 + anchor_count)
        candidates.append((sym, score))

    candidates.sort(key=lambda x: (-x[1], x[0]))
    top_k = int(p["top_k"])
    return [s for s, _ in candidates[:top_k]]


def picks_by_date(
    panel: pd.DataFrame,
    concepts: pd.DataFrame | None = None,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """panel 长表 → {YYYY-MM-DD: [symbols]}。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if panel.empty:
        return {}
    df = panel.copy()
    date_col = "date" if "date" in df.columns else "trade_date"
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    sym_col = "symbol" if "symbol" in df.columns else "ts_code"
    out: dict[str, list[str]] = {}
    for dt, grp in df.groupby(date_col):
        asof = pd.Timestamp(dt)
        stock_concepts = build_stock_concepts(concepts, asof) if concepts is not None else {}
        picks = daily_linkage_picks(grp.assign(symbol=grp[sym_col]), stock_concepts, params=p)
        if picks:
            out[asof.strftime("%Y-%m-%d")] = picks
    return out


def factor14_signal(
    panel: pd.DataFrame | None = None,
    concepts: pd.DataFrame | None = None,
    *,
    date: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    if panel is None:
        return {"factor_id": "factor14", "params": p, "gate": {}}
    gate = picks_by_date(panel, concepts, params=p)
    if date is None:
        return {"factor_id": "factor14", "params": p, "gate": gate}
    key = pd.Timestamp(date).strftime("%Y-%m-%d")
    names = gate.get(key, [])
    return {
        "factor_id": "factor14",
        "date": key,
        "picks": names,
        "target": names,
        "params": p,
    }


@dataclass
class AuctionYiziLinkageResult:
    picks: dict[str, list[str]]
    equity: pd.Series
    stats: dict[str, float]
    params: dict[str, Any]


def _equal_weight_hold_nav(
    picks: dict[str, list[str]],
    open_px: pd.DataFrame,
    close_px: pd.DataFrame,
    low_px: pd.DataFrame,
    high_px: pd.DataFrame,
    pre_close: pd.DataFrame,
    *,
    hold_days: int = 1,
    block_limit_up_buy: bool = True,
    block_limit_down_sell: bool = True,
) -> pd.Series:
    """T 开盘买入 picks[T]，持有 hold_days 后开盘卖出（简化可成交口径）。"""
    dates = sorted(open_px.index)
    if not dates:
        return pd.Series(dtype=float)
    nav = 1.0
    curve: dict[pd.Timestamp, float] = {}
    active: list[tuple[pd.Timestamp, list[str], float]] = []

    for i, d in enumerate(dates):
        # 到期平仓
        still: list[tuple[pd.Timestamp, list[str], float]] = []
        for entry_date, syms, weight in active:
            exit_i = dates.index(entry_date) + hold_days
            if i >= exit_i:
                ret = 0.0
                n = len(syms)
                for sym in syms:
                    if sym not in open_px.columns:
                        continue
                    try:
                        sell_i = min(exit_i, len(dates) - 1)
                        sell_d = dates[sell_i]
                        buy_p = float(open_px.at[entry_date, sym])
                        sell_p = float(open_px.at[sell_d, sym])
                        if buy_p <= 0:
                            continue
                        if block_limit_down_sell:
                            pc = float(pre_close.at[sell_d, sym]) if sym in pre_close.columns else buy_p
                            st = limit_down_state(
                                prev_close=pc,
                                open_px=sell_p,
                                high_px=float(high_px.at[sell_d, sym]),
                                low_px=float(low_px.at[sell_d, sym]),
                                close_px=float(close_px.at[sell_d, sym]),
                            )
                            if st["locked"]:
                                sell_p = float(close_px.at[sell_d, sym])
                        ret += (sell_p / buy_p - 1.0) / n
                    except (KeyError, TypeError, ValueError):
                        continue
                nav *= 1.0 + ret * weight
            else:
                still.append((entry_date, syms, weight))
        active = still

        # 新开仓
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        syms = picks.get(key, [])
        if syms:
            tradable = []
            for sym in syms:
                if sym not in open_px.columns:
                    continue
                try:
                    opn = float(open_px.at[d, sym])
                    pc = float(pre_close.at[d, sym])
                    if opn <= 0 or pc <= 0:
                        continue
                    if block_limit_up_buy and cannot_buy_limit_up(
                        prev_close=pc,
                        open_px=opn,
                        high_px=float(high_px.at[d, sym]),
                        low_px=float(low_px.at[d, sym]),
                        close_px=float(close_px.at[d, sym]),
                    ):
                        continue
                    tradable.append(sym)
                except (KeyError, TypeError, ValueError):
                    continue
            if tradable:
                active.append((d, tradable, 1.0))

        curve[d] = nav

    return pd.Series(curve).sort_index()


def run_auction_yizi_linkage(
    *,
    panel: pd.DataFrame | None = None,
    concepts: pd.DataFrame | None = None,
    open_px: pd.DataFrame | None = None,
    close_px: pd.DataFrame | None = None,
    high_px: pd.DataFrame | None = None,
    low_px: pd.DataFrame | None = None,
    pre_close_px: pd.DataFrame | None = None,
    start: str | None = None,
    end: str | None = None,
    verbose: bool = True,
    **overrides: Any,
) -> AuctionYiziLinkageResult:
    p = {**DEFAULT_PARAMS, **overrides}
    if start is not None:
        p["start"] = start
    if end is not None:
        p["end"] = end

    if panel is None or open_px is None:
        from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc

        ohlc = load_combined_ohlc()
        open_px = ohlc["open"]
        close_px = ohlc["close"]
        high_px = ohlc["high"]
        low_px = ohlc["low"]
        pre_close_px = close_px.shift(1)
        # 长表 panel 供 picks
        frames = []
        for sym in open_px.columns:
            frames.append(
                pd.DataFrame(
                    {
                        "date": open_px.index,
                        "symbol": sym,
                        "open": open_px[sym].values,
                        "high": high_px[sym].values,
                        "low": low_px[sym].values,
                        "close": close_px[sym].values,
                        "pre_close": pre_close_px[sym].values,
                    }
                )
            )
        panel = pd.concat(frames, ignore_index=True)

    start_ts = pd.Timestamp(str(p["start"]))
    end_ts = pd.Timestamp(str(p["end"]))
    open_px = open_px.loc[(open_px.index >= start_ts) & (open_px.index <= end_ts)]
    close_px = close_px.loc[open_px.index]
    high_px = high_px.loc[open_px.index]
    low_px = low_px.loc[open_px.index]
    pre_close_px = pre_close_px.loc[open_px.index]

    panel_sub = panel.copy()
    if "date" in panel_sub.columns:
        panel_sub["date"] = pd.to_datetime(panel_sub["date"])
        panel_sub = panel_sub[(panel_sub["date"] >= start_ts) & (panel_sub["date"] <= end_ts)]

    picks = picks_by_date(
        panel_sub,
        concepts,
        params=p,
    )
    eq = _equal_weight_hold_nav(
        picks,
        open_px,
        close_px,
        low_px,
        high_px,
        pre_close_px,
        hold_days=int(p["hold_days"]),
        block_limit_up_buy=bool(p["block_limit_up_buy"]),
        block_limit_down_sell=bool(p["block_limit_down_sell"]),
    )
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 1 and rets.std() > 0 else 0.0
    stats = {"total_return": total, "sharpe": sharpe, "n_pick_days": len(picks)}
    if verbose:
        print(factor14_rules_text(p))
        print(f"选股日 {len(picks)} · 累计 {total:.2%} · Sharpe≈{sharpe:.2f}")
    return AuctionYiziLinkageResult(picks=picks, equity=eq, stats=stats, params=p)
