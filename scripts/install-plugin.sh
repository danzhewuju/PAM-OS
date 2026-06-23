#!/usr/bin/env bash
set -Eeuo pipefail

PLUGIN_NAME="${PAM_OS_PLUGIN_NAME:-pam-os-memory}"
DEFAULT_REPO_URL="${PAM_OS_REPO_URL:-https://github.com/danzhewuju/PAM-OS.git}"
DEFAULT_REPO_REF="${PAM_OS_REPO_REF:-master}"
DEFAULT_REPO_DIR="${PAM_OS_REPO_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/pam-os/repo}"
DEFAULT_DB_PATH="${PAM_OS_DB:-${PAM_OS_DB_PATH:-$HOME/.pam-os/memory.sqlite3}}"
DEFAULT_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
DEFAULT_PLUGIN_DIR="$HOME/plugins/$PLUGIN_NAME"
DEFAULT_MARKETPLACE_PATH="$HOME/.agents/plugins/marketplace.json"
DEFAULT_CODEX_CONFIG="$DEFAULT_CODEX_HOME/config.toml"
DEFAULT_CODEX_SKILL_DIR="$DEFAULT_CODEX_HOME/skills/$PLUGIN_NAME"
DEFAULT_CLAUDE_SKILL_DIR="$HOME/.claude/skills/$PLUGIN_NAME"
DEFAULT_OPENCODE_AGENTS_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/AGENTS.md"
DEFAULT_HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DEFAULT_HERMES_AGENTS_FILE="$DEFAULT_HERMES_HOME/AGENTS.md"
DEFAULT_HERMES_SKILL_DIR="$DEFAULT_HERMES_HOME/skills/$PLUGIN_NAME"
LEGACY_SERVER_NAME="pam_os_memory"

info() {
  printf '\033[1;34m==>\033[0m %s\n' "$*" >&2
}

warn() {
  printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2
}

die() {
  printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<USAGE
PAM-OS plugin installer

Usage:
  ./scripts/install-plugin.sh [options]

Options:
  --target TARGET      Install target: codex, claude, opencode, hermes, or all. Can be repeated.
  --codex             Install the Codex plugin and global skill.
  --claude            Install the Claude Code global skill.
  --opencode          Install OpenCode guidance and Claude-compatible skill.
  --hermes            Install Hermes skill and guidance.
  --all               Install all supported targets.
  --mode cli|rest     Set skill runtime mode. Default: cli.
  --runtime cli|rest  Alias for --mode.
  --rest-url URL      PAM-OS REST server URL. Default: http://127.0.0.1:8765.
  --rest-username USER
                      REST Basic Auth username. Default: empty.
  --rest-password PASS
                      REST Basic Auth password. Default: empty.
  --db PATH           PAM-OS SQLite database path. Default: ~/.pam-os/memory.sqlite3.
  --python VERSION    Python version for CLI mode. Default: 3.12.
  --repo-dir DIR      Use an existing PAM-OS checkout. Default: managed repo.
  --repo-url URL      Git repository used to refresh the managed repo.
  --ref REF           Git ref used to refresh the managed repo. Default: master.
  --source DIR        Existing pam-os-memory plugin source directory for dev/local installs.
  --plugin-dir DIR    Destination Codex plugin dir. Default: ~/plugins/pam-os-memory.
  --marketplace PATH  Personal marketplace path. Default: ~/.agents/plugins/marketplace.json.
  --codex-config PATH Codex config.toml path used only for legacy cleanup.
  --codex-skill-dir DIR
                      Codex global skill dir. Default: ~/.codex/skills/pam-os-memory.
  --claude-skill-dir DIR
                      Claude Code skill dir. Default: ~/.claude/skills/pam-os-memory.
  --opencode-agents PATH
                      OpenCode AGENTS.md path. Default: ~/.config/opencode/AGENTS.md.
  --hermes-agents PATH
                      Hermes AGENTS.md path. Default: ~/.hermes/AGENTS.md.
  --hermes-skill-dir DIR
                      Hermes skill dir. Default: ~/.hermes/skills/pam-os-memory.
  --skip-marketplace  Do not create or update the personal plugin marketplace entry.
  --skip-global-skill Do not install the Codex global skill.
  --no-refresh        Do not fetch or clone the managed repo before installing.
  --yes               Replace existing installs without prompting.
  -h, --help          Show this help.

PAM-OS now supports only CLI and REST adapters. This installer writes the
selected skill config and removes legacy local tool registrations it manages.
USAGE
}

