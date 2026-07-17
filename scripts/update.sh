#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REPO_URL="${PAM_OS_REPO_URL:-https://github.com/danzhewuju/PAM-OS.git}"
DEFAULT_REPO_DIR="${PAM_OS_REPO_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/pam-os/repo}"
DEFAULT_REF="${PAM_OS_REPO_REF:-latest}"

REPO_URL="$DEFAULT_REPO_URL"
REPO_DIR="$DEFAULT_REPO_DIR"
REF="$DEFAULT_REF"
INSTALL_ARGS=(--yes)

info() { printf '[pam-os] %s\n' "$*"; }
warn() { printf '[pam-os] warning: %s\n' "$*" >&2; }
die() { printf '[pam-os] error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
PAM-OS updater

Usage:
  scripts/update.sh [options] [-- installer-options]

Options:
  --repo-url URL     Git repository URL. Default: https://github.com/danzhewuju/PAM-OS.git
  --repo-dir DIR     Managed checkout directory. Default: ~/.local/share/pam-os/repo
  --ref REF          Git ref to install. Default: latest release tag, falling back to master
  --yes              Pass --yes to the installer. Default.
  --help             Show this help.

Examples:
  curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/update.sh | bash
  scripts/update.sh --ref <version-tag> -- --codex --yes
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --repo-dir)
      REPO_DIR="${2:-}"
      shift 2
      ;;
    --ref)
      REF="${2:-}"
      shift 2
      ;;
    --yes)
      INSTALL_ARGS=(--yes)
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      INSTALL_ARGS=("$@")
      break
      ;;
    *)
      INSTALL_ARGS+=("$1")
      shift
      ;;
  esac
done

[[ -n "$REPO_URL" ]] || die "--repo-url must not be empty"
[[ -n "$REPO_DIR" ]] || die "--repo-dir must not be empty"
[[ -n "$REF" ]] || die "--ref must not be empty"
command -v git >/dev/null 2>&1 || die "git is required"

resolve_latest_ref() {
  local latest
  latest="$(git ls-remote --tags --sort=-v:refname "$REPO_URL" 'v*' 2>/dev/null \
    | awk -F/ '{print $NF}' \
    | sed 's/\^{}//' \
    | grep -E '^v?[0-9]+(\.[0-9]+)*$' \
    | head -n 1 || true)"
  if [[ -n "$latest" ]]; then
    printf '%s\n' "$latest"
  else
    printf 'master\n'
  fi
}

if [[ "$REF" == "latest" ]]; then
  REF="$(resolve_latest_ref)"
fi

info "Updating managed checkout"
info "Repo: $REPO_URL"
info "Ref:  $REF"
info "Dir:  $REPO_DIR"

mkdir -p "$(dirname "$REPO_DIR")"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch --tags --prune origin >/dev/null
  git -C "$REPO_DIR" checkout "$REF" >/dev/null
  git -C "$REPO_DIR" pull --ff-only origin "$REF" >/dev/null 2>&1 || true
else
  if [[ -e "$REPO_DIR" ]]; then
    die "--repo-dir exists but is not a git checkout: $REPO_DIR"
  fi
  git clone --depth 1 --branch "$REF" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 || {
    git clone --depth 1 "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1
    git -C "$REPO_DIR" checkout "$REF" >/dev/null
  }
fi

installer_path="$REPO_DIR/scripts/install-plugin.sh"
[[ -f "$installer_path" ]] || die "installer not found: $installer_path"

info "Running installer: $installer_path ${INSTALL_ARGS[*]}"
bash "$installer_path" --repo-dir "$REPO_DIR" --repo-url "$REPO_URL" --ref "$REF" "${INSTALL_ARGS[@]}"
info "Update complete"
