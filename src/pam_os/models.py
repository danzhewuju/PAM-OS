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


@dataclass(frozen=True)
class MemoryUseDecision:
    should_use: bool
    reason: str
    confidence: float
    signals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedContext:
    decision: MemoryUseDecision
    package: ContextPackage | None
    results: list[SearchResult] = field(default_factory=list)


@dataclass(frozen=True)
class CaptureResult:
    should_capture: bool
    reason: str
    event: Event | None = None
    memories: list[Memory] = field(default_factory=list)


@dataclass(frozen=True)
class ProfileEvidence:
    id: str
    trait_key: str
    evidence_type: str
    content: str
    source_event_id: str | None = None
    source_memory_id: str | None = None
    behavior_event_id: str | None = None
    confidence: float = 0.6
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class ProfileTrait:
    id: str
    trait_type: str
    trait_key: str
    statement: str
    scope: str
    stability: float
    confidence: float
    evidence_count: int
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "active"
    first_seen_at: str = field(default_factory=now_iso)
    last_confirmed_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class BehaviorEvent:
    id: str
    context: str
    chosen: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    reason: str | None = None
    source_ref: str | None = None
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class ConsolidationResult:
    evidence_created: list[ProfileEvidence] = field(default_factory=list)
    traits_updated: list[ProfileTrait] = field(default_factory=list)
    memories_scanned: int = 0
    behavior_events_scanned: int = 0


@dataclass(frozen=True)
class StorageStats:
    db_path: str
    db_size_bytes: int
    fts_available: bool
    latest_write_at: str | None
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
