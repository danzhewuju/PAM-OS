#!/usr/bin/env bash
set -Eeuo pipefail

SKILL_NAME="${PAM_OS_SKILL_NAME:-pam-os-memory}"
DEFAULT_REPO_URL="${PAM_OS_REPO_URL:-https://github.com/danzhewuju/PAM-OS.git}"
DEFAULT_REPO_REF="${PAM_OS_REPO_REF:-main}"

CODEX_DEFAULT_DIR="${CODEX_HOME:-$HOME/.codex}/skills/$SKILL_NAME"
CLAUDE_DEFAULT_DIR="$HOME/.claude/skills/$SKILL_NAME"
OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
OPENCODE_AGENTS_FILE="$OPENCODE_CONFIG_DIR/AGENTS.md"
CC_SWITCH_DEFAULT_DIR="${CC_SWITCH_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/cc-switch}/skills/$SKILL_NAME"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(pwd)"
TMP_DIR=""

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

cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

usage() {
  cat <<USAGE
PAM-OS skill installer

Usage:
  ./scripts/install-skill.sh [options]

Options:
  --all                 Install Codex, Claude Code, OpenCode, and CC Switch targets.
  --codex               Install the Codex global skill.
  --claude              Install the Claude Code global skill.
  --opencode            Install OpenCode compatibility.
  --cc-switch           Install the CC Switch export bundle.
  --mode cli|rest       Set skill runtime mode. Default: prompt, then cli.
  --repo-url URL        Git repository used when the skill template is not local.
  --ref REF             Git ref used when downloading/cloning. Default: main.
  --source DIR          Use an existing pam-os-memory skill directory.
  --yes                 Accept safe defaults and overwrite by creating backups.
  --non-interactive     Same as --yes.
  -h, --help            Show this help.

Environment:
  PAM_OS_REPO_URL       Default repo URL. Current default: $DEFAULT_REPO_URL
  PAM_OS_REPO_REF       Default repo ref. Current default: $DEFAULT_REPO_REF
  CODEX_HOME            Codex home. Default: ~/.codex
  CC_SWITCH_HOME        CC Switch home. Default: ~/.config/cc-switch

The installer defaults to user-global directories and confirms important writes.
USAGE
}

can_prompt() {
  [[ -r /dev/tty && -w /dev/tty ]] || [[ -t 0 && -t 1 ]]
}

read_user() {
  local __result_var="$1"
  local prompt="$2"

  if [[ -r /dev/tty ]]; then
    read -r -p "$prompt" "$__result_var" < /dev/tty
  else
    read -r -p "$prompt" "$__result_var"
  fi
}

read_secret_user() {
  local __result_var="$1"
  local prompt="$2"

  if [[ -r /dev/tty ]]; then
    read -r -s -p "$prompt" "$__result_var" < /dev/tty
    printf '\n' > /dev/tty
  else
    read -r -s -p "$prompt" "$__result_var"
    printf '\n' >&2
  fi
}

confirm() {
  local prompt="$1"
  local default="${2:-y}"
  local reply suffix

  if [[ "$ASSUME_YES" == "1" ]]; then
    return 0
  fi

  if [[ "$default" == "y" ]]; then
    suffix="[Y/n]"
  else
    suffix="[y/N]"
  fi

  while true; do
    read_user reply "$prompt $suffix "
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
  local reply

  if [[ "$ASSUME_YES" == "1" ]]; then
    printf '%s' "$default"
    return 0
  fi

  read_user reply "$prompt [$default]: "
  printf '%s' "${reply:-$default}"
}

prompt_secret() {
  local prompt="$1"
  local reply

  if [[ "$ASSUME_YES" == "1" ]]; then
    printf ''
    return 0
  fi

  read_secret_user reply "$prompt (leave empty for none): "
  printf '%s' "$reply"
}

timestamp() {
  date '+%Y%m%d-%H%M%S'
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
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

copy_dir() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp -R "$src" "$dest"
}

