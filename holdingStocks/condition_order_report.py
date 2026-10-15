"""Read-only condition-order export for comparison with a separate paper account."""
from __future__ import annotations

import csv
import io
from datetime import datetime


def comparison_report(snapshot, now=None):
    now = now or datetime.now()
    snapshot = snapshot or {}
    book = snapshot.get("conditionBuy") or {}
    day = now.date().isoformat()
    current = book.get("session") == day
    ready = bool(book.get("enabled") and current and now.strftime("%H:%M:%S") >= "09:25:00")
    rows = []
    if ready:
        for order in sorted(book.get("orders") or [], key=lambda o: str(o.get("code") or "")):
            if order.get("session") != day:
                continue
            rows.append({
                "session": day, "order_id": order.get("id"), "code": order.get("code"),
                "name": order.get("name"), "status": order.get("status"),
                "reason": order.get("reason"), "kind": order.get("kind"),
                "official_open": order.get("open"), "previous_close": order.get("previous_close"),
                "entry_pct": order.get("entry_pct"), "target_price": order.get("price"),
                "gate": order.get("gate"), "previous_shape": order.get("previous_shape"),
                "armed_at": order.get("armed_at"), "source_quote_at": order.get("armed_quote_at"),
                "open_audit_at": order.get("open_audit_at"),
                "ths_armed_at": "", "ths_trigger_at": "", "ths_fill_at": "",
                "ths_fill_price": "", "ths_fill_qty": "", "comparison_note": "",
            })
    return dict(session=day, generated_at=now.isoformat(sep=" ", timespec="seconds"),
                ready=ready, complete=False,
                note="Orders prepared so far, not a complete pool or a guaranteed fill. ARMED only for new manual orders.",
                fill_assumption="paper_stop_at_order_price", orders=rows)


def comparison_csv(report):
    columns = ("session", "order_id", "code", "name", "status", "reason", "kind",
               "official_open", "previous_close", "entry_pct", "target_price", "gate",
               "previous_shape", "armed_at", "source_quote_at", "open_audit_at",
               "ths_armed_at", "ths_trigger_at", "ths_fill_at", "ths_fill_price",
               "ths_fill_qty", "comparison_note")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in report["orders"]:
        # Preserve six-digit codes and prevent provider text becoming spreadsheet formulas.
        safe = {k: ("'" + str(v) if k == "code" or isinstance(v, str)
                    and v.lstrip().startswith(("=", "+", "-", "@")) else v)
                for k, v in row.items()}
        writer.writerow(safe)
    return output.getvalue().encode("utf-8-sig")
