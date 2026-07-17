from __future__ import annotations

import logging
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from pam_os.config import load_config
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain
from pam_os.version import __version__


logger = logging.getLogger(__name__)
API_VERSION = "v1"
MAX_TEXT_CHARS = 100_000
MAX_QUERY_CHARS = 10_000
MAX_RESULT_LIMIT = 100
MAX_BODY_BYTES = 1_000_000

MemoryType = Literal["semantic", "episodic", "identity", "preference", "goal", "project", "style"]
InspectTable = Literal[
    "all",
    "events",
    "memories",
    "profile_evidence",
    "profile_traits",
    "behavior_events",
    "context_packages",
    "memory_links",
    "policy_signals",
    "quality_traces",
]


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventRequest(ApiRequest):
    content: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    source: str = Field(default="manual", min_length=1, max_length=64)
    source_ref: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)
    extract: bool = True


class SearchRequest(ApiRequest):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    limit: int = Field(default=10, ge=1, le=MAX_RESULT_LIMIT)
    types: list[MemoryType] | None = None
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ShouldUseRequest(ApiRequest):
    task: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    conversation_summary: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


class CompileRequest(ApiRequest):
    task: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    limit: int | None = Field(default=None, ge=1, le=MAX_RESULT_LIMIT)
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PrepareRequest(ApiRequest):
    task: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    conversation_summary: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    force: bool = False
    limit: int | None = Field(default=None, ge=1, le=MAX_RESULT_LIMIT)
    max_chars: int | None = Field(default=None, ge=1, le=100_000)


class CaptureRequest(ApiRequest):
    content: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    source: str = Field(default="conversation", min_length=1, max_length=64)
    source_ref: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)
    force: bool = False


class BehaviorChoiceRequest(ApiRequest):
    context: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    chosen: list[str] = Field(default_factory=list, max_length=100)
    rejected: list[str] = Field(default_factory=list, max_length=100)
    deferred: list[str] = Field(default_factory=list, max_length=100)
    reason: str | None = Field(default=None, max_length=MAX_QUERY_CHARS)
    source_ref: str | None = Field(default=None, max_length=512)


class ObserveTurnRequest(ApiRequest):
    user_message: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    assistant_message: str = Field(default="", max_length=MAX_TEXT_CHARS)
    conversation_summary: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    source_ref: str | None = Field(default=None, max_length=512)
    auto_capture: bool = True
    auto_learn_policy: bool = True


class ConsolidateRequest(ApiRequest):
    recent: int | None = Field(default=None, ge=1, le=10_000)


class ReflectRequest(ApiRequest):
    recent: int = Field(default=50, ge=1, le=10_000)


class ClearMemoryRequest(ApiRequest):
    confirm: bool = False


