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
  --repo-dir DIR        Use an existing PAM-OS repo for MCP/dev mode. Default: managed repo ~/.local/share/pam-os/repo.
  --repo-url URL        Git repository used to refresh the managed repo. Default: https://github.com/danzhewuju/PAM-OS.git.
  --ref REF             Git ref used to refresh the managed repo. Default: master.
  --no-refresh          Do not fetch or clone the managed repo before installing.
  --db PATH             PAM-OS SQLite database path. Default: ~/.pam-os/memory.sqlite3.
  --python VERSION      Python version for uv run --python. Default: 3.12.
  --source DIR          Existing pam-os-memory plugin source directory for dev/local installs.
  --codex-skill-dir DIR Install the Codex global skill fallback here. Default: ~/.codex/skills/pam-os-memory.
  --skip-marketplace    Do not create or update the personal plugin marketplace entry.
  --skip-mcp-config     Do not register the MCP server in Codex config.toml.
  --skip-global-skill   Do not install the Codex global skill fallback.
  --no-init             Skip running "memory init" after install.
  --yes                 Replace an existing plugin install without prompting.
  -h, --help            Show this help.

The default install refreshes a managed PAM-OS repo, copies the plugin from
that repo, writes a marketplace entry for Codex plugin discovery, and unless
--skip-mcp-config is passed, registers a stdio MCP server that runs:
  uv --directory <managed-repo-dir> run --python <version> memory --db <db> mcp

Pass --repo-dir or --source only for local development installs.

By default it also installs the bundled skill to ~/.codex/skills/pam-os-memory
so Codex can load the PAM-OS memory policy even before plugin UI installation
state is refreshed.
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

toml_escape() {
  printf "%s" "$1" | sed "s/\\\\/\\\\\\\\/g; s/\"/\\\"/g"
}

find_python_bin() {
  local candidate
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if command -v py >/dev/null 2>&1 && py -3 -c 'import sys' >/dev/null 2>&1; then
    printf '%s\n' 'py -3'
    return 0
  fi
  if command -v uv >/dev/null 2>&1 && uv run --python "$PYTHON_VERSION" python -c 'import sys' >/dev/null 2>&1; then
    printf 'uv run --python %s python\n' "$PYTHON_VERSION"
    return 0
  fi
  return 1
}

is_pam_repo() {
  local path="$1"
  [[ -f "$path/pyproject.toml" && -d "$path/src/pam_os" ]]
}

refresh_managed_repo() {
  if [[ "$REFRESH_REPO" != "1" ]]; then
    return 0
  fi

  if ! command -v git >/dev/null 2>&1; then
    die "git is required to refresh the managed PAM-OS repo. Re-run with --no-refresh or --repo-dir."
  fi

  if [[ -d "$REPO_DIR/.git" ]]; then
    info "Refreshing managed PAM-OS repo at $REPO_DIR ($REPO_REF)"
    git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_REF" >/dev/null
    git -C "$REPO_DIR" checkout -q FETCH_HEAD
    return 0
  fi

  if [[ -e "$REPO_DIR" ]]; then
    die "Managed repo path exists but is not a git checkout: $REPO_DIR"
  fi

  info "Cloning managed PAM-OS repo into $REPO_DIR ($REPO_REF)"
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 || {
    warn "Branch clone failed; trying default branch."
    git clone --depth 1 "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 || die "Could not clone $REPO_URL"
  }
}

infer_repo_from_source() {
  local source="$1"
  local candidate

  candidate="$(abs_path "$source/../..")"
  if is_pam_repo "$candidate"; then
    printf '%s\n' "$candidate"
    return 0
  fi

  return 1
}

resolve_repo_dir() {
  local inferred

  if [[ "$REPO_DIR_EXPLICIT" == "1" ]]; then
    [[ -e "$REPO_DIR" ]] || die "--repo-dir must point to an existing PAM-OS checkout: $REPO_DIR"
    REPO_DIR="$(abs_path "$REPO_DIR")"
    is_pam_repo "$REPO_DIR" || die "--repo-dir is not a PAM-OS checkout: $REPO_DIR"
    return 0
  fi

  if [[ -n "$SOURCE_DIR" ]]; then
    inferred="$(infer_repo_from_source "$SOURCE_DIR" || true)"
    if [[ -n "$inferred" ]]; then
      REPO_DIR="$inferred"
      REFRESH_REPO=0
      return 0
    fi
  fi

  refresh_managed_repo
  REPO_DIR="$(abs_path "$REPO_DIR")"
  is_pam_repo "$REPO_DIR" || die "Could not find a PAM-OS repo for MCP mode: $REPO_DIR"
}

