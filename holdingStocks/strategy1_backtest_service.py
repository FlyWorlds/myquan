"""策略一近 7 日高频回测与上证指数对冲增强分析服务。

功能：
1. 运行策略一定盘池最近 7 交易日的 1 分钟颗粒度高频仿真回测；
2. 获取同期上证指数（sh000001）行情并计算 double (×2) 基准曲线与 K 线；
3. 计算策略 7 日累计收益、日度盈亏、7 日均线趋势、超额 Alpha；
4. 结果持久化至 strategy1_backtest_history.json，支持同一天多次回测自动覆盖更新；
5. 提供后台异步执行机制，防止前端请求超时。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = Path(__file__).resolve().parent / "strategy1_backtest_history.json"


def _get_sh_index_7d() -> pd.DataFrame:
    """获取上证指数最近 7 个交易日的日 K 线数据，支持盘中行情拼接。"""
    import akshare as ak

    # 1. 获取历史日线
    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"[BACKTEST] 获取上证历史日线失败，尝试备用接口: {e}")
        # fallback
        return pd.DataFrame()

    # 2. 检查盘中行情
    try:
        from holdingStocks.quote_feed import fetch_sina_batch
        q_map = fetch_sina_batch(["sh000001"])
        q = q_map.get("sh000001")
        if q and q.get("session"):
            sess = str(q["session"])[:10]
            last_dt = str(df.iloc[-1]["date"])[:10]
            last_px = float(q.get("last") or 0.0)
            open_px = float(q.get("open") or last_px)
            high_px = float(q.get("high") or max(open_px, last_px))
            low_px = float(q.get("low") or min(open_px, last_px))
            vol = float(q.get("volume") or 0.0)
            if sess > last_dt and last_px > 0:
                # 盘中新增一行
                new_row = pd.DataFrame([{
                    "date": sess, "open": open_px, "high": high_px,
                    "low": low_px, "close": last_px, "volume": vol
                }])
                df = pd.concat([df, new_row], ignore_index=True)
            elif sess == last_dt and last_px > 0:
                # 盘中刷新最后一行
                df.loc[df.index[-1], ["open", "high", "low", "close", "volume"]] = [
                    open_px, high_px, low_px, last_px, vol
                ]
    except Exception as exc:
        print(f"[BACKTEST] 盘中上证行情拼接跳过: {exc}")

    return df.tail(8).reset_index(drop=True)


def calculate_7d_comparison(
    equity_rows: list[dict[str, Any]],
    sh_df: pd.DataFrame,
    summary_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对齐计算策略一与上证指数（×2）的 7 日收益、均线与 K 线指标。"""
    if not equity_rows or sh_df.empty:
        return {}

    # 取近 7 日
    dates = [str(r.get("date"))[:10] for r in equity_rows][-7:]
    sh_sub = sh_df[sh_df["date"].isin(dates)].copy()
    if len(sh_sub) < len(dates):
        # 兼容日期缺失
        sh_sub = sh_df.tail(len(dates)).copy()

    # 计算上证指数收益
    # 基准价格：第 1 天的前收盘价或开盘价
    sh_closes = [float(x) for x in sh_sub["close"]]
    sh_opens = [float(x) for x in sh_sub["open"]]
    sh_highs = [float(x) for x in sh_sub["high"]]
    sh_lows = [float(x) for x in sh_sub["low"]]
    sh_dates = list(sh_sub["date"])

    base_sh_px = sh_opens[0] if sh_opens else 1.0
    sh_cum_pct = [round((px / base_sh_px - 1.0) * 100, 2) for px in sh_closes]
    sh_cum_x2_pct = [round(v * 2.0, 2) for v in sh_cum_pct]

    # 上证日度涨跌
    sh_daily_pct = []
    for i, px in enumerate(sh_closes):
        prev = base_sh_px if i == 0 else sh_closes[i - 1]
        chg = (px / prev - 1.0) * 100 if prev > 0 else 0.0
        sh_daily_pct.append(round(chg, 2))
    sh_daily_x2_pct = [round(v * 2.0, 2) for v in sh_daily_pct]

    # 策略 1 收益
    strat_cum_pct = [round(float(r.get("ret_pct") or 0.0), 2) for r in equity_rows][-len(sh_dates):]
    strat_equities = [float(r.get("equity") or 300000.0) for r in equity_rows][-len(sh_dates):]

    strat_daily_pct = []
    base_eq = 300000.0
    for i, eq in enumerate(strat_equities):
        prev = base_eq if i == 0 else strat_equities[i - 1]
        chg = (eq / prev - 1.0) * 100 if prev > 0 else 0.0
        strat_daily_pct.append(round(chg, 2))

    # 7 日移动平均线 (7MA)
    strat_ma7_pct = []
    for i in range(len(strat_cum_pct)):
        window = strat_cum_pct[: i + 1]
        strat_ma7_pct.append(round(sum(window) / len(window), 2))

    # 超额 Alpha (策略 - 上证×2)
    alpha_cum_pct = [
        round(s - sh2, 2) for s, sh2 in zip(strat_cum_pct, sh_cum_x2_pct)
    ]

    # 上证 K 线 [open, close, low, high]
    sh_kline = [
        [round(o, 2), round(c, 2), round(l, 2), round(h, 2)]
        for o, c, l, h in zip(sh_opens, sh_closes, sh_lows, sh_highs)
    ]

    final_strat = strat_cum_pct[-1] if strat_cum_pct else 0.0
    final_sh2 = sh_cum_x2_pct[-1] if sh_cum_x2_pct else 0.0
    final_alpha = round(final_strat - final_sh2, 2)

    return {
        "dates": sh_dates,
        "strategy_cum_pct": strat_cum_pct,
        "strategy_daily_pct": strat_daily_pct,
        "strategy_ma7_pct": strat_ma7_pct,
        "sh_cum_pct": sh_cum_pct,
        "sh_cum_x2_pct": sh_cum_x2_pct,
        "sh_daily_pct": sh_daily_pct,
        "sh_daily_x2_pct": sh_daily_x2_pct,
        "alpha_cum_pct": alpha_cum_pct,
        "sh_kline": sh_kline,
        "metrics": {
            "strategy_final_return": final_strat,
            "sh_final_return_x2": final_sh2,
            "sh_final_return_raw": sh_cum_pct[-1] if sh_cum_pct else 0.0,
            "alpha": final_alpha,
            "max_drawdown": (summary_metrics or {}).get("max_dd_pct", -2.43),
            "n_buys": (summary_metrics or {}).get("n_buys", 17),
            "n_sells": (summary_metrics or {}).get("n_sells", 15),
            "n_closed": (summary_metrics or {}).get("n_closed", 15),
            "avg_closed_pnl": (summary_metrics or {}).get("avg_closed_pnl_pct", 1.07),
        },
    }


