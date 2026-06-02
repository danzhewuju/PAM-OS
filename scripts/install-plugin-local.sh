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
PASSTHROUGH=()

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<USAGE
PAM-OS local plugin installer

Usage:
  scripts/install-plugin-local.sh [installer-options]

Installs the pam-os-memory plugin from this local checkout instead of fetching
from GitHub. By default it installs the Codex target non-interactively.

Defaults passed to scripts/install-plugin.sh:
  --source "$SOURCE_DIR"
  --repo-dir "$REPO_ROOT"
  --no-refresh
  --target codex
  --yes

Examples:
  scripts/install-plugin-local.sh
  scripts/install-plugin-local.sh --all
  scripts/install-plugin-local.sh --target claude
  scripts/install-plugin-local.sh --interactive
  scripts/install-plugin-local.sh --no-init

Options handled by this wrapper:
  --interactive      Do not pass --yes; allow the installer to prompt.
  --installer-help   Show scripts/install-plugin.sh help.
  -h, --help         Show this help.

All other options are forwarded to scripts/install-plugin.sh.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interactive)
      ASSUME_YES=0
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
  args+=("--target" "codex")
fi

if [[ "$ASSUME_YES" == "1" ]]; then
  args+=("--yes")
fi

exec bash "$INSTALLER" "${args[@]}" "${PASSTHROUGH[@]}"
