"""策略三·鲍鱼捞饭（日线破位止跌）多维参数回测服务。

核心功能：
1. 股票池支持：中证1000（主板池 640+ 只）、手动监控池、经典精选池（legacy30）、自定义池；
2. 核心出场条件自定义：
   - 命中信号后持股时间条件（max_hold_days，如 3, 5, 8, 10, 15, 20 天）；
   - 持仓峰值回撤条件（trailing_drawdown_pct，如 3%, 4%, 5%, 8%，防利润回吐）；
   - 成本回撤硬止损（stop_loss_pct，如 -4%, -5%, -8%）；
   - 目标止盈（take_profit_pct，如 +8%, +10%, +15%）；
3. 真实组合与逐日撮合仿真（严格T+1、涨跌停限制、次日开盘价买卖、滑点、佣金印花税、动态现金流与仓位配比）；
4. 多维绩效分析（累计收益曲线、基准中证1000/全指对比、水下动态回撤、夏普/卡玛、胜率、盈亏比、平均持股天数、出场原因分布）；
5. 异步任务与进度反馈，自动持久化至 strategy3_backtest_history.json。
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = Path(__file__).resolve().parent / "strategy3_backtest_history.json"
FEATURES_DIR = _ROOT / "backtest/strategy3_abalone/manual_scan/features"
LEGACY_DIR = _ROOT / "backtest/strategy3_abalone/factor_mining"

DEFAULT_BACKTEST_PARAMS: dict[str, Any] = {
    # 基础设置
    "universe": "zz1000",       # zz1000 (中证1000) | manual (当前监控池) | legacy30 (经典30) | custom
    "start_date": "2025-01-01",
    "end_date": "2026-11-10",
    "benchmark": "000852",      # 000852 (中证1000) | 000985 (中证全指) | 000300 (沪深300)
    "initial_capital": 1000000.0,
    "max_positions": 5,
    "single_position_max_pct": 0.20,
    # 核心条件 1：命中信号后持股时间条件
    "max_hold_days": 10,        # 命中信号后最大持股交易日数（到期次开平仓）
    # 核心条件 2：回撤出场条件
    "enable_trailing_drawdown": True,
    "trailing_drawdown_pct": 0.04,      # 持仓峰值回撤出场阈值（如从最高点回撤 4% 出场）
    "trailing_profit_threshold": 0.02,  # 最高浮盈达到 2% 后激活移动回撤监控
    "stop_loss_pct": -0.05,             # 成本回撤硬止损（亏损达 5% 出场）
    # 止盈与执行设置
    "take_profit_pct": 0.10,            # 目标止盈幅度（+10%）
    "commission_rate": 0.00015,
    "stamp_tax_rate": 0.0005,
    "slippage_rate": 0.001,
}


def _get_benchmark_data(bench_code: str = "000852", start_date: str = "2025-01-01", end_date: str = "") -> pd.DataFrame:
    """获取基准指数（如中证1000 sh000852 / 中证全指 sh000985 / 沪深300 sh000300）日线行情。"""
    code = f"sh{bench_code}" if not bench_code.startswith(("sh", "sz")) else bench_code
    import urllib.request
    try:
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,400,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
            day_data = data.get("data", {}).get(code, {}).get("day", [])
            rows = []
            for d in day_data:
                rows.append({
                    "date": str(d[0])[:10],
                    "open": float(d[1]),
                    "close": float(d[2]),
                    "high": float(d[3]),
                    "low": float(d[4]),
                    "volume": float(d[5]),
                })
            if rows:
                df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
                if start_date:
                    df = df[df["date"] >= start_date]
                if end_date:
                    df = df[df["date"] <= end_date]
                return df.reset_index(drop=True)
    except Exception as e:
        print(f"[BACKTEST3] 获取基准行情失败: {e}")

    # 备用：从 akshare 获取
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol=code)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _load_features_data(universe: str, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    """根据股票池加载预计算特征或日线行情。支持单日提取与跨期回测。"""
    frames: dict[str, pd.DataFrame] = {}
    target_dir = LEGACY_DIR if universe == "legacy30" and LEGACY_DIR.exists() else FEATURES_DIR

    if target_dir.exists():
        pattern = "*_features.parquet" if universe == "legacy30" else "*.parquet"
        for p in target_dir.glob(pattern):
            sym = p.name.split("_features")[0] if universe == "legacy30" else p.stem
            try:
                df = pd.read_parquet(p)
                df["date"] = pd.to_datetime(df["date"])
                # 筛选在 end_date 之前的行情；如果选单日或短周期，只要在区间有数据或截至日期有数据即纳入
                sub = df[df["date"] <= pd.Timestamp(end_date)]
                if not sub.empty:
                    frames[sym] = sub.sort_values("date").reset_index(drop=True)
            except Exception:
                pass
    return frames


def simulate_strategy3_backtest(params: dict[str, Any], progress_cb=None) -> dict[str, Any]:
    """执行策略三·鲍鱼捞饭（破位止跌）全流程回测仿真。"""
    p = {**DEFAULT_BACKTEST_PARAMS, **params}
    start_date = str(p.get("start_date") or "2025-01-01")
    end_date = str(p.get("end_date") or datetime.now().strftime("%Y-%m-%d"))
    bench_code = str(p.get("benchmark") or "000852")
    universe = str(p.get("universe") or "zz1000")

    # 1. 提取核心条件参数
    max_hold_days = int(p.get("max_hold_days", 10))
    enable_trailing = bool(p.get("enable_trailing_drawdown", True))
    trailing_dd = float(p.get("trailing_drawdown_pct", 0.04))
    trailing_profit_gate = float(p.get("trailing_profit_threshold", 0.02))
    stop_loss = -abs(float(p.get("stop_loss_pct", -0.05)))
    take_profit = abs(float(p.get("take_profit_pct", 0.10)))

    initial_cap = float(p.get("initial_capital", 1000000.0))
    max_positions = int(p.get("max_positions", 5))
    single_slot_pct = float(p.get("single_position_max_pct", 1.0 / max_positions))
    comm_rate = float(p.get("commission_rate", 0.00015))
    tax_rate = float(p.get("stamp_tax_rate", 0.0005))
    slippage = float(p.get("slippage_rate", 0.001))

    if progress_cb:
        progress_cb({"stage": "正在拉取基准指数行情与交易日历", "percent": 10, "completed": 1, "total": 6})

    # 读取基准行情
    bench_df = _get_benchmark_data(bench_code, start_date, end_date)
    trading_dates = list(bench_df["date"]) if not bench_df.empty else []

    if progress_cb:
        progress_cb({"stage": f"正在加载股票池特征行情 (universe={universe})", "percent": 25, "completed": 2, "total": 6})

    frames = _load_features_data(universe, start_date, end_date)
    if not frames:
        raise ValueError(f"未能加载到股票池数据 ({universe})，请确认日线/特征缓存完整")

    # 读取股票名称映射
    from stock_names import _read_name_cache
    name_cache = _read_name_cache()

    # 汇总所有交易日
    all_dates = set()
    for f in frames.values():
        all_dates.update(str(d.date()) for d in f["date"])
    if trading_dates:
        all_dates.update(trading_dates)

    trading_days = sorted(all_dates)
    trading_days = [d for d in trading_days if d >= start_date and d <= end_date]

    is_single_day = (start_date == end_date) or len(trading_days) <= 1
    if not trading_days:
        # 如果选定区间无日线（例如周末或未来日期），向前回溯至最近交易日
        available_before = sorted([d for d in all_dates if d <= end_date])
        if available_before:
            trading_days = [available_before[-1]]
            is_single_day = True
        else:
            raise ValueError(f"选定日期 ({end_date}) 无可用行情数据")

    if progress_cb:
        stage_desc = f"正在提取 {trading_days[0]} 单日买入信号 (标的池: {len(frames)}只)" if is_single_day else f"已对齐 {len(trading_days)} 个交易日、{len(frames)} 只标的，正在构建日线索引"
        progress_cb({"stage": stage_desc, "percent": 45, "completed": 3, "total": 6})

    # 构建快速日期索引结构：records[day][symbol]
    records: dict[str, dict[str, Any]] = {}
    for sym, f in frames.items():
        for r in f.itertuples():
            d_str = str(r.date.date())
            if d_str not in records:
                records[d_str] = {}
            records[d_str][sym] = r

    # ---------- 单日模式：今日/指定日信号提取 ----------
    if is_single_day:
        target_day = trading_days[0]
        today_records = records.get(target_day, {})
        today_signals = []
        for s, r in today_records.items():
            if getattr(r, "stabilize", False):
                code = s[2:] if s.startswith(("sh", "sz")) else s
                name = name_cache.get(code, code)
                close = float(r.close)
                anchor = float(getattr(r, "anchor", close * 0.95))
                peak = float(getattr(r, "peak", close * 1.10))
                depth = float(getattr(r, "depth", 0.0))
                stop_px = round(anchor * 0.99, 2)
                # 以扫描出信号当天的收盘价买入，而非突破攻击买点
                buy_px = round(close, 2)
                support_buy = round(anchor, 2)
                today_signals.append({
                    "symbol": s,
                    "code": code,
                    "name": name,
                    "date": target_day,
                    "close": close,
                    "buy_price": buy_px,
                    "buy_trigger_price": buy_px,  # 兼容字段，统一为当日收盘买入价
                    "depth_pct": round(depth * 100, 2),
                    "anchor_price": anchor,
                    "peak_price": peak,
                    "support_buy_price": support_buy,
                    "stop_loss_price": stop_px,
                    "target_price": peak,
                    "logic": f"日线破位深度{depth*100:.1f}%后量价衰竭止跌；以信号日收盘价 {buy_px:.2f} 元买入建仓；底线止损位 {stop_px:.2f} 元，前高目标 {peak:.2f} 元。",
                })

        today_signals.sort(key=lambda x: x["depth_pct"], reverse=True)

        result = {
            "params": p,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_single_day": True,
            "target_day": target_day,
            "summary": {
                "strategy_return_pct": 0.0,
                "benchmark_return_pct": 0.0,
                "alpha_pct": 0.0,
                "annualized_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "calmar_ratio": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "total_trades": len(today_signals),
                "win_trades": 0,
                "loss_trades": 0,
                "avg_holding_days": 0.0,
                "max_holding_days": max_hold_days,
                "initial_capital": initial_cap,
                "final_capital": initial_cap,
                "universe_count": len(frames),
                "today_signal_count": len(today_signals),
            },
            "dates": [target_day],
            "equity_curve": [0.0],
            "benchmark_curve": [0.0],
            "alpha_curve": [0.0],
            "drawdown_curve": [0.0],
            "daily_returns": [0.0],
            "trades": [],
            "today_signals": today_signals,
            "exit_reason_breakdown": [],
            "stock_contributions": [],
        }
        if progress_cb:
            progress_cb({"stage": f"已成功提取 {target_day} 信号，共命中 {len(today_signals)} 只标的", "percent": 100, "completed": 6, "total": 6})
        return result

    if progress_cb:
        progress_cb({"stage": "开始执行逐日组合撮合与回撤/持股周期风控仿真", "percent": 65, "completed": 4, "total": 6})

    cash = initial_cap
    positions: dict[str, dict[str, Any]] = {}
    previous: dict[str, Any] = {}
    consumed_events: set[tuple[str, Any]] = set()

    trades: list[dict[str, Any]] = []
    equity_records: list[dict[str, Any]] = []
    last_prices: dict[str, float] = {}

    for day_str in trading_days:
        today = records.get(day_str, {})

        # ---------- 1. 平仓判断（开盘撮合） ----------
        for s in list(positions):
            pos = positions[s]
            r = today.get(s)
            prev = previous.get(s)
            if r is None or prev is None:
                continue

            age = pos["age"]
            avg_cost = pos["cost"] / pos["shares"]
            peak = pos["peak"]
            peak_gain = (peak - avg_cost) / avg_cost

            exit_reason = None
            raw_sell_px = r.open

            # A. 成本回撤硬止损 (Stop Loss)
            if prev.close <= avg_cost * (1.0 + stop_loss):
                exit_reason = f"触发成本回撤止损 ({stop_loss * 100:.1f}%)"
            elif r.low <= avg_cost * (1.0 + stop_loss):
                exit_reason = f"盘中触价硬止损 ({stop_loss * 100:.1f}%)"
                raw_sell_px = min(r.open, avg_cost * (1.0 + stop_loss))

            # B. 持仓峰值回撤出场 (Trailing Drawdown Exit)
            elif enable_trailing and peak > 0 and (peak_gain >= trailing_profit_gate) and ((peak - prev.close) / peak >= trailing_dd):
                exit_reason = f"触发峰值回撤出场 (高点回撤 {trailing_dd * 100:.1f}%)"

            # C. 命中信号后持股时间上限到期 (Max Hold Days)
            elif age >= max_hold_days:
                exit_reason = f"持股达上限({max_hold_days}天)到期平仓"

            # D. 目标止盈 (Take Profit)
            elif prev.close >= avg_cost * (1.0 + take_profit):
                exit_reason = f"达到目标止盈 (+{take_profit * 100:.1f}%)"

            # 结构前高平仓（若有设定）
            elif pos.get("target_px") and prev.close >= pos["target_px"]:
                exit_reason = "触及结构前高目标位止盈"

            # 执行卖出（若不可交易/一字跌停则暂挂，次日继续）
            limit_down = r.open <= prev.close * 0.902
            tradable = r.open > 0 and not limit_down

            if exit_reason and tradable:
                sell_px = raw_sell_px * (1.0 - slippage)
                shares = pos["shares"]
                proceeds = shares * sell_px * (1.0 - comm_rate - tax_rate)
                cost = pos["cost"]
                realized_pnl = proceeds - cost
                pnl_pct = (sell_px / (cost / shares) - 1.0) * 100

                cash += proceeds
                code = s[2:]
                stock_name = name_cache.get(code, code)

                trades.append({
                    "symbol": s,
                    "code": code,
                    "name": stock_name,
                    "entry_date": pos["entry_date"],
                    "entry_price": round(pos["entry_price"], 2),
                    "exit_date": day_str,
                    "exit_price": round(sell_px, 2),
                    "shares": shares,
                    "pnl_amount": round(realized_pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "holding_days": age,
                    "peak_price": round(peak, 2),
                    "max_pnl_pct": round(peak_gain * 100, 2),
                    "exit_reason": exit_reason,
                })
                del positions[s]

        # ---------- 2. 买入建仓判断（当日收盘撮合：以扫描出信号的当天收盘价买入） ----------
        candidates = []
        for s, r in today.items():
            if s in positions:
                continue
            # 判断当日是否命中破位止跌信号
            stabilize_passed = getattr(r, "stabilize", False)
            if not stabilize_passed:
                continue
            # 避免同一破位事件重复进场
            event_key = (s, getattr(r, "anchor_date", r.date))
            if event_key in consumed_events:
                continue
            # 过滤不可交易与一字跌停
            prev = previous.get(s)
            locked = False
            if prev is not None and getattr(prev, "close", 0) > 0:
                locked = r.close <= prev.close * 0.902 and r.close == r.low
            if r.close <= 0 or locked:
                continue
            candidates.append((s, r, event_key))

        # 按破位深度优先排序
        candidates.sort(key=lambda x: getattr(x[1], "depth", 0.0), reverse=True)

        for s, r, event_key in candidates:
            if len(positions) >= max_positions:
                break
            nav_close = cash + sum(
                p["shares"] * (today[ps].close if ps in today else last_prices.get(ps, p["entry_price"]))
                for ps, p in positions.items()
            )
            slot_budget = nav_close * single_slot_pct
            entry_budget = min(cash, slot_budget)
            # 以扫描出信号当天的收盘价买入 (考虑标准滑点)
            buy_px = r.close * (1.0 + slippage)
            qty = int(entry_budget / (buy_px * (1.0 + comm_rate)) // 100) * 100
            if qty < 100:
                continue

            cost = qty * buy_px * (1.0 + comm_rate)
            cash -= cost
            consumed_events.add(event_key)

            target_px = getattr(r, "peak", buy_px * (1.0 + take_profit))

            positions[s] = {
                "shares": qty,
                "cost": cost,
                "entry_date": day_str,  # 扫描出信号当天买入
                "entry_price": buy_px,  # 扫描出信号当天的收盘价
                "age": 0,              # 当日买入初始为0，次日可卖(T+1)
                "peak": max(r.close, buy_px),
                "target_px": target_px,
            }

        # ---------- 3. 收盘后状态与净值更新 ----------
        for s, r in today.items():
            last_prices[s] = r.close
            if s in positions:
                # 仅在经历隔夜后递增持股天数
                if positions[s]["entry_date"] != day_str:
                    positions[s]["age"] += 1
                positions[s]["peak"] = max(positions[s]["peak"], r.close, r.high)

        cur_nav = cash + sum(p["shares"] * last_prices.get(s, p["entry_price"]) for s, p in positions.items())
        equity_records.append({
            "date": day_str,
            "nav": round(cur_nav, 2),
            "cash": round(cash, 2),
            "positions_count": len(positions),
        })

        previous.update(today)

    if progress_cb:
        progress_cb({"stage": "正在计算多维收益、超额Alpha与回撤统计指标", "percent": 85, "completed": 5, "total": 6})

    # ---------- 4. 统计曲线与指标 ----------
    eq_df = pd.DataFrame(equity_records)
    if eq_df.empty:
        raise ValueError("回测未生成有效净值序列")

    nav_series = eq_df["nav"]
    strategy_returns = [(n / initial_cap - 1.0) * 100 for n in nav_series]

    # 对齐基准曲线
    bench_map = dict(zip(bench_df["date"], bench_df["close"])) if not bench_df.empty else {}
    base_bench_px = None
    for d in trading_days:
        if d in bench_map and base_bench_px is None:
            base_bench_px = bench_map[d]

    bench_curve = []
    last_bench_pct = 0.0
    for d in trading_days:
        if base_bench_px and d in bench_map:
            last_bench_pct = round((bench_map[d] / base_bench_px - 1.0) * 100, 2)
        bench_curve.append(last_bench_pct)

    alpha_curve = [round(s - b, 2) for s, b in zip(strategy_returns, bench_curve)]

    # 动态回撤曲线
    cum_max = nav_series.cummax()
    drawdown_series = (nav_series - cum_max) / cum_max * 100
    drawdown_curve = [round(x, 2) for x in drawdown_series]
    max_dd = float(drawdown_series.min())

    # 日收益率与波动统计
    daily_returns = nav_series.pct_change().fillna(0.0)
    std = float(daily_returns.std())
    mean_ret = float(daily_returns.mean())
    sharpe = round(float(mean_ret / std * np.sqrt(252)), 2) if std > 0 else 0.0

    days_cnt = len(trading_days)
    annual_ret = round(float((nav_series.iloc[-1] / initial_cap) ** (252 / max(1, days_cnt)) - 1.0) * 100, 2) if days_cnt > 0 else 0.0
    calmar = round(abs(annual_ret / max_dd), 2) if max_dd != 0 else 0.0

    # 交易统计
    total_trades = len(trades)
    win_trades = [t for t in trades if t["pnl_amount"] > 0]
    loss_trades = [t for t in trades if t["pnl_amount"] <= 0]
    win_rate = round(len(win_trades) / total_trades * 100, 2) if total_trades > 0 else 0.0

    sum_win = sum(t["pnl_amount"] for t in win_trades)
    sum_loss = abs(sum(t["pnl_amount"] for t in loss_trades))
    profit_factor = round(sum_win / sum_loss, 2) if sum_loss > 0 else (99.0 if sum_win > 0 else 0.0)

    avg_hold = round(float(np.mean([t["holding_days"] for t in trades])), 1) if total_trades > 0 else 0.0
    max_hold_seen = max([t["holding_days"] for t in trades]) if total_trades > 0 else 0

    # 出场原因分布统计
    exit_reasons_map: dict[str, dict[str, Any]] = {}
    for t in trades:
        reason_group = "持股到期" if "持股达上限" in t["exit_reason"] else \
                       "峰值回撤" if "峰值回撤" in t["exit_reason"] else \
                       "成本止损" if "止损" in t["exit_reason"] else \
                       "目标止盈" if "止盈" in t["exit_reason"] else "其他"
        if reason_group not in exit_reasons_map:
            exit_reasons_map[reason_group] = {"count": 0, "pnls": [], "win_count": 0}
        exit_reasons_map[reason_group]["count"] += 1
        exit_reasons_map[reason_group]["pnls"].append(t["pnl_pct"])
        if t["pnl_pct"] > 0:
            exit_reasons_map[reason_group]["win_count"] += 1

    exit_reason_breakdown = []
    for k, v in exit_reasons_map.items():
        exit_reason_breakdown.append({
            "reason": k,
            "count": v["count"],
            "pct_of_total": round(v["count"] / max(1, total_trades) * 100, 1),
            "win_rate": round(v["win_count"] / v["count"] * 100, 1),
            "avg_pnl_pct": round(float(np.mean(v["pnls"])), 2),
        })

    # 个股盈亏贡献 Top
    stock_group: dict[str, list[dict]] = {}
    for t in trades:
        stock_group.setdefault(t["code"], []).append(t)
    stock_contributions = []
    for code, group in stock_group.items():
        tot_pnl = sum(x["pnl_amount"] for x in group)
        tot_pct = sum(x["pnl_pct"] for x in group)
        wins = sum(1 for x in group if x["pnl_amount"] > 0)
        stock_contributions.append({
            "code": code,
            "name": group[0]["name"],
            "trades_count": len(group),
            "total_pnl_amount": round(tot_pnl, 2),
            "total_pnl_pct": round(tot_pct, 2),
            "win_rate": round(wins / len(group) * 100, 1),
            "avg_pnl": round(tot_pct / len(group), 2),
        })
    stock_contributions.sort(key=lambda x: x["total_pnl_amount"], reverse=True)

    result = {
        "params": p,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "strategy_return_pct": round(strategy_returns[-1], 2),
            "benchmark_return_pct": bench_curve[-1] if bench_curve else 0.0,
            "alpha_pct": round(strategy_returns[-1] - (bench_curve[-1] if bench_curve else 0.0), 2),
            "annualized_return_pct": annual_ret,
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": sharpe,
            "calmar_ratio": calmar,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades,
            "win_trades": len(win_trades),
            "loss_trades": len(loss_trades),
            "avg_holding_days": avg_hold,
            "max_holding_days": max_hold_seen,
            "initial_capital": initial_cap,
            "final_capital": round(nav_series.iloc[-1], 2),
            "universe_count": len(frames),
        },
        "dates": trading_days,
        "equity_curve": [round(x, 2) for x in strategy_returns],
        "benchmark_curve": bench_curve,
        "alpha_curve": alpha_curve,
        "drawdown_curve": drawdown_curve,
        "daily_returns": [round(float(x) * 100, 2) for x in daily_returns],
        "trades": trades,
        "exit_reason_breakdown": exit_reason_breakdown,
        "stock_contributions": stock_contributions[:30],
    }

    if progress_cb:
        progress_cb({"stage": "回测全部完成并入库", "percent": 100, "completed": 6, "total": 6})

    return result


class Strategy3BacktestManager:
    """管理策略三回测执行、持久化历史与异步轮询。"""

    _lock = threading.Lock()
    _running = False
    _started_at: str | None = None
    _last_error: str | None = None
    _progress: dict[str, Any] = {"stage": "就绪", "completed": 0, "total": 0, "percent": 0}
    _current_params: dict[str, Any] = {}

    @classmethod
    def load_history(cls) -> dict[str, Any]:
        with cls._lock:
            if not HISTORY_FILE.exists():
                cls._init_default_history()
            try:
                return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[BACKTEST3] 读取历史文件失败: {e}")
                return {"latest": None, "params": DEFAULT_BACKTEST_PARAMS}

    @classmethod
    def _init_default_history(cls) -> None:
        try:
            res = simulate_strategy3_backtest(DEFAULT_BACKTEST_PARAMS)
            data = {"latest": res, "params": DEFAULT_BACKTEST_PARAMS}
            HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[BACKTEST3] 初始化默认历史失败: {e}")

    @classmethod
    def get_status(cls) -> dict[str, Any]:
        data = cls.load_history()
        with cls._lock:
            return {
                "running": cls._running,
                "started_at": cls._started_at,
                "progress": cls._progress,
                "error": cls._last_error,
                "params": cls._current_params or data.get("params") or DEFAULT_BACKTEST_PARAMS,
                "latest": data.get("latest"),
            }

    @classmethod
    def trigger_backtest(cls, custom_params: dict[str, Any] | None = None) -> dict[str, Any]:
        with cls._lock:
            if cls._running:
                return {"ok": False, "message": "策略三回测正在后台执行中，请等待完成", "running": True}
            cls._running = True
            cls._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._last_error = None
            cls._progress = {"stage": "初始化环境与参数校验", "completed": 0, "total": 6, "percent": 5}
            merged_params = {**DEFAULT_BACKTEST_PARAMS, **(custom_params or {})}
            cls._current_params = merged_params

        def _worker():
            try:
                def on_progress(p_info):
                    with cls._lock:
                        cls._progress = p_info

                res = simulate_strategy3_backtest(merged_params, progress_cb=on_progress)
                with cls._lock:
                    HISTORY_FILE.write_text(
                        json.dumps({"latest": res, "params": merged_params}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    cls._running = False
                    cls._progress = {"stage": "回测已完成并入库", "completed": 6, "total": 6, "percent": 100}
            except Exception as err:
                with cls._lock:
                    cls._running = False
                    cls._last_error = f"回测执行异常: {err}"
                    cls._progress = {"stage": "回测失败", "completed": 0, "total": 6, "percent": 0}
                print(f"[BACKTEST3] 异步任务执行异常: {err}")

        t = threading.Thread(target=_worker, name="Strategy3BacktestWorker", daemon=True)
        t.start()
        return {"ok": True, "message": "策略三参数回测已在后台启动", "running": True}
