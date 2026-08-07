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

# 仅可执行持仓状态（空仓「已触买」无待买入、无仓噪音不推）
_PUSH_POS = frozenset({"待买入", "待卖出"})

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
    """仅推可执行/需动作信号：待买待卖、实仓止损、策略止损、结算、因子2。"""
    pos = str(row.get("持仓状态") or "")
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    qty = int(row.get("持仓") or 0)
    f2_act = str(row.get("因子2动作") or "")

    # 1) 待买入 / 待卖出（含接近带）
    if pos in _PUSH_POS:
        return True
    if bool(row.get("可执行")):
        return True
    # 2) 当日禁买：止损后当日一次（防空仓反复刷「已触买」）
    if pos == "当日禁买" and (
        hit.startswith("策略止损")
        or "止损" in alert
        or bool(row.get("已实现"))
    ):
        return True
    # 3) 策略持有（未登记）：接近/触及止损才推
    if pos == "策略持有" and (
        bool(row.get("近止损"))
        or str(row.get("已触止损") or "") == "是"
        or hit.startswith("策略止损")
        or "将止损" in alert
    ):
        return True
    # 4) 实仓：近止损 / 已触止损（状态尚未翻到待卖出时兜底）
    if qty > 0 and (
        bool(row.get("近止损"))
        or str(row.get("已触止损") or "") == "是"
        or "将止损" in alert
    ):
        return True
    # 5) 策略自动结算
    if row.get("已实现") and alert:
        return True
    # 6) 因子2 追加/提出
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
    pos = str(row.get("持仓状态") or "")
    if f2_act == "inject":
        return "【因子2追加】"
    if f2_act == "withdraw":
        return "【因子2提出】"
    if row.get("已实现"):
        return "【策略触发】"
    if pos == "当日禁买" or str(row.get("因子触发") or "").startswith("策略止损"):
        return "【策略止损】"
    hit = str(row.get("因子触发") or "")
    alert = str(row.get("预警") or "")
    qty = int(row.get("持仓") or 0)
    stop_hit = str(row.get("已触止损")) == "是" and (
        qty > 0 or pos in ("待卖出", "策略持有", "当日禁买")
    )
    if (
        hit.startswith("已触发")
        or "已触" in alert
        or (pos == "待买入" and str(row.get("已触买")) == "是")
        or stop_hit
    ):
        return "【触发预警】"
    if (
        hit.startswith("接近")
        or hit == "接近"
        or "将" in alert
        or (pos == "待买入" and row.get("近买点"))
        or (pos in ("待卖出", "持有", "策略持有") and row.get("近止损"))
    ):
        return "【接近预警】"
    if pos in _PUSH_POS:
        return "【盯盘预警】"
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
        # 个股行：因子2仅账户级推一次，这里跳过「纯因子2」行
        pos = str(row.get("持仓状态") or "")
        f2_act = str(row.get("因子2动作") or "")
        stock_signal = (
            pos in _PUSH_POS
            or bool(row.get("可执行"))
            or pos in ("当日禁买", "策略持有")
            or (
                int(row.get("持仓") or 0) > 0
                and (
                    bool(row.get("近止损"))
                    or str(row.get("已触止损") or "") == "是"
                    or "将止损" in str(row.get("预警") or "")
                )
            )
            or bool(row.get("已实现"))
        )
        if f2_act in ("inject", "withdraw") and not stock_signal:
            continue
        if not is_alert_row(row):
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


def prepare_wechat_for_watch(
    *,
    config: dict[str, Any] | None = None,
    send_test: bool = True,
    restart_gateway: bool = False,
) -> tuple[bool, str]:
    """盯盘启动套件：OpenClaw Gateway → 微信通道自检。

    返回 (ok, detail)。失败时 detail 含原因，供调用方决定是否中止。
    """
    cfg = config or load_config()
    if not bool(cfg.get("enabled", True)):
        return False, "wechat_notify.json enabled=false"

    print(f"[{_now()}] [1/2] 检查/启动 OpenClaw Gateway…")
    ok, detail = ensure_openclaw_gateway(config=cfg, restart=restart_gateway)
    if not ok:
        return False, f"OpenClaw Gateway 不可用: {detail[:400]}"
    print(f"[{_now()}] OpenClaw Gateway OK")

    if not send_test:
        return True, detail

    print(f"[{_now()}] [2/2] 微信通道自检…")
    ok2, detail2 = send_test_alert(config=cfg)
    if not ok2:
        tip = (
            "微信自检失败。若 prepare failed：请先给机器人发一条消息建立会话，"
            "或重新 openclaw channels login --channel openclaw-weixin"
        )
        return False, f"{detail2[:350]}\n{tip}"
    print(f"[{_now()}] 微信通道自检成功")
    return True, detail2


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
