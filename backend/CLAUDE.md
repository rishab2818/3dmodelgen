# backend/ — Python orchestrator

> Folder-scoped rules. Read `../CLAUDE.md` first.

This folder is the brain. It coordinates preprocessing, AI generation, Blender, evaluation, refinement, and export. It is also the HTTP server the desktop UI talks to.

---

## 1. Stack

| Concern | Choice |
|---|---|
| Runtime | **Python 3.10.x** managed by `uv` |
| Web framework | **FastAPI** + **uvicorn** (standalone, no nginx) |
| Async | **asyncio** + **httpx** + **aiofiles** |
| ORM | **SQLAlchemy 2.x** async + **Alembic** migrations |
| Storage | **SQLite** (WAL) at `./backend/state.db` |
| Data models | **Pydantic v2** |
| Subprocess control | **anyio.open_process** (asyncio-safe) |
| Logging | **structlog** → JSON to stderr + rotating file |
| Config | **pydantic-settings** → `Settings` loaded from env + `.env` |
| Tests | **pytest** + **pytest-asyncio** + **httpx.AsyncClient** |
| Lint/format | **Ruff** (no black, no isort) |
| Type check | **pyright** strict |

`backend/` is **torch-free**. It never imports `torch`, `transformers`, `diffusers`. Those live in `ai_models/` and are reached over HTTP.

---

## 2. Project layout (as of M1)

Single top-level package `m3d_backend` under `src/`. Imports read `from m3d_backend.foo.bar import baz`.

```
backend/
├── pyproject.toml
├── .python-version             3.10
├── src/m3d_backend/
│   ├── app/
│   │   ├── main.py             FastAPI factory + lifespan (entry: m3d_backend.app.main:app)
│   │   ├── settings.py         Pydantic settings (env prefix M3D_)
│   │   ├── deps.py             AppState + GPU backend factory
│   │   └── routes/
│   │       ├── system.py       /health, /config, /models
│   │       ├── jobs.py         POST /jobs, GET /jobs, cancel/pause/resume
│   │       ├── events.py       SSE /jobs/{id}/events
│   │       ├── artifacts.py    sandboxed /jobs/{id}/artifacts + /exports/{id}/{file}
│   │       └── budget.py       /jobs/{id}/budget, /budget, /cache/clear
│   ├── db/
│   │   ├── engine.py           async engine with WAL pragmas
│   │   ├── models.py           SQLAlchemy 2.x models (Job, Iteration, StageRun, GpuCall)
│   │   └── repo.py             typed repository functions
│   ├── events/
│   │   ├── bus.py              in-process pub/sub
│   │   └── shapes.py           Pydantic event models (= SSE wire shapes)
│   ├── pipeline/
│   │   ├── graph.py            stage executor with .complete markers + resume
│   │   ├── artifacts.py        marker helpers
│   │   └── stages/
│   │       ├── preprocess.py
│   │       ├── generate.py
│   │       ├── blender_cleanup.py
│   │       ├── render_multiview.py
│   │       ├── evaluate.py
│   │       ├── refine.py
│   │       └── export.py
│   ├── gpu/
│   │   ├── base.py             GPUBackend Protocol + request/response dataclasses
│   │   └── mock.py             MockGPUBackend (M1)
│   ├── blender_runner.py       headless subprocess runner with stderr-JSON tail
│   └── util/
│       ├── ids.py              UUID + idempotency-key formatter
│       ├── paths.py            per-stage / per-iter path conventions
│       └── jsonio.py           atomic write helpers (the .complete marker primitive)
└── tests/
    ├── conftest.py             ASGI client fixture with isolated tmp dirs
    └── test_smoke_pipeline.py  end-to-end against mock backend (3 tests)
```

`remote.py` (RemoteGPUBackend) lands in M2. Alembic migrations land in M2 alongside the first schema change. M1 creates tables via `Base.metadata.create_all` on first launch.

---

## 3. Important rules

### 3.1 Blender invocation

Always via `blender_runner.run(script_name: str, args: list[str], timeout_s: int = 300)`. **Never** spawn Blender directly. The runner:

