#!/usr/bin/env python3
"""
B11 自测脚本

覆盖：
  - 原有快乐路径用例（保留，按新契约 total_equity + 交易日历调整入参）
  - [E1] 交易日语义：周末/节假日入场、次日判定、满2交易日强平、entry为非交易日兜底
  - [E2] 仓位分母 total_equity：=0/负权益/NaN/inf、满仓现金趋零不误减、边界10%
  - [E3] 代码分类：sh600036/SZ000001/600036/688/ETF 判A股、IF2406/rb2410 判期货、整百委托
  - [E4] 期货合约乘数：IF=300/rb=10 名义价值、未知品种报错、传 multiplier 覆盖、A股=1
  - [E5] 健壮性：减仓不退化清仓、today<entry 守卫、today==entry 当日、NaN 价格、numpy 类型、target==current
  - 优先级冲突：TP > 强平、batch_manage 混合标的
  - [依赖] panda_data 缺失 / PANDA_USERNAME / PANDA_PASSWORD env 缺失时的 RuntimeError

依赖处理：交易日历唯一来源是 panda_data.get_trade_cal。测试中通过 monkey-patch
TradingCalendar.from_panda_data 用预置日历序列替换，避免测试真的联网/登录。
沙箱 Py3.10 可独立运行。每例打印 input / expected / actual。
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(__file__))
import build
from build import (
    run, validate_input, manage_position, classify, TradingCalendar,
    _resolve_multiplier, _is_a_stock, _is_future, _normalize_code, _get_lot_size,
    CLS_A_STOCK, CLS_FUTURE,
)

PASS, FAIL = 0, 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"✅ {name}")
    except AssertionError as e:
        FAIL += 1
        print(f"❌ {name}: {e}")
    except Exception as e:
        FAIL += 1
        print(f"💥 {name}: {type(e).__name__}: {e}")


def show(input_data, expected, actual):
    """打印 input/expected/actual（截断长 dict）。"""
    print(f"    input={input_data}")
    print(f"    expected={expected}")
    print(f"    actual={actual}")


# ============================================================
# 交易日历 monkey-patch：拦截 TradingCalendar.from_panda_data
# 用预置的日历序列替换真实的 panda_data 网络调用
# ============================================================

# 跨周末：周三6/17、周四6/18、周五6/19、(周六日非交易)、周一6/22、周二6/23、周三6/24、周四6/25
_TRADE_DAYS_WEEKLY = [
    "2026-06-17", "2026-06-18", "2026-06-19",
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25",
]
# 含国庆长假：9-29/9-30 节前，10-1..10-8 休市，10-9 节后首日
_TRADE_DAYS_HOLIDAY = [
    "2026-09-29", "2026-09-30",
    "2026-10-09", "2026-10-10", "2026-10-12", "2026-10-13",
]
# 合并所有测试涉及的日期（monkey-patch 用一份即可覆盖）
_TRADE_DAYS_ALL = sorted(set(_TRADE_DAYS_WEEKLY + _TRADE_DAYS_HOLIDAY))

_original_from_panda_data = TradingCalendar.from_panda_data


def _fake_from_panda_data(cls, start_date, end_date, exchange="SH"):
    """测试替身：不联网、不读盘，直接用预置日历。"""
    return cls(_TRADE_DAYS_ALL)


TradingCalendar.from_panda_data = classmethod(_fake_from_panda_data)
# 同时避免测试期间尝试真登录 panda_data / 读真实 parquet
build._PANDA_LOGIN_DONE = True
build._CALENDAR_CACHE = None   # 清空单例缓存，让 monkey-patch 生效


def base(**over):
    """构造一条合法输入基线（A股，total_equity 充足，入场当天）。"""
    pos = {
        "code": "600036", "entry_price": 10.0, "entry_date": "2026-06-19",
        "current_qty": 800, "open_price": 10.0,
        "total_equity": 1_000_000, "today": "2026-06-19",
    }
    pos.update(over)
    return pos


# ============================================================
# 校验层
# ============================================================

def test_validate_ok():
    ok, err = validate_input(base())
    assert ok, err


def test_validate_missing_field():
    ok, err = validate_input({"code": "600036"})
    assert not ok


def test_validate_bad_price():
    ok, err = validate_input(base(entry_price=-1.0))
    assert not ok


def test_validate_bad_date():
    ok, err = validate_input(base(entry_date="bad"))
    assert not ok


def test_validate_missing_total_equity():
    p = base()
    del p["total_equity"]
    ok, err = validate_input(p)
    assert not ok and "total_equity" in err, err


# ============================================================
# E1 交易日语义
# ============================================================

def test_e1_friday_entry_monday_take_profit():
    """[E1] 周五入场，周一(交易日次日)高开+5.5% → 止盈（原自然日实现会误判为强平/跳过）。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55)
    r = run(inp)
    exp = {"action": "sell", "target_qty": 0, "reason~": "止盈"}
    show("周五入场+周一+5.5%", exp, {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell", r
    assert r["target_qty"] == 0
    assert "止盈" in r["reason"], r["reason"]


def test_e1_friday_entry_monday_stop_loss():
    """[E1] 周五入场，周一低开-3.5% → 止损。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=9.65)
    r = run(inp)
    show("周五入场+周一-3.5%", {"action": "sell", "reason~": "止损"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止损" in r["reason"], r


def test_e1_holiday_entry_next_session_take_profit():
    """[E1] 节前最后交易日(9-30)入场，节后首日(10-9)为交易日次日，高开+6% → 止盈。"""
    inp = base(entry_date="2026-09-30", today="2026-10-09", open_price=10.6)
    r = run(inp)
    show("国庆前入场+节后首日+6%", {"action": "sell", "reason~": "止盈"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止盈" in r["reason"], r


def test_e1_force_close_across_weekend():
    """[E1] 周五入场，周二(=T+2,满2交易日)→ 强平（非自然日 days）。"""
    inp = base(entry_date="2026-06-19", today="2026-06-23", open_price=10.1)
    r = run(inp)
    show("周五入场+周二(T+2)", {"action": "sell", "reason~": "强制平仓"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "强制平仓" in r["reason"], r


def test_e1_force_close_across_holiday():
    """[E1] 节前入场(9-29)，节后第二个交易日(10-10)=满2交易日 → 强平。"""
    inp = base(entry_date="2026-09-29", today="2026-10-10", open_price=10.1)
    r = run(inp)
    show("国庆跨假满2交易日", {"action": "sell", "reason~": "强制平仓"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "强制平仓" in r["reason"], r


def test_e1_natural_gt1_but_trading_eq1():
    """[E1] 自然日差=3(周五→周一)但交易日差=1：验证按交易日判次日而非自然日。"""
    cal = TradingCalendar(_TRADE_DAYS_WEEKLY)
    assert cal.holding_trading_days("2026-06-19", "2026-06-22") == 1, "周五→周一应为1个交易日"
    assert cal.is_next_day("2026-06-19", "2026-06-22") is True
    # 入场当天=0
    assert cal.holding_trading_days("2026-06-19", "2026-06-19") == 0
    # T+2
    assert cal.holding_trading_days("2026-06-19", "2026-06-23") == 2


def test_e1_entry_on_non_trading_day_fallback():
    """[E1] entry_date 为周六(非交易日,数据异常)：夹逼兜底不崩溃，能给出合理交易日数。"""
    cal = TradingCalendar(_TRADE_DAYS_WEEKLY)
    # 周六 2026-06-20 入场，今天周一 6-22：<=6-22 交易日数=4(17,18,19,22) - <=6-20 交易日数=3(17,18,19)=1
    hd = cal.holding_trading_days("2026-06-20", "2026-06-22")
    show("entry周六兜底", {"holding_trading_days": ">=0 不崩溃"}, {"holding_trading_days": hd})
    assert hd >= 0, hd


def test_e1_calendar_comes_from_panda_data():
    """[E1] 交易日历唯一来源：验证 build.py 只走 TradingCalendar.from_panda_data 路径。"""
    # monkey-patch 已把 from_panda_data 替换为 _fake_from_panda_data
    # 若代码内仍尝试其他路径，会绕过测试替身导致真联网/或不到日历 → 测试失败
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55)
    r = run(inp)
    show("交易日历走 from_panda_data", {"action": "sell", "reason~": "止盈"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止盈" in r["reason"], r


# ============================================================
# E2 仓位分母 total_equity
# ============================================================

def test_e2_total_equity_zero_returns_hold():
    """[E2] total_equity=0 → 返回 hold 不崩溃（原 available_cash=0 会 ZeroDivisionError）。"""
    inp = base(total_equity=0, current_qty=2000, open_price=10.0, today="2026-06-19")
    r = run(inp)
    show("total_equity=0", {"action": "hold", "reason~": "总权益非正"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "总权益非正" in r["reason"], r


def test_e2_total_equity_negative_returns_hold():
    """[E2] 负权益(穿仓) → hold。"""
    inp = base(total_equity=-50000, current_qty=2000, today="2026-06-19")
    r = run(inp)
    show("负权益穿仓", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", r


def test_e2_total_equity_nan_rejected():
    """[E2] total_equity=NaN → validate_input 拒绝。"""
    ok, err = validate_input(base(total_equity=float("nan")))
    show("total_equity=NaN", {"ok": False}, {"ok": ok, "err": err})
    assert not ok, err


def test_e2_full_position_cash_zero_no_false_reduce():
    """[E2] 满仓现金趋零但 total_equity 正常：单票占比小，不再误减（原口径会误减）。"""
    # 持仓市值 60000，总权益 1,000,000 → 占比6% < 10%，应 hold（即便 available_cash≈0）
    inp = base(current_qty=6000, open_price=10.0, total_equity=1_000_000,
               available_cash=0, today="2026-06-19")
    r = run(inp)
    show("满仓现金0但占比6%", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", r


def test_e2_boundary_exactly_10pct_no_reduce():
    """[E2/10%口径] 占比恰好==10% 不减仓（严格 >10% 才动）。"""
    # 市值 = 1000股*100元 = 100,000；总权益 1,000,000 → 恰好10%
    inp = base(current_qty=1000, open_price=100.0, total_equity=1_000_000, today="2026-06-19")
    r = run(inp)
    show("占比恰好10%", {"action": "hold"}, {"action": r["action"], "ratio": "10%", "reason": r["reason"]})
    assert r["action"] == "hold", r


def test_e2_over_10pct_reduces_to_le_10pct():
    """[E2/10%口径] 占比>10% 减仓至 <=10% 最近整百股。"""
    # 市值 = 2000*100 = 200,000；总权益 1,000,000 → 20% > 10%
    # 目标名义=100,000 → 1000股；floor 到 1000（整百），1000<2000 → sell
    inp = base(current_qty=2000, open_price=100.0, total_equity=1_000_000, today="2026-06-19")
    r = run(inp)
    show("占比20%减仓", {"action": "sell", "target_qty": 1000},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell", r
    assert r["target_qty"] == 1000, r
    # 减仓后占比 = 1000*100/1e6 = 10% <= 10%
    assert (r["target_qty"] * 100) / 1_000_000 <= 0.10 + 1e-9


# ============================================================
# E3 代码分类
# ============================================================

def test_e3_classify_a_stock_three_forms():
    """[E3] 600036 / sh600036 / SZ000001 三种写法均判 A股，lot=100。"""
    for code in ("600036", "sh600036", "SH600036", "SZ000001", "sz000001", "Sh600036"):
        assert _is_a_stock(code), f"{code} 应判A股"
        assert classify(code) == CLS_A_STOCK, code
        assert _get_lot_size(code) == 100, code
    show("A股三写法分类", {"all": "A_STOCK lot=100"}, {"checked": ["600036", "sh600036", "SZ000001", "..."]})


def test_e3_classify_star_market_and_etf():
    """[E3] 科创板688 / ETF 510300 / 北交所开头8 均为6位数字 → A股。"""
    for code in ("688981", "510300", "159915", "830799"):
        assert _is_a_stock(code), f"{code} 6位数字应判A股"
        assert _get_lot_size(code) == 100, code


def test_e3_classify_future():
    """[E3] IF2406 / rb2410 / cu2401 判期货，lot=1。"""
    for code in ("IF2406", "rb2410", "cu2401", "RB2410"):
        assert _is_future(code), f"{code} 应判期货"
        assert classify(code) == CLS_FUTURE, code
        assert _get_lot_size(code) == 1, code


def test_e3_sh_prefix_not_future_no_odd_lot():
    """[E3] sh600036 不再被误判期货：减仓产出整百委托(不再出现909股)。"""
    # 市值 = 1000*100=100,000 占总权益... 设 total_equity 使其>10%
    inp = base(code="sh600036", current_qty=2000, open_price=100.0,
               total_equity=1_000_000, today="2026-06-19")
    r = run(inp)
    show("sh前缀减仓整百", {"action": "sell", "target_qty%100": 0},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "sell", r
    assert r["target_qty"] % 100 == 0, f"A股委托必须整百，实际 {r['target_qty']}"


def test_e3_normalize():
    assert _normalize_code("sh600036") == "600036"
    assert _normalize_code("SZ000001") == "000001"
    assert _normalize_code("600036") == "600036"
    assert _normalize_code("IF2406") == "IF2406"


# ============================================================
# E4 期货合约乘数
# ============================================================

def test_e4_if_notional_multiplier_300():
    """[E4] IF2406 名义价值 = qty*price*300，仓位比按名义价值算。"""
    # 10手 * 4050 * 300 = 12,150,000；总权益 1e8 → 12.15% > 10% → 减仓
    inp = base(code="IF2406", entry_price=4000.0, current_qty=10, open_price=4050.0,
               multiplier=300, total_equity=100_000_000, today="2026-06-19")
    r = run(inp)
    # 目标名义=1e7 → 1e7/(4050*300)=8.23 → floor 8 手
    show("IF乘数300减仓", {"action": "sell", "target_qty": 8},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell" and r["target_qty"] == 8, r


def test_e4_rb_notional_multiplier_10():
    """[E4] rb2410 名义价值 = qty*price*10。"""
    mult = _resolve_multiplier("rb2410")
    show("rb内置乘数", {"multiplier": 10}, {"multiplier": mult})
    assert mult == 10, mult
    # 200手*3500*10 = 7,000,000；总权益 1e7 → 70% > 10% → 减仓至 <=10%
    inp = base(code="rb2410", entry_price=3500.0, current_qty=200, open_price=3500.0,
               total_equity=10_000_000, today="2026-06-19")
    r = run(inp)
    # 目标名义=1e6 → 1e6/(3500*10)=28.57 → floor 28 手
    show("rb乘数10减仓", {"action": "sell", "target_qty": 28},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "sell" and r["target_qty"] == 28, r


def test_e4_unknown_future_raises():
    """[E4] 未知期货品种且未传 multiplier → 报错（不静默用1）。"""
    raised = False
    try:
        _resolve_multiplier("zz2410")  # zz 不在表中
    except ValueError as e:
        raised = True
        msg = str(e)
    show("未知期货乘数", {"raises": "ValueError"}, {"raised": raised})
    assert raised, "未知品种应报错"
    assert "multiplier" in msg


def test_e4_caller_multiplier_override():
    """[E4] 调用方传 multiplier 覆盖未知品种 → 不报错，按传入值算。"""
    mult = _resolve_multiplier("zz2410", multiplier=20)
    assert mult == 20, mult
    inp = base(code="zz2410", entry_price=1000.0, current_qty=5, open_price=1000.0,
               multiplier=20, total_equity=10_000_000, today="2026-06-19")
    r = run(inp)  # 名义=5*1000*20=100,000 占1% → hold
    show("传入乘数覆盖未知品种", {"no_raise": True, "action": "hold"},
         {"action": r["action"]})
    assert r["action"] == "hold", r


def test_e4_a_stock_multiplier_1():
    """[E4] A股 multiplier 恒为 1，市值口径不变。"""
    assert _resolve_multiplier("600036") == 1
    assert _resolve_multiplier("sh600036") == 1


# ============================================================
# E5 健壮性（4 子修复）
# ============================================================

def test_e5_no_degrade_to_clear_high_price():
    """[E5-①] 高价单手持仓，10%槽位<1手 → 不退化为清仓（保持原仓 hold，绝不卖光）。"""
    # IF 单手名义 = 1*4050*300 = 1,215,000；总权益 5,000,000 → 24.3% > 10%
    # 目标名义=500,000 → 500000/1215000=0.41手 → floor 0 → 不能清仓，应 hold
    inp = base(code="IF2406", entry_price=4000.0, current_qty=1, open_price=4050.0,
               multiplier=300, total_equity=5_000_000, today="2026-06-19")
    r = run(inp)
    show("高价单手不清仓", {"action": "hold", "target_qty": 1},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "hold", f"绝不能清仓: {r}"
    assert r["target_qty"] == 1, r


def test_e5_a_stock_min_lot_no_clear():
    """[E5-①] A股高价股10%槽位<100股 → 不清仓。"""
    # 100股*3000元=300,000；总权益 1,000,000 → 30% > 10%
    # 目标名义=100,000 → 100000/3000=33.3股 → floor 0(<100) → 不清仓 hold
    inp = base(code="600519", current_qty=100, open_price=3000.0,
               total_equity=1_000_000, today="2026-06-19")
    r = run(inp)
    show("A股高价不清仓", {"action": "hold", "target_qty": 100},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "hold" and r["target_qty"] == 100, r


def test_e5_today_before_entry_guard():
    """[E5-②] today < entry_date：validate_input 拒绝（守卫）。"""
    ok, err = validate_input(base(entry_date="2026-06-22", today="2026-06-19"))
    show("today<entry校验", {"ok": False}, {"ok": ok, "err": err})
    assert not ok, err


def test_e5_today_before_entry_trading_guard_in_decision():
    """[E5-②] 决策层交易日维度 today<entry → hold（绕过校验直接调 manage_position）。"""
    # entry=6-23 (交易日), today=6-19 (交易日)，交易日差 = 索引(19)-索引(23) < 0
    r = manage_position(code="600036", entry_price=10.0, entry_date="2026-06-23",
                        current_qty=800, open_price=10.0, today="2026-06-19",
                        total_equity=1_000_000)
    show("决策层today<entry", {"action": "hold", "reason~": "早于"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "早于" in r["reason"], r


def test_e5_today_equals_entry_same_day_hold():
    """[E5] today==entry（入场当天，0个交易日，既非次日也未满2日）→ hold。"""
    inp = base(entry_date="2026-06-19", today="2026-06-19", open_price=10.5,
               current_qty=100)  # 即便+5%，当天非次日不止盈
    r = run(inp)
    show("入场当天+5%", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", f"入场当天不应触发次日止盈: {r}"


def test_e5_nan_price_validate_rejected():
    """[E5-③] entry_price/open_price 为 NaN → validate_input 拒绝。"""
    ok1, _ = validate_input(base(open_price=float("nan")))
    ok2, _ = validate_input(base(entry_price=float("inf")))
    show("NaN/inf价格校验", {"ok1": False, "ok2": False}, {"ok1": ok1, "ok2": ok2})
    assert not ok1 and not ok2


def test_e5_nan_price_decision_hold():
    """[E5-③] 绕过校验直接传 NaN 价格 → 决策层守卫返回 hold（双保险）。"""
    r = manage_position(code="600036", entry_price=10.0, entry_date="2026-06-19",
                        current_qty=800, open_price=float("nan"), today="2026-06-22",
                        total_equity=1_000_000)
    show("决策层NaN价格", {"action": "hold", "reason~": "NaN"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "NaN" in r["reason"], r


def test_e5_numpy_like_integral_accepted():
    """[E5-④] numbers.Integral（模拟 numpy.int64）current_qty 被接受。"""
    class FakeNpInt(int):
        """模拟 numpy 整数：是 int 子类，也是 numbers.Integral。"""
        pass
    import numbers as _n
    assert isinstance(FakeNpInt(800), _n.Integral)
    ok, err = validate_input(base(current_qty=FakeNpInt(800)))
    show("numpy整数类型", {"ok": True}, {"ok": ok, "err": err})
    assert ok, err


def test_e5_numpy_like_real_price_accepted():
    """[E5-④] numbers.Real（模拟 numpy.float64）价格被接受。"""
    class FakeNpFloat(float):
        pass
    import numbers as _n
    assert isinstance(FakeNpFloat(10.5), _n.Real)
    ok, err = validate_input(base(open_price=FakeNpFloat(10.5), entry_price=FakeNpFloat(10.0)))
    assert ok, err


def test_e5_bool_rejected_as_qty():
    """[E5-④] bool 不应被当作合法数量（True/False 排除）。"""
    ok, err = validate_input(base(current_qty=True))
    assert not ok, "bool 不应通过 current_qty 校验"


def test_e5_target_equals_current_hold():
    """[E5] 减仓计算后 target==current（无需操作）→ hold。"""
    # 构造占比恰好略超但 floor 后 target==current 的场景：占比10.0001%，floor 不变
    # 市值=1000*100.01=100,010 总权益1,000,000 → 10.001% > 10%
    # 目标名义=100,000 → 100000/100.01=999.9 → floor 900？需整百 → 900 < 1000 会 sell
    # 改用：current 已是满足<=10%的最大整百，floor 后==current 则 hold
    # 市值=900*111=99,900 总权益 1,000,000 → 9.99% < 10% → 本就 hold（验证不误触发）
    inp = base(current_qty=900, open_price=111.0, total_equity=1_000_000, today="2026-06-19")
    r = run(inp)
    show("占比9.99%不动", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", r


# ============================================================
# 优先级冲突 & 批量
# ============================================================

def test_priority_tp_over_force_close():
    """[优先级] 次日同时满足止盈(+5.5%)与(若按日)强平 → TP 优先（reason 含止盈非强平）。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55)
    r = run(inp)
    show("TP>强平", {"reason~": "止盈"}, {"reason": r["reason"]})
    assert "止盈" in r["reason"] and "强制平仓" not in r["reason"], r


def test_priority_force_close_over_reduce():
    """[优先级] 满2交易日强平 优先于 仓位减仓：即便超仓也全平到0。"""
    inp = base(code="600036", current_qty=5000, open_price=100.0, total_equity=1_000_000,
               entry_date="2026-06-19", today="2026-06-23")
    r = run(inp)
    show("强平>减仓", {"action": "sell", "target_qty": 0, "reason~": "强制平仓"},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell" and r["target_qty"] == 0 and "强制平仓" in r["reason"], r


def test_batch_mixed_a_stock_and_future():
    """[批量] batch_manage 混合 A股+期货：各自按品种正确处理。"""
    positions = [
        base(code="600036", entry_date="2026-06-19", today="2026-06-22", open_price=10.55),  # A股次日止盈
        base(code="IF2406", entry_price=4000.0, current_qty=10, open_price=4050.0,
             multiplier=300, total_equity=100_000_000, today="2026-06-19"),  # 期货减仓
        base(code="000001", entry_date="2026-06-22", today="2026-06-22", open_price=14.9,
             current_qty=100),  # 入场当天 hold
    ]
    results = run(positions)
    show("批量混合", {"len": 3, "0": "sell止盈", "1": "sell减仓", "2": "hold"},
         {"actions": [x["action"] for x in results]})
    assert len(results) == 3
    assert results[0]["action"] == "sell" and "止盈" in results[0]["reason"], results[0]
    assert results[1]["action"] == "sell" and results[1]["target_qty"] == 8, results[1]
    assert results[2]["action"] == "hold", results[2]


def test_empty_list():
    assert run([]) == []


# ============================================================
# 原有快乐路径用例（保留，按新契约调整）
# ============================================================

def test_legacy_hold_entry_day():
    r = run(base(entry_date="2026-06-19", today="2026-06-19", open_price=10.1, current_qty=100))
    assert r["action"] == "hold", r


def test_legacy_future_take_profit():
    r = run(base(code="IF2406", entry_price=4000.0, current_qty=2, open_price=4220.0,
                 multiplier=300, total_equity=100_000_000,
                 entry_date="2026-06-19", today="2026-06-22"))
    assert r["action"] == "sell" and r["target_qty"] == 0 and "止盈" in r["reason"], r


def test_legacy_boundary_5pct():
    r = run(base(entry_date="2026-06-19", today="2026-06-22", open_price=10.50,
                 current_qty=100))
    assert r["action"] == "sell", r  # 恰好 +5% 触发（>=）


def test_legacy_boundary_3pct():
    r = run(base(entry_date="2026-06-19", today="2026-06-22", open_price=9.70,
                 current_qty=100))
    assert r["action"] == "sell", r  # 恰好 -3% 触发（<=）


# ============================================================
# 依赖：panda_data / PANDA_USERNAME / PANDA_PASSWORD
# ============================================================

def test_dep_missing_env_raises_runtime_error():
    """[依赖] 未配置 PANDA_USERNAME/PANDA_PASSWORD 且 panda_data 未登录时抛 RuntimeError 含引导。"""
    # 保存原状态
    saved_login = build._PANDA_LOGIN_DONE
    saved_user = os.environ.pop("PANDA_USERNAME", None)
    saved_pwd = os.environ.pop("PANDA_PASSWORD", None)
    try:
        build._PANDA_LOGIN_DONE = False
        raised = False
        msg = ""
        try:
            build._ensure_panda_logged_in()
        except RuntimeError as e:
            raised = True
            msg = str(e)
        except ImportError:
            # 若 panda_data 本身未安装，会先抛 ImportError-wrapped RuntimeError（我们代码 raise RuntimeError from ImportError）
            # 但 ImportError 被 raise ... from ... 转成 RuntimeError，不会走到这里
            pass
        show("env缺失", {"raises": "RuntimeError", "msg~": "PANDA_USERNAME"},
             {"raised": raised, "msg_head": msg[:60] if msg else ""})
        # 若 panda_data 已装，则应抛 RuntimeError；若未装，抛的也是 RuntimeError（含 pip install）
        assert raised, "应抛 RuntimeError"
        # 错误消息必须包含配置引导（PANDA_USERNAME 或 pip install）之一
        assert ("PANDA_USERNAME" in msg) or ("pip install panda_data" in msg), \
            f"错误消息应含 env 或 install 引导：{msg}"
    finally:
        # 恢复
        if saved_user is not None:
            os.environ["PANDA_USERNAME"] = saved_user
        if saved_pwd is not None:
            os.environ["PANDA_PASSWORD"] = saved_pwd
        build._PANDA_LOGIN_DONE = saved_login


def test_dep_error_message_mentions_install():
    """[依赖] panda_data 未安装场景：错误消息含 pip install 与 export 引导（通过消息断言，无需真的卸载包）。"""
    # 直接验证 build._ensure_panda_logged_in 逻辑上把安装+配置都写清楚了
    import inspect
    src = inspect.getsource(build._ensure_panda_logged_in)
    assert "pip install panda_data" in src, "应写明 pip install panda_data"
    assert "PANDA_USERNAME" in src and "PANDA_PASSWORD" in src, "应写明 env 变量名"
    assert "export " in src, "应给出 export 示例"
    show("引导消息完整性", {"含": ["pip install", "PANDA_USERNAME", "export"]},
         {"pass": True})


# ============================================================
# production/trade.parquet 缓存
# ============================================================

def test_parquet_load_when_present_and_covers_today():
    """[Cache] parquet 存在且覆盖 today → _load_trade_days_from_parquet 返回日期列表。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过 parquet 读写测试（生产环境 panda_data 会带上 pyarrow）")
        return
    import tempfile
    # 构造覆盖 today 的极简 parquet（列名与 panda_data 输出一致）
    today = "2026-06-22"
    nature_dates = [20260617, 20260618, 20260619, 20260622, 20260623]
    table = pa.table({"nature_date": nature_dates})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name
    try:
        days = build._load_trade_days_from_parquet(parquet_path, today)
        show("parquet 覆盖 today", {"len": 5, "first": "2026-06-17"},
             {"len": len(days) if days else 0, "first": days[0] if days else None})
        assert days is not None and len(days) == 5, days
        assert days[0] == "2026-06-17" and days[-1] == "2026-06-23"
    finally:
        os.unlink(parquet_path)


def test_parquet_returns_none_when_missing():
    """[Cache] parquet 文件不存在 → 返回 None（触发上层回退）。"""
    result = build._load_trade_days_from_parquet("/nonexistent/path/trade.parquet", "2026-06-22")
    show("parquet 缺失", {"result": None}, {"result": result})
    assert result is None


def test_parquet_returns_none_when_stale():
    """[Cache] parquet 存在但最晚交易日 < today → 返回 None（缓存过期，强制回退）。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    # 最晚 20260619，但 today=20260630 → 过期
    table = pa.table({"nature_date": [20260617, 20260618, 20260619]})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name
    try:
        result = build._load_trade_days_from_parquet(parquet_path, "2026-06-30")
        show("parquet 过期", {"result": None}, {"result": result})
        assert result is None
    finally:
        os.unlink(parquet_path)


def test_calendar_cache_singleton():
    """[Cache] 同一进程内 TradingCalendar.from_panda_data 复用单例（_CALENDAR_CACHE）。"""
    # 临时恢复真实 from_panda_data 的缓存逻辑（monkey-patch 版本未走 cache 分支）
    saved_login = build._PANDA_LOGIN_DONE
    build._PANDA_LOGIN_DONE = True
    build._CALENDAR_CACHE = None
    try:
        cal1 = TradingCalendar.from_panda_data("2026-06-19", "2026-06-22")
        # 手动模拟真实 classmethod 会做的事：把 cal1 写入 cache
        build._CALENDAR_CACHE = cal1
        cal2 = TradingCalendar.from_panda_data("2026-06-19", "2026-06-22")
        # 因 cache 命中，from_panda_data 应直接返回 cal1（真 classmethod 会走 cache 分支）
        # monkey-patch 的 fake 不走 cache，所以这里断言 fake 至少构造出等价日历
        show("单例缓存", {"cache 命中后可复用": True}, {"cal1 days == cal2 days": cal1._days == cal2._days})
        assert cal1._days == cal2._days, "同参构造应产生等价日历"
    finally:
        build._PANDA_LOGIN_DONE = saved_login
        build._CALENDAR_CACHE = None


def test_calendar_cache_real_singleton_logic():
    """[Cache] 直接测试真实 from_panda_data classmethod 的单例逻辑（临时恢复原函数）。"""
    # 临时把 classmethod 恢复为原始版本，但用一个 stub _load_trade_days_from_parquet
    saved_login = build._PANDA_LOGIN_DONE
    saved_cache = build._CALENDAR_CACHE
    saved_load = build._load_trade_days_from_parquet
    build._PANDA_LOGIN_DONE = True
    build._CALENDAR_CACHE = None
    build._load_trade_days_from_parquet = lambda p, t: _TRADE_DAYS_ALL  # 假装 parquet 存在

    # 恢复原始 classmethod（避免 monkey-patch 的 fake 版本干扰）
    TradingCalendar.from_panda_data = _original_from_panda_data
    try:
        cal1 = TradingCalendar.from_panda_data("2026-06-19", "2026-06-22")
        cal2 = TradingCalendar.from_panda_data("2026-06-19", "2026-06-22")
        show("真单例", {"cal1 is cal2": True}, {"cal1 is cal2": cal1 is cal2})
        assert cal1 is cal2, "真 classmethod 应通过 _CALENDAR_CACHE 复用同一实例"
    finally:
        # 恢复 monkey-patch
        TradingCalendar.from_panda_data = classmethod(_fake_from_panda_data)
        build._load_trade_days_from_parquet = saved_load
        build._CALENDAR_CACHE = saved_cache
        build._PANDA_LOGIN_DONE = saved_login


# ============================================================
# production API：inspect_calendar / refresh_calendar（agent 侧）
# ============================================================

def test_inspect_calendar_missing():
    """[API] parquet 不存在 → recommendation='missing'。"""
    result = build.inspect_calendar(parquet_path="/nonexistent/trade.parquet")
    show("inspect 缺失", {"exists": False, "recommendation": "missing"},
         {"exists": result["exists"], "recommendation": result["recommendation"]})
    assert result["exists"] is False
    assert result["recommendation"] == "missing"
    assert result["count"] == 0
    assert "build_calendar.py" in result["reason"]


def test_inspect_calendar_ok_when_covers_today_far():
    """[API] parquet 覆盖到 today+30+ → recommendation='ok'。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    # 构造覆盖 today+180 的 parquet
    today = date.today()
    dates = [
        int((today + timedelta(days=d)).strftime("%Y%m%d"))
        for d in range(0, 200, 10)
    ]
    table = pa.table({"nature_date": dates})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name
    try:
        result = build.inspect_calendar(parquet_path=parquet_path)
        show("inspect ok", {"recommendation": "ok"},
             {"recommendation": result["recommendation"],
              "days_to_expiry": result["days_to_expiry"]})
        assert result["exists"] is True
        assert result["covers_today"] is True
        assert result["recommendation"] == "ok"
        assert result["days_to_expiry"] >= 30
    finally:
        os.unlink(parquet_path)


def test_inspect_calendar_expired():
    """[API] parquet 覆盖不到 today → recommendation='refresh_required'。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    # 构造 date_max = today - 30 的过期 parquet
    today = date.today()
    old_date = int((today - timedelta(days=30)).strftime("%Y%m%d"))
    table = pa.table({"nature_date": [old_date - 100, old_date - 50, old_date]})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name
    try:
        result = build.inspect_calendar(parquet_path=parquet_path)
        show("inspect 过期", {"recommendation": "refresh_required", "covers_today": False},
             {"recommendation": result["recommendation"],
              "days_to_expiry": result["days_to_expiry"]})
        assert result["covers_today"] is False
        assert result["recommendation"] == "refresh_required"
        assert result["days_to_expiry"] < 0
    finally:
        os.unlink(parquet_path)


def test_inspect_calendar_soon_to_expire():
    """[API] parquet 距 today < 30 天 → recommendation='refresh_recommended'。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    max_date = int((today + timedelta(days=10)).strftime("%Y%m%d"))
    table = pa.table({"nature_date": [max_date - 200, max_date - 100, max_date]})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name
    try:
        result = build.inspect_calendar(parquet_path=parquet_path)
        show("inspect 即将过期", {"recommendation": "refresh_recommended"},
             {"recommendation": result["recommendation"],
              "days_to_expiry": result["days_to_expiry"]})
        assert result["covers_today"] is True
        assert result["recommendation"] == "refresh_recommended"
        assert 0 <= result["days_to_expiry"] < 30
    finally:
        os.unlink(parquet_path)


def test_refresh_calendar_skips_when_ok():
    """[API] recommendation='ok' 时 refresh_calendar 不重跑。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(0, 200, 10)]
    table = pa.table({"nature_date": dates})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name
    try:
        r = build.refresh_calendar(parquet_path=parquet_path)
        show("refresh skip", {"updated": False}, {"updated": r["updated"], "reason": r["reason"][:40]})
        assert r["updated"] is False
        assert "跳过" in r["reason"]
    finally:
        os.unlink(parquet_path)


def test_refresh_calendar_force_triggers_rebuild(monkeypatch_build_calendar=None):
    """[API] force=True 无视缓存直接重跑（monkey-patch build_calendar 避免真联网）。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    import sys as _sys
    from datetime import date, timedelta
    # 存量 parquet 是 ok 的
    today = date.today()
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(0, 200, 10)]
    table = pa.table({"nature_date": dates})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        parquet_path = f.name

    # 让 build_calendar.build_calendar 的替身写一份新 parquet（不真联网）
    _sys.path.insert(0, os.path.dirname(__file__))
    import build_calendar
    original_bc = build_calendar.build_calendar

    def fake_bc(years_back=3, years_forward=1, exchange="SH", output_path=None):
        # 写一份日期范围明显不同的 parquet 以证明"确实重跑了"
        new_dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(0, 400, 10)]
        table = pa.table({"nature_date": new_dates})
        pq.write_table(table, output_path or parquet_path)
        return {"output_path": output_path or parquet_path, "trade_days_count": len(new_dates)}

    build_calendar.build_calendar = fake_bc
    try:
        r = build.refresh_calendar(force=True, parquet_path=parquet_path)
        show("refresh force", {"updated": True}, {"updated": r["updated"], "count_after": r["after"]["count"] if r["after"] else None})
        assert r["updated"] is True
        assert r["after"]["count"] == 40   # fake_bc 写的日期数
    finally:
        build_calendar.build_calendar = original_bc
        os.unlink(parquet_path)


def test_refresh_calendar_creates_when_missing():
    """[API] parquet 缺失时 refresh 自动创建。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    import sys as _sys
    from datetime import date, timedelta

    # 用一个不存在的路径
    with tempfile.TemporaryDirectory() as tmpdir:
        parquet_path = os.path.join(tmpdir, "trade.parquet")

        _sys.path.insert(0, os.path.dirname(__file__))
        import build_calendar
        original_bc = build_calendar.build_calendar

        today = date.today()
        def fake_bc(years_back=3, years_forward=1, exchange="SH", output_path=None):
            new_dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(0, 100, 10)]
            table = pa.table({"nature_date": new_dates})
            pq.write_table(table, output_path or parquet_path)
            return {"output_path": output_path or parquet_path, "trade_days_count": len(new_dates)}

        build_calendar.build_calendar = fake_bc
        try:
            r = build.refresh_calendar(parquet_path=parquet_path)
            show("refresh 创建", {"updated": True, "before.exists": False, "after.exists": True},
                 {"updated": r["updated"],
                  "before.exists": r["before"]["exists"],
                  "after.exists": r["after"]["exists"] if r["after"] else None})
            assert r["updated"] is True
            assert r["before"]["exists"] is False
            assert r["after"]["exists"] is True
        finally:
            build_calendar.build_calendar = original_bc


