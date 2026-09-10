"""盯盘预警 / 策略触发 → 微信推送（OpenClaw message send，不走大模型）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from watch_buy_signal import ALERT_PRICE_NO_GATE, is_buy_hit, is_weak_price_buy_alert


_SEND_LOCK = threading.Lock()
_LAST_SEND_TS = 0.0

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "wechat_notify.json"
STATE_FILE = ROOT / "wechat_alert_state.json"

# 预警优先级：P0=因子已触发；P1=触发预警带
PRIORITY_P0 = "P0"  # 因子已触发
PRIORITY_P1 = "P1"  # 触发预警带
KIND_P0 = "因子已触发"
KIND_P1 = "触发预警带"

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "channel": "openclaw-weixin",
    # 真实 account/target 只写本地 wechat_notify.json（已 gitignore）
    "account": "",
    "target": "",
    "cooldown_sec": 1800,
    "openclaw_bin": "openclaw",
    "timeout_sec": 45,
    # Windows nvm：可填 Node 目录，发送前拼进 PATH
    "node_bin_dir": "",
    # 启动自检：Gateway 就绪后再等通道 settle；发送失败重试；prepare failed 时等人发消息预热
    "channel_settle_sec": 4,
    "send_retries": 3,
    "send_retry_backoff_sec": 2.0,
    "wait_inbound_sec": 180,
    "wait_inbound_poll_sec": 8,
}


def _safe_print(msg: str) -> None:
    """Windows GBK 控制台下避免因特殊字符抛 UnicodeEncodeError。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


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


def _has_holding(row: dict[str, Any]) -> bool:
    """有仓：实仓，或策略回放仍持有（未登记也按有仓盯止损）。"""
    qty = int(row.get("持仓") or 0)
    pos = str(row.get("持仓状态") or "")
    if qty > 0 or pos in ("持有", "已经买入", "待卖出", "策略持有"):
        return True
    return bool(row.get("策略回放持有")) and pos not in (
        "当日禁买",
        "已止损",
        "已平仓",
        "已触止损平仓",
    )


def _factor_px_for_push(row: dict[str, Any], *, holding: bool) -> Any:
    """推送用因子价：有仓=止损价；空仓=买点。"""
    if holding:
        for k in ("止损", "未触发因子价", "因子价", "建议挂单"):
            if row.get(k) is not None and row.get(k) != "":
                return row.get(k)
        return None
    for k in ("买点", "未触发因子价", "因子价", "建议挂单"):
        if row.get(k) is not None and row.get(k) != "":
            return row.get(k)
    return None


