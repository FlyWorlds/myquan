"""Read-only process/listener checks and watch PID metadata; stopping belongs to the root launcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "holdings_watch.pid"
DEFAULT_API_PORT = 8765
DEFAULT_UI_PORT = 3000


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and int(code.value) == STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_lock() -> dict[str, Any] | None:
    if not PID_FILE.exists():
        return None
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            data = json.loads(raw)
            pid = int(data.get("pid") or 0)
        else:
            pid = int(raw)
            data = {"pid": pid}
        if pid and pid_alive(pid):
            return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def clear_lock(*, only_if_stale: bool = True) -> bool:
    """删除 PID 锁。only_if_stale=True 时仅在进程已退出的情况下删除。"""
    if not PID_FILE.exists():
        return True
    if only_if_stale and read_lock():
        return False
    try:
        PID_FILE.unlink()
        return True
    except OSError:
        return False


def find_listeners(host: str, port: int) -> list[int]:
    """占用端口的进程 PID（仅 LISTEN）。"""
    port = int(port)
    if sys.platform == "win32":
        return _win_listeners(port)
    return _unix_listeners(host, port)


def _win_listeners(port: int) -> list[int]:
    try:
        proc = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    needle = f":{port}"
    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        upper = line.upper()
        if "LISTENING" not in upper:
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0:
            pids.add(pid)
    return sorted(pids)


def _unix_listeners(host: str, port: int) -> list[int]:
    for cmd in (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        ["ss", "-ltnp", f"sport = :{port}"],
    ):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            continue
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        if cmd[0] == "lsof":
            out = []
            for tok in proc.stdout.split():
                try:
                    out.append(int(tok))
                except ValueError:
                    pass
            return sorted(set(out))
        # ss output: users:(("node",pid=123,fd=...))
        import re

        pids = {int(m) for m in re.findall(r"pid=(\d+)", proc.stdout)}
        return sorted(pids)
    return []


def describe_listeners(host: str, ports: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for port in ports:
        pids = find_listeners(host, port)
        if pids:
            out[int(port)] = pids
    return out
