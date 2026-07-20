from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
CLIENT_SOURCE = ROOT / "skills" / "pam-os-memory" / "scripts" / "pam_client.py"
POWERSHELL_LAUNCHER = CLIENT_SOURCE.with_suffix(".ps1")
BASH_LAUNCHER = CLIENT_SOURCE.with_suffix(".sh")
PLUGIN_CLIENT = (
    ROOT
    / "plugins"
    / "pam-os-memory"
    / "skills"
    / "pam-os-memory"
    / "scripts"
    / "pam_client.py"
)
TEST_TOKEN = "pam_test_token_that_must_never_be_printed"


@contextmanager
def _server(*, status: int = 200, response: dict | None = None):
    state: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            state["authorization"] = self.headers.get("Authorization", "")
            state["path"] = self.path
            if status != 200:
                body = json.dumps(
                    {"error": "denied", "token": TEST_TOKEN}
                ).encode()
                self.send_response(status)
            else:
                body = json.dumps(
                    response
                    or {
                        "version": "0.5.1",
                        "api_version": "v2",
                        "echo": TEST_TOKEN,
                        "username": "private-user",
                    }
                ).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _handle  # noqa: N815
        do_POST = _handle  # noqa: N815

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _installed_client(tmp_path: Path, url: str, *, token: str = TEST_TOKEN) -> Path:
    skill_dir = tmp_path / "pam-os-memory"
    scripts = skill_dir / "scripts"
    shutil.copytree(CLIENT_SOURCE.parent, scripts)
    client = scripts / "pam_client.py"
    (skill_dir / "config.toml").write_text(
        "\n".join(
            (
                "[versions]",
                'skill = "0.5.1"',
                'api = "v2"',
                "",
                "[rest]",
                f'url = "{url}"',
                f'token = "{token}"',
                "timeout_seconds = 3",
                "",
            )
        ),
        encoding="utf-8",
    )
    return client


def _run(client: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(client), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_packaged_clients_are_identical():
    for source in (CLIENT_SOURCE, POWERSHELL_LAUNCHER, BASH_LAUNCHER):
        plugin_file = PLUGIN_CLIENT.parent / source.name
        assert plugin_file.read_bytes() == source.read_bytes()


def test_powershell_launcher_finds_runtime_without_exposing_token(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        return
    with _server() as (url, state):
        client = _installed_client(tmp_path, url)
        result = subprocess.run(
            [powershell, "-NoProfile", "-File", str(client.with_suffix(".ps1")), "check"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert result.returncode == 0, result.stderr
    assert state["authorization"] == f"Bearer {TEST_TOKEN}"
    assert TEST_TOKEN not in result.stdout + result.stderr


def test_bash_launcher_finds_runtime_without_exposing_token(tmp_path):
    if sys.platform == "win32":
        candidates = (
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
        )
        bash = next((str(candidate) for candidate in candidates if candidate.is_file()), None)
    else:
        bash = shutil.which("bash")
    if bash is None:
        return
    with _server() as (url, state):
        client = _installed_client(tmp_path, url)
        launcher = client.with_suffix(".sh")
        result = subprocess.run(
            [bash, launcher.as_posix(), "check"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert result.returncode == 0, result.stderr
    assert state["authorization"] == f"Bearer {TEST_TOKEN}"
    assert TEST_TOKEN not in result.stdout + result.stderr


def test_check_keeps_credentials_out_of_output_and_sends_auth(tmp_path):
    with _server() as (url, state):
        client = _installed_client(tmp_path, url)
        result = _run(client, "check")

    assert result.returncode == 0, result.stderr
    assert state["authorization"] == f"Bearer {TEST_TOKEN}"
    assert TEST_TOKEN not in result.stdout
    assert TEST_TOKEN not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "match"
    assert set(payload) == {
        "ok",
        "status",
        "skill_version",
        "skill_api",
        "server_version",
        "server_api",
    }


def test_request_redacts_credentials_and_sensitive_response_fields(tmp_path):
    with _server() as (url, _state):
        client = _installed_client(tmp_path, url)
        result = _run(client, "request", "GET", "/v2/meta")

    assert result.returncode == 0, result.stderr
    assert TEST_TOKEN not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["echo"] == "[REDACTED]"
    assert payload["username"] == "[REDACTED]"


def test_http_error_does_not_echo_server_body_or_credentials(tmp_path):
    with _server(status=401) as (url, _state):
        client = _installed_client(tmp_path, url)
        result = _run(client, "request", "GET", "/v2/meta")

    assert result.returncode == 2
    assert "HTTP 401" in result.stderr
    assert TEST_TOKEN not in result.stdout + result.stderr
    assert "denied" not in result.stdout + result.stderr


def test_client_rejects_remote_plaintext_http_before_connecting(tmp_path):
    client = _installed_client(tmp_path, "http://memory.example.test:8765")
    result = _run(client, "check")

    assert result.returncode == 2
    assert "requires HTTPS" in result.stderr
    assert TEST_TOKEN not in result.stdout + result.stderr


def test_client_rejects_absolute_and_unknown_routes(tmp_path):
    client = _installed_client(tmp_path, "http://127.0.0.1:9")

    absolute = _run(client, "request", "GET", "https://attacker.test/v2/meta")
    unknown = _run(client, "request", "GET", "/v2/admin/users")

    assert absolute.returncode == 2
    assert "relative API path" in absolute.stderr
    assert unknown.returncode == 2
    assert "route is not allowed" in unknown.stderr
    assert TEST_TOKEN not in absolute.stderr + unknown.stderr


def test_memory_clear_requires_explicit_destructive_flag(tmp_path):
    client = _installed_client(tmp_path, "http://127.0.0.1:9")
    result = _run(
        client,
        "request",
        "POST",
        "/v2/memory/clear",
        "--body-json",
        '{"confirm":true}',
    )

    assert result.returncode == 2
    assert "requires --allow-destructive" in result.stderr
    assert TEST_TOKEN not in result.stdout + result.stderr
