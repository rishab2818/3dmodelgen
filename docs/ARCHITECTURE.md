# Architecture

Status: **Draft v1 — for sign-off before M1**

Source spec: [`../ai-image-to-3d-specification.md`](../ai-image-to-3d-specification.md). This document is the engineering translation of that spec.

---

## 1. The big picture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            Desktop App (single binary)                       │
│                                                                              │
│   ┌───────────────────────────┐         ┌──────────────────────────────┐    │
│   │   React UI  (TS, strict)  │ ◄─IPC─► │   Tauri Rust core (thin)     │    │
│   │   - File picker            │  zod   │   - File dialogs              │    │
│   │   - Job list + progress    │ schemas│   - Window mgmt               │    │
│   │   - 3D preview (R3F)       │        │   - Spawn/supervise backend   │    │
│   │   - Quality dashboard      │        │   - Local file I/O           │    │
│   └─────────────┬──────────────┘        └───────────────┬──────────────┘    │
│                 │                                       │                    │
│                 │ HTTP + SSE (localhost:7878)           │ subprocess         │
│                 │                                       │                    │
│   ┌─────────────▼───────────────────────────────────────▼──────────────┐    │
│   │              Python Orchestrator   (FastAPI + asyncio)             │    │
│   │   - REST: jobs, models, settings                                   │    │
│   │   - SSE: per-job progress events                                   │    │
│   │   - Job state in SQLite (./backend/state.db)                       │    │
│   │   - Pipeline coordinator: stage graph executor                     │    │
│   └─────────┬───────────────────┬────────────────────┬─────────────────┘    │
│             │                   │                    │                       │
│   ┌─────────▼──────┐  ┌─────────▼──────┐   ┌─────────▼──────┐                │
│   │  Preprocess     │  │  Blender CLI   │   │  GPU Backend   │                │
│   │  (rembg, cv2,   │  │  (5.x headless)│   │  Adapter        │                │
│   │   Pillow)       │  │  bpy scripts   │   │   ▼              │                │
│   └─────────────────┘  └────────────────┘   ▼                  │                │
│                                       ┌──────────────────────┐ │                │
│                                       │ mock / remote / local │ │                │
│                                       └──────────┬───────────┘ │                │
└──────────────────────────────────────────────────┼─────────────┘                │
                                                   │                               │
                  ┌────────────────────────────────┼──────────────────────────┐    │
                  │                                │                          │    │
        ┌─────────▼─────────┐         ┌────────────▼──────────┐    ┌──────────▼──┐│
        │  mock backend     │         │  remote backend       │    │  local GPU  ││
        │  (returns canned  │         │  HTTP → ngrok/Modal   │    │  CUDA + PT  ││
        │   .glb fixtures)  │         │  → Colab/Kaggle/Modal │    │  (future)    ││
        └───────────────────┘         └───────────────────────┘    └─────────────┘│
```

The dotted boundary is the **process boundary**: everything below crosses into a different runtime.

---

## 2. Layers (what each one owns)

### Layer 0 — UI (React, TypeScript)

- Owns: visual state, user input, the 3D viewer.
- Owns NOT: any business logic, file I/O, model inference.
- Talks to Tauri core via IPC (typed via shared zod schemas). Talks to the Python backend via `http://localhost:7878` (HTTP + SSE).
- Why two channels? IPC is for things only the OS can do (file dialogs, window controls). HTTP is for things the backend does (jobs).

### Layer 1 — Tauri Rust core

- Owns: window lifecycle, native dialogs, spawning and supervising the Python backend process, app updater (later).
- Owns NOT: pipeline logic, ML, file format conversion.
- Why thin? Tauri Rust is a force-multiplier when used for OS plumbing; it's a tax everywhere else. Keep it boring.

### Layer 2 — Python orchestrator (FastAPI + asyncio)

- Owns: the **pipeline graph**, job state, SSE event stream, calling subprocesses (Blender) and HTTP clients (GPU backend).
- Persists: `state.db` (SQLite) — jobs, iterations, scores, file paths.
- Why a separate process? Python's ML ecosystem is too heavy to embed inside Rust; subprocess isolation also means a crash in image preproc doesn't take the UI with it.

### Layer 3 — Workers

Three sibling workers, all called by the orchestrator:

