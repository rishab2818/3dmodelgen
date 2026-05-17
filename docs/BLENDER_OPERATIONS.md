# Blender Operations Catalog

Status: **Draft v1 — for sign-off before M1**

The complete catalog of headless Blender scripts the orchestrator invokes. Every script lives under `blender/scripts/`. Every script obeys the [BACKEND_CONTRACT §3](./BACKEND_CONTRACT.md#3-orchestrator--blender-subprocess) protocol.

---

## Pinned version

**Blender 5.1.x** (detected at `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`).

> ⚠️ Blender 5.0 was a major version with `bpy` API changes vs 4.x:
> - new geometry-nodes attribute model
> - `bpy.ops.import_scene.obj` was renamed to `bpy.ops.wm.obj_import` in 4.0 and that name persists in 5.x
> - default Cycles device handling changed; we always set `cycles.device = 'CPU'` explicitly until the local GPU mode lands
>
> **Do not write Blender scripts that target 4.x syntax.** All scripts here assume 5.x.

---

## Invocation contract

Every script is called as:

```bash
BLENDER_EXE --background --factory-startup --python blender/scripts/{name}.py -- {args...}
```

- `--background` — no UI.
- `--factory-startup` — ignore user prefs. Required for reproducibility.
- Everything after `--` is the script's own argv (parsed with `argparse` against `sys.argv[sys.argv.index("--")+1:]`).

Every script emits its progress JSON on **stderr**, one event per line. stdout is left to Blender's own noise.

---

## Catalog

### `cleanup.py`

**Purpose:** clean up a raw AI-generated mesh.

**Args:**
```
--input PATH           input mesh (.obj or .glb)
--output PATH          output mesh path (.obj or .glb chosen by extension)
--texture PATH         optional, albedo PNG to attach as material
--merge-distance F     default 0.0001
--no-fill-holes        disable hole fill
--no-recalc-normals    disable normal recalc
--no-uv-unwrap         disable UV unwrap pass
--json-progress        emit JSON-on-stderr events
```

**Operations:**
1. Import the mesh (`bpy.ops.wm.obj_import` or `bpy.ops.import_scene.gltf`).
2. Enter Edit mode, select all.
3. Merge by distance.
4. Remove loose: verts with `< 4` linked faces removed.
5. Recalculate normals outside (`bpy.ops.mesh.normals_make_consistent(inside=False)`).
6. Fill small holes via `bpy.ops.mesh.fill_holes(sides=8)`.
7. If `--texture` provided: build a Principled BSDF material with the texture in Base Color.
8. If no UVs present and not `--no-uv-unwrap`: `bpy.ops.uv.smart_project(angle_limit=66.0)`.
9. Export to `--output`.
10. Emit stats: `{vert_count, tri_count, is_manifold, has_uvs, has_material}`.

**Stats JSON also written to:** `{output_dir}/stats.json`.

---

### `render_views.py`

**Purpose:** render a canonical multi-view set for evaluation.

**Args:**
```
--mesh PATH                input mesh (.obj or .glb)
--out  PATH                output directory
--views {default8|dense24|match_input}
--cameras-json PATH        only with --views match_input
--resolution INT           default 512
--engine {cycles|eevee_next}   default cycles
--samples INT              default 32 (cycles only)
--hdri PATH                default blender/hdri/studio_small_09_1k.hdr
--json-progress
```

**Camera setup:**
- `default8`: orthographic cameras at the 8 viewpoints listed in PIPELINE.md §4.
- `dense24`: perspective fov=35°, 24 equator + 4 top + 4 bottom, on a sphere of radius auto-fit to bbox * 1.6.
- `match_input`: load camera matrices from JSON (used in multi-view jobs where we estimated poses upstream).

**Lighting:** HDRI environment + 3-point key/fill/rim.

**Output:**
- `{out}/{view_name}.png` (RGBA, with transparent bg so the silhouette is clean).
- `{out}/manifest.json` mapping view_name → 4×4 camera-to-world matrix.

---

### `bake_texture.py` *(v1.1)*

**Purpose:** bake high-quality PBR textures from generated material.

Held to v1.1. v1 uses generator-supplied textures verbatim.

---

### `mesh_repair.py`

**Purpose:** aggressive repair when `cleanup.py` isn't enough (triggered by `mesh_repair` refinement action).

**Operations on top of cleanup:**
1. Voxel remesh at adaptive resolution (default `voxel_size = bbox_diag / 256`).
2. Smooth corrective (factor 0.2, 4 iterations) — only on regions flagged non-manifold pre-repair.
3. Decimate planar (5°) only if tri count > 200k after remesh.
4. Re-UV (smart project).

**Tradeoff:** remesh can erode fine detail. Only invoked when geometry is broken; not used as a routine step.

---

### `local_inpaint.py` *(v1.1)*

Held — needs an LLM-driven planner to choose the region. Out of v1 scope.

---

### `export_final.py`

**Purpose:** produce the final user-facing exports.

**Args:**
```
--mesh PATH                 source mesh (cleanup output of best iteration)
--out-dir PATH              destination
--formats glb,obj,ply        comma-separated
--texture PATH              optional embedded texture
--hero-render               also produce preview_front.png (1024px Cycles render)
--json-progress
```

**Output rules:**
- `.glb`: textures embedded, Draco compression off (broader compatibility).
- `.obj` + `.mtl` + texture PNGs alongside.
- `.ply`: ASCII, vertex colors if no UV texture, otherwise no colors (PLY texture support is poor across viewers).

---

## Script structure (template)

Every script follows the same skeleton:

```python
# blender/scripts/_template.py
"""Headless Blender op: <one-line purpose>.

This script must run under Blender 5.x bpy. It does NOT import non-bundled
packages — only stdlib + bpy. Anything else lives in the orchestrator.
"""
from __future__ import annotations
import argparse, json, sys, traceback
from pathlib import Path
import bpy

def progress(event: dict) -> None:
    """Emit one progress JSON line on stderr. Caller (orchestrator) tails this."""
    print(json.dumps(event), file=sys.stderr, flush=True)

def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    # ... script-specific args
    p.add_argument("--json-progress", action="store_true")
    return p.parse_args(argv)

def main() -> int:
    args = parse_args()
    try:
        # ... real work, calling progress(...) at meaningful steps
        progress({"event": "done", "ok": True, "outputs": [...], "stats": {...}})
        return 0
    except Exception as e:
        progress({"event": "done", "ok": False, "error": str(e),
                  "traceback": traceback.format_exc()})
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

**Why stdlib-only inside Blender scripts:** Blender 5.x bundles its own Python (3.11.x); installing extras into Blender's Python is brittle on Windows. All heavy lifting (HF models, image processing libs) stays in the orchestrator Python (3.10).

---

## Testing strategy

Each script has a paired test in `blender/tests/test_{script}.py` that runs the actual subprocess on a tiny fixture mesh (under `blender/tests/fixtures/`, < 50 KB). CI installs Blender via apt on Linux and asserts:

- Script exits 0.
- Output file exists and is parseable (trimesh load).
- `stats.json` keys are present.

The test for `render_views.py` does a perceptual hash on the rendered front view vs. a golden reference, with a generous Hamming distance threshold (renders vary slightly across platforms).