can_prompt() {
  [[ -r /dev/tty && -w /dev/tty ]] || [[ -t 0 && -t 1 ]]
}

read_user() {
  local __result_var="$1"
  local prompt="$2"

  printf -v "$__result_var" '%s' ''
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    printf '%s' "$prompt" > /dev/tty
    if read -r "$__result_var" < /dev/tty; then
      return 0
    fi
  fi

  if [[ -t 0 ]] && read -r -p "$prompt" "$__result_var"; then
    return 0
  fi

  return 1
}

read_secret_user() {
  local __result_var="$1"
  local prompt="$2"

  printf -v "$__result_var" '%s' ''
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    printf '%s' "$prompt" > /dev/tty
    if read -r -s "$__result_var" < /dev/tty; then
      printf '\n' > /dev/tty
      return 0
    fi
  fi

  if [[ -t 0 ]] && read -r -s -p "$prompt" "$__result_var"; then
    printf '\n' >&2
    return 0
  fi

  return 1
}

confirm() {
  local prompt="$1"
  local default="${2:-y}"
  local reply suffix

  if [[ "$ASSUME_YES" == "1" ]]; then
    [[ "$default" == "y" ]]
    return
  fi

  suffix="[y/N]"
  [[ "$default" == "y" ]] && suffix="[Y/n]"
  while true; do
    if ! read_user reply "$prompt $suffix "; then
      die "Interactive prompt requires a TTY. Re-run with --yes or explicit options."
    fi
    reply="${reply:-$default}"
    case "$reply" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO) return 1 ;;
      *) printf 'Please answer y or n.\n' ;;
    esac
  done
}

prompt_value() {
  local prompt="$1"
  local default="$2"
  local reply rendered_prompt

  if [[ "$ASSUME_YES" == "1" ]]; then
    printf '%s' "$default"
    return
  fi

  if [[ -n "$default" ]]; then
    rendered_prompt="$prompt [$default]: "
  else
    rendered_prompt="$prompt (leave empty for none): "
  fi
  read_user reply "$rendered_prompt" || die "Interactive prompt requires a TTY. Pass an explicit option or use --yes."
  printf '%s' "${reply:-$default}"
}

prompt_secret() {
  local prompt="$1"
  local default="$2"
  local reply

  if [[ "$ASSUME_YES" == "1" ]]; then
    printf '%s' "$default"
    return
  fi

  read_secret_user reply "$prompt (leave empty for none): " || die "Interactive prompt requires a TTY. Pass explicit REST options or use --yes."
  printf '%s' "${reply:-$default}"
}

enable_target() {
  case "$1" in
    codex) INSTALL_CODEX=1 ;;
    claude|claude-code) INSTALL_CLAUDE=1 ;;
    opencode) INSTALL_OPENCODE=1 ;;
    hermes) INSTALL_HERMES=1 ;;
    all)
      INSTALL_CODEX=1
      INSTALL_CLAUDE=1
      INSTALL_OPENCODE=1
      INSTALL_HERMES=1
      ;;
    *) die "Unknown target: $1" ;;
  esac
}

