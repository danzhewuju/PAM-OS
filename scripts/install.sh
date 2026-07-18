#!/usr/bin/env bash
set -Eeuo pipefail

PLUGIN_NAME="${PAM_OS_PLUGIN_NAME:-pam-os-memory}"
DEFAULT_REPO_URL="${PAM_OS_REPO_URL:-https://github.com/danzhewuju/PAM-OS.git}"
DEFAULT_REPO_REF="${PAM_OS_REPO_REF:-master}"
DEFAULT_REPO_DIR="${PAM_OS_REPO_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/pam-os/repo}"
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
EXPECTED_API_VERSION="v1"
VERSION_CHECK_TIMEOUT_SECONDS=3

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
PAM-OS installer and updater for macOS/Linux

Usage:
  ./scripts/install.sh [options]

Options:
  --target TARGET      Install target: codex, claude, opencode, hermes, or all. Can be repeated.
  --codex             Install the Codex plugin and global skill.
  --claude            Install the Claude Code global skill.
  --opencode          Install OpenCode guidance and Claude-compatible skill.
  --hermes            Install Hermes skill and guidance.
  --all               Install all supported targets.
  --rest-url URL      PAM-OS REST server URL. Default: existing config, otherwise http://127.0.0.1:8765.
  --rest-username USER
                      REST Basic Auth username. Default: existing config, otherwise empty.
  --rest-password PASS
                      REST Basic Auth password. Default: existing config, otherwise empty.
  --rest-timeout SEC  REST request timeout. Default: existing config, otherwise 10.
  --skip-version-check
                      Do not probe server metadata during installation.
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

PAM-OS uses a REST-only adapter. This installer writes the REST skill config
and removes legacy local tool registrations it manages.
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
  local reply rendered_prompt

  if [[ "$ASSUME_YES" == "1" ]]; then
    printf '%s' "$default"
    return
  fi

  if [[ -n "$default" ]]; then
    rendered_prompt="$prompt (configured; press Enter to keep, or type a replacement): "
  else
    rendered_prompt="$prompt (leave empty for none): "
  fi
  read_secret_user reply "$rendered_prompt" || die "Interactive prompt requires a TTY. Pass explicit REST options or use --yes."
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

detect_existing_targets() {
  local detected=0

  if [[ -d "$PLUGIN_DIR" || -d "$CODEX_SKILL_DIR" ]]; then
    INSTALL_CODEX=1
    detected=1
  fi
  if [[ -d "$CLAUDE_SKILL_DIR" ]]; then
    INSTALL_CLAUDE=1
    detected=1
  fi
  if [[ -f "$OPENCODE_AGENTS_FILE" ]] && grep -Fq '<!-- PAM-OS MEMORY BEGIN -->' "$OPENCODE_AGENTS_FILE"; then
    INSTALL_OPENCODE=1
    detected=1
  fi
  if [[ -d "$HERMES_SKILL_DIR" ]]; then
    INSTALL_HERMES=1
    detected=1
  fi

  [[ "$detected" == "1" ]]
}

