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
DEFAULT_CLAUDE_MCP_SCOPE="${PAM_OS_CLAUDE_MCP_SCOPE:-user}"
DEFAULT_OPENCODE_AGENTS_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/AGENTS.md"
DEFAULT_HERMES_CONFIG="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
DEFAULT_HERMES_AGENTS_FILE="${HERMES_HOME:-$HOME/.hermes}/AGENTS.md"
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
PAM-OS plugin installer

Usage:
  ./scripts/install-plugin.sh [options]

Options:
  --target TARGET      Install target: codex, claude, opencode, hermes, or all. Can be repeated.
  --codex             Install the Codex plugin, global skill fallback, and MCP config.
  --claude            Install the Claude Code global skill and MCP config.
  --opencode          Install OpenCode compatibility guidance and Claude-compatible skill.
  --hermes            Install Hermes MCP config and guidance.
  --all               Install all supported targets.
  --plugin-dir DIR      Destination plugin dir. Default: ~/plugins/pam-os-memory.
  --marketplace PATH    Personal marketplace path. Default: ~/.agents/plugins/marketplace.json.
  --codex-config PATH   Codex config.toml path. Default: ~/.codex/config.toml.
  --claude-skill-dir DIR
                      Claude Code skill dir. Default: ~/.claude/skills/pam-os-memory.
  --claude-mcp-scope SCOPE
                      Claude Code MCP scope. Default: user.
  --opencode-agents PATH
                      OpenCode AGENTS.md path. Default: ~/.config/opencode/AGENTS.md.
  --hermes-config PATH
                      Hermes config.yaml path. Default: ~/.hermes/config.yaml.
  --hermes-agents PATH
                      Hermes AGENTS.md path. Default: ~/.hermes/AGENTS.md.
  --repo-dir DIR        Use an existing PAM-OS repo for MCP/dev mode. Default: managed repo ~/.local/share/pam-os/repo.
  --repo-url URL        Git repository used to refresh the managed repo. Default: https://github.com/danzhewuju/PAM-OS.git.
  --ref REF             Git ref used to refresh the managed repo. Default: master.
  --mode cli|rest       Set runtime mode. CLI registers local MCP; REST uses HTTP skill fallback.
  --runtime cli|rest    Alias for --mode.
  --rest-url URL        PAM-OS REST server URL. Default: http://127.0.0.1:8765.
  --rest-username USER  REST Basic Auth username. Default: empty.
  --rest-password PASS  REST Basic Auth password. Default: empty.
                        In interactive REST mode, existing installed skill REST settings are offered for reuse.
  --no-refresh          Do not fetch or clone the managed repo before installing.
  --db PATH             PAM-OS SQLite database path. Default: ~/.pam-os/memory.sqlite3.
  --python VERSION      Python version for uv run --python. Default: 3.12.
  --uv-bin PATH         uv executable path. Default: auto-detect; falls back to system Python when unavailable.
  --source DIR          Existing pam-os-memory plugin source directory for dev/local installs.
  --codex-skill-dir DIR Install the Codex global skill fallback here. Default: ~/.codex/skills/pam-os-memory.
  --skip-marketplace    Do not create or update the personal plugin marketplace entry.
  --skip-mcp-config     Do not register MCP servers in client configs.
  --skip-global-skill   Do not install the Codex global skill fallback.
  --no-init             Skip running "memory init" after install.
  --yes                 Replace an existing plugin install without prompting.
  -h, --help            Show this help.

Without a target option, the installer prompts for one or more targets. With
--yes and no target option, it installs Codex only.

The Codex target refreshes a managed PAM-OS repo, copies the plugin from that
repo, writes a marketplace entry for Codex plugin discovery, and in CLI mode,
unless --skip-mcp-config is passed, registers a stdio MCP server that runs:
  <uv-bin> --directory <managed-repo-dir> run --python <version> memory --db <db> mcp
If uv is unavailable, the installer falls back to:
  PYTHONPATH=<managed-repo-dir>/src <python> -m pam_os.mcp --db <db>
In REST mode, the installer removes PAM-OS MCP registrations it manages so the
installed skill uses the configured REST API instead.

The Claude target installs the global skill and, in CLI mode unless --skip-mcp-config is
passed, registers the same stdio MCP server with:
  claude mcp add-json --scope <scope> pam_os_memory '<json>'

Pass --repo-dir or --source only for local development installs.

By default it also installs the bundled skill to ~/.codex/skills/pam-os-memory
so Codex can load the PAM-OS memory policy even before plugin UI installation
state is refreshed.
USAGE
}

can_prompt() {
  [[ -r /dev/tty && -w /dev/tty ]] || [[ -t 0 && -t 1 ]]
}

is_pipe_install() {
  [[ ! -t 0 ]]
}

