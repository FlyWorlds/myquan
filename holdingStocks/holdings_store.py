"""holdings.json 账本存储层：进程内单一对象 + 串行写 + 版本检查 + 原子落盘。

为什么需要：盯盘进程里扫描、行情快刷、9:15 重置各自改账本再整份写盘。
旧实现每次读盘都换一个新 dict、写盘直接覆盖，线程/进程之间谁后写谁赢，
旧数据会把新数据盖掉（2026-09-29 隔日粘滞复活 → 002636 假成交）。

约定：
· 进程内 ``load()`` 永远返回同一个 dict（身份稳定），外部进程改盘后原地三方合并吸收，
  持有旧引用的线程看到的就是最新账本。
· ``save()`` 在进程锁 + 跨进程文件锁内执行；写盘前比对磁盘版本（mtime_ns+size），
  若被其它进程改过，先三方合并（只改一边的字段各自保留，同字段冲突以磁盘为准）再写。
· 写盘走临时文件 + ``os.replace``，读者不会读到半截 JSON。
· 容器字段（alert_sticky / closed_today / slot_queue …）只原地清空，
  用 ``reset_container``，不要 ``data[key] = {}`` 换绑，否则持有旧容器的线程会把旧内容写回。
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

_MISSING: Any = object()

# 每次写盘都会被重新打戳，不算冲突
STAMP_KEYS = frozenset({"updated_at", "updated_host"})

_FLOCKS_GUARD = threading.Lock()
_FLOCKS: dict[str, "_InterProcessLock"] = {}


def _eq(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if a is _MISSING or b is _MISSING:
        return False
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return False


def sync_inplace(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """把 dst 改成与 src 等值，尽量保留 dst 里嵌套 dict/list 的身份。"""
    if dst is src:
        return
    for k in [k for k in dst if k not in src]:
        del dst[k]
    for k, v in src.items():
        cur = dst.get(k, _MISSING)
        if cur is v:
            continue
        if isinstance(cur, dict) and isinstance(v, dict):
            sync_inplace(cur, v)
        elif isinstance(cur, list) and isinstance(v, list):
            cur[:] = v
        else:
            dst[k] = v


def reset_container(parent: dict[str, Any], key: str, new: Any) -> Any:
    """原地把 parent[key] 换成 new 的内容；类型不同才换绑。返回生效的容器。"""
    cur = parent.get(key)
    if isinstance(cur, dict) and isinstance(new, dict):
        sync_inplace(cur, new)
        return cur
    if isinstance(cur, list) and isinstance(new, list):
        if cur is not new:
            cur[:] = new
        return cur
    parent[key] = new
    return new


def _take_theirs(ours: dict[str, Any], key: str, o: Any, t: Any) -> None:
    if t is _MISSING:
        ours.pop(key, None)
    elif isinstance(o, dict) and isinstance(t, dict):
        sync_inplace(o, t)
    elif isinstance(o, list) and isinstance(t, list):
        o[:] = t
    else:
        ours[key] = t


def merge3_inplace(
    base: Any,
    ours: dict[str, Any],
    theirs: dict[str, Any],
    *,
    conflicts: list[str] | None = None,
    _path: tuple[str, ...] = (),
) -> list[str]:
    """三方合并：把 theirs 相对 base 的改动原地并入 ours。

    · theirs 未改 → 保留 ours；ours 未改 → 取 theirs
    · 两边都是 dict → 递归（base 缺失视为空）
    · 两边改成同一个值 → 保留
    · 真冲突 → 以 theirs（已落盘的外部写入）为准，并记录路径
    """
    out = conflicts if conflicts is not None else []
    b_map = base if isinstance(base, dict) else {}
    keys = list(ours) + [k for k in theirs if k not in ours]
    for k in keys:
        b = b_map.get(k, _MISSING)
        o = ours.get(k, _MISSING)
        t = theirs.get(k, _MISSING)
        if _eq(t, b):
            continue
        if isinstance(o, dict) and isinstance(t, dict):
            merge3_inplace(b, o, t, conflicts=out, _path=_path + (str(k),))
            continue
        if _eq(o, b) or _eq(o, t):
            if not _eq(o, t):
                _take_theirs(ours, k, o, t)
            continue
        if not (_path == () and k in STAMP_KEYS):
            out.append(".".join(_path + (str(k),)))
        _take_theirs(ours, k, o, t)
    return out


class _InterProcessLock:
    """跨进程独占锁（``<file>.lock``）；同进程内按线程可重入。"""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._tlock = threading.RLock()
        self._depth = 0
        self._fh: Any = None

    def _try_os_lock(self) -> bool:
        fh = self._fh
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _os_unlock(self) -> None:
        fh = self._fh
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def acquire(self, timeout: float, log: Callable[[str], None] | None) -> None:
        self._tlock.acquire()
        self._depth += 1
        if self._depth > 1:
            return
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.lock_path, "a+b")  # noqa: SIM115
        except OSError as e:
            self._fh = None
            if log:
                log(f"账本文件锁不可用（继续，仅进程内串行）: {e}")
            return
        deadline = time.monotonic() + max(0.0, timeout)
        while not self._try_os_lock():
            if time.monotonic() >= deadline:
                if log:
                    log(f"账本文件锁等待超时 {timeout:.0f}s（继续写盘）: {self.lock_path.name}")
                self._fh.close()
                self._fh = None
                return
            time.sleep(0.02)

    def release(self) -> None:
        try:
            self._depth -= 1
            if self._depth == 0 and self._fh is not None:
                self._os_unlock()
                self._fh.close()
                self._fh = None
        finally:
            self._tlock.release()


@contextlib.contextmanager
def file_lock(
    path: Path,
    *,
    timeout: float = 10.0,
    log: Callable[[str], None] | None = None,
) -> Iterator[None]:
    """账本跨进程锁：所有写 holdings.json 的路径（盯盘 / CLI / holdings-pull）都要拿。"""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    key = str(lock_path.resolve()) if lock_path.parent.exists() else str(lock_path)
    with _FLOCKS_GUARD:
        lk = _FLOCKS.get(key)
        if lk is None:
            lk = _FLOCKS[key] = _InterProcessLock(lock_path)
    lk.acquire(timeout, log)
    try:
        yield
    finally:
        lk.release()


def file_token(path: Path) -> tuple[int, int] | None:
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + fsync + os.replace；Windows 上目标被短暂占用时重试，最后退回直写。"""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    last_err: OSError | None = None
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.05)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    if last_err is not None and not path.exists():
        raise last_err