- Resolves Blender from `Settings.blender_exe` (env `BLENDER_EXE`). Default on Windows: `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`.
- Passes `--background --factory-startup --python ... -- <args>`.
- Tails stderr line-by-line, parsing JSON events, forwarding them to the event bus.
- Enforces timeout; SIGKILLs cleanly on cancel.

### 3.2 No torch here

Repeat: this folder does not import `torch`, `transformers`, `diffusers`, `triposr`, or any GPU library. If you find yourself wanting to, you are in the wrong folder — that work belongs in `ai_models/` and is reached via HTTP through `gpu/remote.py`.

### 3.3 Long-running work = jobs, not handlers

FastAPI handlers must return in < 1 second. Anything longer is enqueued as a job and progress is streamed via SSE.

### 3.4 SQLite, properly

- WAL mode (`PRAGMA journal_mode=WAL`).
- `PRAGMA synchronous=NORMAL` (we're a desktop app, not a bank).
- One global async engine; one session per request via FastAPI dep.
- All writes through the repo layer (no raw SQL in routes).

### 3.5 Cancellation

Every long-running coroutine respects `asyncio.CancelledError`. Stages clean up partial artifacts on cancel (anything without a `.complete` marker). **Already-completed stages are sacred — never delete them.**

### 3.5.1 Resumability is non-negotiable

Read [`../docs/RESUMABILITY_AND_BUDGET.md`](../docs/RESUMABILITY_AND_BUDGET.md) before touching anything in `pipeline/` or `gpu/`. The rules in short:

- The **last act** of every stage is `temp/{job_id}/iter_{n}/{stage}/.complete` (atomic write → fsync → close).
- All state changes (state.db, .complete marker) for a stage transition go in **one SQLAlchemy transaction**.
- Pause requests are checked **between stages, not inside**. Inside-stage remote calls already in flight are allowed to finish (they're billing anyway).
- The stage executor MUST consult `.complete` markers before invoking a stage. Existing → emit synthetic `cache_hit` event and skip.
- Every remote call carries `Idempotency-Key: {job_id}:{iteration}:{stage}:{call_index}`. Generated from persisted state — deterministic across crashes.
- Every remote call inserts a `gpu_call` row (cached or real). Single source of truth for budget.

If you're tempted to write a stage that doesn't write `.complete` or doesn't pass an idempotency key — stop. That's a regression of the prime directive.

### 3.6 Determinism

- All paths use `pathlib.Path`. No string-concatenated paths.
- All times in UTC, written as ISO 8601.
- Logs are JSON. Field names: `event`, `level`, `job_id`, `stage`, `iteration`, plus context.
- All seeds explicit. Default 42.

---

## 4. Settings

`Settings` (from `src/app/settings.py`):

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="M3D_")

    host: str = "127.0.0.1"
    port: int = 7878
    gpu_backend: Literal["mock", "remote", "local"] = "mock"
    gpu_backend_url: str | None = None    # required for remote
    gpu_backend_token: str | None = None  # bearer
    blender_exe: Path = Path("C:/Program Files/Blender Foundation/Blender 5.1/blender.exe")
    db_url: str = "sqlite+aiosqlite:///./backend/state.db"
    temp_dir: Path = Path("./temp")
    exports_dir: Path = Path("./exports")
    models_cache: Path = Path("./models_cache")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
```

All envs are prefixed `M3D_` so they don't collide with other tools.

---

## 5. Testing

- **Unit:** stages tested with mock event bus + fake artifact directories.
- **Contract:** `test_routes_jobs.py` exercises the HTTP surface with `httpx.AsyncClient` against a real FastAPI test app.
- **Smoke:** `test_pipeline_smoke.py` runs the **full pipeline** end-to-end against `MockGPUBackend` + the real Blender (cleanup.py against a tiny fixture mesh). This must pass on CI within 60 s.

No tests against live remote GPU endpoints (too flaky for CI).

---

## 6. Run + dev

```
uv sync                        # install deps from uv.lock
uv run uvicorn src.app.main:app --reload --port 7878
uv run pytest
uv run ruff check
uv run pyright
```

Tauri's `src-tauri/src/backend.rs` runs `uv run ...` to spawn the backend in production. In dev (`pnpm tauri dev`), the backend can be run manually for faster iteration; Tauri detects an already-running localhost backend and skips its own spawn.