select_install_targets() {
  local selection item

  printf '\nInstall targets:\n'
  printf '  1) codex     - Codex plugin + global skill\n'
  printf '  2) claude    - Claude Code global skill\n'
  printf '  3) opencode  - OpenCode guidance\n'
  printf '  4) hermes    - Hermes skill + guidance\n'
  printf '  5) all\n'
  printf '\nSelect one or more targets, separated by commas or spaces.\n'

  while true; do
    read_user selection 'Selection [1]: ' || die "Interactive target selection requires a TTY."
    selection="${selection:-1}"
    selection="${selection//,/ }"

    INSTALL_CODEX=0
    INSTALL_CLAUDE=0
    INSTALL_OPENCODE=0
    INSTALL_HERMES=0

    for item in $selection; do
      case "$item" in
        1|codex|Codex|CODEX) INSTALL_CODEX=1 ;;
        2|claude|Claude|CLAUDE|claude-code|Claude-Code) INSTALL_CLAUDE=1 ;;
        3|opencode|OpenCode|OPENCODE) INSTALL_OPENCODE=1 ;;
        4|hermes|Hermes|HERMES) INSTALL_HERMES=1 ;;
        5|all|All|ALL) INSTALL_CODEX=1; INSTALL_CLAUDE=1; INSTALL_OPENCODE=1; INSTALL_HERMES=1 ;;
        *) warn "Unknown target: $item"; INSTALL_CODEX=0; INSTALL_CLAUDE=0; INSTALL_OPENCODE=0; INSTALL_HERMES=0; break ;;
      esac
    done

    [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" != "0000" ]] && return 0
    printf 'Please select at least one valid target.\n'
  done
}

abs_path() {
  local path="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$path"
  else
    (cd "$(dirname "$path")" && printf '%s/%s\n' "$(pwd)" "$(basename "$path")")
  fi
}

toml_escape() {
  printf "%s" "$1" | sed "s/\\\\/\\\\\\\\/g; s/\"/\\\"/g"
}

is_pam_repo() {
  local path="$1"
  [[ -f "$path/pyproject.toml" && -d "$path/src/pam_os" ]]
}

refresh_managed_repo() {
  [[ "$REFRESH_REPO" == "1" ]] || return 0
  command -v git >/dev/null 2>&1 || die "git is required to refresh the managed PAM-OS repo. Re-run with --no-refresh or --repo-dir."

  if [[ -d "$REPO_DIR/.git" ]]; then
    info "Refreshing managed PAM-OS repo at $REPO_DIR ($REPO_REF)"
    git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_REF" >/dev/null
    git -C "$REPO_DIR" checkout -q FETCH_HEAD
    return 0
  fi

  [[ ! -e "$REPO_DIR" ]] || die "Managed repo path exists but is not a git checkout: $REPO_DIR"
  info "Cloning managed PAM-OS repo into $REPO_DIR ($REPO_REF)"
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 || {
    warn "Branch clone failed; trying default branch."
    git clone --depth 1 "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 || die "Could not clone $REPO_URL"
  }
}

resolve_repo_dir() {
  if [[ "$REPO_DIR_EXPLICIT" == "1" ]]; then
    [[ -e "$REPO_DIR" ]] || die "--repo-dir must point to an existing PAM-OS checkout: $REPO_DIR"
    REPO_DIR="$(abs_path "$REPO_DIR")"
    is_pam_repo "$REPO_DIR" || die "--repo-dir is not a PAM-OS checkout: $REPO_DIR"
    return 0
  fi

  if [[ -n "$SOURCE_DIR" ]]; then
    local inferred
    inferred="$(abs_path "$SOURCE_DIR/../..")"
    if is_pam_repo "$inferred"; then
      REPO_DIR="$inferred"
      REFRESH_REPO=0
      return 0
    fi
  fi

  refresh_managed_repo
  REPO_DIR="$(abs_path "$REPO_DIR")"
  is_pam_repo "$REPO_DIR" || die "Could not find a PAM-OS repo: $REPO_DIR"
}

