#!/usr/bin/env bash
set -Eeuo pipefail

client_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
client="$client_dir/pam_client.py"

candidates=()
[[ -z "${PAM_OS_PYTHON:-}" ]] || candidates+=("$PAM_OS_PYTHON")
candidates+=(python3 python)

for candidate in "${candidates[@]}"; do
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    exec "$candidate" "$client" "$@"
  fi
done

if uv run --no-cache --no-project python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  exec uv run --no-cache --no-project python "$client" "$@"
fi

printf 'error: PAM-OS requires Python 3.11 or newer (or uv).\n' >&2
exit 2
