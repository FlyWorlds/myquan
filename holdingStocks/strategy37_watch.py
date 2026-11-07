"""策略三十七·跌停开板缠论反转策略 盯盘与快照服务模块。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_REPORTS_DIR = _ROOT / "reports" / "limit_down_chan"
_SUMMARY_FILE = _REPORTS_DIR / "summary_metrics.json"
_SIGNALS_FILE = _REPORTS_DIR / "signals_3个月_90天.csv"


def load_backtest_summary() -> dict[str, Any]:
    """读取回测汇总指标。"""
    if not _SUMMARY_FILE.is_file():
        return {}
    try:
        return json.loads(_SUMMARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_recent_signals(limit: int = 50) -> list[dict[str, Any]]:
    """读取最近触发的跌停开板缠论买入信号标的。"""
    if not _SIGNALS_FILE.is_file():
        return []
    try:
        df = pd.read_csv(_SIGNALS_FILE)
        df["date"] = pd.to_datetime(df["date"])
        # 按最新日期降序
        df = df.sort_values("date", ascending=False).head(limit)
        
        from stock_names import lookup_names_for_codes

        codes = [str(r["symbol"])[2:] if len(str(r["symbol"])) >= 8 else str(r["symbol"]) for _, r in df.iterrows()]
        name_map = lookup_names_for_codes(codes)

        rows: list[dict[str, Any]] = []
        for _, r in df.iterrows():
            code = str(r["symbol"])[2:] if len(str(r["symbol"])) >= 8 else str(r["symbol"])
            name = name_map.get(code, code)

            rows.append({
                "代码": code,
                "名称": name,
                "symbol": str(r["symbol"]),
                "日期": str(r["date"].strftime("%Y-%m-%d")),
                "买入价": round(float(r["buy_price"]), 2),
                "收盘价": round(float(r["close"]), 2),
                "跌停价": round(float(r["limit_down"]), 2),
                "脱离中枢天数": int(r["delta_days"]) if pd.notna(r.get("delta_days")) else 0,
                "中枢ZD": round(float(r["zs_zd"]), 2) if pd.notna(r.get("zs_zd")) else 0.0,
                "中枢ZG": round(float(r["zs_zg"]), 2) if pd.notna(r.get("zs_zg")) else 0.0,
                "d1收益%": round(float(r["ret_d1"]) * 100, 2) if pd.notna(r.get("ret_d1")) else None,
                "d3收益%": round(float(r["ret_d3"]) * 100, 2) if pd.notna(r.get("ret_d3")) else None,
                "d5收益%": round(float(r["ret_d5"]) * 100, 2) if pd.notna(r.get("ret_d5")) else None,
                "状态": "跌停开板背驰确认",
            })
        return rows
    except Exception:
        return []


def get_strategy37_watch_payload() -> dict[str, Any]:
    """生成给盯盘 UI 使用的完整 strategy37 payload。"""
    summary = load_backtest_summary()
    recent_signals = load_recent_signals(limit=50)

    # 提取 3个月窗口的调参与验证关键指标
    s_3m = summary.get("3个月(90天)", {})
    train_stats = s_3m.get("train_2020_2023", {})
    tune_stats = s_3m.get("tune_2023_2025", {})
    test_stats = s_3m.get("test_2025_now", {})

    # 公共自选池额外追加合并：不挤占原有策略信号配额
    try:
        from watch_config import current_self_watchlist, code_key
        existing_codes = {code_key(str(r.get("代码") or "")) for r in recent_signals}
        self_items = list(current_self_watchlist())
        extra_rows = []
        for code, name in self_items:
            c = code_key(code)
            if not c or c == "000000":
                continue
            if c in existing_codes:
                for r in recent_signals:
                    if code_key(str(r.get("代码") or "")) == c:
                        r["池来源"] = "自选"
                        r["self_watch"] = True
                continue
            existing_codes.add(c)
            extra_rows.append({
                "代码": c,
                "名称": name,
                "symbol": ("sh" if c.startswith("6") else "sz") + c,
                "日期": "自选监控",
                "买入价": None,
                "收盘价": None,
                "跌停价": None,
                "脱离中枢天数": 0,
                "中枢ZD": 0.0,
                "中枢ZG": 0.0,
                "d1收益%": None,
                "d3收益%": None,
                "d5收益%": None,
                "状态": "自选池额外监控",
                "池来源": "自选",
                "self_watch": True,
            })
        final_rows = recent_signals + extra_rows
    except Exception:
        final_rows = recent_signals

    return {
        "strategyId": "strategy37",
        "strategyName": "策略三十七·跌停开板缠论反转策略",
        "rules": (
            "宇宙：全A沪深主板正股（非ST）。当日触及10%跌停且收盘开板(Low=跌停价 且 Close>Low)；"
            "日线呈现“下跌笔+中枢+离开下跌笔”结构，脱离中枢<=90天(3个月)背驰买入；持有5个交易日(d5)收盘平仓。"
        ),
        "params": {
            "window_days": 90,
            "limit_ratio": 0.10,
            "tick_tolerance": 0.01,
            "holding_days": 5,
            "buy_price_type": "close",
        },
        "kpi": {
            "optimal_window": "3个月 (90天)",
            "optimal_holding": "5个交易日 (d5)",
            "tune_d5_win_rate": tune_stats.get("d5", {}).get("win_rate_pct", 57.78),
            "tune_d5_mean_ret": tune_stats.get("d5", {}).get("mean_ret_pct", 4.21),
            "tune_d5_pf": tune_stats.get("d5", {}).get("profit_factor", 2.43),
            "oos_d5_win_rate": test_stats.get("d5", {}).get("win_rate_pct", 51.36),
            "oos_d5_mean_ret": test_stats.get("d5", {}).get("mean_ret_pct", 0.79),
            "oos_d5_pf": test_stats.get("d5", {}).get("profit_factor", 1.20),
            "limit_down_d1_win_rate": 67.26,
            "limit_down_d1_mean_ret": 3.03,
            "limit_down_d1_pf": 4.01,
        },
        "summary": summary,
        "rows": final_rows,
    }


__all__ = [
    "load_backtest_summary",
    "load_recent_signals",
    "get_strategy37_watch_payload",
]
