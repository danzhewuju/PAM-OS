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
