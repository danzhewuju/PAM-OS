from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True)
class Event:
    id: str
    source: str
    content: str
    source_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class Memory:
    id: str
    event_id: str
    type: str
    content: str
    importance: float
    confidence: float
    tags: list[str] = field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class SearchResult:
    memory: Memory
    score: float


@dataclass(frozen=True)
class ContextPackage:
    id: str
    task: str
    content: str
    memory_ids: list[str]
    created_at: str = field(default_factory=now_iso)
