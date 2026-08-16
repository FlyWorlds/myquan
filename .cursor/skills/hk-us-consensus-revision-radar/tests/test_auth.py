import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.auth_session import (
    AuthenticationError,
    CredentialError,
    Credentials,
    SessionGrant,
    adopt_authenticated_session,
    authenticate,
    normalize_username,
    read_credentials,
    resolve_credentials,
)


class FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeAuthManager:
    def __init__(self, artifact_path: Path):
        self.artifact_path = artifact_path
        self._auth_lock = FakeLock()
        self._auth_state = SimpleNamespace(
            token=None,
            username=None,
            base_url=None,
            login_timestamp=0.0,
            token_expires_in_seconds=0,
        )
        self.clear_calls = 0

    def save_auth_state(self, username, password, base_url, token, expires_in=14400):
        self.artifact_path.write_text(f"{username}:{password}:{token}", encoding="utf-8")

    def clear_auth(self):
        self.clear_calls += 1
        self._auth_state.token = None


class FakePandaData:
    def __init__(self, artifact_path: Path):
        self.auth_manager = FakeAuthManager(artifact_path)
        self.login_calls = []

    def init_token(self, username, password):
        self.login_calls.append((username, password))
        self.auth_manager.save_auth_state(
            username=username,
            password=password,
            base_url="http://pandadata.example",
            token="private-token",
            expires_in=3600,
        )
        return "private-token"


class RejectingPandaData(FakePandaData):
    def init_token(self, username, password):
        self.login_calls.append((username, password))
        raise RuntimeError("HTTP 401: credential rejected for local-secret")


class TokenOnlyPandaData(FakePandaData):
    BASE_URL = "http://pandadata.example"

    def init_token(self, username, password):
        self.login_calls.append((username, password))
        return "private-token"


