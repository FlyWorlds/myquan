"""Trading Plans Management: Persistent store for pre-market and intraday trade planning."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

DB_PATH = Path(__file__).parent / "trading_plans.sqlite3"
_LOCK = RLock()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _LOCK, _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trading_plans (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                code TEXT,
                name TEXT,
                date TEXT NOT NULL,
                direction TEXT DEFAULT '买入',
                target_price REAL,
                stop_loss REAL,
                target_profit REAL,
                planned_position TEXT,
                strategy_tag TEXT,
                content TEXT,
                status TEXT DEFAULT 'pending',
                pinned INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tp_pinned ON trading_plans(pinned)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tp_date ON trading_plans(date)")
        conn.commit()


_init_db()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "code": row["code"] or "",
        "name": row["name"] or "",
        "date": row["date"],
        "direction": row["direction"] or "买入",
        "target_price": row["target_price"],
        "stop_loss": row["stop_loss"],
        "target_profit": row["target_profit"],
        "planned_position": row["planned_position"] or "",
        "strategy_tag": row["strategy_tag"] or "",
        "content": row["content"] or "",
        "status": row["status"] or "pending",
        "pinned": bool(row["pinned"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_plans() -> list[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute("""
            SELECT * FROM trading_plans
            ORDER BY pinned DESC, date DESC, created_at DESC
        """)
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_plan(plan_id: str) -> dict[str, Any] | None:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute("SELECT * FROM trading_plans WHERE id = ?", (plan_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def save_plan(body: dict[str, Any]) -> dict[str, Any]:
    with _LOCK, _get_connection() as conn:
        plan_id = str(body.get("id") or "").strip()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        action = str(body.get("action") or "").strip()

        if action == "delete":
            if not plan_id:
                raise ValueError("缺少计划 id")
            conn.execute("DELETE FROM trading_plans WHERE id = ?", (plan_id,))
            conn.commit()
            return {"id": plan_id, "deleted": True}

        if action == "toggle_pin":
            if not plan_id:
                raise ValueError("缺少计划 id")
            cur = conn.execute("SELECT pinned FROM trading_plans WHERE id = ?", (plan_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("计划不存在")
            new_pin = 0 if row["pinned"] else 1
            if "pinned" in body:
                new_pin = 1 if body["pinned"] else 0
            conn.execute(
                "UPDATE trading_plans SET pinned = ?, updated_at = ? WHERE id = ?",
                (new_pin, now, plan_id),
            )
            conn.commit()
            return get_plan(plan_id) or {"id": plan_id, "pinned": bool(new_pin)}

        if action == "toggle_status":
            if not plan_id:
                raise ValueError("缺少计划 id")
            new_status = str(body.get("status") or "").strip()
            if new_status not in ("pending", "executed", "cancelled"):
                raise ValueError(f"无效的状态: {new_status}")
            conn.execute(
                "UPDATE trading_plans SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, plan_id),
            )
            conn.commit()
            return get_plan(plan_id) or {"id": plan_id, "status": new_status}

        # 新增或完整更新（若已有记录且某字段未提供，则保留原记录字段）
        existing = None
        if plan_id:
            cur = conn.execute("SELECT * FROM trading_plans WHERE id = ?", (plan_id,))
            existing = cur.fetchone()

        title = str(body.get("title") or "").strip()
        if not title and existing:
            title = existing["title"]
        elif not title:
            code = str(body.get("code") or "").strip()
            name = str(body.get("name") or "").strip()
            if code or name:
                title = f"{name} ({code})".strip() if code and name else (name or code)
            else:
                title = "未命名交易计划"

        plan_date = str(body.get("date") or "").strip()
        if not plan_date and existing:
            plan_date = existing["date"]
        elif not plan_date:
            plan_date = datetime.now().strftime("%Y-%m-%d")

        code = str(body.get("code") if "code" in body else (existing["code"] if existing else "")).strip()
        name = str(body.get("name") if "name" in body else (existing["name"] if existing else "")).strip()
        direction = str(body.get("direction") if "direction" in body else (existing["direction"] if existing else "买入")).strip()

        target_price = existing["target_price"] if existing and "target_price" not in body else None
        if "target_price" in body:
            raw_tp = body.get("target_price")
            if raw_tp is not None and str(raw_tp).strip() != "":
                try:
                    target_price = float(raw_tp)
                except (ValueError, TypeError):
                    target_price = None

        stop_loss = existing["stop_loss"] if existing and "stop_loss" not in body else None
        if "stop_loss" in body:
            raw_sl = body.get("stop_loss")
            if raw_sl is not None and str(raw_sl).strip() != "":
                try:
                    stop_loss = float(raw_sl)
                except (ValueError, TypeError):
                    stop_loss = None

        target_profit = existing["target_profit"] if existing and "target_profit" not in body else None
        if "target_profit" in body:
            raw_tpf = body.get("target_profit")
            if raw_tpf is not None and str(raw_tpf).strip() != "":
                try:
                    target_profit = float(raw_tpf)
                except (ValueError, TypeError):
                    target_profit = None

        planned_position = str(body.get("planned_position") if "planned_position" in body else (existing["planned_position"] if existing else "")).strip()
        strategy_tag = str(body.get("strategy_tag") if "strategy_tag" in body else (existing["strategy_tag"] if existing else "")).strip()
        content = str(body.get("content") if "content" in body else (existing["content"] if existing else "")).strip()
        status = str(body.get("status") if "status" in body else (existing["status"] if existing else "pending")).strip()
        pinned = (1 if body.get("pinned") else 0) if "pinned" in body else (existing["pinned"] if existing else 0)

        if not plan_id:
            plan_id = uuid.uuid4().hex
            created_at = now
            conn.execute("""
                INSERT INTO trading_plans (
                    id, title, code, name, date, direction, target_price, stop_loss,
                    target_profit, planned_position, strategy_tag, content, status,
                    pinned, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan_id, title, code, name, plan_date, direction, target_price, stop_loss,
                target_profit, planned_position, strategy_tag, content, status,
                pinned, created_at, now
            ))
        else:
            # 检查记录是否存在
            cur = conn.execute("SELECT created_at FROM trading_plans WHERE id = ?", (plan_id,))
            row = cur.fetchone()
            if row:
                conn.execute("""
                    UPDATE trading_plans SET
                        title = ?, code = ?, name = ?, date = ?, direction = ?,
                        target_price = ?, stop_loss = ?, target_profit = ?,
                        planned_position = ?, strategy_tag = ?, content = ?,
                        status = ?, pinned = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    title, code, name, plan_date, direction, target_price, stop_loss,
                    target_profit, planned_position, strategy_tag, content, status,
                    pinned, now, plan_id
                ))
            else:
                conn.execute("""
                    INSERT INTO trading_plans (
                        id, title, code, name, date, direction, target_price, stop_loss,
                        target_profit, planned_position, strategy_tag, content, status,
                        pinned, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    plan_id, title, code, name, plan_date, direction, target_price, stop_loss,
                    target_profit, planned_position, strategy_tag, content, status,
                    pinned, now, now
                ))

        conn.commit()
        return get_plan(plan_id) or {"id": plan_id}
