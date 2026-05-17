# ai_models/ — Model adapters + GPU server

> Folder-scoped rules. Read `../CLAUDE.md` first.

This folder holds **all GPU code** in the repo. It is the only place that imports `torch`, `transformers`, `diffusers`, `triposr`, etc. Consumed in two ways:

1. **In-process (local mode, M6):** the orchestrator imports `m3d_ai.adapters` directly.
2. **Over HTTP (remote mode, M2+):** `m3d_ai.remote_server:app` is a FastAPI app deployed to Colab/Modal.

**Same adapter code runs in both modes.** Behavior divergence is a regression.

---

## 1. Layout (as of M2)

```
ai_models/
├── pyproject.toml                  optional extras: [torch] for the GPU host, [dev] for testing
├── .python-version                 3.10
├── README.md
├── src/m3d_ai/
│   ├── __init__.py
│   ├── adapters/
│   │   ├── base.py                 GeneratorAdapter + EvaluatorAdapter Protocols
│   │   ├── mock.py                 cube-fixture; works without torch
│   │   └── triposr.py              real TripoSR; lazy torch import on warm_up()
│   ├── registry.yaml               pinned (repo, revision, min_vram_mb) per generator
│   ├── registry.py                 typed loader
│   ├── settings.py                 env M3D_AI_*
│   ├── idempotency.py              LRU + TTL cache for Idempotency-Key dedup
│   └── remote_server.py            FastAPI app: /health, /generate, /evaluate(stub)
├── fixtures/
│   └── cube.obj                    canonical mock-mode mesh
├── notebooks/
│   └── dev_gpu_server.ipynb        Colab: install, start server, ngrok tunnel
└── tests/
    ├── conftest.py
    └── test_remote_server.py       5 tests: health, round-trip, idempotency dedup
```

`m3d_ai.evaluators.*` lands in **M3** alongside the real CLIP+DINOv2+LPIPS evaluator.

---

## 2. Non-negotiables

1. **Pin every revision** in `registry.yaml`. Code that uses `revision="main"` is broken.
2. **Idempotency-Key required** on `/generate` and `/evaluate`. See `idempotency.py` for the cache semantics:
   - in-flight: subsequent calls block on the first and return its result
   - within TTL: cached response returned without re-running the model
   - past TTL: re-run
3. **Lazy torch imports.** Top-level `import torch` in `m3d_ai/__init__.py` or any module imported by `mock.py` is a regression — the dev laptop must be able to `import m3d_ai` without torch.
4. **Adapter Protocol fidelity.** Every new generator implements `GeneratorAdapter` (see `adapters/base.py`). Don't subclass; structural typing only.
5. **Seeds always explicit.** The seed lives in the request body. Pass it to `torch.manual_seed` AND `torch.cuda.manual_seed_all`. No `time()`-based seeds.
6. **Return `runtime_ms` and `vram_peak_mb`** in every generation response. The orchestrator's budget ledger depends on these (see RESUMABILITY_AND_BUDGET.md §4).

---

## 3. How requests flow

```
orchestrator (backend)               remote_server (ai_models)
       │
       │  POST /generate
       │  Authorization: Bearer ...
       │  Idempotency-Key: <job>:<iter>:<stage>:<call_idx>
       │  body: { model, images_b64, seed, params }
       │ ──────────────────────────────► IdempotencyCache.execute(key, ...)
       │                                       │
       │                                       │ (cache miss)
       │                                       │ adapter.generate(images, seed, params)
       │                                       │ ◄ result: bytes + meta
       │                                       │
       │                                       ▼
       │  200 OK                               cache stored; future calls
       │  { mesh_obj_b64, meta }               with this key skip the adapter
       │ ◄──────────────────────────────
```

---

## 4. Two ways to run the server

**Dev laptop (mock adapter, no GPU, no torch):**

```
cd ai_models
uv sync --extra dev
M3D_AI_PRIMARY_GENERATOR=mock uv run uvicorn m3d_ai.remote_server:app --port 8000
```

Hit it from another shell:
```
curl http://127.0.0.1:8000/health
```

**Colab (TripoSR, real):**

Open `notebooks/dev_gpu_server.ipynb`, run all cells. The notebook auto-installs `[torch]`, clones TripoSR, sets env, starts uvicorn, and prints the ngrok URL.

---

## 5. Adding a new adapter

1. Add a new file under `adapters/`.
2. Implement the `GeneratorAdapter` Protocol (`name`, `revision`, `min_vram_mb`, `warm_up`, `unload`, `generate`).
3. Add an entry to `registry.yaml` with the pinned HuggingFace commit hash.
4. Add a branch in `remote_server.py:_make_adapter`.
5. Add a test in `tests/`.
6. Document in `docs/PIPELINE.md` Stage 2.

The adapter must NOT do its own HTTP, file I/O outside the cache dir, or business logic. Pure compute.

---

## 6. Things explicitly NOT allowed here

- **Business logic / orchestration.** Pipeline graph lives in `backend/`. Adapters are leaves, not branches.
- **HTTP routing inside adapters.** Only `remote_server.py` does HTTP.
- **Subprocess calls to Blender.** Mesh post-processing belongs in the orchestrator via `blender_runner`.
- **Unpinned model revisions.** `revision="main"` is banned everywhere.
