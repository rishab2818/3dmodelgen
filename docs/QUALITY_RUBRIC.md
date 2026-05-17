# Quality Rubric — How we decide a model is "good enough"

Status: **Draft v1 — for sign-off before M1**

> This document is the soul of the product. The differentiator vs. every other image-to-3D tool is that we **measure** quality and refine until it's met. That only works if "quality" is operationalized as numbers, not vibes.

---

## 1. The big idea

A 3D model is "close enough to the input image" when:

1. **Silhouette matches** — outline of the rendered front view ≈ outline of the input.
2. **Appearance matches** — colors, materials, and high-level semantic features of the renders ≈ the input.
3. **Geometry is healthy** — no inverted normals, no holes, manifold, sane vertex count.
4. **No catastrophic features missing** — if the input shows a handle, the output has a handle.

Each is a separate sub-score. We combine them into one `overall_score ∈ [0, 1]`. We stop refining when `overall_score ≥ target_quality` (default 0.85).

We will tune the weights and the threshold against a held-out evaluation set of ~50 reference images (see [`ROADMAP.md`](./ROADMAP.md) M3).

---

## 2. The metrics

| ID | Metric | Range | Direction | What it catches |
|---|---|---|---|---|
| **S** | Silhouette IoU | 0..1 | higher better | wrong shape, missing parts, wrong proportions |
| **C** | CLIP cosine similarity (mean across views) | -1..1 *(typ. 0.5–0.9)* | higher better | wrong semantic content (e.g. "this should look like a chair") |
| **D** | DINOv2 cosine similarity (mean across views) | 0..1 | higher better | wrong fine-grained visual features (texture, material) |
| **H** | Color histogram EMD (masked) | 0..1 *(inverted to similarity)* | higher better | wrong colors |
| **L** | LPIPS perceptual distance (inverted) | 0..1 | higher better | perceptual difference in appearance |
| **G** | Geometry health composite | 0..1 | higher better | non-manifold, holes, NaN, degenerate tris |
| **F** | Feature presence (v1.1) | 0..1 | higher better | missing parts (handles, knobs, etc.) — held back to v1.1 because reliable detection is hard |

CLIP and DINOv2 are computed as an **ensemble**: CLIP is good at semantics, DINOv2 is much stronger at fine-grained discrimination. We average their cosine sims after normalization.

---

## 3. The composite score

```
overall_score = w_S * S + w_C * C_norm + w_D * D + w_H * H + w_L * L + w_G * G
```

Where `C_norm = max(0, (C - 0.5) / 0.5)` (CLIP rarely goes below 0.5 on real cases).

**Default weights** (`backend/eval/weights.yaml`):

```yaml
silhouette:        0.30   # the most important single metric — if outline is wrong, nothing else matters
clip:              0.15
dino:              0.20
color_hist:        0.10
lpips:             0.10
geometry_health:   0.15   # not a quality signal per se, but a hard floor — a broken mesh ships nothing
```

We deliberately weight **silhouette** heavily. It's interpretable, robust, and tightly coupled to "looks like the thing in the photo."

**Geometry health acts as a gate, not just a weight:** if `G < 0.5`, `overall_score` is capped at 0.5 regardless of other metrics. A pretty mesh that's non-manifold is unusable.

---

## 4. Diagnosis — turning numbers into a story

After computing all metrics, we classify the dominant failure mode using a small rules engine. The output is an ordered `list[Issue]`, most severe first. Each issue has an enum tag the refinement planner reads.