detect_install_action() {
  INSTALL_ACTION="install"
  if [[ "$INSTALL_CODEX" == "1" && ( -d "$PLUGIN_DIR" || -d "$CODEX_SKILL_DIR" ) ]]; then
    INSTALL_ACTION="update"
  elif [[ "$INSTALL_CLAUDE" == "1" && -d "$CLAUDE_SKILL_DIR" ]]; then
    INSTALL_ACTION="update"
  elif [[ "$INSTALL_OPENCODE" == "1" && -f "$OPENCODE_AGENTS_FILE" ]] && grep -Fq '<!-- PAM-OS MEMORY BEGIN -->' "$OPENCODE_AGENTS_FILE"; then
    INSTALL_ACTION="update"
  elif [[ "$INSTALL_HERMES" == "1" && -d "$HERMES_SKILL_DIR" ]]; then
    INSTALL_ACTION="update"
  fi
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
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

toml_unescape() {
  printf '%s' "$1" | sed 's/\\"/"/g; s/\\\\/\\/g'
}

read_rest_config() {
  local path="$1"
  local line section="" key value

  CONFIG_HAS_URL=0
  CONFIG_HAS_USERNAME=0
  CONFIG_HAS_PASSWORD=0
  CONFIG_HAS_TIMEOUT=0
  CONFIG_URL=""
  CONFIG_USERNAME=""
  CONFIG_PASSWORD=""
  CONFIG_TIMEOUT=""

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ "$line" =~ ^[[:space:]]*\[([^]]+)\][[:space:]]*$ ]]; then
      section="${BASH_REMATCH[1]}"
      continue
    fi
    [[ "$section" == "rest" ]] || continue

    if [[ "$line" =~ ^[[:space:]]*(url|username|password)[[:space:]]*=[[:space:]]*\"(.*)\"[[:space:]]*$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="$(toml_unescape "${BASH_REMATCH[2]}")"
      case "$key" in
        url) CONFIG_HAS_URL=1; CONFIG_URL="$value" ;;
        username) CONFIG_HAS_USERNAME=1; CONFIG_USERNAME="$value" ;;
        password) CONFIG_HAS_PASSWORD=1; CONFIG_PASSWORD="$value" ;;
      esac
    elif [[ "$line" =~ ^[[:space:]]*timeout_seconds[[:space:]]*=[[:space:]]*([0-9]+)[[:space:]]*$ ]]; then
      CONFIG_HAS_TIMEOUT=1
      CONFIG_TIMEOUT="${BASH_REMATCH[1]}"
    fi
  done < "$path"

  [[ "$CONFIG_HAS_URL$CONFIG_HAS_USERNAME$CONFIG_HAS_PASSWORD$CONFIG_HAS_TIMEOUT" != "0000" ]]
}

load_existing_rest_config() {
  local candidate password_status username_display
  local -a candidates=()

  if [[ "$INSTALL_CODEX" == "1" ]]; then
    candidates+=("$CODEX_SKILL_DIR/config.toml" "$PLUGIN_DIR/skills/$PLUGIN_NAME/config.toml")
  fi
  if [[ "$INSTALL_CLAUDE" == "1" || "$INSTALL_OPENCODE" == "1" ]]; then
    candidates+=("$CLAUDE_SKILL_DIR/config.toml")
  fi
  if [[ "$INSTALL_HERMES" == "1" ]]; then
    candidates+=("$HERMES_SKILL_DIR/config.toml")
  fi
  candidates+=(
    "$CODEX_SKILL_DIR/config.toml"
    "$PLUGIN_DIR/skills/$PLUGIN_NAME/config.toml"
    "$CLAUDE_SKILL_DIR/config.toml"
    "$HERMES_SKILL_DIR/config.toml"
  )

  for candidate in "${candidates[@]}"; do
    [[ -f "$candidate" ]] || continue
    read_rest_config "$candidate" || continue

    EXISTING_REST_CONFIG="$candidate"
    if [[ "$REST_URL_EXPLICIT" != "1" && "$CONFIG_HAS_URL" == "1" ]]; then
      REST_URL="$CONFIG_URL"
      REST_URL_FROM_CONFIG=1
    fi
    [[ "$REST_USERNAME_EXPLICIT" == "1" || "$CONFIG_HAS_USERNAME" != "1" ]] || REST_USERNAME="$CONFIG_USERNAME"
    [[ "$REST_PASSWORD_EXPLICIT" == "1" || "$CONFIG_HAS_PASSWORD" != "1" ]] || REST_PASSWORD="$CONFIG_PASSWORD"
    if [[ "$REST_TIMEOUT_EXPLICIT" != "1" && "$CONFIG_HAS_TIMEOUT" == "1" ]]; then
      REST_TIMEOUT_SECONDS="$CONFIG_TIMEOUT"
      REST_TIMEOUT_FROM_CONFIG=1
    fi

    username_display="${CONFIG_USERNAME:-(empty)}"
    password_status="empty"
    [[ -n "$CONFIG_PASSWORD" ]] && password_status="configured"
    info "Found existing REST config: $candidate"
    printf '    Previous REST URL: %s\n' "${CONFIG_URL:-(empty)}" >&2
    printf '    Previous REST username: %s\n' "$username_display" >&2
    printf '    Previous REST password: %s\n' "$password_status" >&2
    return 0
  done

  return 1
}