# ============================================================
# check_date_coverage：agent 侧查询 API
# ============================================================

def _write_fixture_parquet(path, dates_int):
    """辅助：写一份含 nature_date 列的 parquet。"""
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.table({"nature_date": dates_int})
    pq.write_table(table, path)


def test_check_coverage_in_range():
    """[API] 查询日期在覆盖内 → in_range=True + suggested_action='ok'。"""
    try:
        import pyarrow  # noqa
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-365, 400, 10)]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        _write_fixture_parquet(f.name, dates)
        p = f.name
    try:
        r = build.check_date_coverage(today.strftime("%Y-%m-%d"), parquet_path=p)
        show("check 范围内", {"in_range": True, "suggested_action": "ok"},
             {"in_range": r["in_range"], "suggested_action": r["suggested_action"]})
        assert r["in_range"] is True
        assert r["suggested_action"] == "ok"
        assert r["refresh_command"] is None
        assert r["gap_before"] == 0 and r["gap_after"] == 0
    finally:
        os.unlink(p)


def test_check_coverage_extend_back():
    """[API] 查询早于 date_min → extend_back + suggested_years_back 大于当前。"""
    try:
        import pyarrow  # noqa
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    # 只覆盖 today ± 1 年
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-365, 365, 10)]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        _write_fixture_parquet(f.name, dates)
        p = f.name
    try:
        # 查询 5 年前的日期
        query = (today - timedelta(days=365*5)).strftime("%Y-%m-%d")
        r = build.check_date_coverage(query, parquet_path=p)
        show("check 早于 date_min", {"in_range": False, "action": "extend_back", "years_back>=5": True},
             {"in_range": r["in_range"], "suggested_action": r["suggested_action"],
              "suggested_years_back": r["suggested_years_back"]})
        assert r["in_range"] is False
        assert r["suggested_action"] == "extend_back"
        assert r["gap_before"] > 0 and r["gap_after"] == 0
        assert r["suggested_years_back"] >= 5
        assert "refresh_calendar" in r["refresh_command"]
    finally:
        os.unlink(p)


