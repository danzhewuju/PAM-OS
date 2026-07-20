from __future__ import annotations

import pytest

from pam_os.config import load_config


def test_server_host_and_port_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("PAM_OS_HOST", "0.0.0.0")
    monkeypatch.setenv("PAM_OS_PORT", "9876")

    config = load_config(config_path="/tmp/pam-os-missing.toml")

    assert config.server.host == "0.0.0.0"
    assert config.server.port == 9876


def test_server_port_env_requires_integer(monkeypatch):
    monkeypatch.setenv("PAM_OS_PORT", "not-a-port")

    with pytest.raises(ValueError, match="PAM_OS_PORT must be an integer"):
        load_config(config_path="/tmp/pam-os-missing.toml")


def test_multi_user_storage_and_bootstrap_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("PAM_OS_DATA_DIR", "/tmp/pam-os-users")
    monkeypatch.setenv("PAM_OS_CONTROL_DB", "/tmp/pam-os-control.sqlite3")
    monkeypatch.setenv("PAM_OS_RUNTIME_CACHE_SIZE", "17")
    monkeypatch.setenv("PAM_OS_BOOTSTRAP_TOKEN", "bootstrap-secret")

    config = load_config(config_path="/tmp/pam-os-missing.toml")

    assert config.storage.data_dir == "/tmp/pam-os-users"
    assert config.storage.control_db_path == "/tmp/pam-os-control.sqlite3"
    assert config.storage.runtime_cache_size == 17
    assert config.server.bootstrap_token == "bootstrap-secret"