def write_json_locked(
    path: Path,
    text: str,
    *,
    log: Callable[[str], None] | None = None,
) -> None:
    """进程外工具（holdings-pull/push、修复脚本）整份写账本用：文件锁 + 原子替换。"""
    with file_lock(path, log=log):
        atomic_write_text(path, text)


class HoldingsStore:
    """进程内 holdings.json 的唯一持有者。

    状态放在调用方传入的 ``cache`` dict 里（键：data / mtime / path / token / base_text），
    清空 ``cache`` 等价于冷启动（下次 ``load`` 重新读盘并换绑新对象）。
    """

    def __init__(
        self,
        cache: dict[str, Any],
        *,
        path: Callable[[], Path],
        normalize: Callable[[dict[str, Any]], None] | None = None,
        log: Callable[[str], None] | None = None,
        lock_timeout: float = 10.0,
    ) -> None:
        self.cache = cache
        self._path_fn = path
        self._normalize = normalize
        self._log = log
        self.lock_timeout = float(lock_timeout)
        self.lock = threading.RLock()
        self.last_conflicts: list[str] = []

    # ── 内部 ────────────────────────────────────────────────
    def _path(self) -> Path:
        return Path(self._path_fn())

    def _emit(self, msg: str) -> None:
        if self._log:
            try:
                self._log(msg)
            except Exception:  # noqa: BLE001
                pass

    def _bound(self, path: Path) -> dict[str, Any] | None:
        data = self.cache.get("data")
        if data is None or self.cache.get("path") != str(path):
            return None
        return data

    def _remember(self, path: Path, data: dict[str, Any], text: str) -> None:
        tok = file_token(path)
        self.cache["data"] = data
        self.cache["path"] = str(path)
        self.cache["token"] = tok
        self.cache["base_text"] = text
        self.cache["mtime"] = (tok[0] / 1e9) if tok else 0.0

    @staticmethod
    def _read_disk(path: Path) -> tuple[str, dict[str, Any]] | None:
        err: Exception | None = None
        for _ in range(5):
            try:
                text = path.read_text(encoding="utf-8")
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return text, obj
                return None
            except FileNotFoundError:
                return None
            except (OSError, ValueError) as e:
                err = e
                time.sleep(0.05)
        if err is not None:
            raise err
        return None

    def _base(self) -> dict[str, Any]:
        try:
            base = json.loads(self.cache.get("base_text") or "{}")
        except ValueError:
            base = {}
        return base if isinstance(base, dict) else {}

    def _absorb(self, path: Path, data: dict[str, Any], disk: dict[str, Any]) -> None:
        conflicts = merge3_inplace(self._base(), data, disk)
        self.last_conflicts = conflicts
        if conflicts:
            shown = ", ".join(conflicts[:8]) + (" …" if len(conflicts) > 8 else "")
            self._emit(f"账本被外部改写，已合并；冲突 {len(conflicts)} 处以磁盘为准: {shown}")

    def _dumps(self, data: dict[str, Any]) -> str:
        for i in range(8):
            try:
                return json.dumps(data, ensure_ascii=False, indent=2)
            except RuntimeError:
                # 其它线程正在往账本里加键；锁外改动的兜底
                if i == 7:
                    raise
                time.sleep(0.01)
        raise RuntimeError("unreachable")

    # ── 对外 ────────────────────────────────────────────────
    def load(self) -> dict[str, Any] | None:
        """返回进程内唯一账本对象；文件不存在且从未加载过时返回 None。"""
        path = self._path()
        data = self._bound(path)
        if data is not None:
            tok = file_token(path)
            if tok is None or tok == self.cache.get("token"):
                return data
        with self.lock:
            data = self._bound(path)
            tok = file_token(path)
            if data is not None and (tok is None or tok == self.cache.get("token")):
                return data
            if tok is None:
                return None
            # 先取版本再读内容：两者之间若被改写，下次 load 会再合并一次，不会漏
            with file_lock(path, timeout=self.lock_timeout, log=self._log):
                tok = file_token(path)
                got = self._read_disk(path)
            if got is None:
                return data
            text, disk = got
            if data is None:
                data = disk
            else:
                self._absorb(path, data, disk)
            if self._normalize:
                self._normalize(data)
            self.cache["data"] = data
            self.cache["path"] = str(path)
            self.cache["token"] = tok
            self.cache["base_text"] = text
            self.cache["mtime"] = (tok[0] / 1e9) if tok else 0.0
            return data

    def save(
        self,
        data: dict[str, Any],
        *,
        stamp: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """串行写盘；磁盘被外部改过则先合并。返回实际落盘的（共享）对象。"""
        path = self._path()
        with self.lock, file_lock(path, timeout=self.lock_timeout, log=self._log):
            cur = self._bound(path)
            if cur is None:
                cur = data
            elif data is not cur:
                # 调用方自己构造的整份账本：内容为准，但保持共享对象身份
                sync_inplace(cur, data)
            tok = file_token(path)
            if (
                tok is not None
                and self._bound(path) is cur
                and tok != self.cache.get("token")
            ):
                got = self._read_disk(path)
                if got is not None:
                    self._absorb(path, cur, got[1])
            if stamp:
                stamp(cur)
            text = self._dumps(cur)
            atomic_write_text(path, text)
            self._remember(path, cur, text)
            return cur

    def reload_from_disk(self) -> dict[str, Any] | None:
        """整份以磁盘为准（holdings-pull / clear-all 之后），保持对象身份。"""
        path = self._path()
        with self.lock, file_lock(path, timeout=self.lock_timeout, log=self._log):
            got = self._read_disk(path) if file_token(path) else None
            if got is None:
                self.cache.clear()
                return None
            text, disk = got
            cur = self._bound(path)
            if cur is None:
                cur = disk
            else:
                sync_inplace(cur, disk)
            if self._normalize:
                self._normalize(cur)
            self._remember(path, cur, text)
            return cur

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """读-改-写整段串行（与 save 同一把进程锁）。"""
        with self.lock:
            yield
