"""盯盘预警 / 策略触发 → 微信推送（OpenClaw message send，不走大模型）。

N1 语义：【策略预警】只覆盖未成交信号；【模拟买入】/【模拟卖出】只在
paper mutation + ledger 成功后由 notify_trade_fill 发送。扫描层不得重复
推送已成交事件。Shadow / DecisionEngine 不调用本模块。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from watch_buy_signal import ALERT_PRICE_NO_GATE, is_buy_hit, is_weak_price_buy_alert


_SEND_LOCK = threading.Lock()
_LAST_SEND_TS = 0.0
# None=跟随 wechat_notify.json enabled；False=watch --no-wechat（成交+预警都不发）
_WATCH_WECHAT_ENABLED: bool | None = None
# True=盘中入队由 worker 发送（不阻塞盯盘）；False=同步发送（单测/复盘 CLI）
_ASYNC_DELIVERY: bool = True

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "wechat_notify.json"
STATE_FILE = ROOT / "wechat_alert_state.json"

# 发送错误分类
ERR_OK = "OK"
ERR_SESSION_INVALID = "SESSION_INVALID"  # CONTEXT_TOKEN_INVALID / prepare failed
ERR_TRANSIENT = "TRANSIENT"
ERR_OTHER = "OTHER"


# ---------------------------------------------------------------------------
# 通道健康状态 + pending 队列 + 异步投递 worker
# ---------------------------------------------------------------------------


@dataclass
class WechatChannelState:
    healthy: bool = True
    session_invalid: bool = False
    last_success_at: float | None = None
    last_failure_at: float | None = None
    consecutive_failures: int = 0
    session_invalid_since: float | None = None
    last_action_required_at: float | None = None
    last_session_invalid_log_at: float | None = None
    token_mtime_at_invalid: float | None = None


@dataclass
class PendingNotification:
    dedupe_key: str
    message: str
    code: str
    alert_type: str
    is_fill: bool = False
    enqueued_at: float = field(default_factory=time.time)
    summary: str = ""


_channel_state = WechatChannelState()
_pending: OrderedDict[str, PendingNotification] = OrderedDict()
_pending_lock = threading.RLock()
_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()
_worker_wake = threading.Event()
_storm_last: dict[str, float] = {}  # (code|alert_type) -> last enqueue/send attempt


def get_wechat_channel_state() -> dict[str, Any]:
    """只读健康快照（测试/诊断）。"""
    with _pending_lock:
        st = _channel_state
        return {
            "healthy": st.healthy,
            "session_invalid": st.session_invalid,
            "last_success_at": st.last_success_at,
            "last_failure_at": st.last_failure_at,
            "consecutive_failures": st.consecutive_failures,
            "session_invalid_since": st.session_invalid_since,
            "pending_notification_count": len(_pending),
            "last_wechat_success_at": st.last_success_at,
            "last_wechat_failure_at": st.last_failure_at,
            "wechat_session_invalid_since": st.session_invalid_since,
        }


def _wechat_log(msg: str) -> None:
    _safe_print(f"[{_now()}] [WECHAT] {msg}")


def _mark_send_success() -> None:
    st = _channel_state
    st.healthy = True
    st.session_invalid = False
    st.last_success_at = time.time()
    st.consecutive_failures = 0
    st.session_invalid_since = None
    st.token_mtime_at_invalid = None


def _mark_session_invalid(*, detail: str = "") -> None:
    st = _channel_state
    now = time.time()
    was = st.session_invalid
    st.healthy = False
    st.session_invalid = True
    st.last_failure_at = now
    st.consecutive_failures = int(st.consecutive_failures or 0) + 1
    if st.session_invalid_since is None:
        st.session_invalid_since = now
    if st.token_mtime_at_invalid is None:
        st.token_mtime_at_invalid = _context_token_mtime()
    # 避免每秒刷屏
    if not was or (
        st.last_session_invalid_log_at is None
        or (now - st.last_session_invalid_log_at) >= 60.0
    ):
        st.last_session_invalid_log_at = now
        _wechat_log("prepare failed -> session invalid")
        _wechat_log("pause outbound delivery")
        _wechat_log("waiting for inbound session refresh")
        if detail:
            _wechat_log(f"detail: {detail[:160]}")


def _mark_transient_failure() -> None:
    st = _channel_state
    st.last_failure_at = time.time()
    st.consecutive_failures = int(st.consecutive_failures or 0) + 1


def _maybe_action_required(cfg: dict[str, Any]) -> None:
    st = _channel_state
    if not st.session_invalid or st.session_invalid_since is None:
        return
    threshold = float(cfg.get("session_action_log_sec") or 300)
    elapsed = time.time() - float(st.session_invalid_since)
    if elapsed < threshold:
        return
    now = time.time()
    if st.last_action_required_at and (now - st.last_action_required_at) < threshold:
        return
    st.last_action_required_at = now
    pending_n = 0
    with _pending_lock:
        pending_n = len(_pending)
    _safe_print(
        f"[{_now()}] [WECHAT][ACTION REQUIRED]\n"
        f"微信会话仍未恢复（已 {elapsed/60:.1f} 分钟，pending={pending_n}），"
        f"请给机器人发送任意消息以刷新会话。\n"
        f"或: openclaw channels login --channel openclaw-weixin"
    )


def classify_send_error(detail: str | None) -> str:
    """解析 openclaw 输出：SESSION_INVALID / TRANSIENT / OTHER。"""
    d = (detail or "").lower()
    if not d:
        return ERR_OTHER
    if (
        "prepare failed" in d
        or "ret=-2" in d
        or "contexttoken missing" in d
        or ("context_token" in d and "missing" in d)
        or "context_token_invalid" in d
        or "session_invalid" in d
    ):
        return ERR_SESSION_INVALID
    if any(
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
            "econnrefused",
            "network",
        )
    ):
        return ERR_TRANSIENT
    return ERR_OTHER


def _is_prepare_failed(detail: str) -> bool:
    return classify_send_error(detail) == ERR_SESSION_INVALID


def _is_transient_send_error(detail: str) -> bool:
    return classify_send_error(detail) == ERR_TRANSIENT


def _context_token_path(*, config: dict[str, Any] | None = None) -> Path | None:
    cfg = config or load_config()
    account = str(cfg.get("account") or "").strip()
    if not account:
        return None
    return (
        Path.home()
        / ".openclaw"
        / "openclaw-weixin"
        / "accounts"
        / f"{account}.context-tokens.json"
    )


def _context_token_mtime(*, config: dict[str, Any] | None = None) -> float | None:
    path = _context_token_path(config=config)
    if path is None or not path.is_file():
        return None
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return None


def context_token_refreshed_since(
    baseline_mtime: float | None,
    *,
    config: dict[str, Any] | None = None,
) -> bool:
    """新 inbound 写入后文件 mtime 会前进；不读 token 内容。"""
    cur = _context_token_mtime(config=config)
    if cur is None:
        return False
    if baseline_mtime is None:
        # 原先没有文件、现在有了 → 视为刷新
        return True
    return cur > float(baseline_mtime) + 0.05


def _pending_max(cfg: dict[str, Any] | None = None) -> int:
    cfg = cfg or load_config()
    return max(10, min(200, int(cfg.get("pending_queue_max") or 80)))


def enqueue_notification(
    *,
    message: str,
    dedupe_key: str,
    code: str = "",
    alert_type: str = "",
    is_fill: bool = False,
    summary: str = "",
    config: dict[str, Any] | None = None,
    bypass_storm: bool = False,
) -> bool:
    """主线程只入队；同 (code, alert_type) 预警覆盖旧条；成交不因预警冷却被吞。

    返回 True=入队/更新，False=被短冷却跳过。
    bypass_storm=True：worker 失败回队 / flush 中断回队时使用，避免丢消息。
    """
    cfg = config or load_config()
    code_s = str(code or "").strip()
    typ = str(alert_type or "").strip() or ("fill" if is_fill else "alert")
    key = str(dedupe_key or f"{code_s}|{typ}")
    storm_key = f"{code_s}|{typ}"
    now = time.time()
    if not is_fill and not bypass_storm:
        cool = max(15, int(cfg.get("alert_storm_cooldown_sec") or 45))
        prev = float(_storm_last.get(storm_key) or 0)
        # 已在 pending 则允许覆盖；未 pending 且冷却期内则跳过
        with _pending_lock:
            in_pending = key in _pending or any(
                (not p.is_fill) and p.code == code_s and p.alert_type == typ
                for p in _pending.values()
            )
        if not in_pending and prev and (now - prev) < cool:
            return False
    _storm_last[storm_key] = now

    item = PendingNotification(
        dedupe_key=key,
        message=str(message),
        code=code_s,
        alert_type=typ,
        is_fill=bool(is_fill),
        summary=summary or f"{code_s} {typ}".strip(),
    )
    with _pending_lock:
        if key in _pending:
            _pending.pop(key, None)
        # 预警：同 code+type 只留最新（即使 dedupe_key 略不同）
        if not is_fill and code_s and typ:
            drop = [
                k
                for k, p in _pending.items()
                if (not p.is_fill) and p.code == code_s and p.alert_type == typ
            ]
            for k in drop:
                _pending.pop(k, None)
        _pending[key] = item
        # 限长：优先丢最旧非成交
        cap = _pending_max(cfg)
        while len(_pending) > cap:
            victim = None
            for k, p in _pending.items():
                if not p.is_fill:
                    victim = k
                    break
            if victim is None:
                victim = next(iter(_pending))
            _pending.pop(victim, None)
    _worker_wake.set()
    return True


def _pop_next_pending() -> PendingNotification | None:
    with _pending_lock:
        if not _pending:
            return None
        # 成交优先
        for k, p in list(_pending.items()):
            if p.is_fill:
                _pending.pop(k)
                return p
        k, p = next(iter(_pending.items()))
        _pending.pop(k)
        return p


def _peek_pending_count() -> int:
    with _pending_lock:
        return len(_pending)


def recover_wechat_session(
    *,
    config: dict[str, Any] | None = None,
    wait_sec: float | None = None,
    probe_message: str | None = None,
    send_fn: Callable[..., tuple[bool, str]] | None = None,
) -> tuple[bool, str]:
    """通用会话恢复：等 inbound 刷新 context_token 文件 mtime，再探测发送一次。

    不靠无限发送测试消息判断；盘中 worker 与启动自检共用。
    send_fn 默认走底层单次发送（跳过队列），避免递归入队。
    """
    cfg = config or load_config()
    wait = float(cfg.get("wait_inbound_sec") if wait_sec is None else wait_sec)
    if wait <= 0:
        return False, "wait_inbound_sec=0，跳过会话恢复等待"
    poll = max(
        0.5,
        float(cfg.get("recover_poll_sec") or cfg.get("wait_inbound_poll_sec") or 8),
    )
    # 单次等待窗口内至少能探测几次
    if wait > 0:
        poll = min(poll, max(0.5, wait / 3.0))
    baseline = _channel_state.token_mtime_at_invalid
    if baseline is None:
        baseline = _context_token_mtime(config=cfg)
        _channel_state.token_mtime_at_invalid = baseline

    if not _channel_state.session_invalid:
        _mark_session_invalid(detail="recover_wechat_session")

    _wechat_log("waiting for inbound session refresh")
    _safe_print(
        f"[{_now()}] 请用微信给【盯盘机器人】发任意一条消息以刷新 context_token。\n"
        f"  最多等待 {wait:.0f}s；超时后仍可继续盯盘，恢复后自动补发 pending。\n"
        f"  若长时间无反应: openclaw channels login --channel openclaw-weixin"
    )

    deadline = time.time() + wait
    last = ""
    probe = probe_message or (
        "【盯盘·会话探测】\n通道恢复探测（不走大模型）\n" f"时间: {_now()}"
    )
    sender = send_fn or _send_text_direct

    while time.time() < deadline:
        if _worker_stop.is_set():
            return False, "worker stopped"
        _maybe_action_required(cfg)
        time.sleep(poll)
        if not context_token_refreshed_since(baseline, config=cfg):
            continue
        _wechat_log("session refreshed")
        ok, last = sender(probe, config=cfg, retries=1)
        if ok:
            _mark_send_success()
            _wechat_log("delivery recovered")
            return True, last
        if classify_send_error(last) == ERR_SESSION_INVALID:
            # 文件动了但仍 prepare failed：更新 baseline 继续等下一次 inbound
            baseline = _context_token_mtime(config=cfg)
            _channel_state.token_mtime_at_invalid = baseline
            _mark_session_invalid(detail=last)
            continue
        # 瞬时错误：再试一次后退出本轮 recover（留待下次）
        if classify_send_error(last) == ERR_TRANSIENT:
            ok2, last2 = sender(probe, config=cfg, retries=2)
            if ok2:
                _mark_send_success()
                _wechat_log("delivery recovered")
                return True, last2
            last = last2
        break
    return False, last or "等待入站刷新超时"


def _flush_pending_queue(
    *,
    config: dict[str, Any] | None = None,
    send_fn: Callable[..., tuple[bool, str]] | None = None,
) -> int:
    """成功恢复后逐步补发；再次 prepare failed 则停。返回成功条数。"""
    cfg = config or load_config()
    gap = float(cfg.get("flush_interval_sec") or 1.2)
    sender = send_fn or _send_text_direct
    n = _peek_pending_count()
    if n <= 0:
        return 0
    _wechat_log(f"flushing {n} pending notifications")
    sent_n = 0
    while True:
        item = _pop_next_pending()
        if item is None:
            break
        ok, detail = sender(item.message, config=cfg, retries=1)
        if ok:
            sent_n += 1
            _mark_send_success()
            _wechat_log(f"send success ({item.summary})")
            time.sleep(max(0.5, gap))
            continue
        kind = classify_send_error(detail)
        if kind == ERR_SESSION_INVALID:
            # 放回队列头部语义：重新入队
            enqueue_notification(
                message=item.message,
                dedupe_key=item.dedupe_key,
                code=item.code,
                alert_type=item.alert_type,
                is_fill=item.is_fill,
                summary=item.summary,
                config=cfg,
                bypass_storm=True,
            )
            _mark_session_invalid(detail=detail)
            _wechat_log("prepare failed during flush -> session invalid")
            break
        if kind == ERR_TRANSIENT:
            ok2, detail2 = sender(item.message, config=cfg, retries=2)
            if ok2:
                sent_n += 1
                _mark_send_success()
                time.sleep(max(0.5, gap))
                continue
            enqueue_notification(
                message=item.message,
                dedupe_key=item.dedupe_key,
                code=item.code,
                alert_type=item.alert_type,
                is_fill=item.is_fill,
                summary=item.summary,
                config=cfg,
                bypass_storm=True,
            )
            _wechat_log(f"flush deferred ({item.summary}): {(detail2 or '')[:120]}")
            break
        _wechat_log(f"flush drop other error ({item.summary}): {(detail or '')[:120]}")
    return sent_n


def _send_text_direct(
    message: str,
    *,
    config: dict[str, Any] | None = None,
    retries: int | None = None,
) -> tuple[bool, str]:
    """底层发送（可重试瞬时错误；SESSION_INVALID 立即返回不空转）。"""
    cfg = config or load_config()
    n = int(cfg.get("send_retries") if retries is None else retries)
    n = max(1, n)
    backoff = float(cfg.get("send_retry_backoff_sec") or 2.0)
    last = ""
    with _SEND_LOCK:
        for i in range(n):
            ok, detail = _send_text_once(message, cfg=cfg)
            if ok:
                _mark_send_success()
                return True, detail
            last = detail
            kind = classify_send_error(detail)
            if kind == ERR_SESSION_INVALID:
                _mark_session_invalid(detail=detail)
                return False, detail
            if kind != ERR_TRANSIENT or i >= n - 1:
                _mark_transient_failure()
                break
            wait = backoff * (2**i)
            _wechat_log(f"transient failure, retry {i + 1}/{n}")
            time.sleep(wait)
    return False, last


def _delivery_worker_main() -> None:
    """独立线程：发送 / 会话恢复 / flush；绝不反向影响交易。"""
    _wechat_log("delivery worker started")
    while not _worker_stop.is_set():
        try:
            cfg = load_config()
            if not watch_wechat_enabled(config=cfg):
                _worker_wake.wait(2.0)
                _worker_wake.clear()
                continue

            if _channel_state.session_invalid:
                _maybe_action_required(cfg)
                ok, _detail = recover_wechat_session(config=cfg, wait_sec=float(cfg.get("wait_inbound_sec") or 180))
                if ok:
                    _flush_pending_queue(config=cfg)
                else:
                    # 短歇后再进 recover，避免 CPU 空转；ACTION REQUIRED 已限频
                    _worker_wake.wait(float(cfg.get("recover_poll_sec") or 8))
                    _worker_wake.clear()
                continue

            item = _pop_next_pending()
            if item is None:
                _worker_wake.wait(1.0)
                _worker_wake.clear()
                continue

            ok, detail = _send_text_direct(item.message, config=cfg)
            if ok:
                _wechat_log(f"send success ({item.summary})")
                gap = float(cfg.get("flush_interval_sec") or 1.2)
                time.sleep(max(0.3, min(gap, 2.0)))
                continue

            kind = classify_send_error(detail)
            # 失败：放回队列（预警按 key 去重）
            enqueue_notification(
                message=item.message,
                dedupe_key=item.dedupe_key,
                code=item.code,
                alert_type=item.alert_type,
                is_fill=item.is_fill,
                summary=item.summary,
                config=cfg,
                bypass_storm=True,
            )
            if kind == ERR_SESSION_INVALID:
                continue  # 下一轮进 recover
            # 瞬时/其它：稍后再试
            time.sleep(float(cfg.get("send_retry_backoff_sec") or 2.0))
        except Exception as e:  # noqa: BLE001
            _wechat_log(f"worker error (ignored): {e}")
            time.sleep(2.0)
    _wechat_log("delivery worker stopped")


def start_wechat_delivery_worker() -> None:
    """盯盘启动后调用；幂等。"""
    global _worker_thread
    if _WATCH_WECHAT_ENABLED is False:
        return
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(
        target=_delivery_worker_main,
        name="wechat-delivery",
        daemon=True,
    )
    _worker_thread.start()


def stop_wechat_delivery_worker(*, join_timeout: float = 2.0) -> None:
    global _worker_thread
    _worker_stop.set()
    _worker_wake.set()
    t = _worker_thread
    if t is not None and t.is_alive():
        t.join(timeout=join_timeout)
    _worker_thread = None


def reset_wechat_delivery_state_for_tests() -> None:
    """单测重置。"""
    stop_wechat_delivery_worker(join_timeout=1.0)
    with _pending_lock:
        _pending.clear()
    _storm_last.clear()
    global _channel_state
    _channel_state = WechatChannelState()
    _worker_stop.clear()
    _worker_wake.clear()


def set_watch_wechat_enabled(enabled: bool | None) -> None:
    """watch 进程运行时开关。False 时预警与成交微信都不发，不影响 execution。"""
    global _WATCH_WECHAT_ENABLED
    _WATCH_WECHAT_ENABLED = enabled
    if enabled is False:
        stop_wechat_delivery_worker()


def set_async_delivery(enabled: bool) -> None:
    """测试/复盘可关异步：notify_* 同步走 send_text。"""
    global _ASYNC_DELIVERY
    _ASYNC_DELIVERY = bool(enabled)


def watch_wechat_enabled(*, config: dict[str, Any] | None = None) -> bool:
    """是否允许发出微信。--no-wechat 优先于 json enabled。"""
    if _WATCH_WECHAT_ENABLED is False:
        return False
    cfg = config or load_config()
    return bool(cfg.get("enabled", True))


# 预警优先级：P0=因子已触发；P1=触发预警带（内部去重键；对外文案统一【策略预警】）
PRIORITY_P0 = "P0"  # 因子已触发
PRIORITY_P1 = "P1"  # 触发预警带
KIND_P0 = "因子已触发"
KIND_P1 = "触发预警带"
KIND_ALERT = "策略预警"


def _strategy_label() -> str:
    try:
        from watch_config import STRATEGY_ID

        return str(STRATEGY_ID or "strategy16")
    except Exception:  # noqa: BLE001
        return "strategy16"


def map_fill_reason_code(
    *,
    exit_kind: str = "",
    reason: str = "",
    action_kind: str = "",
) -> str:
    """只映射执行路径已有字段，不重跑 DecisionEngine。"""
    ek = str(exit_kind or "").strip().lower()
    if ek in ("open_protect",):
        return "OPEN_PROTECT"
    if ek in ("path",):
        return "PATH"
    if ek in ("last", "working_stop"):
        return "WORKING_STOP"
    if ek in ("eod_reserve",):
        return "EOD_RESERVE"
    reason_s = str(reason or "")
    if "尾盘空槽" in reason_s or reason_s == "尾盘空槽":
        return "EOD_RESERVE"
    if str(action_kind or "").lower() == "half" or "半仓" in reason_s:
        return "HALF"
    if ek:
        return ek.upper()
    return ""


def in_default_strategy_alert_scope(code: str) -> bool:
    """扫描预警只覆盖默认策略池（strategy16），不含 strategy1 overlay。"""
    try:
        from watch_config import is_default_strategy_pool_code

        return bool(is_default_strategy_pool_code(str(code or "")))
    except Exception:  # noqa: BLE001
        return False


def filter_default_strategy_alert_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """微信扫描名单：只留默认策略池代码。不改变 collect_rows universe。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("代码") or "")
        if code and in_default_strategy_alert_scope(code):
            out.append(row)
    return out

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
    # 盘中会话恢复 / 队列
    "pending_queue_max": 80,
    "alert_storm_cooldown_sec": 45,  # 同 (code, alert_type) 短冷却；成交不受此限
    "session_action_log_sec": 300,  # session invalid 持续超过此秒只打一次 ACTION REQUIRED
    "flush_interval_sec": 1.2,
    "recover_poll_sec": 8.0,
    # 启动时 openclaw channels login（交互扫码，会阻塞终端）
    # login_on_start=true：每次启动都跑（不推荐，除非你愿意每次扫码）
    # login_on_channel_fail=true：仅通道未就绪 / 自检 prepare failed 时跑
    "login_on_start": False,
    "login_on_channel_fail": True,
    "login_timeout_sec": 300,
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
        "今日平仓",
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


