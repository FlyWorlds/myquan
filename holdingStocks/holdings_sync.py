"""Win / Mac 持仓账本远程同步。

真源是 ``holdings.json`` + ``trades.jsonl`` + ``trade_ledger.json``（交割明细），
走独立 git 分支 ``holdings-ledger``，
不进 ``main``（文件仍在 .gitignore，避免随代码误提交）。

``holdings_watch.json`` 只是本机盯盘展示缓存，**不是**账本；拉取后必须丢掉。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / "holdings.json"
TRADES_FILE = ROOT / "trades.jsonl"
TRADE_LEDGER_FILE = ROOT / "trade_ledger.json"
WATCH_META_FILE = ROOT / "holdings_watch.json"
LEDGER_BRANCH = "holdings-ledger"
LEDGER_REL_PATHS = (
    "holdingStocks/holdings.json",
    "holdingStocks/trades.jsonl",
    "holdingStocks/trade_ledger.json",
)


def snapshot_cache_stale(
    watch_path: Path | None = None,
    holdings_path: Path | None = None,
) -> bool:
    """本机盯盘快照比账本旧（或缺失）时视为过期，禁止当持仓真源。"""
    watch = watch_path or WATCH_META_FILE
    holdings = holdings_path or HOLDINGS_FILE
    if not watch.is_file():
        return True
    if not holdings.is_file():
        return False
    try:
        return watch.stat().st_mtime + 0.5 < holdings.stat().st_mtime
    except OSError:
        return True


def invalidate_watch_cache() -> None:
    """丢掉本机 holdings_watch.json，避免 Mac/Win 启动时用旧快照盖住账本。"""
    try:
        if WATCH_META_FILE.is_file():
            WATCH_META_FILE.unlink()
    except OSError:
        pass


def current_host() -> str:
    return socket.gethostname() or "unknown"


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=str(cwd),
        env=merged,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
        timeout=timeout,
    )


def repo_root() -> Path:
    out = _run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT)
    return Path(out.stdout.strip())


def _updated_at(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("updated_at") or "")
    return ""


def _ref_exists(repo: Path, ref: str) -> bool:
    r = _run(["git", "rev-parse", "--verify", ref], cwd=repo, check=False)
    return r.returncode == 0


def _show_file(repo: Path, spec: str, dest: Path) -> bool:
    r = _run(["git", "show", spec], cwd=repo, check=False)
    if r.returncode != 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(r.stdout or "", encoding="utf-8")
    return True


def pull_holdings(*, force: bool = False, quiet: bool = False) -> str:
    """从 origin/holdings-ledger 覆盖本机账本。远程较旧则跳过（--force 除外）。"""
    repo = repo_root()
    # 盯盘启动同步路径：网络挂起时不能无限堵 API（超时由调用方降级为本机账本）
    fetch = _run(
        ["git", "fetch", "origin", LEDGER_BRANCH],
        cwd=repo,
        check=False,
        timeout=20,
    )
    remote_ref = f"origin/{LEDGER_BRANCH}"
    if fetch.returncode != 0 or not _ref_exists(repo, remote_ref):
        msg = "远程尚无 holdings-ledger（先在有账本的机器上 holdings-push）"
        if not quiet:
            print(msg)
        return "missing-remote"

    remote_holdings = repo / LEDGER_REL_PATHS[0]
    tmp = Path(tempfile.mkdtemp(prefix="holdings-ledger-"))
    remote_copy = tmp / "holdings.json"
    try:
        if not _show_file(repo, f"{remote_ref}:{LEDGER_REL_PATHS[0]}", remote_copy):
            if not quiet:
                print("远程分支没有 holdings.json")
            return "missing-remote"
        local_ts = _updated_at(HOLDINGS_FILE)
        remote_ts = _updated_at(remote_copy)
        if (
            local_ts
            and remote_ts
            and local_ts > remote_ts
            and not force
        ):
            if not quiet:
                print(
                    f"本机账本更新（{local_ts}）新于远程（{remote_ts}），"
                    "未覆盖。先 holdings-push，或 --force 强制拉取。"
                )
            return "local-newer"

        HOLDINGS_FILE.write_text(remote_copy.read_text(encoding="utf-8"), encoding="utf-8")
        trades_ok = _show_file(
            repo,
            f"{remote_ref}:{LEDGER_REL_PATHS[1]}",
            TRADES_FILE,
        )
        ledger_ok = False
        if len(LEDGER_REL_PATHS) > 2:
            ledger_ok = _show_file(
                repo,
                f"{remote_ref}:{LEDGER_REL_PATHS[2]}",
                TRADE_LEDGER_FILE,
            )
        invalidate_watch_cache()
        if not quiet:
            host = ""
            try:
                data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
                host = str((data or {}).get("updated_host") or "")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            extra = ""
            if not trades_ok:
                extra += " · trades.jsonl 远程没有（保留本地）"
            if len(LEDGER_REL_PATHS) > 2 and not ledger_ok:
                extra += " · trade_ledger.json 远程没有（保留本地）"
            print(
                f"已拉取远程持仓 · updated_at={remote_ts or '-'} "
                f"host={host or '-'} · 已丢本机 holdings_watch.json"
                + extra
            )
        return "pulled"
    finally:
        try:
            remote_copy.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass


def push_holdings(*, force: bool = False) -> str:
    """把本机 holdings.json + trades.jsonl + trade_ledger.json 推到 origin/holdings-ledger。"""
    if not HOLDINGS_FILE.is_file():
        raise SystemExit("没有 holdings.json，无法推送")
    repo = repo_root()
    fetch = _run(["git", "fetch", "origin", LEDGER_BRANCH], cwd=repo, check=False)
    remote_ref = f"origin/{LEDGER_BRANCH}"
    if fetch.returncode == 0 and _ref_exists(repo, remote_ref) and not force:
        tmp = Path(tempfile.mkdtemp(prefix="holdings-ledger-"))
        remote_copy = tmp / "holdings.json"
        try:
            if _show_file(repo, f"{remote_ref}:{LEDGER_REL_PATHS[0]}", remote_copy):
                local_ts = _updated_at(HOLDINGS_FILE)
                remote_ts = _updated_at(remote_copy)
                if remote_ts and local_ts and remote_ts > local_ts:
                    print(
                        f"远程账本更新（{remote_ts}）新于本机（{local_ts}）。"
                        "先 holdings-pull，或 --force 强制覆盖远程。"
                    )
                    return "remote-newer"
        finally:
            try:
                remote_copy.unlink(missing_ok=True)
                tmp.rmdir()
            except OSError:
                pass

    data: dict[str, Any]
    try:
        data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise SystemExit(f"holdings.json 无法读取: {e}") from e
    if not isinstance(data, dict):
        raise SystemExit("holdings.json 格式不对")
    data["updated_host"] = current_host()
    HOLDINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    index_path = ROOT / ".ledger_git_index"
    env = {"GIT_INDEX_FILE": str(index_path)}
    try:
        parent = ""
        if _ref_exists(repo, f"refs/heads/{LEDGER_BRANCH}"):
            _run(["git", "read-tree", LEDGER_BRANCH], cwd=repo, env=env)
            parent = _run(
                ["git", "rev-parse", LEDGER_BRANCH], cwd=repo
            ).stdout.strip()
        elif _ref_exists(repo, remote_ref):
            _run(["git", "read-tree", remote_ref], cwd=repo, env=env)
            parent = _run(["git", "rev-parse", remote_ref], cwd=repo).stdout.strip()
        else:
            _run(["git", "read-tree", "--empty"], cwd=repo, env=env)

        _run(["git", "add", "-f", *LEDGER_REL_PATHS], cwd=repo, env=env)
        tree = _run(["git", "write-tree"], cwd=repo, env=env).stdout.strip()
        msg = (
            f"sync holdings ledger from {current_host()} "
            f"({_updated_at(HOLDINGS_FILE) or 'no-ts'})"
        )
        cmd = ["git", "commit-tree", tree, "-m", msg]
        if parent:
            cmd.extend(["-p", parent])
        sha = _run(cmd, cwd=repo).stdout.strip()
        _run(["git", "update-ref", f"refs/heads/{LEDGER_BRANCH}", sha], cwd=repo)
        push = _run(
            ["git", "push", "-u", "origin", LEDGER_BRANCH],
            cwd=repo,
            check=False,
        )
        if push.returncode != 0:
            err = (push.stderr or push.stdout or "").strip()
            raise SystemExit(f"git push origin {LEDGER_BRANCH} 失败:\n{err}")
        print(
            f"已推送远程持仓 → origin/{LEDGER_BRANCH} · "
            f"{_updated_at(HOLDINGS_FILE)} · host={current_host()} · {sha[:10]}"
        )
        return "pushed"
    finally:
        try:
            index_path.unlink(missing_ok=True)
        except OSError:
            pass
