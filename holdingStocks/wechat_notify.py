"""盯盘预警 / 策略触发 → 微信推送（OpenClaw message send，不走大模型）。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "wechat_notify.json"
STATE_FILE = ROOT / "wechat_alert_state.json"

# 持仓状态 / 预警文案命中即视为可推送（与页面「预警带」一致）
_PUSH_POS = frozenset({"待买入", "待卖出"})
_PUSH_ALERT_KEYS = (
    "已触买",
    "将买入",
    "已触止损",
    "将止损",
    "待买入",
    "待卖出",
    "将卖出",
    "止损成交",
    "阴线收盘卖",
    "低开945未翻红",
    "因子2",
    "建议追加",
    "建议提出",
)
_PUSH_HIT = frozenset({"接近", "已触发"})

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
    """触发预警 / 接近预警 / 策略结算 / 因子2，均推送（对齐页面预警判定）。"""
    pos = str(row.get("持仓状态") or "")
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    near_buy = bool(row.get("近买点"))
    near_stop = bool(row.get("近止损"))
    f2_act = str(row.get("因子2动作") or "")

    # 1) 卡片持仓状态进入预警带
    if pos in _PUSH_POS:
        return True
    # 2) 因子触发：已触发（含「已触发 M/D」）或接近 → 一律推
    if hit in _PUSH_HIT or hit.startswith("已触发") or hit.startswith("接近"):
        return True
    # 3) 预警文案（已触买/将买入/将止损/止损成交…）
    if any(k in alert for k in _PUSH_ALERT_KEYS):
        return True
    # 4) 行情触及列
    if str(row.get("已触买") or "") == "是" or str(row.get("已触止损") or "") == "是":
        return True
    # 5) 页面「近买点 / 近止损」角标
    if near_buy or near_stop:
        return True
    # 6) 策略自动结算锁定
    if row.get("已实现") and alert:
        return True
    # 7) 因子2 追加/提出建议
    if f2_act in ("inject", "withdraw"):
        return True
    return False


def _alert_key(row: dict[str, Any]) -> str:
    code = str(row.get("代码") or "")
    pos = str(row.get("持仓状态") or "")
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    realized = "1" if row.get("已实现") else "0"
    f2 = f"{row.get('因子2动作')}|{row.get('因子2')}"
    # 接近→已触发、未触→已触 等变化要能再推
    touched = (
        f"{row.get('已触买')}|{row.get('已触止损')}|"
        f"{int(bool(row.get('近买点')))}|{int(bool(row.get('近止损')))}"
    )
    return f"{code}|{pos}|{alert}|{hit}|{realized}|{touched}|{f2}"


def _message_title(row: dict[str, Any]) -> str:
    f2_act = str(row.get("因子2动作") or "")
    if f2_act == "inject":
        return "【因子2追加】"
    if f2_act == "withdraw":
        return "【因子2提出】"
    if row.get("已实现"):
        return "【策略触发】"
    hit = str(row.get("因子触发") or "")
    alert = str(row.get("预警") or "")
    if (
        hit.startswith("已触发")
        or "已触" in alert
        or str(row.get("已触买")) == "是"
        or str(row.get("已触止损")) == "是"
    ):
        return "【触发预警】"
    if hit.startswith("接近") or hit == "接近" or "将" in alert or row.get("近买点") or row.get(
        "近止损"
    ):
        return "【接近预警】"
    return "【盯盘预警】"


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
    realized = bool(row.get("已实现"))

    def _n(v: Any) -> str:
        if v is None or v == "":
            return "-"
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return str(v)

    dist_txt = "-" if dist is None else f"{float(dist):+.2f}%"
    lines = [
        _message_title(row),
        f"{name}({code}) · {pos}",
        f"预警: {alert} · 因子触发: {hit} · 侧: {side}",
        f"现价 {_n(last)} · 因子价 {_n(factor)} · 距因子 {dist_txt}",
        f"建议挂单: {_n(suggest)}",
        f"已触买: {row.get('已触买') or '-'} · 已触止损: {row.get('已触止损') or '-'}",
    ]
    f2_act = str(row.get("因子2动作") or "")
    if f2_act in ("inject", "withdraw") or row.get("因子2"):
        lines.append(
            f"因子2: {row.get('因子2') or '-'} · 回撤{row.get('因子2回撤%')}% "
            f"· 档{row.get('因子2档位')} · 建议额{_n(row.get('因子2建议额'))}"
        )
    if realized:
        lines.append(
            f"成交价 {_n(row.get('成交价'))} · 当日盈亏 {_n(row.get('当日盈亏'))}"
        )
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


def send_text(
    message: str,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """通过 openclaw message send 推送纯文本（不调用大模型）。

    Windows 下不可把含换行的正文直接塞进 subprocess 参数列表
    （list2cmdline/CreateProcess 会截断到第一行），故经 Node argv 发送。
    """
    cfg = config or load_config()
    target = str(cfg.get("target") or "").strip()
    if not target:
        return False, "wechat_notify.json 未配置 target"

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
        if row.get("error"):
            continue
        # 个股预警：排除「仅因子2」重复刷屏（账户级单独推）
        f2_only = str(row.get("因子2动作") or "") in ("inject", "withdraw") and not (
            str(row.get("持仓状态") or "") in _PUSH_POS
            or str(row.get("因子触发") or "").startswith(("已触发", "接近"))
            or any(k in str(row.get("预警") or "") for k in _PUSH_ALERT_KEYS if k != "因子2")
            or str(row.get("已触买")) == "是"
            or str(row.get("已触止损")) == "是"
            or row.get("近买点")
            or row.get("近止损")
            or row.get("已实现")
        )
        if f2_only or not is_alert_row(row):
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

    # 账户级因子2：单独推一次
    f2_row = next(
        (
            r
            for r in rows
            if str(r.get("因子2动作") or "") in ("inject", "withdraw")
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
