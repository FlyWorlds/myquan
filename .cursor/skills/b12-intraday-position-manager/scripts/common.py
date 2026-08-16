"""
B12 v3 — 共享常量、工具、调仓指令构造器

v3 变更：
    - 强平/全平改为「平到 0」，不再走 round_lot 手数下取整（新函数 close_all_qty）
    - 砍半 / 加仓 仍走 round_lot 保持手数整数倍
    - make_instr / make_hold 签名扩展：新增顶层字段 market / sellable / cash_req / flags / capped_by_max_qty
    - reason 恢复为纯人类可读文本；`[MARKET][sellable=N][cash_req=X]` 前缀由模块级开关
      INCLUDE_REASON_PREFIX 控制（默认 True，一版后关闭）

阈值参考 jobs/B12 日内仓位动态管理.txt：
    浮盈 > 1%    → 加仓 50%
    浮亏 >= 0.5% → 砍半仓
    浮亏 >= 1%   → 全平
    收盘前 15 分钟 → 强平
"""

# ── 阈值常量 ─────────────────────────────────────────────────────────
PNL_ADD_THRESHOLD       = 0.01    # 浮盈 > 1% 加仓（严格大于）
PNL_HALF_CUT_THRESHOLD  = -0.005  # 浮亏 >= 0.5% 砍半（含边界）
PNL_CLOSE_ALL_THRESHOLD = -0.01   # 浮亏 >= 1% 全平（含边界）
ADD_RATIO               = 0.5
HALF_CUT_RATIO          = 0.5


# ── reason 前缀开关（v3 过渡期，一版后关闭） ─────────────────────────
INCLUDE_REASON_PREFIX = True


# ── 数量取整 ─────────────────────────────────────────────────────────
def round_lot(qty: int, lot: int) -> int:
    """向下取整到一手的整数倍。lot<=1 时直接返回非负整数。用于加仓/砍半场景。"""
    qty = max(0, int(qty))
    if lot <= 1:
        return qty
    return (qty // lot) * lot


def close_all_qty(sellable: int) -> int:
    """强平/全平专用：直接返回 max(0, sellable)，不做手数下取整。

    A股清仓允许零股（券商实际处理），期货每手已是整数，
    港股同一订单允许非整手清仓。
    """
    return max(0, int(sellable))


# ── 调仓指令 dict 构造（8 基础字段 + 5 v3 顶层字段） ──────────────────
def make_instr(code, pnl_pct, current_qty, time_str,
               action, qty_change, target_qty, reason,
               market="UNKNOWN", sellable=0, cash_req=0.0,
               flags=None, capped_by_max_qty=False) -> dict:
    """
    生成调仓指令 dict：
        基础 8 字段：code / pnl_pct / current_qty / time / action /
                     qty_change / target_qty / reason
        v3 新增 5 字段：market / sellable / cash_req / flags / capped_by_max_qty
    """
    if flags is None:
        flags = []
    if INCLUDE_REASON_PREFIX:
        prefix = reason_prefix(market, sellable, cash_req)
        reason_out = f"{prefix} {reason}"
    else:
        reason_out = reason
    return {
        "code": code,
        "pnl_pct": pnl_pct,
        "current_qty": current_qty,
        "time": time_str,
        "action": action,
        "qty_change": qty_change,
        "target_qty": target_qty,
        "reason": reason_out,
        # v3 顶层元数据
        "market": market,
        "sellable": sellable,
        "cash_req": cash_req,
        "flags": list(flags),
        "capped_by_max_qty": bool(capped_by_max_qty),
    }


def make_hold(code, pnl_pct, total, time_str, reason,
              market="UNKNOWN", sellable=0, cash_req=0.0,
              flags=None, capped_by_max_qty=False) -> dict:
    """快捷：构造 hold 指令。"""
    return make_instr(
        code, pnl_pct, total, time_str, "hold", 0, total, reason,
        market=market, sellable=sellable, cash_req=cash_req,
        flags=flags, capped_by_max_qty=capped_by_max_qty,
    )


# ── reason 结构化前缀（deprecated，v3 保留一版） ─────────────────────
def reason_prefix(market: str, sellable: int, cash_req: float = 0.0) -> str:
    """生成 [MARKET][sellable=N][cash_req=X] 前缀。

    v3 起标记为 deprecated —— 顶层字段 market/sellable/cash_req 已提供结构化数据。
    仍保留一版由 INCLUDE_REASON_PREFIX 开关控制，下版删除。
    """
    return f"[{market}][sellable={sellable}][cash_req={cash_req:.2f}]"
