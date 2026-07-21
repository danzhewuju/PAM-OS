#!/usr/bin/env python3
"""Credential-safe REST client bundled with the PAM-OS memory skill.

The client deliberately owns config loading and Authorization header creation so an
agent never has to place credentials in a terminal command or display config.toml.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tomllib
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"
ALLOWED_ROUTES = {
    ("GET", "/health/live"),
    ("GET", "/v2/meta"),
    ("POST", "/v2/events"),
    ("POST", "/v2/memories/search"),
    ("POST", "/v2/memory/should-use"),
    ("POST", "/v2/context/prepare"),
    ("POST", "/v2/memory/capture"),
    ("POST", "/v2/behavior/choice"),
    ("POST", "/v2/turns/observe"),
    ("POST", "/v2/memory/consolidate"),
    ("GET", "/v2/profile"),
    ("GET", "/v2/memory/inspect"),
    ("GET", "/v2/storage/stats"),
    ("POST", "/v2/context/compile"),
    ("POST", "/v2/reflect"),
    ("POST", "/v2/memory/clear"),
}
SENSITIVE_RESPONSE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "password",
    "refresh_token",
    "secret",
    "token",
    "username",
}


class PamClientError(Exception):
    """Expected client failure whose message is safe to print."""


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    token: str
    timeout: float
    skill_version: str
    skill_api: str
    secrets: tuple[str, ...]


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PamClientError(f"PAM-OS {label} configuration is missing or invalid")
    return value


def _load_config() -> ClientConfig:
    try:
        with CONFIG_PATH.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PamClientError("PAM-OS config.toml is missing, unreadable, or invalid") from exc

    rest = _require_mapping(payload.get("rest"), "REST")
    versions = _require_mapping(payload.get("versions"), "version")
    base_url = str(rest.get("url") or "").strip().rstrip("/")
    token = str(rest.get("token") or "")
    legacy_username = str(rest.get("username") or "")
    legacy_password = str(rest.get("password") or "")
    try:
        timeout = float(rest.get("timeout_seconds", 10))
    except (TypeError, ValueError) as exc:
        raise PamClientError("PAM-OS REST timeout must be a positive number") from exc

    if not base_url:
        raise PamClientError("PAM-OS REST URL is not configured")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PamClientError("PAM-OS REST URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise PamClientError("PAM-OS REST URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise PamClientError("PAM-OS REST URL must not contain a query or fragment")
    if timeout <= 0 or timeout > 60:
        raise PamClientError("PAM-OS REST timeout must be between 0 and 60 seconds")
    if not token:
        if legacy_username or legacy_password:
            raise PamClientError(
                "Legacy username/password authentication is not supported; install a v2 API key"
            )
        raise PamClientError("PAM-OS API key is not configured")

    secrets = tuple(value for value in (token, legacy_username, legacy_password) if value)
    return ClientConfig(
        base_url=base_url,
        token=token,
        timeout=timeout,
        skill_version=str(versions.get("skill") or "").strip(),
        skill_api=str(versions.get("api") or "").strip(),
        secrets=secrets,
    )


def _validate_route(method: str, path: str) -> str:
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith("/"):
        raise PamClientError("PAM-OS request path must be a relative API path")
    if (method, parsed.path) not in ALLOWED_ROUTES:
        raise PamClientError(f"PAM-OS route is not allowed: {method} {parsed.path}")
    return path


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _sanitize(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if str(key).lower() in SENSITIVE_RESPONSE_KEYS
                else _sanitize(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value


def _read_body(args: argparse.Namespace) -> bytes | None:
    if args.body_json is not None and args.body_file is not None:
        raise PamClientError("Use only one of --body-json or --body-file")
    if args.body_json is not None:
        raw = args.body_json
    elif args.body_file is not None:
        if args.body_file == "-":
            raw = sys.stdin.read()
        else:
            try:
                raw = Path(args.body_file).read_text(encoding="utf-8")
            except OSError as exc:
                raise PamClientError("PAM-OS request body file is unreadable") from exc
    else:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PamClientError("PAM-OS request body must be valid JSON") from exc
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _request(
    config: ClientConfig,
    method: str,
    path: str,
    body: bytes | None = None,
) -> Any:
    method = method.upper()
    path = _validate_route(method, path)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.token}",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        config.base_url + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=config.timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise PamClientError(f"PAM-OS request failed with HTTP {exc.code}") from None
    except (OSError, URLError, ValueError):
        raise PamClientError("PAM-OS REST service is unreachable") from None

    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _check(config: ClientConfig) -> dict[str, Any]:
    metadata = _request(config, "GET", "/v2/meta")
    if not isinstance(metadata, dict):
        raise PamClientError("PAM-OS metadata response is invalid")
    server_version = str(metadata.get("version") or "").strip()
    server_api = str(metadata.get("api_version") or "").strip()
    if not server_version or not server_api:
        raise PamClientError("PAM-OS metadata response is missing version fields")
    status = (
        "match"
        if server_version == config.skill_version and server_api == config.skill_api
        else "mismatch"
    )
    return {
        "ok": status == "match",
        "status": status,
        "skill_version": config.skill_version,
        "skill_api": config.skill_api,
        "server_version": server_version,
        "server_api": server_api,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Credential-safe PAM-OS skill REST client"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="check live server and API versions")

    request = commands.add_parser("request", help="call an allowed PAM-OS route")
    request.add_argument("method", choices=("GET", "POST", "get", "post"))
    request.add_argument("path")
    request.add_argument("--body-json")
    request.add_argument("--body-file", help="UTF-8 JSON file, or - for stdin")
    request.add_argument(
        "--allow-destructive",
        action="store_true",
        help="required for the memory clear endpoint",
    )
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        config = _load_config()
        if args.command == "check":
            result = _check(config)
        else:
            method = args.method.upper()
            parsed_path = urlsplit(args.path).path
            if parsed_path == "/v2/memory/clear" and not args.allow_destructive:
                raise PamClientError(
                    "PAM-OS memory clear requires --allow-destructive and explicit user approval"
                )
            result = _request(config, method, args.path, _read_body(args))
        print(json.dumps(_sanitize(result, config.secrets), ensure_ascii=False))
        return 0
    except PamClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Do not emit tracebacks: request/config objects may contain credentials.
        print("error: unexpected PAM-OS client failure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