def classify_stock_alert(row: dict[str, Any]) -> dict[str, Any] | None:
    """股票池推送分类。

    - 有持仓：仅止损侧（P0 因子已触发 / P1 触发预警带）
    - 无持仓：仅买入侧（P0 / P1）
    - 过门未过禁买空仓：不推买入；当日卖出后再触买仍推
    返回 None 表示不推；否则含 level/kind/type/factor_px。
    """
    if row.get("error"):
        return None
    pos = str(row.get("持仓状态") or "")
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    # 仅「当日禁买」挡买入；已止损但再触买（待买入）仍可推
    no_buy = bool(row.get("当日禁买")) or pos == "当日禁买"
    holding = _has_holding(row)

    hit_buy = is_buy_hit(row)
    hit_stop = str(row.get("已触止损") or "") == "是"
    near_buy = bool(row.get("近买点"))
    near_stop = bool(row.get("近止损"))

    def _pack(level: str, kind: str, typ: str, factor_px: Any) -> dict[str, Any]:
        return {
            "level": level,
            "kind": kind,
            "type": typ,
            "factor_px": factor_px,
        }

    # 有仓刚结算：P0 止损因子一次
    if row.get("已实现") and (
        hit_stop or "止损" in alert or hit.startswith("策略止损")
    ) and not (
        hit_buy or pos == "待买入" or "再触买" in alert or "可再买" in alert
    ):
        return _pack(
            PRIORITY_P0,
            KIND_P0,
            "已触止损",
            row.get("成交价")
            if row.get("成交价") is not None
            else _factor_px_for_push(row, holding=True),
        )

    if holding:
        if (
            hit_buy
            or "已触买" in alert
            or (pos == "待买入" and hit.startswith("已触发"))
        ):
            return _pack(
                PRIORITY_P0,
                KIND_P0,
                "已触买",
                row.get("买入侧价")
                or row.get("买点")
                or _factor_px_for_push(row, holding=False),
            )
        if (
            hit_stop
            or hit.startswith("策略止损")
            or "已触止损" in alert
            or (pos == "待卖出" and hit.startswith("已触发"))
        ):
            return _pack(
                PRIORITY_P0,
                KIND_P0,
                "已触止损",
                _factor_px_for_push(row, holding=True),
            )
        if (
            near_stop
            or pos == "待卖出"
            or "将止损" in alert
            or hit == "接近"
            or hit.startswith("接近")
        ):
            return _pack(
                PRIORITY_P1,
                KIND_P1,
                "将止损",
                _factor_px_for_push(row, holding=True),
            )
        return None

    # 无持仓：过门禁买 → 不推买入；当日卖出后再触买仍推
    if no_buy:
        return None
    if is_weak_price_buy_alert(row) or ALERT_PRICE_NO_GATE in alert:
        return _pack(
            PRIORITY_P1,
            KIND_P1,
            ALERT_PRICE_NO_GATE,
            row.get("买入侧价")
            or row.get("买点")
            or _factor_px_for_push(row, holding=False),
        )
    if (
        hit_buy
        or (pos == "待买入" and hit.startswith("已触发"))
        or "已触买" in alert
        or "再触买" in alert
        or "收盘动量可再买" in alert
    ):
        return _pack(
            PRIORITY_P0,
            KIND_P0,
            "已触买",
            _factor_px_for_push(row, holding=False),
        )
    if (
        near_buy
        or pos == "待买入"
        or "将买入" in alert
        or hit == "接近"
        or hit.startswith("接近")
    ):
        return _pack(
            PRIORITY_P1,
            KIND_P1,
            "将买入",
            _factor_px_for_push(row, holding=False),
        )
    return None


def is_alert_row(row: dict[str, Any]) -> bool:
    """股票池：有仓只推止损；空仓只推买入。因子2走账户级通道。"""
    return classify_stock_alert(row) is not None


def _alert_key(row: dict[str, Any]) -> str:
    code = str(row.get("代码") or "")
    info = classify_stock_alert(row) or {}
    return (
        f"{code}|{info.get('level')}|{info.get('kind')}|{info.get('type')}|"
        f"{row.get('已触买')}|{row.get('已触止损')}|"
        f"{int(bool(row.get('近买点')))}|{int(bool(row.get('近止损')))}"
    )


def format_alert_message(row: dict[str, Any]) -> str:
    info = classify_stock_alert(row)
    code = row.get("代码") or "-"
    name = row.get("名称") or "-"
    digits = int(row.get("价位小数") or 2)
    qty = int(row.get("持仓") or 0)

    def _n(v: Any) -> str:
        if v is None or v == "":
            return "-"
        try:
            return f"{float(v):.{digits}f}"
        except (TypeError, ValueError):
            return str(v)

    if info is None:
        return f"【盯盘】{name}({code})\n时间: {_now()}"

    level = str(info["level"])
    kind = str(info["kind"])
    typ = str(info["type"])
    lines = [
        f"【{level}】{name}({code})",
        f"预警类型: {level}·{kind}·{typ}",
        f"因子价格: {_n(info.get('factor_px'))}",
        f"现价: {_n(row.get('现价'))}",
    ]
    if qty > 0:
        lines.insert(2, f"持仓: {qty}股")
    lines.append(f"时间: {_now()}")
    return "\n".join(lines)