find_plugin_source() {
  local candidate
  local roots=(
    "$SOURCE_DIR"
    "$REPO_DIR/plugins/$PLUGIN_NAME"
  )

  for candidate in "${roots[@]}"; do
    if [[ -n "$candidate" && -f "$candidate/.codex-plugin/plugin.json" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done

  return 1
}

write_mcp_config() {
  local path="$1"
  $PYTHON_BIN - "$path" "$REPO_DIR" "$PYTHON_VERSION" "$DB_PATH" <<'JSON_WRITER'
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


write_skill_config() {
  local path="$1"
  local escaped_python escaped_repo_dir escaped_db_path

  escaped_python="$(toml_escape "$PYTHON_VERSION")"
  escaped_repo_dir="$(toml_escape "$REPO_DIR")"
  escaped_db_path="$(toml_escape "$DB_PATH")"

  cat > "$path" <<CONFIG
# PAM-OS skill runtime mode.
# Default is CLI. The Codex plugin also registers MCP tools separately.

mode = "cli"

[cli]
python = "$escaped_python"
command = "memory"
repo_dir = "$escaped_repo_dir"
db_path = "$escaped_db_path"

[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
CONFIG
}

run_cli_init() {
  if [[ "$RUN_INIT" != "1" ]]; then
    return 0
  fi

  if ! confirm "Initialize PAM-OS memory database and warm up uv with \"memory init\"?" "y"; then
    warn "Skipped PAM-OS memory database init."
    return 0
  fi

  if ! command -v uv >/dev/null 2>&1; then
    warn "Could not run init because uv is not installed or not on PATH."
    warn "Run manually later: uv --directory $REPO_DIR run --python $PYTHON_VERSION memory --db $DB_PATH init"
    return 0
  fi

  info "Initializing PAM-OS memory database and warming uv environment"
  if uv --directory "$REPO_DIR" run --python "$PYTHON_VERSION" memory --db "$DB_PATH" init; then
    return 0
  fi

  warn "PAM-OS memory database init or uv warmup failed."
  warn "Run manually later: uv --directory $REPO_DIR run --python $PYTHON_VERSION memory --db $DB_PATH init"
}

install_codex_global_skill() {
  local src="$1"
  local dest="$2"
  local skill_src="$src/skills/$PLUGIN_NAME"

  if [[ ! -f "$skill_src/SKILL.md" ]]; then
    warn "Plugin does not contain a bundled skill at $skill_src; skipped Codex global skill install."
    return 0
  fi

  if [[ -e "$dest" ]]; then
    if confirm "Replace existing Codex global skill at $dest?" "y"; then
      rm -rf "$dest"
    else
      warn "Skipped Codex global skill install."
      return 0
    fi
  fi

  info "Installing Codex global skill fallback to $dest"
  mkdir -p "$(dirname "$dest")"
  cp -R "$skill_src" "$dest"
  write_skill_config "$dest/config.toml"
}


write_marketplace_config() {
  local path="$1"
  $PYTHON_BIN - "$path" "$PLUGIN_NAME" <<'JSON_WRITER'
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
        "installation": "INSTALLED_BY_DEFAULT",
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
  $PYTHON_BIN - "$path" "$REPO_DIR" "$PYTHON_VERSION" "$DB_PATH" "$MCP_SERVER_NAME" <<'TOML_WRITER'
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
CODEX_SKILL_DIR="$DEFAULT_CODEX_SKILL_DIR"
REPO_URL="$DEFAULT_REPO_URL"
REPO_REF="$DEFAULT_REPO_REF"
REPO_DIR="$DEFAULT_REPO_DIR"
REPO_DIR_EXPLICIT=0
REFRESH_REPO=1
DB_PATH="$DEFAULT_DB_PATH"
PYTHON_VERSION="${PAM_OS_CLI_PYTHON:-3.12}"
SOURCE_DIR=""
WRITE_MARKETPLACE=1
WRITE_MCP_CONFIG=1
WRITE_GLOBAL_SKILL=1
RUN_INIT=1
PYTHON_BIN=""

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
      REPO_DIR_EXPLICIT=1
      REFRESH_REPO=0
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
    --no-refresh)
      REFRESH_REPO=0
      shift
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
    --codex-skill-dir)
      CODEX_SKILL_DIR="${2:-}"
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
    --skip-global-skill)
      WRITE_GLOBAL_SKILL=0
      shift
      ;;
    --no-init)
      RUN_INIT=0
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
[[ -n "$CODEX_SKILL_DIR" ]] || die "--codex-skill-dir must not be empty."
[[ -n "$REPO_URL" ]] || die "--repo-url must not be empty."
[[ -n "$REPO_REF" ]] || die "--ref must not be empty."
[[ -n "$REPO_DIR" ]] || die "--repo-dir must not be empty."
[[ -n "$DB_PATH" ]] || die "--db must not be empty."
[[ -n "$PYTHON_VERSION" ]] || die "--python must not be empty."

if [[ "$ASSUME_YES" == "0" && ! can_prompt ]]; then
  die "Interactive install requires a TTY. Use --yes for non-interactive installs."
fi

PYTHON_BIN="$(find_python_bin || true)"
[[ -n "$PYTHON_BIN" ]] || die "Could not find a working Python executable for installer config writes."

resolve_repo_dir
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

if [[ "$WRITE_GLOBAL_SKILL" == "1" ]]; then
  install_codex_global_skill "$PLUGIN_DIR" "$CODEX_SKILL_DIR"
fi

if [[ "$WRITE_MARKETPLACE" == "1" ]]; then
  write_marketplace_config "$MARKETPLACE_PATH"
  info "Updated marketplace: $MARKETPLACE_PATH"
fi

if [[ "$WRITE_MCP_CONFIG" == "1" ]]; then
  write_codex_mcp_config "$CODEX_CONFIG"
  info "Registered MCP server '$MCP_SERVER_NAME' in $CODEX_CONFIG"
fi

run_cli_init

info "Installed: $PLUGIN_DIR"
cat <<SUMMARY

Next checks:
  1. Restart Codex.
  2. Ask Codex to list skills and verify pam-os-memory is present.
  3. Open the local plugin marketplace entry if your Codex UI supports plugins.
  4. Ask Codex to list MCP tools and verify the pam_os_memory server is present.
  5. If MCP tools are still empty, run the MCP command below once in a shell
     to see the uv/runtime error directly.

Marketplace:
  $MARKETPLACE_PATH

Codex global skill:
  $CODEX_SKILL_DIR

Managed/runtime repo:
  $REPO_DIR

MCP command:
  uv --directory $REPO_DIR run --python $PYTHON_VERSION memory --db $DB_PATH mcp

SUMMARY
