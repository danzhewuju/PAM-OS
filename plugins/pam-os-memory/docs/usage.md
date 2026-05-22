# PAM-OS Codex Plugin

This plugin packages PAM-OS for Codex with:

- a `pam-os-memory` skill for usage policy
- a stdio MCP server registration for memory tools

Install from a PAM-OS checkout:

```bash
./scripts/install-codex-plugin.sh --yes
```

The installer refreshes the managed PAM-OS repo at `~/.local/share/pam-os/repo`, writes the plugin to `~/plugins/pam-os-memory`, creates or updates `~/.agents/plugins/marketplace.json` with the plugin installed by default, installs the bundled skill to `~/.codex/skills/pam-os-memory`, and registers `pam_os_memory` in `~/.codex/config.toml`.

The MCP server command points at the managed repo and the shared database at `~/.pam-os/memory.sqlite3`. For local development, pass `--repo-dir /path/to/PAM-OS` or `--source /path/to/plugins/pam-os-memory` explicitly.

After restarting Codex, the global skill fallback lets Codex load the PAM-OS memory policy even if the plugin UI has not refreshed yet. The policy captures stable preferences, project decisions, goals, and corrections; it does not write every chat turn.
