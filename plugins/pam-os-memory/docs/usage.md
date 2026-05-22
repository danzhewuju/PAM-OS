# PAM-OS Codex Plugin

This plugin packages PAM-OS for Codex with:

- a `pam-os-memory` skill for usage policy
- a stdio MCP server registration for memory tools

Install from a PAM-OS checkout:

```bash
./scripts/install-codex-plugin.sh --yes
```

The installer writes the plugin to `~/plugins/pam-os-memory`, creates or updates `~/.agents/plugins/marketplace.json`, and registers `pam_os_memory` in `~/.codex/config.toml`.

The MCP server command defaults to the global PAM-OS repo installed at `~/.local/share/pam-os/repo` and the shared database at `~/.pam-os/memory.sqlite3`. When run from a local checkout, the installer rewrites `.mcp.json` and the Codex MCP config to point at that checkout.
