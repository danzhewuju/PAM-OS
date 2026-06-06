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
HAS_MODE=0
PROMPT_TARGET=1
PROMPT_MODE=1
PASSTHROUGH=()
SELECTED_TARGETS=()
SELECTED_MODE=""
REST_URL="${PAM_OS_REST_URL:-http://127.0.0.1:8765}"
REST_USERNAME="${PAM_OS_REST_USERNAME:-}"
REST_PASSWORD="${PAM_OS_REST_PASSWORD:-}"

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

prompt_value() {
  local __result_var="$1"
  local prompt="$2"
  local default="$3"
  local reply rendered_prompt

  if [[ -n "$default" ]]; then
    rendered_prompt="$prompt [$default]: "
  else
    rendered_prompt="$prompt (leave empty for none): "
  fi

  if ! read_user reply "$rendered_prompt"; then
    die "Interactive REST configuration requires a TTY. Re-run with --mode and REST options, or --yes."
  fi

  printf -v "$__result_var" '%s' "${reply:-$default}"
}

prompt_secret() {
  local __result_var="$1"
  local prompt="$2"
  local default="$3"
  local reply

  if ! read_secret_user reply "$prompt (leave empty for none): "; then
    die "Interactive REST configuration requires a TTY. Re-run with --mode and REST options, or --yes."
  fi

  printf -v "$__result_var" '%s' "${reply:-$default}"
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

select_runtime_mode() {
  local mode_choice

  ui_printf '\nRuntime mode:\n'
  ui_printf '  1) cli  - no long-running server; model runs the local memory CLI\n'
  ui_printf '  2) rest - model calls a running PAM-OS REST server\n'

  while true; do
    if ! read_user mode_choice 'Selection [1]: '; then
      die "Interactive runtime mode selection requires a TTY. Re-run with --mode cli, --mode rest, or --yes."
    fi

    mode_choice="${mode_choice:-1}"
    case "$mode_choice" in
      1|cli|CLI)
        SELECTED_MODE="cli"
        return 0
        ;;
      2|rest|REST)
        SELECTED_MODE="rest"
        prompt_value REST_URL "PAM-OS REST URL" "$REST_URL"
        prompt_value REST_USERNAME "REST username" "$REST_USERNAME"
        prompt_secret REST_PASSWORD "REST password" "$REST_PASSWORD"
        [[ -n "$REST_URL" ]] || die "REST URL must not be empty."
        return 0
        ;;
      *)
        ui_printf 'Invalid runtime mode: %s\n' "$mode_choice"
        ;;
    esac
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
  --yes              Fully non-interactive legacy default: install codex with CLI mode.
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
      PROMPT_MODE=0
      shift
      ;;
    --yes|--non-interactive)
      ASSUME_YES=1
      PROMPT_TARGET=0
      PROMPT_MODE=0
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
    --mode|--runtime)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      HAS_MODE=1
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --rest-url|--rest-username|--rest-user|--rest-password)
      [[ $# -ge 2 ]] || die "$1 requires a value"
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

if [[ "$HAS_MODE" != "1" ]]; then
  if [[ "$PROMPT_MODE" == "1" && can_prompt ]]; then
    select_runtime_mode
    args+=("--mode" "$SELECTED_MODE")
    if [[ "$SELECTED_MODE" == "rest" ]]; then
      export PAM_OS_REST_URL="$REST_URL"
      export PAM_OS_REST_USERNAME="$REST_USERNAME"
      export PAM_OS_REST_PASSWORD="$REST_PASSWORD"
    fi
  fi
fi

if [[ "$ASSUME_YES" == "1" ]]; then
  args+=("--yes")
fi

exec bash "$INSTALLER" "${args[@]}" "${PASSTHROUGH[@]}"
