from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = ROOT / "plugins" / "pam-os-memory"
PROJECT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
EXISTING_URL = "https://memory.example.test:9443"
EXISTING_TOKEN = 'pam_existing\\secret"key'
EXISTING_TIMEOUT = 27


def _rest_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "PAM_OS_REST_URL",
        "PAM_OS_REST_TOKEN",
        "PAM_OS_REST_TIMEOUT_SECONDS",
    ):
        env.pop(name, None)
    return env


def _write_existing_config(skill_dir: Path, *, rest_url: str = EXISTING_URL) -> None:
    def toml_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    skill_dir.mkdir(parents=True)
    (skill_dir / "config.toml").write_text(
        "\n".join(
            (
                "# Existing PAM-OS REST client configuration.",
                "",
                "[rest]",
                f'url = "{rest_url}"',
                f'token = "{toml_string(EXISTING_TOKEN)}"',
                f"timeout_seconds = {EXISTING_TIMEOUT}",
                "",
            )
        ),
        encoding="utf-8",
    )


def _installer_args(
    tmp_path: Path,
    *,
    rest_url: str = EXISTING_URL,
    skip_version_check: bool = True,
) -> tuple[list[str], Path]:
    skill_dir = tmp_path / "claude-skill"
    _write_existing_config(skill_dir, rest_url=rest_url)
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
    if skip_version_check:
        args.append("--skip-version-check")
    return args, skill_dir / "config.toml"


def _assert_reused_config(result: subprocess.CompletedProcess[str], config_path: Path) -> None:
    def toml_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Found existing REST config" in output
    assert "Mode: update" in output
    assert f"Previous REST URL: {EXISTING_URL}" in output
    assert "Previous REST token: configured" in output
    assert EXISTING_TOKEN not in output

    installed = config_path.read_text(encoding="utf-8-sig")
    assert f'url = "{EXISTING_URL}"' in installed
    assert f'token = "{toml_string(EXISTING_TOKEN)}"' in installed
    assert f"timeout_seconds = {EXISTING_TIMEOUT}" in installed
    config = tomllib.loads(installed)
    assert config["versions"] == {
        "skill": PROJECT_VERSION,
        "api": "v2",
        "server": "",
        "server_api": "",
        "server_checked_at": "",
        "status": "not_checked",
    }


@contextmanager
def _legacy_version_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler API
            if self.path == "/v2/meta":
                self.send_response(404)
                self.end_headers()
                return
            if self.path == "/openapi.json":
                payload = {
                    "info": {"title": "Personal Memory Runtime", "version": "0.3.2"},
                    "paths": {"/context/prepare": {}, "/turns/observe": {}, "/memory/capture": {}},
                }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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
        [bash, str(ROOT / "scripts" / "install.sh"), *shell_args],
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
        [powershell, "-NoProfile", "-File", str(ROOT / "scripts" / "install.ps1"), *args],
        cwd=ROOT,
        env=_rest_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    _assert_reused_config(result, config_path)


def test_powershell_installer_uses_repo_skill_without_source(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")
    skill_dir = tmp_path / "claude-skill"
    _write_existing_config(skill_dir)
    args = [
        "--claude",
        "--yes",
        "--repo-dir",
        str(ROOT),
        "--claude-skill-dir",
        str(skill_dir),
        "--no-refresh",
        "--skip-version-check",
    ]
    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(ROOT / "scripts" / "install.ps1"), *args],
        cwd=ROOT,
        env=_rest_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    _assert_reused_config(result, skill_dir / "config.toml")


def test_bash_installer_records_legacy_server_version_mismatch(tmp_path: Path) -> None:
    bash = _find_bash()
    if bash is None:
        pytest.skip("bash is not available")

    with _legacy_version_server() as rest_url:
        args, config_path = _installer_args(tmp_path, rest_url=rest_url, skip_version_check=False)
        result = subprocess.run(
            [bash, str(ROOT / "scripts" / "install.sh"), *args],
            cwd=ROOT,
            env=_rest_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"Version mismatch: skill {PROJECT_VERSION} / API v2; server 0.3.2 / API unversioned" in output
    config = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    assert config["versions"]["skill"] == PROJECT_VERSION
    assert config["versions"]["server"] == "0.3.2"
    assert config["versions"]["server_api"] == "unversioned"
    assert config["versions"]["status"] == "mismatch"
    assert config["versions"]["server_checked_at"].endswith("Z")


def test_bash_installer_auto_detects_existing_target_on_rerun(tmp_path: Path) -> None:
    bash = _find_bash()
    if bash is None:
        pytest.skip("bash is not available")

    claude_skill = tmp_path / "claude-skill"
    _write_existing_config(claude_skill)
    args = [
        "--repo-dir",
        str(ROOT),
        "--source",
        str(PLUGIN_SOURCE),
        "--plugin-dir",
        str(tmp_path / "plugin"),
        "--marketplace",
        str(tmp_path / "marketplace.json"),
        "--codex-skill-dir",
        str(tmp_path / "codex-skill"),
        "--claude-skill-dir",
        str(claude_skill),
        "--opencode-agents",
        str(tmp_path / "opencode-AGENTS.md"),
        "--hermes-agents",
        str(tmp_path / "hermes-AGENTS.md"),
        "--hermes-skill-dir",
        str(tmp_path / "hermes-skill"),
        "--no-refresh",
        "--skip-version-check",
    ]
    result = subprocess.run(
        [bash, str(ROOT / "scripts" / "install.sh"), *args],
        cwd=ROOT,
        env=_rest_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Detected an existing PAM-OS integration; updating all installed targets." in output
    assert "Mode: update" in output
    assert (claude_skill / "SKILL.md").is_file()
    assert not (tmp_path / "plugin").exists()


def test_bash_installer_detects_first_install_and_defaults_to_codex(tmp_path: Path) -> None:
    bash = _find_bash()
    if bash is None:
        pytest.skip("bash is not available")

    args = [
        "--yes",
        "--repo-dir",
        str(ROOT),
        "--source",
        str(PLUGIN_SOURCE),
        "--plugin-dir",
        str(tmp_path / "plugin"),
        "--marketplace",
        str(tmp_path / "marketplace.json"),
        "--codex-config",
        str(tmp_path / "codex-config.toml"),
        "--codex-skill-dir",
        str(tmp_path / "codex-skill"),
        "--claude-skill-dir",
        str(tmp_path / "claude-skill"),
        "--opencode-agents",
        str(tmp_path / "opencode-AGENTS.md"),
        "--hermes-agents",
        str(tmp_path / "hermes-AGENTS.md"),
        "--hermes-skill-dir",
        str(tmp_path / "hermes-skill"),
        "--rest-url",
        "http://127.0.0.1:8765",
        "--no-refresh",
        "--skip-version-check",
    ]
    result = subprocess.run(
        [bash, str(ROOT / "scripts" / "install.sh"), *args],
        cwd=ROOT,
        env=_rest_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Mode: install" in output
    assert (tmp_path / "plugin" / ".codex-plugin" / "plugin.json").is_file()
    assert (tmp_path / "codex-skill" / "SKILL.md").is_file()
