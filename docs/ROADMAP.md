# Roadmap

Status: **Draft v1 — for sign-off**

Six milestones from zero to a v1.0 you'd be proud to ship. Each milestone has a hard exit criterion. We don't move to N+1 until N passes its criterion.

---

## M0 — Planning (current)

**Goal:** sign-off on architecture, pipeline, quality rubric, contracts.

**Exit criteria:**
- [x] `ai-image-to-3d-specification.md` exists (provided by user).
- [x] Full `.md` scaffold created (this milestone's deliverable).
- [ ] User has reviewed and either accepted or annotated `ARCHITECTURE.md`, `PIPELINE.md`, `QUALITY_RUBRIC.md`, `BACKEND_CONTRACT.md`.
- [ ] ADR-0001 through ADR-0005 marked `Accepted`.

**No code written.**

---

## M1 — Walking skeleton

**Goal:** Tauri app launches, talks to Python backend, runs the full pipeline against the `mock` backend, displays a 3D preview, exports a `.glb`. End-to-end works; nothing is real yet.

**Scope:**
- Tauri scaffold via `create-tauri-app`. React + TS strict + Tailwind + shadcn/ui.
- Python backend scaffold: FastAPI, SQLite, SSE, the stage graph executor with a single stage that just calls the mock backend.
- `MockGPUBackend` returns a fixture `.glb` of a cube.
- One Blender script: `cleanup.py` — runs the real op on the fixture cube.
- One canonical render via `render_views.py` — wired but skipped in mock mode (mock returns canned renders).
- One canonical evaluator — wired but returns a hardcoded score in mock mode.
- 3D preview in React Three Fiber.
- Export step writes the `.glb` to disk.

**Exit criteria:**
- [ ] `pnpm tauri dev` starts the app on Windows.
- [ ] Drag-drop an image → progress UI shows all stages → final viewer renders a cube → "Export" produces a `.glb`.
- [ ] All inter-process contracts (HTTP + SSE + Blender subprocess) are exercised at least once.
- [ ] No real ML libraries pulled in yet (kept light so the app boots fast).
- [ ] Lint + typecheck + cargo check all clean.
- [ ] Backend RSS at idle < 300 MB; cold-start to "ready" < 4 s.

**Why this milestone exists:** the integration risk is highest. Better to integrate three runtimes against fake AI than to debug Hunyuan3D-2 and integration at the same time.

---

## M2 — Real generator on remote GPU

**Goal:** the mock backend is replaced (or augmented) by a real Colab notebook running TripoSR. Image goes in, real (low-quality) mesh comes out.

**Scope:**
- Colab notebook authored: installs TripoSR, exposes FastAPI on a port, tunnels via ngrok.
- `RemoteGPUBackend` adapter implementing `/generate`.
- TripoSRAdapter (works on both remote and local).
- Preprocessing (rembg → cv2 alpha cleanup → resize) implemented in the orchestrator.
- Real Blender cleanup runs on TripoSR's output.
- 3D preview shows the actual generated mesh.

**Exit criteria:**
- [ ] A real photo of a clean-background object → generated mesh in the viewer in < 60 s.
- [ ] Switching `GPU_BACKEND=mock` vs `remote` works at runtime via the settings panel.
- [ ] All errors surfaced cleanly (Colab disconnect, ngrok auth, generator OOM).
- [ ] At least 10 sample inputs produce sensible (not great) results; checked into `evaluation/samples/`.

---

## M3 — Evaluation + refinement loop

**Goal:** the iterative refinement loop is real. Models improve across iterations.

**Scope:**
- Full multi-view renderer (`render_views.py`, default8 view set).
- Evaluator stack on the remote endpoint: CLIP + DINOv2 + LPIPS + silhouette IoU.
- Refinement planner rules engine implemented per `QUALITY_RUBRIC.md` §4–5.
- The pipeline graph executor runs the loop with proper iteration tracking, `best_iteration` selection, stopping rule, SSE events.
- UI: per-iteration timeline, per-metric breakdown, plain-language diagnosis line.

**Exit criteria:**
- [ ] On the M3 calibration set (~50 hand-curated images, see QUALITY_RUBRIC §8), iteration-N score ≥ iteration-1 score on > 75% of cases (any improvement counts).
- [ ] On the calibration set, the binary "is_acceptable" judgement agrees with `overall_score ≥ tuned_threshold` ≥ 80% of the time.
- [ ] Cancelling a running job during any stage produces a clean, non-corrupted state in `state.db`.
- [ ] **Resumability test suite passes** (per `RESUMABILITY_AND_BUDGET.md` §9):
  - kill-mid-stage → resume produces bit-identical final mesh
  - drop the remote → `paused_remote_offline` → auto-resume with zero double-billed calls
  - reboot simulation → resume from last completed stage with same total `gpu_call.runtime_ms`
- [ ] Pause / resume buttons work from the UI; paused jobs survive an app close and reopen.
- [ ] Generation cache hit on identical (image, model, seed, params) returns in < 200 ms with `cached=1` in the gpu_call row.

This is the milestone where "world-class" becomes measurable.

---

## M4 — Hunyuan3D-2 + texture refinement

**Goal:** swap the primary generator to Hunyuan3D-2 (better quality). Texture-only refinement becomes a real refinement action.

**Scope:**
- Hunyuan3D-2 adapter — runs on a beefier Colab/Modal instance (paid tier likely needed for sustained dev; Modal $30 credit covers a few hundred jobs).
- `texture_refine_only` action wired to Hunyuan's texture-only mode (or Paint3D as a fallback if Hunyuan API doesn't expose it).
- TripoSR retained as the "fast preview" generator — it always runs first and produces a placeholder while Hunyuan runs.

