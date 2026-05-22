#!/usr/bin/env bash
set -Eeuo pipefail

PLUGIN_NAME="${PAM_OS_PLUGIN_NAME:-pam-os-memory}"
DEFAULT_REPO_DIR="${PAM_OS_REPO_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/pam-os/repo}"
DEFAULT_DB_PATH="${PAM_OS_DB:-${PAM_OS_DB_PATH:-$HOME/.pam-os/memory.sqlite3}}"
DEFAULT_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
DEFAULT_PLUGIN_DIR="$HOME/plugins/$PLUGIN_NAME"
DEFAULT_MARKETPLACE_PATH="$HOME/.agents/plugins/marketplace.json"
DEFAULT_CODEX_CONFIG="$DEFAULT_CODEX_HOME/config.toml"
MCP_SERVER_NAME="pam_os_memory"

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_SOURCE" ]]; then
  SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
else
  SCRIPT_DIR=""
fi
WORK_DIR="$(pwd)"

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
PAM-OS Codex plugin installer

Usage:
  ./scripts/install-codex-plugin.sh [options]

Options:
  --plugin-dir DIR      Destination plugin dir. Default: ~/plugins/pam-os-memory.
  --marketplace PATH    Personal marketplace path. Default: ~/.agents/plugins/marketplace.json.
  --codex-config PATH   Codex config.toml path. Default: ~/.codex/config.toml.
  --repo-dir DIR        PAM-OS repo used by the MCP server. Default: ~/.local/share/pam-os/repo.
  --db PATH             PAM-OS SQLite database path. Default: ~/.pam-os/memory.sqlite3.
  --python VERSION      Python version for uv run --python. Default: 3.12.
  --source DIR          Existing pam-os-memory plugin source directory.
  --skip-marketplace    Do not create or update the personal plugin marketplace entry.
  --skip-mcp-config     Do not register the MCP server in Codex config.toml.
  --yes                 Replace an existing plugin install without prompting.
  -h, --help            Show this help.

The installed plugin writes a marketplace entry for Codex plugin discovery and,
unless --skip-mcp-config is passed, registers a stdio MCP server that runs:
  uv --directory <repo-dir> run --python <version> memory --db <db> mcp
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

confirm() {
  local prompt="$1"
  local default="${2:-y}"
  local reply suffix

  if [[ "$ASSUME_YES" == "1" ]]; then
    [[ "$default" == "y" ]]
    return
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

abs_path() {
  local path="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$path"
  else
    (cd "$(dirname "$path")" && printf '%s/%s\n' "$(pwd)" "$(basename "$path")")
  fi
}

find_plugin_source() {
  local candidate
  local roots=(
    "$SOURCE_DIR"
    "$WORK_DIR/plugins/$PLUGIN_NAME"
  )
  if [[ -n "$SCRIPT_DIR" ]]; then
    roots+=("$SCRIPT_DIR/../plugins/$PLUGIN_NAME")
  fi
  for candidate in "${roots[@]}"; do
    if [[ -n "$candidate" && -f "$candidate/.codex-plugin/plugin.json" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_repo_dir() {
  if [[ -f "$REPO_DIR/pyproject.toml" && -d "$REPO_DIR/src/pam_os" ]]; then
    return 0
  fi
  if [[ -f "$WORK_DIR/pyproject.toml" && -d "$WORK_DIR/src/pam_os" ]]; then
    REPO_DIR="$(abs_path "$WORK_DIR")"
    return 0
  fi
  if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../pyproject.toml" && -d "$SCRIPT_DIR/../src/pam_os" ]]; then
    REPO_DIR="$(abs_path "$SCRIPT_DIR/..")"
    return 0
  fi
  die "Could not find a PAM-OS repo for MCP mode: $REPO_DIR"
}

write_mcp_config() {
  local path="$1"
  python3 - "$path" "$REPO_DIR" "$PYTHON_VERSION" "$DB_PATH" <<'JSON_WRITER'
import json
import sys
from pathlib import Path

path, repo_dir, python_version, db_path = sys.argv[1:]
payload = {
    "mcpServers": {
        "pam-os-memory": {
            "command": "uv",
            "args": [
                "--directory",
                repo_dir,
                "run",
                "--python",
                python_version,
                "memory",
                "--db",
                db_path,
                "mcp",
            ],
            "env": {},
        }
    }
}
Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
JSON_WRITER
}


write_marketplace_config() {
  local path="$1"
  python3 - "$path" "$PLUGIN_NAME" <<'JSON_WRITER'
import json
import sys
from pathlib import Path

path, plugin_name = sys.argv[1:]
marketplace_path = Path(path).expanduser()
if marketplace_path.exists():
    payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
else:
    payload = {
        "name": "personal",
        "interface": {
            "displayName": "Personal",
        },
        "plugins": [],
    }

if not isinstance(payload, dict):
    raise SystemExit(f"{marketplace_path} must contain a JSON object")
plugins = payload.setdefault("plugins", [])
if not isinstance(plugins, list):
    raise SystemExit(f"{marketplace_path} field 'plugins' must be an array")

entry = {
    "name": plugin_name,
    "source": {
        "source": "local",
        "path": f"./plugins/{plugin_name}",
    },
    "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    },
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
JSON_WRITER
}

write_codex_mcp_config() {
  local path="$1"
  python3 - "$path" "$REPO_DIR" "$PYTHON_VERSION" "$DB_PATH" "$MCP_SERVER_NAME" <<'TOML_WRITER'
import sys
from pathlib import Path

path, repo_dir, python_version, db_path, server_name = sys.argv[1:]
config_path = Path(path).expanduser()
server_header = f"[mcp_servers.{server_name}]"
block_lines = [
    server_header,
    'command = "uv"',
    "args = [",
    f'  "--directory", "{repo_dir}",',
    '  "run",',
    f'  "--python", "{python_version}",',
    '  "memory",',
    '  "--db",',
    f'  "{db_path}",',
    '  "mcp"',
    "]",
    'description = "PAM-OS local-first long-term memory"',
    "",
]

if config_path.exists():
    lines = config_path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

output = []
index = 0
replaced = False
while index < len(lines):
    line = lines[index]
    if line.strip() == server_header:
        output.extend(block_lines)
        replaced = True
        index += 1
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                break
            index += 1
        continue
    output.append(line)
    index += 1

if not replaced:
    if output and output[-1].strip():
        output.append("")
    if not any(line.strip() == "[mcp_servers]" for line in output):
        output.append("[mcp_servers]")
        output.append("")
    output.extend(block_lines)

config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
TOML_WRITER
}

ASSUME_YES=0
PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
MARKETPLACE_PATH="$DEFAULT_MARKETPLACE_PATH"
CODEX_CONFIG="$DEFAULT_CODEX_CONFIG"
REPO_DIR="$DEFAULT_REPO_DIR"
DB_PATH="$DEFAULT_DB_PATH"
PYTHON_VERSION="${PAM_OS_CLI_PYTHON:-3.12}"
SOURCE_DIR=""
WRITE_MARKETPLACE=1
WRITE_MCP_CONFIG=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plugin-dir)
      PLUGIN_DIR="${2:-}"
      shift 2
      ;;
    --marketplace)
      MARKETPLACE_PATH="${2:-}"
      shift 2
      ;;
    --codex-config)
      CODEX_CONFIG="${2:-}"
      shift 2
      ;;
    --repo-dir)
      REPO_DIR="${2:-}"
      shift 2
      ;;
    --db)
      DB_PATH="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_VERSION="${2:-}"
      shift 2
      ;;
    --source)
      SOURCE_DIR="${2:-}"
      shift 2
      ;;
    --skip-marketplace)
      WRITE_MARKETPLACE=0
      shift
      ;;
    --skip-mcp-config)
      WRITE_MCP_CONFIG=0
      shift
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

