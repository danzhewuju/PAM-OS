# PAM-OS Multi-user v2

## Security invariant

Normal memory requests never select a user. The server resolves one immutable user from a Bearer API key before opening memory storage:

```text
Bearer token -> API key -> Principal -> User -> owner-bound SQLite
```

`user_id` and `X-PAM-OS-User` are not accepted by v2 business request models. Cross-user administration is available only through explicit `/v2/admin/*` routes with `admin:users`.

## Identity control plane

`control.sqlite3` owns four tables:

- `users`: stable account ID, username, display name, and status.
- `principals`: an independently revocable caller identity such as Codex or Claude.
- `api_keys`: token prefix, SHA-256 hash, scopes, expiry, revocation, and last use. Plaintext tokens are returned once and never persisted.
- `audit_logs`: identity, credential, and destructive-operation audit events.

API keys use 256 bits of random secret material. A fast one-way hash is appropriate because offline guessing of that entropy is infeasible; account passwords are not part of this design.

## Memory data plane

Each user receives:

```text
<data_dir>/users/<immutable-user-id>/memory.sqlite3
```

`store_metadata.owner_user_id` is created and verified whenever a runtime is first opened. `UserRuntimeFactory` validates internal IDs, serializes runtime creation, and keeps a bounded LRU cache. SQLite operations continue using short connections, WAL, foreign keys, and busy timeouts.

Physical databases are the primary isolation mechanism. Memory rows do not carry caller-provided ownership fields, so retrieval, deduplication, profile consolidation, policy learning, inspection, statistics, and clear operations cannot omit a tenant predicate.

## Authentication and scopes

All `/v2` endpoints require `Authorization: Bearer <api-key>` except `/health/live`. Current scopes are:

- `memory:read`
- `memory:write`
- `memory:delete`
- `memory:inspect`
- `api_keys:manage`
- `admin:users`

The optional `PAM_OS_BOOTSTRAP_TOKEN` produces a system context with only `admin:users`. It can provision the first user but cannot access memory. It should be removed after provisioning a user-bound administrative API key.

## Client contract

Installed skills use `/v2`, store a user-bound `token` in their permission-restricted `config.toml`, and send it as Bearer authentication. The installer supports `--rest-token` and `PAM_OS_REST_TOKEN`.

There are no v1 or unversioned compatibility routes.

## Future storage adapter

Large centralized deployments can replace the physical SQLite data plane with PostgreSQL. That adapter must put `user_id` on every tenant table, include it in uniqueness and foreign-key constraints, and enforce PostgreSQL row-level security. The REST identity contract remains unchanged.
