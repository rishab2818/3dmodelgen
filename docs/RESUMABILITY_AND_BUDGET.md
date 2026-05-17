# Resumability and Budget-Conscious Operation

Status: **Draft v1 — for sign-off before M1**

> The product's audience includes users who cannot afford lots of GPU credits and whose connections drop. The system is designed so a Colab disconnect, a ngrok URL change, an app crash, or a week-long pause never wastes the work that was already done. **This is a contract, not an aspiration.**

This document specifies the durability, pause/resume, budget tracking, and idempotency behavior that `backend/pipeline/` and `app/` must implement. The architectural decision is captured in [ADR-0006](./DECISIONS/ADR-0006-resumability-and-budget.md).

---

## 1. The durability contract

| Survives | How |
|---|---|
| Remote GPU disconnect (Colab timeout, ngrok URL rotation, network drop) | Job pauses to state `paused_remote_offline`; resumes when the remote endpoint is reachable again. No artifacts lost. |
| User clicks Pause | Job moves to state `paused_by_user`; current stage is allowed to finish if it's > 50% complete, otherwise interrupted at the next safe point. Resumable next session. |
| Backend process crash | On next launch, all `running` jobs are reset to `paused_crashed`. They resume from the last completed stage. No double-billing because of idempotency keys (§5). |
| App close (Tauri window closed) | Backend can keep running headless (configurable); else same as crash recovery. |
| Machine reboot | Same as crash recovery. |
| A week-long pause | Same. Artifacts on disk are retained until the user explicitly clears them. |

**What does NOT survive:** disk loss, manual deletion of `temp/{job_id}/`, manual edits to `state.db`. We do not back up to the cloud.

---

## 2. Stage-level resumability (not iteration-level)

A job is a sequence of iterations. Each iteration is a sequence of stages. **We checkpoint at the stage boundary, not the iteration boundary.** Reasons:

- Stages are 10s–120s each. Re-running a stage costs cents at worst.
- Iterations are minutes-to-tens-of-minutes. Re-running an iteration wastes real money.
- Stage-level granularity is enough — finer (intra-stage) is much more complex and not justified.

Implementation:

- Each stage writes its artifacts to `temp/{job_id}/iter_{n}/{stage}/...`.
- The **last** thing each stage does is write `temp/{job_id}/iter_{n}/{stage}/.complete` containing `{"completed_at": "...", "idempotency_key": "..."}`.
- On resume, the executor walks the stage graph and skips any stage where `.complete` exists. The skipped stage emits a synthetic `stage_update` event with `status=cached_from_disk` so the UI timeline still shows it.

A stage that crashed mid-write leaves no `.complete` file → safe to re-run.

---

## 3. Pause and resume UX

### States the user sees

| Backend state | UI label | What's happening |
|---|---|---|
| `queued` | "Waiting for GPU" | not started yet |
| `running` | "Working..." | actively executing |
| `paused_by_user` | "Paused" | user clicked pause |
| `paused_remote_offline` | "Waiting for remote GPU" | health check failing |
| `paused_crashed` | "Recovering" | backend just came back up |
| `paused_budget` | "Budget cap hit" | exceeded per-job or per-session limit |
| `succeeded` / `failed` / `cancelled` | terminal | unchanged |

### Controls

- Every running or paused job has a `Pause` / `Resume` button.
- Cancelled is **distinct from paused** — cancel is terminal, pause is not.
- A "Resume all paused" action exists at the job-list level.
- `paused_remote_offline` auto-resumes when `/health` to the remote succeeds for two consecutive pings.

### What pause actually does at runtime