[[ -n "$PLUGIN_DIR" ]] || die "--plugin-dir must not be empty."
[[ -n "$MARKETPLACE_PATH" ]] || die "--marketplace must not be empty."
[[ -n "$CODEX_CONFIG" ]] || die "--codex-config must not be empty."
[[ -n "$REPO_DIR" ]] || die "--repo-dir must not be empty."
[[ -n "$DB_PATH" ]] || die "--db must not be empty."
[[ -n "$PYTHON_VERSION" ]] || die "--python must not be empty."

if [[ "$ASSUME_YES" == "0" && ! can_prompt ]]; then
  die "Interactive install requires a TTY. Use --yes for non-interactive installs."
fi

ensure_repo_dir
SOURCE="$(find_plugin_source || true)"
[[ -n "$SOURCE" ]] || die "Could not find plugin source. Run from a PAM-OS checkout or pass --source."

if [[ -e "$PLUGIN_DIR" ]]; then
  if confirm "Replace existing Codex plugin at $PLUGIN_DIR?" "y"; then
    rm -rf "$PLUGIN_DIR"
  else
    warn "Skipped install."
    exit 0
  fi
fi

info "Installing Codex plugin from $SOURCE"
mkdir -p "$(dirname "$PLUGIN_DIR")"
cp -R "$SOURCE" "$PLUGIN_DIR"
write_mcp_config "$PLUGIN_DIR/.mcp.json"

if [[ "$WRITE_MARKETPLACE" == "1" ]]; then
  write_marketplace_config "$MARKETPLACE_PATH"
  info "Updated marketplace: $MARKETPLACE_PATH"
fi

if [[ "$WRITE_MCP_CONFIG" == "1" ]]; then
  write_codex_mcp_config "$CODEX_CONFIG"
  info "Registered MCP server '$MCP_SERVER_NAME' in $CODEX_CONFIG"
fi

info "Installed: $PLUGIN_DIR"
cat <<SUMMARY

Next checks:
  1. Restart Codex.
  2. Open the local plugin marketplace entry if your Codex UI supports plugins.
  3. Ask Codex to list MCP tools and verify the pam_os_memory server is present.

Marketplace:
  $MARKETPLACE_PATH

MCP command:
  uv --directory $REPO_DIR run --python $PYTHON_VERSION memory --db $DB_PATH mcp

SUMMARY
