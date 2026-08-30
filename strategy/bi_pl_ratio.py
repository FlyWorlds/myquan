"""缠论日线笔 vs 因子1 盈亏归因（卖点平移到买入笔）。

研究工具：用 CZSC 日线笔切段，把策略一·因子1（开盘突破）闭环交易
按「买入所在笔」记账；若卖出落在另一笔，卖价差价仍记入买入笔。
费用口径见 ``strategy.costs``。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from strategy.costs import (
    COST_ROUND_TRIP,
    ENGINE_COMMISSION_RATE,
    SLIPPAGE_VALUE,
    STAMP_TAX_RATE,
    fee_rules_text,
    stamp_tax_for_code,
)
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    entry_trigger_price,
    limit_down_state,
    prev_day_allows_entry,
    should_block_entry_by_yang,
    stop_trigger_price,
)

TICK_DEFAULT = 0.01


@dataclass(frozen=True)
class BiPlRatioResult:
    """单标的笔归因结果。"""

    symbol: str
    symbol_name: str
    window: str
    entry_pct: float
    fee_text: str
    cost_round_trip: float
    summary: dict[str, Any]
    bis: pd.DataFrame
    trades: pd.DataFrame
    bi_vs_factor1: pd.DataFrame
    year_stats: pd.DataFrame = field(default_factory=pd.DataFrame)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "window": self.window,
            "entry_pct": self.entry_pct,
            "fee_text": self.fee_text,
            "cost_round_trip": self.cost_round_trip,
            "summary": self.summary,
        }


def net_round_trip_return(
    buy_px: float,
    sell_px: float,
    *,
    commission_rate: float = ENGINE_COMMISSION_RATE,
    stamp_tax_rate: float = STAMP_TAX_RATE,
    slippage_value: float = SLIPPAGE_VALUE,
) -> float:
    """买入加滑点+佣金杂费；卖出减滑点，扣佣金杂费+印花。"""
    buy_eff = float(buy_px) * (1.0 + float(slippage_value))
    sell_eff = float(sell_px) * (1.0 - float(slippage_value))
    cash_out = buy_eff * (1.0 + float(commission_rate))
    cash_in = sell_eff * (1.0 - float(commission_rate) - float(stamp_tax_rate))
    if cash_out <= 0:
        return 0.0
    return cash_in / cash_out - 1.0


def _normalize_ts(x: Any) -> pd.Timestamp:
    t = pd.Timestamp(str(x))
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return t.normalize()


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    if "date" not in df.columns:
        raise ValueError("日线缺少 date 列")
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    need = {"open", "high", "low", "close"}
    missing = need.difference(df.columns)
    if missing:
        raise ValueError(f"日线缺少列: {sorted(missing)}")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    return df.sort_values("date").reset_index(drop=True)


def build_bis(daily: pd.DataFrame, *, symbol: str, max_bi_num: int = 500) -> pd.DataFrame:
    """CZSC 日线笔列表。"""
    from czsc import CZSC, Direction, format_standard_kline

    df = _prepare_daily(daily)
    code = str(symbol).lower().replace("sh", "").replace("sz", "")
    ts_code = f"{code}.SH" if str(symbol).lower().startswith("sh") or code.startswith(
        ("5", "6")
    ) else f"{code}.SZ"
    kdf = pd.DataFrame(
        {
            "dt": df["date"],
            "symbol": ts_code,
            "open": df["open"],
            "close": df["close"],
            "high": df["high"],
            "low": df["low"],
            "vol": df["volume"],
            "amount": df["close"] * df["volume"],
        }
    )
    bars = format_standard_kline(kdf, freq="日线")
    c = CZSC(bars, max_bi_num=int(max_bi_num))
    rows: list[dict[str, Any]] = []
    for i, bi in enumerate(c.bi_list):
        pa, pb = float(bi.fx_a.fx), float(bi.fx_b.fx)
        rows.append(
            {
                "bi_id": i + 1,
                "direction": "up" if bi.direction == Direction.Up else "down",
                "sdt": _normalize_ts(bi.sdt),
                "edt": _normalize_ts(bi.edt),
                "fx_a": pa,
                "fx_b": pb,
                "high": float(bi.high),
                "low": float(bi.low),
                "length": int(bi.length),
                "struct_ret": (pb - pa) / pa if pa else 0.0,
                "snr": float(bi.SNR) if bi.SNR is not None else np.nan,
            }
        )
    return pd.DataFrame(rows)


def replay_factor1_trades(
    daily: pd.DataFrame,
    *,
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float | None = None,
    tick: float = TICK_DEFAULT,
    stamp_tax_rate: float = STAMP_TAX_RATE,
    commission_rate: float = ENGINE_COMMISSION_RATE,
    slippage_value: float = SLIPPAGE_VALUE,
    prev_entry_mode: str = "yin_or_small_yang",
    ban_double_yang: bool = DEFAULT_BAN_DOUBLE_YANG,
    ban_single_yang: bool = DEFAULT_BAN_SINGLE_YANG,
    double_yang_combined_min_pct: float = DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    double_yang_combined_mode: str = DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    limit_down_pct: float = 0.10,
) -> tuple[pd.DataFrame, bool]:
    """重放因子1闭环；返回 (trades_df, still_holding)。"""
    df = _prepare_daily(daily)
    stop_pct = float(entry_pct if stop_pct is None else stop_pct)
    trades: list[dict[str, Any]] = []
    holding = False
    buy_day: pd.Timestamp | None = None
    buy_px: float | None = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        prev2 = df.iloc[i - 2] if i >= 2 else None
        day = pd.Timestamp(row["date"]).normalize()
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c_px = float(row["close"])
        if o <= 0:
            continue
        buy_trigger = entry_trigger_price(o, entry_pct=entry_pct, tick=tick)
        stop_trigger = stop_trigger_price(o, stop_pct=stop_pct, tick=tick)
        allows = prev_day_allows_entry(
            float(prev["open"]),
            float(prev["close"]),
            prev_small_yang_pct=entry_pct,
            prev_entry_mode=prev_entry_mode,
        )
        blocked = False
        if prev2 is not None:
            blocked = should_block_entry_by_yang(
                float(prev2["open"]),
                float(prev2["close"]),
                float(prev["open"]),
                float(prev["close"]),
                tick=tick,
                ban_double_yang=ban_double_yang,
                ban_single_yang=ban_single_yang,
                double_yang_combined_min_pct=double_yang_combined_min_pct,
                double_yang_combined_mode=double_yang_combined_mode,
            )
        if holding:
            if buy_day is not None and day == buy_day:
                continue
            if l <= stop_trigger + 1e-12:
                limit_state = limit_down_state(
                    prev_close=float(prev["close"]),
                    open_px=o,
                    high_px=h,
                    low_px=l,
                    close_px=c_px,
                    limit_down_pct=limit_down_pct,
                    tick=tick,
                )
                if bool(limit_state["locked"]):
                    continue
                assert buy_px is not None
                sell_px = float(
                    limit_state["limit_px"] if limit_state["opened"] else stop_trigger
                )
                gross = sell_px / buy_px - 1.0
                net = net_round_trip_return(
                    buy_px,
                    sell_px,
                    commission_rate=commission_rate,
                    stamp_tax_rate=stamp_tax_rate,
                    slippage_value=slippage_value,
                )
                trades.append(
                    {
                        "buy_date": buy_day,
                        "buy_px": buy_px,
                        "sell_date": day,
                        "sell_px": sell_px,
                        "ret_gross": gross,
                        "ret": net,
                    }
                )
                holding = False
                buy_day = None
                buy_px = None
                continue
            continue
        if allows and (not blocked) and (h + 1e-12 >= buy_trigger):
            holding = True
            buy_day = day
            buy_px = float(buy_trigger)

    return pd.DataFrame(trades), holding


def _find_bi_for_buy(bi_df: pd.DataFrame, day: pd.Timestamp) -> int | None:
    day = pd.Timestamp(day).normalize()
    if bi_df.empty:
        return None
    for r in bi_df.itertuples():
        if r.sdt == day:
            return int(r.bi_id)
    hits = bi_df[(bi_df.sdt <= day) & (bi_df.edt >= day)]
    if hits.empty:
        if day < bi_df.sdt.min():
            return None
        if day > bi_df.edt.max():
            return int(bi_df.bi_id.iloc[-1])
        return None
    return int(hits.bi_id.iloc[-1])


def _find_bi_for_sell(bi_df: pd.DataFrame, day: pd.Timestamp) -> int | None:
    day = pd.Timestamp(day).normalize()
    if bi_df.empty:
        return None
    for r in bi_df.itertuples():
        if r.edt == day:
            return int(r.bi_id)
    hits = bi_df[(bi_df.sdt <= day) & (bi_df.edt >= day)]
    if hits.empty:
        if day > bi_df.edt.max():
            return int(bi_df.bi_id.iloc[-1])
        return None
    return int(hits.bi_id.iloc[0])


def attribute_trades_to_bis(
    trades: pd.DataFrame, bi_df: pd.DataFrame
) -> pd.DataFrame:
    """卖点跨笔时，整笔净收益记入买入笔（卖点价格平移）。"""
    if trades is None or trades.empty:
        return pd.DataFrame(
            columns=[
                "buy_date",
                "buy_px",
                "sell_date",
                "sell_px",
                "ret_gross",
                "ret",
                "buy_bi",
                "sell_bi",
                "cross_bi",
                "attrib_bi",
                "attrib_ret",
            ]
        )
    rows: list[dict[str, Any]] = []
    for t in trades.to_dict(orient="records"):
        bid = _find_bi_for_buy(bi_df, t["buy_date"])
        sid = _find_bi_for_sell(bi_df, t["sell_date"])
        cross = bid is not None and sid is not None and bid != sid
        rows.append(
            {
                **t,
                "buy_bi": bid,
                "sell_bi": sid,
                "cross_bi": cross,
                "attrib_bi": bid,
                "attrib_ret": float(t["ret"]),
            }
        )
    return pd.DataFrame(rows)


def aggregate_bi_vs_factor1(bi_df: pd.DataFrame, trades_attrib: pd.DataFrame) -> pd.DataFrame:
    agg: list[dict[str, Any]] = []
    atr = trades_attrib if trades_attrib is not None else pd.DataFrame()
    for r in bi_df.itertuples():
        sub = atr[atr["attrib_bi"] == r.bi_id] if len(atr) else atr
        n = len(sub)
        sum_ret = float(sub["attrib_ret"].sum()) if n else 0.0
        compound = (
            float(np.prod(1.0 + sub["attrib_ret"].to_numpy()) - 1.0) if n else 0.0
        )
        if r.direction == "up":
            rangli = r.struct_ret - compound
            fangshou = np.nan
        else:
            rangli = np.nan
            fangshou = compound - r.struct_ret
        agg.append(
            {
                "bi_id": r.bi_id,
                "direction": r.direction,
                "sdt": pd.Timestamp(r.sdt).date(),
                "edt": pd.Timestamp(r.edt).date(),
                "fx_a": round(float(r.fx_a), 3),
                "fx_b": round(float(r.fx_b), 3),
                "struct_ret_pct": round(float(r.struct_ret) * 100, 2),
                "n_trades": n,
                "factor1_sum_pct": round(sum_ret * 100, 2),
                "factor1_compound_pct": round(compound * 100, 2),
                "n_cross_sell": int(sub["cross_bi"].sum()) if n else 0,
                "rangli_pct": None if rangli != rangli else round(float(rangli) * 100, 2),
                "fangshou_pct": None
                if fangshou != fangshou
                else round(float(fangshou) * 100, 2),
            }
        )
    return pd.DataFrame(agg)


def _pl_stats(returns: pd.Series) -> dict[str, Any]:
    if returns is None or len(returns) == 0:
        return {
            "n": 0,
            "win_rate": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "pl_ratio": None,
            "compound_pct": 0.0,
            "sum_pct": 0.0,
        }
    r = pd.to_numeric(returns, errors="coerce").dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    if avg_loss < 0:
        pl_ratio = avg_win / abs(avg_loss)
    elif avg_win > 0:
        pl_ratio = float("inf")
    else:
        pl_ratio = 0.0
    return {
        "n": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "avg_win_pct": round(avg_win * 100, 3),
        "avg_loss_pct": round(avg_loss * 100, 3),
        "pl_ratio": round(pl_ratio, 3) if np.isfinite(pl_ratio) else None,
        "compound_pct": round(float(np.prod(1.0 + r.to_numpy()) - 1.0) * 100, 2),
        "sum_pct": round(float(r.sum()) * 100, 2),
    }


def year_pl_stats(trades_attrib: pd.DataFrame) -> pd.DataFrame:
    """按卖出年份、买入年份统计盈亏比。"""
    if trades_attrib is None or trades_attrib.empty:
        return pd.DataFrame()
    atr = trades_attrib.copy()
    atr["buy_date"] = pd.to_datetime(atr["buy_date"])
    atr["sell_date"] = pd.to_datetime(atr["sell_date"])
    rows = []
    for year in sorted(set(atr["sell_date"].dt.year) | set(atr["buy_date"].dt.year)):
        sell_mask = atr["sell_date"].dt.year == year
        both_mask = (atr["buy_date"].dt.year == year) & (atr["sell_date"].dt.year == year)
        for scope, mask in (("sell_year", sell_mask), ("buy_and_sell_year", both_mask)):
            st = _pl_stats(atr.loc[mask, "attrib_ret"])
            rows.append({"year": int(year), "scope": scope, **st})
    return pd.DataFrame(rows)


def analyze_bi_pl_ratio(
    daily: pd.DataFrame,
    *,
    symbol: str,
    symbol_name: str = "",
    entry_pct: float = DEFAULT_PCT,
    stop_pct: float | None = None,
    tick: float = TICK_DEFAULT,
    max_bi_num: int = 500,
    out_dir: str | Path | None = None,
) -> BiPlRatioResult:
    """主入口：日线 → 笔 → 因子1费用后归因 → 盈亏比/让利/防守。"""
    df = _prepare_daily(daily)
    stamp = stamp_tax_for_code(symbol)
    bi_df = build_bis(df, symbol=symbol, max_bi_num=max_bi_num)
    trades, still_holding = replay_factor1_trades(
        df,
        entry_pct=entry_pct,
        stop_pct=stop_pct,
        tick=tick,
        stamp_tax_rate=stamp,
    )
    atr = attribute_trades_to_bis(trades, bi_df)
    agg = aggregate_bi_vs_factor1(bi_df, atr)
    years = year_pl_stats(atr)

    closed = atr["attrib_ret"] if len(atr) else pd.Series(dtype=float)
    gross = atr["ret_gross"] if len(atr) else pd.Series(dtype=float)
    overall = _pl_stats(closed)
    up = agg[agg.direction == "up"] if len(agg) else agg
    dn = agg[agg.direction == "down"] if len(agg) else agg

    window = f"{df.date.min().date()} ~ {df.date.max().date()}"
    summary = {
        "symbol": symbol,
        "symbol_name": symbol_name or symbol,
        "level": "日线·笔（CZSC；无线段则按笔）",
        "window": window,
        "entry_pct": float(entry_pct),
        "fee": fee_rules_text(etf=stamp <= 0),
        "cost_round_trip": float(COST_ROUND_TRIP if stamp > 0 else COST_ROUND_TRIP - STAMP_TAX_RATE),
        "n_bis": int(len(bi_df)),
        "n_up": int((bi_df.direction == "up").sum()) if len(bi_df) else 0,
        "n_down": int((bi_df.direction == "down").sum()) if len(bi_df) else 0,
        "n_trades": int(overall["n"]),
        "n_cross_bi_trades": int(atr["cross_bi"].sum()) if len(atr) else 0,
        "still_holding": bool(still_holding),
        "win_rate_net": overall["win_rate"],
        "pl_ratio": overall["pl_ratio"],
        "avg_win_pct": overall["avg_win_pct"],
        "avg_loss_pct": overall["avg_loss_pct"],
        "factor1_compound_net_pct": overall["compound_pct"],
        "factor1_compound_gross_pct": _pl_stats(gross)["compound_pct"],
        "bi_up_mean_struct_pct": round(float(up.struct_ret_pct.mean()), 2)
        if len(up)
        else None,
        "bi_up_mean_factor1_net_pct": round(float(up.factor1_compound_pct.mean()), 2)
        if len(up)
        else None,
        "bi_up_mean_rangli_pct": round(float(up.rangli_pct.dropna().mean()), 2)
        if len(up) and up.rangli_pct.notna().any()
        else None,
        "bi_down_mean_struct_pct": round(float(dn.struct_ret_pct.mean()), 2)
        if len(dn)
        else None,
        "bi_down_mean_factor1_net_pct": round(float(dn.factor1_compound_pct.mean()), 2)
        if len(dn)
        else None,
        "bi_down_mean_fangshou_pct": round(float(dn.fangshou_pct.dropna().mean()), 2)
        if len(dn) and dn.fangshou_pct.notna().any()
        else None,
    }

    result = BiPlRatioResult(
        symbol=symbol,
        symbol_name=symbol_name or symbol,
        window=window,
        entry_pct=float(entry_pct),
        fee_text=fee_rules_text(etf=stamp <= 0),
        cost_round_trip=float(summary["cost_round_trip"]),
        summary=summary,
        bis=bi_df,
        trades=atr,
        bi_vs_factor1=agg,
        year_stats=years,
    )

    if out_dir is not None:
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        bi_df.to_csv(path / "bis.csv", index=False)
        atr.to_csv(path / "trades_attrib_net.csv", index=False)
        agg.to_csv(path / "bi_vs_factor1_net.csv", index=False)
        years.to_csv(path / "year_pl_stats.csv", index=False)
        pd.Series(summary).to_json(path / "summary_net.json", force_ascii=False)

    return result


def run_bi_pl_ratio(
    cfg: Any = None,
    *,
    symbol: str | None = None,
    symbol_name: str | None = None,
    start: str | None = None,
    end: str | None = None,
    entry_pct: float | None = None,
    force_daily_refresh: bool = False,
    out_dir: str | Path | None = None,
    daily: pd.DataFrame | None = None,
    verbose: bool = True,
) -> BiPlRatioResult:
    """策略七运行入口：读配置/日线 → 输出笔盈亏比报告。"""
    import datetime as dt

    from strategy.config import TIANTONG
    from strategy.data import fetch_daily

    base = cfg if cfg is not None else TIANTONG
    sym = str(symbol or getattr(base, "symbol", "sh600330"))
    name = str(
        symbol_name
        or getattr(base, "symbol_name", "")
        or sym
    )
    sdt = str(start or getattr(base, "start_date", "20200101"))
    edt = str(end or dt.date.today().strftime("%Y%m%d"))
    pct = float(
        entry_pct
        if entry_pct is not None
        else getattr(base, "threshold_pct", DEFAULT_PCT)
    )
    cache = getattr(base, "daily_cache", None)

    if daily is None:
        daily = fetch_daily(
            sym,
            sdt,
            edt,
            cache_path=cache,
            force_refresh=force_daily_refresh,
        )

    if out_dir is None:
        out_dir = Path("data_cache") / "strategy7_bi_pl" / sym.lower()

    result = analyze_bi_pl_ratio(
        daily,
        symbol=sym,
        symbol_name=name,
        entry_pct=pct,
        out_dir=out_dir,
    )
    if verbose:
        s = result.summary
        print(f"\n========== {result.symbol_name} · 缠论笔算盈亏比 ==========")
        print(f"窗口 {s['window']}  阈值±{pct*100:.1f}%  {result.fee_text}")
        print(
            f"笔 {s['n_bis']} (上{s['n_up']}/下{s['n_down']})  "
            f"因子1闭环 {s['n_trades']}  跨笔卖出 {s['n_cross_bi_trades']}"
        )
        print(
            f"费用后胜率 {s['win_rate_net']}  "
            f"均盈 {s['avg_win_pct']}% / 均亏 {s['avg_loss_pct']}%  "
            f"盈亏比 {s['pl_ratio']}"
        )
        print(
            f"向上笔均结构 {s['bi_up_mean_struct_pct']}% / "
            f"因子1 {s['bi_up_mean_factor1_net_pct']}% / 让利 {s['bi_up_mean_rangli_pct']}%"
        )
        print(
            f"向下笔均结构 {s['bi_down_mean_struct_pct']}% / "
            f"因子1 {s['bi_down_mean_factor1_net_pct']}% / 防守 {s['bi_down_mean_fangshou_pct']}%"
        )
        if len(result.year_stats):
            y = result.year_stats
            y2026 = y[(y["year"] == 2026) & (y["scope"] == "buy_and_sell_year")]
            if len(y2026):
                row = y2026.iloc[0]
                print(
                    f"2026(买卖均在当年) 盈亏比 {row['pl_ratio']}  "
                    f"胜率 {row['win_rate']}  n={row['n']}"
                )
        print(f"明细 → {out_dir}")
    return result


__all__ = [
    "BiPlRatioResult",
    "analyze_bi_pl_ratio",
    "attribute_trades_to_bis",
    "aggregate_bi_vs_factor1",
    "build_bis",
    "net_round_trip_return",
    "replay_factor1_trades",
    "run_bi_pl_ratio",
    "year_pl_stats",
]
