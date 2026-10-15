"""Local project launcher (macOS/Linux). No forced port reclamation or account migration."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "backend/logs/project-launcher"
STATE = RUNTIME / "state.json"
HOST = "127.0.0.1"


class LaunchError(RuntimeError):
    pass


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=.4):
            return True
    except OSError:
        return False


def get_json(url):
    with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
        return json.load(response)


def process_birth(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="], capture_output=True,
                            text=True, env=dict(os.environ, LC_ALL="C"), check=False)
    parts = result.stdout.strip().split(maxsplit=1)
    return parts[1] if result.returncode == 0 and len(parts) == 2 and not parts[0].startswith("Z") else ""


def same_process(record):
    pid = record.get("pid", 0)
    return isinstance(pid, int) and pid > 1 and bool(record.get("birth")) and process_birth(pid) == record["birth"]


def stop_owned(record):
    if not same_process(record):
        return
    pid = record["pid"]
    try:
        if os.getpgid(pid) != pid:
            raise LaunchError(f"拒绝停止非独立进程组 pid={pid}")
        # Python handles SIGINT to close its feed, PID lock and child resources gracefully.
        os.killpg(pid, signal.SIGINT if record["name"] == "python" else signal.SIGTERM)
        deadline = time.monotonic() + 15
        while same_process(record) and time.monotonic() < deadline:
            time.sleep(.2)
        if same_process(record):
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def resolve_python():
    override = os.environ.get("MYQUAN_PYTHON")
    candidates = [override] if override else [str(ROOT / ".venv/bin/python"),
                    "/opt/homebrew/bin/python3", sys.executable, shutil.which("python3")]
    for candidate in dict.fromkeys(candidates):
        if not candidate or not Path(candidate).is_file():
            continue
        result = subprocess.run([candidate, "-c",
            "import pandas, akshare, akquant, json; print(json.dumps({'akquant':akquant.__version__}))"],
            capture_output=True, timeout=30)
        if result.returncode == 0:
            installed = json.loads(result.stdout)["akquant"]
            requirements = ROOT / "requirements.txt"
            pin = re.search(r"(?m)^akquant==([^\s#]+)", requirements.read_text()) if requirements.is_file() else None
            if pin and installed != pin[1]:
                print(f"[提示] 当前 AKQuant={installed}，项目要求={pin[1]}；未自动修改环境，正式回测前请统一依赖版本。")
            return candidate
    raise LaunchError("未找到已安装 pandas/akshare/akquant 的 Python；用 MYQUAN_PYTHON 指定项目 Python，先安装 requirements.txt 依赖。")


def resolve_node_env():
    selected = os.environ.get("MYQUAN_NODE") or shutil.which("node")
    if not selected:
        raise LaunchError("前端构建/开发需要 Node 22.12+，可通过 MYQUAN_NODE 指定路径。")
    result = subprocess.run([selected, "--version"], capture_output=True, text=True, check=True)
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
    if not match or tuple(map(int, match.groups())) < (22, 12, 0):
        raise LaunchError("Node 版本过低，前端构建/开发需 22.12+；已有 dist 时日常静态启动不需要 Node。")
    env = dict(os.environ, PATH=str(Path(selected).resolve().parent) + os.pathsep + os.environ.get("PATH", ""))
    npm = shutil.which("npm", path=env["PATH"])
    if not npm:
        raise LaunchError("找不到 npm，请安装 Node/npm。")
    return npm, env


def static_frontend_ready():
    ui = ROOT / "holdingStocks/watch-ui"
    index = ui / "dist/index.html"
    if not index.is_file():
        return False
    files = [ui / name for name in ("app.vue", "nuxt.config.ts", "package.json", "package-lock.json")]
    for folder in ("pages", "components", "composables", "stores", "utils", "assets", "types", "layouts"):
        files.extend(p for p in (ui / folder).rglob("*") if p.is_file())
    return all(not p.exists() or p.stat().st_mtime <= index.stat().st_mtime for p in files)


def prepare_frontend(dev):
    if not dev and static_frontend_ready():
        return None, None
    npm, env = resolve_node_env()
    ui = ROOT / "holdingStocks/watch-ui"
    if not (ui / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=ui, env=env, check=True, timeout=600)
    if not dev:
        print("[启动] 构建静态前端…", flush=True)
        subprocess.run([npm, "run", "build"], cwd=ui, env=env, check=True, timeout=600)
        if not static_frontend_ready():
            raise LaunchError("静态前端构建后仍不可用。")
    return npm, env


def ensure_mysql():
    host = os.environ.get("DB_HOST", HOST)
    port = int(os.environ.get("DB_PORT", "3306"))
    if not 1 <= port <= 65535:
        raise LaunchError("DB_PORT 必须在1～65535。")
    if port_open(host, port):
        print(f"[启动] 数据库端口已就绪 {host}:{port}")
        return
    brew = shutil.which("brew")
    if sys.platform != "darwin" or host not in (HOST, "localhost") or port != 3306 or not brew:
        raise LaunchError(f"数据库 {host}:{port} 不可用，请先启动配置的 MySQL。")
    print("[启动] 启动本机 Homebrew MySQL…", flush=True)
    subprocess.run([brew, "services", "start", "mysql"], check=True, timeout=60)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if port_open(host, port):
            return
        time.sleep(.5)
    raise LaunchError("等待 MySQL 端口超时；未创建/清空任何账户数据。")


def service_matches(name, port):
    # A healthy HTTP response is insufficient: the listener must belong to this checkout.
    lsof = shutil.which("lsof")
    if not lsof:
        raise LaunchError("需要 lsof 核验占用端口的进程；不会强制回收未知端口。")
    result = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                            capture_output=True, text=True, check=False)
    expected = ROOT / ("backend" if name == "java" else "holdingStocks/watch-ui" if name == "frontend" else "")
    for item in result.stdout.split():
        if not item.isdigit():
            continue
        paths = subprocess.run([lsof, "-a", "-p", item, "-d", "cwd", "-Fn"],
                               capture_output=True, text=True, check=False).stdout.splitlines()
        if "n" + str(expected) not in paths:
            return False
    return bool(result.stdout.strip())


def backend_ready(port):
    base = f"http://{HOST}:{port}"
    status = get_json(base + "/api/system/status")
    if not isinstance(status, dict) or status.get("application") != "myquan-backend" or status.get("status") != "UP":
        return False
    database = status.get("database")
    if not isinstance(database, dict) or database.get("name") != os.environ.get("DB_NAME", "myquan"):
        return False
    health = get_json(base + "/actuator/health")
    return isinstance(health, dict) and health.get("status") == "UP"


def watch_ready(port):
    data = get_json(f"http://{HOST}:{port}/api/snapshot")
    return isinstance(data, dict) and data.get("type") == "snapshot" and isinstance(data.get("holdings"), list)


def frontend_ready(port):
    with build_opener(ProxyHandler({})).open(f"http://{HOST}:{port}/", timeout=3) as response:
        return response.status == 200 and b"<html" in response.read(4096).lower()


def read_state():
    if not STATE.exists():
        return {}
    raw = json.loads(STATE.read_text())
    if not isinstance(raw, dict) or any(not isinstance(v, dict) for v in raw.values()):
        raise LaunchError("启动器状态文件损坏，拒绝据此停止进程。")
    return raw


def write_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)


@contextlib.contextmanager
def operation_lock():
    if os.name != "posix":
        raise LaunchError("此入口支持 macOS/Linux；Windows 暂用文档中的分步启动。")
    import fcntl
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "operation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LaunchError("另一条启动/停止命令正在执行，请勿重复点击。") from exc
        yield


def start_service(name, port, command, cwd, env, probe, state, created, timeout):
    if port_open(HOST, port):
        if not service_matches(name, port) or not probe(port):
            raise LaunchError(f":{port} 被未知或未就绪服务占用；不会停止该进程。")
        managed = same_process(state.get(name, {}))
        prior = state.get(name, {})
        settings = {key: env.get(key) for key in ("PAPER_BACKEND_URL", "WATCH_API_PORT", "NUXT_PORT") if key in env}
        if managed and prior.get("command") and command and (
                prior["command"] != command or prior.get("settings", {}) != settings):
            raise LaunchError(f"{name} 启动参数已变化；先 --stop 或使用 --restart，不能静默复用旧参数。")
        print(f"[启动] 复用已有 {name} :{port}（{'启动器已管理' if managed else '不接管、不停止'}）")
        if not managed:
            print("[启动] 已有服务沿用原进程参数；修改参数需先在原终端停止。")
        return
    log = RUNTIME / f"{name}.log"
    with log.open("ab") as output:
        os.chmod(log, 0o600)
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        birth = process_birth(proc.pid)
    except BaseException:
        abort_spawn(proc)
        raise
    record = dict(name=name, pid=proc.pid, birth=birth, port=port, log=str(log), command=command,
                  settings={key: env.get(key) for key in ("PAPER_BACKEND_URL", "WATCH_API_PORT", "NUXT_PORT") if key in env})
    if not record["birth"]:
        abort_spawn(proc)
        raise LaunchError(f"{name} 无法启动，查看 {log}")
    created.append(record)
    state[name] = record
    write_state(state)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise LaunchError(f"{name} 已退出，查看 {log}")
        try:
            if probe(port) and service_matches(name, port):
                print(f"[启动] {name} 就绪 :{port}，pid={proc.pid}")
                return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise LaunchError(f"等待 {name} 超时，查看 {log}")


def abort_spawn(proc):
    """Only for a child just created here, before its ownership record is persisted."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    except ProcessLookupError:
        pass


