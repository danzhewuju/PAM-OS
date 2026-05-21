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


def test_clear_memory_rest_api_requires_confirmation(tmp_path):
    app = create_app(db_path=tmp_path / "memory.sqlite3")
    route = next(route for route in app.routes if getattr(route, "path", None) == "/memory/clear")
    request = type("ClearRequest", (), {"confirm": False})()

    with pytest.raises(Exception) as exc:
        route.endpoint(request)

    assert "400" in str(exc.value)


def test_clear_memory_rest_api_clears_storage(tmp_path):
    app = create_app(db_path=tmp_path / "memory.sqlite3")
    capture_route = next(route for route in app.routes if getattr(route, "path", None) == "/memory/capture")
    clear_route = next(route for route in app.routes if getattr(route, "path", None) == "/memory/clear")
    capture_request = type(
        "CaptureRequest",
        (),
        {
            "content": "我偏好 self-host、开源、可控系统。",
            "source": "conversation",
            "source_ref": None,
            "metadata": {},
            "force": True,
        },
    )()
    clear_request = type("ClearRequest", (), {"confirm": True})()

    capture_route.endpoint(capture_request)
    payload = clear_route.endpoint(clear_request)

    assert payload["deleted_counts"]["events"] == 1
    assert payload["deleted_counts"]["memories"] >= 1
    assert payload["storage_stats"]["tables"]["events"]["count"] == 0
    assert payload["storage_stats"]["tables"]["memories"]["count"] == 0


def test_inspect_memory_rest_api_returns_requested_table(tmp_path):
    app = create_app(db_path=tmp_path / "memory.sqlite3")
    capture_route = next(route for route in app.routes if getattr(route, "path", None) == "/memory/capture")
    inspect_route = next(route for route in app.routes if getattr(route, "path", None) == "/memory/inspect")
    capture_request = type(
        "CaptureRequest",
        (),
        {
            "content": "我偏好 self-host、开源、可控系统。",
            "source": "conversation",
            "source_ref": None,
            "metadata": {},
            "force": True,
        },
    )()

    capture_route.endpoint(capture_request)
    payload = inspect_route.endpoint(table="memories", limit=10, q="self-host")

    assert set(payload["details"]) == {"memories"}
    assert payload["stats"]["tables"]["memories"]["count"] >= 1
    assert payload["details"]["memories"]


def test_inspect_memory_rest_api_rejects_unknown_table(tmp_path):
    app = create_app(db_path=tmp_path / "memory.sqlite3")
    inspect_route = next(route for route in app.routes if getattr(route, "path", None) == "/memory/inspect")

    with pytest.raises(Exception) as exc:
        inspect_route.endpoint(table="secrets", limit=20, q=None)

    assert "400" in str(exc.value)
