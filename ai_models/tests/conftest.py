"""ai_models test fixtures."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ai_models" / "src"))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M3D_AI_PRIMARY_GENERATOR", "mock")
    # No auth in tests (the orchestrator's default config also leaves the token unset).
    monkeypatch.delenv("M3D_AI_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("M3D_AI_LOG_LEVEL", "WARNING")


@pytest_asyncio.fixture
async def server_client() -> AsyncIterator[AsyncClient]:
    """An httpx client wired to the in-process remote_server via ASGITransport."""
    from m3d_ai.remote_server import create_app  # imported lazily so env is applied

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c
