from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Iterable
from uuid import uuid4

from pam_os.models import now_iso


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$")
TOKEN_PATTERN = re.compile(r"^pam_([0-9a-f]{16})_([A-Za-z0-9_-]{20,})$")

MEMORY_READ = "memory:read"
MEMORY_WRITE = "memory:write"
MEMORY_DELETE = "memory:delete"
MEMORY_INSPECT = "memory:inspect"
API_KEYS_MANAGE = "api_keys:manage"
ADMIN_USERS = "admin:users"

KNOWN_SCOPES = frozenset(
    {
        MEMORY_READ,
        MEMORY_WRITE,
        MEMORY_DELETE,
        MEMORY_INSPECT,
        API_KEYS_MANAGE,
        ADMIN_USERS,
    }
)
DEFAULT_USER_SCOPES = frozenset(
    {
        MEMORY_READ,
        MEMORY_WRITE,
        MEMORY_DELETE,
        MEMORY_INSPECT,
        API_KEYS_MANAGE,
    }
)


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Principal:
    id: str
    user_id: str
    name: str
    kind: str
    status: str
    created_at: str


@dataclass(frozen=True)
class IssuedApiKey:
    id: str
    principal_id: str
    token: str
    prefix: str
    scopes: frozenset[str]
    expires_at: str | None
    created_at: str


@dataclass(frozen=True)
class ProvisionedUser:
    user: User
    principal: Principal
    api_key: IssuedApiKey


@dataclass(frozen=True)
class RequestContext:
    user_id: str | None
    username: str | None
    principal_id: str
    api_key_id: str | None
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def is_bootstrap(self) -> bool:
        return self.user_id is None and self.principal_id == "bootstrap"