pipe_install_hint() {
  printf 'Pipe installs cannot read interactive answers in this terminal.\n' >&2
  printf 'Choose targets explicitly, for example:\n' >&2
  printf '  curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install-plugin.sh | bash -s -- --target codex --yes\n' >&2
  printf 'Or download the script first, then run it interactively:\n' >&2
  printf '  curl -fsSLO https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install-plugin.sh\n' >&2
  printf '  bash install-plugin.sh\n' >&2
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

  if [[ "$default" == "y" ]]; then
    suffix="[Y/n]"
  else
    suffix="[y/N]"
  fi

  while true; do
    if ! read_user reply "$prompt $suffix "; then
      if is_pipe_install; then
        pipe_install_hint
      fi
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
    return 0
  fi

  if [[ -n "$default" ]]; then
    rendered_prompt="$prompt [$default]: "
  else
    rendered_prompt="$prompt (leave empty for none): "
  fi

  if ! read_user reply "$rendered_prompt"; then
    if is_pipe_install; then
      pipe_install_hint
    fi
    die "Interactive prompt requires a TTY. Pass an explicit option or use --yes."
  fi
  printf '%s' "${reply:-$default}"
}

prompt_secret() {
  local prompt="$1"
  local default="$2"
  local reply

  if [[ "$ASSUME_YES" == "1" ]]; then
    printf '%s' "$default"
    return 0
  fi

  if ! read_secret_user reply "$prompt (leave empty for none): "; then
    if is_pipe_install; then
      pipe_install_hint
    fi
    die "Interactive prompt requires a TTY. Pass explicit REST options or use --yes."
  fi
  printf '%s' "${reply:-$default}"
}


load_existing_rest_config() {
  local paths=()
  local output=()

  if [[ "$INSTALL_CODEX" == "1" ]]; then
    paths+=("$CODEX_SKILL_DIR/config.toml")
  fi
  if [[ "$INSTALL_CLAUDE" == "1" || "$INSTALL_OPENCODE" == "1" || "$INSTALL_HERMES" == "1" ]]; then
    paths+=("$CLAUDE_SKILL_DIR/config.toml")
  fi
  paths+=("$CODEX_SKILL_DIR/config.toml" "$CLAUDE_SKILL_DIR/config.toml")

  while IFS= read -r line; do
    output+=("$line")
  done < <("$PYTHON_BIN" - "${paths[@]}" <<'PY'
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit(0)

seen = set()
for raw_path in sys.argv[1:]:
    if not raw_path or raw_path in seen:
        continue
    seen.add(raw_path)
    path = Path(raw_path).expanduser()
    if not path.exists():
        continue
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(data, dict):
        continue
    rest = data.get("rest", {})
    if not isinstance(rest, dict):
        continue
    url = rest.get("url", "")
    if not isinstance(url, str) or not url.strip():
        continue
    mode = data.get("mode", "")
    username = rest.get("username", "")
    password = rest.get("password", "")
    print(str(path))
    print(mode if isinstance(mode, str) else "")
    print(url)
    print(username if isinstance(username, str) else "")
    print(password if isinstance(password, str) else "")
    raise SystemExit(0)
PY
)

  [[ "${#output[@]}" -ge 5 ]] || return 1
  EXISTING_REST_CONFIG_PATH="${output[0]}"
  EXISTING_REST_MODE="${output[1]}"
  EXISTING_REST_URL="${output[2]}"
  EXISTING_REST_USERNAME="${output[3]}"
  EXISTING_REST_PASSWORD="${output[4]}"
}

print_rest_config_summary() {
  local path="$1"
  local mode="$2"
  local url="$3"
  local username="$4"
  local password="$5"
  local password_label="empty"

  if [[ -n "$password" ]]; then
    password_label="set"
  fi

  printf '\nREST configuration found:\n'
  printf '  path: %s\n' "$path"
  if [[ -n "$mode" ]]; then
    printf '  mode: %s\n' "$mode"
  fi
  printf '  url: %s\n' "$url"
  printf '  username: %s\n' "${username:-<empty>}"
  printf '  password: %s\n' "$password_label"
}

configure_rest_runtime() {
  local explicit_count=0

  if [[ "$REST_URL_EXPLICIT" == "1" ]]; then
    explicit_count=$((explicit_count + 1))
  fi
  if [[ "$REST_USERNAME_EXPLICIT" == "1" ]]; then
    explicit_count=$((explicit_count + 1))
  fi
  if [[ "$REST_PASSWORD_EXPLICIT" == "1" ]]; then
    explicit_count=$((explicit_count + 1))
  fi

  if [[ "$explicit_count" -eq 0 ]] && load_existing_rest_config; then
    print_rest_config_summary "$EXISTING_REST_CONFIG_PATH" "$EXISTING_REST_MODE" "$EXISTING_REST_URL" "$EXISTING_REST_USERNAME" "$EXISTING_REST_PASSWORD"
    if confirm "Use this existing REST configuration?" "y"; then
      REST_URL="$EXISTING_REST_URL"
      REST_USERNAME="$EXISTING_REST_USERNAME"
      REST_PASSWORD="$EXISTING_REST_PASSWORD"
      return 0
    fi
  fi

  if [[ "$explicit_count" -gt 0 ]]; then
    print_rest_config_summary "options/environment" "" "$REST_URL" "$REST_USERNAME" "$REST_PASSWORD"
    if confirm "Use this REST configuration?" "y"; then
      return 0
    fi
  fi

  REST_URL="$(prompt_value "PAM-OS REST URL" "$REST_URL")"
  REST_USERNAME="$(prompt_value "REST username" "$REST_USERNAME")"
  REST_PASSWORD="$(prompt_secret "REST password" "$REST_PASSWORD")"
}