def create_app(db_path: Path | str | None = None, config=None) -> FastAPI:
    config = config or load_config()
    if config.server.auth_enabled and (not config.server.auth_username or not config.server.auth_password):
        raise RuntimeError("REST API auth is enabled, but server.auth_username or server.auth_password is missing")
    if config.server.host not in {"127.0.0.1", "localhost", "::1"} and not config.server.auth_enabled:
        logger.warning("PAM-OS is configured on a non-loopback host without REST authentication")

    runtime = PersonalMemoryRuntime(db_path=db_path, config=config)
    security = HTTPBasic(auto_error=False)

    def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
        ensure_basic_auth(credentials, config.server.auth_enabled, config.server.auth_username, config.server.auth_password)

    protected = [Depends(require_auth)]
    app = FastAPI(
        title="PAM-OS REST API",
        version=__version__,
        description="REST-only API for the PAM-OS personal memory runtime.",
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "").strip()
        request_id = supplied[:128] if supplied else uuid.uuid4().hex
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                response = error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Invalid Content-Length")
                response.headers["X-Request-ID"] = request_id
                return response
            if body_size < 0:
                response = error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", "Invalid Content-Length")
                response.headers["X-Request-ID"] = request_id
                return response
            if body_size > MAX_BODY_BYTES:
                response = error_response(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "request_too_large",
                    f"Request body exceeds {MAX_BODY_BYTES} bytes",
                )
                response.headers["X-Request-ID"] = request_id
                return response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Request validation failed",
            details=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "unauthorized" if exc.status_code == status.HTTP_401_UNAUTHORIZED else "http_error"
        response = error_response(exc.status_code, code, str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(sqlite3.OperationalError)
    async def sqlite_error_handler(_request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        logger.error("PAM-OS SQLite operation failed", exc_info=(type(exc), exc, exc.__traceback__))
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "storage_unavailable",
            "Memory storage is temporarily unavailable",
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled PAM-OS REST error", exc_info=(type(exc), exc, exc.__traceback__))
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An internal PAM-OS error occurred",
        )

    @app.get("/health/live", tags=["health"], operation_id="health_live")
    def health_live() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "api_version": API_VERSION}

    @app.get("/health", include_in_schema=False, dependencies=protected)
    @app.get("/v1/health/ready", tags=["health"], dependencies=protected, operation_id="health_ready")
    def health_ready() -> dict[str, Any]:
        with runtime.store.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "ok": True,
            "version": __version__,
            "api_version": API_VERSION,
            "fts_available": runtime.store.fts_available,
        }

    @app.get("/v1/meta", tags=["meta"], dependencies=protected, operation_id="get_api_metadata")
    def get_api_metadata() -> dict[str, Any]:
        return {
            "name": "PAM-OS",
            "version": __version__,
            "api_version": API_VERSION,
            "adapter": "rest",
            "capabilities": [
                "prepare_context",
                "capture_memory",
                "observe_turn",
                "search_memory",
                "profile",
                "consolidation",
                "inspection",
            ],
        }

    @app.get("/storage/stats", include_in_schema=False, dependencies=protected)
    @app.get("/v1/storage/stats", tags=["admin"], dependencies=protected, operation_id="get_storage_stats")
    def get_storage_stats() -> dict[str, Any]:
        return to_plain(runtime.get_storage_stats())

    @app.get("/memory/inspect", include_in_schema=False, dependencies=protected)
    @app.get("/v1/memory/inspect", tags=["admin"], dependencies=protected, operation_id="inspect_memory")
    def inspect_memory(
        table: InspectTable = "all",
        limit: int = Query(default=20, ge=1, le=MAX_RESULT_LIMIT),
        q: str | None = Query(default=None, max_length=MAX_QUERY_CHARS),
    ) -> dict[str, Any]:
        return to_plain(runtime.inspect_memory(table=table, limit=limit, query=q))

    @app.post("/memory/clear", include_in_schema=False, dependencies=protected)
    @app.post("/v1/memory/clear", tags=["admin"], dependencies=protected, operation_id="clear_memory")
    def clear_memory(request: ClearMemoryRequest) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true")
        return to_plain(runtime.clear_memory())

    @app.post("/events", include_in_schema=False, dependencies=protected)
    @app.post("/v1/events", tags=["memory"], dependencies=protected, operation_id="create_event")
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

    @app.post("/v1/memories/search", tags=["memory"], dependencies=protected, operation_id="search_memories")
    def search_memory(request: SearchRequest) -> list[dict[str, Any]]:
        return to_plain(
            runtime.search_memory(
                request.query,
                limit=request.limit,
                types=request.types,
                min_importance=request.min_importance,
                min_confidence=request.min_confidence,
            )
        )

    @app.get("/memories/search", include_in_schema=False, dependencies=protected)
    def search_memory_legacy(
        q: str = Query(min_length=1, max_length=MAX_QUERY_CHARS),
        limit: int = Query(default=10, ge=1, le=MAX_RESULT_LIMIT),
        memory_types: list[MemoryType] | None = Query(default=None, alias="type"),
        min_importance: float = Query(default=0.0, ge=0.0, le=1.0),
        min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    ) -> list[dict[str, Any]]:
        return to_plain(
            runtime.search_memory(
                q,
                limit=limit,
                types=memory_types,
                min_importance=min_importance,
                min_confidence=min_confidence,
            )
        )

    @app.post("/v1/memory/should-use", tags=["memory"], dependencies=protected, operation_id="should_use_memory")
    def should_use_memory(request: ShouldUseRequest) -> dict[str, Any]:
        return to_plain(runtime.should_use_memory(request.task, request.conversation_summary))

    @app.get("/memory/should-use", include_in_schema=False, dependencies=protected)
    def should_use_memory_legacy(
        task: str = Query(min_length=1, max_length=MAX_QUERY_CHARS),
        conversation_summary: str | None = Query(default=None, max_length=MAX_TEXT_CHARS),
    ) -> dict[str, Any]:
        return to_plain(runtime.should_use_memory(task, conversation_summary))

    @app.post("/context/prepare", include_in_schema=False, dependencies=protected)
    @app.post("/v1/context/prepare", tags=["context"], dependencies=protected, operation_id="prepare_context")
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

    @app.post("/memory/capture", include_in_schema=False, dependencies=protected)
    @app.post("/v1/memory/capture", tags=["memory"], dependencies=protected, operation_id="capture_memory")
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

    @app.post("/behavior/choice", include_in_schema=False, dependencies=protected)
    @app.post("/v1/behavior/choice", tags=["behavior"], dependencies=protected, operation_id="record_behavior_choice")
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

    @app.post("/turns/observe", include_in_schema=False, dependencies=protected)
    @app.post("/v1/turns/observe", tags=["behavior"], dependencies=protected, operation_id="observe_turn")
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

    @app.post("/memory/consolidate", include_in_schema=False, dependencies=protected)
    @app.post("/v1/memory/consolidate", tags=["admin"], dependencies=protected, operation_id="consolidate_memory")
    def consolidate_memory(request: ConsolidateRequest) -> dict[str, Any]:
        return to_plain(runtime.consolidate_memory(recent=request.recent))

    @app.get("/profile", include_in_schema=False, dependencies=protected)
    @app.get("/v1/profile", tags=["profile"], dependencies=protected, operation_id="get_user_profile")
    def get_user_profile(
        limit: int = Query(default=20, ge=1, le=MAX_RESULT_LIMIT),
        q: str | None = Query(default=None, max_length=MAX_QUERY_CHARS),
    ) -> list[dict[str, Any]]:
        return to_plain(runtime.get_user_profile(limit=limit, query=q))

    @app.post("/context/compile", include_in_schema=False, dependencies=protected)
    @app.post("/v1/context/compile", tags=["context"], dependencies=protected, operation_id="compile_context")
    def compile_context(request: CompileRequest) -> dict[str, Any]:
        return to_plain(
            runtime.compile_context(
                request.task,
                limit=request.limit,
                min_importance=request.min_importance,
                min_confidence=request.min_confidence,
            )
        )

    @app.post("/reflect", include_in_schema=False, dependencies=protected)
    @app.post("/v1/reflect", tags=["admin"], dependencies=protected, operation_id="reflect")
    def reflect(request: ReflectRequest) -> dict[str, Any]:
        return to_plain(runtime.reflect(recent=request.recent))

    return app


def error_response(status_code: int, code: str, message: str, *, details: Any = None) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


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
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid REST API credentials",
        headers={"WWW-Authenticate": "Basic"},
    )
