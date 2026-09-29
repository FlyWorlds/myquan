# -*- coding: utf-8 -*-
"""账本存储层回归：旧数据不得覆盖新数据（2026-09-29 隔日粘滞复活 → 002636 假成交）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import holdings_store as hs  # noqa: E402


def _external_write(path: Path, obj: dict) -> None:
    """模拟另一进程（CLI / holdings-pull）改盘，并确保 mtime_ns 一定变化。"""
    before = hs.file_token(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    after = hs.file_token(path)
    if before is not None and after == before:
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "holdings.json"
        self.cache: dict = {"data": None, "mtime": 0.0}
        self.logs: list[str] = []
        self.store = hs.HoldingsStore(
            self.cache, path=lambda: self.path, log=self.logs.append
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _disk(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))


class TestMerge3(unittest.TestCase):
    def test_disjoint_edits_both_kept(self) -> None:
        base = {"a": 1, "b": {"x": 1, "y": 1}}
        ours = {"a": 2, "b": {"x": 1, "y": 1}}
        theirs = {"a": 1, "b": {"x": 1, "y": 9}, "c": 3}
        conflicts = hs.merge3_inplace(base, ours, theirs)
        self.assertEqual(ours, {"a": 2, "b": {"x": 1, "y": 9}, "c": 3})
        self.assertEqual(conflicts, [])

    def test_conflict_prefers_disk_and_is_reported(self) -> None:
        ours = {"cash": 100.0}
        conflicts = hs.merge3_inplace({"cash": 50.0}, ours, {"cash": 80.0})
        self.assertEqual(ours["cash"], 80.0)
        self.assertEqual(conflicts, ["cash"])

    def test_external_delete_applies_when_ours_untouched(self) -> None:
        ours = {"sticky": {"002636": {"session": "2026-09-28"}}}
        base = json.loads(json.dumps(ours))
        hs.merge3_inplace(base, ours, {"sticky": {}})
        self.assertEqual(ours["sticky"], {})

    def test_nested_identity_preserved(self) -> None:
        pos = {"qty": 100}
        ours = {"positions": {"600330": pos}}
        base = {"positions": {"600330": {"qty": 100}}}
        hs.merge3_inplace(base, ours, {"positions": {"600330": {"qty": 0}}})
        self.assertIs(ours["positions"]["600330"], pos)
        self.assertEqual(pos["qty"], 0)

    def test_stamp_keys_not_reported(self) -> None:
        ours = {"updated_at": "t1"}
        self.assertEqual(hs.merge3_inplace({"updated_at": "t0"}, ours, {"updated_at": "t2"}), [])


class TestResetContainer(unittest.TestCase):
    def test_holder_of_old_container_cannot_resurrect(self) -> None:
        """09-29 根因：重置换绑 {} 后，扫描持有的旧 sticky 被整份写回。"""
        data = {"alert_sticky": {"002636": {"session": "2026-09-28", "buy_touched": True}}}
        scan_ref = data["alert_sticky"]
        hs.reset_container(data, "alert_sticky", {})
        self.assertIs(data["alert_sticky"], scan_ref)
        self.assertEqual(scan_ref, {})

    def test_filtered_rebuild_keeps_identity(self) -> None:
        keep = {"session": "s2"}
        data = {"closed_today": {"a": {"session": "s1"}, "b": keep}}
        ref = data["closed_today"]
        hs.reset_container(
            data, "closed_today", {k: v for k, v in ref.items() if v["session"] == "s2"}
        )
        self.assertIs(data["closed_today"], ref)
        self.assertEqual(list(ref), ["b"])
        self.assertIs(ref["b"], keep)

    def test_list_in_place(self) -> None:
        data = {"q": [1, 2]}
        ref = data["q"]
        hs.reset_container(data, "q", [])
        self.assertIs(data["q"], ref)
        self.assertEqual(ref, [])


class TestHoldingsStore(_StoreCase):
    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(self.store.load())

    def test_identity_stable_across_external_write(self) -> None:
        self.path.write_text(json.dumps({"cash": 1, "positions": {}}), encoding="utf-8")
        first = self.store.load()
        pos_ref = first["positions"]
        _external_write(self.path, {"cash": 2, "positions": {"600330": {"qty": 100}}})
        again = self.store.load()
        self.assertIs(again, first)
        self.assertIs(again["positions"], pos_ref)
        self.assertEqual(again["cash"], 2)
        self.assertEqual(pos_ref["600330"]["qty"], 100)

    def test_save_merges_external_write_instead_of_overwriting(self) -> None:
        self.path.write_text(json.dumps({"cash": 1, "note": "a"}), encoding="utf-8")
        data = self.store.load()
        data["note"] = "watch"  # 盯盘内存改动，尚未落盘
        _external_write(self.path, {"cash": 999, "note": "a"})  # CLI 改现金
        self.store.save(data)
        disk = self._disk()
        self.assertEqual(disk["cash"], 999, "外部写入被旧数据覆盖")
        self.assertEqual(disk["note"], "watch")
        self.assertEqual(self.store.last_conflicts, [])

    def test_conflict_logged(self) -> None:
        self.path.write_text(json.dumps({"cash": 1}), encoding="utf-8")
        data = self.store.load()
        data["cash"] = 2
        _external_write(self.path, {"cash": 3})
        self.store.save(data)
        self.assertEqual(self._disk()["cash"], 3)
        self.assertTrue(any("cash" in m for m in self.logs))

    def test_foreign_dict_copied_into_shared_object(self) -> None:
        self.path.write_text(json.dumps({"cash": 1}), encoding="utf-8")
        shared = self.store.load()
        self.store.save({"cash": 5, "x": 1})
        self.assertIs(self.store.load(), shared)
        self.assertEqual(shared, {"cash": 5, "x": 1})

    def test_stamp_applied_after_merge(self) -> None:
        self.path.write_text(json.dumps({"updated_at": "old"}), encoding="utf-8")
        data = self.store.load()
        _external_write(self.path, {"updated_at": "ext"})
        self.store.save(data, stamp=lambda d: d.__setitem__("updated_at", "mine"))
        self.assertEqual(self._disk()["updated_at"], "mine")

    def test_atomic_write_leaves_no_tmp(self) -> None:
        self.store.save({"a": 1})
        self.assertEqual(self._disk(), {"a": 1})
        leftovers = [p.name for p in self.path.parent.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_own_writes_do_not_trigger_merge(self) -> None:
        self.store.save({"a": 1})
        for i in range(5):
            data = self.store.load()
            data["a"] = i
            self.store.save(data)
        self.assertEqual(self.store.last_conflicts, [])
        self.assertEqual(self.logs, [])

    def test_reload_from_disk_keeps_identity(self) -> None:
        self.path.write_text(json.dumps({"a": 1, "keep": {"x": 1}}), encoding="utf-8")
        data = self.store.load()
        keep_ref = data["keep"]
        data["local"] = True
        _external_write(self.path, {"a": 2, "keep": {"x": 2}})
        out = self.store.reload_from_disk()
        self.assertIs(out, data)
        self.assertIs(data["keep"], keep_ref)
        self.assertEqual(data, {"a": 2, "keep": {"x": 2}})

    def test_cache_cleared_means_cold_load(self) -> None:
        self.path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        first = self.store.load()
        self.cache.clear()
        self.cache.update({"data": None, "mtime": 0.0})
        self.assertIsNot(self.store.load(), first)

    def test_path_switch_does_not_merge_across_files(self) -> None:
        self.path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.store.load()
        other = self.path.with_name("other.json")
        other.write_text(json.dumps({"b": 2}), encoding="utf-8")
        store2 = hs.HoldingsStore(self.cache, path=lambda: other)
        self.assertEqual(store2.load(), {"b": 2})

    def test_concurrent_mutate_and_save(self) -> None:
        self.store.save({"positions": {}, "sticky": {}})
        errors: list[BaseException] = []

        def writer(tag: str) -> None:
            try:
                for i in range(40):
                    with self.store.transaction():
                        data = self.store.load()
                        data["positions"][f"{tag}{i}"] = {"qty": i}
                        self.store.save(data)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in "abcd"]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self._disk()["positions"]), 160, "并发写丢了更新")


class TestInterProcess(_StoreCase):
    def test_other_process_blocked_while_locked(self) -> None:
        self.store.save({"a": 1})
        code = (
            "import sys, time; sys.path.insert(0, %r);"
            "import holdings_store as hs; from pathlib import Path;"
            "t=time.monotonic();"
            "hs.write_json_locked(Path(%r), '{\"a\": 2}');"
            "print(round(time.monotonic()-t, 2))"
        ) % (str(_HOLD), str(self.path))
        with hs.file_lock(self.path):
            proc = subprocess.Popen(
                [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
            )
            threading.Event().wait(0.8)
            self.assertEqual(self._disk(), {"a": 1}, "锁内被外部进程改写")
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertGreaterEqual(float(out.strip()), 0.5)
        self.assertEqual(self._disk(), {"a": 2})
        data = self.store.load()
        self.assertEqual(data["a"], 2)


class TestIndexWiring(unittest.TestCase):
    """index.load_holdings / save_holdings 走存储层：身份稳定 + 容器原地重置。"""

    def setUp(self) -> None:
        import index

        self.index = index
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "holdings.json"
        self.path.write_text(
            json.dumps(
                {
                    "positions": {},
                    "realized_today": {},
                    "alert_sticky": {"002636": {"session": "2026-09-28", "buy_touched": True}},
                    "closed_today": {"002636": {"session": "2026-09-28"}},
                }
            ),
            encoding="utf-8",
        )
        self._saved = dict(index._HOLDINGS_CACHE)
        index._HOLDINGS_CACHE.clear()
        index._HOLDINGS_CACHE.update({"data": None, "mtime": 0.0})
        self._patch = mock.patch.object(index, "HOLDINGS_FILE", self.path)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.index._HOLDINGS_CACHE.clear()
        self.index._HOLDINGS_CACHE.update(self._saved)
        self._tmp.cleanup()

    def test_save_then_load_same_object(self) -> None:
        data = self.index.load_holdings()
        data["account_cash"] = 123.0
        self.index.save_holdings(data)
        self.assertIs(self.index.load_holdings(), data)
        disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(disk["account_cash"], 123.0)
        self.assertTrue(disk.get("updated_at"))

    def test_stale_sticky_holder_cannot_write_back(self) -> None:
        """扫描拿着旧 sticky，9:15 重置清空后，扫描尾部写回不得复活昨日粘滞。"""
        data = self.index.load_holdings()
        scan_sticky = self.index._alert_sticky_map(data)
        self.index.reset_container(data, "alert_sticky", {})
        self.index.save_holdings(data)
        self.index._save_alert_sticky("2026-09-28", scan_sticky)
        disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(disk["alert_sticky"], {})

    def test_purge_stale_realized_in_place(self) -> None:
        data = self.index.load_holdings()
        closed_ref = data["closed_today"]
        self.index._purge_stale_realized(data, "2026-09-29")
        self.assertIs(data["closed_today"], closed_ref)
        self.assertEqual(closed_ref, {})
        self.assertEqual(data["slot_queue"]["session"], "2026-09-29")

    def test_external_cli_write_absorbed(self) -> None:
        data = self.index.load_holdings()
        disk = json.loads(self.path.read_text(encoding="utf-8"))
        disk["account_cash"] = 777.0
        _external_write(self.path, disk)
        self.assertIs(self.index.load_holdings(), data)
        self.assertEqual(data["account_cash"], 777.0)


if __name__ == "__main__":
    unittest.main()
