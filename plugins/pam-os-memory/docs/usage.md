# PAM-OS Codex Plugin

This plugin packages PAM-OS for Codex with:

- a `pam-os-memory` skill for usage policy

Install from a PAM-OS checkout:

```bash
./scripts/install.sh --codex --yes
```

The installer refreshes the managed PAM-OS repo at `~/.local/share/pam-os/repo`, writes the plugin to `~/plugins/pam-os-memory`, creates or updates `~/.agents/plugins/marketplace.json` with the plugin installed by default, and installs the bundled skill to `~/.codex/skills/pam-os-memory`.

The skill config contains observable skill, API, and detected server versions together with the PAM-OS REST URL, user-bound Bearer API key, and request timeout. Re-running either platform installer detects and updates existing integrations. Existing REST settings are reused by default; interactive prompts only report whether a token is configured. Explicit options and `PAM_OS_REST_*` environment variables take precedence. For local development, pass `--repo-dir /path/to/PAM-OS` explicitly.

After restarting Codex, the global skill fallback lets Codex load the PAM-OS memory policy even if the plugin UI has not refreshed yet. The policy calls `observe_turn` after each substantial user-facing turn so PAM-OS can conservatively capture stable preferences, project decisions, goals, and corrections while skipping transient chat.
