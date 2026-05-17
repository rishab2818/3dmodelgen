# blender/ — Headless Blender scripts

> Folder-scoped rules. Read `../CLAUDE.md` first. Catalog of scripts in [`../docs/BLENDER_OPERATIONS.md`](../docs/BLENDER_OPERATIONS.md).

---

## 1. The non-negotiables

1. **Blender 5.1+ only.** Do not write 4.x-compatible code. Operator names have changed; APIs have changed.
2. **Stdlib + bpy only.** No pip-installing into Blender's Python. All heavy lifting (HF models, image processing libs) lives in the orchestrator process.
3. **Headless, always.** Every script is invoked with `--background --factory-startup`.
4. **JSON progress on stderr.** stdout is left to Blender's noise. One event per line. Final event is `{"event": "done", "ok": true|false, ...}`.
5. **Idempotent.** Running the same script with the same inputs produces the same output. No timestamps in filenames.
6. **No side effects on the user's Blender install.** No writes outside the artifact directory passed in via `--output`.

---

## 2. Folder layout

```
blender/
├── scripts/
│   ├── _template.py         # canonical skeleton; copy this for new scripts
│   ├── _bpy_helpers.py      # shared helpers (camera setup, lighting, exporters)
│   ├── cleanup.py
│   ├── render_views.py
│   ├── mesh_repair.py
│   ├── export_final.py
│   └── bake_texture.py      # v1.1 placeholder, raises NotImplementedError
├── hdri/
│   └── studio_small_09_1k.hdr   # bundled HDRI for lighting; Polyhaven CC0
├── tests/
│   ├── fixtures/
│   │   ├── cube.obj
│   │   └── monkey.obj
│   ├── test_cleanup.py
│   ├── test_render_views.py
│   └── conftest.py
└── README.md                # this file's audience is humans; technical detail is in ../docs/BLENDER_OPERATIONS.md
```

---

## 3. The script skeleton

Every script begins with this skeleton (in `_template.py`):

```python
"""<one-line purpose>.

This script must run under Blender 5.x bpy. stdlib + bpy only.
"""
from __future__ import annotations
import argparse, json, sys, traceback
from pathlib import Path
import bpy

def progress(event: dict) -> None:
    print(json.dumps(event), file=sys.stderr, flush=True)

def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    # ... script-specific args
    p.add_argument("--json-progress", action="store_true")
    return p.parse_args(argv)

def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)

def main() -> int:
    args = parse_args()
    try:
        reset_scene()
        # work...
        progress({"event": "done", "ok": True, "outputs": [...], "stats": {...}})
        return 0
    except Exception as e:
        progress({"event": "done", "ok": False, "error": str(e),
                  "traceback": traceback.format_exc()})
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

---

## 4. Shared helpers (`_bpy_helpers.py`)

These are the only "internal library" allowed. Each helper is a pure function or a tightly-scoped builder:

| Helper | Purpose |
|---|---|
| `clean_factory_scene()` | wipe scene + collections to a known-empty state |
| `import_mesh(path) -> bpy.types.Object` | format-detect (.obj/.glb/.ply) and import; return the new object |
| `setup_camera(view: str, target: Object, distance: float)` | one of the canonical 8 views |
| `setup_three_point_lighting()` | key + fill + rim |
| `set_world_hdri(path)` | sky/env from an HDRI |
| `apply_material_albedo(obj, png_path)` | Principled BSDF with texture |
| `export_glb(obj, path)` / `export_obj(...)` / `export_ply(...)` | format-specific export |
| `mesh_stats(obj) -> dict` | tri/vert counts, manifold flags, bbox |

No helper does I/O outside of import/export. No helper mutates global state implicitly.

---

## 5. Operator API drift checklist (5.x vs 4.x)

When porting examples from older docs/StackOverflow, watch for:

| Old (4.x) | New (5.x) |
|---|---|
| `bpy.ops.import_scene.obj(filepath=...)` | `bpy.ops.wm.obj_import(filepath=...)` |
| `bpy.ops.export_scene.obj(...)` | `bpy.ops.wm.obj_export(...)` |
| `bpy.ops.import_scene.gltf` (still works) | unchanged |
| `mesh.calc_normals()` | `mesh.calc_normals_split()` for per-loop, otherwise normals are auto-managed |
| `cycles.device = 'GPU'` (forced) | explicitly set per-call; default to `'CPU'` until local-GPU mode |

If you see the older API in any committed script, fix it — that's a bug.

---

## 6. Performance

Scripts run inside short-lived subprocesses. We don't need to obsess about cold start (Blender takes ~1.5 s to boot headless and that's the floor). But:

- **Avoid `--addons` loads.** `--factory-startup` already disables them; do not re-enable inside the script.
- **Avoid the depsgraph evaluation in loops.** Build geometry first, then access the evaluated mesh once.
- **Disable Cycles GPU code paths in 5.x:** set `bpy.context.scene.cycles.device = 'CPU'`. Until M6 local GPU mode lands, we want consistent CPU-only renders so output is identical between machines.

---

## 7. Tests

Each script has a paired test that runs the actual subprocess:

```python
def test_cleanup_runs_and_emits_done(tmp_path):
    out = tmp_path / "cleaned.obj"
    result = subprocess.run(
        [BLENDER_EXE, "--background", "--factory-startup",
         "--python", "blender/scripts/cleanup.py", "--",
         "--input", "blender/tests/fixtures/cube.obj",
         "--output", str(out), "--json-progress"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0
    assert out.exists()
    # last stderr line is the done event
    last = next(line for line in reversed(result.stderr.splitlines()) if line.strip())
    event = json.loads(last)
    assert event["event"] == "done" and event["ok"] is True
```

CI installs Blender 5.1 on Linux runners via apt + the Blender Foundation PPA.

---

## 8. Things you might be tempted to do, and shouldn't

- **Install `numpy` or `Pillow` into Blender's Python.** No. Move that logic into the orchestrator.
- **Use `bpy.app.handlers`.** Headless scripts don't need handlers; the orchestrator drives the lifecycle.
- **Persist state in `.blend` files between calls.** No. Every call is a fresh process. State flows via files (input mesh → output mesh).
- **Open a GUI even briefly.** `--background` means no UI; do not call any `ops` that require a window context.
