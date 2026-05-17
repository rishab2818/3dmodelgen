# 3dmodel_gen

A desktop application that turns an image into a high-quality 3D model — and then **keeps improving the model until rendered views of it match the input image**.

> The differentiator is the iterative refinement loop, not the first-pass generation.

This README is the **human** intro. If you are an AI coding agent, read [`CLAUDE.md`](./CLAUDE.md) first.

---

## What's inside

| Folder | Purpose |
|---|---|
| `app/` | Desktop shell — Tauri + React. |
| `backend/` | Python orchestrator — FastAPI + asyncio. Coordinates pipeline. |
| `blender/` | Headless Blender 5.x scripts for mesh ops, baking, rendering. |
| `ai_models/` | Adapters for TripoSR / Hunyuan3D-2 / evaluators. Pluggable backends. |
| `docs/` | Architecture, pipeline, quality rubric, ADRs, roadmap. |
| `ai-image-to-3d-specification.md` | The original product brief. Source of truth for *what* we are building. |

---

## Status

Planning phase. No code yet. The full `.md` scaffold is in place; first milestone (M1 — UI skeleton + mock backend) starts after architecture sign-off.

See [`docs/ROADMAP.md`](./docs/ROADMAP.md).

---

## Quick links

- [Architecture](./docs/ARCHITECTURE.md)
- [Pipeline detail](./docs/PIPELINE.md)
- [Quality rubric](./docs/QUALITY_RUBRIC.md) — how we decide a model is "good enough"
- [Resumability + Budget](./docs/RESUMABILITY_AND_BUDGET.md) — durability contract for users with limited GPU credits
- [Backend contract](./docs/BACKEND_CONTRACT.md) — Tauri ↔ Python ↔ GPU backend
- [Roadmap](./docs/ROADMAP.md)
- [Decisions (ADRs)](./docs/DECISIONS/)

---

## Running it

You can't yet. Stay tuned for M1.