**Exit criteria:**
- [ ] On the calibration set, Hunyuan-driven runs score higher than TripoSR-driven runs by ≥ 0.10 mean overall_score.
- [ ] Fast preview (TripoSR) visible in the viewer in < 20 s, even when Hunyuan is still running.
- [ ] Texture-only refinements actually move the D (DINOv2) sub-score upward when triggered, in > 60% of cases.

---

## M5 — Polish

**Goal:** the desktop app feels like a product, not a prototype.

**Scope:**
- Onboarding flow (first-launch wizard: GPU backend, HF token).
- Settings panel polished, per-project config, recently-used.
- Job library view: sort, filter, search, rerun, duplicate.
- Quality dashboard: history of scores, comparison view (input | render | mesh side-by-side).
- **Budget panel** in Settings: GPU-time today/week/lifetime, per-provider breakdown, cache hit rate, optional caps, frugal-mode toggle.
- Export presets ("Web-ready glTF", "Unity-compatible OBJ", "Game-engine PLY").
- Crash reporter (local file write; never uploads — single-user app).
- App icon, splash, codesigning on Windows (signed installer).

**Exit criteria:**
- [ ] Installer (`.msi` or `.exe`) builds from CI.
- [ ] Tutorial path: install → first job → export → < 5 min for a non-technical user.
- [ ] Lighthouse-style internal audit: zero blocking UX issues, no jank > 100 ms on 60-fps targets.

---

## M6 — Local GPU mode

**Goal:** when the user gets an NVIDIA box, everything runs locally with no behavior change.

**Scope:**
- `LocalGPUBackend` adapter (the very same `ai_models/` code, just imported in-process).
- One-time setup script: detects CUDA, installs the right PyTorch, downloads weights, smoke-tests the pipeline.
- "Local" mode visible in the settings panel; auto-detected if CUDA + sufficient VRAM present.

**Exit criteria:**
- [ ] On a 12 GB NVIDIA card: full Hunyuan run + 3 refinement iterations in < 6 minutes.
- [ ] First-launch detection of CUDA → guided setup that ends with a working `local` mode.

---

## Cross-cutting practices

These are not milestones but they must hold throughout:

- **Test pyramid:** unit tests for adapters, contract tests for HTTP, smoke tests for Blender scripts, end-to-end tests for the mock pipeline. Run on CI per push.
- **Performance baselines:** the M1 + M3 + M5 milestones each freeze a perf baseline. Regressions > 20% block merges.
- **Reproducibility:** all generations are seeded. The same seed + same model revision must produce bit-identical meshes.
- **Resumability is non-regressable.** Any change that breaks the resumability test suite (RESUMABILITY_AND_BUDGET §9) is a blocker.
- **Docs as code:** any code change that affects PIPELINE / BACKEND_CONTRACT / QUALITY_RUBRIC / RESUMABILITY_AND_BUDGET includes a docs PR in the same commit.

---

## What we are explicitly NOT building

Listing these so the team (and the agent) stops being tempted:

- Account systems, cloud sync, multiplayer.
- A "prompt-to-3D" mode without an image. The spec is image-driven.
- Real-time collaborative editing.
- Plugins / extension marketplace.
- A mobile companion app.
- Auto-publishing to Sketchfab / TurboSquid / etc.

All of these are reasonable future products. None of them are v1.
