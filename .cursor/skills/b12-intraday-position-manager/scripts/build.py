"""
B12 v3 — 日内仓位动态管理（多品种）

按品种分发到独立模块决策：
    A_STOCK / A_ETF       → markets/a_stock.py
    INDEX_FUTURE          → markets/index_future.py
    COMMODITY_FUTURE      → markets/commodity_future.py
    HK_STOCK              → markets/hk_stock.py
    UNKNOWN               → 直接 hold

规则（优先级从高到低，对所有品种语义一致）：
    1. 到达品种强平时间 → 强平（平到 0）
    2. 浮亏 >= 1%        → 全平（平到 0）
    3. 浮亏 >= 0.5%      → 砍半仓（round_lot 下取整）
    4. 浮盈 > 1%         → 加仓 50%（round_lot 下取整，可选 max_qty 封顶）
    5. 其他              → hold

v3 breaking changes:
    - 强平/全平不再手数下取整，直接平到 0（common.close_all_qty）
    - 校验加固：拒绝 NaN/inf/bool，time 需在合法交易时段
    - 新增 max_qty（目标仓位上限）、session_check（时段校验开关，默认 True）
    - 输出新增 5 顶层字段：market / sellable / cash_req / flags / capped_by_max_qty
"""
import math
import os
import re
import sys

# 允许 `python build.py` 直接运行：把 scripts/ 加入 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from classify import classify
from common import make_hold
from markets import a_stock, index_future, commodity_future, hk_stock


# ── 入参字段 ─────────────────────────────────────────────────────────
_REQUIRED_FIELDS = (
    "code", "pnl_pct",
    "sellable_qty", "locked_qty",
    "price", "available_cash",
    "time",
)

_RE_TIME = re.compile(r"^(\d{2}):(\d{2})$")


# ── 交易时段白名单 ───────────────────────────────────────────────────
# 每个市场若干 (start_hhmm, end_hhmm) 闭区间，字符串比较。
_TRADING_SESSIONS = {
    "A_STOCK":          [("09:30", "11:30"), ("13:00", "14:57")],
    "A_ETF":            [("09:30", "11:30"), ("13:00", "14:57")],
    "INDEX_FUTURE":     [("09:30", "11:30"), ("13:00", "15:00")],
    "COMMODITY_FUTURE": [("09:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00")],
    "HK_STOCK":         [("09:30", "12:00"), ("13:00", "16:00")],
}


def _check_trading_session(time_str: str, market: str) -> None:
    """时段校验。UNKNOWN 或未配置的市场跳过。命中失败 → ValueError。"""
    sessions = _TRADING_SESSIONS.get(market)
    if not sessions:
        return
    for start, end in sessions:
        if start <= time_str <= end:
            return
    raise ValueError(
        f"time '{time_str}' 不在 {market} 交易时段 {sessions} 内"
    )


# ── 输入校验（v3 加固） ──────────────────────────────────────────────
def _is_bool(x) -> bool:
    """严格检测 bool（Python 中 bool 是 int 的子类，isinstance(True, int) 为 True）。"""
    return type(x) is bool


