"""Shared test fixtures."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run each test against fresh temp/exports/db dirs and the bundled fixture cube."""
    monkeypatch.setenv("M3D_GPU_BACKEND", "mock")
    monkeypatch.setenv("M3D_TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setenv("M3D_EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("M3D_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("M3D_FIXTURES_DIR", str(REPO_ROOT / "ai_models" / "fixtures"))
    monkeypatch.setenv("M3D_MOCK_DELAY_MS", "10")
    monkeypatch.setenv("M3D_MOCK_SCORE_PROFILE", "instant_success")
    monkeypatch.setenv("M3D_LOG_LEVEL", "WARNING")
    # Tests skip rembg's 170 MB model download — preprocessing just resizes.
    monkeypatch.setenv("M3D_BG_REMOVAL_ENABLED", "false")
    monkeypatch.setenv(
        "M3D_BLENDER_EXE",
        os.environ.get(
            "BLENDER_EXE",
            "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe",
        ),
    )
    yield


@pytest.fixture
def png_image(tmp_path: Path) -> Path:
    """A small deterministic PNG. Used as the standard test input image."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=(60, 120, 200, 255))
    p = tmp_path / "input.png"
    img.save(p, format="PNG")
    return p


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An httpx client backed by the real ASGI app + real lifespan (creates the DB)."""
    from m3d_backend.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Manually drive the lifespan so background tasks (job runners) actually start.
        async with app.router.lifespan_context(app):
            yield c
