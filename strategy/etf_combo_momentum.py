"""因子6 · 组合动量 ETF 轮动。

思路（散户可交易的宽基 ETF，非个股截面）：
  · 对每只 ETF 算短窗 ROC(n) + 长窗 ROC(n2)，合成分数（组合动量）
  · 收盘截面取 TopK；最高分 <= min_score 则空仓（动量失效）
  · 信号日收盘确认 → 次日开盘轮动；默认每 hold_days 再平衡
  · 持仓分数跌破门槛则下一开盘风控空仓（T+1 买入当日不卖）

本模块只做研究/回测信号，不构成投资建议。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

DEFAULT_UNIVERSE: tuple[tuple[str, str], ...] = (
    ("sh510300", "沪深300ETF"),
    ("sh510500", "中证500ETF"),
    ("sz159915", "创业板ETF"),
    ("sh512100", "中证1000ETF"),
    ("sh588000", "科创50ETF"),
    ("sh510880", "红利ETF"),
)

DEFAULT_PARAMS: dict[str, Any] = {
    "n": 20,
    "n2": 60,
    "w": 1.0,
    "top_k": 1,
    "hold_days": 20,
    "min_score": 0.0,
    "defensive": None,
    "start": "20200101",
    "warm_start": "20180101",
}

COMMISSION = 0.0000854
STAMP = 0.0  # 场内 ETF 无印花税
SLIP = 0.001
LOT = 100
INITIAL_CASH = 1_000_000.0


def etf_combo_momentum_rules_text(
    params: Mapping[str, Any] | None = None,
    universe: Sequence[tuple[str, str]] | None = None,
) -> str:
    p = {**DEFAULT_PARAMS, **dict(params or {})}
    univ = universe or DEFAULT_UNIVERSE
    names = "、".join(f"{code[2:]} {name}" for code, name in univ)
    defensive = p.get("defensive") or "现金"
    return f"""\
================================================================================
  因子6 · 组合动量 ETF 轮动
================================================================================
  · 股票池：{names}
  · 分数：ROC(n={p['n']}) + {p['w']:g}×ROC(n2={p['n2']})；越大越强
  · 选仓：收盘截面 Top{p['top_k']}；最高分 <= {p['min_score']} → 空仓（可改 defensive={defensive}）
  · 执行：收盘信号 → 次日开盘；每 {p['hold_days']} 日再平衡
  · 风控：持仓分数跌破门槛，下一开盘空仓；T+1 买入当日不卖
  · 成本：佣金 {COMMISSION}、滑点 {SLIP}、ETF 印花税 {STAMP}