select_install_targets() {
  local selection item

  printf '\nInstall targets:\n'
  printf '  1) codex     - Codex plugin + MCP + global skill fallback\n'
  printf '  2) claude    - Claude Code global skill + MCP (%s)\n' "$CLAUDE_SKILL_DIR"
  printf '  3) opencode  - OpenCode guidance (%s)\n' "$OPENCODE_AGENTS_FILE"
  printf '  4) hermes    - Hermes MCP config + guidance (%s)\n' "$HERMES_CONFIG"
  printf '  5) all\n'
  printf '\nSelect one or more targets, separated by commas or spaces.\n'

  while true; do
    if ! read_user selection 'Selection [1]: '; then
      if is_pipe_install; then
        pipe_install_hint
      fi
      die "Interactive target selection requires a TTY."
    fi
    selection="${selection:-1}"
    selection="${selection//,/ }"

    INSTALL_CODEX=0
    INSTALL_CLAUDE=0
    INSTALL_OPENCODE=0
    INSTALL_HERMES=0

    for item in $selection; do
      case "$item" in
        1|codex|Codex|CODEX)
          INSTALL_CODEX=1
          ;;
        2|claude|Claude|CLAUDE|claude-code|Claude-Code)
          INSTALL_CLAUDE=1
          ;;
        3|opencode|OpenCode|OPENCODE)
          INSTALL_OPENCODE=1
          ;;
        4|hermes|Hermes|HERMES)
          INSTALL_HERMES=1
          ;;
        5|all|All|ALL)
          INSTALL_CODEX=1
          INSTALL_CLAUDE=1
          INSTALL_OPENCODE=1
          INSTALL_HERMES=1
          ;;
        *)
          warn "Unknown target: $item"
          INSTALL_CODEX=0
          INSTALL_CLAUDE=0
          INSTALL_OPENCODE=0
          INSTALL_HERMES=0
          break
          ;;
      esac
    done

    if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" != "0000" ]]; then
      return 0
    fi

    printf 'Please select at least one valid target.\n'
  done
}

enable_target() {
  local target="$1"
  case "$target" in
    codex)
      INSTALL_CODEX=1
      ;;
    claude|claude-code)
      INSTALL_CLAUDE=1
      ;;
    opencode)
      INSTALL_OPENCODE=1
      ;;
    hermes)
      INSTALL_HERMES=1
      ;;
    all)
      INSTALL_CODEX=1
      INSTALL_CLAUDE=1
      INSTALL_OPENCODE=1
      INSTALL_HERMES=1
      ;;
    *)
      die "Unknown target: $target"
      ;;
  esac
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

timestamp() {
  date '+%Y%m%d-%H%M%S'
}

