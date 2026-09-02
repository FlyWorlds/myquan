"""盯盘进程 / 端口回收（Windows 友好）。

解决 Ctrl+C 后子进程未退出、PID 锁残留、8765/3000 端口占用等问题。
"""

from __future__ import annotations

import json
import os
import signal
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


def kill_pid(pid: int, *, force: bool = True) -> bool:
    if not pid_alive(pid):
        return True
    try:
        if sys.platform == "win32":
            cmd = ["taskkill", "/T"]
            if force:
                cmd.append("/F")
            cmd.extend(["/PID", str(int(pid))])
            subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        return not pid_alive(pid)
    except (OSError, ProcessLookupError, AttributeError):
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(int(pid))],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        return not pid_alive(pid)


def reclaim_ports(
    ports: list[int],
    *,
    host: str = "127.0.0.1",
    exclude_pids: set[int] | None = None,
    force: bool = True,
) -> list[int]:
    """结束占用给定端口的进程，返回已尝试结束的 PID。"""
    exclude = exclude_pids or set()
    killed: list[int] = []
    seen: set[int] = set()
    for port in ports:
        for pid in find_listeners(host, int(port)):
            if pid in exclude or pid in seen:
                continue
            seen.add(pid)
            kill_pid(pid, force=force)
            killed.append(pid)
    return killed


def stop_watch(
    *,
    api_port: int = DEFAULT_API_PORT,
    ui_port: int = DEFAULT_UI_PORT,
    host: str = "127.0.0.1",
    force: bool = True,
) -> dict[str, Any]:
    """停止盯盘：锁文件 PID + 8765/3000 监听进程。"""
    killed: list[int] = []
    lock = read_lock()
    lock_pid = int(lock.get("pid") or 0) if lock else 0
    if lock_pid and pid_alive(lock_pid):
        kill_pid(lock_pid, force=force)
        killed.append(lock_pid)
    killed.extend(
        reclaim_ports(
            [int(api_port), int(ui_port)],
            host=host,
            exclude_pids=set(killed),
            force=force,
        )
    )
    lock_cleared = clear_lock(only_if_stale=False)
    remaining = describe_listeners(host, [int(api_port), int(ui_port)])
    return {
        "killed": killed,
        "lock_cleared": lock_cleared,
        "remaining": remaining,
    }


def format_stop_report(result: dict[str, Any]) -> str:
    lines: list[str] = []
    killed = result.get("killed") or []
    if killed:
        lines.append(f"已结束进程: {', '.join(str(p) for p in killed)}")
    else:
        lines.append("未发现需结束的盯盘进程")
    if result.get("lock_cleared"):
        lines.append("已清理 holdings_watch.pid")
    remaining = result.get("remaining") or {}
    if remaining:
        parts = [f":{port}→pid{'/'.join(str(p) for p in pids)}" for port, pids in remaining.items()]
        lines.append(f"仍有端口占用: {', '.join(parts)}（可管理员权限重试或以 --force 再停）")
    else:
        lines.append("端口已释放，可重新启动")
    return "\n".join(lines)
