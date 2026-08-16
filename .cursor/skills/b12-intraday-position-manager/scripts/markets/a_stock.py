"""
B12 v3 — A股 / A股ETF 决策模块

T+1 规则：今日新建仓位被锁定（locked_qty），当日不可卖。
    sellable = sellable_qty
    total    = sellable_qty + locked_qty
LOT_SIZE = 100。加仓/砍半 走 round_lot，强平/全平 直接平到 0（保留锁仓）。

v3 变更：
    - 强平/全平：qty_change = -sellable（不再 round_lot）；target_qty = locked（T+1 保留）
    - 加仓：max_qty 封顶截断，先命中优先
"""
from common import (
    PNL_ADD_THRESHOLD, PNL_HALF_CUT_THRESHOLD, PNL_CLOSE_ALL_THRESHOLD,
    ADD_RATIO, HALF_CUT_RATIO,
    round_lot, close_all_qty, make_instr, make_hold,
)
from specs import CATEGORIES


def _required_cash(qty: int, price: float, cat: dict) -> float:
    """买入所需现金 = qty × price + 手续费（费率与最低费两者取大）。"""
    if qty <= 0 or price <= 0:
        return 0.0
    notional = qty * price
    fee = max(notional * cat["fee_rate"], cat["min_fee"])
    return notional + fee


def manage(item: dict, market: str) -> dict:
    """A股 / A股ETF 共用决策逻辑。market 取值 A_STOCK 或 A_ETF。"""
    code     = item["code"]
    pnl_pct  = float(item["pnl_pct"])
    sellable = int(item["sellable_qty"])
    locked   = int(item["locked_qty"])
    price    = float(item["price"])
    cash     = float(item["available_cash"])
    time_str = item["time"]
    max_qty  = item.get("max_qty", None)

    cat     = CATEGORIES[market]
    lot     = cat["lot_size"]
    force_t = cat["force_close_time"]
    total   = sellable + locked

    # ── 1) 强平：到点收盘前 15 分钟（平到 0，保留锁仓） ──
    if time_str >= force_t:
        if sellable <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"{force_t} 强平 但锁仓 {locked} 股 T+1 不可卖 hold",
                market=market, sellable=sellable, flags=["force_close", "t1_blocked"],
            )
        sell = close_all_qty(sellable)  # 不 round_lot，允许零股
        block = f"（T+1 阻断 {locked} 股）" if locked > 0 else ""
        flags = ["force_close"] + (["t1_blocked"] if locked > 0 else [])
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -sell, locked,
            f"强平清仓 {sell} 股（{force_t}）{block}",
            market=market, sellable=sellable, flags=flags,
        )

    # ── 2) 全平：浮亏 >= 1%（平到 0，保留锁仓） ──
    if pnl_pct <= PNL_CLOSE_ALL_THRESHOLD:
        if sellable <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮亏 {pnl_pct*100:.2f}% 全平 但锁仓 T+1 不可卖 hold",
                market=market, sellable=sellable, flags=["stop_loss_full", "t1_blocked"],
            )
        sell = close_all_qty(sellable)
        block = f"（T+1 阻断 {locked} 股）" if locked > 0 else ""
        flags = ["stop_loss_full"] + (["t1_blocked"] if locked > 0 else [])
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -sell, locked,
            f"浮亏 {pnl_pct*100:.2f}% 全平 {sell} 股{block}",
            market=market, sellable=sellable, flags=flags,
        )

    # ── 3) 砍半仓：浮亏 >= 0.5%（round_lot 下取整） ──
    if pnl_pct <= PNL_HALF_CUT_THRESHOLD:
        raw = int(sellable * HALF_CUT_RATIO)
        cut = round_lot(raw, lot)
        if cut <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮亏 {pnl_pct*100:.2f}% 砍半计算 {raw} 股不足一手 hold",
                market=market, sellable=sellable,
                flags=["stop_loss_half", "lot_short"],
            )
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -cut, total - cut,
            f"浮亏 {pnl_pct*100:.2f}% 砍半仓 {cut} 股",
            market=market, sellable=sellable, flags=["stop_loss_half"],
        )

    # ── 4) 加仓：浮盈 > 1%（基数为 sellable；先 max_qty 截断再校验现金） ──
    if pnl_pct > PNL_ADD_THRESHOLD:
        raw = int(sellable * ADD_RATIO)
        add_by_ratio = round_lot(raw, lot)
        if max_qty is None:
            add = add_by_ratio
        else:
            headroom = max_qty - total
            add_by_cap = round_lot(max(0, headroom), lot)
            add = min(add_by_ratio, add_by_cap)
            if add <= 0:
                return make_hold(
                    code, pnl_pct, total, time_str,
                    f"浮盈 {pnl_pct*100:.2f}% 加仓被 max_qty={max_qty} 封顶 hold",
                    market=market, sellable=sellable,
                    flags=["add_position", "capped_by_max_qty"],
                    capped_by_max_qty=True,
                )
        if add <= 0:
            # 无 max_qty 场景下仍不足一手
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮盈 {pnl_pct*100:.2f}% 加仓计算 {raw} 股不足一手 hold",
                market=market, sellable=sellable,
                flags=["add_position", "lot_short"],
            )
        need = _required_cash(add, price, cat)
        if need > cash:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮盈 {pnl_pct*100:.2f}% 加仓 {add} 股需 {need:.2f} 现金 {cash:.2f} 不足 hold",
                market=market, sellable=sellable, cash_req=need,
                flags=["add_position", "cash_insufficient"],
            )
        capped = (max_qty is not None and add < add_by_ratio)
        flags = ["add_position"] + (["capped_by_max_qty"] if capped else [])
        return make_instr(
            code, pnl_pct, total, time_str, "buy", add, total + add,
            f"加仓 {add} 股（浮盈 {pnl_pct*100:+.2f}%）"
            + (f"，max_qty={max_qty} 封顶" if capped else ""),
            market=market, sellable=sellable, cash_req=need,
            flags=flags, capped_by_max_qty=capped,
        )

    # ── 5) 默认 hold ──
    return make_hold(
        code, pnl_pct, total, time_str,
        f"浮盈/亏 {pnl_pct*100:+.2f}% 未触发任何条件 hold",
        market=market, sellable=sellable,
    )
