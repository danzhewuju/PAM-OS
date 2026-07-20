from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re
import sqlite3
from threading import RLock

from pam_os.config import AppConfig
from pam_os.runtime import PersonalMemoryRuntime


USER_ID_PATTERN = re.compile(r"^usr_[0-9a-f]{32}$")


class UserRuntimeFactory:
    """Resolves an authenticated user to a physically isolated memory runtime."""

    def __init__(self, data_dir: Path | str, config: AppConfig, *, max_cached: int | None = None):
        self.data_dir = Path(data_dir)
        self.config = config
        self.max_cached = max_cached if max_cached is not None else config.storage.runtime_cache_size
        if self.max_cached < 1:
            raise ValueError("runtime_cache_size must be at least 1")
        self._cache: OrderedDict[str, PersonalMemoryRuntime] = OrderedDict()
        self._lock = RLock()

    def for_user(self, user_id: str) -> PersonalMemoryRuntime:
        if not USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("invalid internal user id")
        with self._lock:
            cached = self._cache.pop(user_id, None)
            if cached is not None:
                self._cache[user_id] = cached
                return cached

            db_path = self.db_path_for_user(user_id)
            bind_store_owner(db_path, user_id)
            runtime = PersonalMemoryRuntime(db_path=db_path, config=self.config)
            self._cache[user_id] = runtime
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
            return runtime

    def db_path_for_user(self, user_id: str) -> Path:
        if not USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("invalid internal user id")
        return self.data_dir / "users" / user_id / "memory.sqlite3"


def bind_store_owner(db_path: Path | str, user_id: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS store_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT value FROM store_metadata WHERE key = 'owner_user_id'").fetchone()
        if row is None:
            try:
                conn.execute(
                    "INSERT INTO store_metadata(key, value) VALUES ('owner_user_id', ?)",
                    (user_id,),
                )
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT value FROM store_metadata WHERE key = 'owner_user_id'").fetchone()
                if row is None or row["value"] != user_id:
                    raise RuntimeError("memory store owner binding failed")
        elif row["value"] != user_id:
            raise RuntimeError("memory store belongs to a different user")
        conn.execute(
            "INSERT OR IGNORE INTO store_metadata(key, value) VALUES ('schema_version', '1')"
        )
