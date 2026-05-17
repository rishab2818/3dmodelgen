# CLAUDE.md — Repo-wide operating rules

> **You (Claude) are working inside `D:\3dmodel_gen`. Read this file first on every fresh session before touching code.**

This file is the single source of truth for *how* to work in this repo. The *what* (product) lives in [`ai-image-to-3d-specification.md`](./ai-image-to-3d-specification.md). The *why* behind architecture choices lives in [`docs/DECISIONS/`](./docs/DECISIONS/).

---

## 1. What this project is, in one paragraph

A desktop application (Tauri + React shell, Python orchestrator, Blender headless backend) that converts an image into a high-quality 3D model and then **iteratively refines** that model until rendered views of it match the original image to a defined quality threshold. The differentiator is the refinement loop, not the first-pass generation. Treat every component as a building block for that loop.

---

## 2. Repo map (what lives where)

```
.
├── ai-image-to-3d-specification.md  Product brief (do not edit — it is the user's source-of-truth)
├── CLAUDE.md                        This file. Repo-wide rules.
├── README.md                        Human-facing intro and quickstart.
├── docs/
│   ├── ARCHITECTURE.md              System architecture, layers, data flow.
│   ├── PIPELINE.md                  Per-stage AI pipeline detail.
│   ├── QUALITY_RUBRIC.md            How the evaluator decides "good enough". WORLD-CLASS lives here.
│   ├── BACKEND_CONTRACT.md          HTTP/IPC contracts between Tauri ↔ Python ↔ GPU backend.
│   ├── BLENDER_OPERATIONS.md        Headless Blender scripts catalog.
│   ├── RESUMABILITY_AND_BUDGET.md   Durability contract: pause/resume, idempotency, cache, caps.
│   ├── ROADMAP.md                   Milestones with exit criteria.
│   └── DECISIONS/                   ADRs. Numbered. Immutable once accepted; supersede with new ADRs.
├── app/         Tauri + React desktop shell.            See app/CLAUDE.md
├── backend/     Python orchestrator (FastAPI + asyncio). See backend/CLAUDE.md
├── blender/     Headless Blender scripts.               See blender/CLAUDE.md
├── ai_models/   Model adapters + weight registry.        See ai_models/CLAUDE.md
└── .claude/
    ├── agents/  Specialized sub-agents (load via Task tool when delegating).
    └── settings.local.json  Allow-listed commands to reduce permission prompts.
```

**Folder-scoped rules live in each folder's `CLAUDE.md`.** Load the one relevant to the files you're editing.

---

## 3. Operating rules — read carefully

### 3.1 Plan before code

- For any change touching > 1 module, write the plan into the relevant doc *first* (ARCHITECTURE / PIPELINE / BACKEND_CONTRACT), get it confirmed, then implement.
- Do not "vibe code." Do not stub out something just to make a screen render. Either it works to spec or it raises `NotImplementedError` with a clear TODO that has an ADR reference.

### 3.2 ADR discipline

- Any decision that affects > 1 module → ADR.
- ADRs are *append-only*. To change a past decision, write a new ADR that supersedes the old one. Keep the old file. Add a banner at top: `**Status: Superseded by ADR-XXXX**`.
- ADR file naming: `ADR-NNNN-kebab-case-title.md`. Increment NNNN strictly. Index in [`docs/DECISIONS/README.md`](./docs/DECISIONS/README.md).

### 3.3 The three runtime modes

The app supports three GPU backend modes — `mock`, `remote`, `local` — selected by the `GPU_BACKEND` env var. **Every AI pipeline stage MUST honor all three.** See [ADR-0002](./docs/DECISIONS/ADR-0002-gpu-backend-abstraction.md) and [BACKEND_CONTRACT.md](./docs/BACKEND_CONTRACT.md). If you write a stage that only works on local CUDA, it's broken.

### 3.4 Determinism + reproducibility

- All generation calls take an explicit `seed` parameter. Default `42`. Never use `time()`-based seeds.
- All model loads pin a `revision` (HuggingFace commit hash). Never `revision="main"`.
- Blender scripts are run with `--factory-startup` to ignore user prefs.

### 3.5 Never commit these

- Model weights (`*.safetensors`, `*.ckpt`, `*.pth`, `*.onnx`, `*.gguf`). Use Git LFS only for tiny test fixtures (< 5 MB).
- API keys, HuggingFace tokens, ngrok auth tokens. Use `.env` (gitignored).
- Generated outputs (`exports/`, `temp/`, `__pycache__/`, `target/`, `node_modules/`).
- Anything in `temp/`. Ever.

### 3.6 Cross-platform reality

