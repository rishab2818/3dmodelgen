# ADR-0003: Initial 3D generator — TripoSR (fast) + Hunyuan3D-2 (primary)

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** user, Claude

## Context

The "initial 3D generation" stage is the costly, quality-defining step. The spec lists three candidates: TripoSR, Hunyuan3D-2, InstantMesh. There is also a newer alternative, TRELLIS (Microsoft), worth considering.

Constraints:
- Free Colab T4 (~14 GB VRAM after overhead).
- The user wants a "world-class" final product. Slow first-pass is acceptable if quality follows.
- The user also asked for "balance" — they want to *see* a result quickly during dev.

## Decision

Ship **two generators behind one interface**, used as a sequence:

1. **TripoSR** — runs first as a "fast preview." ~5–15 s on T4. Result appears in the viewer almost immediately.
2. **Hunyuan3D-2** — runs second as the "real" generation. ~60–120 s on T4 with `enable_model_cpu_offload`. Replaces the preview when done.

The refinement loop, when active, operates on the Hunyuan output. TripoSR is *not* used during refinement except in the `regenerate_with_new_seed` action when speed is more valuable than fidelity.

`InstantMesh` is supported but only auto-selected when the user uploads multiple images of the same object.

`TRELLIS` is a strong candidate but its memory profile is tight on a free T4. We mark it as a v1.1 swap-in target and design the adapter interface to make the swap one file.

## Consequences

**Good**
- Users see something within ~15 s of clicking Generate — preserves perceived responsiveness.
- The "final" output is best-in-class among open-weight generators (Hunyuan3D-2).
- The two-stage approach is also a robustness story: if Hunyuan fails or times out, we still have the TripoSR result as a usable fallback.
- The adapter abstraction means swapping in TRELLIS or a newer model is a one-file change.

**Bad**
- 2× model weight download (~10 GB combined). Cached after first run.
- The UI must handle "preview" → "final" mesh swap gracefully (the viewer needs to re-load without losing camera state).
- Hunyuan3D-2 weights are **gated** on HuggingFace — users (and the Colab notebook) need to accept the license and provide a token.

**Neutral**
- The refinement planner's `regenerate_with_higher_capacity` action becomes "TripoSR → Hunyuan." When Hunyuan was the initial generator and we still need higher capacity, the next-tier action goes to TRELLIS (v1.1).

## Alternatives considered

**TripoSR only.** Lower quality ceiling. Hard to call the result "world-class."

**Hunyuan3D-2 only.** No fast preview; the user waits 1–2 minutes staring at a progress bar. Worse UX even if final quality is the same.

**TRELLIS as primary.** Compelling on quality but VRAM headroom on free T4 is uncomfortable. Deferred to v1.1 when we can validate it on a 24 GB endpoint.