find_uv_bin() {
  local candidate

  if [[ -n "${PAM_OS_UV_BIN:-}" ]]; then
    if [[ -x "$PAM_OS_UV_BIN" ]]; then
      abs_path "$PAM_OS_UV_BIN"
      return 0
    fi
    return 1
  fi

  candidate="$(type -P uv || true)"
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    abs_path "$candidate"
    return 0
  fi

  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/usr/local/bin/uv" "/opt/homebrew/bin/uv" "/usr/bin/uv"; do
    if [[ -x "$candidate" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done

  return 1
}

find_claude_bin() {
  local candidate

  if [[ -n "${PAM_OS_CLAUDE_BIN:-}" ]]; then
    if [[ -x "$PAM_OS_CLAUDE_BIN" ]]; then
      abs_path "$PAM_OS_CLAUDE_BIN"
      return 0
    fi
    return 1
  fi

  candidate="$(type -P claude || true)"
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    abs_path "$candidate"
    return 0
  fi

  return 1
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
  if [[ -n "$UV_BIN" && -x "$UV_BIN" ]] && "$UV_BIN" run --python "$PYTHON_VERSION" python -c 'import sys' >/dev/null 2>&1; then
    printf '%s run --python %s python\n' "$UV_BIN" "$PYTHON_VERSION"
    return 0
  fi
  return 1
}

python_major_minor() {
  $PYTHON_BIN - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

python_supports_pam_os() {
  $PYTHON_BIN - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
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

find_skill_source() {
  local candidate
  local roots=(
    "$REPO_DIR/skills/$PLUGIN_NAME"
    "$REPO_DIR/.agents/skills/$PLUGIN_NAME"
    "$REPO_DIR/.claude/skills/$PLUGIN_NAME"
    "$REPO_DIR/plugins/$PLUGIN_NAME/skills/$PLUGIN_NAME"
    "$SOURCE_DIR/skills/$PLUGIN_NAME"
  )

  for candidate in "${roots[@]}"; do
    if [[ -n "$candidate" && -f "$candidate/SKILL.md" ]]; then
      abs_path "$candidate"
      return 0
    fi
  done

  return 1
}

prepare_runtime_commands() {
  local repo_src
  repo_src="$REPO_DIR/src"

  if [[ -n "$UV_BIN" ]]; then
    MCP_COMMAND="$UV_BIN"
    MCP_ARGS=(
      "--directory" "$REPO_DIR"
      "run"
      "--python" "$PYTHON_VERSION"
      "memory"
      "--db" "$DB_PATH"
      "mcp"
    )
    MCP_ENV_JSON="{}"
    INIT_COMMAND="$UV_BIN"
    INIT_ARGS=(
      "--directory" "$REPO_DIR"
      "run"
      "--python" "$PYTHON_VERSION"
      "memory"
      "--db" "$DB_PATH"
      "init"
    )
    INIT_ENV=()
    INIT_ENV_COUNT=0
    RUNTIME_LABEL="uv"
    return 0
  fi

  python_supports_pam_os || die "Could not find uv, and fallback Python $(python_major_minor) is too old. PAM-OS requires Python 3.11+."
  MCP_COMMAND="$PYTHON_BIN"
  MCP_ARGS=("-m" "pam_os.mcp" "--db" "$DB_PATH")
  MCP_ENV_JSON="$(printf '{"PYTHONPATH":%s}' "$($PYTHON_BIN - "$repo_src" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1], ensure_ascii=False))
PY
)")"
  INIT_COMMAND="$PYTHON_BIN"
  INIT_ARGS=("-m" "pam_os.cli" "--db" "$DB_PATH" "init")
  INIT_ENV=("PYTHONPATH=$repo_src")
  INIT_ENV_COUNT=1
  RUNTIME_LABEL="system Python"
}

write_mcp_config() {
  local path="$1"
  $PYTHON_BIN - "$path" "$MCP_COMMAND" "$MCP_ENV_JSON" "${MCP_ARGS[@]}" <<'JSON_WRITER'
import json
import sys
from pathlib import Path

path, command, env_json, *args = sys.argv[1:]
payload = {
    "mcpServers": {
        "pam-os-memory": {
            "command": command,
            "args": args,
            "env": json.loads(env_json),
        }
    }
}
Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
JSON_WRITER
}

build_claude_mcp_json() {
  $PYTHON_BIN - "$MCP_COMMAND" "$MCP_ENV_JSON" "${MCP_ARGS[@]}" <<'JSON_WRITER'
import json
import sys

command, env_json, *args = sys.argv[1:]
payload = {
    "command": command,
    "args": args,
    "env": json.loads(env_json),
}
print(json.dumps(payload, ensure_ascii=False))
JSON_WRITER
}

write_claude_mcp_config() {
  local claude_bin payload

  claude_bin="$(find_claude_bin || true)"
  if [[ -z "$claude_bin" ]]; then
    warn "Could not find claude CLI; skipped Claude MCP registration."
    warn "Run manually later: claude mcp add-json --scope $CLAUDE_MCP_SCOPE $MCP_SERVER_NAME '<json>'"
    return 0
  fi

  payload="$(build_claude_mcp_json)"
  info "Registering Claude MCP server '$MCP_SERVER_NAME' with scope '$CLAUDE_MCP_SCOPE'"
  "$claude_bin" mcp remove --scope "$CLAUDE_MCP_SCOPE" "$MCP_SERVER_NAME" >/dev/null 2>&1 || true
  if "$claude_bin" mcp add-json --scope "$CLAUDE_MCP_SCOPE" "$MCP_SERVER_NAME" "$payload"; then
    return 0
  fi

  warn "Failed to register Claude MCP server '$MCP_SERVER_NAME'."
  warn "Run manually later: claude mcp add-json --scope $CLAUDE_MCP_SCOPE $MCP_SERVER_NAME '$payload'"
}

remove_claude_mcp_config() {
  local claude_bin

  claude_bin="$(find_claude_bin || true)"
  if [[ -z "$claude_bin" ]]; then
    warn "Could not find claude CLI; skipped Claude MCP removal."
    warn "Run manually later: claude mcp remove --scope $CLAUDE_MCP_SCOPE $MCP_SERVER_NAME"
    return 0
  fi

  info "Removing Claude MCP server '$MCP_SERVER_NAME' from scope '$CLAUDE_MCP_SCOPE' for REST mode"
  "$claude_bin" mcp remove --scope "$CLAUDE_MCP_SCOPE" "$MCP_SERVER_NAME" >/dev/null 2>&1 || true
}


write_skill_config() {
  local path="$1"
  local escaped_url escaped_user escaped_pass escaped_python escaped_repo_dir escaped_db_path

  escaped_url="$(toml_escape "$REST_URL")"
  escaped_user="$(toml_escape "$REST_USERNAME")"
  escaped_pass="$(toml_escape "$REST_PASSWORD")"
  escaped_python="$(toml_escape "$PYTHON_VERSION")"
  escaped_repo_dir="$(toml_escape "$REPO_DIR")"
  escaped_db_path="$(toml_escape "$DB_PATH")"

  cat > "$path" <<CONFIG
# PAM-OS skill runtime mode.
# Default is CLI. Change mode to "rest" when the REST server is running.

mode = "$INSTALL_MODE"

[cli]
python = "$escaped_python"
command = "memory"
repo_dir = "$escaped_repo_dir"
db_path = "$escaped_db_path"

[rest]
url = "$escaped_url"
username = "$escaped_user"
password = "$escaped_pass"
CONFIG
}

run_cli_init() {
  if [[ "$INSTALL_MODE" != "cli" || "$RUN_INIT" != "1" ]]; then
    return 0
  fi

  if ! confirm "Initialize PAM-OS memory database and warm up the selected runtime?" "y"; then
    warn "Skipped PAM-OS memory database init."
    return 0
  fi

  if [[ -z "$INIT_COMMAND" ]]; then
    warn "Could not run init because no init command was prepared."
    warn "Run manually later: $MCP_COMMAND ${MCP_ARGS[*]}"
    return 0
  fi

  info "Initializing PAM-OS memory database and warming selected runtime"
  if [[ "$INIT_ENV_COUNT" -gt 0 ]]; then
    if env "${INIT_ENV[@]}" "$INIT_COMMAND" "${INIT_ARGS[@]}"; then
      return 0
    fi
  else
    if "$INIT_COMMAND" "${INIT_ARGS[@]}"; then
      return 0
    fi
  fi

  warn "PAM-OS memory database init or runtime warmup failed."
  warn "Run manually later: $INIT_COMMAND ${INIT_ARGS[*]}"
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

install_global_skill() {
  local src="$1"
  local dest="$2"
  local label="$3"

  if [[ ! -f "$src/SKILL.md" ]]; then
    warn "Skill source is invalid at $src; skipped $label."
    return 0
  fi

  if [[ -e "$dest" ]]; then
    if confirm "Replace existing $label at $dest?" "y"; then
      rm -rf "$dest"
    else
      warn "Skipped $label."
      return 0
    fi
  fi

  info "Installing $label to $dest"
  mkdir -p "$(dirname "$dest")"
  cp -R "$src" "$dest"
  write_skill_config "$dest/config.toml"
}

append_managed_guidance() {
  local file="$1"
  local skill_path="$2"
  local start='<!-- PAM-OS memory plugin: begin -->'
  local end='<!-- PAM-OS memory plugin: end -->'
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
    if [[ "$INSTALL_MODE" == "rest" ]]; then
      printf 'Use the installed PAM-OS skill and its REST configuration from `%s`. Do not prefer a local MCP server unless the user explicitly re-enables MCP.\n\n' "$skill_path"
    else
      printf 'Prefer the PAM-OS MCP server when available. If a compatible skill is available, use it; otherwise read the installed skill instructions from `%s`.\n\n' "$skill_path"
    fi
    printf 'Do not store secrets or sensitive details unless the user explicitly asks to remember them.\n'
    printf '%s\n' "$end"
  } >> "$tmp"

  mv "$tmp" "$file"
}

install_claude() {
  local src="$1"
  install_global_skill "$src" "$CLAUDE_SKILL_DIR" "Claude Code global skill"

  if [[ "$WRITE_MCP_CONFIG" == "1" ]]; then
    if [[ "$INSTALL_MODE" == "cli" ]]; then
      write_claude_mcp_config
    else
      remove_claude_mcp_config
    fi
  fi
}

install_opencode() {
  local src="$1"

  info "Installing OpenCode compatibility"
  if [[ "$INSTALL_CLAUDE" == "1" ]]; then
    info "Claude-compatible skill target is already handled by the Claude Code install."
  else
    install_global_skill "$src" "$CLAUDE_SKILL_DIR" "OpenCode Claude-compatible skill"
  fi

  append_managed_guidance "$OPENCODE_AGENTS_FILE" "$CLAUDE_SKILL_DIR/SKILL.md"
  printf 'Updated: %s\n' "$OPENCODE_AGENTS_FILE"
}

write_hermes_mcp_config() {
  local path="$1"
  $PYTHON_BIN - "$path" "$MCP_SERVER_NAME" "$MCP_COMMAND" "$MCP_ENV_JSON" "${MCP_ARGS[@]}" <<'YAML_WRITER'
import json
import sys
from pathlib import Path

path, server_name, command, env_json, *args = sys.argv[1:]
config_path = Path(path).expanduser()
server_header = f"  {server_name}:"


def yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


block_lines = [
    server_header,
    f"    command: {yaml_scalar(command)}",
    "    args:",
    *[f"      - {yaml_scalar(arg)}" for arg in args],
]
env = json.loads(env_json)
if env:
    block_lines.append("    env:")
    block_lines.extend(f"      {key}: {yaml_scalar(str(value))}" for key, value in sorted(env.items()))

if config_path.exists():
    lines = config_path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

output = []
index = 0
in_mcp = False
replaced = False
found_mcp = False
while index < len(lines):
    line = lines[index]
    stripped = line.strip()
    if line == "mcp_servers:":
        found_mcp = True
        in_mcp = True
        output.append(line)
        index += 1
        continue
    if in_mcp and line.startswith("  ") and stripped == f"{server_name}:":
        output.extend(block_lines)
        replaced = True
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if next_line and not next_line.startswith("    ") and not next_line.startswith("      "):
                break
            index += 1
        continue
    if in_mcp and line and not line.startswith(" "):
        if not replaced:
            output.extend(block_lines)
            replaced = True
        in_mcp = False
    output.append(line)
    index += 1

if not found_mcp:
    if output and output[-1].strip():
        output.append("")
    output.append("mcp_servers:")
    output.extend(block_lines)
elif not replaced:
    output.extend(block_lines)

config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
YAML_WRITER
}

remove_hermes_mcp_config() {
  local path="$1"
  $PYTHON_BIN - "$path" "$MCP_SERVER_NAME" <<'YAML_REMOVER'
import sys
from pathlib import Path

path, server_name = sys.argv[1:]
config_path = Path(path).expanduser()
if not config_path.exists():
    raise SystemExit(0)

lines = config_path.read_text(encoding="utf-8").splitlines()
output = []
index = 0
in_mcp = False
removed = False
while index < len(lines):
    line = lines[index]
    stripped = line.strip()
    if line == "mcp_servers:":
        in_mcp = True
        output.append(line)
        index += 1
        continue
    if in_mcp and line.startswith("  ") and stripped == f"{server_name}:":
        removed = True
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if next_line and not next_line.startswith("    ") and not next_line.startswith("      "):
                break
            index += 1
        continue
    if in_mcp and line and not line.startswith(" "):
        in_mcp = False
    output.append(line)
    index += 1

if removed:
    config_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
YAML_REMOVER
}

install_hermes() {
  local skill_src="$1"

  info "Installing Hermes compatibility"
  if [[ "$WRITE_MCP_CONFIG" == "1" ]]; then
    if [[ "$INSTALL_MODE" == "cli" ]]; then
      write_hermes_mcp_config "$HERMES_CONFIG"
      printf 'Updated: %s\n' "$HERMES_CONFIG"
    else
      remove_hermes_mcp_config "$HERMES_CONFIG"
      printf 'Removed PAM-OS MCP server from: %s\n' "$HERMES_CONFIG"
    fi
  fi
  append_managed_guidance "$HERMES_AGENTS_FILE" "$skill_src/SKILL.md"
  printf 'Updated: %s\n' "$HERMES_AGENTS_FILE"
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
  $PYTHON_BIN - "$path" "$MCP_SERVER_NAME" "$MCP_COMMAND" "$MCP_ENV_JSON" "${MCP_ARGS[@]}" <<'TOML_WRITER'
import sys
import json
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

path, server_name, command, env_json, *args = sys.argv[1:]
config_path = Path(path).expanduser()
server_header = f"[mcp_servers.{server_name}]"
server_child_prefix = f"[mcp_servers.{server_name}."


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def is_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def is_managed_server_header(line: str) -> bool:
    stripped = line.strip()
    return stripped == server_header or stripped.startswith(server_child_prefix)


block_lines = [
    server_header,
    f"command = {toml_string(command)}",
    "args = [",
    *[f"  {toml_string(arg)}," for arg in args],
    "]",
    'description = "PAM-OS local-first long-term memory"',
    "",
]
env = json.loads(env_json)
if env:
    block_lines.extend(["[mcp_servers.%s.env]" % server_name])
    block_lines.extend(f"{key} = {toml_string(str(value))}" for key, value in sorted(env.items()))
    block_lines.append("")

if config_path.exists():
    lines = config_path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

output = []
index = 0
replaced = False
while index < len(lines):
    line = lines[index]
    if is_managed_server_header(line):
        if not replaced:
            output.extend(block_lines)
            replaced = True
        index += 1
        while index < len(lines):
            if is_table_header(lines[index]) and not is_managed_server_header(lines[index]):
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
rendered = "\n".join(output).rstrip() + "\n"
if tomllib is not None:
    tomllib.loads(rendered)
config_path.write_text(rendered, encoding="utf-8")
TOML_WRITER
}

remove_codex_mcp_config() {
  local path="$1"
  $PYTHON_BIN - "$path" "$MCP_SERVER_NAME" <<'TOML_REMOVER'
import sys
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

path, server_name = sys.argv[1:]
config_path = Path(path).expanduser()
server_header = f"[mcp_servers.{server_name}]"
server_child_prefix = f"[mcp_servers.{server_name}."


def is_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def is_managed_server_header(line: str) -> bool:
    stripped = line.strip()
    return stripped == server_header or stripped.startswith(server_child_prefix)

if not config_path.exists():
    raise SystemExit(0)

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
    rendered = "\n".join(output).rstrip() + "\n" if output else ""
    if tomllib is not None and rendered.strip():
        tomllib.loads(rendered)
    config_path.write_text(rendered, encoding="utf-8")
TOML_REMOVER
}

ASSUME_YES=0
INSTALL_CODEX=0
INSTALL_CLAUDE=0
INSTALL_OPENCODE=0
INSTALL_HERMES=0
PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
MARKETPLACE_PATH="$DEFAULT_MARKETPLACE_PATH"
CODEX_CONFIG="$DEFAULT_CODEX_CONFIG"
CODEX_SKILL_DIR="$DEFAULT_CODEX_SKILL_DIR"
CLAUDE_SKILL_DIR="$DEFAULT_CLAUDE_SKILL_DIR"
CLAUDE_MCP_SCOPE="$DEFAULT_CLAUDE_MCP_SCOPE"
OPENCODE_AGENTS_FILE="$DEFAULT_OPENCODE_AGENTS_FILE"
HERMES_CONFIG="$DEFAULT_HERMES_CONFIG"
HERMES_AGENTS_FILE="$DEFAULT_HERMES_AGENTS_FILE"
REPO_URL="$DEFAULT_REPO_URL"
REPO_REF="$DEFAULT_REPO_REF"
REPO_DIR="$DEFAULT_REPO_DIR"
REPO_DIR_EXPLICIT=0
REFRESH_REPO=1
MODE_ARG=""
INSTALL_MODE=""
REST_URL="${PAM_OS_REST_URL:-http://127.0.0.1:8765}"
REST_USERNAME="${PAM_OS_REST_USERNAME:-}"
REST_PASSWORD="${PAM_OS_REST_PASSWORD:-}"
REST_URL_EXPLICIT=0
REST_USERNAME_EXPLICIT=0
REST_PASSWORD_EXPLICIT=0
[[ -n "${PAM_OS_REST_URL:-}" ]] && REST_URL_EXPLICIT=1
[[ -n "${PAM_OS_REST_USERNAME+x}" ]] && REST_USERNAME_EXPLICIT=1
[[ -n "${PAM_OS_REST_PASSWORD+x}" ]] && REST_PASSWORD_EXPLICIT=1
EXISTING_REST_CONFIG_PATH=""
EXISTING_REST_MODE=""
EXISTING_REST_URL=""
EXISTING_REST_USERNAME=""
EXISTING_REST_PASSWORD=""
DB_PATH="$DEFAULT_DB_PATH"
PYTHON_VERSION="${PAM_OS_CLI_PYTHON:-3.12}"
UV_BIN="${PAM_OS_UV_BIN:-}"
SOURCE_DIR=""
WRITE_MARKETPLACE=1
WRITE_MCP_CONFIG=1
WRITE_GLOBAL_SKILL=1
RUN_INIT=1
PYTHON_BIN=""
MCP_COMMAND=""
MCP_ARGS=()
MCP_ENV_JSON="{}"
INIT_COMMAND=""
INIT_ARGS=()
INIT_ENV=()
INIT_ENV_COUNT=0
RUNTIME_LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      enable_target "${2:-}"
      shift 2
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
    --hermes)
      INSTALL_HERMES=1
      shift
      ;;
    --all)
      enable_target all
      shift
      ;;
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
    --claude-skill-dir)
      CLAUDE_SKILL_DIR="${2:-}"
      shift 2
      ;;
    --claude-mcp-scope)
      CLAUDE_MCP_SCOPE="${2:-}"
      shift 2
      ;;
    --opencode-agents)
      OPENCODE_AGENTS_FILE="${2:-}"
      shift 2
      ;;
    --hermes-config)
      HERMES_CONFIG="${2:-}"
      shift 2
      ;;
    --hermes-agents)
      HERMES_AGENTS_FILE="${2:-}"
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
    --mode|--runtime)
      MODE_ARG="${2:-}"
      shift 2
      ;;
    --rest-url)
      REST_URL="${2:-}"
      REST_URL_EXPLICIT=1
      shift 2
      ;;
    --rest-username|--rest-user)
      REST_USERNAME="${2:-}"
      REST_USERNAME_EXPLICIT=1
      shift 2
      ;;
    --rest-password)
      REST_PASSWORD="${2:-}"
      REST_PASSWORD_EXPLICIT=1
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
    --uv-bin)
      UV_BIN="${2:-}"
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
[[ -n "$CLAUDE_SKILL_DIR" ]] || die "--claude-skill-dir must not be empty."
[[ -n "$CLAUDE_MCP_SCOPE" ]] || die "--claude-mcp-scope must not be empty."
[[ -n "$OPENCODE_AGENTS_FILE" ]] || die "--opencode-agents must not be empty."
[[ -n "$HERMES_CONFIG" ]] || die "--hermes-config must not be empty."
[[ -n "$HERMES_AGENTS_FILE" ]] || die "--hermes-agents must not be empty."
[[ -n "$REPO_URL" ]] || die "--repo-url must not be empty."
[[ -n "$REPO_REF" ]] || die "--ref must not be empty."
[[ -n "$REPO_DIR" ]] || die "--repo-dir must not be empty."
[[ -n "$DB_PATH" ]] || die "--db must not be empty."
[[ -n "$PYTHON_VERSION" ]] || die "--python must not be empty."
if [[ -n "$MODE_ARG" && "$MODE_ARG" != "cli" && "$MODE_ARG" != "rest" ]]; then
  die "--mode must be cli or rest."
