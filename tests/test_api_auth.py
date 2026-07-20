from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from pam_os.api import create_app
from pam_os.config import AppConfig, ServerConfig
from pam_os.identity import DEFAULT_USER_SCOPES, MEMORY_READ


BOOTSTRAP_TOKEN = "test-bootstrap-token"


@pytest.fixture
def api(tmp_path: Path) -> tuple[TestClient, object, Path]:
    config = AppConfig(server=ServerConfig(bootstrap_token=BOOTSTRAP_TOKEN))
    app = create_app(config, data_root=tmp_path)
    return TestClient(app), app, tmp_path


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def provision_user(
    client: TestClient,
    username: str,
    *,
    scopes: list[str] | None = None,
) -> dict:
    payload = {"username": username}
    if scopes is not None:
        payload["scopes"] = scopes
    response = client.post(
        "/v2/admin/users",
        headers=bearer(BOOTSTRAP_TOKEN),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_live_is_public_but_product_routes_require_bearer(api):
    client, _app, _root = api

    assert client.get("/health/live").status_code == 200
    for path in ["/v2/meta", "/v2/me", "/v2/storage/stats", "/v2/profile"]:
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_bootstrap_credential_can_provision_user_but_cannot_read_memory(api):
    client, _app, _root = api

    provisioned = provision_user(client, "alice")

    assert provisioned["user"]["username"] == "alice"
    assert provisioned["api_key"]["token"].startswith("pam_")
    response = client.post(
        "/v2/memories/search",
        headers=bearer(BOOTSTRAP_TOKEN),
        json={"query": "anything"},
    )
    assert response.status_code == 403


def test_api_key_authentication_returns_fixed_identity(api):
    client, _app, _root = api
    provisioned = provision_user(client, "alice")
    token = provisioned["api_key"]["token"]

    response = client.get("/v2/me", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {
        "user_id": provisioned["user"]["id"],
        "username": "alice",
        "principal_id": provisioned["principal"]["id"],
        "api_key_id": provisioned["api_key"]["id"],
        "scopes": sorted(DEFAULT_USER_SCOPES),
        "bootstrap": False,
    }


def test_control_store_never_persists_plaintext_api_token(api):
    client, _app, root = api
    provisioned = provision_user(client, "alice")
    token = provisioned["api_key"]["token"]

    with sqlite3.connect(root / "control.sqlite3") as conn:
        row = conn.execute("SELECT secret_hash FROM api_keys").fetchone()
        database_bytes = (root / "control.sqlite3").read_bytes()

    assert row is not None
    assert row[0] != token
    assert token.encode() not in database_bytes


def test_two_users_are_isolated_across_capture_search_inspect_stats_and_clear(api):
    client, app, _root = api
    alice = provision_user(client, "alice")
    bob = provision_user(client, "bob")
    alice_headers = bearer(alice["api_key"]["token"])
    bob_headers = bearer(bob["api_key"]["token"])

    assert client.post(
        "/v2/memory/capture",
        headers=alice_headers,
        json={"content": "Alice prefers quiet engineering answers.", "force": True},
    ).status_code == 200
    assert client.post(
        "/v2/memory/capture",
        headers=bob_headers,
        json={"content": "Bob prefers concise product answers.", "force": True},
    ).status_code == 200

    alice_results = client.post(
        "/v2/memories/search", headers=alice_headers, json={"query": "Alice"}
    ).json()
    bob_results = client.post(
        "/v2/memories/search", headers=bob_headers, json={"query": "Alice"}
    ).json()
    alice_inspect = client.get(
        "/v2/memory/inspect", headers=alice_headers, params={"table": "memories", "q": "Alice"}
    ).json()
    bob_inspect = client.get(
        "/v2/memory/inspect", headers=bob_headers, params={"table": "memories", "q": "Alice"}
    ).json()

    assert alice_results
    assert bob_results == []
    assert alice_inspect["details"]["memories"]
    assert bob_inspect["details"]["memories"] == []
    alice_stats = client.get("/v2/storage/stats", headers=alice_headers).json()
    assert "db_path" not in alice_stats
    assert alice_stats["tables"]["events"]["count"] == 1
    assert client.get("/v2/storage/stats", headers=bob_headers).json()["tables"]["events"]["count"] == 1
    assert "db_path" not in alice_inspect["stats"]

    clear = client.post("/v2/memory/clear", headers=alice_headers, json={"confirm": True})
    assert clear.status_code == 200
    assert "db_path" not in clear.json()["storage_stats"]
    assert client.get("/v2/storage/stats", headers=alice_headers).json()["tables"]["events"]["count"] == 0
    assert client.get("/v2/storage/stats", headers=bob_headers).json()["tables"]["events"]["count"] == 1

    factory = app.state.runtime_factory
    alice_path = factory.db_path_for_user(alice["user"]["id"])
    bob_path = factory.db_path_for_user(bob["user"]["id"])
    assert alice_path != bob_path
    with sqlite3.connect(alice_path) as conn:
        assert conn.execute("SELECT value FROM store_metadata WHERE key = 'owner_user_id'").fetchone()[0] == alice["user"]["id"]
    with sqlite3.connect(bob_path) as conn:
        assert conn.execute("SELECT value FROM store_metadata WHERE key = 'owner_user_id'").fetchone()[0] == bob["user"]["id"]


def test_client_cannot_select_user_in_request_body_or_header(api):
    client, _app, _root = api
    alice = provision_user(client, "alice")
    bob = provision_user(client, "bob")

    response = client.post(
        "/v2/memory/capture",
        headers={**bearer(alice["api_key"]["token"]), "X-PAM-OS-User": bob["user"]["id"]},
        json={"content": "attempted impersonation", "force": True, "user_id": bob["user"]["id"]},
    )

    assert response.status_code == 422
    assert client.post(
        "/v2/memories/search",
        headers=bearer(bob["api_key"]["token"]),
        json={"query": "impersonation"},
    ).json() == []


def test_parallel_users_keep_separate_write_streams(api):
    client, app, _root = api
    alice = provision_user(client, "alice")
    bob = provision_user(client, "bob")
    work = [
        (alice["api_key"]["token"], "alice", index)
        for index in range(8)
    ] + [
        (bob["api_key"]["token"], "bob", index)
        for index in range(8)
    ]

    def capture(item):
        token, username, index = item
        with TestClient(app) as thread_client:
            return thread_client.post(
                "/v2/events",
                headers=bearer(token),
                json={"content": f"{username} event {index}", "extract": False},
            ).status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(capture, work))

    assert statuses == [200] * len(work)
    assert client.get(
        "/v2/storage/stats", headers=bearer(alice["api_key"]["token"])
    ).json()["tables"]["events"]["count"] == 8
    assert client.get(
        "/v2/storage/stats", headers=bearer(bob["api_key"]["token"])
    ).json()["tables"]["events"]["count"] == 8


def test_scope_checks_prevent_write_and_introspection(api):
    client, _app, _root = api
    reader = provision_user(client, "reader", scopes=[MEMORY_READ])
    headers = bearer(reader["api_key"]["token"])

    assert client.post(
        "/v2/memories/search", headers=headers, json={"query": "anything"}
    ).status_code == 200
    assert client.post(
        "/v2/memory/capture", headers=headers, json={"content": "forbidden", "force": True}
    ).status_code == 403
    assert client.get("/v2/storage/stats", headers=headers).status_code == 403


def test_user_can_issue_and_revoke_non_escalating_api_key(api):
    client, _app, _root = api
    alice = provision_user(client, "alice")
    original_headers = bearer(alice["api_key"]["token"])

    issued = client.post(
        "/v2/me/api-keys",
        headers=original_headers,
        json={"principal_name": "codex", "scopes": [MEMORY_READ]},
    )
    assert issued.status_code == 200
    issued_payload = issued.json()
    new_headers = bearer(issued_payload["api_key"]["token"])
    assert client.get("/v2/me", headers=new_headers).status_code == 200

    escalated = client.post(
        "/v2/me/api-keys",
        headers=original_headers,
        json={"principal_name": "admin", "scopes": ["admin:users"]},
    )
    assert escalated.status_code == 403

    revoked = client.delete(
        f"/v2/me/api-keys/{issued_payload['api_key']['id']}", headers=original_headers
    )
    assert revoked.status_code == 200
    assert client.get("/v2/me", headers=new_headers).status_code == 401


def test_clear_requires_confirmation_and_delete_scope(api):
    client, _app, _root = api
    alice = provision_user(client, "alice")

    response = client.post(
        "/v2/memory/clear",
        headers=bearer(alice["api_key"]["token"]),
        json={"confirm": False},
    )

    assert response.status_code == 400


def test_duplicate_username_returns_conflict(api):
    client, _app, _root = api
    provision_user(client, "alice")

    response = client.post(
        "/v2/admin/users",
        headers=bearer(BOOTSTRAP_TOKEN),
        json={"username": "ALICE"},
    )

    assert response.status_code == 409


def test_openapi_exposes_only_v2_product_routes(api):
    _client, app, _root = api
    schema = app.openapi()

    assert "/v2/context/prepare" in schema["paths"]
    assert "/v2/memory/capture" in schema["paths"]
    assert "/v2/admin/users" in schema["paths"]
    assert not any(path.startswith("/v1/") for path in schema["paths"])
    assert "/context/prepare" not in schema["paths"]
