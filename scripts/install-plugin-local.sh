#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALLER="$REPO_ROOT/scripts/install-plugin.sh"
PLUGIN_NAME="${PAM_OS_PLUGIN_NAME:-pam-os-memory}"
SOURCE_DIR="$REPO_ROOT/plugins/$PLUGIN_NAME"

ASSUME_YES=1
FORWARD_ARGS=()

usage() {
  cat <<USAGE
PAM-OS local plugin installer

Usage:
  scripts/install-plugin-local.sh [installer-options]

Installs the REST-only pam-os-memory integration from this checkout.

Defaults passed to scripts/install-plugin.sh:
  --source "$SOURCE_DIR"
  --repo-dir "$REPO_ROOT"
  --no-refresh
  --yes

Options handled by this wrapper:
  --interactive      Allow target and REST configuration prompts.
  --yes              Non-interactive install; defaults to the Codex target.
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
      shift
      ;;
    --yes|--non-interactive)
      ASSUME_YES=1
      shift
      ;;
    --installer-help)
      exec bash "$INSTALLER" --help
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      FORWARD_ARGS+=("$1")
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

ARGS=(
  "--source" "$SOURCE_DIR"
  "--repo-dir" "$REPO_ROOT"
  "--no-refresh"
)

if [[ "$ASSUME_YES" == "1" ]]; then
  ARGS+=("--yes")
fi

exec bash "$INSTALLER" "${ARGS[@]}" "${FORWARD_ARGS[@]}"