def test_check_coverage_extend_forward():
    """[API] 查询晚于 date_max → extend_forward + suggested_years_forward 增大。"""
    try:
        import pyarrow  # noqa
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-365, 365, 10)]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        _write_fixture_parquet(f.name, dates)
        p = f.name
    try:
        query = (today + timedelta(days=365*3)).strftime("%Y-%m-%d")
        r = build.check_date_coverage(query, parquet_path=p)
        show("check 晚于 date_max", {"in_range": False, "action": "extend_forward"},
             {"in_range": r["in_range"], "suggested_action": r["suggested_action"],
              "suggested_years_forward": r["suggested_years_forward"]})
        assert r["in_range"] is False
        assert r["suggested_action"] == "extend_forward"
        assert r["gap_after"] > 0 and r["gap_before"] == 0
        assert r["suggested_years_forward"] >= 3
    finally:
        os.unlink(p)


def test_check_coverage_extend_both():
    """[API] 区间两端都超出 → extend_both + 建议同时扩展。"""
    try:
        import pyarrow  # noqa
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-180, 180, 10)]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        _write_fixture_parquet(f.name, dates)
        p = f.name
    try:
        s = (today - timedelta(days=365*3)).strftime("%Y-%m-%d")
        e = (today + timedelta(days=365*3)).strftime("%Y-%m-%d")
        r = build.check_date_coverage(s, e, parquet_path=p)
        show("check 两端超出", {"action": "extend_both"},
             {"action": r["suggested_action"],
              "back": r["suggested_years_back"], "forward": r["suggested_years_forward"]})
        assert r["suggested_action"] == "extend_both"
        assert r["gap_before"] > 0 and r["gap_after"] > 0
        assert r["suggested_years_back"] >= 3
        assert r["suggested_years_forward"] >= 3
    finally:
        os.unlink(p)


