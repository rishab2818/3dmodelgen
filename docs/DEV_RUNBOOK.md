# Dev runbook (M1)

How to actually run the thing while developing. M1 ships with the backend and the Tauri app as two separate processes — Tauri does not auto-spawn the backend yet (that's M2).

## Prerequisites (one-time)

- Python 3.10 via uv: `uv python install 3.10` (already installed)
- pnpm: `npm i -g pnpm` (already installed)
- Rust + create-tauri-app: `cargo install create-tauri-app --locked` (already installed)
- Blender 5.x at `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`

## First-run setup

```powershell
# Backend
cd D:\3dmodel_gen\backend
uv sync --extra dev

# Frontend
cd ..\app
pnpm install
```

## Daily dev loop

**Terminal 1 — backend:**

```powershell
cd D:\3dmodel_gen\backend
uv run uvicorn m3d_backend.app.main:app --reload --port 7878
```

You should see structured logs ending in `backend.start port=7878 gpu_backend=mock`. Verify with:

```powershell
curl http://127.0.0.1:7878/health
```

**Terminal 2 — Tauri app:**

```powershell
cd D:\3dmodel_gen\app
pnpm tauri dev
```

First run compiles ~400 Rust crates (5–15 min). Subsequent runs are seconds.

## Tests + checks

Backend:
```powershell
cd D:\3dmodel_gen\backend
uv run pytest -v                # 3 tests, ~6s with mock pipeline + real Blender
uv run ruff check src tests
uv run pyright src
```

Frontend:
```powershell
cd D:\3dmodel_gen\app
pnpm typecheck                  # strict TS, no `any`
```

Tauri Rust:
```powershell
cd D:\3dmodel_gen\app\src-tauri
cargo check
cargo clippy -- -D warnings
```

## Useful env knobs (backend)

All prefixed `M3D_`:

| Var | Default | Notes |
|---|---|---|
| `M3D_GPU_BACKEND` | `mock` | `mock` / `remote` / `local` (only `mock` is wired in M1) |
| `M3D_PORT` | `7878` | |
| `M3D_BLENDER_EXE` | path to Blender 5.1 | override if installed elsewhere |
| `M3D_MOCK_DELAY_MS` | `400` | how long the mock pretends to "work" — set to `0` for fast tests |
| `M3D_MOCK_SCORE_PROFILE` | `instant_success` | `instant_success` / `improving` / `stuck` / `oscillating` — drives refinement loop behavior |
| `M3D_LOG_LEVEL` | `INFO` | |
| `M3D_LOG_JSON` | `false` | true = structured JSON logs, useful for piping |

## Smoke test (manual)

Once both processes are up:

1. The Tauri window opens.
2. Click the dropzone → pick any image file (it's a placeholder in mock mode).
3. The progress timeline lights up: preprocess → generate → blender_cleanup → render_multiview → evaluate.
4. The R3F viewer loads the resulting cube `.glb`.
5. Click "show exports folder" — Explorer opens `D:\3dmodel_gen\exports\<job_id>\` with `model.glb`, `model.obj`, `report.json`.

If any of those break: check the backend terminal for the error, and check the browser devtools console (right-click → Inspect in the Tauri window).

## Common issues

| Symptom | Likely cause |
|---|---|
| `backend offline` in status bar | uvicorn not running on 7878 |
| Tauri compiles forever | first-run Rust build — be patient. Subsequent runs cache. |
| Blender stage fails | wrong `M3D_BLENDER_EXE` path, or Blender 4.x (we require 5.x) |
| `pnpm typecheck` complains about `env` | missing `src/vite-env.d.ts` reference |

---

## M2 — running against a real Colab GPU

The dev laptop has no NVIDIA GPU, so the AI generators run on a remote box. Default dev target is Google Colab + ngrok.

### One-time setup
1. **ngrok auth token** — sign up at https://ngrok.com (free), copy your token.
2. Open https://huggingface.co/settings/tokens, generate a read token (only needed once we use gated models in M4).

### Daily Colab flow
1. Open `ai_models/notebooks/dev_gpu_server.ipynb` in Colab (File → Upload notebook).
2. Runtime → Change runtime type → **GPU (T4)**.
3. Add Colab Secrets:
   - `NGROK_AUTHTOKEN` — your ngrok token
   - (optional) `BACKEND_TOKEN` — a random secret of your choosing; the notebook auto-generates one if absent
   - (optional) `HF_TOKEN` — for gated models, M4 onward
4. Edit the `REPO_URL` cell to point to your fork.
5. Runtime → Run all. The last cell prints:
   - `https://xyz.ngrok-free.app` — the public URL
   - `BACKEND_TOKEN` — the bearer token

### Pointing the orchestrator at it
Two ways:

**(a) env var, restart backend:**
```powershell
$env:M3D_GPU_BACKEND = "remote"
$env:M3D_GPU_BACKEND_URL = "https://xyz.ngrok-free.app"
$env:M3D_GPU_BACKEND_TOKEN = "<paste-token>"
$env:M3D_GPU_BACKEND_PROVIDER = "colab"   # recorded in budget ledger
uv run uvicorn m3d_backend.app.main:app --reload --port 7878
```

**(b) runtime PUT /config (no restart):**
```powershell
curl -X PUT http://127.0.0.1:7878/config -H "content-type: application/json" -d @- <<'JSON'
{
  "gpu_backend": "remote",
  "gpu_backend_url": "https://xyz.ngrok-free.app",
  "gpu_backend_token": "<paste-token>",
  "gpu_backend_provider": "colab"
}
JSON
```

`GET /health` will now show `gpu_backend: remote` and the remote adapter's name + revision.

### What to expect on first remote run
- TripoSR weights (~1 GB) download to the Colab session on first invocation.
- First image-to-3D round-trip: ~30–60 s (including weight load).
- Subsequent calls: ~5–15 s.
- Cache hit (same image + seed + params): < 1 s — the remote returns the cached response by Idempotency-Key.

### When Colab disconnects
- The remote `/health` ping starts failing.
- Running jobs move to `paused_remote_offline`.
- Rerun the Colab notebook; the ngrok URL changes; PUT /config with the new URL.
- The orchestrator's auto-resume (M3) reissues paused stages with the same idempotency keys — already-completed work is not re-billed.
