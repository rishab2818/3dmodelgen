# backend

Python orchestrator for `3dmodel_gen`. FastAPI + asyncio + SQLite + SSE. **No torch.**

## Run

```
uv sync --extra dev
uv run uvicorn m3d_backend.app.main:app --reload --port 7878
```

## Test

```
uv run pytest
```

## Lint + typecheck

```
uv run ruff check
uv run ruff format --check
uv run pyright
```

Rules and conventions: see `./CLAUDE.md`.
