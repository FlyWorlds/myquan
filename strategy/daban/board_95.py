"""9.5% 触板战法 — 规则与全市场事件回测（次日竞价卖）。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import akshare as ak
import pandas as pd

from strategy.daban.rules import TICK_SIZE, ceil_to_tick, limit_up_price
from strategy.daban.universe import fetch_main_board_universe

STRATEGY_RULES = """
================================================================================
  9.5% 触板战法（Board95）— 主板 · 次日竞价出
================================================================================

【标的过滤】
  · 非 ST（含 *ST、退市）
  · 非科创板（688/689）
  · 非创业板（300/301）
  · 保留：沪市 600/601/603/605 + 深市 000/001/002

【买入 · 信号日 T】
  · 昨收 > 0
  · 当日最高价 >= ceil(昨收 × 1.095)  （触达 9.5%）
  · 非一字板：开盘价 < 涨停价 - 1tick（一字板无法买入）
  · 成交价：触发价 = ceil(昨收 × 1.095)

【卖出 · T+1】
  · 次日集合竞价/开盘价全出

【回测近似】
  · 日线：触价即成交于 9.5% 触发价；不考虑排板队列
  · 每笔独立；未扣佣金时可加 commission_bps
================================================================================
"""

ENTRY_PCT = 0.095
LIMIT_PCT = 0.10


@dataclass
class Board95ScanConfig:
    start_date: str = "20260601"
    end_date: str = "20260731"
    entry_pct: float = ENTRY_PCT
    limit_pct: float = LIMIT_PCT
    commission_bps: float = 15.0  # 买卖合计约 15bp 近似
    max_symbols: int | None = None  # 调试截断


def entry_trigger_price(prev_close: float, entry_pct: float = ENTRY_PCT) -> float:
    return ceil_to_tick(float(prev_close) * (1.0 + float(entry_pct)))


def is_yizi_board(open_px: float, prev_close: float, limit_pct: float = LIMIT_PCT) -> bool:
    """一字板：开盘即涨停价，无法买入。"""
    if prev_close <= 0:
        return True
    lu = limit_up_price(prev_close, limit_pct)
    return float(open_px) + TICK_SIZE * 0.5 + 1e-8 >= lu


def match_board95_entry(
    *,
    open_px: float,
    high_px: float,
    prev_close: float,
    entry_pct: float = ENTRY_PCT,
    limit_pct: float = LIMIT_PCT,
) -> tuple[bool, float]:
    """是否满足买入；返回 (匹配, 触发价)。"""
    if prev_close <= 0:
        return False, float("nan")
    if is_yizi_board(open_px, prev_close, limit_pct):
        return False, float("nan")
    trig = entry_trigger_price(prev_close, entry_pct)
    if float(high_px) + 1e-8 < trig:
        return False, trig
    return True, trig


def _fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        raw = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust="qfq")
    except Exception:
        return None
    if raw is None or raw.empty:
        return None
    df = raw.copy()
    if "date" not in df.columns and "日期" in df.columns:
        df = df.rename(columns={"日期": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    return df


def scan_symbol_board95(
    symbol: str,
    name: str,
    daily: pd.DataFrame,
    cfg: Board95ScanConfig,
) -> list[dict]:
    df = daily.copy()
    ts = pd.to_datetime(df["date"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    df["day"] = ts.dt.strftime("%Y-%m-%d")

    rows: list[dict] = []
    for i in range(1, len(df) - 1):
        prev_c = float(df.iloc[i - 1]["close"])
        row = df.iloc[i]
        nxt = df.iloc[i + 1]
        o, h, c = float(row["open"]), float(row["high"]), float(row["close"])
        day = str(row["day"])
        if day < pd.to_datetime(cfg.start_date).strftime("%Y-%m-%d"):
            continue
        if day > pd.to_datetime(cfg.end_date).strftime("%Y-%m-%d"):
            continue

        ok, trig = match_board95_entry(
            open_px=o,
            high_px=h,
            prev_close=prev_c,
            entry_pct=cfg.entry_pct,
            limit_pct=cfg.limit_pct,
        )
        if not ok:
            continue

        buy = trig
        sell = float(nxt["open"])
        gross = (sell / buy - 1.0) * 100.0
        net = gross - cfg.commission_bps / 100.0
        rows.append(
            {
                "signal_day": day,
                "exit_day": str(nxt["day"]),
                "symbol": symbol,
                "name": name,
                "prev_close": prev_c,
                "open": o,
                "high": h,
                "close": c,
                "entry_px": buy,
                "exit_px": sell,
                "gross_pct": gross,
                "net_pct": net,
                "yizi": False,
            }
        )
    return rows


def run_board95_scan(cfg: Board95ScanConfig) -> pd.DataFrame:
    # 多取几天用于 T+1
    start_pad = (
        pd.to_datetime(cfg.start_date) - pd.Timedelta(days=10)
    ).strftime("%Y%m%d")
    end_pad = (
        pd.to_datetime(cfg.end_date) + pd.Timedelta(days=10)
    ).strftime("%Y%m%d")

    universe = fetch_main_board_universe()
    if cfg.max_symbols:
        universe = universe.head(int(cfg.max_symbols))

    all_rows: list[dict] = []
    total = len(universe)
    for idx, u in universe.iterrows():
        sym, name = str(u["symbol"]), str(u["name"])
        daily = _fetch_daily(sym, start_pad, end_pad)
        if daily is None or len(daily) < 3:
            continue
        all_rows.extend(scan_symbol_board95(sym, name, daily, cfg))
        if (idx + 1) % 200 == 0:
            print(f"  进度 {idx+1}/{total}  已捕获信号 {len(all_rows)}", flush=True)

    return pd.DataFrame(all_rows)


def print_board95_report(cfg: Board95ScanConfig, trades: pd.DataFrame) -> None:
    print("=== 9.5% 触板战法 · 主板全市场 ===")
    print(f"区间: {cfg.start_date} ~ {cfg.end_date}")
    print(STRATEGY_RULES.split("【标的过滤】")[1].split("======")[0].strip())
    print(f"触发价: 昨收×{1+cfg.entry_pct:.3f} | 一字板不买 | 次日开盘卖")
    print()

    if trades.empty:
        print("(无成交样本)")
        return

    n = len(trades)
    win = int((trades["net_pct"] > 0).sum())
    print(f"信号成交: {n} 笔  |  涉及 {trades['symbol'].nunique()} 只")
    print(
        f"单笔净收益: 均{trades['net_pct'].mean():+.2f}%  "
        f"中位{trades['net_pct'].median():+.2f}%  "
        f"最大{trades['net_pct'].max():+.2f}%  最小{trades['net_pct'].min():+.2f}%"
    )
    print(f"胜率: {win}/{n} ({win/n*100:.1f}%)")
    print(f"净收益合计(简单加总): {trades['net_pct'].sum():+.2f}%")
    print()

    by_day = trades.groupby("signal_day")["net_pct"].agg(["count", "mean", "sum"])
    print("【按信号日汇总】")
    print(f"  {'日期':<12} {'笔数':>5} {'均净%':>8} {'合计%':>8}")
    for day, r in by_day.iterrows():
        print(f"  {day:<12} {int(r['count']):>5} {r['mean']:>+8.2f} {r['sum']:>+8.2f}")
    print()

    print("【明细 Top 20（按净收益）】")
    print(
        f"  {'信号日':<12} {'代码':<10} {'名称':<8} {'买':>7} {'次日开':>7} {'净%':>7}"
    )
    top = trades.sort_values("net_pct", ascending=False).head(20)
    for _, r in top.iterrows():
        print(
            f"  {r['signal_day']:<12} {r['symbol']:<10} {str(r['name'])[:8]:<8} "
            f"{r['entry_px']:>7.2f} {r['exit_px']:>7.2f} {r['net_pct']:>+7.2f}"
        )
    print()
    worst = trades.sort_values("net_pct").head(10)
    print("【明细 Bottom 10】")
    for _, r in worst.iterrows():
        print(
            f"  {r['signal_day']:<12} {r['symbol']:<10} {str(r['name'])[:8]:<8} "
            f"{r['entry_px']:>7.2f} {r['exit_px']:>7.2f} {r['net_pct']:>+7.2f}"
        )
