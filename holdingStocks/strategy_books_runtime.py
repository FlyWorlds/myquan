"""Independent quote-driven strategy lifecycle; never edits the paper portfolio."""
from __future__ import annotations

import copy
import math
import threading
import time
from datetime import datetime

from condition_buy import fresh_quote, is_trigger, timestamp
from quote_exit import evaluate_quote_exit, overnight_note_updates
from strategy.exit_rules.overnight_open_protect import evaluate_overnight_open_protect
from strategy.open_break import cannot_buy_limit_up, limit_down_state
from strategy.board_rules import limit_down_pct_of


class StrategyBooksRuntime:
    def __init__(self, client, *, vol_for, signal_window, order_valid=lambda _: True):
        self.client, self.vol_for, self.signal_window = client, vol_for, signal_window
        self.lock = threading.RLock()
        self.orders = {}
        self.active = set()
        self.last_write = {}
        self.order_valid = order_valid

    def prepare(self, drafts, active):
        with self.lock:
            self.active = set(active)
            self.orders = {code: value for code, value in self.orders.items() if code in active}
            for order in drafts:
                if order["code"] in active:
                    old = self.orders.get(order["code"], {})
                    same_reference = old.get("session") == order.get("session") and old.get("daily_sig") == order.get("daily_sig")
                    if order.get("status") != "BLOCKED" and same_reference and (
                            old.get("id") == order.get("id")
                            or (old.get("kind") == "auction_open" and old.get("open") == order.get("open")
                                and datetime.now().strftime("%H:%M:%S") <= "09:30:05")):
                        continue
                    self.orders[order["code"]] = copy.deepcopy(order)

    def on_quote(self, sina, quote, received_at):
        now = datetime.now()
        day = now.date().isoformat()
        if not self.client.ready:
            return
        if not fresh_quote(quote, day, now):
            # A delayed official close may value inventory, but cannot update peaks or execute.
            at = timestamp(quote.get("last_ts"))
            if (not self.signal_window(now) and at and at <= now
                    and (at.strftime("%H:%M:%S") == "11:30:00" or "14:57:00" <= at.strftime("%H:%M:%S") <= "15:00:00")
                    and fresh_quote(quote, str(quote.get("session")), at)):
                code = sina[-6:]
                book = self.client.get(code)
                with self.lock:
                    active = code in self.active
                if ((active or book.get("virtual_shares")) and str(quote["last_ts"]) >= str(book.get("last_quote_ts") or "")
                        and float(book.get("last_mark") or 0) != float(quote["last"])):
                    self.client.command(code, book, quote=quote, now=now)
            return
        if not 0 <= (now-received_at).total_seconds() <= 5:
            return
        code = sina[-6:]
        book = self.client.get(code)
        with self.lock:
            order = copy.deepcopy(self.orders.get(code))
            active = code in self.active
        if not active and not book.get("virtual_shares"):
            return
        prior_ts = str(book.get("last_quote_ts") or "")
        if str(quote["last_ts"]) < prior_ts:
            return
        qty = int(book.get("virtual_shares") or 0)
        action, updates = None, {}
        if qty > 0:
            pos = dict(book, code=code, qty=qty, cost=book.get("entry_price"), buy_time=book.get("entry_time"))
            note_updates = overnight_note_updates(pos, quote, day)
            pos.update(note_updates)
            result = evaluate_quote_exit(pos, quote, session=day, now=now, received_at=received_at,
                                         vol20_daily=self.vol_for(sina, day))
            if result:
                updates = dict(result["updates"], quote_exit_watermark=result["watermark"])
                updates.update(note_updates)
                action = result["action"]
            if str(book.get("entry_time") or "")[:10] < day and book.get("overnight_peak_session") != day:
                updates.update(overnight_peak=float(book.get("peak_high") or book.get("entry_price") or 0),
                               overnight_peak_session=day)
            # Opening protection uses only a timely quote and a pre-session peak.
            if (self.signal_window(now) and str(book.get("entry_time") or "")[:10] < day
                    and "09:30:00" <= now.strftime("%H:%M:%S") <= "09:30:05"
                    and "09:30:00" <= quote["last_ts"][11:19] <= "09:30:05"):
                frozen = book.get("overnight_peak") if book.get("overnight_peak_session") == day else book.get("peak_high")
                limit = limit_down_state(prev_close=quote.get("prev_close"), open_px=quote["open"],
                    high_px=quote["high"], low_px=quote["low"], close_px=quote["last"], limit_down_pct=limit_down_pct_of(code))
                opened = evaluate_overnight_open_protect(dict(cost=book.get("entry_price"), open_px=quote["open"],
                    prev_close=quote.get("prev_close"), peak_high=frozen or book.get("entry_price"), qty=qty,
                    buy_time=book.get("entry_time"), session=day, overnight_high_ok=True))
                if opened.triggered and not limit["locked"] and not book.get("hold_lock"):
                    action = dict(kind="full", shares=qty, fill_px=quote["open"], reason="open_protect")
            if updates.get("peak_high", 0) > float(book.get("peak_high") or 0):
                updates["peak_high_at"] = quote["last_ts"]
        elif active and order and self.order_valid(order) and self.signal_window(now) and is_trigger(order, quote, received_at, now):
            price = float(order["price"])
            sold_today = str(book.get("exit_time") or "").startswith(day)
            if sold_today and book.get("gap_rebuy_allowed") and order.get("kind") == "breakout":
                sold_today = False
            if not sold_today and not cannot_buy_limit_up(prev_close=quote.get("prev_close"),
                    open_px=quote["open"], high_px=quote["high"], low_px=quote["low"], close_px=quote["last"],
                    limit_up_pct=order.get("limit_up_pct") or .10, tick=order["tick"]):
                shares = math.floor(float(book.get("virtual_cash", 100000.))* .95 / price / 100)*100
                if shares >= 100:
                    action = dict(kind="buy", shares=shares, fill_px=price, reason="prepared_quote_order")
        if action and not self.signal_window(now):
            action = None
        decision_now = datetime.now()
        if (not fresh_quote(quote, day, decision_now)
                or not 0 <= (decision_now-received_at).total_seconds() <= 5):
            return
        now = decision_now
        if action and not self.signal_window(now):
            return
        if action:
            self.client.command(code, book, quote=quote, now=now,
                side="BUY" if action["kind"] == "buy" else "SELL", price=action["fill_px"],
                qty=action["shares"], state=updates, reason=action["reason"])
            self.last_write[code] = time.monotonic()
        elif (str(quote["last_ts"]) >= prior_ts and
                (float(book.get("last_mark") or 0) != float(quote["last"])
                 or any(book.get(k) != v for k,v in updates.items() if k != "quote_exit_watermark"))):
            # Never throttle lifecycle/peak changes: a later quote cannot recover a missed peak.
            critical = any(book.get(k) != v for k, v in updates.items() if k != "quote_exit_watermark")
            if critical or time.monotonic()-self.last_write.get(code, 0) >= 1:
                self.client.command(code, book, quote=quote, now=now, state=updates)
                self.last_write[code] = time.monotonic()