def _env_with_node(cfg: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    node_dir = str(cfg.get("node_bin_dir") or "").strip()
    if node_dir and Path(node_dir).is_dir():
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
    return env


def _resolve_openclaw_node(openclaw_bin: str, env: dict[str, str]) -> tuple[str, list[str]]:
    """把 openclaw.cmd 解析成 node + openclaw.mjs，便于 argv 保留换行。"""
    bin_path = Path(str(openclaw_bin))
    candidates: list[Path] = []
    if bin_path.suffix.lower() in {".cmd", ".bat"}:
        candidates.append(bin_path.parent / "node_modules" / "openclaw" / "openclaw.mjs")
    # PATH 里找同目录
    for part in str(env.get("PATH") or "").split(os.pathsep):
        if not part:
            continue
        base = Path(part)
        candidates.append(base / "node_modules" / "openclaw" / "openclaw.mjs")
        if bin_path.name.lower().startswith("openclaw"):
            candidates.append(base / "node_modules" / "openclaw" / "openclaw.mjs")

    mjs: Path | None = None
    for c in candidates:
        if c.is_file():
            mjs = c
            break
    if mjs is None:
        # 退回原 bin（可能非 Windows .cmd）
        return str(openclaw_bin), []

    node_exe = "node"
    node_dir = Path(mjs).parents[2]  # .../nvm/v24.15.0/node_modules/openclaw → v24.15.0
    # parents: openclaw, node_modules, v24.15.0
    if (node_dir / "node.exe").is_file():
        node_exe = str(node_dir / "node.exe")
    elif (node_dir / "node").is_file():
        node_exe = str(node_dir / "node")
    return node_exe, [str(mjs)]


def _send_via_node_argv(
    openclaw_bin: str,
    args: list[str],
    message: str,
    *,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """经 Node spawnSync 传参，避免 Windows CreateProcess 截断 --message 内换行。"""
    import tempfile

    exe, prefix = _resolve_openclaw_node(openclaw_bin, env)
    # 最终 argv: node openclaw.mjs message send ...  或  openclaw message send ...
    payload = {
        "bin": exe,
        "args": prefix + args,
        "message": message,
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False)
        payload_path = tf.name

    # 单行 JS，勿含未转义换行（否则又会踩 Windows argv）
    js = (
        "const fs=require('fs');const {spawnSync}=require('child_process');"
        f"const p=JSON.parse(fs.readFileSync({json.dumps(payload_path)},'utf8'));"
        "const a=p.args.slice();"
        "const i=a.indexOf('--message');"
        "if(i>=0)a[i+1]=p.message;else a.push('--message',p.message);"
        "const r=spawnSync(p.bin,a,{encoding:'utf8',env:process.env});"
        "if(r.error){process.stderr.write(String(r.error));process.exit(1);}"
        "if(r.stdout)process.stdout.write(r.stdout);"
        "if(r.stderr)process.stderr.write(r.stderr);"
        "try{fs.unlinkSync(" + json.dumps(payload_path) + ");}catch(e){}"
        "process.exit(r.status==null?1:r.status);"
    )
    node_launcher = "node"
    # 优先用与 openclaw 同目录的 node，避免落到别的 node
    if exe.lower().endswith("node.exe") or Path(exe).name.lower() in {"node", "node.exe"}:
        node_launcher = exe
    try:
        return subprocess.run(
            [node_launcher, "-e", js],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        try:
            os.unlink(payload_path)
        except OSError:
            pass
        raise


def _is_prepare_failed(detail: str) -> bool:
    d = (detail or "").lower()
    return (
        "prepare failed" in d
        or "ret=-2" in d
        or "contexttoken missing" in d
        or "context_token" in d and "missing" in d
    )


def _is_transient_send_error(detail: str) -> bool:
    d = (detail or "").lower()
    return any(
        x in d
        for x in (
            "timeout",
            "econnreset",
            "tls",
            "fetch failed",
            "gateway not",
            "not reachable",
            "socket",
            "temporar",
        )
    )


def _send_text_once(
    message: str,
    *,
    cfg: dict[str, Any],
) -> tuple[bool, str]:
    """单次 openclaw message send（已持锁时可直接调）。"""
    global _LAST_SEND_TS
    target = str(cfg.get("target") or "").strip()
    if not target:
        return False, "wechat_notify.json 未配置 target"

    # 避免连发撞微信侧 prepare / 限流
    gap = max(0.0, 1.2 - (time.time() - _LAST_SEND_TS))
    if gap > 0:
        time.sleep(gap)

    openclaw_bin = str(cfg.get("openclaw_bin") or "openclaw")
    args = [
        "message",
        "send",
        "--channel",
        str(cfg.get("channel") or "openclaw-weixin"),
        "--target",
        target,
        "--message",
        "",  # 占位，由 Node 写入真实正文
    ]
    account = str(cfg.get("account") or "").strip()
    if account:
        args.extend(["--account", account])

    timeout = float(cfg.get("timeout_sec") or 45)
    env = _env_with_node(cfg)
    try:
        proc = _send_via_node_argv(
            openclaw_bin,
            args,
            message,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError:
        # 无 node：压成单行再直调 openclaw（功能降级，无换行）
        flat = " | ".join(
            ln.strip() for ln in str(message).splitlines() if ln.strip()
        )
        cmd = [openclaw_bin] + list(args)
        if len(cmd) >= 2 and cmd[-2] == "--message":
            cmd[-1] = flat
        else:
            cmd.extend(["--message", flat])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=env,
            )
        except FileNotFoundError:
            return False, "找不到 openclaw/node 命令，请确认已安装并在 PATH 中"
        except subprocess.TimeoutExpired:
            return False, f"openclaw message send 超时（>{timeout:.0f}s）"
    except subprocess.TimeoutExpired:
        return False, f"openclaw message send 超时（>{timeout:.0f}s）"

    _LAST_SEND_TS = time.time()
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


def send_text(
    message: str,
    *,
    config: dict[str, Any] | None = None,
    retries: int | None = None,
) -> tuple[bool, str]:
    """通过 openclaw message send 推送纯文本（不调用大模型）。

    Windows 下不可把含换行的正文直接塞进 subprocess 参数列表
    （list2cmdline/CreateProcess 会截断到第一行），故经 Node argv 发送。
    对 prepare failed / 瞬时网络错误自动重试。
    """
    cfg = config or load_config()
    n = int(cfg.get("send_retries") if retries is None else retries)
    n = max(1, n)
    backoff = float(cfg.get("send_retry_backoff_sec") or 2.0)
    last = ""
    with _SEND_LOCK:
        for i in range(n):
            ok, detail = _send_text_once(message, cfg=cfg)
            if ok:
                return True, detail
            last = detail
            retryable = _is_prepare_failed(detail) or _is_transient_send_error(detail)
            if not retryable or i >= n - 1:
                break
            wait = backoff * (i + 1)
            print(
                f"[{_now()}] 微信发送失败，{wait:.0f}s 后重试 "
                f"({i + 1}/{n}): {(detail or '')[:120]}"
            )
            time.sleep(wait)
    return False, last


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
        if row.get("error"):
            continue
        # 个股只走 classify；因子2账户级单独推
        info = classify_stock_alert(row)
        if info is None:
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
            print(
                f"[{_now()}] 微信已推送: {name}({code}) "
                f"{info.get('level')}·{info.get('kind')}·{info.get('type')}"
            )
        else:
            print(f"[{_now()}] 微信推送失败 {name}({code}): {detail[:200]}")

    # 账户级因子2：单独推一次
    f2_row = next(
        (
            r
            for r in rows
            if str(r.get("因子2动作") or "") in (
                "inject",
                "withdraw",
                "add_alert",
                "reduce_alert",
                "near_max",
            )
        ),
        None,
    )
    if f2_row is not None:
        f2_act = str(f2_row.get("因子2动作"))
        f2_key = f"factor2|{f2_row.get('因子2')}|{f2_act}"
        active_keys.add(f2_key)
        prev_ts = float(sent.get(f2_key) or 0)
        if force or (now_ts - prev_ts) >= cooldown:
            try:
                from factor2_watch import format_factor2_push

                f2_status = {
                    "action": f2_act,
                    "label": f2_row.get("因子2"),
                    "dd_pct": f2_row.get("因子2回撤%"),
                    "layers": f2_row.get("因子2档位"),
                    "suggest_amount": f2_row.get("因子2建议额"),
                    "equity": None,
                    "peak": None,
                    "levels_label": "",
                    "add_pct": 0.1,
                }
                hp = ROOT / "holdings.json"
                if hp.exists():
                    raw = json.loads(hp.read_text(encoding="utf-8"))
                    saved = raw.get("factor2") if isinstance(raw, dict) else None
                    if isinstance(saved, dict):
                        f2_status = {
                            **saved,
                            "action": f2_act,
                            "label": f2_row.get("因子2") or saved.get("last_label"),
                            "levels_label": "/".join(
                                f"{float(x)*100:.0f}"
                                for x in (saved.get("levels") or [])
                            ),
                        }
                msg = format_factor2_push(f2_status)
            except Exception:
                msg = format_alert_message(f2_row)
            ok, detail = send_text(msg, config=cfg)
            if ok:
                sent[f2_key] = now_ts
                pushed.append("因子2(账户)")
                print(f"[{_now()}] 微信已推送: 因子2(账户)")
            else:
                print(f"[{_now()}] 微信推送失败 因子2: {detail[:200]}")

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


def _run_openclaw_cli(
    cli_args: list[str],
    *,
    config: dict[str, Any] | None = None,
    timeout: float = 90,
) -> tuple[int, str]:
    """跑 openclaw 子命令（经 node+mjs，兼容 Windows .cmd）。"""
    cfg = config or load_config()
    openclaw_bin = str(cfg.get("openclaw_bin") or "openclaw")
    env = _env_with_node(cfg)
    exe, prefix = _resolve_openclaw_node(openclaw_bin, env)
    # prefix 非空：node + openclaw.mjs + cli；否则直接 openclaw.cmd/bin
    cmd = [exe, *prefix, *cli_args] if prefix else [openclaw_bin, *cli_args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return 127, "找不到 openclaw/node"
    except subprocess.TimeoutExpired:
        return 124, f"openclaw {' '.join(cli_args)} 超时"
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return int(proc.returncode), out


def gateway_reachable(*, config: dict[str, Any] | None = None) -> tuple[bool, str]:
    """探测 Gateway 是否可连（gateway status）。"""
    code, out = _run_openclaw_cli(
        ["gateway", "status"], config=config, timeout=60
    )
    text = out or ""
    ok = (
        code == 0
        and (
            "Connectivity probe: ok" in text
            or "Runtime: running" in text
            or "listening" in text.lower()
        )
    )
    return ok, text


def ensure_openclaw_gateway(
    *,
    config: dict[str, Any] | None = None,
    restart: bool = False,
) -> tuple[bool, str]:
    """确保 OpenClaw Gateway 在跑；必要时 start / restart。"""
    cfg = config or load_config()
    if not restart:
        ok, detail = gateway_reachable(config=cfg)
        if ok:
            return True, "Gateway 已在运行"

    action = "restart" if restart else "start"
    print(f"[{_now()}] OpenClaw Gateway {action}…")
    code, out = _run_openclaw_cli(
        ["gateway", action], config=cfg, timeout=120
    )
    # start/restart 后稍等再探测
    deadline = time.time() + 45
    last = out
    while time.time() < deadline:
        time.sleep(2.0)
        ok, last = gateway_reachable(config=cfg)
        if ok:
            return True, f"Gateway {action} 成功"
    # 再试一次 restart
    if action == "start":
        print(f"[{_now()}] Gateway 未就绪，尝试 restart…")
        _run_openclaw_cli(["gateway", "restart"], config=cfg, timeout=120)
        time.sleep(4.0)
        ok, last = gateway_reachable(config=cfg)
        if ok:
            return True, "Gateway restart 成功"
    return False, last or out or f"gateway {action} 失败 (exit={code})"


def weixin_channel_ready(*, config: dict[str, Any] | None = None) -> tuple[bool, str]:
    """探测 openclaw-weixin 账号是否 configured + running。"""
    cfg = config or load_config()
    account = str(cfg.get("account") or "").strip()
    code, out = _run_openclaw_cli(
        ["channels", "status", "--probe"], config=cfg, timeout=90
    )
    text = out or ""
    if code != 0 and "Gateway reachable" not in text:
        return False, text or f"channels status exit={code}"

    lines = [ln.strip() for ln in text.splitlines() if "openclaw-weixin" in ln]
    if account:
        hit = next((ln for ln in lines if account in ln), "")
        if not hit:
            return False, f"未在 probe 中找到账号 {account}\n{text[:400]}"
        # "enabled, configured, running" 为通过
        ok = (
            "configured" in hit
            and "running" in hit
            and "not configured" not in hit
        )
        return ok, hit or text
    any_ok = any(
        "configured" in ln and "running" in ln and "not configured" not in ln
        for ln in lines
    )
    return any_ok, "\n".join(lines) or text


def wait_weixin_channel_ready(
    *,
    config: dict[str, Any] | None = None,
    timeout_sec: float = 45,
) -> tuple[bool, str]:
    cfg = config or load_config()
    deadline = time.time() + max(5.0, timeout_sec)
    last = ""
    while time.time() < deadline:
        ok, last = weixin_channel_ready(config=cfg)
        if ok:
            return True, last
        time.sleep(2.0)
    return False, last or "微信通道未就绪"


def context_token_status(*, config: dict[str, Any] | None = None) -> tuple[bool, str]:
    """检查本地是否已有 target 对应的 context_token 文件（不打印 token）。"""
    cfg = config or load_config()
    account = str(cfg.get("account") or "").strip()
    target = str(cfg.get("target") or "").strip()
    if not account or not target:
        return False, "account/target 未配置"
    path = (
        Path.home()
        / ".openclaw"
        / "openclaw-weixin"
        / "accounts"
        / f"{account}.context-tokens.json"
    )
    if not path.is_file():
        return False, f"无会话文件（需先给机器人发一条微信）: {path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"会话文件损坏: {e}"
    if not isinstance(data, dict) or not data:
        return False, "会话文件为空"
    uid = target.split("@")[0]
    keys = list(data.keys())
    hit = target in keys or uid in keys or any(
        str(k).split("@")[0] == uid for k in keys
    )
    age_h = (time.time() - path.stat().st_mtime) / 3600.0
    if not hit:
        return False, f"会话文件无本机 target（keys={len(keys)}, age={age_h:.1f}h）"
    return True, f"本地会话 token 存在（age={age_h:.1f}h）"


def _ensure_plugin_disk_fallback_patch() -> str:
    """尽力给 openclaw-weixin 打磁盘回落补丁（幂等）。"""
    script = ROOT / "tools" / "patch_openclaw_weixin_context_token.py"
    if not script.is_file():
        return "no-script"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            cwd=str(ROOT),
        )
    except Exception as e:  # noqa: BLE001
        return f"patch-error:{e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return f"patch-fail:{out[:200]}"
    # Windows 控制台常为 GBK：去掉无法编码字符，避免 print 炸毁整套启动
    line = out.splitlines()[0] if out else "patched"
    return line.encode("ascii", "replace").decode("ascii")[:200]


def wait_inbound_and_retry_send(
    message: str,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """prepare failed 时提示用户给机器人发消息，并轮询直到可发或超时。"""
    cfg = config or load_config()
    wait_sec = float(cfg.get("wait_inbound_sec") or 0)
    if wait_sec <= 0:
        return False, "wait_inbound_sec=0，跳过会话预热等待"
    poll = max(3.0, float(cfg.get("wait_inbound_poll_sec") or 8))
    print(
        f"[{_now()}] 微信会话 token 已失效（服务端 prepare failed；本地磁盘回落已生效但仍被拒）。\n"
        f"  → 请用微信给【盯盘机器人】发任意一条消息（如：1）刷新 context_token。\n"
        f"  → 网关 getUpdates 收到后会自动写入会话文件；最多等待 {wait_sec:.0f}s 并重试发送。\n"
        f"  → 若长时间无反应：openclaw channels login --channel openclaw-weixin"
    )
    deadline = time.time() + wait_sec
    last = ""
    attempt = 0
    while time.time() < deadline:
        time.sleep(poll)
        attempt += 1
        tok_ok, tok_detail = context_token_status(config=cfg)
        print(
            f"[{_now()}] 预热探测 #{attempt}: token={tok_detail}; 尝试发送…"
        )
        ok, last = send_text(message, config=cfg, retries=1)
        if ok:
            print(f"[{_now()}] 会话已恢复，发送成功")
            return True, last
        if not _is_prepare_failed(last):
            # 非 prepare 类错误，不必空等
            break
    return False, last or "等待入站刷新超时"


def prepare_wechat_for_watch(
    *,
    config: dict[str, Any] | None = None,
    send_test: bool = True,
    restart_gateway: bool = False,
) -> tuple[bool, str]:
    """盯盘启动套件：补丁 → Gateway → 通道就绪 → 微信自检。

    返回 (ok, detail)。失败时 detail 含原因，供调用方决定是否中止。
    """
    cfg = config or load_config()
    if not bool(cfg.get("enabled", True)):
        return False, "wechat_notify.json enabled=false"

    print(f"[{_now()}] [0/3] 检查 openclaw-weixin context_token 磁盘回落补丁…")
    patch_info = _ensure_plugin_disk_fallback_patch()
    _safe_print(f"[{_now()}] 补丁: {patch_info[:200]}")

    print(f"[{_now()}] [1/3] 检查/启动 OpenClaw Gateway…")
    ok, detail = ensure_openclaw_gateway(config=cfg, restart=restart_gateway)
    if not ok:
        return False, f"OpenClaw Gateway 不可用: {detail[:400]}"
    print(f"[{_now()}] OpenClaw Gateway OK")

    settle = float(cfg.get("channel_settle_sec") or 4)
    print(f"[{_now()}] [2/3] 等待微信通道就绪（settle {settle:.0f}s）…")
    if settle > 0:
        time.sleep(settle)
    ch_ok, ch_detail = wait_weixin_channel_ready(config=cfg, timeout_sec=40)
    if not ch_ok:
        # 再强制 restart 一次常能恢复 TLS/长轮询挂死
        print(f"[{_now()}] 通道未就绪，自动 gateway restart…")
        ok2, detail2 = ensure_openclaw_gateway(config=cfg, restart=True)
        if not ok2:
            return False, f"微信通道未就绪且 Gateway 重启失败: {detail2[:300]}"
        time.sleep(max(settle, 3.0))
        ch_ok, ch_detail = wait_weixin_channel_ready(config=cfg, timeout_sec=40)
        if not ch_ok:
            return False, f"微信通道未就绪: {ch_detail[:400]}"
    print(f"[{_now()}] 微信通道 OK: {ch_detail[:160]}")

    tok_ok, tok_detail = context_token_status(config=cfg)
    print(f"[{_now()}] 会话 token: {tok_detail}")

    if not send_test:
        return True, detail

    print(f"[{_now()}] [3/3] 微信通道自检…")
    ok2, detail2 = send_test_alert(config=cfg)
    if ok2:
        print(f"[{_now()}] 微信通道自检成功")
        return True, detail2

    if _is_prepare_failed(detail2):
        # 磁盘 token 过期：等人发消息；同时再 restart 一次加载补丁/清 TLS
        if "disk-fallback" not in patch_info and "patched" not in patch_info.lower():
            print(f"[{_now()}] 补丁可能未生效，gateway restart 后再试…")
        else:
            print(f"[{_now()}] prepare failed：gateway restart 后重试一次…")
        ensure_openclaw_gateway(config=cfg, restart=True)
        time.sleep(max(settle, 3.0))
        wait_weixin_channel_ready(config=cfg, timeout_sec=30)
        ok3, detail3 = send_test_alert(config=cfg)
        if ok3:
            print(f"[{_now()}] 微信通道自检成功（重启后）")
            return True, detail3
        detail2 = detail3
        ok4, detail4 = wait_inbound_and_retry_send(
            (
                "【盯盘预警·测试】\n"
                "通道自检成功：OpenClaw 微信推送可用（不走大模型）。\n"
                f"时间: {_now()}"
            ),
            config=cfg,
        )
        if ok4:
            return True, detail4
        detail2 = detail4

    tip = (
        "微信自检失败。\n"
        "若 prepare failed：用微信给机器人发任意一条消息刷新会话，然后重跑；\n"
        "或: openclaw channels login --channel openclaw-weixin\n"
        "也可临时: watch --wechat-optional / --skip-wechat-check"
    )
    return False, f"{detail2[:350]}\n{tip}"


def send_startup_message(
    *,
    url: str = "",
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """盯盘 watch 启动完成后推送一条（不走大模型）。"""
    cfg = config or load_config()
    lines = [
        "【盯盘启动完成】",
        "持仓盯盘已启动，微信仅推送预警/策略触发（不走大模型）。",
        f"时间: {_now()}",
    ]
    if url:
        lines.append(f"页面: {url}")
    return send_text("\n".join(lines), config=cfg)


def send_review_message(
    message: str,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """推送行情复盘全文（不走大模型）。"""
    return send_text(message, config=config)