is_pam_repo() {
  local path="$1"
  [[ -f "$path/pyproject.toml" && -d "$path/src/pam_os" ]]
}

refresh_managed_repo() {
  [[ "$REFRESH_REPO" == "1" ]] || return 0
  command -v git >/dev/null 2>&1 || die "git is required to refresh the managed PAM-OS repo. Re-run with --no-refresh or --repo-dir."

  if [[ -d "$REPO_DIR/.git" ]]; then
    info "Updating managed PAM-OS checkout at $REPO_DIR ($REPO_REF)"
    git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_REF" >/dev/null
    git -C "$REPO_DIR" checkout -q FETCH_HEAD
    return 0
  fi

  [[ ! -e "$REPO_DIR" ]] || die "Managed repo path exists but is not a git checkout: $REPO_DIR"
  mkdir -p "$(dirname "$REPO_DIR")"
  info "Creating managed PAM-OS checkout at $REPO_DIR ($REPO_REF)"
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
# PAM-OS REST client configuration.

[versions]
skill = "$(toml_escape "$SKILL_VERSION")"
api = "$(toml_escape "$EXPECTED_API_VERSION")"
server = "$(toml_escape "$SERVER_VERSION")"
server_api = "$(toml_escape "$SERVER_API_VERSION")"
server_checked_at = "$(toml_escape "$SERVER_CHECKED_AT")"
status = "$(toml_escape "$VERSION_STATUS")"

[rest]
url = "$(toml_escape "$REST_URL")"
username = "$(toml_escape "$REST_USERNAME")"
password = "$(toml_escape "$REST_PASSWORD")"
timeout_seconds = $REST_TIMEOUT_SECONDS
EOF
  chmod 600 "$path"
}

read_skill_version() {
  local manifest="$REPO_DIR/plugins/$PLUGIN_NAME/.codex-plugin/plugin.json"
  [[ -f "$manifest" ]] || die "Plugin manifest not found: $manifest"
  python3 - "$manifest" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = str(manifest.get("version") or "").strip()
if not version:
    raise SystemExit("plugin manifest version is missing")
print(version)
PY
}

