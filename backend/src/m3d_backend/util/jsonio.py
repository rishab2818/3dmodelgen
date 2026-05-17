"""Atomic JSON / marker writers.

The atomic-write pattern is critical for the durability contract: a crash mid-write
must never leave a half-written `.complete` marker (which would cause the stage to be
skipped on resume — silent data loss).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text to ``path``.

    Writes to a sibling temp file, fsyncs, then ``os.replace`` (atomic on Windows + POSIX).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp_name = f.name
    os.replace(tmp_name, path)


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write ``data`` as JSON to ``path``."""
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True, default=str))


def write_stage_complete(marker_path: Path, idempotency_key: str, completed_at_iso: str) -> None:
    """Write a stage's `.complete` marker atomically.

    See docs/RESUMABILITY_AND_BUDGET.md §2.
    """
    atomic_write_json(
        marker_path,
        {"completed_at": completed_at_iso, "idempotency_key": idempotency_key},
    )