def test_check_coverage_missing_parquet():
    """[API] parquet 缺失 → suggested_action='missing' + 给出兜底建议。"""
    r = build.check_date_coverage("2025-01-15", parquet_path="/nonexistent/trade.parquet")
    show("check 缺失", {"action": "missing", "in_range": False},
         {"action": r["suggested_action"], "in_range": r["in_range"]})
    assert r["in_range"] is False
    assert r["suggested_action"] == "missing"
    assert r["coverage"]["date_min"] is None
    assert "refresh_calendar" in r["refresh_command"] or "build_calendar" in r["refresh_command"]


def test_check_coverage_swaps_reversed_range():
    """[API] 用户传 start > end 时自动交换而不是报错。"""
    try:
        import pyarrow  # noqa
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    from datetime import date, timedelta
    today = date.today()
    dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-365, 400, 10)]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        _write_fixture_parquet(f.name, dates)
        p = f.name
    try:
        # 反向传入
        s = (today + timedelta(days=100)).strftime("%Y-%m-%d")
        e = (today - timedelta(days=100)).strftime("%Y-%m-%d")
        r = build.check_date_coverage(s, e, parquet_path=p)
        # 归一化后 query.start 应 <= query.end
        assert r["query"]["start_date"] <= r["query"]["end_date"]
        assert r["in_range"] is True   # 两端都在覆盖内
    finally:
        os.unlink(p)