probe_server_version() {
  local output

  SERVER_VERSION=""
  SERVER_API_VERSION=""
  SERVER_CHECKED_AT=""
  VERSION_STATUS="not_checked"
  [[ "$CHECK_SERVER_VERSION" == "1" ]] || return 0

  SERVER_CHECKED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  output="$({
    PAM_OS_PROBE_URL="$REST_URL" \
    PAM_OS_PROBE_USERNAME="$REST_USERNAME" \
    PAM_OS_PROBE_PASSWORD="$REST_PASSWORD" \
    PAM_OS_PROBE_TIMEOUT="$VERSION_CHECK_TIMEOUT_SECONDS" \
    PAM_OS_SKILL_VERSION="$SKILL_VERSION" \
    PAM_OS_EXPECTED_API="$EXPECTED_API_VERSION" \
      python3 - <<'PY'
import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

base_url = os.environ["PAM_OS_PROBE_URL"].rstrip("/")
username = os.environ.get("PAM_OS_PROBE_USERNAME", "")
password = os.environ.get("PAM_OS_PROBE_PASSWORD", "")
timeout = float(os.environ.get("PAM_OS_PROBE_TIMEOUT", "3"))
skill_version = os.environ["PAM_OS_SKILL_VERSION"]
expected_api = os.environ["PAM_OS_EXPECTED_API"]
headers = {"Accept": "application/json"}
if username and password:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers["Authorization"] = f"Basic {token}"


def fetch(path):
    request = Request(base_url + path, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, None
    except (OSError, URLError, ValueError):
        return None, None


status, metadata = fetch("/v1/meta")
if status == 200 and isinstance(metadata, dict):
    server_version = str(metadata.get("version") or "").strip()
    server_api = str(metadata.get("api_version") or "").strip()
    comparison = "match" if server_version == skill_version and server_api == expected_api else "mismatch"
elif status in {401, 403}:
    server_version, server_api, comparison = "", "", "authentication_failed"
else:
    openapi_status, openapi = fetch("/openapi.json")
    if openapi_status == 200 and isinstance(openapi, dict):
        info = openapi.get("info") or {}
        server_version = str(info.get("version") or "").strip()
        paths = openapi.get("paths") or {}
        server_api = "v1" if any(str(path).startswith("/v1/") for path in paths) else "unversioned"
        comparison = "match" if server_version == skill_version and server_api == expected_api else "mismatch"
    elif openapi_status in {401, 403}:
        server_version, server_api, comparison = "", "", "authentication_failed"
    elif status is None and openapi_status is None:
        server_version, server_api, comparison = "", "", "unreachable"
    else:
        server_version, server_api, comparison = "", "", "unknown"

print("|".join((server_version, server_api, comparison)))
PY
  } 2>/dev/null)" || output="||unreachable"

  IFS='|' read -r SERVER_VERSION SERVER_API_VERSION VERSION_STATUS <<< "$output"
  SERVER_VERSION="${SERVER_VERSION:-}"
  SERVER_API_VERSION="${SERVER_API_VERSION:-}"
  VERSION_STATUS="${VERSION_STATUS:-unknown}"

  if [[ "$VERSION_STATUS" == "match" ]]; then
    info "Version check: skill $SKILL_VERSION / API $EXPECTED_API_VERSION matches server $SERVER_VERSION / API $SERVER_API_VERSION"
  elif [[ "$VERSION_STATUS" == "mismatch" ]]; then
    warn "Version mismatch: skill $SKILL_VERSION / API $EXPECTED_API_VERSION; server ${SERVER_VERSION:-unknown} / API ${SERVER_API_VERSION:-unknown}"
  else
    warn "Could not verify server version: $VERSION_STATUS"
  fi
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
  local stage="${dest}.pam-os-stage.$$"
  if [[ -e "$dest" ]]; then
    if confirm "Replace existing $label at $dest?" "y"; then
      :
    else
      warn "Skipped $label install."
      return 0
    fi
  fi
  info "Staging $label for $dest"
  rm -rf "$stage"
  copy_dir "$src" "$stage"
  write_skill_config "$stage/config.toml"
  rm -rf "$dest"
  mv "$stage" "$dest"
  info "Installed $label to $dest"
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
Use the installed PAM-OS skill from `{skill_path}`. Read its `config.toml` first and call the configured PAM-OS REST API.
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
INSTALL_ACTION="install"
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
REST_URL="${PAM_OS_REST_URL-}"
REST_USERNAME="${PAM_OS_REST_USERNAME-}"
REST_PASSWORD="${PAM_OS_REST_PASSWORD-}"
REST_TIMEOUT_SECONDS="${PAM_OS_REST_TIMEOUT_SECONDS-}"
REST_URL_EXPLICIT=0
REST_USERNAME_EXPLICIT=0
REST_PASSWORD_EXPLICIT=0
REST_TIMEOUT_EXPLICIT=0
REST_URL_FROM_CONFIG=0
REST_TIMEOUT_FROM_CONFIG=0
CHECK_SERVER_VERSION=1
SKILL_VERSION=""
SERVER_VERSION=""
SERVER_API_VERSION=""
SERVER_CHECKED_AT=""
VERSION_STATUS="not_checked"
[[ -n "${PAM_OS_REST_URL+x}" ]] && REST_URL_EXPLICIT=1
[[ -n "${PAM_OS_REST_USERNAME+x}" ]] && REST_USERNAME_EXPLICIT=1
[[ -n "${PAM_OS_REST_PASSWORD+x}" ]] && REST_PASSWORD_EXPLICIT=1
[[ -n "${PAM_OS_REST_TIMEOUT_SECONDS+x}" ]] && REST_TIMEOUT_EXPLICIT=1
EXISTING_REST_CONFIG=""
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
    --rest-url) REST_URL="${2:-}"; REST_URL_EXPLICIT=1; shift 2 ;;
    --rest-username|--rest-user) REST_USERNAME="${2:-}"; REST_USERNAME_EXPLICIT=1; shift 2 ;;
    --rest-password) REST_PASSWORD="${2:-}"; REST_PASSWORD_EXPLICIT=1; shift 2 ;;
    --rest-timeout) REST_TIMEOUT_SECONDS="${2:-}"; REST_TIMEOUT_EXPLICIT=1; shift 2 ;;
    --skip-version-check) CHECK_SERVER_VERSION=0; shift ;;
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

