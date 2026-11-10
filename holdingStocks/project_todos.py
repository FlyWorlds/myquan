"""Project Todos & Refactoring Tracker: Persistent store for system tasks and enhancements."""
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
            CREATE TABLE IF NOT EXISTS project_todos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT DEFAULT '策略优化',
                priority TEXT DEFAULT 'P1',
                status TEXT DEFAULT 'todo',
                content TEXT,
                target_date TEXT,
                pinned INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_todo_pinned ON project_todos(pinned)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_todo_status ON project_todos(status)")
        conn.commit()

        # 初始化预置项目已有的改造跟踪事项（若为空）
        cur = conn.execute("SELECT COUNT(*) as cnt FROM project_todos")
        if cur.fetchone()["cnt"] == 0:
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            initial_todos = [
                (
                    uuid.uuid4().hex,
                    "首屏秒开优化：Stale-While-Revalidate 快照缓存优先机制",
                    "性能加速",
                    "P1",
                    "todo",
                    "启动时不物理删除上次磁盘快照，前端首屏 0.1s 极速呈现上次收盘数据，后台异步静默刷新，消除白屏等待感。",
                    "2026-11-15",
                    1,
                    now,
                    now,
                ),
                (
                    uuid.uuid4().hex,
                    "行情拉取线程池并发优化 (持仓+策略池并发请求)",
                    "性能加速",
                    "P1",
                    "todo",
                    "将持仓池、策略池、指数的多批 HTTP 串行拉取改为 ThreadPoolExecutor 并行拉取，将网络冷启动等待时间从 5s 压至 1.5s 内。",
                    "2026-11-18",
                    0,
                    now,
                    now,
                ),
                (
                    uuid.uuid4().hex,
                    "买卖解耦与交易闭环生命周期状态机全局化改造",
                    "风控止损",
                    "P0",
                    "done",
                    "已完成：无论策略换池与否，已有持仓与已触买未卖出股票全部进入全局常驻监听队列；延迟清理原则确保当日卖出留痕，次日9:00统一重置销毁。",
                    "2026-11-09",
                    1,
                    now,
                    now,
                ),
                (
                    uuid.uuid4().hex,
                    "中证全指(000985)基准对比与策略Alpha超额收益归因",
                    "策略优化",
                    "P1",
                    "done",
                    "已完成：策略1的7日对比基准由上证指数升级为中证全指(000985)，剔除2倍杠杆系数，还原真实基准超额Alpha。",
                    "2026-11-07",
                    0,
                    now,
                    now,
                ),
            ]
            conn.executemany("""
                INSERT INTO project_todos (
                    id, title, category, priority, status, content, target_date, pinned, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, initial_todos)
            conn.commit()


_init_db()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"] or "策略优化",
        "priority": row["priority"] or "P1",
        "status": row["status"] or "todo",
        "content": row["content"] or "",
        "target_date": row["target_date"] or "",
        "pinned": bool(row["pinned"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_todos() -> list[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute("""
            SELECT * FROM project_todos
            ORDER BY pinned DESC,
                     CASE status
                         WHEN 'in_progress' THEN 1
                         WHEN 'todo' THEN 2
                         WHEN 'done' THEN 3
                         ELSE 4
                     END,
                     CASE priority
                         WHEN 'P0' THEN 1
                         WHEN 'P1' THEN 2
                         ELSE 3
                     END,
                     updated_at DESC
        """)
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_todo(todo_id: str) -> dict[str, Any] | None:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute("SELECT * FROM project_todos WHERE id = ?", (todo_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def save_todo(body: dict[str, Any]) -> dict[str, Any]:
    with _LOCK, _get_connection() as conn:
        todo_id = str(body.get("id") or "").strip()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        action = str(body.get("action") or "").strip()

        if action == "delete":
            if not todo_id:
                raise ValueError("缺少待办事项 id")
            conn.execute("DELETE FROM project_todos WHERE id = ?", (todo_id,))
            conn.commit()
            return {"id": todo_id, "deleted": True}

        if action == "toggle_pin":
            if not todo_id:
                raise ValueError("缺少待办事项 id")
            cur = conn.execute("SELECT pinned FROM project_todos WHERE id = ?", (todo_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("事项不存在")
            new_pin = 0 if row["pinned"] else 1
            if "pinned" in body:
                new_pin = 1 if body["pinned"] else 0
            conn.execute(
                "UPDATE project_todos SET pinned = ?, updated_at = ? WHERE id = ?",
                (new_pin, now, todo_id),
            )
            conn.commit()
            return get_todo(todo_id) or {"id": todo_id, "pinned": bool(new_pin)}

        if action == "toggle_status":
            if not todo_id:
                raise ValueError("缺少待办事项 id")
            new_status = str(body.get("status") or "").strip()
            if new_status not in ("todo", "in_progress", "done", "deferred"):
                raise ValueError(f"无效的状态: {new_status}")
            conn.execute(
                "UPDATE project_todos SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, todo_id),
            )
            conn.commit()
            return get_todo(todo_id) or {"id": todo_id, "status": new_status}

        title = str(body.get("title") or "").strip()
        if not title:
            raise ValueError("事项标题不能为空")

        category = str(body.get("category") or "策略优化").strip()
        priority = str(body.get("priority") or "P1").strip()
        status = str(body.get("status") or "todo").strip()
        content = str(body.get("content") or "").strip()
        target_date = str(body.get("target_date") or "").strip()
        pinned = 1 if body.get("pinned") else 0

        if not todo_id:
            todo_id = uuid.uuid4().hex
            conn.execute("""
                INSERT INTO project_todos (
                    id, title, category, priority, status, content, target_date, pinned, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                todo_id, title, category, priority, status, content, target_date, pinned, now, now
            ))
        else:
            cur = conn.execute("SELECT created_at FROM project_todos WHERE id = ?", (todo_id,))
            row = cur.fetchone()
            if row:
                conn.execute("""
                    UPDATE project_todos SET
                        title = ?, category = ?, priority = ?, status = ?,
                        content = ?, target_date = ?, pinned = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    title, category, priority, status, content, target_date, pinned, now, todo_id
                ))
            else:
                conn.execute("""
                    INSERT INTO project_todos (
                        id, title, category, priority, status, content, target_date, pinned, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    todo_id, title, category, priority, status, content, target_date, pinned, now, now
                ))

        conn.commit()
        return get_todo(todo_id) or {"id": todo_id}
