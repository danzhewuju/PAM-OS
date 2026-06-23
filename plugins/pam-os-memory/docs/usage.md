# PAM-OS Codex Plugin

This plugin packages PAM-OS for Codex with:

- a `pam-os-memory` skill for usage policy

Install from a PAM-OS checkout:

```bash
./scripts/install-plugin.sh --codex --yes
```

The installer refreshes the managed PAM-OS repo at `~/.local/share/pam-os/repo`, writes the plugin to `~/plugins/pam-os-memory`, creates or updates `~/.agents/plugins/marketplace.json` with the plugin installed by default, and installs the bundled skill to `~/.codex/skills/pam-os-memory`.

The skill config chooses either CLI mode with the shared database at `~/.pam-os/memory.sqlite3` or REST mode with the configured API URL. For local development, pass `--repo-dir /path/to/PAM-OS` or `--source /path/to/plugins/pam-os-memory` explicitly.

After restarting Codex, the global skill fallback lets Codex load the PAM-OS memory policy even if the plugin UI has not refreshed yet. The policy calls `observe_turn` after each substantial user-facing turn so PAM-OS can conservatively capture stable preferences, project decisions, goals, and corrections while skipping transient chat.