if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" == "0000" ]]; then
  if detect_existing_targets; then
    ASSUME_YES=1
    info "Detected an existing PAM-OS integration; updating all installed targets."
  elif [[ "$ASSUME_YES" == "1" ]]; then
    INSTALL_CODEX=1
  else
    can_prompt || die "Interactive install requires a TTY. Use --yes or choose targets explicitly."
    select_install_targets
  fi
fi
detect_install_action
info "Mode: $INSTALL_ACTION"

if ! load_existing_rest_config; then
  info "No existing REST config found; using installer defaults for the prompts."
fi
if [[ "$REST_URL_EXPLICIT" != "1" && "$REST_URL_FROM_CONFIG" != "1" ]]; then
  REST_URL="http://127.0.0.1:8765"
fi
if [[ "$REST_TIMEOUT_EXPLICIT" != "1" && "$REST_TIMEOUT_FROM_CONFIG" != "1" ]]; then
  REST_TIMEOUT_SECONDS="10"
fi
configure_rest_runtime
[[ -n "$REST_URL" ]] || die "--rest-url must not be empty."
[[ "$REST_TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$REST_TIMEOUT_SECONDS" -gt 0 ]] || die "--rest-timeout must be a positive integer."

resolve_repo_dir
SKILL_VERSION="$(read_skill_version)"
probe_server_version
PLUGIN_SOURCE="$(find_plugin_source || true)"
SKILL_SOURCE="$(find_skill_source || true)"
[[ -n "$PLUGIN_SOURCE" || "$INSTALL_CODEX" != "1" ]] || die "Could not find plugin source. Run from a PAM-OS checkout or pass --source."
[[ -n "$SKILL_SOURCE" ]] || die "Could not find skill source. Run from a PAM-OS checkout or pass --source."

  if [[ "$INSTALL_CODEX" == "1" ]]; then
    plugin_stage="${PLUGIN_DIR}.pam-os-stage.$$"
    if [[ -e "$PLUGIN_DIR" ]]; then
      if confirm "Replace existing Codex plugin at $PLUGIN_DIR?" "y"; then
        :
      else
        warn "Skipped Codex plugin install."
        INSTALL_CODEX=0
    fi
    fi
    if [[ "$INSTALL_CODEX" == "1" ]]; then
    info "Staging Codex plugin from $PLUGIN_SOURCE"
    rm -rf "$plugin_stage"
    copy_dir "$PLUGIN_SOURCE" "$plugin_stage"
    write_bundled_skill_config "$plugin_stage"
    rm -rf "$PLUGIN_DIR"
    mv "$plugin_stage" "$PLUGIN_DIR"
    info "Installed Codex plugin to $PLUGIN_DIR"
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

info "PAM-OS $INSTALL_ACTION complete"
cat <<SUMMARY

REST runtime:
  REST URL: $REST_URL

Operation:
  Mode: $INSTALL_ACTION
  Skill version: $SKILL_VERSION
  Expected API: $EXPECTED_API_VERSION
  Server version: ${SERVER_VERSION:-unknown}
  Server API: ${SERVER_API_VERSION:-unknown}
  Version status: $VERSION_STATUS

Skill paths:
  $CODEX_SKILL_DIR
  $CLAUDE_SKILL_DIR
  $HERMES_SKILL_DIR

Installation source repo:
  $REPO_DIR

PAM-OS uses the REST adapter only.

SUMMARY
