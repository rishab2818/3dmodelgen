"""Shared helpers for headless Blender scripts.

Pure functions / tightly-scoped builders. No global state, no I/O beyond import/export.
See blender/CLAUDE.md §4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]


def clean_factory_scene() -> None:
    """Wipe to a known-empty state. Headless-safe."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_mesh(path: Path):  # type: ignore[no-untyped-def]
    """Format-detect (.obj/.glb/.gltf/.ply) and import. Return the imported object."""
    p = str(path)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=p)
    elif suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=p)
    elif suffix == ".ply":
        bpy.ops.wm.ply_import(filepath=p)
    else:
        raise ValueError(f"Unsupported mesh format: {suffix}")
    # The newly-imported geometry is selected. Pick the active mesh object.
    obj = bpy.context.selected_objects[0] if bpy.context.selected_objects else None
    if obj is None or obj.type != "MESH":
        # Search for any mesh.
        for o in bpy.data.objects:
            if o.type == "MESH":
                obj = o
                break
    if obj is None:
        raise RuntimeError(f"No mesh object found after importing {path}")
    return obj


def export_glb(obj, path: Path) -> None:  # type: ignore[no-untyped-def]
    """Export ``obj`` (and its descendants) as a self-contained .glb."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )


def export_obj(obj, path: Path) -> None:  # type: ignore[no-untyped-def]
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=True)


def mesh_stats(obj) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Return tri/vert counts + manifoldness flags."""
    m = obj.data
    n_verts = len(m.vertices)
    n_tris = sum(1 for p in m.polygons if len(p.vertices) == 3)
    n_quads = sum(1 for p in m.polygons if len(p.vertices) == 4)
    n_ngons = sum(1 for p in m.polygons if len(p.vertices) > 4)
    # Effective tri count (quads count as 2 tris, ngons as n-2).
    tri_count = sum(max(0, len(p.vertices) - 2) for p in m.polygons)
    return {
        "vert_count": n_verts,
        "tri_count": tri_count,
        "face_count": len(m.polygons),
        "n_quads": n_quads,
        "n_ngons": n_ngons,
        "n_native_tris": n_tris,
        "has_uvs": bool(m.uv_layers),
        "has_materials": bool(obj.material_slots),
    }


def write_stats(path: Path, stats: dict[str, Any]) -> None:
    path.write_text(json.dumps(stats, indent=2, sort_keys=True))