find_plugin_source() {
  local candidate
  for candidate in "$SOURCE_DIR" "$REPO_DIR/plugins/$PLUGIN_NAME"; do
    if [[ -n "$candidate" && -f "$candidate/.codex-plugin/plugin.json" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done
  return 1
}

find_skill_source() {
  local candidate
  for candidate in "$REPO_DIR/skills/$PLUGIN_NAME" "$REPO_DIR/plugins/$PLUGIN_NAME/skills/$PLUGIN_NAME" "$SOURCE_DIR/skills/$PLUGIN_NAME"; do
    if [[ -n "$candidate" && -f "$candidate/SKILL.md" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done
  return 1
}

write_skill_config() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  cat > "$path" <<EOF
# PAM-OS skill runtime mode.
# Supported modes: cli, rest.

mode = "$INSTALL_MODE"

[cli]
python = "$(toml_escape "$PYTHON_VERSION")"
command = "memory"
repo_dir = "$(toml_escape "$REPO_DIR")"
db_path = "$(toml_escape "$DB_PATH")"

[rest]
url = "$(toml_escape "$REST_URL")"
username = "$(toml_escape "$REST_USERNAME")"
password = "$(toml_escape "$REST_PASSWORD")"
EOF
}

copy_dir() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp -R "$src" "$dest"
}

install_skill() {
  local src="$1"
  local dest="$2"
  local label="$3"
  if [[ -e "$dest" ]]; then
    if confirm "Replace existing $label at $dest?" "y"; then
      rm -rf "$dest"
    else
      warn "Skipped $label install."
      return 0
    fi
  fi
  info "Installing $label to $dest"
  copy_dir "$src" "$dest"
  write_skill_config "$dest/config.toml"
}

write_bundled_skill_config() {
  local plugin_dir="$1"
  local skill_dir="$plugin_dir/skills/$PLUGIN_NAME"
  [[ -d "$skill_dir" ]] && write_skill_config "$skill_dir/config.toml"
  rm -f "$plugin_dir/.mcp.json"
}

write_marketplace_config() {
  local path="$1"
  python3 - "$path" "$PLUGIN_NAME" <<'PY'
import json
import sys
from pathlib import Path

path, plugin_name = sys.argv[1:]
marketplace_path = Path(path).expanduser()
if marketplace_path.exists():
    payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
else:
    payload = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}

plugins = payload.setdefault("plugins", [])
entry = {
    "name": plugin_name,
    "source": {"source": "local", "path": f"./plugins/{plugin_name}"},
    "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}
for index, existing in enumerate(plugins):
    if isinstance(existing, dict) and existing.get("name") == plugin_name:
        plugins[index] = entry
        break
else:
    plugins.append(entry)

marketplace_path.parent.mkdir(parents=True, exist_ok=True)
marketplace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

remove_legacy_codex_config() {
  local path="$1"
  python3 - "$path" "$LEGACY_SERVER_NAME" <<'PY'
import sys
from pathlib import Path

path, server_name = sys.argv[1:]
config_path = Path(path).expanduser()
if not config_path.exists():
    raise SystemExit(0)

server_header = f"[mcp_servers.{server_name}]"
server_child_prefix = f"[mcp_servers.{server_name}."

def is_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")

def is_managed_server_header(line: str) -> bool:
    stripped = line.strip()
    return stripped == server_header or stripped.startswith(server_child_prefix)

lines = config_path.read_text(encoding="utf-8").splitlines()
output = []
index = 0
removed = False
while index < len(lines):
    line = lines[index]
    if is_managed_server_header(line):
        removed = True
        index += 1
        while index < len(lines):
            if is_table_header(lines[index]) and not is_managed_server_header(lines[index]):
                break
            index += 1
        continue
    output.append(line)
    index += 1

if removed:
    config_path.write_text(("\n".join(output).rstrip() + "\n") if output else "", encoding="utf-8")
PY
}

append_guidance() {
  local path="$1"
  local skill_path="$2"
  local begin="<!-- PAM-OS MEMORY BEGIN -->"
  local end="<!-- PAM-OS MEMORY END -->"
  mkdir -p "$(dirname "$path")"
  python3 - "$path" "$skill_path" "$begin" "$end" <<'PY'
import sys
from pathlib import Path

path, skill_path, begin, end = sys.argv[1:]
target = Path(path).expanduser()
existing = target.read_text(encoding="utf-8") if target.exists() else ""
while begin in existing and end in existing:
    start = existing.index(begin)
    finish = existing.index(end, start) + len(end)
    existing = (existing[:start] + existing[finish:]).strip() + "\n"

block = f"""{begin}
Use the installed PAM-OS skill from `{skill_path}`. Read its `config.toml` first and use the configured CLI or REST adapter.
{end}
"""
target.write_text(existing.rstrip() + "\n\n" + block if existing.strip() else block, encoding="utf-8")
PY
}

configure_rest_runtime() {
  REST_URL="$(prompt_value "PAM-OS REST URL" "$REST_URL")"
  REST_USERNAME="$(prompt_value "REST username" "$REST_USERNAME")"
  REST_PASSWORD="$(prompt_secret "REST password" "$REST_PASSWORD")"
}

ASSUME_YES=0
INSTALL_CODEX=0
INSTALL_CLAUDE=0
INSTALL_OPENCODE=0
INSTALL_HERMES=0
INSTALL_MODE=""
MODE_ARG=""
PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
MARKETPLACE_PATH="$DEFAULT_MARKETPLACE_PATH"
CODEX_CONFIG="$DEFAULT_CODEX_CONFIG"
CODEX_SKILL_DIR="$DEFAULT_CODEX_SKILL_DIR"
CLAUDE_SKILL_DIR="$DEFAULT_CLAUDE_SKILL_DIR"
OPENCODE_AGENTS_FILE="$DEFAULT_OPENCODE_AGENTS_FILE"
HERMES_AGENTS_FILE="$DEFAULT_HERMES_AGENTS_FILE"
HERMES_SKILL_DIR="$DEFAULT_HERMES_SKILL_DIR"
REPO_URL="$DEFAULT_REPO_URL"
REPO_REF="$DEFAULT_REPO_REF"
REPO_DIR="$DEFAULT_REPO_DIR"
REPO_DIR_EXPLICIT=0
REFRESH_REPO=1
SOURCE_DIR=""
DB_PATH="$DEFAULT_DB_PATH"
PYTHON_VERSION="${PAM_OS_CLI_PYTHON:-3.12}"
REST_URL="${PAM_OS_REST_URL:-http://127.0.0.1:8765}"
REST_USERNAME="${PAM_OS_REST_USERNAME:-}"
REST_PASSWORD="${PAM_OS_REST_PASSWORD:-}"
WRITE_MARKETPLACE=1
WRITE_GLOBAL_SKILL=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) enable_target "${2:-}"; shift 2 ;;
    --codex) INSTALL_CODEX=1; shift ;;
    --claude) INSTALL_CLAUDE=1; shift ;;
    --opencode) INSTALL_OPENCODE=1; shift ;;
    --hermes) INSTALL_HERMES=1; shift ;;
    --all) enable_target all; shift ;;
    --mode|--runtime) MODE_ARG="${2:-}"; shift 2 ;;
    --rest-url) REST_URL="${2:-}"; shift 2 ;;
    --rest-username|--rest-user) REST_USERNAME="${2:-}"; shift 2 ;;
    --rest-password) REST_PASSWORD="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --python) PYTHON_VERSION="${2:-}"; shift 2 ;;
    --repo-dir) REPO_DIR="${2:-}"; REPO_DIR_EXPLICIT=1; REFRESH_REPO=0; shift 2 ;;
    --repo-url) REPO_URL="${2:-}"; shift 2 ;;
    --ref) REPO_REF="${2:-}"; shift 2 ;;
    --source) SOURCE_DIR="${2:-}"; shift 2 ;;
    --plugin-dir) PLUGIN_DIR="${2:-}"; shift 2 ;;
    --marketplace) MARKETPLACE_PATH="${2:-}"; shift 2 ;;
    --codex-config) CODEX_CONFIG="${2:-}"; shift 2 ;;
    --codex-skill-dir) CODEX_SKILL_DIR="${2:-}"; shift 2 ;;
    --claude-skill-dir) CLAUDE_SKILL_DIR="${2:-}"; shift 2 ;;
    --opencode-agents) OPENCODE_AGENTS_FILE="${2:-}"; shift 2 ;;
    --hermes-agents) HERMES_AGENTS_FILE="${2:-}"; shift 2 ;;
    --hermes-skill-dir) HERMES_SKILL_DIR="${2:-}"; shift 2 ;;
    --skip-marketplace) WRITE_MARKETPLACE=0; shift ;;
    --skip-global-skill) WRITE_GLOBAL_SKILL=0; shift ;;
    --no-refresh) REFRESH_REPO=0; shift ;;
    --skip-mcp-config|--no-init|--claude-mcp-scope|--hermes-config)
      [[ "$1" == "--skip-mcp-config" || "$1" == "--no-init" ]] && shift || shift 2
      ;;
    --yes|--non-interactive) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$MODE_ARG" ]] || MODE_ARG="cli"
