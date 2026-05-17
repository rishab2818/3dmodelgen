/**
 * Tiny strip showing backend health + active GPU backend. Reassures the user that the
 * orchestrator is alive.
 */
import { useHealth } from "@/lib/api";

export function StatusBar(): JSX.Element {
  const health = useHealth();
  const ok = health.data?.status === "ok";

  return (
    <div className="flex items-center gap-3 text-xs">
      <span
        className={`inline-block h-2 w-2 rounded-full ${
          ok ? "bg-success" : "bg-error"
        }`}
      />
      <span className="text-muted">
        backend{" "}
        <span className="text-text">
          {health.isError ? "offline" : (health.data?.status ?? "…")}
        </span>
      </span>
      <span className="text-muted">&middot;</span>
      <span className="text-muted">
        gpu{" "}
        <span className="text-text">{health.data?.gpu_backend ?? "—"}</span>
      </span>
    </div>
  );
}