class AuthenticationTests(unittest.TestCase):
    def test_normalizes_only_plain_eleven_digit_mobile_username(self):
        mobile = "1" * 11
        self.assertEqual(normalize_username(f"  {mobile}  "), "86" + mobile)
        self.assertEqual(normalize_username("86" + mobile), "86" + mobile)
        self.assertEqual(normalize_username("research-user"), "research-user")
        self.assertEqual(normalize_username("１" * 11), "１" * 11)

    def test_normalizes_mainland_mobile_username(self):
        mobile = "1" * 11
        self.assertEqual(normalize_username(mobile), "86" + mobile)

    def test_preserves_prefixed_mobile_and_named_account(self):
        prefixed = "86" + "1" * 11
        self.assertEqual(normalize_username(prefixed), prefixed)
        self.assertEqual(normalize_username("research-user"), "research-user")

    def test_requires_both_environment_variables(self):
        with self.assertRaisesRegex(CredentialError, "PANDADATA_PASSWORD"):
            read_credentials({"PANDADATA_USERNAME": "1" * 11})

    def test_reads_and_normalizes_environment_credentials(self):
        credentials = read_credentials(
            {
                "PANDADATA_USERNAME": "1" * 11,
                "PANDADATA_PASSWORD": "example-only",
            }
        )
        self.assertEqual(credentials.username, "86" + "1" * 11)
        self.assertEqual(credentials.password, "example-only")

    def test_prompts_locally_when_environment_credentials_are_missing(self):
        prompts = []

        credentials = resolve_credentials(
            {},
            interactive=True,
            username_reader=lambda prompt: prompts.append(prompt) or "1" * 11,
            password_reader=lambda prompt: prompts.append(prompt) or "local-secret",
        )

        self.assertEqual(credentials.username, "86" + "1" * 11)
        self.assertEqual(credentials.password, "local-secret")
        self.assertEqual(prompts, ["PandaData Username: ", "PandaData Password: "])

    def test_local_input_announces_authentication_after_password(self):
        status_messages = []

        resolve_credentials(
            {},
            interactive=True,
            username_reader=lambda _prompt: "research-user",
            password_reader=lambda _prompt: "local-secret",
            status_writer=status_messages.append,
        )

        self.assertEqual(status_messages, ["账号和密码已接收，正在登录 PandaData..."])

    def test_environment_credentials_do_not_trigger_prompts(self):
        def unexpected_prompt(prompt):
            self.fail(f"unexpected prompt: {prompt}")

        credentials = resolve_credentials(
            {
                "PANDADATA_USERNAME": "research-user",
                "PANDADATA_PASSWORD": "environment-secret",
            },
            interactive=True,
            username_reader=unexpected_prompt,
            password_reader=unexpected_prompt,
        )

        self.assertEqual(credentials.username, "research-user")
        self.assertEqual(credentials.password, "environment-secret")

    def test_noninteractive_missing_credentials_fail_without_prompt(self):
        def unexpected_prompt(prompt):
            self.fail(f"unexpected prompt: {prompt}")

        with self.assertRaisesRegex(CredentialError, "PANDADATA_PASSWORD"):
            resolve_credentials(
                {"PANDADATA_USERNAME": "research-user"},
                interactive=False,
                username_reader=unexpected_prompt,
                password_reader=unexpected_prompt,
            )

    def test_cancelled_local_input_has_safe_error(self):
        def cancel(_prompt):
            raise EOFError("terminal closed")

        with self.assertRaises(CredentialError) as caught:
            resolve_credentials(
                {"PANDADATA_USERNAME": "research-user"},
                interactive=True,
                password_reader=cancel,
            )

        self.assertIn("cancelled", str(caught.exception).lower())
        self.assertNotIn("terminal closed", str(caught.exception))

    def test_authentication_is_memory_only_and_restores_sdk_hook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "user.json"
            panda = FakePandaData(artifact)
            original_save = panda.auth_manager.save_auth_state
            credentials = read_credentials(
                {
                    "PANDADATA_USERNAME": "1" * 11,
                    "PANDADATA_PASSWORD": "example-only",
                }
            )

            session = authenticate(panda, credentials)

            self.assertFalse(artifact.exists())
            self.assertEqual(
                session.grant,
                SessionGrant(
                    access_token="private-token",
                    username="86" + "1" * 11,
                    base_url="http://pandadata.example",
                    expires_in_seconds=3600,
                ),
            )
            self.assertEqual(panda.login_calls, [("86" + "1" * 11, "example-only")])
            self.assertIs(panda.auth_manager.save_auth_state.__func__, original_save.__func__)
            self.assertEqual(panda.auth_manager._auth_state.token, "private-token")
            session.close()
            self.assertEqual(panda.auth_manager.clear_calls, 1)
            self.assertIsNone(panda.auth_manager._auth_state.token)

    def test_adopting_session_grant_initializes_client_without_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "user.json"
            panda = FakePandaData(artifact)
            client = SimpleNamespace(init=lambda **kwargs: setattr(client, "kwargs", kwargs))
            grant = SessionGrant(
                access_token="short-lived-token",
                username="research-user",
                base_url="http://pandadata.example",
                expires_in_seconds=3600,
            )

            with patch("scripts.auth_session.importlib.import_module", return_value=client):
                session = adopt_authenticated_session(panda, grant)

            self.assertEqual(panda.login_calls, [])
            self.assertFalse(artifact.exists())
            self.assertEqual(panda.auth_manager._auth_state.token, "short-lived-token")
            self.assertEqual(
                client.kwargs,
                {
                    "username": "research-user",
                    "password": "",
                    "base_url": "http://pandadata.example",
                },
            )
            session.close()

    def test_authentication_failure_exposes_safe_http_category_without_secret(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            panda = RejectingPandaData(Path(temp_dir) / "user.json")

            with self.assertRaises(AuthenticationError) as caught:
                authenticate(panda, Credentials("research-user", "local-secret"))

        message = str(caught.exception)
        self.assertIn("HTTP 401", message)
        self.assertIn("服务端拒绝", message)
        self.assertNotIn("local-secret", message)

    def test_authentication_uses_sdk_defaults_when_token_state_metadata_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            panda = TokenOnlyPandaData(Path(temp_dir) / "user.json")

            session = authenticate(panda, Credentials("research-user", "local-secret"))

        self.assertEqual(session.grant.access_token, "private-token")
        self.assertEqual(session.grant.base_url, "http://pandadata.example")
        self.assertEqual(session.grant.expires_in_seconds, 14400)


if __name__ == "__main__":
    unittest.main()
