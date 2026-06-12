import re
import secrets
from pathlib import Path
from typing import Any

from pam_os.config import load_config
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain
from pam_os.version import __version__


def create_app(db_path: Path | str | None = None, config=None):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
        from fastapi.security import HTTPBasic, HTTPBasicCredentials
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError('REST API dependencies are missing. Install with: pip install -e ".[api]"') from exc

    config = config or load_config()
    if config.server.auth_enabled and (not config.server.auth_username or not config.server.auth_password):
        raise RuntimeError("REST API auth is enabled, but server.auth_username or server.auth_password is missing")

    runtime = PersonalMemoryRuntime(db_path=db_path, config=config)
    user_runtimes: dict[str, PersonalMemoryRuntime] = {}
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
        user_id: str | None = None

    class CompileRequest(BaseModel):
        task: str
        limit: int | None = None
        min_importance: float = 0.0
        min_confidence: float = 0.0
        user_id: str | None = None

    class PrepareRequest(BaseModel):
        task: str
        conversation_summary: str | None = None
        force: bool = False
        limit: int | None = None
        max_chars: int | None = None
        user_id: str | None = None

    class CaptureRequest(BaseModel):
        content: str
        source: str = "conversation"
        source_ref: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)
        force: bool = False
        user_id: str | None = None

    class BehaviorChoiceRequest(BaseModel):
        context: str
        chosen: list[str] = Field(default_factory=list)
        rejected: list[str] = Field(default_factory=list)
        deferred: list[str] = Field(default_factory=list)
        reason: str | None = None
        source_ref: str | None = None
        user_id: str | None = None

    class ObserveTurnRequest(BaseModel):
        user_message: str
        assistant_message: str = ""
        conversation_summary: str | None = None
        source_ref: str | None = None
        auto_capture: bool = True
        auto_learn_policy: bool = True
        user_id: str | None = None

    class ConsolidateRequest(BaseModel):
        recent: int | None = None
        user_id: str | None = None

    class ReflectRequest(BaseModel):
        recent: int = 50
        user_id: str | None = None

    class ClearMemoryRequest(BaseModel):
        confirm: bool = False
        user_id: str | None = None

    def runtime_for_user(user_id: str | None) -> PersonalMemoryRuntime:
        if user_id is None:
            return runtime
        cached = user_runtimes.get(user_id)
        if cached is not None:
            return cached
        scoped = PersonalMemoryRuntime(db_path=scoped_user_db_path(runtime.db_path, user_id), config=config)
        user_runtimes[user_id] = scoped
        return scoped

    def request_user(explicit_user_id: str | None = None, header_user_id: Any = None) -> str | None:
        return normalize_rest_user_id(explicit_user_id or _string_or_none(header_user_id))

    @app.get("/health")
    def health(
        user_id: str | None = None,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(user_id, x_pam_os_user)
        scoped = runtime_for_user(user)
        return {
            "ok": True,
            "user_id": user or "default",
            "db_path": str(scoped.db_path),
            "fts_available": scoped.store.fts_available,
        }

    @app.get("/storage/stats")
    def get_storage_stats(
        user_id: str | None = None,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(user_id, x_pam_os_user)
        payload = to_plain(runtime_for_user(user).get_storage_stats())
        payload["user_id"] = user or "default"
        return payload

    @app.get("/memory/inspect")
    def inspect_memory(
        table: str = "all",
        limit: int = 20,
        q: str | None = None,
        user_id: str | None = None,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(user_id, x_pam_os_user)
        try:
            payload = to_plain(runtime_for_user(user).inspect_memory(table=table, limit=limit, query=q))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        payload["user_id"] = user or "default"
        return payload

    @app.post("/memory/clear")
    def clear_memory(
        request: ClearMemoryRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true")
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        payload = to_plain(runtime_for_user(user).clear_memory())
        payload["user_id"] = user or "default"
        return payload

    @app.post("/events")
    def remember(
        request: EventRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(
            runtime_for_user(user).remember(
                request.content,
                source=request.source,
                source_ref=request.source_ref,
                metadata=with_rest_user_metadata(request.metadata, user),
                extract=request.extract,
            )
        )

    @app.get("/memories/search")
    def search_memory(
        q: str,
        limit: int = 10,
        memory_types: list[str] | None = Query(default=None, alias="type"),
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
        user_id: str | None = None,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> list[dict[str, Any]]:
        user = request_user(user_id, x_pam_os_user)
        return to_plain(
            runtime_for_user(user).search_memory(
                q,
                limit=limit,
                types=memory_types,
                min_importance=min_importance,
                min_confidence=min_confidence,
            )
        )

    @app.get("/memory/should-use")
    def should_use_memory(
        task: str,
        conversation_summary: str | None = None,
        user_id: str | None = None,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(user_id, x_pam_os_user)
        return to_plain(runtime_for_user(user).should_use_memory(task, conversation_summary))

    @app.post("/context/prepare")
    def prepare_context(
        request: PrepareRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(
            runtime_for_user(user).prepare_context(
                request.task,
                conversation_summary=request.conversation_summary,
                force=request.force,
                limit=request.limit,
                max_chars=request.max_chars,
            )
        )

    @app.post("/memory/capture")
    def capture_memory(
        request: CaptureRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(
            runtime_for_user(user).capture_memory(
                request.content,
                source=request.source,
                source_ref=request.source_ref,
                metadata=with_rest_user_metadata(request.metadata, user),
                force=request.force,
            )
        )

    @app.post("/behavior/choice")
    def record_behavior_choice(
        request: BehaviorChoiceRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(
            runtime_for_user(user).record_behavior_choice(
                context=request.context,
                chosen=request.chosen,
                rejected=request.rejected,
                deferred=request.deferred,
                reason=request.reason,
                source_ref=request.source_ref,
            )
        )

    @app.post("/turns/observe")
    def observe_turn(
        request: ObserveTurnRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(
            runtime_for_user(user).observe_turn(
                user_message=request.user_message,
                assistant_message=request.assistant_message,
                conversation_summary=request.conversation_summary,
                source_ref=request.source_ref,
                auto_capture=request.auto_capture,
                auto_learn_policy=request.auto_learn_policy,
            )
        )

    @app.post("/memory/consolidate")
    def consolidate_memory(
        request: ConsolidateRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(runtime_for_user(user).consolidate_memory(recent=request.recent))

    @app.get("/profile")
    def get_user_profile(
        limit: int = 20,
        q: str | None = None,
        user_id: str | None = None,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> list[dict[str, Any]]:
        user = request_user(user_id, x_pam_os_user)
        return to_plain(runtime_for_user(user).get_user_profile(limit=limit, query=q))

    @app.post("/context/compile")
    def compile_context(
        request: CompileRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(
            runtime_for_user(user).compile_context(
                request.task,
                limit=request.limit,
                min_importance=request.min_importance,
                min_confidence=request.min_confidence,
            )
        )

    @app.post("/reflect")
    def reflect(
        request: ReflectRequest,
        x_pam_os_user: Any = Header(default=None, alias="X-PAM-OS-User"),
    ) -> dict[str, Any]:
        user = request_user(getattr(request, "user_id", None), x_pam_os_user)
        return to_plain(runtime_for_user(user).reflect(recent=request.recent))

    return app


REST_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")


def normalize_rest_user_id(user_id: Any) -> str | None:
    if not isinstance(user_id, str):
        return None
    normalized = user_id.strip()
    if not normalized or normalized == "default":
        return None
    if not REST_USER_ID_PATTERN.fullmatch(normalized):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id must match [A-Za-z0-9][A-Za-z0-9_.@-]{0,127}",
        )
    return normalized


def scoped_user_db_path(base_db_path: Path | str, user_id: str) -> Path:
    base = Path(base_db_path)
    safe_user_id = normalize_rest_user_id(user_id)
    if safe_user_id is None:
        return base
    return base.with_name(f"{base.stem}.{safe_user_id}{base.suffix}")


def with_rest_user_metadata(metadata: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    if user_id is None:
        return metadata
    return {**metadata, "user_id": user_id, "rest_user_id": user_id}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


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