def validate_input(input_data) -> None:
    """
    校验输入数据合法性。
    Args:
        input_data: dict 或 list of dict
    Raises:
        TypeError / ValueError / KeyError：字段缺失、类型错误、非法值
    """
    if isinstance(input_data, dict):
        items = [input_data]
    elif isinstance(input_data, list):
        items = input_data
    else:
        raise TypeError(f"input_data 必须是 dict 或 list，收到 {type(input_data).__name__}")

    if len(items) == 0:
        raise ValueError("input_data 不能为空列表")

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(f"第 {i} 条记录必须是 dict，收到 {type(item).__name__}")
        missing = set(_REQUIRED_FIELDS) - set(item.keys())
        if missing:
            raise KeyError(f"第 {i} 条记录缺少字段: {sorted(missing)}")

        # code
        if not isinstance(item["code"], str) or not item["code"]:
            raise TypeError(f"第 {i} 条 code 必须是非空字符串")

        # pnl_pct: 拒绝 bool / NaN / inf
        pnl = item["pnl_pct"]
        if _is_bool(pnl):
            raise TypeError(f"第 {i} 条 pnl_pct 不能是 bool")
        if not isinstance(pnl, (int, float)):
            raise TypeError(f"第 {i} 条 pnl_pct 必须是数值")
        if isinstance(pnl, float) and (math.isnan(pnl) or math.isinf(pnl)):
            raise ValueError(f"第 {i} 条 pnl_pct 不能是 NaN/inf")

        # sellable_qty / locked_qty: 拒绝 bool，非负 int
        for fld in ("sellable_qty", "locked_qty"):
            v = item[fld]
            if _is_bool(v):
                raise TypeError(f"第 {i} 条 {fld} 不能是 bool")
            if not isinstance(v, int) or v < 0:
                raise ValueError(f"第 {i} 条 {fld} 必须是非负整数")

        # price: 拒绝 bool / NaN / inf，需 > 0
        price = item["price"]
        if _is_bool(price):
            raise TypeError(f"第 {i} 条 price 不能是 bool")
        if not isinstance(price, (int, float)):
            raise ValueError(f"第 {i} 条 price 必须是正数")
        if isinstance(price, float) and (math.isnan(price) or math.isinf(price)):
            raise ValueError(f"第 {i} 条 price 不能是 NaN/inf")
        if price <= 0:
            raise ValueError(f"第 {i} 条 price 必须是正数")

        # available_cash: 拒绝 bool / NaN / inf，非负
        cash = item["available_cash"]
        if _is_bool(cash):
            raise TypeError(f"第 {i} 条 available_cash 不能是 bool")
        if not isinstance(cash, (int, float)):
            raise ValueError(f"第 {i} 条 available_cash 必须是非负数")
        if isinstance(cash, float) and (math.isnan(cash) or math.isinf(cash)):
            raise ValueError(f"第 {i} 条 available_cash 不能是 NaN/inf")
        if cash < 0:
            raise ValueError(f"第 {i} 条 available_cash 必须是非负数")

        # time: HH:MM 格式，且 0<=HH<=23, 0<=MM<=59
        t = item["time"]
        if not isinstance(t, str):
            raise ValueError(f"第 {i} 条 time 必须是 'HH:MM' 字符串")
        m = _RE_TIME.match(t)
        if not m:
            raise ValueError(f"第 {i} 条 time 必须是 'HH:MM' 字符串，收到 '{t}'")
        hh = int(m.group(1))
        mm = int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"第 {i} 条 time '{t}' 越界（HH 0-23, MM 0-59）")

        # max_qty（可选）：None 或非负 int，排除 bool
        if "max_qty" in item and item["max_qty"] is not None:
            mq = item["max_qty"]
            if _is_bool(mq):
                raise TypeError(f"第 {i} 条 max_qty 不能是 bool")
            if not isinstance(mq, int) or mq < 0:
                raise ValueError(f"第 {i} 条 max_qty 必须是非负整数或 None")


# ── 决策分发 ─────────────────────────────────────────────────────────
def _dispatch(item: dict) -> dict:
    """按品种分发到对应市场模块。"""
    market = classify(item["code"])
    total = int(item["sellable_qty"]) + int(item["locked_qty"])

    if market == "A_STOCK":
        return a_stock.manage(item, "A_STOCK")
    if market == "A_ETF":
        return a_stock.manage(item, "A_ETF")
    if market == "INDEX_FUTURE":
        return index_future.manage(item)
    if market == "COMMODITY_FUTURE":
        return commodity_future.manage(item)
    if market == "HK_STOCK":
        return hk_stock.manage(item)

    # UNKNOWN：直接 hold，避免误操作
    return make_hold(
        item["code"], float(item["pnl_pct"]), total, item["time"],
        "未识别品种 hold",
        market="UNKNOWN", sellable=0, cash_req=0.0,
        flags=["unknown_market"],
    )


# ── 批量层 ───────────────────────────────────────────────────────────
def batch_manage(positions: list, session_check: bool = True) -> list:
    results = []
    for p in positions:
        if session_check:
            market = classify(p["code"])
            _check_trading_session(p["time"], market)
        results.append(_dispatch(p))
    return results


# ── 标准入口 ─────────────────────────────────────────────────────────
def run(input_data, config=None, session_check: bool = True) -> list:
    """
    标准调用入口。
    Args:
        input_data:    dict（单条）或 list of dict（批量）
        config:        保留参数，暂未使用
        session_check: 是否校验交易时段（默认 True，非交易时段抛 ValueError）
    Returns:
        list of 调仓指令 dict（即使单条也返回长度为 1 的列表）
    """
    validate_input(input_data)
    items = [input_data] if isinstance(input_data, dict) else input_data
    return batch_manage(items, session_check=session_check)


