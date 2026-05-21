from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StorageConfig:
    db_path: str = "~/.pam-os/memory.sqlite3"


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    auth_enabled: bool = False
    auth_username: str = ""
    auth_password: str = ""


@dataclass(frozen=True)
class ContextConfig:
    default_limit: int = 12
    max_chars: int = 4000
    profile_limit: int = 8


@dataclass(frozen=True)
class ConsolidationConfig:
    recent_limit: int = 100
    stability_increment: float = 0.12
    max_confidence: float = 0.98
    max_stability: float = 0.98


@dataclass(frozen=True)
class OrchestratorConfig:
    memory_use_threshold: float = 0.5
    capture_threshold: float = 0.5
    candidate_multiplier: int = 3


@dataclass(frozen=True)
class RetrievalConfig:
    max_query_terms: int = 12


@dataclass(frozen=True)
class ProfileConfig:
    default_limit: int = 20


@dataclass(frozen=True)
class AppConfig:
    storage: StorageConfig = field(default_factory=StorageConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    config_path: Path | None = None


def load_config(config_path: Path | str | None = None) -> AppConfig:
    path = _resolve_config_path(config_path)
    data: dict[str, Any] = {}
    if path and path.exists():
        with path.open("rb") as handle:
            data = tomllib.load(handle)

    config = AppConfig(
        storage=StorageConfig(**_section(data, "storage")),
        server=ServerConfig(**_section(data, "server")),
        context=ContextConfig(**_section(data, "context")),
        consolidation=ConsolidationConfig(**_section(data, "consolidation")),
        orchestrator=OrchestratorConfig(**_section(data, "orchestrator")),
        retrieval=RetrievalConfig(**_section(data, "retrieval")),
        profile=ProfileConfig(**_section(data, "profile")),
        config_path=path if path and path.exists() else None,
    )
    return _apply_env_overrides(config)


def default_db_path(config: AppConfig | None = None) -> Path:
    configured = os.environ.get("PAM_OS_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    config = config or load_config()
    return _resolve_path(config.storage.db_path)


def _resolve_config_path(config_path: Path | str | None) -> Path | None:
    configured = config_path or os.environ.get("PAM_OS_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    default = Path.cwd() / "config" / "pam-os.toml"
    return default.resolve()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name, {})
    if not isinstance(section, dict):
        raise ValueError(f"config section [{name}] must be a table")
    return section


def _apply_env_overrides(config: AppConfig) -> AppConfig:
    db_path = os.environ.get("PAM_OS_DB") or config.storage.db_path
    return AppConfig(
        storage=StorageConfig(db_path=db_path),
        server=ServerConfig(
            host=config.server.host,
            port=config.server.port,
            auth_enabled=_env_bool("PAM_OS_AUTH_ENABLED", config.server.auth_enabled),
            auth_username=os.environ.get("PAM_OS_AUTH_USERNAME", config.server.auth_username),
            auth_password=os.environ.get("PAM_OS_AUTH_PASSWORD", config.server.auth_password),
        ),
        context=config.context,
        consolidation=config.consolidation,
        orchestrator=config.orchestrator,
        retrieval=config.retrieval,
        profile=config.profile,
        config_path=config.config_path,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved.resolve()