prepare_dest() {
  local dest="$1"

  if [[ ! -e "$dest" ]]; then
    return 0
  fi

  if [[ "$ASSUME_YES" != "1" ]]; then
    printf '\nExisting installation found:\n  %s\n' "$dest"
    printf 'Choose what to do:\n'
    printf '  1) backup and replace\n'
    printf '  2) skip this target\n'
    printf '  3) abort\n'
    local choice
    read_user choice 'Selection [1]: '
    choice="${choice:-1}"
    case "$choice" in
      1) ;;
      2) return 1 ;;
      3) die "Aborted by user." ;;
      *) die "Invalid selection: $choice" ;;
    esac
  fi

  local backup="${dest}.bak.$(timestamp)"
  info "Backing up $dest -> $backup"
  mv "$dest" "$backup"
  return 0
}

install_skill_dir() {
  local src="$1"
  local dest="$2"
  local label="$3"

  if ! prepare_dest "$dest"; then
    warn "Skipped $label."
    return 0
  fi

  info "Installing $label"
  copy_dir "$src" "$dest"
  write_skill_config "$dest/config.toml"
  printf 'Installed: %s\n' "$dest"
}

find_skill_source() {
  local candidate
  local roots=(
    "$SOURCE_DIR"
    "$WORK_DIR/skills/$SKILL_NAME"
    "$SCRIPT_DIR/../skills/$SKILL_NAME"
    "$WORK_DIR/.agents/skills/$SKILL_NAME"
    "$WORK_DIR/.claude/skills/$SKILL_NAME"
    "$SCRIPT_DIR/../.agents/skills/$SKILL_NAME"
    "$SCRIPT_DIR/../.claude/skills/$SKILL_NAME"
    "$SCRIPT_DIR/.agents/skills/$SKILL_NAME"
    "$SCRIPT_DIR/.claude/skills/$SKILL_NAME"
  )

  for candidate in "${roots[@]}"; do
    if [[ -n "$candidate" && -f "$candidate/SKILL.md" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done

  return 1
}

download_repo_source() {
  local repo_url="$1"
  local ref="$2"

  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pam-os-skill.XXXXXX")"
  local repo_dir="$TMP_DIR/repo"

  if command -v git >/dev/null 2>&1; then
    info "Fetching PAM-OS skill template from $repo_url ($ref)"
    git clone --depth 1 --branch "$ref" "$repo_url" "$repo_dir" >/dev/null 2>&1 || {
      warn "Branch clone failed; trying default branch."
      git clone --depth 1 "$repo_url" "$repo_dir" >/dev/null 2>&1 || die "Could not clone $repo_url"
    }
  else
    die "Could not find a local skill template and git is not installed. Re-run from a PAM-OS checkout or install git."
  fi

  if [[ -f "$repo_dir/skills/$SKILL_NAME/SKILL.md" ]]; then
    printf '%s\n' "$repo_dir/skills/$SKILL_NAME"
  elif [[ -f "$repo_dir/.agents/skills/$SKILL_NAME/SKILL.md" ]]; then
    printf '%s\n' "$repo_dir/.agents/skills/$SKILL_NAME"
  elif [[ -f "$repo_dir/.claude/skills/$SKILL_NAME/SKILL.md" ]]; then
    printf '%s\n' "$repo_dir/.claude/skills/$SKILL_NAME"
  else
    die "Downloaded repository does not contain $SKILL_NAME."
  fi
}

write_skill_config() {
  local path="$1"
  local escaped_url escaped_user escaped_pass escaped_python escaped_command

  escaped_url="$(toml_escape "$REST_URL")"
  escaped_user="$(toml_escape "$REST_USERNAME")"
  escaped_pass="$(toml_escape "$REST_PASSWORD")"
  escaped_python="$(toml_escape "$CLI_PYTHON")"
  escaped_command="$(toml_escape "$CLI_COMMAND")"

  cat > "$path" <<CONFIG
# PAM-OS skill runtime mode.
# Default is CLI. Change mode to "rest" when the REST server is running.

mode = "$INSTALL_MODE"

[cli]
python = "$escaped_python"
command = "$escaped_command"

[rest]
url = "$escaped_url"
username = "$escaped_user"
password = "$escaped_pass"
CONFIG
}

append_managed_block() {
  local file="$1"
  local start='<!-- PAM-OS memory skill: begin -->'
  local end='<!-- PAM-OS memory skill: end -->'
  local tmp

  mkdir -p "$(dirname "$file")"
  if [[ -f "$file" ]]; then
    local backup="${file}.bak.$(timestamp)"
    info "Backing up $file -> $backup"
    cp "$file" "$backup"
  fi

  tmp="$(mktemp "${TMPDIR:-/tmp}/pam-os-agents.XXXXXX")"

  if [[ -f "$file" ]]; then
    awk -v start="$start" -v end="$end" '
      $0 == start {skip=1; next}
      $0 == end {skip=0; next}
      skip != 1 {print}
    ' "$file" > "$tmp"
  else
    : > "$tmp"
  fi

  {
    if [[ -s "$tmp" ]]; then
      printf '\n'
    fi
    printf '%s\n' "$start"
    printf '## PAM-OS Memory\n\n'
    printf 'Use PAM-OS as local long-term memory when a task depends on user preferences, project history, prior decisions, long-term goals, answer style, or an explicit request to remember something.\n\n'
    printf 'If the pam-os-memory skill is available, use it. Otherwise read the installed skill instructions from `%s`.\n\n' "$CLAUDE_DEFAULT_DIR/SKILL.md"
    printf 'Do not store secrets or sensitive details unless the user explicitly asks to remember them.\n'
    printf '%s\n' "$end"
  } >> "$tmp"

  mv "$tmp" "$file"
}

install_opencode() {
  local src="$1"

  info "Installing OpenCode compatibility"
  if [[ "$INSTALL_CLAUDE" == "1" ]]; then
    info "Claude-compatible skill target is already handled by the Claude Code install."
  else
    install_skill_dir "$src" "$CLAUDE_DEFAULT_DIR" "OpenCode Claude-compatible skill (~/.claude/skills)"
  fi

  if confirm "Add/update PAM-OS guidance in $OPENCODE_AGENTS_FILE?" "y"; then
    append_managed_block "$OPENCODE_AGENTS_FILE"
    printf 'Updated: %s\n' "$OPENCODE_AGENTS_FILE"
  else
    warn "Skipped OpenCode AGENTS.md guidance."
  fi
}

print_summary() {
  cat <<SUMMARY

Done.

Next checks:
  Codex:       restart Codex, then ask "List available skills" or "Use \$pam-os-memory."
  Claude Code: run "claude" and ask "List available skills" or invoke "/pam-os-memory".
  OpenCode:    restart opencode; it can read ~/.config/opencode/AGENTS.md and Claude-compatible skills.
  CC Switch:   import or point CC Switch to the installed bundle directory if its UI asks for a skill path.

PAM-OS runtime:
  mode:        $INSTALL_MODE
  CLI command: uv run --python $CLI_PYTHON $CLI_COMMAND prepare "<task>" --json
  REST URL:    $REST_URL

SUMMARY
}

ASSUME_YES=0
INSTALL_CODEX=0
INSTALL_CLAUDE=0
INSTALL_OPENCODE=0
INSTALL_CC_SWITCH=0
MODE_ARG=""
REPO_URL="$DEFAULT_REPO_URL"
REPO_REF="$DEFAULT_REPO_REF"
SOURCE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      INSTALL_CODEX=1
      INSTALL_CLAUDE=1
      INSTALL_OPENCODE=1
      INSTALL_CC_SWITCH=1
      shift
      ;;
    --codex)
      INSTALL_CODEX=1
      shift
      ;;
    --claude)
      INSTALL_CLAUDE=1
      shift
      ;;
    --opencode)
      INSTALL_OPENCODE=1
      shift
      ;;
    --cc-switch)
      INSTALL_CC_SWITCH=1
      shift
      ;;
    --mode)
      MODE_ARG="${2:-}"
      shift 2
      ;;
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --ref)
      REPO_REF="${2:-}"
      shift 2
      ;;
    --source)
      SOURCE_DIR="${2:-}"
      shift 2
      ;;
    --yes|--non-interactive)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

