"""Browser-initiated OpenClaw login; only public QR/status data leaves this module."""
from __future__ import annotations

import re
import subprocess
import threading
import time
from urllib.parse import urlparse

ACTIVE = {"starting", "waiting", "scanned"}


class WechatLogin:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = dict(status="idle", message="点击生成二维码，使用微信扫码连接。", loginUrl=None)
        self.process = None
        self.closed = False
        self.probing = False
        self.checked_at = 0.0
        self.channel_ready = None
        self.test_push = dict(status="idle", message="")

    def _view(self):
        return dict(self.state, channelReady=self.channel_ready, testPush=dict(self.test_push))

    def status(self):
        with self.lock:
            if not self.closed and not self.probing and time.monotonic() - self.checked_at > 20:
                self.probing = True
                threading.Thread(target=self._probe, daemon=True).start()
            return self._view()

    def send_test(self):
        with self.lock:
            if self.closed:
                return self._view()
            if self.test_push["status"] != "sending":
                self.test_push = dict(status="sending", message="正在发送测试消息…")
                threading.Thread(target=self._send_test, daemon=True).start()
            return self._view()

    def _send_test(self):
        from wechat_notify import send_test_alert, classify_send_error, ERR_SESSION_INVALID
        try:
            ok, detail = send_test_alert()
            if ok:
                message = "测试消息已发送，请查看微信。"
            elif classify_send_error(detail) == ERR_SESSION_INVALID:
                message = "微信会话已失效，请先给机器人发一条消息，再重试测试推送。"
            elif "target" in str(detail) and "未配置" in str(detail):
                message = "尚未配置微信接收人，请先配置接收人后重试。"
            elif "weixin not configured" in str(detail):
                message = "推送账号未就绪，请重新扫码连接，并确认微信接收人配置。"
            else:
                message = "测试消息发送失败，请检查微信连接后重试。"
        except Exception as exc:
            print(f"[WECHAT TEST] {type(exc).__name__}", flush=True)
            ok, message = False, "测试消息发送失败，请稍后重试。"
        with self.lock:
            self.test_push = dict(status="sent" if ok else "error", message=message)

    def _probe(self):
        from wechat_notify import weixin_channel_ready
        try:
            ready, _ = weixin_channel_ready()
            with self.lock:
                self.channel_ready = ready
        except Exception:
            pass
        finally:
            with self.lock:
                self.checked_at = time.monotonic()
                self.probing = False

    def start(self):
        with self.lock:
            if self.closed:
                return dict(status="error", message="服务正在关闭，请稍后重试。", loginUrl=None)
            if self.state["status"] not in ACTIVE and self.process is None:
                self.state = dict(status="starting", message="正在生成微信二维码…", loginUrl=None)
                threading.Thread(target=self._run, daemon=True).start()
            return self._view()

    def _line(self, raw):
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw).strip()
        # Only consume explicit QR output, never forward CLI logs/tokens to the browser.
        candidate = line.split("二维码链接:", 1)[-1].strip() if "二维码链接:" in line else line
        parsed = urlparse(candidate)
        host = parsed.hostname or ""
        with self.lock:
            if (parsed.scheme == "https" and not parsed.username and not parsed.password
                    and (host.endswith(".qq.com") or host.endswith(".weixin.com")
                         or host.endswith(".wechat.com"))):
                self.state.update(status="waiting", message="请用微信扫一扫；扫码后在手机上确认连接。", loginUrl=candidate)
            elif "已扫码" in line:
                self.state.update(status="scanned", message="已扫码，请在微信中确认连接。")
            elif "二维码已过期" in line:
                self.state.update(status="starting", message="二维码已过期，正在刷新…", loginUrl=None)
            elif "与微信连接成功" in line:
                self.state.update(status="connected", message="微信已连接。请给机器人发一条消息，以便接收预警。", loginUrl=None)
                self.channel_ready = True

    def _run(self):
        from wechat_notify import load_config, _env_with_node, _resolve_openclaw_node
        timer = None
        proc = None
        timed_out = threading.Event()
        try:
            cfg = load_config()
            env = _env_with_node(cfg)
            exe, prefix = _resolve_openclaw_node(str(cfg.get("openclaw_bin") or "openclaw"), env)
            command = [exe, *prefix, "channels", "login", "--channel", str(cfg.get("channel") or "openclaw-weixin")]
            with self.lock:
                if self.closed:
                    return
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
                self.process = proc

            def expire():
                if proc.poll() is None:
                    timed_out.set()
                    proc.kill()

            timer = threading.Timer(480, expire)
            timer.daemon = True
            timer.start()
            for line in proc.stdout:
                self._line(line)
            proc.wait()
            with self.lock:
                if self.state["status"] != "connected":
                    print(f"[WECHAT LOGIN] 登录未完成 exit={proc.returncode} timeout={timed_out.is_set()}", flush=True)
                    self.state.update(status="error", loginUrl=None,
                        message="扫码已超时，请重新生成二维码。" if timed_out.is_set()
                        else "微信连接未完成，请重试；详细原因见服务日志。")
        except Exception as exc:
            # Avoid exposing subprocess output or authentication material.
            print(f"[WECHAT LOGIN] {type(exc).__name__}", flush=True)
            with self.lock:
                self.state.update(status="error", message="无法启动微信登录，请检查 OpenClaw 是否已安装。", loginUrl=None)
        finally:
            if timer:
                timer.cancel()
            if proc:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                if proc.stdout:
                    proc.stdout.close()
            with self.lock:
                if self.process is proc:
                    self.process = None

    def close(self):
        with self.lock:
            self.closed = True
            if self.process and self.process.poll() is None:
                self.process.kill()


login = WechatLogin()