fi

if [[ "$ASSUME_YES" == "0" && ! can_prompt ]]; then
  die "Interactive install requires a TTY. Use --yes for non-interactive installs."
fi

if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" == "0000" ]]; then
  if [[ "$ASSUME_YES" == "1" ]]; then
    INSTALL_CODEX=1
  else
    select_install_targets
  fi
fi

if [[ "$INSTALL_CODEX$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" == "0000" ]]; then
  die "No install targets selected."
fi

if [[ -z "$MODE_ARG" ]]; then
  if [[ "$ASSUME_YES" == "1" ]]; then
    INSTALL_MODE="cli"
  else
    printf '\nRuntime mode:\n'
    printf '  1) cli  - register local MCP runtime; CLI fallback remains available\n'
    printf '  2) rest - use a running PAM-OS REST server and remove managed local MCP\n'
    if ! read_user mode_choice 'Selection [1]: '; then
      if is_pipe_install; then
        pipe_install_hint
      fi
      die "Interactive runtime mode selection requires a TTY. Pass --mode cli or --mode rest."
    fi
    mode_choice="${mode_choice:-1}"
    case "$mode_choice" in
      1|cli|CLI) INSTALL_MODE="cli" ;;
      2|rest|REST) INSTALL_MODE="rest" ;;
      *) die "Invalid runtime mode: $mode_choice" ;;
    esac
  fi