def java_command():
    env = dict(os.environ)
    java_home = env.get("JAVA_HOME") or "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"
    java = str(Path(java_home) / "bin/java")
    if not Path(java).is_file():
        java = shutil.which("java")
    if not java:
        raise LaunchError("未找到 Java，请安装 JDK 21+。")
    jar = ROOT / "backend/target/myquan-backend-0.1.0-SNAPSHOT.jar"
    sources = [p for p in [ROOT / "backend/pom.xml", *(ROOT / "backend/src").rglob("*")] if p.is_file()]
    fingerprint = hashlib.sha256()
    for path in sorted(sources):
        fingerprint.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    source_hash = fingerprint.hexdigest()
    cache_file = RUNTIME / "backend-build.json"
    try:
        cached = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cached = {}
    if not isinstance(cached, dict):
        cached = {}
    artifact_hash = file_hash(jar) if jar.is_file() else None
    if (not artifact_hash or cached.get("source") != source_hash or cached.get("artifact") != artifact_hash):
        print("[启动] 编译并测试 Java 后台…", flush=True)
        log = RUNTIME / "backend-build.log"
        with log.open("ab") as output:
            os.chmod(log, 0o600)
            try:
                subprocess.run(["bash", str(ROOT / "backend/run.sh"), "package"], cwd=ROOT, env=env,
                               stdout=output, stderr=subprocess.STDOUT, check=True, timeout=600)
            except subprocess.SubprocessError as exc:
                raise LaunchError(f"Java 构建失败，查看 {log}") from exc
        if not jar.is_file():
            raise LaunchError(f"Java 构建未生成 JAR，查看 {log}")
        cache_file.write_text(json.dumps(dict(source=source_hash, artifact=file_hash(jar))) + "\n")
        os.chmod(cache_file, 0o600)
    return [java, "-Xms128m", "-Xmx512m", "-jar", str(jar)], env


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def start(opts):
    state, created = read_state(), []
    try:
        desired_ports = dict(java=opts.backend_port, python=opts.port, frontend=opts.ui_port)
        for name, record in state.items():
            if same_process(record) and record.get("port") != desired_ports.get(name):
                raise LaunchError("已有启动器管理的服务使用其它端口；先 --stop，再变更端口启动。")
        python = resolve_python()
        npm, node_env = prepare_frontend(opts.ui_dev)
        ensure_mysql()
        if port_open(HOST, opts.backend_port):
            java, java_env = [], dict(os.environ)
        else:
            java, java_env = java_command()
        java_env.update(SERVER_ADDRESS=HOST, SERVER_PORT=str(opts.backend_port))
        start_service("java", opts.backend_port, java, ROOT / "backend", java_env,
                      backend_ready, state, created, opts.timeout)
        backend_url = f"http://{HOST}:{opts.backend_port}"
        try:
            book = get_json(backend_url + "/api/paper/state")
        except OSError as exc:
            raise LaunchError("数据库账户不可读取；检查 Java 日志和迁移状态，不会自动导入/清空账户。") from exc
        if (not isinstance(book, dict) or not isinstance(book.get("revision"), int)
                or isinstance(book["revision"], bool) or book["revision"] <= 0):
            raise LaunchError("数据库账户未初始化，请先确认迁移；启动器不会自动导入或清空持仓。")
        print(f"[启动] 数据库账户已就绪 revision={book['revision']}")
        env = dict(os.environ, HOLDINGS_STORAGE="database", PAPER_BACKEND_URL=backend_url, PYTHONUNBUFFERED="1")
        for key in ("NO_PROXY", "no_proxy"):
            env[key] = env.get(key, "") + ",127.0.0.1,localhost,::1"
        command = [python, "-u", str(ROOT / "holdingStocks/index.py"), "watch", "--no-ui-dev",
                   "--no-open", "--port", str(opts.port), "--no-wechat" if opts.no_wechat else "--wechat-optional"]
        start_service("python", opts.port, command, ROOT, env, watch_ready, state, created, opts.timeout)
        if opts.ui_dev:
            node_env.update(WATCH_API_HOST=HOST, WATCH_API_PORT=str(opts.port), NUXT_PORT=str(opts.ui_port))
            start_service("frontend", opts.ui_port, [npm, "run", "dev"], ROOT / "holdingStocks/watch-ui",
                          node_env, frontend_ready, state, created, opts.timeout)
        else:
            if not frontend_ready(opts.port):
                raise LaunchError("Python API 就绪，但静态页面不可用，请检查前端 dist。")
        url = f"http://{HOST}:{opts.ui_port if opts.ui_dev else opts.port}/"
        print(f"[启动] 页面 {url}\n[启动] 服务后台运行；日志 {RUNTIME}\n[启动] 停止：bash start.sh --stop（MySQL 保持运行）")
        if not opts.no_open:
            webbrowser.open(url)
        return 0
    except BaseException:
        for record in reversed(created):
            stop_owned(record)
            state.pop(record["name"], None)
        write_state(state)
        raise


