/**
 * Per-iteration, per-stage progress timeline driven by the SSE feed.
 */
import { useJobStore } from "@/stores/job";

const STAGE_LABELS: Record<string, string> = {
  preprocess: "Preprocess",
  generate: "Generate",
  blender_cleanup: "Blender cleanup",
  render_multiview: "Render views",
  evaluate: "Evaluate",
};

function statusColor(status: string): string {
  switch (status) {
    case "complete":
      return "bg-success";
    case "cache_hit":
      return "bg-accent";
    case "running":
      return "bg-warn animate-pulse";
    case "failed":
      return "bg-error";
    default:
      return "bg-border";
  }
}

export function JobTimeline(): JSX.Element {
  const iterations = useJobStore((s) => s.iterations);
  const lifecycle = useJobStore((s) => s.lifecycle);
  const lastBudget = useJobStore((s) => s.lastBudget);

  if (iterations.length === 0 && lifecycle.kind === "idle") {
    return (
      <div className="text-muted text-sm">
        No active job. Drop an image to start.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {iterations.map((it) => (
        <div key={it.n} className="rounded-xl border border-border bg-panel p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="font-medium">Iteration {it.n}</div>
            {it.score && typeof (it.score as { overall_score?: unknown }).overall_score === "number" ? (
              <div className="text-sm text-muted">
                score{" "}
                <span className="text-text font-mono">
                  {((it.score as { overall_score: number }).overall_score).toFixed(2)}
                </span>
              </div>
            ) : null}
          </div>
          <ul className="space-y-2">
            {it.stages.map((s) => (
              <li
                key={s.stage}
                className="flex items-center gap-3 text-sm"
              >
                <span
                  className={`inline-block h-2 w-2 rounded-full ${statusColor(s.status)}`}
                />
                <span className="w-40 text-muted">
                  {STAGE_LABELS[s.stage] ?? s.stage}
                </span>
                <span className="flex-1 text-text">
                  {s.message || s.status}
                </span>
                <span className="font-mono text-xs text-muted">
                  {s.elapsed_ms > 0 ? `${s.elapsed_ms}ms` : ""}
                </span>
              </li>
            ))}
          </ul>
          {it.refinementAction ? (
            <div className="text-xs text-muted mt-3">
              next: <span className="text-text">{it.refinementAction}</span>
            </div>
          ) : null}
        </div>
      ))}

      {lastBudget ? (
        <div className="text-xs text-muted">
          GPU time this job: {(lastBudget.job_total_runtime_ms / 1000).toFixed(1)}s
          {" "}&middot; provider: {lastBudget.provider}
        </div>
      ) : null}
    </div>
  );
}
