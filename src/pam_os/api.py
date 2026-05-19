from __future__ import annotations

from pathlib import Path
from typing import Any

from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain


def create_app(db_path: Path | str | None = None):
    try:
        from fastapi import FastAPI
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError('REST API dependencies are missing. Install with: pip install -e ".[api]"') from exc

    runtime = PersonalMemoryRuntime(db_path=db_path)
    app = FastAPI(title="Personal Memory Runtime", version="0.1.0")

    class EventRequest(BaseModel):
        content: str
        source: str = "manual"
        source_ref: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)
        extract: bool = True

    class CompileRequest(BaseModel):
        task: str
        limit: int = 12
        min_importance: float = 0.0
        min_confidence: float = 0.0

    class ReflectRequest(BaseModel):
        recent: int = 50

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "db_path": str(runtime.db_path), "fts_available": runtime.store.fts_available}

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


def serve(*, host: str, port: int, db_path: Path | str | None = None) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError('REST API dependencies are missing. Install with: pip install -e ".[api]"') from exc
    app = create_app(db_path=db_path)
    uvicorn.run(app, host=host, port=port)