def stop():
    state = read_state()
    for name in ("frontend", "python", "java"):
        record = state.get(name)
        if record:
            stop_owned(record)
            state.pop(name, None)
            write_state(state)
            print(f"[停止] {name}（仅本启动器登记的进程）")
    print("[停止] MySQL 与未接管的已有服务保持运行。")
    return 0


def status(opts):
    state = read_state()
    for name, port, probe in (("java", opts.backend_port, backend_ready), ("python", opts.port, watch_ready),
                               ("frontend", opts.ui_port, frontend_ready)):
        try:
            ready = port_open(HOST, port) and service_matches(name, port) and probe(port)
        except (OSError, ValueError, LaunchError):
            ready = False
        owned = same_process(state.get(name, {}))
        print(f"{name} :{port} {'就绪' if ready else '未就绪/未运行'} {'[启动器管理]' if owned else '[未接管]'}")
    host, port = os.environ.get("DB_HOST", HOST), int(os.environ.get("DB_PORT", "3306"))
    print(f"MySQL {host}:{port} {'端口可连接' if port_open(host, port) else '不可连接'}")
    print(f"日常页面 http://{HOST}:{opts.port}/；开发页面仅 --ui-dev 时为 :{opts.ui_port}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="MySQL + Java + Python + 前端一键启动（macOS/Linux）")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--stop", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--restart", action="store_true", help="重启启动器管理的服务，不停止 MySQL 或手工启动的服务")
    parser.add_argument("--ui-dev", action="store_true", help="使用 Nuxt 热更新，默认静态前端")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-wechat", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--backend-port", type=int, default=8080)
    parser.add_argument("--ui-port", type=int, default=3000)
    parser.add_argument("--timeout", type=float, default=120)
    opts = parser.parse_args()
    if any(not 1 <= p <= 65535 for p in (opts.port, opts.backend_port, opts.ui_port)) or not math.isfinite(opts.timeout) or opts.timeout <= 0:
        parser.error("端口必须在1～65535，超时必须大于0")
    if len({opts.port, opts.backend_port, opts.ui_port}) != 3:
        parser.error("三个服务端口不能重复")
    try:
        with operation_lock():
            if opts.restart:
                stop()
            return stop() if opts.stop else status(opts) if opts.status else start(opts)
    except (LaunchError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[停止] 已取消启动，仅清理本次新启动的服务。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
