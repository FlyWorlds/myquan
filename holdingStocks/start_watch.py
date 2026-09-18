#!/usr/bin/env python3
"""一键启动 Web 盯盘：Python 数据 API + Nuxt 前端（Mac / Windows 通用）。

Python 只提供行情/信号 JSON（HTTP /api + WebSocket /ws）。
盯盘页面只走 watch-ui。

用法:
  python start_watch.py
  python start_watch.py --stop          # 停止并释放 8765/3000 端口
  python start_watch.py --force         # 强制停旧实例后启动
  python start_watch.py --no-wechat
  python start_watch.py --no-open
  python start_watch.py -- --skip-wechat-check

平台快捷脚本:
  Windows:  powershell -File start_watch.ps1
  macOS:    ./start_watch.sh
"""

from __future__ import annotations

import argparse
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


def _import_watch_process():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import watch_process

    return watch_process


def _pid_alive(pid: int) -> bool:
    return _import_watch_process().pid_alive(pid)


def _prepare_start(*, force: bool) -> None:
    """启动前：处理 PID 锁与端口占用（Windows Ctrl+C 遗留孤儿进程）。"""
    wp = _import_watch_process()
    lock = wp.read_lock()
    blocked = wp.describe_listeners(API_HOST, [API_PORT, UI_PORT])

    if force:
        if lock or blocked:
            print("[start_watch] --force：正在停止旧实例并回收端口…")
            report = wp.stop_watch(api_port=API_PORT, ui_port=UI_PORT, force=True)
            print("[start_watch] " + wp.format_stop_report(report).replace("\n", "\n[start_watch] "))
        return

    if lock:
        print(
            f"[start_watch] 盯盘已在运行 pid={lock.get('pid')} "
            f"API :{lock.get('port', API_PORT)}  Web {UI_URL}"
        )
        print(
            "[start_watch] 请先停止旧实例：\n"
            "  python start_watch.py --stop\n"
            "  或强制重启：python start_watch.py --force"
        )
        raise SystemExit(1)

    wp.clear_lock(only_if_stale=False)
    if blocked:
        print("[start_watch] 检测到端口占用（多为 Ctrl+C 后子进程未退出），正在回收…")
        for port, pids in blocked.items():
            print(f"  :{port} → pid {', '.join(str(p) for p in pids)}")
        wp.reclaim_ports([API_PORT, UI_PORT], host=API_HOST, force=True)
        left = wp.describe_listeners(API_HOST, [API_PORT, UI_PORT])
        if left:
            print("[start_watch] 部分端口仍占用，请运行: python start_watch.py --stop")
            raise SystemExit(1)
        print("[start_watch] 端口已释放")


def _cmd_stop() -> int:
    wp = _import_watch_process()
    report = wp.stop_watch(api_port=API_PORT, ui_port=UI_PORT, force=True)
    print("[start_watch] " + wp.format_stop_report(report).replace("\n", "\n[start_watch] "))
    return 0 if not report.get("remaining") else 1


def _resolve_python() -> str:
    env_py = os.environ.get("MYQUAN_PYTHON", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    return sys.executable


def _install_shutdown_hooks(procs: dict[str, subprocess.Popen | None]) -> None:
    import atexit

    def _cleanup() -> None:
        _stop_proc(procs.get("ui"))
        _stop_proc(procs.get("api"))
        try:
            _import_watch_process().clear_lock(only_if_stale=False)
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_cleanup)


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
    env["NUXT_IGNORE_LOCK"] = "1"
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制停止旧实例并回收 8765/3000 端口后启动",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="停止盯盘并释放端口（不启动新实例）",
    )
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--no-wechat",
        action="store_true",
        help="关闭微信（预警与买卖成交都不推；不影响 paper execution）",
    )
    parser.add_argument(
        "--no-ledger-pull",
        action="store_true",
        help="启动时不拉取远程持仓（本机 holdings.json 为准）",
    )
    parser.add_argument(
        "extra",
        nargs="*",
        help="传给 index.py watch 的额外参数；可用 -- 分隔",
    )
    args, unknown = parser.parse_known_args()
    if args.stop:
        return _cmd_stop()
    extra = _split_passthrough(list(args.extra) + unknown)

    if not INDEX.is_file():
        raise SystemExit(f"[start_watch] 缺少 {INDEX}")

    _prepare_start(force=bool(args.force))
    if not args.no_ledger_pull:
        try:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from holdings_sync import pull_holdings

            print("[start_watch] 拉取远程持仓（holdings-ledger）…")
            pull_holdings(quiet=False)
        except Exception as e:  # noqa: BLE001
            print(f"[start_watch] 远程持仓拉取失败（继续本机账本）: {e}")
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
        "--no-ui-dev",
    ]
    if args.force:
        watch_args.append("--force")
    if args.no_wechat:
        watch_args.append("--no-wechat")
    if args.no_ledger_pull:
        watch_args.append("--no-ledger-pull")
    watch_args.extend(extra)

    env = _loopback_env()
    print(f"[start_watch] 数据后端: {py} {' '.join(watch_args)}")
    print(f"[start_watch] Web 盯盘: {UI_URL}")
    api_proc: subprocess.Popen | None = None
    ui_proc: subprocess.Popen | None = None
    procs: dict[str, subprocess.Popen | None] = {"api": None, "ui": None}
    _install_shutdown_hooks(procs)
    try:
        api_proc = subprocess.Popen([py, *watch_args], cwd=str(ROOT), env=env, **_popen_kwargs())
        procs["api"] = api_proc
        api_ok = _wait_port(API_PORT, timeout=120, label="数据 API")
        if not api_ok:
            print("[start_watch] 数据 API 未起来，请看 Python 终端输出")
        ui_proc = subprocess.Popen(
            [npm, "run", "dev"],
            cwd=str(WATCH_UI),
            env=env,
            **_popen_kwargs(),
        )
        procs["ui"] = ui_proc
        ui_ok = _wait_port(UI_PORT, timeout=60, label="Web 盯盘")
        if not ui_ok:
            print("[start_watch] 前端未起来，请检查 Node/npm 与 watch-ui 依赖")
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
        try:
            _import_watch_process().clear_lock(only_if_stale=False)
        except Exception:  # noqa: BLE001
            pass
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
