# ADR-0002: GPU backend abstraction — mock / remote / local

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** user, Claude

## Context

The product *must* support local GPU execution per the spec. The dev machine has **no NVIDIA GPU** (Intel Iris Xe, no CUDA). Buying hardware now is not an option. We still need to ship a credible v1.

Constraints:
- The user wants to build the full product **now**.
- The user wants to drop in local GPU **later**.
- The system has to be testable on the current machine without a GPU.

If we let local CUDA assumptions leak through the codebase, swapping in remote (or mock) becomes a refactor instead of a config change.

## Decision

All AI pipeline stages call a `GPUBackend` adapter chosen at runtime by the `GPU_BACKEND` env var. There are exactly three implementations:

| Mode | Used for | Backed by |
|---|---|---|
| `mock` | UI dev, integration tests, demo without internet | canned fixtures + scripted scores in `ai_models/fixtures/` |
| `remote` | AI dev on the current machine | HTTP to a remote FastAPI server (Colab + ngrok in dev, Modal later) |
| `local` | Production for users with NVIDIA hardware | in-process `ai_models/` adapters on local CUDA |

The remote endpoint **runs the same `ai_models/` adapter code as `local`**, wrapped in `ai_models/remote_server.py`. There is no second implementation of TripoSR-on-the-server. This is critical: there must be no behavior divergence between modes.

Concrete dev workflow during M2–M4:
1. Open `notebooks/dev_gpu_server.ipynb` in Google Colab (free T4).
2. Run all cells → installs deps, starts FastAPI, prints an ngrok URL.
3. Paste the ngrok URL into the desktop app's settings panel.
4. Set `GPU_BACKEND=remote`. Done.

## Consequences

**Good**
- We can keep coding now, on a machine that can't run Hunyuan3D-2 locally.
- Switching from Colab to Modal (when free tier runs out) is a URL change.
- `mock` mode means UI work doesn't need any GPU and runs in seconds.
- Testing is cheap and offline.

**Bad**
- The HTTP round-trip + base64 mesh encoding adds ~1–3 s of overhead per call vs. in-process. Acceptable for jobs that are tens of seconds long.
- Colab notebooks time out at 12h and disconnect on inactivity. The app will show "Remote GPU offline" and the user has to re-run the notebook. Documented in the UI.
- ngrok free tier rotates the URL on restart. The app stores the most recent URL and re-prompts only when health checks fail.
- We're bound to the constraint that *any* feature added to one mode must work in all three. This is a real discipline tax but it's a feature, not a bug.

**Neutral**
- Modal Labs has a $30/month free credit and persistent endpoints. When we outgrow free Colab+ngrok, we move there. The adapter doesn't change.

## Alternatives considered

**Single-mode design (only local CUDA).** Rejected — blocks all development on this machine. The user explicitly said "I can't hold my development for not having resources."

**Cloud-only (always remote, no local mode).** Rejected — the spec is explicit about local execution being the long-term goal. Building only for remote and bolting on local later means assumptions get baked in that we'd have to rip out.

**Local-with-CPU-fallback.** I.e., run Hunyuan3D-2 on CPU on this machine. Rejected because Hunyuan on CPU is unusable (1+ hour per generation) and would distort the dev feedback loop. TripoSR-on-CPU is borderline OK (~5 min) and we keep that as a fallback for `mock`/`local` users without GPUs, but it is not the path of primary development.

**SSH tunnel to a friend's machine.** Considered, rejected: same architecture as ngrok but worse uptime guarantees.