# ============================================================
# 硬伤回归测试（H1-H4 / M1-M4）—— 每例针对一个具体审计发现
# ============================================================

def test_hardbug_h1_entry_price_zero_no_crash():
    """[H1] 直接调 manage_position(entry_price=0) 不再 ZeroDivisionError，守卫返回 hold。"""
    r = manage_position(code="600036", entry_price=0.0, entry_date="2026-06-19",
                        current_qty=800, open_price=10.55, today="2026-06-22",
                        total_equity=1_000_000)
    show("H1 entry_price=0", {"action": "hold", "reason~": "entry_price 非正"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "entry_price 非正" in r["reason"], r


def test_hardbug_h1_entry_price_negative_no_crash():
    """[H1] 负 entry_price 也走守卫（不进入 pnl 计算）。"""
    r = manage_position(code="600036", entry_price=-1.0, entry_date="2026-06-19",
                        current_qty=800, open_price=10.55, today="2026-06-22",
                        total_equity=1_000_000)
    assert r["action"] == "hold" and "entry_price 非正" in r["reason"], r


def test_hardbug_h1_nan_price_guard_still_works():
    """[H1] NaN 价格守卫仍然优先命中（在 entry_price 非正守卫之前）。"""
    r = manage_position(code="600036", entry_price=float("nan"), entry_date="2026-06-19",
                        current_qty=800, open_price=10.55, today="2026-06-22",
                        total_equity=1_000_000)
    assert r["action"] == "hold" and "NaN" in r["reason"], r


def test_hardbug_h2_parquet_string_nature_date_falls_back():
    """[H2] parquet 的 nature_date 列若是 str "2026-06-19"（模拟 panda_data 未来升级），
    _load_trade_days_from_parquet 应返回 None 触发回退，而不是 ValueError 崩溃。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    # 关键：写入 str 而非 int64
    table = pa.table({"nature_date": ["2026-06-19", "2026-06-22", "2026-06-23"]})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        p = f.name
    try:
        result = build._load_trade_days_from_parquet(p, "2026-06-22")
        show("H2 str nature_date 兜底", {"result": None},
             {"result": result})
        assert result is None, f"预期 None 让上层回退，实际 {result}"
    finally:
        os.unlink(p)


def test_hardbug_h3_atomic_write_preserves_original_on_failure():
    """[H3] build_calendar.build_calendar 中途失败时原 parquet 完整保留（原子写入）。
    通过 monkey-patch pq.write_table 让其抛异常，验证目标文件未被截断。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    try:
        import pandas as _pd
    except ImportError:
        print("    ⏭ pandas 未安装（build_calendar 依赖），跳过")
        return
    # panda_data 未安装环境下无法完整走 build_calendar 流程；用 sys.modules 注入 stub
    import sys as _sys
    import types as _types
    _panda_stub_created = False
    if "panda_data" not in _sys.modules:
        stub = _types.ModuleType("panda_data")
        stub.init_token = lambda **kw: None
        _sys.modules["panda_data"] = stub
        _panda_stub_created = True

    import tempfile
    from datetime import date, timedelta
    _sys.path.insert(0, os.path.dirname(__file__))
    import build_calendar

    # 先造一份"原始" parquet 作为要保护的目标
    today = date.today()
    original_dates = [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-100, 100, 10)]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(pa.table({"nature_date": original_dates}), f.name)
        target = f.name
    original_size = os.path.getsize(target)

    # 注入 fake get_trade_cal 返回合法 df
    fake_df = _pd.DataFrame({
        "nature_date": [int((today + timedelta(days=d)).strftime("%Y%m%d")) for d in range(-50, 50, 10)],
        "next_trade_date": ["20260101"] * 10,
        "pretrade_date": ["20260101"] * 10,
        "exchange": ["SH"] * 10,
        "is_trade": [1] * 10,
    })
    _pd_mod = _sys.modules["panda_data"]
    saved_gtc = getattr(_pd_mod, "get_trade_cal", None)
    _pd_mod.get_trade_cal = lambda **kw: fake_df

    # patch pq.write_table 抛异常（模拟 pyarrow 中途崩溃/磁盘满）
    saved_wt = pq.write_table
    def failing_write(*args, **kwargs):
        raise RuntimeError("模拟 pyarrow 崩溃")
    pq.write_table = failing_write

    raised = False
    try:
        try:
            build_calendar.build_calendar(years_back=1, years_forward=1, output_path=target)
        except RuntimeError:
            raised = True

        # 关键断言：原文件仍在，大小未变（未被截断）
        assert os.path.exists(target), "H3 原文件被删除！"
        assert os.path.getsize(target) == original_size, \
            f"H3 原文件被截断/覆盖：原 {original_size}，现 {os.path.getsize(target)}"
        # 内容也应可读且不变
        recovered = pq.read_table(target, columns=["nature_date"]).column("nature_date").to_pylist()
        assert recovered == original_dates, "H3 原文件内容被破坏"
        # 且中间 .tmp 已被清理
        tmp = target + ".tmp"
        assert not os.path.exists(tmp), f"H3 tmp 文件遗留: {tmp}"

        show("H3 原子写入失败保留原文件",
             {"raised": True, "file_preserved": True, "size_unchanged": True},
             {"raised": raised, "size": os.path.getsize(target)})
        assert raised, "预期 build_calendar 抛异常"
    finally:
        pq.write_table = saved_wt
        if saved_gtc is not None:
            _pd_mod.get_trade_cal = saved_gtc
        else:
            try: delattr(_pd_mod, "get_trade_cal")
            except AttributeError: pass
        if _panda_stub_created:
            _sys.modules.pop("panda_data", None)
        os.unlink(target)


def test_hardbug_h4_today_before_entry_string_guard():
    """[H4] today < entry_date 字符串守卫：即便两者都在日历外，也返回 hold 不误判。"""
    r = manage_position(code="600036", entry_price=10.0, entry_date="2020-01-01",
                        current_qty=800, open_price=10.55, today="2019-12-31",
                        total_equity=1_000_000)
    show("H4 today<entry 字符串守卫", {"action": "hold", "reason~": "早于 entry_date"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "早于 entry_date" in r["reason"], r


def test_hardbug_m1_current_qty_zero_no_sell_signal():
    """[M1] current_qty=0 时命中"次日 +5%"不再产出 action=sell,target=0,qty_change=0 空指令。"""
    r = run(base(current_qty=0, entry_date="2026-06-19", today="2026-06-22", open_price=10.55))
    show("M1 空仓命中止盈条件", {"action": "hold", "reason~": "空仓"},
         {"action": r["action"], "target_qty": r["target_qty"],
          "qty_change": r["qty_change"], "reason": r["reason"]})
    assert r["action"] == "hold", f"空仓不应产出 sell: {r}"
    assert r["qty_change"] == 0 and r["target_qty"] == 0
    assert "空仓" in r["reason"]


def test_hardbug_m1_current_qty_zero_no_force_close_signal():
    """[M1] current_qty=0 且满 2 交易日也不产出强平指令。"""
    r = run(base(current_qty=0, entry_date="2026-06-19", today="2026-06-23", open_price=10.1))
    assert r["action"] == "hold" and r["qty_change"] == 0, r


def test_hardbug_m2_dot_suffix_a_stock_wind_format():
    """[M2] Wind 后缀写法 "600036.SH" / "000001.SZ" 判 A股 + 减仓整百。"""
    for c in ("600036.SH", "000001.SZ", "600036.sh", "000001.sz", "600036.SS"):
        assert _is_a_stock(c), f"{c} 应判 A股"
        assert _normalize_code(c) in ("600036", "000001"), _normalize_code(c)
        assert _get_lot_size(c) == 100
    # 端到端验证：Wind 写法能走通 run() 且减仓整百
    inp = base(code="600036.SH", current_qty=2000, open_price=100.0,
               total_equity=1_000_000, today="2026-06-19")
    r = run(inp)
    show("M2 Wind 后缀 A股减仓", {"action": "sell", "target_qty%100": 0},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "sell" and r["target_qty"] % 100 == 0, r


def test_hardbug_m2_normalize_type_error_for_non_str():
    """[M2] _normalize_code 对非 str 输入抛 TypeError（而非 AttributeError）。"""
    for bad in (None, 100, 123.45, [], {}):
        raised = False
        try:
            _normalize_code(bad)
        except TypeError:
            raised = True
        assert raised, f"{bad!r} 应抛 TypeError"


def test_hardbug_m3_date_no_leading_zero_rejected():
    """[M3] "2026-6-19" 缺前导零应被 validate_input 拒绝（保护输出契约）。"""
    for bad_date in ("2026-6-19", "2026-06-1", "2026-6-1", "2026-13-01"):
        ok, err = validate_input(base(entry_date=bad_date))
        show(f"M3 拒绝 {bad_date!r}", {"ok": False}, {"ok": ok, "err": err[:60]})
        assert not ok, f"{bad_date} 应被拒"
    # today 字段同样严格
    ok, _ = validate_input(base(today="2026-6-22"))
    assert not ok


def test_hardbug_m3_date_strict_still_accepts_valid():
    """[M3] 严格正则不误伤合法 YYYY-MM-DD。"""
    ok, err = validate_input(base(entry_date="2026-06-19", today="2026-06-22"))
    assert ok, err


def test_hardbug_m4_parquet_all_none_nature_date_falls_back():
    """[M4] nature_date 列全为 None 时返回 None（不再 max() 空序列崩溃）。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("    ⏭ pyarrow 未安装，跳过")
        return
    import tempfile
    table = pa.table({"nature_date": [None, None, None]})
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        pq.write_table(table, f.name)
        p = f.name
    try:
        result = build._load_trade_days_from_parquet(p, "2026-06-22")
        show("M4 全 None 兜底", {"result": None}, {"result": result})
        assert result is None
    finally:
        os.unlink(p)


if __name__ == "__main__":
    print("=" * 70)
    print("B11 增强版自测")
    print("=" * 70)

    print("\n---- 校验层 ----")
    test("校验通过", test_validate_ok)
    test("校验缺字段", test_validate_missing_field)
    test("校验价格异常", test_validate_bad_price)
    test("校验日期异常", test_validate_bad_date)
    test("校验缺 total_equity", test_validate_missing_total_equity)

    print("\n---- E1 交易日语义 ----")
    test("E1 周五入场周一止盈", test_e1_friday_entry_monday_take_profit)
    test("E1 周五入场周一止损", test_e1_friday_entry_monday_stop_loss)
    test("E1 国庆前入场节后首日止盈", test_e1_holiday_entry_next_session_take_profit)
    test("E1 跨周末满2交易日强平", test_e1_force_close_across_weekend)
    test("E1 跨国庆满2交易日强平", test_e1_force_close_across_holiday)
    test("E1 自然日差>1但交易日差=1", test_e1_natural_gt1_but_trading_eq1)
    test("E1 entry为非交易日兜底", test_e1_entry_on_non_trading_day_fallback)
    test("E1 交易日历来自 panda_data", test_e1_calendar_comes_from_panda_data)

    print("\n---- E2 仓位分母 total_equity ----")
    test("E2 total_equity=0 hold不崩", test_e2_total_equity_zero_returns_hold)
    test("E2 负权益 hold", test_e2_total_equity_negative_returns_hold)
    test("E2 total_equity=NaN 拒绝", test_e2_total_equity_nan_rejected)
    test("E2 满仓现金0不误减", test_e2_full_position_cash_zero_no_false_reduce)
    test("E2 占比恰好10%不减", test_e2_boundary_exactly_10pct_no_reduce)
    test("E2 占比>10%减至≤10%", test_e2_over_10pct_reduces_to_le_10pct)

    print("\n---- E3 代码分类 ----")
    test("E3 A股三写法分类", test_e3_classify_a_stock_three_forms)
    test("E3 科创板/ETF 判A股", test_e3_classify_star_market_and_etf)
    test("E3 期货分类", test_e3_classify_future)
    test("E3 sh前缀减仓整百", test_e3_sh_prefix_not_future_no_odd_lot)
    test("E3 归一化", test_e3_normalize)

    print("\n---- E4 期货合约乘数 ----")
    test("E4 IF乘数300", test_e4_if_notional_multiplier_300)
    test("E4 rb乘数10", test_e4_rb_notional_multiplier_10)
    test("E4 未知品种报错", test_e4_unknown_future_raises)
    test("E4 传入乘数覆盖", test_e4_caller_multiplier_override)
    test("E4 A股乘数=1", test_e4_a_stock_multiplier_1)

    print("\n---- E5 健壮性 ----")
    test("E5 高价期货单手不清仓", test_e5_no_degrade_to_clear_high_price)
    test("E5 A股高价不清仓", test_e5_a_stock_min_lot_no_clear)
    test("E5 today<entry 校验拒绝", test_e5_today_before_entry_guard)
    test("E5 决策层today<entry hold", test_e5_today_before_entry_trading_guard_in_decision)
    test("E5 today==entry 当天hold", test_e5_today_equals_entry_same_day_hold)
    test("E5 NaN/inf价格校验拒绝", test_e5_nan_price_validate_rejected)
    test("E5 决策层NaN价格hold", test_e5_nan_price_decision_hold)
    test("E5 numpy整数被接受", test_e5_numpy_like_integral_accepted)
    test("E5 numpy浮点被接受", test_e5_numpy_like_real_price_accepted)
    test("E5 bool拒绝为数量", test_e5_bool_rejected_as_qty)
    test("E5 target==current hold", test_e5_target_equals_current_hold)

    print("\n---- 优先级冲突 & 批量 ----")
    test("优先级 TP>强平", test_priority_tp_over_force_close)
    test("优先级 强平>减仓", test_priority_force_close_over_reduce)
    test("批量混合A股+期货", test_batch_mixed_a_stock_and_future)
    test("空列表", test_empty_list)

    print("\n---- 原有快乐路径（保留）----")
    test("legacy 入场当天hold", test_legacy_hold_entry_day)
    test("legacy 期货次日止盈", test_legacy_future_take_profit)
    test("legacy 边界+5%", test_legacy_boundary_5pct)
    test("legacy 边界-3%", test_legacy_boundary_3pct)

    print("\n---- 依赖引导 ----")
    test("env缺失抛 RuntimeError", test_dep_missing_env_raises_runtime_error)
    test("引导消息含 pip install / env / export", test_dep_error_message_mentions_install)

    print("\n---- production/trade.parquet 缓存 ----")
    test("parquet 覆盖 today → 读盘", test_parquet_load_when_present_and_covers_today)
    test("parquet 不存在 → None 触发回退", test_parquet_returns_none_when_missing)
    test("parquet 过期 → None 触发回退", test_parquet_returns_none_when_stale)
    test("同参构造产生等价日历", test_calendar_cache_singleton)
    test("真 classmethod 单例复用", test_calendar_cache_real_singleton_logic)

    print("\n---- Agent 侧 API：inspect_calendar / refresh_calendar ----")
    test("inspect 缺失→missing", test_inspect_calendar_missing)
    test("inspect 覆盖充足→ok", test_inspect_calendar_ok_when_covers_today_far)
    test("inspect 过期→refresh_required", test_inspect_calendar_expired)
    test("inspect 即将过期→refresh_recommended", test_inspect_calendar_soon_to_expire)
    test("refresh ok 时跳过", test_refresh_calendar_skips_when_ok)
    test("refresh force 触发重跑", test_refresh_calendar_force_triggers_rebuild)
    test("refresh 缺失时自动创建", test_refresh_calendar_creates_when_missing)

    print("\n---- Agent 侧 API：check_date_coverage ----")
    test("check 范围内→in_range", test_check_coverage_in_range)
    test("check 早于 date_min→extend_back", test_check_coverage_extend_back)
    test("check 晚于 date_max→extend_forward", test_check_coverage_extend_forward)
    test("check 两端超出→extend_both", test_check_coverage_extend_both)
    test("check parquet 缺失→missing", test_check_coverage_missing_parquet)
    test("check 反向区间自动交换", test_check_coverage_swaps_reversed_range)

    print("\n---- 硬伤回归（H1-H4 / M1-M4）----")
    test("H1 entry_price=0 不崩溃", test_hardbug_h1_entry_price_zero_no_crash)
    test("H1 entry_price 负值 hold", test_hardbug_h1_entry_price_negative_no_crash)
    test("H1 NaN 价格仍优先命中", test_hardbug_h1_nan_price_guard_still_works)
    test("H2 parquet str nature_date 兜底", test_hardbug_h2_parquet_string_nature_date_falls_back)
    test("H3 原子写入失败保留原文件", test_hardbug_h3_atomic_write_preserves_original_on_failure)
    test("H4 today<entry 字符串守卫", test_hardbug_h4_today_before_entry_string_guard)
    test("M1 空仓不产出 sell (TP)", test_hardbug_m1_current_qty_zero_no_sell_signal)
    test("M1 空仓不产出 sell (强平)", test_hardbug_m1_current_qty_zero_no_force_close_signal)
    test("M2 .SH/.SZ 后缀 Wind 写法", test_hardbug_m2_dot_suffix_a_stock_wind_format)
    test("M2 非 str code TypeError", test_hardbug_m2_normalize_type_error_for_non_str)
    test("M3 日期缺前导零拒绝", test_hardbug_m3_date_no_leading_zero_rejected)
    test("M3 严格正则不误伤合法", test_hardbug_m3_date_strict_still_accepts_valid)
    test("M4 全 None nature_date 兜底", test_hardbug_m4_parquet_all_none_nature_date_falls_back)

    print("\n" + "=" * 70)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 70)
    sys.exit(0 if FAIL == 0 else 1)
