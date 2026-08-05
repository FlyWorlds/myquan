"""盯盘预警 → 微信推送（OpenClaw message send，不走大模型）。"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "wechat_notify.json"
STATE_FILE = ROOT / "wechat_alert_state.json"

# 持仓状态 / 预警文案命中即视为可推送
_PUSH_POS = frozenset({"待买入", "待卖出"})
_PUSH_ALERT_KEYS = ("已触买", "将买入", "已触止损", "将止损", "待买入", "待卖出")

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "channel": "openclaw-weixin",
    "account": "3bbbe6b62301-im-bot",
    "target": "o9cq80_iIEqzbgJuahFUOOw1fbWc@im.wechat",
    "cooldown_sec": 1800,
    "openclaw_bin": "openclaw",
    "timeout_sec": 45,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config() -> dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if v is not None})
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_default_config(*, force: bool = False) -> Path:
    if CONFIG_FILE.exists() and not force:
        return CONFIG_FILE
    CONFIG_FILE.write_text(
        json.dumps(_DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return CONFIG_FILE


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"sent": {}}
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("sent", {})
            return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {"sent": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def is_alert_row(row: dict[str, Any]) -> bool:
    pos = str(row.get("持仓状态") or "")
    if pos in _PUSH_POS:
        return True
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    if any(k in alert for k in _PUSH_ALERT_KEYS):
        return True
    if hit == "接近" or hit == "已触发" or hit.startswith("已触发"):
        return pos in _PUSH_POS or any(k in alert for k in _PUSH_ALERT_KEYS)
    return False


def _alert_key(row: dict[str, Any]) -> str:
    code = str(row.get("代码") or "")
    pos = str(row.get("持仓状态") or "")
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    return f"{code}|{pos}|{alert}|{hit}"


def format_alert_message(row: dict[str, Any]) -> str:
    code = row.get("代码") or "-"
    name = row.get("名称") or "-"
    pos = row.get("持仓状态") or "-"
    alert = row.get("预警") or "-"
    hit = row.get("因子触发") or "-"
    last = row.get("现价")
    factor = row.get("因子价")
    dist = row.get("距因子%")
    suggest = row.get("建议挂单")
    side = row.get("因子侧") or "-"

    def _n(v: Any) -> str:
        if v is None or v == "":
            return "-"
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return str(v)

    dist_txt = "-" if dist is None else f"{float(dist):+.2f}%"
    lines = [
        "【盯盘预警】",
        f"{name}({code}) · {pos}",
        f"预警: {alert} · 因子触发: {hit} · 侧: {side}",
        f"现价 {_n(last)} · 因子价 {_n(factor)} · 距因子 {dist_txt}",
        f"建议挂单: {_n(suggest)}",
        f"时间: {_now()}",
    ]
    return "\n".join(lines)


def send_text(
    message: str,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """通过 openclaw message send 推送纯文本（不调用大模型）。"""
    cfg = config or load_config()
    target = str(cfg.get("target") or "").strip()
    if not target:
        return False, "wechat_notify.json 未配置 target"

    cmd = [
        str(cfg.get("openclaw_bin") or "openclaw"),
        "message",
        "send",
        "--channel",
        str(cfg.get("channel") or "openclaw-weixin"),
        "--target",
        target,
        "--message",
        message,
    ]
    account = str(cfg.get("account") or "").strip()
    if account:
        cmd.extend(["--account", account])

    timeout = float(cfg.get("timeout_sec") or 45)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "找不到 openclaw 命令，请确认已安装并在 PATH 中"
    except subprocess.TimeoutExpired:
        return False, f"openclaw message send 超时（>{timeout:.0f}s）"

    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and (
        "Sent via" in out or "sent" in out.lower() or not out
    )
    if proc.returncode == 0 and not ok:
        # 部分版本成功时几乎无输出
        ok = True
    if not ok:
        return False, out or f"exit={proc.returncode}"
    return True, out or "ok"


def notify_watch_rows(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """扫描盯盘行，对新增/变更预警做防抖推送。返回已推送摘要。"""
    cfg = config or load_config()
    if not force and not bool(cfg.get("enabled", True)):
        return []

    cooldown = max(60, int(cfg.get("cooldown_sec") or 1800))
    state = _load_state()
    sent: dict[str, Any] = state.setdefault("sent", {})
    now_ts = time.time()
    active_keys: set[str] = set()
    pushed: list[str] = []

    for row in rows:
        if row.get("error") or not is_alert_row(row):
            continue
        key = _alert_key(row)
        active_keys.add(key)
        prev_ts = float(sent.get(key) or 0)
        if not force and (now_ts - prev_ts) < cooldown:
            continue
        msg = format_alert_message(row)
        ok, detail = send_text(msg, config=cfg)
        code = str(row.get("代码") or "")
        name = str(row.get("名称") or "")
        if ok:
            sent[key] = now_ts
            pushed.append(f"{name}({code})")
            print(f"[{_now()}] 微信已推送: {name}({code})")
        else:
            print(f"[{_now()}] 微信推送失败 {name}({code}): {detail[:200]}")

    # 清理已不在预警带的旧 key
    for k in list(sent.keys()):
        if k not in active_keys:
            del sent[k]
    state["sent"] = sent
    state["updated_at"] = _now()
    _save_state(state)
    return pushed


def send_test_alert(*, config: dict[str, Any] | None = None) -> tuple[bool, str]:
    cfg = config or load_config()
    msg = (
        "【盯盘预警·测试】\n"
        "通道自检成功：OpenClaw 微信推送可用（不走大模型）。\n"
        f"时间: {_now()}"
    )
    return send_text(msg, config=cfg)