Primary dev target: **Windows 11**. The code must also build on Linux (for GPU servers and CI). macOS is best-effort. Avoid:
- Hard-coded `C:\` paths. Use `pathlib.Path` and platform-aware config.
- Backslashes in string literals.
- Subprocess calls that assume bash. Use Python's `subprocess` with `shell=False` and an argv list.

### 3.7 Long-running work

Anything > 10 seconds is a **job**, not a function call. Jobs:
- Have a UUID.
- Stream progress events via SSE (server) → frontend store.
- Are resumable / cancellable.
- Persist state to SQLite (`backend/state.db`) so a crash doesn't lose work.

### 3.8 Resumability + budget — the **prime directive**

Our target users do not have unlimited GPU credits and their connections drop. Every line of pipeline code must respect this:

1. **Stage-level resumability.** Every stage writes a `.complete` marker as its last act. On resume, completed stages are skipped, not re-run. Granularity is stage, not iteration.
2. **Idempotency keys on every remote call.** Format: `{job_id}:{iteration}:{stage}:{call_index}`. The remote endpoint deduplicates. A retry is free.
3. **Never lose work on disconnect.** Colab timeout, ngrok URL rotation, app close, machine reboot — none of these waste already-paid-for GPU time.
4. **Pause is distinct from cancel.** Pause survives restart. Cancel is terminal.
5. **Cache aggressively.** `(preprocessed_image_hash, model, revision, seed, params)` is the cache key. A user re-running with the same inputs is instant.
6. **Show what was spent.** Every remote call is logged to the `gpu_call` table. The UI surfaces GPU-time per job and cumulative.

If you add a stage, a refinement action, or a remote endpoint that violates any of these, you have created a regression. See [`docs/RESUMABILITY_AND_BUDGET.md`](./docs/RESUMABILITY_AND_BUDGET.md) and [ADR-0006](./docs/DECISIONS/ADR-0006-resumability-and-budget.md).

---

## 4. Coding conventions

### 4.1 Python (backend, blender scripts, ai_models)

- **Version: 3.10.x** (pinned via `uv`). Not 3.11, not 3.12. Hunyuan3D-2 and TripoSR are picky.
- Type hints **mandatory** on every public function. `from __future__ import annotations` at the top of every file.
- `ruff` + `ruff format` (line length 100). No `black`, no `isort` — ruff replaces them.
- `pytest` for tests. Test files mirror source files: `backend/foo.py` → `backend/tests/test_foo.py`.
- **No bare `except`.** Catch specific exceptions. If you must catch broadly, name the variable and log it: `except Exception as e: log.exception("context"); raise`.
- Async by default in the orchestrator. Use `asyncio`, not `threading`, except inside Blender subprocess boundaries.
- Pydantic v2 for all data models that cross a process or HTTP boundary.

### 4.2 TypeScript (app/)

- **strict: true** in `tsconfig.json`. No `any`. If you reach for `any`, you're stuck — ask for help instead.
- React function components only. No class components.
- State: **Zustand** for client state, **TanStack Query** for server state. Do not invent a fourth state library.
- Styling: Tailwind + shadcn/ui components. No CSS-in-JS.
- Tauri IPC: typed via shared zod schemas → generated TS types. See `app/CLAUDE.md`.

### 4.3 Rust (Tauri side)

- Edition 2021. `cargo fmt` + `clippy -- -D warnings` clean.
- The Tauri Rust side is **thin**: file pickers, window management, spawning the Python backend, IPC plumbing. Business logic lives in Python.

### 4.4 Commits

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:`.
- One logical change per commit. Don't bundle "ran formatter" with "fixed bug X."
- Don't commit without running `ruff check`, `pnpm typecheck`, and `cargo check` for whatever you touched.

---

## 5. How to use Claude efficiently in this repo

The folder-scoped `CLAUDE.md` files are designed so the agent loads only the rules it needs. **When you (the agent) work in a subfolder, read that folder's `CLAUDE.md` before the root one if context is tight.**

Sub-agents are available under `.claude/agents/`:
- **`ml-pipeline`** — for anything touching `ai_models/`, model selection, generation parameters, eval logic.
- **`blender-tech`** — for headless Blender scripting (5.x API, `bpy`, geometry nodes).
- **`ui-engineer`** — for Tauri/React work in `app/`.
- **`quality-evaluator`** — for designing the scoring/refinement logic in `evaluation/` and `refinement/`.

Delegate to them rather than loading their full context into the main thread.

---

## 6. Environment expectations

Confirmed installed on dev box (2026-05-16):

| Tool | Version | Where |
|---|---|---|
| Python | 3.12.10 (system) | `C:\Users\lenov\AppData\Local\Programs\Python\Python312\` |
| Python | 3.10.x (project, via uv) | managed |
| Node | 24.14.0 | global |
| pnpm | latest | npm global |
| Rust | 1.89.0 | `~/.cargo/bin` |
| Git | 2.49.0 + Git LFS 3.6.1 | global |
| Blender | 5.1 | `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe` *(not on PATH)* |
| FFmpeg | winget | `~/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe` |
| ngrok | npm | global |
| uv | 0.11.14 | winget |

**Blender is not on PATH.** Backend invokes it via absolute path from config (`BLENDER_EXE` env var). See `backend/CLAUDE.md` § 3.

GPU: Intel Iris Xe only on this machine. CUDA work runs `remote` (Colab + ngrok). See [ADR-0002](./docs/DECISIONS/ADR-0002-gpu-backend-abstraction.md).

---

## 7. Things that are NOT in scope (per spec)

Do not write code for: payments, auth, cloud accounts, online collaboration, telemetry/analytics, or web hosting. If a feature needs any of these, push back and ask. The product is **a single-user desktop app**.

---

## 8. When in doubt

1. Re-read the relevant ADR.
2. If no ADR covers it, draft one (in `docs/DECISIONS/`), tag it `Status: Proposed`, and ask the user.
3. Do not invent silently.
