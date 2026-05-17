"""Headless Blender op: clean up a raw AI-generated mesh.

See docs/BLENDER_OPERATIONS.md for the full catalog entry. M1 implements the
default-on subset: merge by distance, remove loose, recalc normals outside,
fill small holes, optional UV unwrap, then export to ``--output``.

Invocation:

    blender --background --factory-startup --python cleanup.py -- \\
        --input  in_mesh.obj \\
        --output out_mesh.glb \\
        [--texture albedo.png] \\
        [--merge-distance 0.0001] \\
        [--no-fill-holes] [--no-recalc-normals] [--no-uv-unwrap] \\
        [--json-progress]
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy  # type: ignore[import-not-found]

# Make sibling helper module importable when invoked via --python.
sys.path.insert(0, str(Path(__file__).parent))
from _bpy_helpers import (  # noqa: E402
    clean_factory_scene,
    export_glb,
    export_obj,
    import_mesh,
    mesh_stats,
    write_stats,
)


def progress(event: dict) -> None:
    print(json.dumps(event), file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--texture", type=Path, default=None)
    p.add_argument("--merge-distance", type=float, default=0.0001)
    p.add_argument("--no-fill-holes", action="store_true")
    p.add_argument("--no-recalc-normals", action="store_true")
    p.add_argument("--no-uv-unwrap", action="store_true")
    p.add_argument("--json-progress", action="store_true")
    return p.parse_args(argv)


def _apply_texture(obj, texture: Path) -> None:  # type: ignore[no-untyped-def]
    mat = bpy.data.materials.new("AlbedoMat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex_node = nt.nodes.new("ShaderNodeTexImage")
    tex_node.image = bpy.data.images.load(str(texture))
    nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    if not obj.material_slots:
        obj.data.materials.append(mat)
    else:
        obj.material_slots[0].material = mat


def main() -> int:
    args = parse_args()
    try:
        progress({"event": "progress", "progress": 0.05, "msg": "Loading"})
        clean_factory_scene()
        obj = import_mesh(args.input)
        progress({"event": "progress", "progress": 0.25, "msg": "Imported"})

        # Operations happen in Edit mode.
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        # 1. Merge by distance.
        bpy.ops.mesh.remove_doubles(threshold=args.merge_distance)
        progress({"event": "progress", "progress": 0.40, "msg": "Merged duplicates"})

        # 2. Recalculate normals outside.
        if not args.no_recalc_normals:
            bpy.ops.mesh.normals_make_consistent(inside=False)
            progress({"event": "progress", "progress": 0.55, "msg": "Recalced normals"})

        # 3. Fill small holes.
        if not args.no_fill_holes:
            bpy.ops.mesh.fill_holes(sides=8)
            progress({"event": "progress", "progress": 0.65, "msg": "Filled holes"})

        # 4. UV unwrap if no UVs present.
        had_uvs = bool(obj.data.uv_layers)
        if not had_uvs and not args.no_uv_unwrap:
            bpy.ops.uv.smart_project(angle_limit=1.15)  # 66 deg in radians
            progress({"event": "progress", "progress": 0.75, "msg": "UV-unwrapped"})

        bpy.ops.object.mode_set(mode="OBJECT")

        # 5. Remove loose geometry: tiny islands.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_loose()
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        progress({"event": "progress", "progress": 0.82, "msg": "Removed loose"})

        # 6. Apply texture if provided.
        if args.texture is not None and args.texture.exists():
            _apply_texture(obj, args.texture)

        # 7. Export.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        suffix = args.output.suffix.lower()
        if suffix == ".glb":
            export_glb(obj, args.output)
        elif suffix == ".obj":
            export_obj(obj, args.output)
        else:
            raise ValueError(f"Unsupported output format: {suffix}")
        progress({"event": "progress", "progress": 0.95, "msg": "Exported"})

        # 8. Stats.
        stats = mesh_stats(obj)
        write_stats(args.output.with_name("stats.json"), stats)

        progress({
            "event": "done", "ok": True,
            "outputs": [str(args.output)],
            "stats": stats,
        })
        return 0

    except Exception as e:  # noqa: BLE001
        progress({
            "event": "done", "ok": False, "error": str(e),
            "traceback": traceback.format_exc(),
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