[[ "$MODE_ARG" == "cli" || "$MODE_ARG" == "rest" ]] || die "--mode must be cli or rest."
INSTALL_MODE="$MODE_ARG"

if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" == "0000" ]]; then
  if [[ "$ASSUME_YES" == "1" ]]; then
    INSTALL_CODEX=1
  else
    can_prompt || die "Interactive install requires a TTY. Use --yes or choose targets explicitly."
    select_install_targets
  fi
fi

if [[ "$INSTALL_MODE" == "rest" ]]; then
  configure_rest_runtime
  [[ -n "$REST_URL" ]] || die "--rest-url must not be empty when --mode rest is selected."
fi

resolve_repo_dir
PLUGIN_SOURCE="$(find_plugin_source || true)"
SKILL_SOURCE="$(find_skill_source || true)"
[[ -n "$PLUGIN_SOURCE" || "$INSTALL_CODEX" != "1" ]] || die "Could not find plugin source. Run from a PAM-OS checkout or pass --source."
[[ -n "$SKILL_SOURCE" ]] || die "Could not find skill source. Run from a PAM-OS checkout or pass --source."

if [[ "$INSTALL_CODEX" == "1" ]]; then
  if [[ -e "$PLUGIN_DIR" ]]; then
    if confirm "Replace existing Codex plugin at $PLUGIN_DIR?" "y"; then
      rm -rf "$PLUGIN_DIR"
    else
      warn "Skipped Codex plugin install."
      INSTALL_CODEX=0
    fi
  fi
  if [[ "$INSTALL_CODEX" == "1" ]]; then
    info "Installing Codex plugin from $PLUGIN_SOURCE"
    copy_dir "$PLUGIN_SOURCE" "$PLUGIN_DIR"
    write_bundled_skill_config "$PLUGIN_DIR"
    remove_legacy_codex_config "$CODEX_CONFIG"
    if [[ "$WRITE_GLOBAL_SKILL" == "1" ]]; then
      install_skill "$PLUGIN_DIR/skills/$PLUGIN_NAME" "$CODEX_SKILL_DIR" "Codex global skill"
    fi
    if [[ "$WRITE_MARKETPLACE" == "1" ]]; then
      write_marketplace_config "$MARKETPLACE_PATH"
      info "Updated marketplace: $MARKETPLACE_PATH"
    fi
  fi
