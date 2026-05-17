"""FastAPI application factory + ASGI entrypoint.

Run in dev:

    uv run uvicorn m3d_backend.app.main:app --reload --port 7878

The Tauri shell spawns this same module in production.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from m3d_backend.app.deps import AppState, make_gpu_backend
from m3d_backend.app.routes import artifacts, budget, events, jobs, system
from m3d_backend.app.settings import Settings
from m3d_backend.db.engine import init_db, make_engine, make_sessionmaker
from m3d_backend.events.bus import EventBus


def _configure_logging(level: str, json_logs: bool) -> None:
    logging.basicConfig(
        level=level, stream=sys.stderr, format="%(message)s",
    )
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )


def _detect_repo_root(start: Path | None = None) -> Path:
    """Walk up from this file to find the directory containing 'blender/'."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "blender" / "scripts").is_dir():
            return candidate
    return Path.cwd()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    _configure_logging(settings.log_level, settings.log_json)
    log = structlog.get_logger("m3d_backend")

    settings.ensure_dirs()

    engine = make_engine(settings.db_url)
    session_factory = make_sessionmaker(engine)
    await init_db(engine)

    bus = EventBus()
    backend = make_gpu_backend(settings)

    repo_root = _detect_repo_root()

    app.state.app = AppState(
        settings=settings,
        repo_root=repo_root,
        engine=engine,
        session_factory=session_factory,
        bus=bus,
        backend=backend,
    )
    app.state.tasks = set()  # background job runners

    log.info(
        "backend.start",
        port=settings.port,
        gpu_backend=settings.gpu_backend,
        repo_root=str(repo_root),
        blender_exe=str(settings.blender_exe),
    )
    try:
        yield
    finally:
        # Cancel outstanding background jobs cleanly.
        for t in list(app.state.tasks):
            t.cancel()
        await asyncio.gather(*app.state.tasks, return_exceptions=True)
        await engine.dispose()
        log.info("backend.stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="3dmodel_gen orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )
    # Allow the Tauri webview's origin to call us. localhost only.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420", "http://127.0.0.1:1420",   # tauri dev
            "tauri://localhost",                                 # tauri prod webview
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router)
    app.include_router(jobs.router)
    app.include_router(events.router)
    app.include_router(artifacts.router)
    app.include_router(budget.router)
    return app


app = create_app()