else
  INSTALL_MODE="$MODE_ARG"
fi

if [[ -n "$UV_BIN" ]]; then
  [[ -x "$UV_BIN" ]] || die "--uv-bin must point to an executable uv binary: $UV_BIN"
  UV_BIN="$(abs_path "$UV_BIN")"
else
  UV_BIN="$(find_uv_bin || true)"
fi

PYTHON_BIN="$(find_python_bin || true)"
[[ -n "$PYTHON_BIN" ]] || die "Could not find a working Python executable for installer config writes."

if [[ "$INSTALL_MODE" == "rest" ]]; then
  configure_rest_runtime
fi

[[ -n "$REST_URL" ]] || die "--rest-url must not be empty when --mode rest is selected."

resolve_repo_dir
if [[ "$INSTALL_CODEX" == "1" ]]; then
  SOURCE="$(find_plugin_source || true)"
  [[ -n "$SOURCE" ]] || die "Could not find plugin source. Run from a PAM-OS checkout or pass --source."
else
  SOURCE=""
fi
SKILL_SOURCE="$(find_skill_source || true)"
if [[ "$INSTALL_CLAUDE$INSTALL_OPENCODE$INSTALL_HERMES" != "000" || "$WRITE_GLOBAL_SKILL" == "1" ]]; then
  [[ -n "$SKILL_SOURCE" ]] || die "Could not find skill source. Run from a PAM-OS checkout or pass --source."
