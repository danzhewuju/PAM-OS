from __future__ import annotations

import pytest

from pam_os.api import create_app
from pam_os.api import ensure_basic_auth
from pam_os.config import AppConfig, ServerConfig


class Credentials:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password


def test_basic_auth_helper_accepts_valid_credentials():
    ensure_basic_auth(Credentials("yuhao", "secret"), True, "yuhao", "secret")


def test_basic_auth_helper_rejects_missing_credentials():
    with pytest.raises(Exception) as exc:
        ensure_basic_auth(None, True, "yuhao", "secret")
    assert "401" in str(exc.value)


def test_basic_auth_helper_rejects_wrong_credentials():
    with pytest.raises(Exception) as exc:
        ensure_basic_auth(Credentials("yuhao", "wrong"), True, "yuhao", "secret")
    assert "401" in str(exc.value)


def test_rest_api_auth_enabled_requires_credentials():
    config = AppConfig(server=ServerConfig(auth_enabled=True))

    with pytest.raises(RuntimeError, match="auth_username or server.auth_password"):
        create_app(db_path=None, config=config)
