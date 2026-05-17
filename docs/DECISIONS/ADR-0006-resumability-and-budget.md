# ADR-0006: Resumability and budget-conscious operation as a first-class concern

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** user, Claude

## Context

The target audience for this product includes users who:

- Cannot afford large GPU-credit budgets.
- Use free-tier cloud GPU (Colab, Kaggle) that **disconnects every 12 hours** and times out on idle.
- Have unreliable connectivity (ngrok URL rotation, flaky Wi-Fi).
- May pause work for days or weeks between sessions.

If a 6-iteration Hunyuan3D-2 job loses progress at iteration 5 because the Colab session dropped, that's not a "rough edge" — that's the product failing its users. Same for accidentally double-billing a GPU call because of a retried HTTP request. Same for paused work being unrecoverable.

We must design for these realities now, while the architecture is still small. Bolting durability onto a mature codebase is expensive; baking it in from M1 is cheap.

## Decision

Resumability, budget transparency, idempotency, and caching are **load-bearing architectural features**, not afterthoughts.

Concretely:

1. **Stage-level resumability.** Every stage in the pipeline writes its artifacts plus a `.complete` marker atomically. The executor's resume path skips stages whose `.complete` exists. Granularity is stage, not iteration.
2. **Durable job state.** All transitions persisted to SQLite (`state.db`) inside a single transaction per stage. No in-memory state that isn't also on disk.
3. **Pause / resume as a first-class user action.** Distinct from cancel. Pauses survive app restarts and reboots.
4. **Auto-pause on remote GPU outage.** Surfaces a clear "waiting for remote" state; auto-resumes when health checks pass.
5. **Idempotency keys** on every remote call (`{job_id}:{iteration}:{stage}:{call_index}`). The remote endpoint deduplicates. Retries are free.
6. **Local generation cache** keyed on `(preprocessed_image_hash, model, revision, seed, params)`. Cache hits skip the remote entirely.
7. **Budget tracking** as a SQL table (`gpu_call`) recording every call. Surfaced in the UI per job and overall.
8. **Optional budget caps** (per-job and per-session) that pause jobs cleanly without losing work.
9. **Frugal mode** that biases generator selection and iteration count toward cheap.

The full contract is in [`RESUMABILITY_AND_BUDGET.md`](../RESUMABILITY_AND_BUDGET.md).

## Consequences

**Good**
- Users on free Colab get usable work done despite the 12h disconnect.
- A crash, ngrok rotation, app close, or week-long pause never wastes paid GPU time.
- The product distinguishes itself on a dimension competitors ignore (most assume infinite GPU).
- Idempotency + caching mean we can be aggressive with retry policies (`tenacity` with high attempt counts) without fear of cost.

**Bad**
- More SQLite writes per job (one transaction per stage transition, not per iteration). Still trivially cheap on WAL-mode SQLite — maybe 200 writes per job.
- Larger disk footprint: intermediate artifacts are retained until the user clears them. Mitigation: cache size cap + a one-click clear in Settings.
- More UI surface (pause/resume buttons, budget panel, frugal toggle). Mitigation: progressive disclosure — basic users never see the budget panel.
- The stage executor is more complex (must walk a stage graph, check `.complete`, emit synthetic `cache_hit` events). Mitigation: this is well-understood pattern (workflow engines have done it for 20 years).

**Neutral**
- Idempotency keys impose a small contract obligation on the remote endpoint (it must maintain an LRU of seen keys). Trivial implementation, ~50 lines.

## Alternatives considered

**Coarser resumability (whole-iteration).** Rejected — wastes too much GPU time on retry. The whole point is to save the user's money.

**No caching, just idempotency.** Rejected — a user re-running with the same image + seed should be instant, not "instant remote round trip." Cache is local, free, and high-value.

**Cloud-side state.** I.e., persist jobs to a hosted service. Rejected — conflicts with the spec's "single-user desktop app, no cloud account" mandate.

**Eventual consistency / async log shipping.** Rejected — overkill for a single-user desktop. WAL-mode SQLite is the right answer.

**Encrypted cache.** Rejected for v1 — single-user app, local-only. Threat model doesn't justify the complexity.

## Related decisions

- [ADR-0002](./ADR-0002-gpu-backend-abstraction.md) — the GPU backend abstraction is what makes a single idempotency contract reachable across mock/remote/local.
- [ADR-0003](./ADR-0003-initial-generator-choice.md) — TripoSR-as-preview supports the frugal-mode default.
