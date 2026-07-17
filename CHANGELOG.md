# Changelog

## v0.4.1

Fix build image error.

## v0.4.0

### Removed
- Removed the `memory` and `pam-memory` console scripts and deleted `src/pam_os/cli.py`.
- Removed the direct-SQLite `scripts/inspect_memory.py` command; diagnostics now go through REST.
- Removed CLI mode, CLI fallback, database-path, and Python-runtime settings from the packaged skill configuration and installers.
- Removed client-supplied REST `user_id` database switching because it was data partitioning without an authentication boundary.

### Added
- Added canonical `/v1` REST endpoints, including metadata, liveness, and authenticated readiness endpoints.
- Added REST body-size and field-range validation, unknown-field rejection, stable operation IDs, request IDs, and structured validation/runtime/storage error payloads.
- Added POST-body search and memory-use decision endpoints so sensitive task and query text does not need to be placed in URLs.
- Added SQLite WAL initialization, busy timeout, and connection timeout for normal multi-agent REST concurrency.
- Added atomic event-plus-memory transactions for raw event writes and deduplicating capture writes.
- Added REST timeout settings and restrictive credential-file permissions to the skill installers.

### Changed
- Made FastAPI and Uvicorn required package dependencies and changed Docker to launch the ASGI factory directly.
- Reworked PAM-OS as a personal single-database REST service. Unversioned v0.3 routes remain as hidden compatibility aliases for a migration window.
- Rewrote the packaged skill, installers, README files, and usage documentation around REST-only operation.
- Changed the REST-only installers to discover and reuse existing skill REST settings by default while keeping explicit options and environment variables authoritative.
- Bumped project, runtime, lockfile, and plugin versions to `0.4.0`.

