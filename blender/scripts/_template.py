"""Canonical headless-Blender script skeleton. Copy this when adding a new script.

Rules (also in blender/CLAUDE.md):
  - Blender 5.x bpy only.
  - stdlib + bpy only — no pip-installs into Blender's Python.
  - --background --factory-startup invocation.
  - JSON progress on STDERR (one event per line).
  - Final stderr line: {"event":"done","ok":true|false,...}.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback

import bpy  # type: ignore[import-not-found]


def progress(event: dict) -> None:
    """Emit one JSON progress event on stderr."""
    print(json.dumps(event), file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--json-progress", action="store_true")
    return p.parse_args(argv)


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def main() -> int:
    args = parse_args()
    try:
        reset_scene()
        # ... do work, calling progress(...) at meaningful milestones
        progress({"event": "done", "ok": True, "outputs": [], "stats": {}})
        return 0
    except Exception as e:  # noqa: BLE001
        progress({
            "event": "done", "ok": False, "error": str(e),
            "traceback": traceback.format_exc(),
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
