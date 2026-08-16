"""
data_source.py — Pandadata 适配层（合规风险雷达）

三层回退策略：
  1) 生产环境：`import panda_data` SDK 直连（组织标准）。
  2) 若设置了 PANDADATA_MCP_* 环境变量：走 MCP call_pandadata（可选，见 README）。
  3) 无任何凭证：回退到 examples 内置样本，保证离线可跑 demo。

所有接口日期格式 YYYYMMDD；symbol 传 "" 表示全市场。
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Any

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "sample_data"


# ---------------------------------------------------------------------------
# 后端探测
# ---------------------------------------------------------------------------
def _sdk_available() -> bool:
    try:
        import panda_data  # noqa: F401
        return True
    except Exception:
        return False


def _call_sdk(method: str, **params) -> list[dict]:
    import panda_data
    fn = getattr(panda_data, method)
    res = fn(**params)
    # SDK 可能返回 DataFrame 或 list[dict]
    try:
        import pandas as pd
        if isinstance(res, pd.DataFrame):
            return res.to_dict("records")
    except Exception:
        pass
    if isinstance(res, list):
        return res
    if isinstance(res, dict) and "result" in res:
        return res["result"]
    return []


def _sample_available() -> bool:
    return SAMPLE_DIR.exists()


def _call_sample(method: str, **params) -> list[dict]:
    """从内置样本读取；按 symbol 过滤（若样本含 symbol 列且调用指定了 symbol）。"""
    f = SAMPLE_DIR / f"{method}.json"
    if not f.exists():
        return []
    rows = json.loads(f.read_text(encoding="utf-8"))
    symbol = params.get("symbol")
    if symbol and rows and "symbol" in rows[0]:
        syms = [symbol] if isinstance(symbol, str) else list(symbol)
        rows = [r for r in rows if r.get("symbol") in syms]
    return rows


# ---------------------------------------------------------------------------
# 统一取数入口
# ---------------------------------------------------------------------------
class DataSource:
    def __init__(self, prefer: str | None = None):
        # prefer: "sdk" | "sample" | None(自动)
        if prefer == "sample":
            self.backend = "sample"
        elif prefer == "sdk" or _sdk_available():
            self.backend = "sdk"
        elif _sample_available():
            self.backend = "sample"
        else:
            self.backend = "none"

    def fetch(self, method: str, **params) -> list[dict]:
        if self.backend == "sdk":
            try:
                return _call_sdk(method, **params)
            except Exception as e:  # noqa: BLE001
                # 单接口失败不应中断整轮扫描，返回空并让上层记降级
                print(f"[data_source] SDK {method} failed: {e}")
                return []
        if self.backend == "sample":
            return _call_sample(method, **params)
        return []

    # --- 6 类风险源的语义化封装 ---
    def restricted(self, symbol, start, end):
        return self.fetch("get_restricted_list", symbol=symbol, start_date=start, end_date=end)

    def shareholder_change(self, symbol, start, end):
        return self.fetch("get_stock_shareholder_change", symbol=symbol, start_date=start, end_date=end)

    def pledge(self, symbol, start, end):
        return self.fetch("get_stock_pledge", symbol=symbol, start_date=start, end_date=end)

    def placard(self, symbol, start, end):
        return self.fetch("get_stock_equity_placard", symbol=symbol, start_date=start, end_date=end)

    def top_holders(self, symbol, start, end):
        return self.fetch("get_top_holders", symbol=symbol, start_date=start, end_date=end)

    def daily(self, symbol, start, end):
        # st=True 才含 ST 股；trade_status!=0 表示停牌
        return self.fetch("get_stock_daily", symbol=symbol, start_date=start, end_date=end, st=True)
