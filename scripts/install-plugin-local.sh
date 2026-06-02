#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALLER="$REPO_ROOT/scripts/install-plugin.sh"
PLUGIN_NAME="${PAM_OS_PLUGIN_NAME:-pam-os-memory}"
SOURCE_DIR="$REPO_ROOT/plugins/$PLUGIN_NAME"

ASSUME_YES=1
HAS_TARGET=0
PROMPT_TARGET=1
PASSTHROUGH=()
SELECTED_TARGETS=()

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

can_prompt() {
  [[ -r /dev/tty && -w /dev/tty ]] || [[ -t 0 && -t 1 ]]
}

ui_printf() {
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    printf "$@" > /dev/tty
  else
    printf "$@" >&2
  fi
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

select_install_targets() {
  local selection item valid

  ui_printf '\nInstall targets:\n'
  ui_printf '  1) codex     - Codex plugin + MCP + global skill fallback\n'
  ui_printf '  2) claude    - Claude Code global skill + MCP\n'
  ui_printf '  3) opencode  - OpenCode guidance\n'
  ui_printf '  4) hermes    - Hermes MCP config + guidance\n'
  ui_printf '  5) all\n'
  ui_printf '\nSelect one or more targets, separated by commas or spaces.\n'

  while true; do
    if ! read_user selection 'Selection [1]: '; then
      die "Interactive target selection requires a TTY. Re-run with --target, --all, or --yes."
    fi

    selection="${selection:-1}"
    selection="${selection//,/ }"
    SELECTED_TARGETS=()
    valid=1

    for item in $selection; do
      case "$item" in
        1|codex|Codex|CODEX)
          SELECTED_TARGETS+=("codex")
          ;;
        2|claude|Claude|CLAUDE|claude-code|Claude-Code)
          SELECTED_TARGETS+=("claude")
          ;;
        3|opencode|OpenCode|OPENCODE)
          SELECTED_TARGETS+=("opencode")
          ;;
        4|hermes|Hermes|HERMES)
          SELECTED_TARGETS+=("hermes")
          ;;
        5|all|All|ALL)
          SELECTED_TARGETS=("all")
          ;;
        *)
          ui_printf 'Unknown target: %s\n' "$item"
          valid=0
          break
          ;;
      esac
    done

    if [[ "$valid" == "1" && "${#SELECTED_TARGETS[@]}" -gt 0 ]]; then
      return 0
    fi

    ui_printf 'Please select at least one valid target.\n'
  done
}

usage() {
  cat <<USAGE
PAM-OS local plugin installer

Usage:
  scripts/install-plugin-local.sh [installer-options]

Installs the pam-os-memory plugin from this local checkout instead of fetching
from GitHub. By default it asks which target to install, then accepts replace
prompts non-interactively for fast local debugging.

Defaults passed to scripts/install-plugin.sh:
  --source "$SOURCE_DIR"
  --repo-dir "$REPO_ROOT"
  --no-refresh
  --yes

If no TTY is available and no target is provided, it falls back to --target codex.

Examples:
  scripts/install-plugin-local.sh
  scripts/install-plugin-local.sh --all
  scripts/install-plugin-local.sh --target claude
  scripts/install-plugin-local.sh --interactive
  scripts/install-plugin-local.sh --yes
  scripts/install-plugin-local.sh --no-init

Options handled by this wrapper:
  --interactive      Do not pass --yes; allow the installer to prompt.
  --yes              Fully non-interactive legacy default: install codex.
  --non-interactive  Alias for --yes.
  --installer-help   Show scripts/install-plugin.sh help.
  -h, --help         Show this help.

All other options are forwarded to scripts/install-plugin.sh.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interactive)
      ASSUME_YES=0
      PROMPT_TARGET=0
      shift
      ;;
    --yes|--non-interactive)
      ASSUME_YES=1
      PROMPT_TARGET=0
      shift
      ;;
    --installer-help)
      exec bash "$INSTALLER" --help
      ;;
    --target)
      [[ $# -ge 2 ]] || die "--target requires a value"
      HAS_TARGET=1
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --codex|--claude|--opencode|--hermes|--all)
      HAS_TARGET=1
      PASSTHROUGH+=("$1")
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      PASSTHROUGH+=("$1")
      shift
      ;;
  esac
done

[[ -f "$INSTALLER" ]] || {
  printf 'error: installer not found: %s\n' "$INSTALLER" >&2
  exit 1
}

[[ -f "$SOURCE_DIR/.codex-plugin/plugin.json" ]] || {
  printf 'error: plugin source not found: %s\n' "$SOURCE_DIR" >&2
  exit 1
}

args=(
  "--source" "$SOURCE_DIR"
  "--repo-dir" "$REPO_ROOT"
  "--no-refresh"
)

if [[ "$HAS_TARGET" != "1" ]]; then
  if [[ "$PROMPT_TARGET" == "1" && can_prompt ]]; then
    select_install_targets
    for target in "${SELECTED_TARGETS[@]}"; do
      args+=("--target" "$target")
    done
  elif [[ "$ASSUME_YES" == "1" ]]; then
    args+=("--target" "codex")
  fi
fi

if [[ "$ASSUME_YES" == "1" ]]; then
  args+=("--yes")
fi

exec bash "$INSTALLER" "${args[@]}" "${PASSTHROUGH[@]}"
