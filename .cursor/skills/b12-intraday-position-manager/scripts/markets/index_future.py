"""
B12 v3 — 股指期货决策模块（IF / IC / IH / IM）

T+0：当日开仓可平。
    sellable = sellable_qty + locked_qty
    （T+0 品种调用方一般传 locked_qty=0；为容错，把锁仓也视为可卖）
合约最小单位 1 手；资金占用 = qty × price × multiplier × margin_rate + 手续费。

v3 变更：
    - 强平/全平：qty_change = -sellable，target_qty = 0（每手已是整数，close_all_qty 与 round_lot 等价，仍走 close_all_qty 语义统一）
    - 加仓：max_qty 封顶
"""
from common import (
    PNL_ADD_THRESHOLD, PNL_HALF_CUT_THRESHOLD, PNL_CLOSE_ALL_THRESHOLD,
    ADD_RATIO, HALF_CUT_RATIO,
    round_lot, close_all_qty, make_instr, make_hold,
)
from specs import CATEGORIES

MARKET = "INDEX_FUTURE"


def _contract_spec(code: str) -> dict:
    """从代码前 2 位（IF/IC/IH/IM）取合约规格。"""
    prefix = code[:2]
    return CATEGORIES[MARKET]["contracts"][prefix]


def _required_margin(qty: int, price: float, code: str) -> float:
    """开仓所需保证金 + 手续费。"""
    if qty <= 0 or price <= 0:
        return 0.0
    spec = _contract_spec(code)
    cat  = CATEGORIES[MARKET]
    notional = qty * price * spec["multiplier"]
    margin = notional * spec["margin_rate"]
    fee = notional * cat["fee_rate"]
    return margin + fee


def manage(item: dict) -> dict:
    code     = item["code"]
    pnl_pct  = float(item["pnl_pct"])
    sellable = max(0, int(item["sellable_qty"]) + int(item["locked_qty"]))
    price    = float(item["price"])
    cash     = float(item["available_cash"])
    time_str = item["time"]
    max_qty  = item.get("max_qty", None)

    cat     = CATEGORIES[MARKET]
    lot     = cat["lot_size"]
    force_t = cat["force_close_time"]
    total   = sellable

    # 1) 强平（平到 0）
    if time_str >= force_t:
        if sellable <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"{force_t} 强平 无持仓 hold",
                market=MARKET, sellable=sellable, flags=["force_close"],
            )
        close = close_all_qty(sellable)
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -close, 0,
            f"强平清仓 {close} 手（{force_t}）",
            market=MARKET, sellable=sellable, flags=["force_close"],
        )

    # 2) 全平（平到 0）
    if pnl_pct <= PNL_CLOSE_ALL_THRESHOLD:
        if sellable <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮亏 {pnl_pct*100:.2f}% 全平 无持仓 hold",
                market=MARKET, sellable=sellable, flags=["stop_loss_full"],
            )
        close = close_all_qty(sellable)
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -close, 0,
            f"浮亏 {pnl_pct*100:.2f}% 全平 {close} 手",
            market=MARKET, sellable=sellable, flags=["stop_loss_full"],
        )

    # 3) 砍半仓（round_lot）
    if pnl_pct <= PNL_HALF_CUT_THRESHOLD:
        raw = int(sellable * HALF_CUT_RATIO)
        cut = round_lot(raw, lot)
        if cut <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮亏 {pnl_pct*100:.2f}% 砍半计算 {raw} 手不足一手 hold",
                market=MARKET, sellable=sellable,
                flags=["stop_loss_half", "lot_short"],
            )
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -cut, total - cut,
            f"浮亏 {pnl_pct*100:.2f}% 砍半仓 {cut} 手",
            market=MARKET, sellable=sellable, flags=["stop_loss_half"],
        )

    # 4) 加仓（round_lot + max_qty 封顶）
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
                    market=MARKET, sellable=sellable,
                    flags=["add_position", "capped_by_max_qty"],
                    capped_by_max_qty=True,
                )
        if add <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮盈 {pnl_pct*100:.2f}% 加仓计算 {raw} 手不足一手 hold",
                market=MARKET, sellable=sellable,
                flags=["add_position", "lot_short"],
            )
        need = _required_margin(add, price, code)
        if need > cash:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮盈 {pnl_pct*100:.2f}% 加仓 {add} 手需保证金 {need:.2f} 现金 {cash:.2f} 不足 hold",
                market=MARKET, sellable=sellable, cash_req=need,
                flags=["add_position", "cash_insufficient"],
            )
        capped = (max_qty is not None and add < add_by_ratio)
        flags = ["add_position"] + (["capped_by_max_qty"] if capped else [])
        return make_instr(
            code, pnl_pct, total, time_str, "buy", add, total + add,
            f"加仓 {add} 手（浮盈 {pnl_pct*100:+.2f}%）"
            + (f"，max_qty={max_qty} 封顶" if capped else ""),
            market=MARKET, sellable=sellable, cash_req=need,
            flags=flags, capped_by_max_qty=capped,
        )

    # 5) 默认 hold
    return make_hold(
        code, pnl_pct, total, time_str,
        f"浮盈/亏 {pnl_pct*100:+.2f}% 未触发任何条件 hold",
        market=MARKET, sellable=sellable,
    )