if [[ -n "$MODE_ARG" && "$MODE_ARG" != "cli" && "$MODE_ARG" != "rest" ]]; then
  die "--mode must be cli or rest."
fi

if [[ "$ASSUME_YES" == "0" && ! can_prompt ]]; then
  die "Interactive install requires a TTY. Use --yes with explicit options for non-interactive installs."
fi

info "PAM-OS global skill installer"

if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_CC_SWITCH" == "0000" ]]; then
  if [[ "$ASSUME_YES" == "1" ]]; then
    INSTALL_CODEX=1
    INSTALL_CLAUDE=1
  else
    confirm "Install Codex global skill to $CODEX_DEFAULT_DIR?" "y" && INSTALL_CODEX=1
    confirm "Install Claude Code global skill to $CLAUDE_DEFAULT_DIR?" "y" && INSTALL_CLAUDE=1
    confirm "Install OpenCode compatibility?" "y" && INSTALL_OPENCODE=1
    confirm "Install CC Switch export bundle to $CC_SWITCH_DEFAULT_DIR?" "n" && INSTALL_CC_SWITCH=1
  fi
fi

if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_CC_SWITCH" == "0000" ]]; then
  die "No install targets selected."
fi

if [[ -z "$MODE_ARG" ]]; then
  if [[ "$ASSUME_YES" == "1" ]]; then
    INSTALL_MODE="cli"
  else
    printf '\nRuntime mode:\n'
    printf '  1) cli  - no long-running server; model runs the local memory CLI\n'
    printf '  2) rest - model calls a running PAM-OS REST server\n'
    read_user mode_choice 'Selection [1]: '
    mode_choice="${mode_choice:-1}"
    case "$mode_choice" in
      1|cli) INSTALL_MODE="cli" ;;
      2|rest) INSTALL_MODE="rest" ;;
      *) die "Invalid runtime mode: $mode_choice" ;;
    esac
  fi
