# Pipeline Detail

Status: **Draft v1 — for sign-off before M1**

This document specifies every stage of the image→3D pipeline: inputs, outputs, models, parameters, failure handling. It is the contract that `backend/pipeline/` implements.

For the *why* behind model choices see [`DECISIONS/ADR-0003`](./DECISIONS/ADR-0003-initial-generator-choice.md). For scoring/decision logic see [`QUALITY_RUBRIC.md`](./QUALITY_RUBRIC.md). For resumability + idempotency + caching rules (which every stage below must obey) see [`RESUMABILITY_AND_BUDGET.md`](./RESUMABILITY_AND_BUDGET.md).

---

## Stage authoring rules (every stage MUST obey)

These are not advice — these are requirements. A stage that violates any is broken.

1. **Idempotent.** Same inputs → same outputs (deterministic). Re-running after a crash produces bit-identical artifacts.
2. **Atomically completed.** The last act of every stage is to write `temp/{job_id}/iter_{n}/{stage}/.complete` with `{completed_at, idempotency_key}`. Write to a `.tmp` file then `os.replace` (atomic on Windows + POSIX) then fsync.
3. **Cacheable, when remote.** Remote-GPU stages compute a cache key (`sha256(preprocessed_image_bytes || model || revision || seed || canonical_json(params))`) and check `models_cache/generation_cache/` *before* hitting the remote.
4. **Carries an idempotency key.** Remote calls send `Idempotency-Key: {job_id}:{iteration}:{stage}:{call_index}` so the remote can deduplicate. Format is deterministic — a crashed-then-restarted backend generates the same key.
5. **Records GPU usage.** Every remote call inserts a `gpu_call` row (`runtime_ms`, `model`, `revision`, `provider`, `cached`). Local-only stages insert nothing.
6. **Respects pause.** Between stages, the executor checks the `pause_requested` flag and exits cleanly if set. Inside a stage, do not poll — let the stage finish (it's already-paid-for work).
7. **Handles cancel mid-stage.** Stages catch `asyncio.CancelledError`, clean up any *partial* artifacts (anything without a `.complete`), and re-raise. Already-completed stages are untouched.

---

## Stage 0 — Job intake

**Input**
- 1–6 images (JPEG, PNG, WebP). Each ≤ 32 MB, ≤ 4096 px on longest side.
- `target_quality: float ∈ [0, 1]` (default 0.85)
- `max_iterations: int ∈ [1, 12]` (default 6)
- `seed: int` (default 42)
- `generator_pref: "auto" | "triposr" | "hunyuan3d-2" | "instantmesh"`

**Output**
- `job_id: UUID`, persisted in `state.db`, `temp/{job_id}/input/` populated.

**Validation**
- Decode each image with Pillow. Reject if decode fails or aspect ratio < 0.25 or > 4.0.
- If multiple images supplied → set internal flag `multi_view: true`; this routes to InstantMesh in stage 2 instead of TripoSR/Hunyuan.

---

## Stage 1 — Preprocessing

**Goal:** produce a clean, normalized, masked image ready for generation.

**Sub-steps (executed in order):**

| Step | Tool | Output |
|---|---|---|
| 1.1 Background removal | `rembg` with `isnet-general-use` model | RGBA image |
| 1.2 Alpha cleanup | OpenCV — morphological close (3×3, 2 iter) + small-component removal (< 0.5% area) | RGBA |
| 1.3 Auto-crop to alpha bbox + 10% padding | Pillow | RGBA |
| 1.4 Resize to model input size | Pillow LANCZOS | RGBA at target resolution (1024×1024 for Hunyuan, 512×512 for TripoSR) |
| 1.5 Lighting normalization (optional, off by default) | OpenCV CLAHE on L channel of Lab | RGBA |
| 1.6 Optional upscale | Real-ESRGAN x2 — only if input min-side < 512 | RGBA |
| 1.7 Save mask separately | derived from alpha channel | `mask.png` (binary, single channel) |

**Artifacts written**
- `temp/{job_id}/input/preprocessed.png` (RGBA, generator input)
- `temp/{job_id}/input/mask.png` (silhouette mask, used by evaluator)
- `temp/{job_id}/input/original.png` (copy of original for evaluator reference)

**Failure modes**
- rembg removes the entire image (e.g., uniform background mistake) → fail job with `PreprocessingError("background removal collapsed the subject")`.
- Real-ESRGAN OOM on low-VRAM remote → skip upscale, log warning, continue.

---

## Stage 2 — Initial 3D generation

**Goal:** produce a first-pass mesh + texture from the preprocessed image.

**Adapter selection** (`backend/pipeline/generate.py`):

```
if multi_view:                        return InstantMeshAdapter
elif generator_pref == "triposr":     return TripoSRAdapter
elif generator_pref == "hunyuan3d-2": return Hunyuan3D2Adapter
elif generator_pref == "auto":
    if backend == "mock":             return MockAdapter
    if vram_available >= 14e9:        return Hunyuan3D2Adapter
    else:                              return TripoSRAdapter
```

### 2A — TripoSR adapter

- **Model:** `stabilityai/TripoSR` — pinned to commit hash in `ai_models/registry.yaml`.
- **Input:** RGBA 512×512 PNG.
- **Output:** untextured mesh, ~50k–100k triangles, vertex colors from triplane sampling.
- **Runtime:** ~5–15 s on T4. ~5 min on CPU.
- **Determinism:** seeded via torch generator. Set `torch.use_deterministic_algorithms(True)` only on local CUDA (incurs perf cost on Colab).
- **Output artifacts:** `temp/{job_id}/iter_{n}/generate/mesh.obj`, `mesh_meta.json`.

### 2B — Hunyuan3D-2 adapter

- **Model:** `tencent/Hunyuan3D-2` (gated — needs HF token + license acceptance). Pin revision.
- **Input:** RGBA 1024×1024 PNG.
- **Output:** textured mesh (~100k tri) + albedo PNG. Optionally PBR (metallic/roughness) if `use_pbr=true`.
- **Runtime:** ~60–120 s on T4 (fp16, with CPU offload). ~30 s on A100.
- **VRAM:** ~12–14 GB at fp16 with `enable_model_cpu_offload`.
- **Output artifacts:** `temp/{job_id}/iter_{n}/generate/mesh.obj`, `albedo.png`, `mesh_meta.json`.

### 2C — InstantMesh adapter

- **Model:** `TencentARC/InstantMesh`. Pin revision.
- **Input:** 2–6 preprocessed views.
- **Output:** textured mesh, ~80k tri.
- **Runtime:** ~30–60 s on T4.

### Mock adapter

Returns a canned `.obj` from `ai_models/fixtures/`. Adds a configurable artificial delay (`MOCK_DELAY_MS` env var, default 800 ms) so the UI sees realistic progress.

---

## Stage 3 — Blender cleanup

**Goal:** turn a raw AI mesh into a well-formed mesh suitable for rendering and export.

**Executed as:**
```
blender --background --factory-startup --python blender/scripts/cleanup.py -- \
    --input  temp/{job_id}/iter_{n}/generate/mesh.obj \
    --output temp/{job_id}/iter_{n}/cleanup/mesh.obj \
    --texture temp/{job_id}/iter_{n}/generate/albedo.png  # optional
```

**Operations (in order, each toggleable via CLI flags):**

| Op | Default | Why |
|---|---|---|
| Merge by distance (0.0001) | on | TripoSR outputs lots of micro-duplicate verts |
| Remove loose geometry (< 4 verts island) | on | AI artifacts |
| Recalculate normals outside | on | textures need correct normals |
| Hole-fill (small holes only, max edge count 8) | on | meshes are rarely watertight |
| Decimate planar (angle 5°) | off in v1 | risk of losing detail; revisit in v1.1 |
| Smooth corrective (factor 0.3, 2 iter) | off in v1 | makes silhouettes worse on detailed objects |
| UV unwrap (smart project, angle 66°) | on if no UVs present | required for texture baking |

**Output artifacts:** `cleanup/mesh.obj`, `cleanup/mesh.glb`, `cleanup/stats.json` (vert/tri count, manifoldness flags).

**See:** [`BLENDER_OPERATIONS.md`](./BLENDER_OPERATIONS.md) for the full Blender script catalog.

---

## Stage 4 — Multi-view rendering

**Goal:** render the cleaned model from a canonical view set so the evaluator can compare it to the original image.

**Executed as:**
```
blender --background --factory-startup --python blender/scripts/render_views.py -- \
    --mesh temp/{job_id}/iter_{n}/cleanup/mesh.glb \
    --out  temp/{job_id}/iter_{n}/render/ \
    --views default8 \
    --resolution 512 \
    --engine cycles --samples 32
```

**View sets:**

| Name | Views |
|---|---|
| `default8` (default) | front, back, left, right, top, bottom, front-quarter-left, front-quarter-right |
| `dense24` | 24 evenly-spaced views around the equator + 4 top + 4 bottom |
| `match_input` | (multi-view jobs only) renders from the camera poses estimated for input images |

**Lighting:** neutral 3-point + HDRI (`studio_small_09_1k.hdr` shipped under `blender/hdri/`). No floor.

**Camera:** orthographic for `default8` (so silhouette IoU is well-defined), perspective at fov=35° for `dense24`.

**Renderer:** Cycles with 32 samples (denoise on). At 512×512 this is ~1–2 s/view on T4, ~5 s/view on CPU.

**Artifacts:** `render/{view_name}.png` (RGBA), `render/manifest.json` (view → camera matrix).

---

## Stage 5 — Evaluation

**Goal:** produce a quality score and a structured diagnosis of what's wrong.

**Sub-steps:**

| Step | Metric | Tool |
|---|---|---|
| 5.1 Silhouette IoU | IoU of `mask.png` ↔ alpha of `render/front.png` | OpenCV |
| 5.2 Multi-view CLIP/DINO similarity | cosine sim of input ↔ each render embedding | `open_clip` ViT-L/14 + DINOv2-Base ensemble |
| 5.3 Color histogram distance | EMD on RGB histograms (masked region only) | OpenCV |
| 5.4 LPIPS perceptual distance | input vs. front render | `lpips` package |
| 5.5 Geometry health | manifoldness, % non-manifold edges, watertight % | trimesh |
| 5.6 Diagnosis | classify dominant failure mode | rule-based on the metrics above (see QUALITY_RUBRIC §4) |

**Output:** structured `EvaluationReport` (Pydantic):

```python
class EvaluationReport(BaseModel):
    overall_score: float                  # 0..1, weighted combo
    silhouette_iou: float
    clip_similarity: float                 # mean across views
    dino_similarity: float
    color_emd: float
    lpips: float
    geometry: GeometryHealth
    diagnosis: list[Issue]                 # ordered, most severe first
    recommended_action: RefinementAction   # what to do next
```

`overall_score` weights are configurable per project; defaults in `backend/eval/weights.yaml`. See [`QUALITY_RUBRIC.md`](./QUALITY_RUBRIC.md) §3.

---

## Stage 6 — Refinement decision + plan

**Goal:** decide whether to stop, and if not, plan the next iteration.

```
if overall_score >= target_quality:        → stop, go to Stage 7 (export)
if iteration >= max_iterations:            → stop with "max_iter_reached" status, export best
else:                                       → plan refinement, loop back
```

**Refinement actions** (see QUALITY_RUBRIC §5 for the mapping):

| Action | What it does |
|---|---|
| `regenerate_with_new_seed` | re-runs Stage 2 with seed+1, keeps everything else; used when generation was just unlucky |
| `regenerate_with_higher_capacity` | re-runs Stage 2 with the next-tier model (TripoSR → Hunyuan3D-2) |
| `texture_refine_only` | keeps mesh, re-runs texture generation only (Hunyuan3D-2's texture-only mode, or Paint3D in v1.1) |
| `mesh_repair` | Blender mesh repair (more aggressive than cleanup): fill, remesh, smooth |
| `local_inpaint` | (v1.1) localized re-generation of a masked region |

The planner is a small rules engine in `backend/refine/planner.py`. **It is not an LLM.** Rules:
- silhouette IoU < 0.6 → `regenerate_with_higher_capacity`
- silhouette OK but CLIP < 0.7 → `texture_refine_only`
- geometry non-manifold > 5% → `mesh_repair`
- otherwise → `regenerate_with_new_seed`

We will revisit using an LLM planner in v1.2 — it's an obvious place for an LLM but it's also where things become unpredictable, and predictability matters more in v1.

---

## Stage 7 — Export

**Goal:** write final artifacts in user-facing formats.

**Always exported:**
- `exports/{job_id}/model.glb` — primary deliverable
- `exports/{job_id}/model.obj` + `model.mtl` + texture PNGs
- `exports/{job_id}/model.ply`
- `exports/{job_id}/preview_front.png` — 1024×1024 hero render
- `exports/{job_id}/report.json` — full pipeline log + per-iteration scores

**Not in v1:** `.fbx` (Autodesk SDK pain). Planned for v1.1 via Blender's FBX exporter. See [ADR-0005](./DECISIONS/ADR-0005-export-formats.md).

---

## Per-stage SSE event shape

Every stage emits:

```json
{
  "event": "stage_update",
  "job_id": "...",
  "iteration": 2,
  "stage": "generate.initial",
  "status": "running" | "complete" | "failed",
  "progress": 0.42,
  "message": "Generating mesh with Hunyuan3D-2",
  "artifacts": ["temp/.../mesh.obj"],
  "elapsed_ms": 18230
}
```

Frontend renders this into the per-job timeline.

---

## What can run in parallel (future)

In v1, the pipeline is sequential. Once we have local GPU:
- Stage 4 (multi-view render) is embarrassingly parallel across views (currently serial in Blender).
- Stages 5.1, 5.2, 5.3, 5.4 are independent — can be run concurrently.
- Multiple refinement candidates can be generated in parallel and the best one kept (proposal for v1.1: "branching refinement").
