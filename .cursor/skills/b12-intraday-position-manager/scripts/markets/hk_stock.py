"""
B12 v3 — 港股 / 港股ETF 决策模块

T+0：当日买入可卖。
    sellable = sellable_qty + locked_qty
LOT_SIZE 按 hk_lot_overrides 覆盖表查，未命中默认 100。
强平时间 15:45（港股下午半场 16:00 收盘）。

v3 变更：
    - 强平/全平：qty_change = -sellable，target_qty = 0（不 round_lot）
    - 加仓：max_qty 封顶
"""
from common import (
    PNL_ADD_THRESHOLD, PNL_HALF_CUT_THRESHOLD, PNL_CLOSE_ALL_THRESHOLD,
    ADD_RATIO, HALF_CUT_RATIO,
    round_lot, close_all_qty, make_instr, make_hold,
)
from specs import CATEGORIES, HK_LOT_OVERRIDES

MARKET = "HK_STOCK"


def _normalize_code(code: str) -> str:
    """归一化为 5 位数字代码用于查 hk_lot_overrides。"""
    c = code.upper().replace("HK", "")
    digits = "".join(ch for ch in c if ch.isdigit())
    return digits.zfill(5)[-5:]


def _lot_size(code: str) -> int:
    return HK_LOT_OVERRIDES.get(_normalize_code(code), CATEGORIES[MARKET]["lot_size"])


def _required_cash(qty: int, price: float, cat: dict) -> float:
    if qty <= 0 or price <= 0:
        return 0.0
    notional = qty * price
    fee = max(notional * cat["fee_rate"], cat["min_fee"])
    return notional + fee


def manage(item: dict) -> dict:
    code     = item["code"]
    pnl_pct  = float(item["pnl_pct"])
    sellable = max(0, int(item["sellable_qty"]) + int(item["locked_qty"]))
    price    = float(item["price"])
    cash     = float(item["available_cash"])
    time_str = item["time"]
    max_qty  = item.get("max_qty", None)

    cat     = CATEGORIES[MARKET]
    lot     = _lot_size(code)
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
        sell = close_all_qty(sellable)
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -sell, 0,
            f"强平清仓 {sell} 股（{force_t}）",
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
        sell = close_all_qty(sellable)
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -sell, 0,
            f"浮亏 {pnl_pct*100:.2f}% 全平 {sell} 股",
            market=MARKET, sellable=sellable, flags=["stop_loss_full"],
        )

    # 3) 砍半仓（round_lot）
    if pnl_pct <= PNL_HALF_CUT_THRESHOLD:
        raw = int(sellable * HALF_CUT_RATIO)
        cut = round_lot(raw, lot)
        if cut <= 0:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮亏 {pnl_pct*100:.2f}% 砍半计算 {raw} 股不足一手 hold",
                market=MARKET, sellable=sellable,
                flags=["stop_loss_half", "lot_short"],
            )
        return make_instr(
            code, pnl_pct, total, time_str, "sell", -cut, total - cut,
            f"浮亏 {pnl_pct*100:.2f}% 砍半仓 {cut} 股",
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
                f"浮盈 {pnl_pct*100:.2f}% 加仓计算 {raw} 股不足一手 hold",
                market=MARKET, sellable=sellable,
                flags=["add_position", "lot_short"],
            )
        need = _required_cash(add, price, cat)
        if need > cash:
            return make_hold(
                code, pnl_pct, total, time_str,
                f"浮盈 {pnl_pct*100:.2f}% 加仓 {add} 股需 {need:.2f} 现金 {cash:.2f} 不足 hold",
                market=MARKET, sellable=sellable, cash_req=need,
                flags=["add_position", "cash_insufficient"],
            )
        capped = (max_qty is not None and add < add_by_ratio)
        flags = ["add_position"] + (["capped_by_max_qty"] if capped else [])
        return make_instr(
            code, pnl_pct, total, time_str, "buy", add, total + add,
            f"加仓 {add} 股（浮盈 {pnl_pct*100:+.2f}%）"
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