else
  INSTALL_MODE="$MODE_ARG"
fi

CLI_PYTHON="$(prompt_value "Python version for uv run --python" "3.12")"
CLI_COMMAND="$(prompt_value "PAM-OS CLI command" "memory")"
REST_URL="$(prompt_value "PAM-OS REST URL" "http://127.0.0.1:8765")"
REST_USERNAME=""
REST_PASSWORD=""

if [[ "$INSTALL_MODE" == "rest" ]]; then
  if confirm "Configure REST Basic Auth credentials in skill config?" "n"; then
    REST_USERNAME="$(prompt_value "REST username" "")"
    REST_PASSWORD="$(prompt_secret "REST password")"
  fi
fi

SKILL_SOURCE="$(find_skill_source || true)"
if [[ -z "$SKILL_SOURCE" ]]; then
  REPO_URL="$(prompt_value "PAM-OS Git repository URL" "$REPO_URL")"
  REPO_REF="$(prompt_value "PAM-OS Git ref" "$REPO_REF")"
  SKILL_SOURCE="$(download_repo_source "$REPO_URL" "$REPO_REF")"
fi

[[ -f "$SKILL_SOURCE/SKILL.md" ]] || die "Skill source is invalid: $SKILL_SOURCE"
info "Using skill template: $SKILL_SOURCE"

if [[ "$INSTALL_CODEX" == "1" ]]; then
  install_skill_dir "$SKILL_SOURCE" "$CODEX_DEFAULT_DIR" "Codex global skill"
fi

if [[ "$INSTALL_CLAUDE" == "1" ]]; then
  install_skill_dir "$SKILL_SOURCE" "$CLAUDE_DEFAULT_DIR" "Claude Code global skill"
fi

if [[ "$INSTALL_OPENCODE" == "1" ]]; then
  install_opencode "$SKILL_SOURCE"
fi

if [[ "$INSTALL_CC_SWITCH" == "1" ]]; then
  install_skill_dir "$SKILL_SOURCE" "$CC_SWITCH_DEFAULT_DIR" "CC Switch export bundle"
fi

print_summary
