"""
B12 v3 测试脚本

覆盖维度：
  1. 4 品种 × 5 优先级（强平/全平/砍半/加仓/hold）
  2. T+1 边界（A股 14:45 强平时今仓阻断）+ target_qty=locked
  3. 资金不足 → hold + cash_insufficient flag
  4. UNKNOWN 兜底 + unknown_market flag
  5. 异常输入：缺字段、负数、空列表、非 dict、time 格式错、price <= 0、available_cash < 0
     + v3 新增：NaN/inf/bool、time 越界、time 非交易时段
  6. 优先级冲突（14:45 + 浮亏 -1.2% → 强平优先于全平）
  7. 强平/全平「平到 0」（不下取整，允许零股）
  8. max_qty 目标仓位上限（E2）
  9. 输出顶层字段 market / sellable / cash_req / flags / capped_by_max_qty
 10. 向后兼容：8 基础字段全在

运行：python3 scripts/test.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from build import run, validate_input  # noqa: E402


# ── 测试框架 ─────────────────────────────────────────────────────────
_PASSED = 0
_FAILED = 0
_FAILS = []


def assert_eq(actual, expected, label):
    global _PASSED, _FAILED
    if actual == expected:
        _PASSED += 1
        print(f"  ✓ {label}")
    else:
        _FAILED += 1
        msg = f"  ✗ {label}: expected {expected!r}, got {actual!r}"
        _FAILS.append(msg)
        print(msg)


def assert_in(needle, haystack, label):
    global _PASSED, _FAILED
    if needle in haystack:
        _PASSED += 1
        print(f"  ✓ {label}")
    else:
        _FAILED += 1
        msg = f"  ✗ {label}: '{needle}' not in '{haystack}'"
        _FAILS.append(msg)
        print(msg)


def assert_not_in(needle, haystack, label):
    global _PASSED, _FAILED
    if needle not in haystack:
        _PASSED += 1
        print(f"  ✓ {label}")
    else:
        _FAILED += 1
        msg = f"  ✗ {label}: '{needle}' unexpectedly in '{haystack}'"
        _FAILS.append(msg)
        print(msg)


def assert_raises(exc_types, fn, label):
    global _PASSED, _FAILED
    try:
        fn()
    except exc_types:
        _PASSED += 1
        print(f"  ✓ {label}")
        return
    except Exception as e:
        _FAILED += 1
        msg = f"  ✗ {label}: expected {exc_types}, got {type(e).__name__}: {e}"
        _FAILS.append(msg)
        print(msg)
        return
    _FAILED += 1
    msg = f"  ✗ {label}: no exception raised"
    _FAILS.append(msg)
    print(msg)


def section(title):
    print(f"\n── {title} ──")


def _r(item, session_check=True):
    """run 单条便捷封装。"""
    return run(item, session_check=session_check)[0]


# ════════════════════════════════════════════════════════════════════
# 1) A 股 — 5 优先级 + T+1 边界 + 资金不足
# ════════════════════════════════════════════════════════════════════
section("A_STOCK 全规则")

o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["action"], "buy", "A股加仓 action=buy")
assert_eq(o["qty_change"], 400, "A股加仓 +400 股")
assert_eq(o["target_qty"], 1200, "A股加仓 target=1200")
assert_eq(o["market"], "A_STOCK", "A股 market 字段=A_STOCK")

o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 200,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["qty_change"], 400, "A股加仓基数=sellable 而非总持仓")

o = _r({"code": "000001", "pnl_pct": -0.007, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["action"], "sell", "A股砍半 action=sell")
assert_eq(o["qty_change"], -500, "A股砍半 -500 股")

o = _r({"code": "000001", "pnl_pct": -0.007, "sellable_qty": 200, "locked_qty": 800,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -100, "A股砍半基数=可卖 200 而非总 1000")

o = _r({"code": "300750", "pnl_pct": -0.012, "sellable_qty": 600, "locked_qty": 400,
        "price": 100.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -600, "A股全平仅平可卖部分")
assert_eq(o["target_qty"], 400, "A股全平 target=locked=400")
assert_in("t1_blocked", o["flags"], "A股全平 flags 含 t1_blocked")

o = _r({"code": "601318", "pnl_pct": -0.003, "sellable_qty": 0, "locked_qty": 500,
        "price": 60.0, "available_cash": 0, "time": "14:45"})
assert_eq(o["action"], "hold", "A股强平时全锁仓不可卖 → hold")
assert_eq(o["qty_change"], 0, "qty_change=0")

o = _r({"code": "601318", "pnl_pct": -0.003, "sellable_qty": 300, "locked_qty": 200,
        "price": 60.0, "available_cash": 0, "time": "14:45"})
assert_eq(o["qty_change"], -300, "A股强平仅平可卖 300")
assert_eq(o["target_qty"], 200, "A股强平 target=locked=200")

o = _r({"code": "600519", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 100.0, "available_cash": 1000, "time": "10:00"})
assert_eq(o["action"], "hold", "A股资金不足 → hold")
assert_in("cash_insufficient", o["flags"], "A股 flags 含 cash_insufficient")

o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 850, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["qty_change"], 400, "A股加仓向下取整 425→400")

o = _r({"code": "600036", "pnl_pct": 0.005, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["action"], "hold", "A股浮盈不足 1% → hold")


# ════════════════════════════════════════════════════════════════════
# 2) A 股 ETF
# ════════════════════════════════════════════════════════════════════
section("A_ETF")

o = _r({"code": "510300", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 1.5, "available_cash": 10000, "time": "10:00"})
assert_eq(o["action"], "buy", "ETF 加仓 action=buy")
assert_eq(o["qty_change"], 500, "ETF 加仓 500 股")
assert_eq(o["market"], "A_ETF", "ETF market=A_ETF")

o = _r({"code": "510300", "pnl_pct": -0.008, "sellable_qty": 600, "locked_qty": 0,
        "price": 1.5, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -300, "ETF 砍半 -300 股")


# ════════════════════════════════════════════════════════════════════
# 3) 股指期货
# ════════════════════════════════════════════════════════════════════
section("INDEX_FUTURE (IF/IC)")

o = _r({"code": "IF2406", "pnl_pct": 0.015, "sellable_qty": 2, "locked_qty": 0,
        "price": 4000.0, "available_cash": 200000, "time": "10:00"})
assert_eq(o["action"], "buy", "IF 加仓 action=buy")
assert_eq(o["qty_change"], 1, "IF 加 1 手")
assert_eq(o["market"], "INDEX_FUTURE", "IF market=INDEX_FUTURE")

o = _r({"code": "IF2406", "pnl_pct": 0.015, "sellable_qty": 2, "locked_qty": 0,
        "price": 4000.0, "available_cash": 50000, "time": "10:00"})
assert_eq(o["action"], "hold", "IF 保证金不足 → hold")
assert_in("cash_insufficient", o["flags"], "IF flags 含 cash_insufficient")

o = _r({"code": "IC2406", "pnl_pct": -0.007, "sellable_qty": 2, "locked_qty": 2,
        "price": 6000.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -2, "IC 砍半基数=4(T+0 含锁仓)")

o = _r({"code": "IF2406", "pnl_pct": -0.001, "sellable_qty": 0, "locked_qty": 3,
        "price": 4000.0, "available_cash": 0, "time": "14:45"})
assert_eq(o["qty_change"], -3, "IF 强平 T+0 含锁仓全平")
assert_eq(o["target_qty"], 0, "IF 强平 target=0")


# ════════════════════════════════════════════════════════════════════
# 4) 商品期货
# ════════════════════════════════════════════════════════════════════
section("COMMODITY_FUTURE (rb/cu)")

o = _r({"code": "rb2410", "pnl_pct": 0.015, "sellable_qty": 4, "locked_qty": 0,
        "price": 3500.0, "available_cash": 50000, "time": "10:00"})
assert_eq(o["action"], "buy", "rb 加仓")
assert_eq(o["qty_change"], 2, "rb 加 2 手")
assert_eq(o["market"], "COMMODITY_FUTURE", "rb market=COMMODITY_FUTURE")

o = _r({"code": "cu2406", "pnl_pct": -0.012, "sellable_qty": 1, "locked_qty": 1,
        "price": 70000.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -2, "cu 全平 T+0 平 2 手")
assert_eq(o["target_qty"], 0, "cu 全平 target=0")


# ════════════════════════════════════════════════════════════════════
# 5) 港股
# ════════════════════════════════════════════════════════════════════
section("HK_STOCK")

o = _r({"code": "00700", "pnl_pct": 0.015, "sellable_qty": 100, "locked_qty": 100,
        "price": 400.0, "available_cash": 200000, "time": "10:00"})
assert_eq(o["action"], "buy", "港股加仓")
assert_eq(o["qty_change"], 100, "港股加 100 股 T+0")
assert_eq(o["market"], "HK_STOCK", "港股 market=HK_STOCK")

o = _r({"code": "00700", "pnl_pct": -0.007, "sellable_qty": 100, "locked_qty": 100,
        "price": 400.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -100, "港股砍半 -100 股 T+0")

o = _r({"code": "00700", "pnl_pct": -0.003, "sellable_qty": 100, "locked_qty": 0,
        "price": 400.0, "available_cash": 0, "time": "14:50"})
assert_eq(o["action"], "hold", "港股 14:50 未到强平时间")

o = _r({"code": "00700", "pnl_pct": -0.003, "sellable_qty": 100, "locked_qty": 0,
        "price": 400.0, "available_cash": 0, "time": "15:45"})
assert_eq(o["qty_change"], -100, "港股 15:45 强平")


# ════════════════════════════════════════════════════════════════════
# 6) UNKNOWN 兜底 + 优先级冲突 + 不足一手
# ════════════════════════════════════════════════════════════════════
section("UNKNOWN & 优先级冲突 & 不足一手")

o = _r({"code": "ABCD", "pnl_pct": -0.012, "sellable_qty": 100, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["action"], "hold", "UNKNOWN → hold")
assert_eq(o["market"], "UNKNOWN", "UNKNOWN market=UNKNOWN")
assert_in("unknown_market", o["flags"], "UNKNOWN flags 含 unknown_market")

o = _r({"code": "600036", "pnl_pct": -0.012, "sellable_qty": 500, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "14:45"})
assert_eq(o["qty_change"], -500, "优先级冲突 强平/全平结果一致")
assert_in("force_close", o["flags"], "优先级 1 强平触发 flags 含 force_close")

o = _r({"code": "600036", "pnl_pct": -0.007, "sellable_qty": 50, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["action"], "hold", "砍半不足一手 → hold")
assert_in("lot_short", o["flags"], "砍半不足 flags 含 lot_short")


# ════════════════════════════════════════════════════════════════════
# 7) 异常输入
# ════════════════════════════════════════════════════════════════════
section("validate_input 异常")

assert_raises(KeyError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "available_cash": 100000, "time": "10:00",
}), "缺字段 price → KeyError")

assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": -100, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00",
}), "负 sellable_qty → ValueError")

assert_raises(ValueError, lambda: run([]), "空列表 → ValueError")

assert_raises(TypeError, lambda: run("not a dict"), "字符串输入 → TypeError")

assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00:00",
}), "time HH:MM:SS 格式 → ValueError")

assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 0, "available_cash": 100000, "time": "10:00",
}), "price=0 → ValueError")

assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": -1, "time": "10:00",
}), "available_cash<0 → ValueError")

o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
base_keys = {"code", "pnl_pct", "current_qty", "time",
             "action", "qty_change", "target_qty", "reason"}
assert_eq(base_keys.issubset(set(o.keys())), True, "8 基础字段全在（向后兼容）")


# ════════════════════════════════════════════════════════════════════
# 8) E1: 强平/全平「平到 0」（不下取整）
# ════════════════════════════════════════════════════════════════════
section("E1 强平/全平 平到 0（允许零股）")

# test_force_close_零股_A股：sellable=50, locked=0, time=14:45 → qty_change=-50, target_qty=0
o = _r({"code": "600036", "pnl_pct": -0.003, "sellable_qty": 50, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "14:45"})
assert_eq(o["qty_change"], -50, "test_force_close_零股_A股 qty_change=-50")
assert_eq(o["target_qty"], 0, "test_force_close_零股_A股 target=0")
assert_in("force_close", o["flags"], "flags 含 force_close")

# test_force_close_港股非100手数：sellable=600, lot=400（02800） → qty_change=-600
o = _r({"code": "02800", "pnl_pct": -0.003, "sellable_qty": 600, "locked_qty": 0,
        "price": 20.0, "available_cash": 0, "time": "15:45"})
assert_eq(o["qty_change"], -600, "test_force_close_港股非100手数 卖 600 股不下取整")
assert_eq(o["target_qty"], 0, "港股非整手强平 target=0")

# test_stop_loss_full_零股：sellable=50, pnl_pct=-0.011 → qty_change=-50
o = _r({"code": "600036", "pnl_pct": -0.011, "sellable_qty": 50, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["qty_change"], -50, "test_stop_loss_full_零股 全平零股 qty_change=-50")
assert_eq(o["target_qty"], 0, "全平零股 target=0")
assert_in("stop_loss_full", o["flags"], "全平 flags 含 stop_loss_full")

# test_half_cut_零股_保留_hold：sellable=50, pnl_pct=-0.006 → hold（砍半不改）
o = _r({"code": "600036", "pnl_pct": -0.006, "sellable_qty": 50, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["action"], "hold", "test_half_cut_零股_保留_hold 砍半仍取整 hold")
assert_in("lot_short", o["flags"], "flags 含 lot_short")

# test_force_close_T1_保持_locked：sellable=200, locked=800, 14:45 → qty_change=-200, target_qty=800
o = _r({"code": "600036", "pnl_pct": 0.003, "sellable_qty": 200, "locked_qty": 800,
        "price": 10.0, "available_cash": 0, "time": "14:45"})
assert_eq(o["qty_change"], -200, "test_force_close_T1_保持_locked qty_change=-200")
assert_eq(o["target_qty"], 800, "test_force_close_T1_保持_locked target=locked=800")
assert_in("t1_blocked", o["flags"], "强平 T+1 flags 含 t1_blocked")


# ════════════════════════════════════════════════════════════════════
# 9) E2: max_qty 目标仓位上限
# ════════════════════════════════════════════════════════════════════
section("E2 max_qty 目标仓位上限")

# test_add_capped_by_max_qty：sellable=1000, max_qty=1200, pnl=0.02 → add=200
o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": 1200})
assert_eq(o["action"], "buy", "test_add_capped_by_max_qty 仍是 buy")
assert_eq(o["qty_change"], 200, "test_add_capped_by_max_qty add=200")
assert_eq(o["capped_by_max_qty"], True, "capped_by_max_qty=True")
assert_in("capped_by_max_qty", o["flags"], "flags 含 capped_by_max_qty")

# test_add_max_qty_已到上限 → hold, flags 含 capped_by_max_qty
o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": 1000})
assert_eq(o["action"], "hold", "test_add_max_qty_已到上限 hold")
assert_in("capped_by_max_qty", o["flags"], "已到上限 flags 含 capped_by_max_qty")
assert_eq(o["capped_by_max_qty"], True, "已到上限 capped_by_max_qty=True")

# test_add_max_qty_None_兼容 → 行为不变
o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": None})
assert_eq(o["qty_change"], 500, "test_add_max_qty_None_兼容 仍加仓 500")
assert_eq(o["capped_by_max_qty"], False, "max_qty=None 不封顶")

# test_add_max_qty_0 → hold
o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": 0})
assert_eq(o["action"], "hold", "test_add_max_qty_0 hold")
assert_in("capped_by_max_qty", o["flags"], "max_qty=0 flags 含 capped_by_max_qty")

# test_add_max_qty_与现金同时不足 → flags 只含 capped_by_max_qty（先命中）
o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00", "max_qty": 1000})
assert_eq(o["action"], "hold", "test_add_max_qty_与现金同时不足 hold")
assert_in("capped_by_max_qty", o["flags"], "flags 含 capped_by_max_qty")
assert_not_in("cash_insufficient", o["flags"], "flags 不含 cash_insufficient（先命中）")

# max_qty 在期货上生效
o = _r({"code": "IF2406", "pnl_pct": 0.015, "sellable_qty": 4, "locked_qty": 0,
        "price": 4000.0, "available_cash": 1000000, "time": "10:00", "max_qty": 5})
assert_eq(o["qty_change"], 1, "IF max_qty=5 已持 4 → 加 1 手")
assert_eq(o["capped_by_max_qty"], True, "IF capped_by_max_qty=True")

# max_qty 在港股上生效（lot=400 场景）
o = _r({"code": "02800", "pnl_pct": 0.02, "sellable_qty": 800, "locked_qty": 0,
        "price": 20.0, "available_cash": 1000000, "time": "10:00", "max_qty": 1000})
# headroom=200, round_lot(200,400)=0 → hold
assert_eq(o["action"], "hold", "港股 lot=400 headroom 200 不足一手 → hold")
assert_in("capped_by_max_qty", o["flags"], "港股封顶 flags")


# ════════════════════════════════════════════════════════════════════
# 10) E3: 校验加固
# ════════════════════════════════════════════════════════════════════
section("E3 校验加固")

# test_validate_max_qty_bool → TypeError
assert_raises(TypeError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": True,
}), "test_validate_max_qty_bool → TypeError")

# test_validate_max_qty_负数 → ValueError
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": -1,
}), "test_validate_max_qty_负数 → ValueError")

# test_validate_pnl_nan/inf/bool
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": float("nan"), "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00",
}), "test_validate_pnl_nan → ValueError")
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": float("inf"), "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00",
}), "test_validate_pnl_inf → ValueError")
assert_raises(TypeError, lambda: run({
    "code": "600036", "pnl_pct": True, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00",
}), "test_validate_pnl_bool → TypeError")

# test_validate_price_nan/inf/bool
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": float("nan"), "available_cash": 100000, "time": "10:00",
}), "test_validate_price_nan → ValueError")
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": float("inf"), "available_cash": 100000, "time": "10:00",
}), "test_validate_price_inf → ValueError")
assert_raises(TypeError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": True, "available_cash": 100000, "time": "10:00",
}), "test_validate_price_bool → TypeError")

# test_validate_cash_nan/inf/bool
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": float("nan"), "time": "10:00",
}), "test_validate_cash_nan → ValueError")
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": float("inf"), "time": "10:00",
}), "test_validate_cash_inf → ValueError")
assert_raises(TypeError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": True, "time": "10:00",
}), "test_validate_cash_bool → TypeError")

# test_validate_sellable_bool → TypeError
assert_raises(TypeError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": True, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "10:00",
}), "test_validate_sellable_bool → TypeError")

assert_raises(TypeError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": False,
    "price": 10.0, "available_cash": 100000, "time": "10:00",
}), "test_validate_locked_bool → TypeError")

# test_validate_time_out_of_range "25:00"/"12:60" → ValueError
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "25:00",
}), "test_validate_time_out_of_range 25:00 → ValueError")
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "12:60",
}), "test_validate_time_out_of_range 12:60 → ValueError")

# test_validate_time_after_hours A股 "16:00" → ValueError
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "16:00",
}), "test_validate_time_after_hours A股 16:00 → ValueError")

# A股午休时段 12:00 也应拒绝
assert_raises(ValueError, lambda: run({
    "code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
    "price": 10.0, "available_cash": 100000, "time": "12:00",
}), "A股午休 12:00 非交易时段 → ValueError")

# test_validate_time_session_check_false 关闭开关 → 通过
o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "16:00"},
       session_check=False)
assert_eq(o["market"], "A_STOCK", "test_validate_time_session_check_false 16:00 关闭校验通过")

# 商品期货交易时段 09:00 通过（10:00 A股不 OK for cmdty）
o = _r({"code": "rb2410", "pnl_pct": 0.015, "sellable_qty": 4, "locked_qty": 0,
        "price": 3500.0, "available_cash": 50000, "time": "09:00"})
assert_eq(o["market"], "COMMODITY_FUTURE", "商品期货 09:00 在段内通过")

# UNKNOWN 品种不做时段校验（任何时间通过）
o = _r({"code": "ABCD", "pnl_pct": 0.0, "sellable_qty": 100, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "23:59"})
assert_eq(o["market"], "UNKNOWN", "UNKNOWN 23:59 不做时段校验")


# ════════════════════════════════════════════════════════════════════
# 11) E4: 输出顶层字段
# ════════════════════════════════════════════════════════════════════
section("E4 输出顶层字段")

# test_output_market_field 5 品种断言
markets_expected = [
    ("600036", "A_STOCK"),
    ("510300", "A_ETF"),
    ("IF2406", "INDEX_FUTURE"),
    ("rb2410", "COMMODITY_FUTURE"),
    ("00700", "HK_STOCK"),
]
for c, m in markets_expected:
    o = _r({"code": c, "pnl_pct": 0.0, "sellable_qty": 100, "locked_qty": 0,
            "price": 10.0, "available_cash": 0, "time": "10:00"})
    assert_eq(o["market"], m, f"test_output_market_field {c} → {m}")

# test_output_sellable_field
o = _r({"code": "600036", "pnl_pct": 0.0, "sellable_qty": 300, "locked_qty": 200,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["sellable"], 300, "test_output_sellable_field A股=sellable_qty")

o = _r({"code": "IF2406", "pnl_pct": 0.0, "sellable_qty": 2, "locked_qty": 3,
        "price": 4000.0, "available_cash": 0, "time": "10:00"})
assert_eq(o["sellable"], 5, "test_output_sellable_field IF=sellable+locked (T+0)")

# test_output_cash_req_field 加仓成功 / hold 现金不足 / hold 未触发
o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["cash_req"] > 0, True, "test_output_cash_req 加仓成功 cash_req>0")

o = _r({"code": "600519", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 100.0, "available_cash": 1000, "time": "10:00"})
assert_eq(o["cash_req"] > 0, True, "test_output_cash_req 现金不足 hold cash_req>0")

o = _r({"code": "600036", "pnl_pct": 0.0, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["cash_req"], 0.0, "test_output_cash_req 未触发 hold cash_req=0")

# test_output_flags_field 各种组合
o = _r({"code": "600036", "pnl_pct": -0.012, "sellable_qty": 500, "locked_qty": 500,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_in("stop_loss_full", o["flags"], "flags 含 stop_loss_full")
assert_in("t1_blocked", o["flags"], "flags 含 t1_blocked")

o = _r({"code": "600036", "pnl_pct": -0.007, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 0, "time": "10:00"})
assert_in("stop_loss_half", o["flags"], "flags 含 stop_loss_half")

# test_output_capped_by_max_qty
o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00", "max_qty": 1200})
assert_eq(o["capped_by_max_qty"], True, "test_output_capped_by_max_qty True")

o = _r({"code": "600036", "pnl_pct": 0.02, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["capped_by_max_qty"], False, "test_output_capped_by_max_qty 未封顶 False")

# test_backward_compat_8_fields 断言基础 8 字段仍存在
o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
for k in ("code", "pnl_pct", "current_qty", "time",
          "action", "qty_change", "target_qty", "reason"):
    assert_eq(k in o, True, f"test_backward_compat_8_fields 含 {k}")

# 5 v3 新增字段
for k in ("market", "sellable", "cash_req", "flags", "capped_by_max_qty"):
    assert_eq(k in o, True, f"v3 新增顶层字段 {k}")

# reason 前缀（INCLUDE_REASON_PREFIX=True 默认）
o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_in("[A_STOCK]", o["reason"], "reason 默认含 [A_STOCK] 前缀（deprecated 但保留）")

# 关闭前缀开关时 reason 无 [MARKET] 前缀
import common
common.INCLUDE_REASON_PREFIX = False
try:
    o = _r({"code": "600036", "pnl_pct": 0.015, "sellable_qty": 800, "locked_qty": 0,
            "price": 10.0, "available_cash": 100000, "time": "10:00"})
    assert_not_in("[A_STOCK]", o["reason"], "关闭 INCLUDE_REASON_PREFIX 后 reason 无前缀")
finally:
    common.INCLUDE_REASON_PREFIX = True


# ════════════════════════════════════════════════════════════════════
# classify 后缀格式识别（bugfix：真实数据回放暴露 000001.SZ 被识别为 UNKNOWN）
# ════════════════════════════════════════════════════════════════════
section("classify 后缀格式识别（.SH / .SZ / .HK）")

from classify import classify

# ── A 股主板：.SH / .SZ 后缀（panda-data / Wind 主流数据源格式） ──
assert_eq(classify("600036.SH"), "A_STOCK", "600036.SH → A_STOCK")
assert_eq(classify("601988.SH"), "A_STOCK", "601988.SH → A_STOCK")
assert_eq(classify("603288.SH"), "A_STOCK", "603288.SH → A_STOCK")
assert_eq(classify("000001.SZ"), "A_STOCK", "000001.SZ → A_STOCK")
assert_eq(classify("002415.SZ"), "A_STOCK", "002415.SZ → A_STOCK（中小板已并入深主板号段）")
assert_eq(classify("300750.SZ"), "A_STOCK", "300750.SZ → A_STOCK（创业板）")
assert_eq(classify("688981.SH"), "A_STOCK", "688981.SH → A_STOCK（科创板）")

# ── 大小写不敏感（真实数据源可能返回 .sh / .Sz） ──
assert_eq(classify("600036.sh"), "A_STOCK", "600036.sh 小写后缀 → A_STOCK")
assert_eq(classify("000001.Sz"), "A_STOCK", "000001.Sz 混合大小写 → A_STOCK")

# ── A 股 ETF：.SH / .SZ 后缀 ──
assert_eq(classify("510300.SH"), "A_ETF", "510300.SH → A_ETF（沪深300ETF）")
assert_eq(classify("159919.SZ"), "A_ETF", "159919.SZ → A_ETF（沪深300ETF深）")
assert_eq(classify("588000.SH"), "A_ETF", "588000.SH → A_ETF（科创50ETF）")

# ── 港股：.HK 后缀 ──
assert_eq(classify("00700.HK"), "HK_STOCK", "00700.HK → HK_STOCK（腾讯）")
assert_eq(classify("00005.HK"), "HK_STOCK", "00005.HK → HK_STOCK（汇丰）")
assert_eq(classify("09988.HK"), "HK_STOCK", "09988.HK → HK_STOCK（阿里）")
assert_eq(classify("00700.hk"), "HK_STOCK", "00700.hk 小写后缀 → HK_STOCK")

# ── 无后缀：原有格式仍生效（向后兼容） ──
assert_eq(classify("600036"), "A_STOCK", "600036 无后缀 → A_STOCK")
assert_eq(classify("sh600036"), "A_STOCK", "sh600036 前缀 → A_STOCK")
assert_eq(classify("sz000001"), "A_STOCK", "sz000001 前缀 → A_STOCK")
assert_eq(classify("00700"), "HK_STOCK", "00700 无后缀 → HK_STOCK")
assert_eq(classify("HK00700"), "HK_STOCK", "HK00700 前缀 → HK_STOCK")

# ── 边界：非法后缀组合应 UNKNOWN ──
assert_eq(classify("abc.SH"), "UNKNOWN", "abc.SH 非数字 body → UNKNOWN")
assert_eq(classify("12345.SH"), "UNKNOWN", "12345.SH 位数不对 → UNKNOWN")
assert_eq(classify("600036.US"), "UNKNOWN", "600036.US 非支持后缀 → UNKNOWN")
assert_eq(classify(".SH"), "UNKNOWN", "空 body → UNKNOWN")

# ── 端到端：后缀格式能正常触发决策（不再走 UNKNOWN hold） ──
o = _r({"code": "000001.SZ", "pnl_pct": 0.015, "sellable_qty": 1000, "locked_qty": 0,
        "price": 10.5, "available_cash": 100000, "time": "10:00"})
assert_eq(o["market"], "A_STOCK", "000001.SZ 端到端 market=A_STOCK")
assert_eq(o["action"], "buy", "000001.SZ pnl=+1.5% 端到端触发加仓")

o = _r({"code": "600036.SH", "pnl_pct": -0.012, "sellable_qty": 500, "locked_qty": 0,
        "price": 10.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["market"], "A_STOCK", "600036.SH 端到端 market=A_STOCK")
assert_eq(o["action"], "sell", "600036.SH pnl=-1.2% 端到端触发全平")

o = _r({"code": "00700.HK", "pnl_pct": 0.015, "sellable_qty": 200, "locked_qty": 0,
        "price": 300.0, "available_cash": 100000, "time": "10:00"})
assert_eq(o["market"], "HK_STOCK", "00700.HK 端到端 market=HK_STOCK")


# ════════════════════════════════════════════════════════════════════
# 总结
# ════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 64}")
print(f"测试总数：{_PASSED + _FAILED}  通过：{_PASSED}  失败：{_FAILED}")
print('=' * 64)
if _FAILED:
    print("\n失败用例：")
    for m in _FAILS:
        print(m)
    sys.exit(1)
print("\n✓ 所有用例通过")