# ── 输出层 ───────────────────────────────────────────────────────────
def print_order(order: dict) -> None:
    label = {"buy": "【加仓 BUY】", "sell": "【减仓/平仓 SELL】", "hold": "【持仓不动 HOLD】"}
    print("=" * 64)
    print(f"  代码      : {order['code']}")
    print(f"  品种      : {order.get('market', '?')}")
    print(f"  当前时间  : {order['time']}")
    print(f"  浮盈亏    : {order['pnl_pct']:+.2%}")
    print(f"  当前持仓  : {order['current_qty']}")
    print(f"  可卖      : {order.get('sellable', '?')}")
    print(f"  操作指令  : {label.get(order['action'], order['action'])}")
    if order["qty_change"] != 0:
        print(f"  变动数量  : {order['qty_change']:+d}")
        print(f"  目标持仓  : {order['target_qty']}")
    if order.get("cash_req", 0):
        print(f"  资金需求  : {order['cash_req']:.2f}")
    if order.get("capped_by_max_qty"):
        print(f"  上限截断  : 是（capped_by_max_qty）")
    if order.get("flags"):
        print(f"  标志      : {order['flags']}")
    print(f"  触发原因  : {order['reason']}")
    print("=" * 64)


# ── 示例入口 ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample = [
        # A股 — 加仓（可卖 800，锁仓 0，加仓 50% × 800 = 400 股）
        {"code": "600036", "pnl_pct":  0.015, "sellable_qty":  800, "locked_qty":   0,
         "price": 10.0, "available_cash": 100000, "time": "10:30"},
        # A股 — 砍半仓但今仓 800 锁仓不可卖（可卖 200 → 砍 100 股）
        {"code": "000001", "pnl_pct": -0.007, "sellable_qty":  200, "locked_qty": 800,
         "price": 10.0, "available_cash":      0, "time": "13:00"},
        # A股 — 全平但 T+1 阻断 400 股（可卖 600，平 600）
        {"code": "300750", "pnl_pct": -0.012, "sellable_qty":  600, "locked_qty": 400,
         "price": 100.0, "available_cash":     0, "time": "13:00"},
        # A股 — 14:50 强平，全是锁仓 → hold
        {"code": "601318", "pnl_pct":  0.008, "sellable_qty":    0, "locked_qty": 500,
         "price": 60.0, "available_cash":      0, "time": "14:50"},
        # 股指期货 IF — 加仓 1 手
        {"code": "IF2406", "pnl_pct":  0.015, "sellable_qty":    2, "locked_qty":   0,
         "price": 4000.0, "available_cash": 200000, "time": "10:30"},
        # 商品期货 rb — 砍半仓 T+0
        {"code": "rb2410", "pnl_pct": -0.007, "sellable_qty":    4, "locked_qty":   0,
         "price": 3500.0, "available_cash":      0, "time": "10:30"},
        # 港股 00700 — 加仓 T+0
        {"code":  "00700", "pnl_pct":  0.015, "sellable_qty":  200, "locked_qty":   0,
         "price": 400.0,   "available_cash": 200000, "time": "10:30"},
        # 资金不足 — A股加仓改 hold
        {"code": "600519", "pnl_pct":  0.015, "sellable_qty": 1000, "locked_qty":   0,
         "price": 1700.0, "available_cash":   1000, "time": "10:30"},
        # UNKNOWN — 未识别代码（关闭时段校验，UNKNOWN 不受限，但示例中一并关掉）
        {"code":   "ABCD", "pnl_pct": -0.012, "sellable_qty":  100, "locked_qty":   0,
         "price": 10.0,    "available_cash":      0, "time": "10:30"},
        # A股 — 加仓遇 max_qty=1000 封顶（可卖 800 + 锁仓 0，加仓算 400 但 headroom=200）
        {"code": "600036", "pnl_pct":  0.015, "sellable_qty":  800, "locked_qty":   0,
         "price": 10.0, "available_cash": 100000, "time": "10:30", "max_qty": 1000},
    ]

    print("\nB12 v3 多品种日内仓位动态管理 — 调仓指令演示\n")
    for order in run(sample):
        print_order(order)