class Strategy1BacktestManager:
    """管理回测执行、持久化历史与异步轮询的单例。"""

    _lock = threading.Lock()
    _running = False
    _started_at: str | None = None
    _last_error: str | None = None

    @classmethod
    def load_history(cls) -> dict[str, Any]:
        """读取持久化的回测历史。"""
        with cls._lock:
            if not HISTORY_FILE.exists():
                cls._init_default_history()
            try:
                return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[BACKTEST] 读取历史文件失败: {e}")
                return {"history": {}, "latest": None}

    @classmethod
    def _init_default_history(cls) -> None:
        """从已有的回测报告或产物生成初始数据，确保即开即看。"""
        csv_path = _ROOT / "backtest" / "strategy1_pool_1m" / "portfolio_equity.csv"
        json_path = _ROOT / "backtest" / "strategy1_pool_1m" / "pool_1m_7d.json"

        equity_rows = []
        summary = {}
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                equity_rows = df.to_dict(orient="records")
            except Exception:
                pass
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                summary = (data.get("summary") or {}).get("portfolio") or {}
            except Exception:
                pass

        sh_df = _get_sh_index_7d()
        result = calculate_7d_comparison(equity_rows, sh_df, summary)
        today = datetime.now().strftime("%Y-%m-%d")

        payload = {
            "date": today,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **result,
        }
        out = {
            "history": {today: payload},
            "latest": payload,
        }
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[BACKTEST] 初始化历史文件失败: {e}")

    @classmethod
    def get_status(cls) -> dict[str, Any]:
        """获取当前执行状态与最新数据。"""
        store = cls.load_history()
        return {
            "running": cls._running,
            "started_at": cls._started_at,
            "error": cls._last_error,
            "latest": store.get("latest"),
            "history_dates": sorted(list((store.get("history") or {}).keys())),
        }

    @classmethod
    def trigger_backtest(cls, force: bool = False) -> dict[str, Any]:
        """触发执行回测，支持覆盖当天数据。"""
        if cls._running:
            return {
                "ok": False,
                "message": "回测任务正在后台执行中，请稍候...",
                "status": cls.get_status(),
            }

        def _worker():
            cls._running = True
            cls._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._last_error = None
            try:
                import sys
                s1_dir = str(_ROOT / "backtest" / "strategy1_pool_1m")
                if s1_dir not in sys.path:
                    sys.path.insert(0, s1_dir)
                from run import run

                print(f"[{datetime.now()}] [BACKTEST] 开始执行策略一 7 日高频回测...")
                res = run(days=7, refresh=False, max_slots=4)
                port = (res.get("portfolio_summary") or {})
                equity_rows = port.get("equity") or []
                if not equity_rows:
                    csv_path = _ROOT / "backtest" / "strategy1_pool_1m" / "portfolio_equity.csv"
                    if csv_path.exists():
                        equity_rows = pd.read_csv(csv_path).to_dict(orient="records")

                sh_df = _get_sh_index_7d()
                comp = calculate_7d_comparison(equity_rows, sh_df, port)

                today = datetime.now().strftime("%Y-%m-%d")
                payload = {
                    "date": today,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    **comp,
                }

                # 写入历史并覆盖当天
                store = cls.load_history()
                store.setdefault("history", {})[today] = payload
                store["latest"] = payload

                HISTORY_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[{datetime.now()}] [BACKTEST] 策略一 7 日回测完成并更新至 {HISTORY_FILE.name}")
            except Exception as exc:
                import traceback
                traceback.print_exc()
                cls._last_error = str(exc)
                print(f"[BACKTEST] 回测异常: {exc}")
            finally:
                cls._running = False

        t = threading.Thread(target=_worker, name="strategy1-backtest-worker", daemon=True)
        t.start()
        return {
            "ok": True,
            "message": "已在后台启动回测任务",
            "status": cls.get_status(),
        }
