# Windows Skill Installer Design

## Goal

Add a Windows-native installer for the PAM-OS memory skill. The script should let Windows users install the same global skill targets that `scripts/install-skill.sh` supports without requiring Bash, WSL, or Git Bash.

The implementation target is a new PowerShell script at `scripts/install-skill.ps1`.

## Scope

The Windows installer will mirror the Bash skill installer behavior where it matters:

- Install targets: Codex, Claude Code, OpenCode compatibility, and CC Switch.
- Runtime modes: `cli` and `rest`.
- Skill configuration: write `config.toml` into each installed skill directory.
- Source discovery: prefer a local checkout and support an explicit `--source` path.
- Remote fallback: clone the configured PAM-OS repository when no local skill template is available.
- Existing installs: prompt before replacement unless `--yes` or `--non-interactive` is used.
- CLI mode: find or clone a PAM-OS repo and optionally run `memory init`.
- OpenCode mode: install the Claude-compatible skill when needed and update `AGENTS.md` with a managed block.

Out of scope:

- Changing the skill template contents.
- Changing `install-skill.sh`.
- Adding plugin installer support. This script is only for skill installation.
- Supporting Windows CMD as the primary implementation language.

## User Interface

The script should be invoked as:

```powershell
.\scripts\install-skill.ps1 [options]
```

It should accept the same user-facing options as `install-skill.sh`:

- `--all`
- `--codex`
- `--claude`
- `--opencode`
- `--cc-switch`
- `--mode cli|rest`
- `--no-init`
- `--python VERSION`
- `--cli-command COMMAND`
- `--repo-dir DIR`
- `--db PATH`
- `--repo-url URL`
- `--ref REF`
- `--source DIR`
- `--yes`
- `--non-interactive`
- `-h` or `--help`

When no target is passed, interactive mode should prompt for install targets. With `--yes` and no target, it should install Codex only, matching the Bash installer.

## Windows Defaults

Default paths should use Windows-friendly locations:

- Skill name: `pam-os-memory`
- Repo URL: `https://github.com/danzhewuju/PAM-OS.git`
- Repo ref: `master`
- Codex skill: `$HOME\.codex\skills\pam-os-memory`
- Claude Code skill: `$HOME\.claude\skills\pam-os-memory`
- OpenCode config: `$env:APPDATA\opencode\AGENTS.md`, falling back to `$HOME\AppData\Roaming\opencode\AGENTS.md` when `APPDATA` is unavailable.
- CC Switch skill: `$env:APPDATA\cc-switch\skills\pam-os-memory`, falling back to `$HOME\AppData\Roaming\cc-switch\skills\pam-os-memory`.
- CLI repo: `$env:LOCALAPPDATA\pam-os\repo`, falling back to `$HOME\AppData\Local\pam-os\repo`.
- SQLite database: `$HOME\.pam-os\memory.sqlite3`.

Environment variables should continue to override defaults where the Bash installer already supports them:

- `PAM_OS_SKILL_NAME`
- `PAM_OS_REPO_URL`
- `PAM_OS_REPO_REF`
- `PAM_OS_REPO_DIR`
- `PAM_OS_DB`
- `PAM_OS_DB_PATH`
- `PAM_OS_CLI_PYTHON`
- `PAM_OS_CLI_COMMAND`
- `CODEX_HOME`
- `CC_SWITCH_HOME`

## Implementation Notes

Use PowerShell-native behavior instead of shelling out to Bash utilities:

- `Copy-Item -Recurse` for skill installs.
- `Remove-Item -Recurse -Force` for replacing an existing install after confirmation.
- `New-Item -ItemType Directory -Force` for parent directory creation.
- `Read-Host` for prompts.
- `Read-Host -AsSecureString` plus conversion for REST password input.
- `Get-Command` to detect `git` and `uv`.
- `git clone --depth 1 --branch <ref>` with a fallback clone of the default branch.
- `uv --directory <repo> run --python <version> <command> --db <path> init` for optional CLI initialization.

The script should keep helper functions small and parallel to the Bash script:

- `Write-Info`, `Write-Warn`, and `Stop-Install`
- `Confirm-Action`
- `Prompt-Value`
- `Select-InstallTargets`
- `Resolve-AbsolutePath`
- `ConvertTo-TomlString`
- `Ensure-CliRepo`
- `Find-SkillSource`
- `Download-RepoSource`
- `Write-SkillConfig`
- `Prepare-Destination`
- `Install-SkillDir`
- `Update-ManagedBlock`
- `Install-OpenCode`
- `Invoke-CliInit`
- `Show-Summary`

## Error Handling

The script should fail early with clear messages when required option values are empty, the runtime mode is invalid, or no install target is selected.

In CLI mode, if a suitable PAM-OS checkout cannot be found and `git` is unavailable, installation should stop with a clear message. If `uv` is unavailable during optional init, installation should still succeed and print the manual command to run later.

## Safety

The script may replace existing installation directories only after user confirmation, unless `--yes` or `--non-interactive` is set. Directory replacement should use resolved literal paths and only target the explicitly selected install destination.

When updating OpenCode `AGENTS.md`, the script should create a timestamped backup if the file already exists, remove any previous PAM-OS managed block, and append a fresh block.

## Validation

Minimum validation before considering the script complete:

- `pwsh -NoProfile -File scripts/install-skill.ps1 --help`
- `pwsh -NoProfile -File scripts/install-skill.ps1 --codex --yes --no-init --source <local skill source>`
- Verify that the installed skill contains `SKILL.md` and `config.toml`.

If `pwsh` is unavailable, run equivalent Windows PowerShell syntax checks with `powershell -NoProfile -File ... --help` and report the reduced validation.