def _qty(row: dict[str, Any]) -> int:
    try:
        return int(row.get("持仓") or 0)
    except (TypeError, ValueError):
        return 0


def is_t1_block_alert(row: dict[str, Any]) -> bool:
    """卖出条件已展示触发，但 T+1 没有真实 SELL。"""
    alert = str(row.get("预警") or "")
    if "T+1" not in alert:
        return False
    hit_stop = str(row.get("已触止损") or "") == "是"
    return bool(
        hit_stop
        or "止损已记" in alert
        or "已触止损" in alert
        or "暂不可卖" in alert
    )


def is_filled_slot_buy_row(row: dict[str, Any]) -> bool:
    """已实际入槽的 BUY：扫描不得再发已触买。"""
    alert = str(row.get("预警") or "")
    if _qty(row) <= 0:
        return False
    if bool(row.get("槽位占用")):
        return True
    return "已入槽" in alert


def is_realized_exit_row(row: dict[str, Any]) -> bool:
    """已有真实 SELL/PARTIAL fill 的行：扫描不得再发同一成交语义。"""
    if not row.get("已实现"):
        return False
    alert = str(row.get("预警") or "")
    hit_stop = str(row.get("已触止损") or "") == "是"
    hit = str(row.get("因子触发") or "")
    rebuy = (
        is_buy_hit(row)
        or str(row.get("持仓状态") or "") == "待买入"
        or "再触买" in alert
        or "可再买" in alert
        or "将买入" in alert
    )
    if rebuy and not (
        hit_stop or "半仓" in alert or "止盈" in alert or "止损" in alert
    ):
        return False
    return bool(
        hit_stop
        or "半仓" in alert
        or "止盈" in alert
        or "止损" in alert
        or str(hit).startswith("策略止损")
        or str(hit).startswith("半仓")
    )


