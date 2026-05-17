"""Headless Blender subprocess invocation with JSON-on-stderr progress.

See docs/BACKEND_CONTRACT.md §3 and blender/CLAUDE.md.

This module is the *only* place that spawns Blender. All scripts must follow the
``--background --factory-startup`` + stderr-JSON protocol; this runner enforces it on the
orchestrator side.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class BlenderProgress:
    progress: float | None = None
    msg: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BlenderRunResult:
    ok: bool
    exit_code: int
    outputs: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    traceback: str | None = None


async def run_blender_script(
    *,
    blender_exe: Path,
    script: Path,
    args: list[str],
    timeout_s: int = 300,
    on_progress: "asyncio.Queue[BlenderProgress] | None" = None,
) -> BlenderRunResult:
    """Run a Blender Python script headlessly.

    The runner:
      1. Builds the standard argv: ``blender --background --factory-startup --python S -- <args>``.
      2. Streams stderr line-by-line, parsing JSON progress events.
      3. Enforces a hard timeout (default 5 min).
      4. Returns the parsed ``done`` event as a :class:`BlenderRunResult`.

    Stdout is left for Blender's own noise — we do not parse it.
    """
    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found at {blender_exe}")
    if not script.exists():
        raise FileNotFoundError(f"Blender script not found at {script}")

    cmd = [
        str(blender_exe),
        "--background",
        "--factory-startup",
        "--python",
        str(script),
        "--",
        *args,
    ]
    log.info("blender.spawn", cmd=" ".join(shlex.quote(c) for c in cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    done_event: dict[str, Any] | None = None

    async def _drain() -> None:
        nonlocal done_event
        assert proc.stderr is not None  # noqa: S101
        async for line in _iter_lines(proc.stderr):
            line = line.strip()
            if not line:
                continue
            event = _try_json(line)
            if event is None:
                # Blender's non-JSON stderr chatter. Log at debug; do not surface.
                log.debug("blender.stderr", raw=line[:200])
                continue
            if event.get("event") == "progress":
                if on_progress is not None:
                    await on_progress.put(
                        BlenderProgress(
                            progress=event.get("progress"),
                            msg=event.get("msg", ""),
                            raw=event,
                        ),
                    )
            elif event.get("event") == "done":
                done_event = event

    try:
        await asyncio.wait_for(_drain(), timeout=timeout_s)
        exit_code = await proc.wait()
    except asyncio.TimeoutError:
        log.warning("blender.timeout", timeout_s=timeout_s)
        proc.kill()
        await proc.wait()
        return BlenderRunResult(
            ok=False,
            exit_code=-1,
            error=f"Blender exceeded {timeout_s}s timeout",
        )

    if done_event is None:
        return BlenderRunResult(
            ok=False,
            exit_code=exit_code,
            error="Blender script did not emit a 'done' event",
        )

    return BlenderRunResult(
        ok=bool(done_event.get("ok")),
        exit_code=exit_code,
        outputs=list(done_event.get("outputs", [])),
        stats=dict(done_event.get("stats", {})),
        error=done_event.get("error"),
        traceback=done_event.get("traceback"),
    )


async def _iter_lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    while True:
        raw = await stream.readline()
        if not raw:
            return
        yield raw.decode("utf-8", errors="replace")


def _try_json(line: str) -> dict[str, Any] | None:
    if not line.startswith("{"):
        return None
    try:
        v = json.loads(line)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None