fi
prepare_runtime_commands

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
    info "Installing Codex plugin from $SOURCE"
    mkdir -p "$(dirname "$PLUGIN_DIR")"
    cp -R "$SOURCE" "$PLUGIN_DIR"
    if [[ "$INSTALL_MODE" == "cli" ]]; then
      write_mcp_config "$PLUGIN_DIR/.mcp.json"
    else
      rm -f "$PLUGIN_DIR/.mcp.json"
      info "REST mode: removed Codex plugin MCP manifest so the skill uses REST fallback"
    fi

    if [[ "$WRITE_GLOBAL_SKILL" == "1" ]]; then
      install_codex_global_skill "$PLUGIN_DIR" "$CODEX_SKILL_DIR"
    fi

    if [[ "$WRITE_MARKETPLACE" == "1" ]]; then
      write_marketplace_config "$MARKETPLACE_PATH"
      info "Updated marketplace: $MARKETPLACE_PATH"
    fi

    if [[ "$WRITE_MCP_CONFIG" == "1" ]]; then
      if [[ "$INSTALL_MODE" == "cli" ]]; then
        write_codex_mcp_config "$CODEX_CONFIG"
        info "Registered MCP server '$MCP_SERVER_NAME' in $CODEX_CONFIG"
      else
        remove_codex_mcp_config "$CODEX_CONFIG"
        info "REST mode: removed MCP server '$MCP_SERVER_NAME' from $CODEX_CONFIG"
      fi
    fi
  fi