fi

if [[ "$INSTALL_CLAUDE" == "1" ]]; then
  install_skill "$SKILL_SOURCE" "$CLAUDE_SKILL_DIR" "Claude Code skill"
fi

if [[ "$INSTALL_OPENCODE" == "1" ]]; then
  if [[ "$INSTALL_CLAUDE" != "1" ]]; then
    install_skill "$SKILL_SOURCE" "$CLAUDE_SKILL_DIR" "OpenCode Claude-compatible skill"
  fi
  append_guidance "$OPENCODE_AGENTS_FILE" "$CLAUDE_SKILL_DIR/SKILL.md"
  info "Updated OpenCode guidance: $OPENCODE_AGENTS_FILE"
fi

if [[ "$INSTALL_HERMES" == "1" ]]; then
  install_skill "$SKILL_SOURCE" "$HERMES_SKILL_DIR" "Hermes skill"
  append_guidance "$HERMES_AGENTS_FILE" "$HERMES_SKILL_DIR/SKILL.md"
  info "Updated Hermes guidance: $HERMES_AGENTS_FILE"
fi

info "Install complete"
cat <<SUMMARY

Runtime:
  mode: $INSTALL_MODE
  REST URL: $REST_URL

Skill paths:
  $CODEX_SKILL_DIR
  $CLAUDE_SKILL_DIR
  $HERMES_SKILL_DIR

Managed/runtime repo:
  $REPO_DIR

PAM-OS supports CLI and REST adapters only.

SUMMARY
