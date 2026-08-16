"""
B12 v3 — 商品期货决策模块（rb / cu / m / au / ag / i 等）

T+0：当日开仓可平。
    sellable = sellable_qty + locked_qty
合约规格按品种前缀（小写字母）查表。

v3 变更：
    - 强平/全平：qty_change = -sellable，target_qty = 0
    - 加仓：max_qty 封顶
"""
import re

from common import (
    PNL_ADD_THRESHOLD, PNL_HALF_CUT_THRESHOLD, PNL_CLOSE_ALL_THRESHOLD,
    ADD_RATIO, HALF_CUT_RATIO,
    round_lot, close_all_qty, make_instr, make_hold,
)
from specs import CATEGORIES

MARKET = "COMMODITY_FUTURE"

_RE_PREFIX = re.compile(r"^([a-z]{1,3})\d{3,4}$")


def _contract_spec(code: str) -> dict:
    """提取小写字母前缀，查合约规格。调用前 classify 已确保命中白名单。"""
    m = _RE_PREFIX.match(code)
    prefix = m.group(1)
    return CATEGORIES[MARKET]["contracts"][prefix]


def _required_margin(qty: int, price: float, code: str) -> float:
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

    # 1) 强平
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

    # 2) 全平
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

    # 3) 砍半仓
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

    # 4) 加仓
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