def classify_stock_alert(row: dict[str, Any]) -> dict[str, Any] | None:
    """扫描层只分类【策略预警】（未成交信号）。已成交 BUY/SELL 返回 None。"""
    if row.get("error"):
        return None
    pos = str(row.get("持仓状态") or "")
    alert = str(row.get("预警") or "")
    hit = str(row.get("因子触发") or "")
    no_buy = bool(row.get("当日禁买")) or pos == "当日禁买"
    holding = _has_holding(row)

    hit_buy = is_buy_hit(row)
    hit_stop = str(row.get("已触止损") or "") == "是"
    near_buy = bool(row.get("近买点"))
    near_stop = bool(row.get("近止损"))
    half_or_tp = (
        "半仓" in alert
        or alert.startswith("将半仓")
        or "止盈" in alert
        or hit.startswith("半仓")
        or "止盈" in hit
    )

    def _pack(level: str, typ: str, status: str, factor_px: Any) -> dict[str, Any]:
        return {
            "level": level,
            "kind": KIND_ALERT,
            "type": typ,
            "status": status,
            "factor_px": factor_px,
        }

    if is_t1_block_alert(row):
        return _pack(
            PRIORITY_P0,
            "T1_BLOCK",
            "卖出条件已触发，但 T+1 暂不可卖",
            _factor_px_for_push(row, holding=True),
        )

    if "不可卖" in alert and (
        hit_stop or "跌停" in alert or "封单" in alert
    ):
        return _pack(
            PRIORITY_P0,
            "跌停不可卖",
            "卖出条件已触发，但跌停封单暂不可卖",
            _factor_px_for_push(row, holding=True),
        )

    # 已实际成交：扫描静默（成交微信由 notify_trade_fill 负责）
    if is_filled_slot_buy_row(row):
        hit_buy = False
    if is_realized_exit_row(row):
        if not (
            hit_buy
            or pos == "待买入"
            or "再触买" in alert
            or "可再买" in alert
            or "将买入" in alert
        ):
            # 半仓成交后若只剩「将止损」预警，允许继续扫
            if near_stop or "将止损" in alert or "将半仓" in alert:
                pass
            else:
                return None

    if holding:
        if half_or_tp and row.get("已实现") and "将半仓" not in alert:
            # 半仓 fill 已发【模拟卖出】；剩余仓的将止损仍可预警
            if near_stop or "将止损" in alert:
                return _pack(
                    PRIORITY_P1,
                    "将止损",
                    "将止损",
                    _factor_px_for_push(row, holding=True),
                )
            return None
        if half_or_tp and "将半仓" in alert:
            return _pack(
                PRIORITY_P1,
                "将半仓",
                "将半仓",
                row.get("卖出价")
                or row.get("止损")
                or _factor_px_for_push(row, holding=True),
            )
        if half_or_tp and not row.get("已实现"):
            return _pack(
                PRIORITY_P0,
                "半仓止盈",
                "半仓止盈已触发但尚未成交",
                row.get("卖出价")
                or row.get("止损")
                or _factor_px_for_push(row, holding=True),
            )
        if (
            hit_buy
            or ("已触买" in alert and not is_filled_slot_buy_row(row))
            or (pos == "待买入" and hit.startswith("已触发"))
        ):
            return _pack(
                PRIORITY_P0,
                "已触买",
                "已触买但尚未实际成交",
                row.get("买入侧价")
                or row.get("买点")
                or _factor_px_for_push(row, holding=False),
            )
        if (
            (hit_stop or hit.startswith("策略止损") or "已触止损" in alert
             or (pos == "待卖出" and hit.startswith("已触发")))
            and not row.get("已实现")
        ):
            return _pack(
                PRIORITY_P0,
                "已触止损",
                "卖出条件已触发但尚未成交",
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
                "将止损",
                "将止损",
                _factor_px_for_push(row, holding=True),
            )
        return None

    if no_buy:
        return None
    if is_weak_price_buy_alert(row) or ALERT_PRICE_NO_GATE in alert:
        return None
    if (
        hit_buy
        or (pos == "待买入" and hit.startswith("已触发"))
        or "已触买" in alert
        or "再触买" in alert
        or "收盘动量可再买" in alert
    ):
        if "已入槽" in alert:
            return None
        if "槽满" in alert:
            return _pack(
                PRIORITY_P0,
                "已触买·槽满",
                "槽满",
                _factor_px_for_push(row, holding=False),
            )
        status = "已触买但尚未实际成交"
        typ = "已触买·未入槽" if "未入槽" in alert else "已触买"
        return _pack(
            PRIORITY_P0,
            typ,
            status,
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
            "将买入",
            "将买入",
            _factor_px_for_push(row, holding=False),
        )
    return None