| Issue tag | Trigger | Suggested fix |
|---|---|---|
| `SILHOUETTE_MISMATCH` | S < 0.6 | regenerate with higher-capacity model |
| `SILHOUETTE_PARTIAL` | 0.6 ≤ S < 0.8 | mesh_repair + re-render; if still bad, regenerate |
| `WRONG_SEMANTICS` | C < 0.65 | regenerate (often the generator chose the wrong object class) |
| `TEXTURE_MISMATCH` | D < 0.7 and S ≥ 0.8 | texture_refine_only |
| `COLOR_MISMATCH` | H < 0.6 and other metrics OK | texture_refine_only with explicit color guidance (v1.1) |
| `GEOMETRY_BROKEN` | G < 0.6 | mesh_repair |
| `NEAR_TARGET` | all sub-scores ≥ 0.8, overall ≥ 0.82 but < target | regenerate_with_new_seed (you're 1 lucky roll away) |

Multiple issues can fire. The planner takes the highest-severity one for the next iteration.

---

## 5. Refinement → action mapping

Tied to the diagnosis above and to [PIPELINE.md §6](./PIPELINE.md#stage-6--refinement-decision--plan):

```
SILHOUETTE_MISMATCH       → regenerate_with_higher_capacity
SILHOUETTE_PARTIAL        → mesh_repair (then re-render; do not re-generate)
WRONG_SEMANTICS           → regenerate_with_higher_capacity (or InstantMesh if multi-view)
TEXTURE_MISMATCH          → texture_refine_only
COLOR_MISMATCH            → texture_refine_only
GEOMETRY_BROKEN           → mesh_repair
NEAR_TARGET               → regenerate_with_new_seed
```

If the same action is chosen twice in a row and the score does not improve by ≥ 0.03, the planner **escalates**: it picks the next action up the severity ladder. This prevents infinite spin on the same bad seed.

---

## 6. The stopping rule

A job stops when **any** of these is true:

1. `overall_score ≥ target_quality` — **success**.
2. `iteration ≥ max_iterations` — **exhausted**. We still export the best iteration seen, not the last one.
3. `no_improvement_streak ≥ 2 AND overall_score ≥ 0.75` — **good-enough plateau**. Saves time on jobs that won't get better.
4. User clicked Cancel — **cancelled**.

We track `best_iteration` separately from `current_iteration`. Export always uses `best_iteration`.

---

## 7. Choice of evaluator models — pending

This is **ADR-0008 (Proposed)**, not yet decided.

| Option | Pro | Con | VRAM (fp16) |
|---|---|---|---|
| CLIP ViT-L/14 (OpenAI) | well-known, robust | weaker fine-grained discrimination | ~2 GB |
| SigLIP-Large | better text-image alignment | newer, less battle-tested in eval pipelines | ~2.5 GB |
| DINOv2-Base | strong fine-grained features, no text | no semantic signal alone | ~0.4 GB |
| **Ensemble (CLIP + DINOv2)** ← current plan | both axes covered | 2× VRAM, 2× latency | ~2.4 GB |

The current default in `weights.yaml` assumes the ensemble. We will benchmark this on the M3 eval set and may switch.

---

## 8. Calibration plan (M3 milestone)

We will assemble a **calibration set** of ~50 reference images — diverse objects, varied lighting, single + multi-view — each paired with a hand-curated "good enough" judgement (binary `is_acceptable`).

Then we will:

1. Generate models for each input.
2. Compute all metrics.
3. Find the weights that maximize agreement between `overall_score ≥ threshold` and `is_acceptable`.
4. Lock weights + threshold for v1 GA.

This turns "world-class" from a marketing word into a measured number.

The calibration set lives in `evaluation/calibration_set/` (Git LFS, gitignored if > 500 MB total).

---

## 9. Reporting to the user

The UI's per-job timeline shows:
- The overall_score bar (current iteration vs. target).
- Sparkline of overall_score across iterations.
- Per-metric mini-bars (S, C, D, H, L, G).
- Plain-language diagnosis line: *"The outline matches well but the texture color is too saturated. Trying a texture-only refinement next."*

Users don't see the raw weights. They see the story. Numbers exist for diagnosability and for us.

---

## 10. What we explicitly do NOT score in v1

- Topology quality (edge flow, quad-ness). Matters for downstream 3D artists, irrelevant for the AI's own metrics. Plan: optional "retopology pass" in v1.2.
- Texture seam quality. Hard to measure automatically. Plan: visual inspection in v1.1.
- PBR plausibility (metallic/roughness "looks like metal"). v1.2.

We will be honest about these limitations in the UI's quality dashboard.
