"""把仍写在本地 JSON 里的运行时数据导入 MySQL，成功后删除源文件。

研究回测产物、backend/logs 备份和离线测试夹具不在范围内。
盯盘进程仍在跑时拒绝导入：它还会重写这些文件，提前拷贝会丢掉之后的更新。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _watch_pid() -> int:
    path = ROOT / "holdings_watch.pid"
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return int(raw.get("pid") or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def foreign_watch_running() -> bool:
    pid = _watch_pid()
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _store_if_empty(key: str, path: Path, payload: Any) -> str:
    from runtime_documents import read_document, write_document

    revision, _current = read_document(key)
    if revision > 0:
        if path.is_file():
            path.unlink()
        return "already-stored"
    if payload is None:
        return "missing"
    write_document(key, payload, 0)
    if path.is_file():
        path.unlink()
    return "imported"


def import_legacy(*, delete_ledger: bool = True) -> dict[str, str]:
    if foreign_watch_running():
        raise RuntimeError("盯盘进程仍在运行，先停止后再导入运行时 JSON")
    from runtime_documents import append_voided, voided_count

    result: dict[str, str] = {}
    state_path = ROOT / "strategy_sim_state.json"
    events_path = ROOT / "strategy_signal_events.json"
    void_path = ROOT / "strategy_signal_events.voided.json"
    watch_path = ROOT / "holdings_watch.json"
    alert_path = ROOT / "wechat_alert_state.json"
    config_path = ROOT / "wechat_notify.json"
    review_path = ROOT / "market_review_latest.json"
    review_text = ROOT / "market_review_latest.txt"
    names_path = ROOT / "cache" / "a_share_code_names.json"

    if state_path.is_file():
        result["strategy_simulator_state"] = _store_if_empty(
            "strategy_simulator_state", state_path, _load_json(state_path))
    if events_path.is_file():
        result["strategy_simulator_events"] = _store_if_empty(
            "strategy_simulator_events", events_path, _load_json(events_path))
    if watch_path.is_file():
        result["watch_snapshot"] = _store_if_empty("watch_snapshot", watch_path, _load_json(watch_path))
    if alert_path.is_file():
        result["wechat_alert_state"] = _store_if_empty(
            "wechat_alert_state", alert_path, _load_json(alert_path))
    if config_path.is_file():
        result["wechat_notify"] = _store_if_empty("wechat_notify", config_path, _load_json(config_path))
    if names_path.is_file():
        result["a_share_code_names"] = _store_if_empty(
            "a_share_code_names", names_path, _load_json(names_path))
    if review_path.is_file() or review_text.is_file():
        payload = _load_json(review_path) if review_path.is_file() else {}
        if review_text.is_file():
            payload["text"] = review_text.read_text(encoding="utf-8")
        result["market_review"] = _store_if_empty("market_review", review_path, payload)
        review_text.unlink(missing_ok=True)

    if void_path.is_file():
        raw = _load_json(void_path)
        events = list((raw or {}).get("events") or []) if isinstance(raw, dict) else list(raw or [])
        ids = {str(event.get("event_id") or "") for event in events if isinstance(event, dict) and event.get("event_id")}
        if events:
            append_voided([event for event in events if isinstance(event, dict) and event.get("event_id")])
        if not ids or voided_count() >= len(ids):
            void_path.unlink()
            result["strategy_sim_voided"] = f"stored:{voided_count()}"
        else:
            result["strategy_sim_voided"] = "incomplete"

    if delete_ledger:
        result["paper_ledger_files"] = _delete_migrated_ledger()
    return result


def _delete_migrated_ledger() -> str:
    from database_holdings import request_state

    state = request_state()
    if int(state.get("revision") or 0) <= 0:
        return "kept-until-account-migrated"
    for name in ("holdings.json", "trades.jsonl", "trade_ledger.json"):
        path = ROOT / name
        if path.is_file():
            path.unlink()
    return "deleted"


def schedule_legacy_import() -> None:
    if foreign_watch_running():
        print("[runtime-documents] 已有盯盘进程，跳过 JSON 导入")
        return

    def _run() -> None:
        try:
            summary = import_legacy()
        except Exception as exc:  # noqa: BLE001
            print(f"[runtime-documents] 历史 JSON 入库未完成: {exc}")
            return
        print("[runtime-documents] 历史 JSON 入库:", summary)

    threading.Thread(target=_run, name="runtime-json-import", daemon=True).start()


if __name__ == "__main__":
    print(import_legacy())
