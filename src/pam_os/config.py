from __future__ import annotations

import os
from pathlib import Path


def default_db_path() -> Path:
    configured = os.environ.get("PAM_OS_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / ".pam-os" / "memory.sqlite3").resolve()
