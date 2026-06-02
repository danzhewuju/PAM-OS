from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from pam_os.config import load_config
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain
from pam_os.version import __version__


def create_app(db_path: Path | str | None = None, config=None):
    try:
        from fastapi import Depends, FastAPI, HTTPException, status
        from fastapi.security import HTTPBasic, HTTPBasicCredentials
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError('REST API dependencies are missing. Install with: pip install -e ".[api]"') from exc

    config = config or load_config()
    if config.server.auth_enabled and (not config.server.auth_username or not config.server.auth_password):
        raise RuntimeError("REST API auth is enabled, but server.auth_username or server.auth_password is missing")

    runtime = PersonalMemoryRuntime(db_path=db_path, config=config)
    security = HTTPBasic(auto_error=False)

    def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
        ensure_basic_auth(credentials, config.server.auth_enabled, config.server.auth_username, config.server.auth_password)

    app = FastAPI(title="Personal Memory Runtime", version=__version__, dependencies=[Depends(require_auth)])

    class EventRequest(BaseModel):
        content: str
        source: str = "manual"
        source_ref: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)
        extract: bool = True

    class CompileRequest(BaseModel):
        task: str
        limit: int | None = None
        min_importance: float = 0.0
        min_confidence: float = 0.0

    class PrepareRequest(BaseModel):
        task: str
        conversation_summary: str | None = None
        force: bool = False
        limit: int | None = None
        max_chars: int | None = None

    class CaptureRequest(BaseModel):
        content: str
        source: str = "conversation"
        source_ref: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)
        force: bool = False

    class BehaviorChoiceRequest(BaseModel):
        context: str
        chosen: list[str] = Field(default_factory=list)
        rejected: list[str] = Field(default_factory=list)
        deferred: list[str] = Field(default_factory=list)
        reason: str | None = None
        source_ref: str | None = None

    class ObserveTurnRequest(BaseModel):
        user_message: str
        assistant_message: str = ""
        conversation_summary: str | None = None
        source_ref: str | None = None
        auto_capture: bool = True
        auto_learn_policy: bool = True

    class ConsolidateRequest(BaseModel):
        recent: int | None = None

    class ReflectRequest(BaseModel):
        recent: int = 50

    class ClearMemoryRequest(BaseModel):
        confirm: bool = False

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "db_path": str(runtime.db_path), "fts_available": runtime.store.fts_available}

    @app.get("/storage/stats")
    def get_storage_stats() -> dict[str, Any]:
        return to_plain(runtime.get_storage_stats())

    @app.get("/memory/inspect")
    def inspect_memory(table: str = "all", limit: int = 20, q: str | None = None) -> dict[str, Any]:
        try:
            return to_plain(runtime.inspect_memory(table=table, limit=limit, query=q))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/memory/clear")
    def clear_memory(request: ClearMemoryRequest) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true")
        return to_plain(runtime.clear_memory())

    @app.post("/events")
    def remember(request: EventRequest) -> dict[str, Any]:
        return to_plain(
            runtime.remember(
                request.content,
                source=request.source,
                source_ref=request.source_ref,
                metadata=request.metadata,
                extract=request.extract,
            )
        )

    @app.get("/memories/search")
    def search_memory(q: str, limit: int = 10) -> list[dict[str, Any]]:
        return to_plain(runtime.search_memory(q, limit=limit))

    @app.get("/memory/should-use")
    def should_use_memory(task: str, conversation_summary: str | None = None) -> dict[str, Any]:
        return to_plain(runtime.should_use_memory(task, conversation_summary))

    @app.post("/context/prepare")
    def prepare_context(request: PrepareRequest) -> dict[str, Any]:
        return to_plain(
            runtime.prepare_context(
                request.task,
                conversation_summary=request.conversation_summary,
                force=request.force,
                limit=request.limit,
                max_chars=request.max_chars,
            )
        )

    @app.post("/memory/capture")
    def capture_memory(request: CaptureRequest) -> dict[str, Any]:
        return to_plain(
            runtime.capture_memory(
                request.content,
                source=request.source,
                source_ref=request.source_ref,
                metadata=request.metadata,
                force=request.force,
            )
        )

    @app.post("/behavior/choice")
    def record_behavior_choice(request: BehaviorChoiceRequest) -> dict[str, Any]:
        return to_plain(
            runtime.record_behavior_choice(
                context=request.context,
                chosen=request.chosen,
                rejected=request.rejected,
                deferred=request.deferred,
                reason=request.reason,
                source_ref=request.source_ref,
            )
        )

    @app.post("/turns/observe")
    def observe_turn(request: ObserveTurnRequest) -> dict[str, Any]:
        return to_plain(
            runtime.observe_turn(
                user_message=request.user_message,
                assistant_message=request.assistant_message,
                conversation_summary=request.conversation_summary,
                source_ref=request.source_ref,
                auto_capture=request.auto_capture,
                auto_learn_policy=request.auto_learn_policy,
            )
        )

    @app.post("/memory/consolidate")
    def consolidate_memory(request: ConsolidateRequest) -> dict[str, Any]:
        return to_plain(runtime.consolidate_memory(recent=request.recent))

    @app.get("/profile")
    def get_user_profile(limit: int = 20, q: str | None = None) -> list[dict[str, Any]]:
        return to_plain(runtime.get_user_profile(limit=limit, query=q))

    @app.post("/context/compile")
    def compile_context(request: CompileRequest) -> dict[str, Any]:
        return to_plain(
            runtime.compile_context(
                request.task,
                limit=request.limit,
                min_importance=request.min_importance,
                min_confidence=request.min_confidence,
            )
        )

    @app.post("/reflect")
    def reflect(request: ReflectRequest) -> dict[str, Any]:
        return to_plain(runtime.reflect(recent=request.recent))

    return app


def serve(*, host: str, port: int, db_path: Path | str | None = None, config=None) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError('REST API dependencies are missing. Install with: pip install -e ".[api]"') from exc
    app = create_app(db_path=db_path, config=config)
    uvicorn.run(app, host=host, port=port)


def ensure_basic_auth(
    credentials,
    auth_enabled: bool,
    auth_username: str,
    auth_password: str,
) -> None:
    if not auth_enabled:
        return
    if credentials is None:
        raise_auth_error()
    username_ok = secrets.compare_digest(credentials.username, auth_username)
    password_ok = secrets.compare_digest(credentials.password, auth_password)
    if not (username_ok and password_ok):
        raise_auth_error()


def raise_auth_error() -> None:
    from fastapi import HTTPException, status

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid REST API credentials",
        headers={"WWW-Authenticate": "Basic"},
    )
