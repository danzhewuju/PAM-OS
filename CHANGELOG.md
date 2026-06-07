# Changelog

## v0.3.0 - 2026-06-07

### Added
- Added optional LLM-backed memory extraction behind the provider pipeline, with strict normalization and automatic fallback to the local rule extractor.
- Added configuration for `[extraction]` and `[providers.llm]` so future LLM extraction clients can be wired in without changing the public runtime API.
- Added Docker deployment support for running the REST API in a container with `/data/memory.sqlite3` persistence, configurable base image and package index, health checks, and documented volume usage.
- Added a GitHub Actions workflow that publishes the Docker image to GitHub Container Registry when a GitHub Release is published, including semver tags and `latest`.
- Added CLI and REST support for memory search filters, including memory type, minimum importance, and minimum confidence.
- Added storage inspection and diagnostics through `memory inspect`, `/memory/inspect`, and `/storage/stats`.
- Added multi-client installer support for Codex, Claude Code, OpenCode, and Hermes, including Windows PowerShell installation paths.
- Added interactive REST-mode installer support that can reuse existing skill REST configuration instead of prompting for credentials again.

### Changed
- Bumped the project, runtime, lockfile, and Codex plugin manifest versions to `0.3.0`.
- Reworked the installer flow around a managed PAM-OS checkout so plugin, skill, MCP, and runtime installs stay aligned across clients.
- Consolidated skill installation into the plugin installer and removed the older standalone skill installer scripts.
- Improved CLI-mode and REST-mode behavior: CLI mode registers local MCP where supported, while REST mode removes installer-managed MCP registrations and relies on skill REST configuration.
- Improved Claude MCP registration by making the Claude MCP scope configurable.
- Improved search and context compilation behavior by carrying type and confidence filters through CLI, REST, and runtime calls.
- Improved trait keys for preference and decision-style memory so profile consolidation is more consistent.
- Tightened Docker build context ignores for local config, environment, SQLite, and database files.
- Replaced hard-coded release-tag examples in update documentation with `<version-tag>`.

### Documentation
- Updated the English and Chinese README files with the new installer model, multi-client support, version/update commands, REST API endpoints, and Docker deployment flow.
- Updated usage documentation for REST mode, memory inspection, storage stats, search filters, Docker deployment, and quality trace inspection.
- Added an LLM memory extractor design document covering provider configuration, fallback behavior, and validation expectations.
- Expanded PAM-OS skill usage guidance for CLI vs REST mode, REST server setup, authentication, Claude Code, OpenCode, and Hermes.

### Tests
- Added tests for LLM extraction success, invalid JSON fallback, client-error fallback, missing-evidence rejection, and memory type/score normalization.
- Added tests for REST API clear, inspect, search filtering, request validation, and authentication behavior.
- Added tests for storage stats, memory inspection, config environment overrides, and filtered context compilation.
- Added version consistency checks for project metadata, plugin manifest, lockfile, and release-tag examples.
- Updated offline update-check tests for the `0.3.0` release line.

## v0.2.1 - 2026-06-02

### Added
- Added `observe_turn` as a post-conversation observation entry point for MCP and REST integrations.
- Added `PersonalMemoryRuntime.observe_turn(...)` to conservatively auto-capture stable conversation signals and learn reusable policy signals.
- Added the `AdaptiveLearningLoop` and local admission controller for generating, scoring, and filtering policy signal candidates.
- Added policy learning support for explicit memory requests, durable future instructions, short follow-ups, continuity references, and correction feedback.
- Added quality trace records for `observe_turn` and automatic policy signal admission.
- Added local development plugin installation through `scripts/install-plugin-local.sh`.

### Changed
- Exposed the new `observe_turn` workflow in MCP tool definitions so clients can observe a completed chat turn after answering.
- Updated the runtime and orchestrator flow to combine conservative automatic memory capture with adaptive policy learning.
- Improved plugin installation scripts for local checkout based development, target selection, and non-interactive installation paths.

### Documentation
- Added adaptive learning interaction design documentation covering observation, candidate generation, admission, confirmation, reinforcement, and audit phases.
- Updated English and Chinese README files with local installation instructions for development.
- Updated usage documentation with the `observe_turn` tool, adaptive learning flow, and quality trace guidance.

### Tests
- Added runtime tests for active policy learning from future instructions, staged short follow-up candidates, and high-risk candidate rejection.
- Added MCP tests to verify `observe_turn` is listed and can learn policy signals through the tool interface.