- Sets a `pause_requested` flag in the job record.
- The stage executor checks the flag between stages. If set, it sets state to `paused_by_user` and exits the loop. No mid-stage abort.
- Exception: if the current stage is a remote `/generate` or `/evaluate` HTTP call, we let it complete (it's billing whether we wait or not), then pause. If it fails, the next resume re-issues with the same idempotency key (§5).

---

## 4. Budget tracking and caps

### What we measure

For every remote-GPU call, the remote endpoint returns in its response body:

```json
{
  "meta": {
    "model": "hunyuan3d-2",
    "revision": "4b2e83f1",
    "seed": 42,
    "runtime_ms": 73420,
    "vram_peak_mb": 12800,
    "compute_seconds": 73.4,
    "estimated_credits": { "provider": "colab", "value": 0.0, "currency": "free" }
  }
}
```

The orchestrator records every call as a `GpuCall` row in `state.db`:

```sql
CREATE TABLE gpu_call (
  id            INTEGER PRIMARY KEY,
  job_id        TEXT NOT NULL,
  iteration     INTEGER NOT NULL,
  stage         TEXT NOT NULL,
  model         TEXT NOT NULL,
  revision      TEXT NOT NULL,
  runtime_ms    INTEGER NOT NULL,
  vram_peak_mb  INTEGER,
  provider      TEXT NOT NULL,             -- 'colab' | 'modal' | 'runpod' | 'local'
  est_credits   REAL,                       -- nullable; provider-defined units
  est_currency  TEXT,                       -- 'free' | 'USD' | 'modal_credit' | etc.
  cached        INTEGER NOT NULL DEFAULT 0, -- 1 if served from cache (then runtime_ms = 0)
  created_at    TEXT NOT NULL
);
```

### What the user sees

- **Per-job summary** on each job card: *"GPU time: 3m 47s • Provider: Colab (free) • 2 cached hits"*.
- **Settings → Budget**: cumulative GPU time today / this week / lifetime. Per-provider breakdown.
- **Pre-flight estimate** when starting a job: *"Estimated 1m–4m on Hunyuan3D-2. Cache may make this faster."*

### Caps

Two optional caps (off by default; user opts in from Settings → Budget):

| Cap | When triggered | What happens |
|---|---|---|
| Per-job GPU-minutes | a single job exceeds its cap | Job moves to `paused_budget`. User can raise the cap and resume, or accept the best-iteration-so-far as the export. |
| Per-session GPU-minutes | total since app launch | Newly-started jobs go to `queued` indefinitely; running jobs finish their current iteration then move to `paused_budget`. |

There is **no** "automatic credit charge" anywhere. Caps are advisory limits, not payment gates.

### Frugal mode

A boolean setting (default off): "Frugal mode — prefer fast/cheap models."

When on:
- Generator selection forced to `triposr` regardless of `auto`/`hunyuan3d-2` preference.
- Max iterations capped at 3.
- Multi-view render uses `default8` only (never `dense24`).
- The refinement planner's `regenerate_with_higher_capacity` action is replaced with `regenerate_with_new_seed`.

The user can switch a job from frugal to full mode and re-trigger refinement — the partial work is preserved.

---

## 5. Idempotency: never pay twice

Every call to the remote GPU endpoint carries an `Idempotency-Key` header:

```
Idempotency-Key: {job_id}:{iteration}:{stage}:{call_index}
```

The remote endpoint maintains a small LRU (e.g. last 1000 keys, 24h TTL) mapping key → response. On a repeated request with the same key:

- Within TTL → returns the cached response. Does **not** re-run the model. Does **not** count against any quota.
- TTL expired → re-runs (rare on a single dev session; tunable per provider).

This is exactly the pattern Stripe and others use. The pattern matters because:

- If the orchestrator's HTTP call times out *after* the GPU finished but *before* the response reached us, a naive retry would re-bill. With idempotency, the retry gets the cached response.
- If the user pauses then resumes during a stuck call, the resume re-issues with the same key.

**Idempotency-Key generation is deterministic** from job state — the orchestrator does NOT generate random keys, because a crashed-then-restarted backend wouldn't have the same random.

---

## 6. The cache layer

A second-tier "don't even hit the remote" cache lives in the orchestrator:

```
cache_key = sha256(
    sha256(preprocessed_image_bytes)
    || model_name
    || model_revision
    || seed
    || canonical_json(params)
)
```

When a stage is about to call the remote, it checks `models_cache/generation_cache/{cache_key}/` for a prior result. Hit → record a `GpuCall` row with `cached=1, runtime_ms=0`, emit `stage_update` with `status=cache_hit`, return the cached artifacts.

The cache is keyed on the **preprocessed** image (after Stage 1), so a user who re-uploads the same photo at a different crop still hits the cache if the preprocessor produces the same bytes.

**Eviction:** LRU when `models_cache/generation_cache/` exceeds a configurable size (default 5 GB). Tunable in Settings.

**Privacy note:** the cache is local-only. Single-user desktop app. No leak surface.

---

## 7. Adaptive degrade-on-flake

When the remote endpoint is unreachable for > 5 minutes:

- All `running` jobs move to `paused_remote_offline`.
- The UI banner says *"Remote GPU offline. Resuming when it comes back. Or switch to Frugal mode (TripoSR-only, can run locally on CPU in ~5 min)."*
- If the user switches to local CPU TripoSR mid-job, the partial Hunyuan output is preserved and TripoSR runs alongside — the planner picks the better of the two for the next iteration.

This is the "graceful degradation" that earns trust from budget-constrained users.

---

## 8. What state.db looks like

The minimal schema (full DDL in `backend/db/migrations/0001_init.sql`):

```sql
CREATE TABLE job (
  id              TEXT PRIMARY KEY,
  label           TEXT,
  state           TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  paused_reason   TEXT,
  inputs_json     TEXT NOT NULL,    -- the original CreateJobRequest
  best_iter_n     INTEGER,
  budget_cap_s    INTEGER           -- per-job seconds cap; NULL = no cap
);

CREATE TABLE iteration (
  job_id          TEXT NOT NULL,
  n               INTEGER NOT NULL,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  score_json      TEXT,             -- the EvaluationReport
  refinement_action TEXT,
  PRIMARY KEY (job_id, n)
);

CREATE TABLE stage_run (
  job_id          TEXT NOT NULL,
  iteration       INTEGER NOT NULL,
  stage           TEXT NOT NULL,
  status          TEXT NOT NULL,    -- pending|running|complete|failed|cache_hit
  started_at      TEXT,
  finished_at     TEXT,
  artifacts_json  TEXT,
  error_json      TEXT,
  idempotency_key TEXT,
  PRIMARY KEY (job_id, iteration, stage)
);

CREATE TABLE gpu_call (...);    -- see §4 above
```

All state changes happen in **a single transaction per stage transition**. There is no in-memory state that isn't also on disk. That's the property that makes resumability work.

---

## 9. Resumability tests (M1 + M3 exit criteria)

Three tests must pass:

1. **Kill mid-stage:** start a job, `SIGKILL` the backend mid-`generate.initial`, restart, job resumes from the same stage and produces the same final mesh as a non-interrupted run (bit-identical via deterministic seed).
2. **Drop the remote:** start a job, point `GPU_BACKEND_URL` to `127.0.0.1:9` (closed port) mid-flight, observe `paused_remote_offline`, restore the URL, observe auto-resume with no double-billed GPU call (idempotency).
3. **Reboot simulation:** start a job, stop the backend cleanly, wait 60 s, restart, job resumes from last completed stage, total `gpu_call.runtime_ms` is identical to a non-interrupted run.

These move from `nice-to-have` to **required exit criteria** for M3.

---

## 10. UI surface (what users actually see)

The UI exposes three new things:

1. **Job state pill** with the labels in §3, color-coded.
2. **Pause / Resume** button on each job.
3. **Settings → Budget panel:**
   - GPU-time today / this week / lifetime
   - Per-provider breakdown
   - Cache hit rate
   - "Clear cache (5 GB)" button
   - Optional caps (per-job, per-session)
   - Frugal mode toggle

There is no graph that pretends to predict cost in dollars. Free tiers don't have dollar costs; paid tiers vary. We surface compute time and let the user reason about their own provider's pricing.

---

## 11. Why this is the right shape

Other image-to-3D tools assume infinite GPU. We don't. Designing for the constrained case is what makes this product land with the audience the spec implies: independent creators, hobbyists, students, anyone who doesn't have a 4090 in the closet.

Resumability + budget transparency + idempotency + caching are the four moves that, together, mean a user with a $5/month Modal credit gets meaningful work done — and a user with intermittent Wi-Fi never loses progress.
