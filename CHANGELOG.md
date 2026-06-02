# Changelog

## v0.2.0 - 2026-06-02

### Added
- Added structured memory fact candidates with `fact:<key>` tags.
- Added query intent based memory retrieval for identity and preference recall.
- Added finer profile trait keys such as `profile.identity.name` and `preference.interests`.
- Added `memory version` and `memory update-check` CLI commands.
- Added `scripts/update.sh` for refreshing the managed PAM-OS checkout and reinstalling integrations.

### Fixed
- Fixed English identity roundtrip: `Hello, I'm Alex, I like digital products.` followed by `Hello, who am I?` now recalls identity and interests.
- Preserved legacy semantic identity recall as a fallback.
