/**
 * M1 single-screen UI: dropzone + timeline + viewer + export button.
 *
 * Multi-page navigation (job library, settings) lands in M5. For M1 the goal is a
 * walking skeleton: one job at a time, drop image → cube → export.
 */
import { useCallback, useMemo } from "react";
import { Dropzone } from "@/components/Dropzone";
import { JobTimeline } from "@/components/JobTimeline";
import { ModelViewer } from "@/components/ModelViewer";
import { StatusBar } from "@/components/StatusBar";
import {
  useCancelJob,
  useCreateJob,
  useJob,
} from "@/lib/api";
import { useJobEvents } from "@/lib/sse";
import { useJobStore } from "@/stores/job";
import { showInFolder } from "@/lib/tauri-files";

export default function App(): JSX.Element {
  const activeJobId = useJobStore((s) => s.activeJobId);
  const lifecycle = useJobStore((s) => s.lifecycle);
  const startTracking = useJobStore((s) => s.startTracking);
  const applyEvent = useJobStore((s) => s.applyEvent);
  const resetJob = useJobStore((s) => s.reset);

  const createJob = useCreateJob();
  const cancelJob = useCancelJob();
  const jobQuery = useJob(activeJobId);

  // Subscribe to the SSE stream for the active job.
  useJobEvents(activeJobId, applyEvent);

  const onSelectedImages = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) return;
      const { job_id } = await createJob.mutateAsync({
        input_images: paths,
        target_quality: 0.85,
        max_iterations: 2,
        export_formats: ["glb", "obj"],
        label: paths[0]?.split(/[\\/]/).pop() ?? "untitled",
      });
      startTracking(job_id);
    },
    [createJob, startTracking],
  );

  const glbRelPath = useMemo(() => {
    if (lifecycle.kind !== "succeeded") return null;
    return lifecycle.exports.glb ?? null;
  }, [lifecycle]);

  const onCancel = useCallback(() => {
    if (activeJobId) void cancelJob.mutate(activeJobId);
  }, [activeJobId, cancelJob]);

  const onShowExport = useCallback(async () => {
    if (lifecycle.kind !== "succeeded") return;
    const rel = lifecycle.exports.glb;
    if (!rel) return;
    // ``rel`` is "exports/<jobId>/model.glb" — reveal the folder.
    await showInFolder(rel.split(/[\\/]/).slice(0, -1).join("/"));
  }, [lifecycle]);

  const isWorking =
    lifecycle.kind === "running" || (jobQuery.data?.state === "running");

  return (
    <div className="h-full w-full flex flex-col">
      <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-panel/60 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="h-7 w-7 rounded-md bg-accent/20 border border-accent grid place-items-center text-accent text-xs font-bold">
            3D
          </div>
          <div className="font-semibold tracking-tight">3dmodel_gen</div>
          <span className="text-xs text-muted ml-2">M1 — walking skeleton</span>
        </div>
        <StatusBar />
      </header>

      <main className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6 p-6 overflow-auto">
        <section className="space-y-6 min-w-0">
          <Dropzone
            onSelected={onSelectedImages}
            disabled={createJob.isPending || isWorking}
          />

          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-muted uppercase tracking-wider">
                Progress
              </h2>
              {activeJobId ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="text-xs text-muted hover:text-text"
                    onClick={onCancel}
                  >
                    cancel
                  </button>
                  <button
                    type="button"
                    className="text-xs text-muted hover:text-text"
                    onClick={resetJob}
                  >
                    clear
                  </button>
                </div>
              ) : null}
            </div>
            <JobTimeline />
            {lifecycle.kind === "failed" ? (
              <div className="mt-4 rounded-lg border border-error/40 bg-error/10 p-3 text-sm">
                <div className="font-medium text-error">
                  {lifecycle.error.code}
                </div>
                <div className="text-muted">{lifecycle.error.message}</div>
              </div>
            ) : null}
          </div>
        </section>

        <section className="space-y-3 min-w-0">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider">
              Preview
            </h2>
            {lifecycle.kind === "succeeded" ? (
              <button
                type="button"
                className="text-xs rounded-md bg-accent/15 border border-accent/40 px-3 py-1 hover:bg-accent/25"
                onClick={() => void onShowExport()}
              >
                show exports folder
              </button>
            ) : null}
          </div>
          <ModelViewer jobId={activeJobId} glbRelPath={glbRelPath} />
        </section>
      </main>
    </div>
  );
}