================================================================================
""".strip()


def combo_momentum_score(
    closes: pd.DataFrame,
    *,
    n: int = 20,
    n2: int = 60,
    w: float = 1.0,
) -> pd.DataFrame:
    """日期×标的组合动量分数；信息截止当日收盘，无未来函数。"""
    c = closes.astype(float)
    n = int(n)
    n2 = int(n2)
    roc1 = c / c.shift(n) - 1.0
    roc2 = c / c.shift(n2) - 1.0
    return roc1.add(float(w) * roc2)


def _lookup_list(
    mapping: dict[pd.Timestamp, list[str]], day: pd.Timestamp | None
) -> list[str]:
    if day is None:
        return []
    if day in mapping:
        return list(mapping[day])
    key = pd.Timestamp(day).normalize()
    if key in mapping:
        return list(mapping[key])
    for k, v in mapping.items():
        if pd.Timestamp(k).normalize() == key:
            return list(v)
    return []


def daily_targets(
    score: pd.DataFrame,
    *,
    top_k: int = 1,
    min_score: float = 0.0,
    defensive: str | None = None,
) -> dict[pd.Timestamp, list[str]]:
    """每个收盘日的目标持仓（可能为空=现金；或 defensive）。"""
    k = max(int(top_k), 1)
    floor = float(min_score)
    out: dict[pd.Timestamp, list[str]] = {}
    for dt, row in score.iterrows():
        valid = row.dropna()
        valid = valid[valid > floor]
        if valid.empty:
            if defensive and defensive in score.columns:
                out[pd.Timestamp(dt)] = [str(defensive)]
            else:
                out[pd.Timestamp(dt)] = []
            continue
        ranked = valid.sort_values(ascending=False)
        out[pd.Timestamp(dt)] = [str(s) for s in ranked.index[:k]]
    return out


def _panel_from_dailies(
    dailies: Mapping[str, pd.DataFrame],
    field: str,
) -> pd.DataFrame:
    cols: dict[str, pd.Series] = {}
    for sym, df in dailies.items():
        if df is None or df.empty or field not in df.columns:
            continue
        idx = pd.to_datetime(df["date"])
        if getattr(idx.dt, "tz", None) is not None:
            idx = idx.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
        else:
            idx = idx.dt.normalize()
        s = pd.Series(df[field].astype(float).to_numpy(), index=idx, name=sym)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        cols[sym] = s
    if not cols:
        return pd.DataFrame()
    panel = pd.concat(cols, axis=1).sort_index()
    panel.columns = [str(c) for c in panel.columns]
    return panel


def simulate_etf_combo_momentum(
    *,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: dict[pd.Timestamp, list[str]],
    score: pd.DataFrame,
    bt_start: pd.Timestamp,
    hold_days: int,
    min_score: float,
    initial_cash: float,
    factor_label: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """全仓轮动：到期再平衡 + 分数跌破门槛提前空仓。"""
    dates = [pd.Timestamp(d) for d in closes.index]
    cash = float(initial_cash)
    pos: list[dict[str, Any]] = []
    first_i: int | None = None
    last_reb_i: int | None = None
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    n_reb = 0
    n_risk = 0

    def _mtm(day: pd.Timestamp) -> float:
        value = cash
        for item in pos:
            sym = item["sym"]
            px = (
                float(closes.at[day, sym])
                if sym in closes.columns and not pd.isna(closes.at[day, sym])
                else float(item.get("last_px") or 0.0)
            )
            value += item["shares"] * px
        return value

    def _sell_all(day: pd.Timestamp, reason: str) -> None:
        nonlocal cash, pos
        still: list[dict[str, Any]] = []
        for item in pos:
            sym = item["sym"]
            if (
                sym not in opens.columns
                or pd.isna(opens.at[day, sym])
                or float(opens.at[day, sym]) <= 0
            ):
                still.append(item)
                continue
            px = float(opens.at[day, sym]) * (1.0 - SLIP)
            proceeds = item["shares"] * px
            fee = proceeds * (COMMISSION + STAMP)
            cash += proceeds - fee
            trade_rows.append(
                {
                    "date": day,
                    "symbol": sym,
                    "side": "sell",
                    "shares": item["shares"],
                    "price": px,
                    "reason": reason,
                }
            )
        pos = still

    def _buy(day: pd.Timestamp, desired: list[str], entry_i: int) -> None:
        nonlocal cash, pos
        names = [s for s in desired if s in opens.columns and not pd.isna(opens.at[day, s])]
        if not names or cash <= 0:
            return
        budget = cash / len(names)
        for sym in names:
            px = float(opens.at[day, sym]) * (1.0 + SLIP)
            if px <= 0:
                continue
            shares = int(budget // (px * LOT)) * LOT
            if shares <= 0:
                continue
            cost = shares * px
            fee = cost * COMMISSION
            if cost + fee > cash:
                continue
            cash -= cost + fee
            pos.append({"sym": sym, "shares": shares, "entry_i": entry_i, "last_px": px})
            trade_rows.append(
                {
                    "date": day,
                    "symbol": sym,
                    "side": "buy",
                    "shares": shares,
                    "price": px,
                    "reason": "rotate",
                }
            )

    for di, d in enumerate(dates):
        if d < bt_start:
            continue
        if first_i is None:
            first_i = di
        held_ok = all(di - int(item["entry_i"]) >= 1 for item in pos) if pos else True
        prev = dates[di - 1] if di > 0 else None
        desired = _lookup_list(targets, prev) if prev is not None else []
        holding_syms = [str(item["sym"]) for item in pos]

        risk_off = False
        if pos and prev is not None and held_ok:
            for item in pos:
                sym = item["sym"]
                if (
                    prev not in score.index
                    or sym not in score.columns
                    or pd.isna(score.at[prev, sym])
                ):
                    continue
                if float(score.at[prev, sym]) <= float(min_score):
                    risk_off = True
                    break

        scheduled = last_reb_i is None or (di - int(last_reb_i)) >= int(hold_days)
        if risk_off and held_ok:
            _sell_all(d, "risk")
            n_risk += 1
            last_reb_i = di
        elif scheduled and held_ok and set(holding_syms) != set(desired):
            if pos:
                _sell_all(d, "rebalance")
            if desired:
                _buy(d, desired, di)
            n_reb += 1
            last_reb_i = di
        elif scheduled and last_reb_i is None:
            last_reb_i = di

        equity_rows.append(
            {
                "date": d,
                "equity": _mtm(d),
                "cash": cash,
                "holdings": ",".join(item["sym"] for item in pos),
                "target": ",".join(desired),
            }
        )

    eq_df = pd.DataFrame(equity_rows)
    tr_df = pd.DataFrame(trade_rows)
    end_eq = float(eq_df["equity"].iloc[-1]) if not eq_df.empty else float(initial_cash)
    stats = {
        "label": factor_label,
        "start": str(bt_start.date()) if hasattr(bt_start, "date") else str(bt_start),
        "end": str(eq_df["date"].iloc[-1].date()) if not eq_df.empty else "",
        "total_return_pct": (end_eq / float(initial_cash) - 1.0) * 100,
        "n_buys": int((tr_df["side"] == "buy").sum()) if not tr_df.empty else 0,
        "n_sells": int((tr_df["side"] == "sell").sum()) if not tr_df.empty else 0,
        "n_rebalance": n_reb,
        "n_risk_exits": n_risk,
        "final_equity": end_eq,
    }
    return eq_df, tr_df, stats


def load_etf_dailies(
    symbols: Sequence[str],
    *,
    start: str,
    end: str,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    from strategy.data import fetch_daily

    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = fetch_daily(str(sym), start, end, force_refresh=refresh)
        if df is not None and not df.empty:
            out[str(sym)] = df
    return out


def run_etf_combo_momentum(
    *,
    n: int | None = None,
    n2: int | None = None,
    w: float | None = None,
    top_k: int | None = None,
    hold_days: int | None = None,
    min_score: float | None = None,
    defensive: str | None = None,
    start: str | None = None,
    end: str | None = None,
    warm_start: str | None = None,
    universe: Sequence[tuple[str, str]] | None = None,
    refresh: bool = False,
    initial_cash: float | None = None,
    verbose: bool = True,
    dailies: Mapping[str, pd.DataFrame] | None = None,
):
    """宽基 ETF 组合动量轮动回测。dailies 传入时不拉行情（测试用）。"""
    from strategy.dd_alert import max_drawdown_pct
    from strategy.strategies.strategy5.portfolio import PortfolioResult

    cfg = dict(DEFAULT_PARAMS)
    if n is not None:
        cfg["n"] = int(n)
    if n2 is not None:
        cfg["n2"] = int(n2)
    if w is not None:
        cfg["w"] = float(w)
    if top_k is not None:
        cfg["top_k"] = int(top_k)
    if hold_days is not None:
        cfg["hold_days"] = int(hold_days)
    if min_score is not None:
        cfg["min_score"] = float(min_score)
    if defensive is not None:
        cfg["defensive"] = defensive
    if start:
        cfg["start"] = start
    if warm_start:
        cfg["warm_start"] = warm_start

    univ = tuple(universe or DEFAULT_UNIVERSE)
    name_map = {code: name for code, name in univ}
    symbols = [code for code, _ in univ]
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    cash = float(initial_cash if initial_cash is not None else INITIAL_CASH)

    if verbose:
        print(
            f"[因子6 ETF组合动量] n={cfg['n']}+{cfg['n2']}*w{cfg['w']:g} "
            f"top_k={cfg['top_k']} hold={cfg['hold_days']} "
            f"min_score={cfg['min_score']}  {cfg['start']}→{end}"
        )

    loaded = dict(dailies) if dailies is not None else load_etf_dailies(
        symbols,
        start=str(cfg["warm_start"]),
        end=end,
        refresh=refresh,
    )
    opens = _panel_from_dailies(loaded, "open")
    closes = _panel_from_dailies(loaded, "close")
    if closes.empty or opens.empty:
        raise RuntimeError("因子6：ETF 日线面板为空")

    score = combo_momentum_score(
        closes, n=int(cfg["n"]), n2=int(cfg["n2"]), w=float(cfg["w"])
    )
    targets = daily_targets(
        score,
        top_k=int(cfg["top_k"]),
        min_score=float(cfg["min_score"]),
        defensive=cfg.get("defensive"),
    )
    bt_start = pd.Timestamp(str(cfg["start"]))
    label = (
        f"s6/etf_combo/roc{{{cfg['n']}+{cfg['n2']}*w{cfg['w']:g},"
        f"top={cfg['top_k']},hold={cfg['hold_days']}}}"
    )
    eq_df, tr_df, stats = simulate_etf_combo_momentum(
        opens=opens,
        closes=closes,
        targets=targets,
        score=score,
        bt_start=bt_start,
        hold_days=int(cfg["hold_days"]),
        min_score=float(cfg["min_score"]),
        initial_cash=cash,
        factor_label=label,
    )
    if eq_df.empty:
        raise RuntimeError("因子6：无权益曲线")

    eq = eq_df.set_index("date")["equity"].astype(float).sort_index()
    yearly_rows: list[dict[str, Any]] = []
    years = eq.index.year
    for y, g in eq.groupby(years):
        prev = eq[eq.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else cash
        yearly_rows.append(
            {
                "year": int(y),
                "return_pct": float(g.iloc[-1] / base - 1.0) * 100,
                "max_dd_pct": max_drawdown_pct(g) * 100 if len(g) > 1 else 0.0,
            }
        )
    pick_rows = [
        {"signal_date": d, "target": ",".join(syms)}
        for d, syms in targets.items()
        if pd.Timestamp(d) >= bt_start
    ]
    return PortfolioResult(
        stats=stats,
        equity=eq_df,
        trades=tr_df,
        picks=pd.DataFrame(pick_rows),
        yearly=pd.DataFrame(yearly_rows),
        name_map=name_map,
        config=cfg,
    )


def factor6_signal(**kwargs: Any) -> dict[str, Any]:
    """供因子注册表调用：传入 closes 面板则只打分，否则跑一轮快照回测配置。"""
    closes = kwargs.get("closes")
    n = int(kwargs.get("n", DEFAULT_PARAMS["n"]))
    n2 = int(kwargs.get("n2", DEFAULT_PARAMS["n2"]))
    w = float(kwargs.get("w", DEFAULT_PARAMS["w"]))
    top_k = int(kwargs.get("top_k", DEFAULT_PARAMS["top_k"]))
    min_score = float(kwargs.get("min_score", DEFAULT_PARAMS["min_score"]))
    defensive = kwargs.get("defensive", DEFAULT_PARAMS["defensive"])
    if closes is not None:
        score = combo_momentum_score(closes, n=n, n2=n2, w=w)
        last = score.iloc[-1] if not score.empty else pd.Series(dtype=float)
        targets = daily_targets(
            score, top_k=top_k, min_score=min_score, defensive=defensive
        )
        last_day = pd.Timestamp(score.index[-1]) if not score.empty else None
        return {
            "factor_id": "factor6",
            "action": "etf_combo_momentum",
            "asof": None if last_day is None else str(last_day.date()),
            "target": targets.get(last_day, []) if last_day is not None else [],
            "scores": {str(k): (None if pd.isna(v) else float(v)) for k, v in last.items()},
        }
    return {
        "factor_id": "factor6",
        "action": "etf_combo_momentum",
        "universe": [code for code, _ in DEFAULT_UNIVERSE],
        "params": {
            "n": n,
            "n2": n2,
            "w": w,
            "top_k": top_k,
            "min_score": min_score,
            "defensive": defensive,
        },
    }


if __name__ == "__main__":
    result = run_etf_combo_momentum(verbose=True)
    print(result.stats)
    print(result.yearly)
