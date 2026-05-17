# ADR-0005: Export formats in v1 — glb + obj + ply (fbx deferred)

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** user, Claude

## Context

The spec lists `.glb`, `.obj`, `.fbx`, `.ply` as supported export formats. Implementing all four reliably from open-source tooling is not equal-effort.

- `.glb` — the modern standard. Single-file, embeds textures + materials + animations. Excellent open tooling (trimesh, pygltflib, Blender).
- `.obj` — universal text format. Materials in `.mtl`. Textures separate. Mature and trivial.
- `.ply` — common in scanning/photogrammetry workflows. Trivial.
- `.fbx` — Autodesk's binary format. The reference implementation is the Autodesk FBX SDK (proprietary). Open-source FBX support exists (Blender's exporter, `fbx-sdk` wrappers) but is **incomplete**: PBR materials, modern texture features, and certain animation properties don't round-trip cleanly. Shipping an FBX exporter that *kind of* works is worse than not shipping one.

## Decision

**v1 supports `.glb` + `.obj` + `.ply`.** `.fbx` is deferred to v1.1, implemented via Blender's bundled FBX exporter (`bpy.ops.export_scene.fbx`).

`.glb` is the **primary** format: it's what the in-app viewer loads, what the user gets by default, and what we test most thoroughly.

## Consequences

**Good**
- Zero ambiguity about which format is canonical. `.glb` wins.
- We don't burn engineering time on FBX edge cases (PBR transfer, mesh subdivision metadata, etc.) in v1.
- All three v1 formats are well-supported by `trimesh` and `Blender 5.x`. Implementation cost is low.

**Bad**
- Some pipelines (Maya, MotionBuilder, older Unity workflows) expect FBX. Users in those workflows will need to convert externally for v1. We will document this clearly in the export panel ("Need FBX? Drag your `.glb` into Blender and export, or wait for v1.1").
- The roadmap commits to v1.1 FBX. Don't break that promise.

**Neutral**
- Blender's FBX exporter is good enough for textured static meshes (our case). When v1.1 comes, the implementation is mostly a new entry in `export_final.py` calling `bpy.ops.export_scene.fbx`.

## Alternatives considered

**Ship FBX in v1 via Blender exporter.** Tempting but adds a known-flaky surface to v1. We will not ship something we don't trust just to tick a feature box.

**Ship FBX via assimp.** assimp has FBX *import* but its FBX *export* is widely considered immature. Rejected.

**Drop `.ply` in v1.** Considered. Rejected because `.ply` is the only format with first-class vertex-color support without UVs, and our first-pass TripoSR meshes are vertex-colored. `.ply` is also useful for photogrammetry workflows. Implementation cost is trivial.

**Drop `.obj` in v1.** Rejected. `.obj` is the universal "if all else fails" interchange format; users expect it.
