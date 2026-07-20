from __future__ import annotations

import logging
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Callable, Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from pam_os.config import control_db_path, data_dir, load_config
from pam_os.identity import (
    ADMIN_USERS,
    API_KEYS_MANAGE,
    DEFAULT_USER_SCOPES,
    MEMORY_DELETE,
    MEMORY_INSPECT,
    MEMORY_READ,
    MEMORY_WRITE,
    ControlStore,
    RequestContext,
)
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain
from pam_os.tenancy import UserRuntimeFactory
from pam_os.version import __version__


logger = logging.getLogger(__name__)
API_VERSION = "v2"
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


class CreateUserRequest(ApiRequest):
    username: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    principal_name: str = Field(default="default-agent", min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: sorted(DEFAULT_USER_SCOPES), min_length=1)
    expires_at: str | None = None


class CreateApiKeyRequest(ApiRequest):
    principal_name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: sorted(DEFAULT_USER_SCOPES), min_length=1)
    expires_at: str | None = None


def create_app(
    config=None,
    *,
    data_root: Path | str | None = None,
    control_store: ControlStore | None = None,
    runtime_factory: UserRuntimeFactory | None = None,
) -> FastAPI:
    config = config or load_config()
    root = Path(data_root) if data_root is not None else data_dir(config)
    control = control_store or ControlStore(root / "control.sqlite3" if data_root is not None else control_db_path(config))
    runtimes = runtime_factory or UserRuntimeFactory(root, config)
    bearer = HTTPBearer(auto_error=False)

    if not config.server.bootstrap_token and control.user_count() == 0:
        logger.warning(
            "PAM-OS has no users and no bootstrap token; set PAM_OS_BOOTSTRAP_TOKEN to provision the first user"
        )
    elif config.server.bootstrap_token and control.user_count() > 0:
        logger.warning("PAM_OS_BOOTSTRAP_TOKEN remains enabled after user provisioning; remove it when possible")

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> RequestContext:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise_auth_error()
        token = credentials.credentials.strip()
        context = control.authenticate(token)
        if context is not None:
            return context
        bootstrap_token = config.server.bootstrap_token
        if bootstrap_token and secrets.compare_digest(token, bootstrap_token):
            return RequestContext(
                user_id=None,
                username=None,
                principal_id="bootstrap",
                api_key_id=None,
                scopes=frozenset({ADMIN_USERS}),
            )
        raise_auth_error()

    def require_scope(scope: str, *, user_required: bool = True) -> Callable[..., RequestContext]:
        def dependency(context: RequestContext = Depends(authenticate)) -> RequestContext:
            if not context.has_scope(scope):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing required scope: {scope}")
            if user_required and context.user_id is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A user-bound credential is required")
            return context

        return dependency

    def runtime_for(context: RequestContext) -> PersonalMemoryRuntime:
        if context.user_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A user-bound credential is required")
        return runtimes.for_user(context.user_id)

    app = FastAPI(
        title="PAM-OS REST API",
        version=__version__,
        description="Multi-user REST API for the PAM-OS personal memory runtime.",
    )
    app.state.control_store = control
    app.state.runtime_factory = runtimes

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
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "Request validation failed",
            details=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return error_response(status.HTTP_400_BAD_REQUEST, "invalid_request", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            status.HTTP_401_UNAUTHORIZED: "unauthorized",
            status.HTTP_403_FORBIDDEN: "forbidden",
            status.HTTP_404_NOT_FOUND: "not_found",
        }
        response = error_response(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def sqlite_integrity_error_handler(_request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        logger.info("PAM-OS SQLite constraint rejected a request", exc_info=(type(exc), exc, exc.__traceback__))
        return error_response(status.HTTP_409_CONFLICT, "conflict", "The requested identity already exists")

    @app.exception_handler(sqlite3.OperationalError)
    async def sqlite_error_handler(_request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        logger.error("PAM-OS SQLite operation failed", exc_info=(type(exc), exc, exc.__traceback__))
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "storage_unavailable",
            "PAM-OS storage is temporarily unavailable",
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

    @app.get("/v2/health/ready", tags=["health"], operation_id="health_ready")
    def health_ready(
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> dict[str, Any]:
        runtime = runtime_for(context)
        with control.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        with runtime.store.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "ok": True,
            "version": __version__,
            "api_version": API_VERSION,
            "fts_available": runtime.store.fts_available,
        }

    @app.get("/v2/meta", tags=["meta"], operation_id="get_api_metadata")
    def get_api_metadata(_context: RequestContext = Depends(authenticate)) -> dict[str, Any]:
        return {
            "name": "PAM-OS",
            "version": __version__,
            "api_version": API_VERSION,
            "adapter": "rest",
            "auth": "bearer_api_key",
            "capabilities": [
                "multi_user",
                "prepare_context",
                "capture_memory",
                "observe_turn",
                "search_memory",
                "profile",
                "consolidation",
                "inspection",
            ],
        }

    @app.get("/v2/me", tags=["identity"], operation_id="get_current_identity")
    def get_current_identity(context: RequestContext = Depends(authenticate)) -> dict[str, Any]:
        return {
            "user_id": context.user_id,
            "username": context.username,
            "principal_id": context.principal_id,
            "api_key_id": context.api_key_id,
            "scopes": sorted(context.scopes),
            "bootstrap": context.is_bootstrap,
        }

    @app.post("/v2/admin/users", tags=["admin"], operation_id="create_user")
    def create_user(
        request: CreateUserRequest,
        response: Response,
        context: RequestContext = Depends(require_scope(ADMIN_USERS, user_required=False)),
    ) -> dict[str, Any]:
        provisioned = control.create_user(
            username=request.username,
            display_name=request.display_name,
            principal_name=request.principal_name,
            scopes=request.scopes,
            expires_at=request.expires_at,
        )
        control.record_audit(
            context,
            action="user.create",
            target_type="user",
            target_id=provisioned.user.id,
            metadata={"username": provisioned.user.username},
        )
        response.headers["Cache-Control"] = "no-store"
        return provisioned_user_payload(provisioned)

    @app.post("/v2/admin/users/{user_id}/api-keys", tags=["admin"], operation_id="create_user_api_key")
    def create_user_api_key(
        user_id: str,
        request: CreateApiKeyRequest,
        response: Response,
        context: RequestContext = Depends(require_scope(ADMIN_USERS, user_required=False)),
    ) -> dict[str, Any]:
        principal, api_key = control.issue_api_key(
            user_id=user_id,
            principal_name=request.principal_name,
            scopes=request.scopes,
            expires_at=request.expires_at,
        )
        control.record_audit(
            context,
            action="api_key.create",
            target_type="api_key",
            target_id=api_key.id,
            metadata={"user_id": user_id, "principal_id": principal.id},
        )
        response.headers["Cache-Control"] = "no-store"
        return api_key_payload(principal, api_key)

    @app.post("/v2/me/api-keys", tags=["identity"], operation_id="create_current_user_api_key")
    def create_current_user_api_key(
        request: CreateApiKeyRequest,
        response: Response,
        context: RequestContext = Depends(require_scope(API_KEYS_MANAGE)),
    ) -> dict[str, Any]:
        requested_scopes = frozenset(request.scopes)
        if not requested_scopes.issubset(context.scopes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot grant scopes you do not hold")
        assert context.user_id is not None
        principal, api_key = control.issue_api_key(
            user_id=context.user_id,
            principal_name=request.principal_name,
            scopes=request.scopes,
            expires_at=request.expires_at,
        )
        control.record_audit(
            context,
            action="api_key.create",
            target_type="api_key",
            target_id=api_key.id,
            metadata={"principal_id": principal.id},
        )
        response.headers["Cache-Control"] = "no-store"
        return api_key_payload(principal, api_key)

    @app.delete("/v2/me/api-keys/{api_key_id}", tags=["identity"], operation_id="revoke_current_user_api_key")
    def revoke_current_user_api_key(
        api_key_id: str,
        context: RequestContext = Depends(require_scope(API_KEYS_MANAGE)),
    ) -> dict[str, Any]:
        assert context.user_id is not None
        if not control.revoke_api_key_for_user(api_key_id=api_key_id, user_id=context.user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        control.record_audit(
            context,
            action="api_key.revoke",
            target_type="api_key",
            target_id=api_key_id,
        )
        return {"revoked": True, "api_key_id": api_key_id}

    @app.get("/v2/storage/stats", tags=["maintenance"], operation_id="get_storage_stats")
    def get_storage_stats(context: RequestContext = Depends(require_scope(MEMORY_INSPECT))) -> dict[str, Any]:
        payload = to_plain(runtime_for(context).get_storage_stats())
        payload.pop("db_path", None)
        payload["user_id"] = context.user_id
        return payload

    @app.get("/v2/memory/inspect", tags=["maintenance"], operation_id="inspect_memory")
    def inspect_memory(
        table: InspectTable = "all",
        limit: int = Query(default=20, ge=1, le=MAX_RESULT_LIMIT),
        q: str | None = Query(default=None, max_length=MAX_QUERY_CHARS),
        context: RequestContext = Depends(require_scope(MEMORY_INSPECT)),
    ) -> dict[str, Any]:
        payload = to_plain(runtime_for(context).inspect_memory(table=table, limit=limit, query=q))
        payload.get("stats", {}).pop("db_path", None)
        return payload

    @app.post("/v2/memory/clear", tags=["maintenance"], operation_id="clear_memory")
    def clear_memory(
        request: ClearMemoryRequest,
        context: RequestContext = Depends(require_scope(MEMORY_DELETE)),
    ) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true")
        payload = to_plain(runtime_for(context).clear_memory())
        payload.get("storage_stats", {}).pop("db_path", None)
        control.record_audit(context, action="memory.clear", target_type="user", target_id=context.user_id)
        return payload

    @app.post("/v2/events", tags=["memory"], operation_id="create_event")
    def remember(
        request: EventRequest,
        context: RequestContext = Depends(require_scope(MEMORY_WRITE)),
    ) -> dict[str, Any]:
        return to_plain(
            runtime_for(context).remember(
                request.content,
                source=request.source,
                source_ref=request.source_ref,
                metadata=with_actor_metadata(request.metadata, context),
                extract=request.extract,
            )
        )

    @app.post("/v2/memories/search", tags=["memory"], operation_id="search_memories")
    def search_memory(
        request: SearchRequest,
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> list[dict[str, Any]]:
        return to_plain(
            runtime_for(context).search_memory(
                request.query,
                limit=request.limit,
                types=request.types,
                min_importance=request.min_importance,
                min_confidence=request.min_confidence,
            )
        )

    @app.post("/v2/memory/should-use", tags=["memory"], operation_id="should_use_memory")
    def should_use_memory(
        request: ShouldUseRequest,
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> dict[str, Any]:
        return to_plain(runtime_for(context).should_use_memory(request.task, request.conversation_summary))

    @app.post("/v2/context/prepare", tags=["context"], operation_id="prepare_context")
    def prepare_context(
        request: PrepareRequest,
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> dict[str, Any]:
        return to_plain(
            runtime_for(context).prepare_context(
                request.task,
                conversation_summary=request.conversation_summary,
                force=request.force,
                limit=request.limit,
                max_chars=request.max_chars,
            )
        )

    @app.post("/v2/memory/capture", tags=["memory"], operation_id="capture_memory")
    def capture_memory(
        request: CaptureRequest,
        context: RequestContext = Depends(require_scope(MEMORY_WRITE)),
    ) -> dict[str, Any]:
        return to_plain(
            runtime_for(context).capture_memory(
                request.content,
                source=request.source,
                source_ref=request.source_ref,
                metadata=with_actor_metadata(request.metadata, context),
                force=request.force,
            )
        )

    @app.post("/v2/behavior/choice", tags=["behavior"], operation_id="record_behavior_choice")
    def record_behavior_choice(
        request: BehaviorChoiceRequest,
        context: RequestContext = Depends(require_scope(MEMORY_WRITE)),
    ) -> dict[str, Any]:
        return to_plain(
            runtime_for(context).record_behavior_choice(
                context=request.context,
                chosen=request.chosen,
                rejected=request.rejected,
                deferred=request.deferred,
                reason=request.reason,
                source_ref=request.source_ref,
            )
        )

    @app.post("/v2/turns/observe", tags=["behavior"], operation_id="observe_turn")
    def observe_turn(
        request: ObserveTurnRequest,
        context: RequestContext = Depends(require_scope(MEMORY_WRITE)),
    ) -> dict[str, Any]:
        return to_plain(
            runtime_for(context).observe_turn(
                user_message=request.user_message,
                assistant_message=request.assistant_message,
                conversation_summary=request.conversation_summary,
                source_ref=request.source_ref,
                auto_capture=request.auto_capture,
                auto_learn_policy=request.auto_learn_policy,
            )
        )

    @app.post("/v2/memory/consolidate", tags=["maintenance"], operation_id="consolidate_memory")
    def consolidate_memory(
        request: ConsolidateRequest,
        context: RequestContext = Depends(require_scope(MEMORY_WRITE)),
    ) -> dict[str, Any]:
        return to_plain(runtime_for(context).consolidate_memory(recent=request.recent))

    @app.get("/v2/profile", tags=["profile"], operation_id="get_user_profile")
    def get_user_profile(
        limit: int = Query(default=20, ge=1, le=MAX_RESULT_LIMIT),
        q: str | None = Query(default=None, max_length=MAX_QUERY_CHARS),
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> list[dict[str, Any]]:
        return to_plain(runtime_for(context).get_user_profile(limit=limit, query=q))

    @app.post("/v2/context/compile", tags=["context"], operation_id="compile_context")
    def compile_context(
        request: CompileRequest,
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> dict[str, Any]:
        return to_plain(
            runtime_for(context).compile_context(
                request.task,
                limit=request.limit,
                min_importance=request.min_importance,
                min_confidence=request.min_confidence,
            )
        )

    @app.post("/v2/reflect", tags=["maintenance"], operation_id="reflect")
    def reflect(
        request: ReflectRequest,
        context: RequestContext = Depends(require_scope(MEMORY_READ)),
    ) -> dict[str, Any]:
        return to_plain(runtime_for(context).reflect(recent=request.recent))

    return app


def with_actor_metadata(metadata: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return {
        **metadata,
        "authenticated_principal_id": context.principal_id,
    }


def provisioned_user_payload(provisioned) -> dict[str, Any]:
    return {
        "user": to_plain(provisioned.user),
        "principal": to_plain(provisioned.principal),
        "api_key": {
            "id": provisioned.api_key.id,
            "token": provisioned.api_key.token,
            "prefix": provisioned.api_key.prefix,
            "scopes": sorted(provisioned.api_key.scopes),
            "expires_at": provisioned.api_key.expires_at,
            "created_at": provisioned.api_key.created_at,
        },
    }


def api_key_payload(principal, api_key) -> dict[str, Any]:
    return {
        "principal": to_plain(principal),
        "api_key": {
            "id": api_key.id,
            "token": api_key.token,
            "prefix": api_key.prefix,
            "scopes": sorted(api_key.scopes),
            "expires_at": api_key.expires_at,
            "created_at": api_key.created_at,
        },
    }


def error_response(status_code: int, code: str, message: str, *, details: Any = None) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def raise_auth_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )
