from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = ROOT / "plugins" / "pam-os-memory"
EXISTING_URL = "https://memory.example.test:9443"
EXISTING_USERNAME = 'existing"user\\name'
EXISTING_PASSWORD = 'existing\\secret"key'
EXISTING_TIMEOUT = 27


def _rest_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "PAM_OS_REST_URL",
        "PAM_OS_REST_USERNAME",
        "PAM_OS_REST_PASSWORD",
        "PAM_OS_REST_TIMEOUT_SECONDS",
    ):
        env.pop(name, None)
    return env


def _write_existing_config(skill_dir: Path) -> None:
    def toml_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    skill_dir.mkdir(parents=True)
    (skill_dir / "config.toml").write_text(
        "\n".join(
            (
                "# Existing PAM-OS REST client configuration.",
                "",
                "[rest]",
                f'url = "{EXISTING_URL}"',
                f'username = "{toml_string(EXISTING_USERNAME)}"',
                f'password = "{toml_string(EXISTING_PASSWORD)}"',
                f"timeout_seconds = {EXISTING_TIMEOUT}",
                "",
            )
        ),
        encoding="utf-8",
    )


def _installer_args(tmp_path: Path) -> tuple[list[str], Path]:
    skill_dir = tmp_path / "claude-skill"
    _write_existing_config(skill_dir)
    args = [
        "--claude",
        "--yes",
        "--repo-dir",
        str(ROOT),
        "--source",
        str(PLUGIN_SOURCE),
        "--claude-skill-dir",
        str(skill_dir),
        "--no-refresh",
    ]
    return args, skill_dir / "config.toml"


def _assert_reused_config(result: subprocess.CompletedProcess[str], config_path: Path) -> None:
    def toml_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Found existing REST config" in output
    assert f"Previous REST URL: {EXISTING_URL}" in output
    assert f"Previous REST username: {EXISTING_USERNAME}" in output
    assert "Previous REST password: configured" in output
    assert EXISTING_PASSWORD not in output

    installed = config_path.read_text(encoding="utf-8-sig")
    assert f'url = "{EXISTING_URL}"' in installed
    assert f'username = "{toml_string(EXISTING_USERNAME)}"' in installed
    assert f'password = "{toml_string(EXISTING_PASSWORD)}"' in installed
    assert f"timeout_seconds = {EXISTING_TIMEOUT}" in installed


def _find_bash() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    for candidate in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "bash.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _shell_path(path: Path) -> str:
    return path.as_posix()


def test_bash_installer_reuses_existing_rest_config(tmp_path: Path) -> None:
    bash = _find_bash()
    if bash is None:
        pytest.skip("bash is not available")
    args, config_path = _installer_args(tmp_path)
    shell_args = [_shell_path(Path(value)) if value.startswith(str(ROOT.drive)) else value for value in args]
    result = subprocess.run(
        [bash, str(ROOT / "scripts" / "install-plugin.sh"), *shell_args],
        cwd=ROOT,
        env=_rest_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    _assert_reused_config(result, config_path)


def test_powershell_installer_reuses_existing_rest_config(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")
    args, config_path = _installer_args(tmp_path)
    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(ROOT / "scripts" / "install-plugin.ps1"), *args],
        cwd=ROOT,
        env=_rest_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    _assert_reused_config(result, config_path)