| Worker | Process model | Stateful? |
|---|---|---|
| Preprocessing | in-process Python | no |
| Blender | subprocess (one per call), headless | no |
| GPU backend | HTTP (`mock`/`remote`/`local`) | no — model warm-up handled per-mode |

---

## 3. Data flow for one generation job

```
1.  User drops image(s) into the UI.
2.  UI calls Tauri to validate file paths → returns canonical absolute paths.
3.  UI POSTs POST /jobs with { input_images: [paths], target_quality: 0.85, max_iterations: 6 }.
4.  Orchestrator creates Job row, returns { job_id }. UI subscribes to SSE /jobs/{id}/events.
5.  Orchestrator executes the pipeline graph (see PIPELINE.md):
        preprocess → generate(initial)
                       → blender.cleanup
                       → render.multiview
                       → evaluate
                       → if score < target and iter < max: refine → loop
                       → else: export
    For each stage transition, an SSE event is emitted: {stage, status, progress, artifacts}.
6.  Final artifacts (.glb + .obj + .ply) land in ./exports/{job_id}/.
7.  UI's 3D viewer loads the final .glb via fetch from the orchestrator's static-files mount.
```

Every stage writes its intermediate artifacts to `./temp/{job_id}/{iter}/{stage}/`. Resumability comes for free: a crashed job is restartable from the last completed stage.

---

## 4. The pipeline graph