class ControlStore:
    """Identity control plane for users, principals, credentials, and audit records."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                  display_name TEXT NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('active', 'disabled')),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS principals (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('active', 'disabled')),
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                  id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL,
                  prefix TEXT NOT NULL UNIQUE,
                  secret_hash TEXT NOT NULL,
                  scopes_json TEXT NOT NULL,
                  expires_at TEXT,
                  revoked_at TEXT,
                  last_used_at TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(principal_id) REFERENCES principals(id)
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                  id TEXT PRIMARY KEY,
                  user_id TEXT,
                  principal_id TEXT NOT NULL,
                  action TEXT NOT NULL,
                  target_type TEXT,
                  target_id TEXT,
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_principals_user
                ON principals(user_id, status);

                CREATE INDEX IF NOT EXISTS idx_api_keys_principal
                ON api_keys(principal_id, revoked_at);

                CREATE INDEX IF NOT EXISTS idx_audit_logs_user
                ON audit_logs(user_id, created_at DESC);
                """
            )

    def create_user(
        self,
        *,
        username: str,
        display_name: str | None = None,
        principal_name: str = "default-agent",
        scopes: Iterable[str] | None = None,
        expires_at: str | None = None,
    ) -> ProvisionedUser:
        normalized_username = normalize_username(username)
        normalized_display_name = (display_name or normalized_username).strip()
        if not normalized_display_name:
            raise ValueError("display_name must not be empty")
        normalized_principal_name = normalize_principal_name(principal_name)
        normalized_scopes = normalize_scopes(scopes or DEFAULT_USER_SCOPES)
        validate_expiration(expires_at)

        timestamp = now_iso()
        user = User(
            id=f"usr_{uuid4().hex}",
            username=normalized_username,
            display_name=normalized_display_name,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        principal = Principal(
            id=f"prn_{uuid4().hex}",
            user_id=user.id,
            name=normalized_principal_name,
            kind="api_key",
            status="active",
            created_at=timestamp,
        )

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(id, username, display_name, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user.id, user.username, user.display_name, user.status, user.created_at, user.updated_at),
            )
            self._insert_principal(conn, principal)
            api_key = self._insert_api_key(
                conn,
                principal_id=principal.id,
                scopes=normalized_scopes,
                expires_at=expires_at,
            )
        return ProvisionedUser(user=user, principal=principal, api_key=api_key)

    def issue_api_key(
        self,
        *,
        user_id: str,
        principal_name: str,
        scopes: Iterable[str] | None = None,
        expires_at: str | None = None,
    ) -> tuple[Principal, IssuedApiKey]:
        normalized_principal_name = normalize_principal_name(principal_name)
        normalized_scopes = normalize_scopes(scopes or DEFAULT_USER_SCOPES)
        validate_expiration(expires_at)
        user = self.get_user(user_id)
        if user is None or user.status != "active":
            raise ValueError("active user not found")
        principal = Principal(
            id=f"prn_{uuid4().hex}",
            user_id=user_id,
            name=normalized_principal_name,
            kind="api_key",
            status="active",
            created_at=now_iso(),
        )
        with self.connect() as conn:
            self._insert_principal(conn, principal)
            api_key = self._insert_api_key(
                conn,
                principal_id=principal.id,
                scopes=normalized_scopes,
                expires_at=expires_at,
            )
        return principal, api_key

    def authenticate(self, token: str) -> RequestContext | None:
        match = TOKEN_PATTERN.fullmatch(token.strip())
        if match is None:
            return None
        prefix = match.group(1)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                  k.id AS api_key_id, k.secret_hash, k.scopes_json, k.expires_at, k.revoked_at,
                  p.id AS principal_id, p.status AS principal_status,
                  u.id AS user_id, u.username, u.status AS user_status
                FROM api_keys k
                JOIN principals p ON p.id = k.principal_id
                JOIN users u ON u.id = p.user_id
                WHERE k.prefix = ?
                """,
                (prefix,),
            ).fetchone()
            if row is None:
                return None
            if row["revoked_at"] or row["principal_status"] != "active" or row["user_status"] != "active":
                return None
            if is_expired(row["expires_at"]):
                return None
            if not hmac.compare_digest(row["secret_hash"], hash_token(token)):
                return None
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now_iso(), row["api_key_id"]))

        try:
            scopes = normalize_scopes(json.loads(row["scopes_json"]))
        except (TypeError, json.JSONDecodeError, ValueError):
            return None
        return RequestContext(
            user_id=row["user_id"],
            username=row["username"],
            principal_id=row["principal_id"],
            api_key_id=row["api_key_id"],
            scopes=scopes,
        )

    def get_user(self, user_id: str) -> User | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_user(row) if row else None

    def revoke_api_key(self, api_key_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (now_iso(), api_key_id),
            )
        return cursor.rowcount > 0

    def revoke_api_key_for_user(self, *, api_key_id: str, user_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE api_keys
                SET revoked_at = ?
                WHERE id = ?
                  AND revoked_at IS NULL
                  AND principal_id IN (SELECT id FROM principals WHERE user_id = ?)
                """,
                (now_iso(), api_key_id, user_id),
            )
        return cursor.rowcount > 0

    def record_audit(
        self,
        context: RequestContext,
        *,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs(
                  id, user_id, principal_id, action, target_type, target_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"aud_{uuid4().hex}",
                    context.user_id,
                    context.principal_id,
                    action,
                    target_type,
                    target_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def user_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT count(*) AS count FROM users").fetchone()
        return int(row["count"] if row else 0)

    def _insert_principal(self, conn: sqlite3.Connection, principal: Principal) -> None:
        conn.execute(
            """
            INSERT INTO principals(id, user_id, name, kind, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                principal.id,
                principal.user_id,
                principal.name,
                principal.kind,
                principal.status,
                principal.created_at,
            ),
        )

    def _insert_api_key(
        self,
        conn: sqlite3.Connection,
        *,
        principal_id: str,
        scopes: frozenset[str],
        expires_at: str | None,
    ) -> IssuedApiKey:
        api_key_id = f"key_{uuid4().hex}"
        prefix = secrets.token_hex(8)
        token = f"pam_{prefix}_{secrets.token_urlsafe(32)}"
        created_at = now_iso()
        conn.execute(
            """
            INSERT INTO api_keys(
              id, principal_id, prefix, secret_hash, scopes_json, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                api_key_id,
                principal_id,
                prefix,
                hash_token(token),
                json.dumps(sorted(scopes)),
                expires_at,
                created_at,
            ),
        )
        return IssuedApiKey(
            id=api_key_id,
            principal_id=principal_id,
            token=token,
            prefix=prefix,
            scopes=scopes,
            expires_at=expires_at,
            created_at=created_at,
        )

    def _row_to_user(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def normalize_username(username: str) -> str:
    normalized = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("username must match [A-Za-z0-9][A-Za-z0-9_.@-]{0,63}")
    return normalized


def normalize_principal_name(name: str) -> str:
    normalized = name.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("principal_name must contain 1..128 characters")
    return normalized


def normalize_scopes(scopes: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(str(scope).strip() for scope in scopes if str(scope).strip())
    unknown = normalized - KNOWN_SCOPES
    if unknown:
        raise ValueError(f"unknown scopes: {', '.join(sorted(unknown))}")
    if not normalized:
        raise ValueError("at least one scope is required")
    return normalized


def validate_expiration(expires_at: str | None) -> None:
    if expires_at is None:
        return
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")


def is_expired(expires_at: str | None) -> bool:
    if expires_at is None:
        return False
    try:
        value = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if value.tzinfo is None:
        return True
    return value <= datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    # The token contains 256 bits of randomness, so a fast one-way hash is appropriate.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