fi

if [[ "$INSTALL_CLAUDE" == "1" ]]; then
  install_claude "$SKILL_SOURCE"
fi

if [[ "$INSTALL_OPENCODE" == "1" ]]; then
  install_opencode "$SKILL_SOURCE"
fi

if [[ "$INSTALL_HERMES" == "1" ]]; then
  install_hermes "$SKILL_SOURCE"
fi

run_cli_init

info "Install complete"
if [[ "$INSTALL_MODE" == "cli" ]]; then
  cat <<SUMMARY

Next checks:
  Codex:   restart Codex, list skills, and verify the pam_os_memory MCP server.
  Claude:  restart Claude Code, run /mcp, then list skills or invoke /pam-os-memory.
  OpenCode: restart opencode so it reloads AGENTS.md guidance.
  Hermes:  restart Hermes and verify the pam_os_memory MCP server is listed.

Marketplace:
  $MARKETPLACE_PATH

Skill paths:
  $CODEX_SKILL_DIR
  $CLAUDE_SKILL_DIR

Guidance/config:
  $OPENCODE_AGENTS_FILE
  $HERMES_CONFIG
  $HERMES_AGENTS_FILE

Managed/runtime repo:
  $REPO_DIR

MCP command:
  $MCP_COMMAND ${MCP_ARGS[*]}

Runtime:
  $RUNTIME_LABEL

Skill fallback runtime:
  mode: $INSTALL_MODE
  REST URL: $REST_URL

MCP environment:
  $MCP_ENV_JSON

SUMMARY
else
  cat <<SUMMARY

Next checks:
  Codex:   restart Codex, list skills, and verify the pam-os-memory skill uses REST.
  Claude:  restart Claude Code, then list skills or invoke /pam-os-memory.
  OpenCode: restart opencode so it reloads AGENTS.md guidance.
  Hermes:  restart Hermes and verify PAM-OS guidance uses REST.

Marketplace:
  $MARKETPLACE_PATH

Skill paths:
  $CODEX_SKILL_DIR
  $CLAUDE_SKILL_DIR

Guidance/config:
  $OPENCODE_AGENTS_FILE
  $HERMES_CONFIG
  $HERMES_AGENTS_FILE

Managed/runtime repo:
  $REPO_DIR

MCP:
  disabled for REST mode; managed pam_os_memory registrations were removed when writable.

Runtime:
  REST API

Skill runtime:
  mode: $INSTALL_MODE
  REST URL: $REST_URL

SUMMARY
fi