def is_alert_row(row: dict[str, Any]) -> bool:
    """扫描层可推送的【策略预警】行。因子2走账户级通道。"""
    return classify_stock_alert(row) is not None


def _alert_key(row: dict[str, Any]) -> str:
    code = str(row.get("代码") or "")
    info = classify_stock_alert(row) or {}
    return (
        f"{code}|alert|{info.get('type')}|{info.get('status')}|"
        f"{row.get('已触买')}|{row.get('已触止损')}|"
        f"{int(bool(row.get('近买点')))}|{int(bool(row.get('近止损')))}"
    )


def format_alert_message(row: dict[str, Any]) -> str:
    info = classify_stock_alert(row)
    code = row.get("代码") or "-"
    name = row.get("名称") or "-"
    digits = int(row.get("价位小数") or 2)

    def _n(v: Any) -> str:
        if v is None or v == "":
            return "-"
        try:
            return f"{float(v):.{digits}f}"
        except (TypeError, ValueError):
            return str(v)

    status = str((info or {}).get("status") or (info or {}).get("type") or "预警")
    extra = ""
    if info and str(info.get("type") or "") == "T1_BLOCK":
        extra = "\n原因：T1_BLOCK"
    return "\n".join(
        [
            "【策略预警】",
            f"股票：{code} {name}",
            f"状态：{status}{extra}",
            f"当前价：{_n(row.get('现价'))}",
            f"策略：{_strategy_label()}",
            f"时间：{_now()}",
        ]
    )


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

    · TRANSIENT：指数退避重试
    · SESSION_INVALID（prepare failed / ret=-2）：立即返回，不空转重试
    """
    return _send_text_direct(message, config=config, retries=retries)


def format_buy_fill_message(
    *,
    code: str,
    name: str,
    price: float,
    qty: int,
    strategy_id: str = "",
) -> str:
    return "\n".join(
        [
            "【模拟买入】",
            f"股票：{code} {name}",
            f"成交价：{float(price):.2f}",
            f"买入数量：{int(qty)}",
            f"策略：{strategy_id or _strategy_label()}",
            f"时间：{_now()}",
        ]
    )


def format_sell_fill_message(
    *,
    code: str,
    name: str,
    price: float,
    qty: int,
    action_kind: str = "",
    reason_code: str = "",
    before_qty: int | None = None,
    after_qty: int | None = None,
    quantity_ratio: float | None = None,
) -> str:
    half = str(action_kind or "").lower() == "half" or (
        quantity_ratio is not None and float(quantity_ratio) < 1.0 - 1e-12
    )
    fill_kind = "半仓" if half else "全仓"
    lines = [
        "【模拟卖出】",
        f"股票：{code} {name}",
        f"成交价：{float(price):.2f}",
        f"卖出数量：{int(qty)}",
        f"成交类型：{fill_kind}",
    ]
    if reason_code:
        lines.append(f"原因：{reason_code}")
    if before_qty is not None and after_qty is not None:
        lines.append(f"仓位：{int(before_qty)} → {int(after_qty)}")
    elif after_qty is not None:
        lines.append(f"成交后持仓：{int(after_qty)}")
    if quantity_ratio is not None:
        lines.append(f"quantity_ratio：{float(quantity_ratio):.4f}")
    lines.append(f"时间：{_now()}")
    return "\n".join(lines)


def notify_trade_fill(
    *,
    side: str,
    code: str,
    name: str,
    price: float,
    qty: int,
    reason: str = "",
    pnl: float | None = None,
    pnl_pct: float | None = None,
    after_qty: int | None = None,
    before_qty: int | None = None,
    action_kind: str = "",
    exit_kind: str = "",
    reason_code: str = "",
    quantity_ratio: float | None = None,
    strategy_id: str = "",
    config: dict[str, Any] | None = None,
) -> bool:
    """买卖成交即时推送。只应在 paper mutation + ledger 成功后调用。

    异步模式下只入队（不阻塞交易）；同步模式（单测）直接 send_text。
    成交不受预警短冷却吞没。
    """
    cfg = config or load_config()
    if not watch_wechat_enabled(config=cfg):
        return False
    side_l = str(side or "").strip().lower()
    if side_l in ("买", "买入"):
        side_l = "buy"
    elif side_l in ("卖", "卖出", "stop"):
        side_l = "sell"
    code_s = str(code or "").strip()
    name_s = str(name or code_s)
    mapped = str(reason_code or "").strip() or map_fill_reason_code(
        exit_kind=exit_kind,
        reason=reason,
        action_kind=action_kind,
    )
    ratio = quantity_ratio
    if ratio is None and before_qty:
        try:
            ratio = float(qty) / float(before_qty) if float(before_qty) > 0 else None
        except (TypeError, ValueError):
            ratio = None
    if side_l == "buy":
        msg = format_buy_fill_message(
            code=code_s,
            name=name_s,
            price=float(price),
            qty=int(qty),
            strategy_id=strategy_id,
        )
        typ = "模拟买入"
    else:
        msg = format_sell_fill_message(
            code=code_s,
            name=name_s,
            price=float(price),
            qty=int(qty),
            action_kind=action_kind,
            reason_code=mapped,
            before_qty=before_qty,
            after_qty=after_qty,
            quantity_ratio=ratio,
        )
        typ = "模拟卖出"
    # 成交唯一键：含时刻分钟，避免同秒重复；不同成交不互相覆盖
    key = (
        f"fill|{code_s}|{side_l}|{typ}|{mapped}|"
        f"{int(price * 100)}|{int(qty)}|{_now()[:16]}"
    )
    state = _load_state()
    sent: dict[str, Any] = state.setdefault("sent", {})
    now_ts = time.time()
    prev = float(sent.get(key) or 0)
    if (now_ts - prev) < 30:
        return False

    summary = f"{name_s}({code_s}) {typ}"
    if _ASYNC_DELIVERY:
        enqueue_notification(
            message=msg,
            dedupe_key=key,
            code=code_s,
            alert_type=typ,
            is_fill=True,
            summary=summary,
            config=cfg,
        )
        # 乐观记防抖键，避免成交风暴；真实发送由 worker 负责
        sent[key] = now_ts
        state["sent"] = sent
        state["updated_at"] = _now()
        _save_state(state)
        start_wechat_delivery_worker()
        return True

    ok, detail = send_text(msg, config=cfg)
    if ok:
        sent[key] = now_ts
        state["sent"] = sent
        state["updated_at"] = _now()
        _save_state(state)
        print(f"[{_now()}] 微信已推送成交: {name_s}({code_s}) {typ}")
        return True
    if classify_send_error(detail) == ERR_SESSION_INVALID:
        enqueue_notification(
            message=msg,
            dedupe_key=key,
            code=code_s,
            alert_type=typ,
            is_fill=True,
            summary=summary,
            config=cfg,
        )
        start_wechat_delivery_worker()
    print(f"[{_now()}] 微信成交推送失败 {name_s}({code_s}): {(detail or '')[:200]}")
    return False


def notify_watch_rows(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """扫描盯盘行，对新增/变更预警做防抖推送。返回已受理摘要（异步=已入队）。"""
    cfg = config or load_config()
    if not force and not watch_wechat_enabled(config=cfg):
        return []

    cooldown = max(60, int(cfg.get("cooldown_sec") or 1800))
    state = _load_state()
    sent: dict[str, Any] = state.setdefault("sent", {})
    now_ts = time.time()
    active_keys: set[str] = set()
    pushed: list[str] = []

    def _dispatch(msg: str, *, key: str, code: str, name: str, alert_type: str) -> bool:
        summary = f"{name}({code}) {alert_type}"
        if _ASYNC_DELIVERY:
            ok_q = enqueue_notification(
                message=msg,
                dedupe_key=key,
                code=code,
                alert_type=alert_type,
                is_fill=False,
                summary=summary,
                config=cfg,
            )
            if ok_q:
                # 成功入队即记防抖，避免 session invalid 时每轮狂入队
                # （队列内同 key 仍会覆盖为最新文案）
                sent[key] = now_ts
                pushed.append(f"{name}({code})")
                start_wechat_delivery_worker()
            return ok_q
        ok, detail = send_text(msg, config=cfg)
        if ok:
            sent[key] = now_ts
            pushed.append(f"{name}({code})")
            print(
                f"[{_now()}] 微信已推送: {name}({code}) {alert_type}"
            )
            return True
        if classify_send_error(detail) == ERR_SESSION_INVALID:
            enqueue_notification(
                message=msg,
                dedupe_key=key,
                code=code,
                alert_type=alert_type,
                is_fill=False,
                summary=summary,
                config=cfg,
            )
            start_wechat_delivery_worker()
            # session invalid：也记短防抖，避免主循环同步风暴
            sent[key] = now_ts
            pushed.append(f"{name}({code})")
            return False
        print(f"[{_now()}] 微信推送失败 {name}({code}): {(detail or '')[:200]}")
        return False

    for row in rows:
        if row.get("error"):
            continue
        info = classify_stock_alert(row)
        if info is None:
            continue
        key = _alert_key(row)
        active_keys.add(key)
        prev_ts = float(sent.get(key) or 0)
        if not force and (now_ts - prev_ts) < cooldown:
            # 冷却期内：若已在 pending，仍允许覆盖为最新文案；否则跳过
            with _pending_lock:
                in_q = key in _pending or any(
                    (not p.is_fill)
                    and p.code == str(row.get("代码") or "")
                    and p.alert_type == str(info.get("type") or "")
                    for p in _pending.values()
                )
            if not in_q:
                continue
        msg = format_alert_message(row)
        code = str(row.get("代码") or "")
        name = str(row.get("名称") or "")
        typ = str(info.get("type") or "策略预警")
        _dispatch(msg, key=key, code=code, name=name, alert_type=typ)

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
            _dispatch(
                msg,
                key=f2_key,
                code="factor2",
                name="因子2",
                alert_type=f2_act,
            )

    for k in list(sent.keys()):
        if k.startswith("fill|"):
            continue
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
    path = _context_token_path(config=cfg)
    if path is None or not path.is_file():
        return False, "无会话文件（需先给机器人发一条微信）"
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
    return True, f"本地会话 token 存在（age={age_h:.1f}h, mtime={path.stat().st_mtime:.0f})"


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
    """启动自检兼容入口：委托 recover_wechat_session。"""
    return recover_wechat_session(
        config=config,
        probe_message=message,
        send_fn=_send_text_direct,
    )


def run_weixin_channels_login(
    *,
    config: dict[str, Any] | None = None,
    timeout_sec: float | None = None,
) -> tuple[bool, str]:
    """交互式执行 ``openclaw channels login --channel openclaw-weixin``。

    必须继承 stdin/stdout（二维码/确认），故不 capture。
    已登录时多数版本会很快返回；未登录则终端内完成扫码。
    """
    cfg = config or load_config()
    channel = str(cfg.get("channel") or "openclaw-weixin")
    to = float(
        cfg.get("login_timeout_sec") if timeout_sec is None else timeout_sec
    )
    to = max(60.0, to)
    openclaw_bin = str(cfg.get("openclaw_bin") or "openclaw")
    env = _env_with_node(cfg)
    exe, prefix = _resolve_openclaw_node(openclaw_bin, env)
    cli = [*prefix, "channels", "login", "--channel", channel] if prefix else [
        "channels",
        "login",
        "--channel",
        channel,
    ]
    cmd = [exe, *cli] if prefix else [openclaw_bin, *cli]
    print(
        f"[{_now()}] [WECHAT] 运行: openclaw channels login --channel {channel}\n"
        f"  （交互扫码/确认；完成后回到本流程。超时 {to:.0f}s）"
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=False,  # 必须给二维码留终端
            text=True,
            timeout=to,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return False, "找不到 openclaw/node，无法 channels login"
    except subprocess.TimeoutExpired:
        return False, f"channels login 超时（>{to:.0f}s）"
    if int(proc.returncode) == 0:
        print(f"[{_now()}] [WECHAT] channels login 完成")
        return True, "ok"
    return False, f"channels login exit={proc.returncode}"


def prepare_wechat_for_watch(
    *,
    config: dict[str, Any] | None = None,
    send_test: bool = True,
    restart_gateway: bool = False,
    force_login: bool = False,
) -> tuple[bool, str]:
    """盯盘启动套件：补丁 → Gateway →（可选 login）→ 通道就绪 → 微信自检。

    返回 (ok, detail)。失败时 detail 含原因，供调用方决定是否中止。

    force_login / 配置 login_on_start：启动即跑 ``channels login``（交互）。
    login_on_channel_fail：仅通道未就绪或 prepare failed 时再 login。
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

    do_login_start = bool(force_login) or bool(cfg.get("login_on_start"))
    if do_login_start:
        print(f"[{_now()}] [1b/3] 启动前执行 channels login…")
        lok, ldetail = run_weixin_channels_login(config=cfg)
        if not lok:
            print(f"[{_now()}] channels login 未成功: {ldetail[:200]}（继续探测通道）")

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
        if not ch_ok and bool(cfg.get("login_on_channel_fail", True)):
            print(f"[{_now()}] 通道仍未就绪，尝试 channels login…")
            lok, ldetail = run_weixin_channels_login(config=cfg)
            if lok:
                time.sleep(max(settle, 3.0))
                ch_ok, ch_detail = wait_weixin_channel_ready(config=cfg, timeout_sec=40)
            else:
                print(f"[{_now()}] channels login 失败: {ldetail[:200]}")
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
        start_wechat_delivery_worker()
        return True, detail2

    if _is_prepare_failed(detail2):
        # 磁盘 token 过期：login（可选）+ 等人发消息；同时 gateway restart
        if "disk-fallback" not in patch_info and "patched" not in patch_info.lower():
            print(f"[{_now()}] 补丁可能未生效，gateway restart 后再试…")
        else:
            print(f"[{_now()}] prepare failed：gateway restart 后重试一次…")
        ensure_openclaw_gateway(config=cfg, restart=True)
        time.sleep(max(settle, 3.0))
        wait_weixin_channel_ready(config=cfg, timeout_sec=30)
        if bool(cfg.get("login_on_channel_fail", True)):
            print(f"[{_now()}] prepare failed：尝试 channels login 刷新通道账号…")
            run_weixin_channels_login(config=cfg)
            time.sleep(max(settle, 2.0))
        ok3, detail3 = send_test_alert(config=cfg)
        if ok3:
            print(f"[{_now()}] 微信通道自检成功（重启/login 后）")
            start_wechat_delivery_worker()
            return True, detail3
        detail2 = detail3
        print(
            f"[{_now()}] 提示：channels login 解决的是通道账号；"
            f"prepare failed 还常需你给机器人发一条消息刷新 context_token。"
        )
        ok4, detail4 = wait_inbound_and_retry_send(
            (
                "【盯盘预警·测试】\n"
                "通道自检成功：OpenClaw 微信推送可用（不走大模型）。\n"
                f"时间: {_now()}"
            ),
            config=cfg,
        )
        if ok4:
            start_wechat_delivery_worker()
            return True, detail4
        detail2 = detail4
        # 自检失败也启动 worker：盘中 inbound 刷新后可自动恢复并补发
        start_wechat_delivery_worker()

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
