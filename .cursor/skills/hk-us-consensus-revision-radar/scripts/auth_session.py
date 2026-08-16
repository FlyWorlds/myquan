"""Environment-only PandaData authentication with process-memory token state."""

from __future__ import annotations

import getpass
import importlib
import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping


class CredentialError(ValueError):
    """Raised when required PandaData environment variables are unavailable."""


class AuthenticationError(RuntimeError):
    """Raised when PandaData rejects authentication."""

    def __str__(self) -> str:
        if self.__cause__ is not None:
            return _safe_login_failure_message(self.__cause__)
        return super().__str__()


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


@dataclass(frozen=True)
class SessionGrant:
    """A short-lived PandaData session transferred only in process memory."""

    access_token: str
    username: str
    base_url: str
    expires_in_seconds: int


@dataclass
class AuthSession:
    _auth_manager: object
    grant: SessionGrant
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        clear_auth = getattr(self._auth_manager, "clear_auth", None)
        if callable(clear_auth):
            clear_auth()
        self._closed = True

    def __enter__(self) -> "AuthSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


def normalize_username(value: str) -> str:
    username = value.strip()
    if len(username) == 11 and username.isascii() and username.isdigit():
        return f"86{username}"
    return username


def read_credentials(env: Mapping[str, str]) -> Credentials:
    username = normalize_username(env.get("PANDADATA_USERNAME", ""))
    password = env.get("PANDADATA_PASSWORD", "")
    missing = []
    if not username:
        missing.append("PANDADATA_USERNAME")
    if not password:
        missing.append("PANDADATA_PASSWORD")
    if missing:
        raise CredentialError("Missing PandaData credentials: " + ", ".join(missing))
    return Credentials(username=username, password=password)



def resolve_credentials(
    env: Mapping[str, str],
    *,
    interactive: bool,
    username_reader: Callable[[str], str] = input,
    password_reader: Callable[[str], str] = getpass.getpass,
    status_writer: Callable[[str], None] | None = None,
) -> Credentials:
    """Resolve credentials from the process environment or a local terminal."""
    values = {
        "PANDADATA_USERNAME": env.get("PANDADATA_USERNAME", ""),
        "PANDADATA_PASSWORD": env.get("PANDADATA_PASSWORD", ""),
    }
    if values["PANDADATA_USERNAME"] and values["PANDADATA_PASSWORD"]:
        return read_credentials(values)
    if not interactive:
        return read_credentials(values)
    prompted = False
    try:
        if not values["PANDADATA_USERNAME"]:
            values["PANDADATA_USERNAME"] = username_reader("PandaData Username: ")
            prompted = True
        if not values["PANDADATA_PASSWORD"]:
            values["PANDADATA_PASSWORD"] = password_reader("PandaData Password: ")
            prompted = True
    except (EOFError, KeyboardInterrupt) as exc:
        raise CredentialError("PandaData credential input cancelled") from exc
    credentials = read_credentials(values)
    if prompted and status_writer is not None:
        status_writer("账号和密码已接收，正在登录 PandaData...")
    return credentials


def _resolve_auth_manager(panda_module):
    manager = getattr(panda_module, "auth_manager", None)
    if manager is not None:
        return manager
    return importlib.import_module("panda_data.auth_manager")


def _memory_save_factory(auth_manager):
    def save_auth_state(username, password, base_url, token, expires_in=14400):
        del password
        lock = auth_manager._auth_lock
        state = auth_manager._auth_state
        with lock:
            state.token = token
            state.username = username
            state.base_url = base_url
            state.login_timestamp = time.time()
            state.token_expires_in_seconds = expires_in

    return save_auth_state


def _safe_login_failure_message(exc: BaseException) -> str:
    """Classify login failures without exposing credentials or tokens."""
    detail = str(exc)
    http_status = re.search(r"\bHTTP\s+(\d{3})\b", detail, flags=re.IGNORECASE)
    if http_status:
        return (
            "PandaData 登录失败：服务端拒绝请求"
            f"（HTTP {http_status.group(1)}）。请核对账号、密码与账户状态后重试。"
        )
    if re.search(r"timeout|timed out|network error|urlerror", detail, flags=re.IGNORECASE):
        return "PandaData 登录失败：网络连接或登录超时。请确认服务可用后重试。"
    return "PandaData 登录失败：服务端未返回可用登录结果。请稍后重试。"


def authenticate(panda_module, credentials: Credentials) -> AuthSession:
    auth_manager = _resolve_auth_manager(panda_module)
    original_save = auth_manager.save_auth_state
    auth_manager.save_auth_state = _memory_save_factory(auth_manager)
    try:
        access_token = panda_module.init_token(
            username=credentials.username,
            password=credentials.password,
        )
    except Exception as exc:
        clear_auth = getattr(auth_manager, "clear_auth", None)
        if callable(clear_auth):
            clear_auth()
        raise AuthenticationError("PandaData 登录失败") from exc
    finally:
        auth_manager.save_auth_state = original_save
    state = auth_manager._auth_state
    grant = SessionGrant(
        access_token=str(access_token or getattr(state, "token", "")),
        username=str(getattr(state, "username", "") or credentials.username),
        base_url=str(
            getattr(state, "base_url", "") or getattr(panda_module, "BASE_URL", "")
        ),
        expires_in_seconds=int(
            getattr(state, "token_expires_in_seconds", 0) or 14400
        ),
    )
    if not grant.access_token or not grant.base_url or grant.expires_in_seconds <= 0:
        clear_auth = getattr(auth_manager, "clear_auth", None)
        if callable(clear_auth):
            clear_auth()
        raise AuthenticationError("PandaData 登录未返回可复用会话")
    return AuthSession(auth_manager, grant)


def adopt_authenticated_session(panda_module, grant: SessionGrant) -> AuthSession:
    """Initialize this process from a verified in-memory session grant."""
    if (
        not grant.access_token
        or not grant.username
        or not grant.base_url
        or grant.expires_in_seconds <= 0
    ):
        raise AuthenticationError("PandaData 会话信息无效")

    auth_manager = _resolve_auth_manager(panda_module)
    try:
        lock = auth_manager._auth_lock
        state = auth_manager._auth_state
        with lock:
            state.token = grant.access_token
            state.username = grant.username
            state.base_url = grant.base_url
            state.login_timestamp = time.time()
            state.token_expires_in_seconds = grant.expires_in_seconds
        client_module = importlib.import_module("panda_data.client")
        client_module.init(
            username=grant.username,
            password="",
            base_url=grant.base_url,
        )
    except Exception as exc:
        clear_auth = getattr(auth_manager, "clear_auth", None)
        if callable(clear_auth):
            clear_auth()
        raise AuthenticationError("PandaData 会话初始化失败") from exc
    return AuthSession(auth_manager, grant)
