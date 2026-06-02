# Changelog

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
