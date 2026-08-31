#!/usr/bin/env python3
"""一键启动 Web 盯盘：Python 数据 API + Nuxt 前端（Mac / Windows 通用）。

Python 只提供行情/信号 JSON（HTTP /api + WebSocket /ws）。
盯盘页面只走 watch-ui。

用法:
  python start_watch.py
  python start_watch.py --no-wechat
  python start_watch.py --no-open
  python start_watch.py -- --skip-wechat-check

平台快捷脚本:
  Windows:  powershell -File start_watch.ps1
  macOS:    ./start_watch.sh
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.py"
WATCH_UI = ROOT / "watch-ui"
PID_FILE = ROOT / "holdings_watch.pid"
API_HOST = "127.0.0.1"
API_PORT = 8765
UI_PORT = 3000
UI_URL = f"http://{API_HOST}:{UI_PORT}/"


def _pid_alive(pid: int) -> bool:
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


def _read_lock() -> dict | None:
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
        if pid and _pid_alive(pid):
            return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _clear_stale_lock() -> None:
    if not PID_FILE.exists():
        return
    lock = _read_lock()
    if lock:
        print(
            f"[start_watch] 数据后端已在运行 pid={lock.get('pid')} "
            f"API :{lock.get('port', API_PORT)}  Web {UI_URL}"
        )
        print("[start_watch] 请先在该终端 Ctrl+C 停掉旧进程后再启动。")
        raise SystemExit(1)
    try:
        PID_FILE.unlink()
        print("[start_watch] 已清理失效锁文件 holdings_watch.pid")
    except OSError as e:
        print(f"[start_watch] 无法删除失效锁: {e}")
        raise SystemExit(1) from e


def _resolve_python() -> str:
    env_py = os.environ.get("MYQUAN_PYTHON", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    return sys.executable


def _resolve_npm() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm") or shutil.which("npm.exe")
    if not npm:
        raise SystemExit(
            "[start_watch] 未找到 npm。请安装 Node.js 后再运行。\n"
            "  Windows/macOS: https://nodejs.org/  或 nvm / nvm-windows"
        )
    return npm


def _port_open(port: int, *, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((API_HOST, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_port(port: int, *, timeout: float, label: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            print(f"[start_watch] {label} 就绪 http://{API_HOST}:{port}/")
            return True
        time.sleep(0.4)
    print(f"[start_watch] 等待 {label} :{port} 超时（{timeout:.0f}s）")
    return False


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _stop_proc(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass


def _loopback_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    extra = "127.0.0.1,localhost,::1"
    for key in ("NO_PROXY", "no_proxy"):
        cur = (env.get(key) or "").strip()
        env[key] = f"{cur},{extra}" if cur else extra
    env["WATCH_API_HOST"] = API_HOST
    env["WATCH_API_PORT"] = str(API_PORT)
    env["NUXT_PORT"] = str(UI_PORT)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _ensure_node_modules(npm: str) -> None:
    if (WATCH_UI / "node_modules").is_dir():
        return
    if not (WATCH_UI / "package.json").is_file():
        raise SystemExit(f"[start_watch] 缺少 {WATCH_UI / 'package.json'}")
    print("[start_watch] 首次安装 watch-ui 依赖: npm install")
    proc = subprocess.run([npm, "install"], cwd=str(WATCH_UI), check=False)
    if proc.returncode:
        raise SystemExit(proc.returncode)


def _split_passthrough(argv: list[str]) -> list[str]:
    if not argv:
        return []
    if argv[0] == "--":
        return argv[1:]
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="启动 Web 盯盘（Python 数据 API + Nuxt 页面）",
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--no-wechat",
        action="store_true",
        help="关闭微信（传给 index.py watch）",
    )
    parser.add_argument(
        "extra",
        nargs="*",
        help="传给 index.py watch 的额外参数；可用 -- 分隔",
    )
    args, unknown = parser.parse_known_args()
    extra = _split_passthrough(list(args.extra) + unknown)

    if not INDEX.is_file():
        raise SystemExit(f"[start_watch] 缺少 {INDEX}")

    _clear_stale_lock()
    py = _resolve_python()
    npm = _resolve_npm()
    _ensure_node_modules(npm)

    watch_args = [
        str(INDEX),
        "watch",
        "--interval",
        "5",
        "--port",
        str(API_PORT),
        "--no-open",
        "--wechat-optional",
    ]
    if args.no_wechat:
        watch_args.append("--no-wechat")
    watch_args.extend(extra)

    env = _loopback_env()
    print(f"[start_watch] 数据后端: {py} {' '.join(watch_args)}")
    print(f"[start_watch] Web 盯盘: {UI_URL}")
    api_proc: subprocess.Popen | None = None
    ui_proc: subprocess.Popen | None = None
    try:
        api_proc = subprocess.Popen([py, *watch_args], cwd=str(ROOT), env=env, **_popen_kwargs())
        ui_proc = subprocess.Popen(
            [npm, "run", "dev"],
            cwd=str(WATCH_UI),
            env=env,
            **_popen_kwargs(),
        )
        ui_ok = _wait_port(UI_PORT, timeout=60, label="Web 盯盘")
        api_ok = _wait_port(API_PORT, timeout=90, label="数据 API")
        if not ui_ok:
            print("[start_watch] 前端未起来，请检查 Node/npm 与 watch-ui 依赖")
        if not api_ok:
            print("[start_watch] 数据 API 未起来，请看 Python 终端输出")
        if ui_ok and not args.no_open:
            webbrowser.open(UI_URL)
        print("[start_watch] Ctrl+C 同时停止数据后端与 Web 盯盘")
        while True:
            api_code = api_proc.poll()
            ui_code = ui_proc.poll()
            if api_code is not None:
                print(f"[start_watch] 数据后端已退出 code={api_code}")
                break
            if ui_code is not None:
                print(f"[start_watch] Web 盯盘已退出 code={ui_code}")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[start_watch] 正在停止…")
    finally:
        _stop_proc(ui_proc)
        _stop_proc(api_proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