A directed graph of **stages**. Each stage:
- has an explicit input schema (Pydantic) and output schema,
- is idempotent given the same inputs (so re-runs after a crash produce the same artifacts),
- writes artifacts to a stage-local directory,
- as its **last act**, writes a `.complete` marker (atomic, fsync'd) containing `{completed_at, idempotency_key}`,
- emits a `stage_event` over SSE.

On resume, the executor walks the graph and skips stages whose `.complete` exists — replayed to the UI as synthetic `cache_hit` events so the timeline stays complete. A stage that crashed mid-write has no `.complete`, so re-running is safe. This is the foundation of stage-level resumability across crashes, ngrok rotations, app closes, and reboots. Full contract in [`RESUMABILITY_AND_BUDGET.md`](./RESUMABILITY_AND_BUDGET.md).

```
[preprocess]
    │
    ▼
[generate.initial] ──► [blender.cleanup] ──► [render.multiview] ──► [evaluate]
    ▲                                                                    │
    │                                                                    ▼
    └──────────────────── [refine.plan] ◄──── (score < target) ──── decision
                                │
                                ▼
                          [refine.apply]
                          (re-enters at generate.initial or blender.cleanup
                           depending on what refine.plan decided)
```

Detail: [`PIPELINE.md`](./PIPELINE.md). Quality scoring + decision logic: [`QUALITY_RUBRIC.md`](./QUALITY_RUBRIC.md).

---

## 5. The "GPU Backend" abstraction

`generate.*` and `evaluate.*` stages do not call CUDA directly. They call a `GPUBackend` adapter (`backend/gpu/__init__.py`). The adapter is chosen by env var `GPU_BACKEND ∈ {mock, remote, local}`.

| Adapter | What it does |
|---|---|
| `MockGPUBackend` | Returns pre-baked fixture artifacts and scripted scores. Lets UI dev proceed without a GPU. |
| `RemoteGPUBackend` | HTTP POST to a remote endpoint (Colab via ngrok in dev, Modal in staging, your own RunPod in prod). |
| `LocalGPUBackend` | Loads models in-process, runs inference on local CUDA. Activated when the user gets an NVIDIA box. |

The remote endpoint runs the **same model adapter code** as the local one — it's literally the local code wrapped in a FastAPI server. See [`BACKEND_CONTRACT.md`](./BACKEND_CONTRACT.md) §2.

ADR: [ADR-0002](./DECISIONS/ADR-0002-gpu-backend-abstraction.md).

---

## 6. Process supervision

- Tauri spawns the Python backend on app start, captures its stdout/stderr to a rotating log (`./logs/backend.log`), and restarts it if it crashes (with exponential backoff, max 3 attempts before surfacing a UI error).
- Blender invocations are short-lived subprocesses (one per call). Each has a 5-minute hard timeout. Killed cleanly via process group on cancel.
- The remote GPU endpoint has its own lifecycle (e.g. Colab notebook stays alive 12h). The orchestrator pings `/health` every 30s and surfaces "remote GPU offline" cleanly.

---

## 7. State and storage

- **SQLite** (`backend/state.db`) — job metadata, iteration scores, artifact paths, **GPU-call ledger for budget tracking**. WAL mode. SQLAlchemy + Alembic for migrations.
- **Filesystem** — everything large (images, meshes, textures). Under `./temp/{job_id}/` for intermediates, `./exports/{job_id}/` for finals. **Intermediate artifacts persist across sessions** to support stage-level resume.
- **Generation cache** — `./models_cache/generation_cache/{cache_key}/` indexed on `(preprocessed_image_hash, model, revision, seed, params)`. LRU-evicted at a configurable size cap. Cache hits skip the remote entirely.
- **In-memory** — current SSE subscriber set, in-flight job graphs.

No Redis, no Postgres, no message broker. This is a single-user desktop app.

**Critical invariant:** there is no in-memory state that isn't also on disk. All state changes happen inside a single SQLite transaction per stage transition. This is what makes resumability work. See [`RESUMABILITY_AND_BUDGET.md`](./RESUMABILITY_AND_BUDGET.md).

---

## 8. Concurrency model

- One job at a time **per GPU backend instance** (a single Colab notebook can't realistically multiplex Hunyuan3D-2 calls). The orchestrator serializes jobs in a `JobQueue`.
- Within a job, stages run sequentially (the graph is a DAG but currently linear). Future: parallel multi-view renders.
- The UI never blocks. All long calls are async and stream progress.

---

## 9. Failure modes and what we do about them

| Failure | Detection | Recovery |
|---|---|---|
| Remote GPU endpoint down | `/health` ping fails for > 5 min | running jobs move to `paused_remote_offline`; auto-resume when health passes twice in a row. UI surfaces "Frugal mode" as an alternative. |
| Remote HTTP call times out mid-flight | client timeout | retry with the **same idempotency key** — remote returns the cached response if it actually finished; otherwise re-runs. Never double-billed. |
| Backend process crash | next launch finds `running` rows | reset them to `paused_crashed`; resume from last completed stage on user action (or auto on next session if configured). |
| Blender subprocess crashes | non-zero exit | retry once with `--factory-startup`; on second failure, fail the stage with the captured stderr. |
| Preprocessing OOM | exception | fail the job with a clear message; do not retry. |
| Evaluation produces NaN score | sanity check on every score | clamp to 0.0, log, treat as "needs more refinement" up to max_iterations. |
| Disk full | OS error during artifact write | fail job; UI shows free-space hint. |
| Per-job or per-session budget cap hit | budget check between stages | job moves to `paused_budget`; user can raise the cap, accept best-iter-so-far, or cancel. |

Errors are never swallowed. Every failure path lands in the SSE stream and the SQLite job row. **No failure ever loses prior completed stages' artifacts.**

---

## 10. Security posture (single-user desktop)

- Backend binds to **127.0.0.1 only** — never `0.0.0.0`.
- HuggingFace / ngrok tokens stored via OS keychain (Tauri's `keyring` plugin), not plaintext config.
- Inputs (images) are size-capped (32 MB) and type-checked before any decode.
- Outputs (`.glb`, `.obj`) are inspected for path traversal before write.

---

## 11. Non-functional targets

| Property | Target | How measured |
|---|---|---|
| First-pass generation time (TripoSR on T4) | < 30 s | wall-clock from POST /jobs to first artifact |
| Full refinement (Hunyuan + 3 iterations on T4) | < 8 min | wall-clock |
| UI frame time (3D viewer) | 60 fps on iGPU for < 100k tri meshes | DevTools |
| Cold start (app launch → ready) | < 4 s | OS timer |
| Memory (Python backend idle) | < 600 MB RSS | task manager |

Numbers will be re-baselined per milestone in [`ROADMAP.md`](./ROADMAP.md).

---

## 12. Open questions still to resolve

These are tracked as ADRs in `Proposed` status:

- ADR-0006 (TBD): texture-baking strategy — Blender-native bake vs. learned texture diffusion (e.g., Paint3D).
- ADR-0007 (TBD): refinement strategy taxonomy — when do we re-generate the whole mesh vs. locally edit it?
- ADR-0008 (TBD): which evaluator vision model — DINOv2 vs. SigLIP vs. CLIP-ViT-L? See QUALITY_RUBRIC.md §7.
