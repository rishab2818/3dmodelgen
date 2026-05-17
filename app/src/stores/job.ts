/**
 * Per-job timeline state. SSE events are merged in via `applyEvent`.
 *
 * Zustand keeps everything in one slim store for M1; we split per concern in M5.
 */
import { create } from "zustand";
import type {
  BudgetUpdateEvent,
  IterationComplete,
  JobCompleteEvent,
  JobFailedEvent,
  JobSnapshot,
  StageUpdate,
} from "@/lib/schemas";

export type TimelineStage = StageUpdate;

export type TimelineIteration = {
  n: number;
  stages: TimelineStage[];
  score?: IterationComplete["score"];
  refinementAction?: string | null;
};

type JobLifecycle =
  | { kind: "idle" }
  | { kind: "running"; jobId: string }
  | { kind: "succeeded"; jobId: string; exports: Record<string, string> }
  | { kind: "failed"; jobId: string; error: { code: string; message: string } };

type State = {
  activeJobId: string | null;
  lifecycle: JobLifecycle;
  iterations: TimelineIteration[];
  lastBudget?: BudgetUpdateEvent;
  snapshot?: JobSnapshot;

  startTracking(jobId: string): void;
  applyEvent(event: string, data: unknown): void;
  reset(): void;
};

export const useJobStore = create<State>((set) => ({
  activeJobId: null,
  lifecycle: { kind: "idle" },
  iterations: [],

  startTracking(jobId) {
    set({
      activeJobId: jobId,
      lifecycle: { kind: "running", jobId },
      iterations: [],
      lastBudget: undefined,
      snapshot: undefined,
    });
  },

  reset() {
    set({
      activeJobId: null,
      lifecycle: { kind: "idle" },
      iterations: [],
      lastBudget: undefined,
      snapshot: undefined,
    });
  },

  applyEvent(event, data) {
    set((s) => {
      switch (event) {
        case "snapshot": {
          const { job } = data as { job: JobSnapshot };
          return { snapshot: job };
        }
        case "stage_update": {
          const update = data as StageUpdate;
          const iters = [...s.iterations];
          let it = iters.find((x) => x.n === update.iteration);
          if (!it) {
            it = { n: update.iteration, stages: [] };
            iters.push(it);
            iters.sort((a, b) => a.n - b.n);
          }
          const idx = it.stages.findIndex((x) => x.stage === update.stage);
          if (idx >= 0) {
            it.stages[idx] = update;
          } else {
            it.stages = [...it.stages, update];
          }
          return { iterations: iters };
        }
        case "iteration_complete": {
          const ic = data as IterationComplete;
          const iters = [...s.iterations];
          const it = iters.find((x) => x.n === ic.iteration);
          if (it) {
            it.score = ic.score;
            it.refinementAction = ic.refinement_action;
          }
          return { iterations: iters };
        }
        case "job_complete": {
          const c = data as JobCompleteEvent;
          if (s.activeJobId == null) return s;
          return {
            lifecycle: {
              kind: "succeeded",
              jobId: s.activeJobId,
              exports: c.exports,
            },
          };
        }
        case "job_failed": {
          const f = data as JobFailedEvent;
          if (s.activeJobId == null) return s;
          return {
            lifecycle: {
              kind: "failed",
              jobId: s.activeJobId,
              error: f.error,
            },
          };
        }
        case "budget_update": {
          return { lastBudget: data as BudgetUpdateEvent };
        }
        default:
          return s;
      }
    });
  },
}));
