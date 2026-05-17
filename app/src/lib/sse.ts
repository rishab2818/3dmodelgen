/**
 * SSE subscription helper. Built directly on the platform `EventSource` for simplicity.
 * Handles automatic reconnect with backoff; replays through the server's `snapshot` event
 * after reconnects so we never miss state.
 */
import { useEffect, useRef } from "react";
import { backendUrl } from "./api";

export type SseHandler = (event: string, data: unknown) => void;

export function useJobEvents(jobId: string | null, handler: SseHandler): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let backoffMs = 500;
    let es: EventSource | null = null;

    const connect = () => {
      if (cancelled) return;
      es = new EventSource(`${backendUrl()}/jobs/${jobId}/events`);
      const fire = (name: string) => (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as unknown;
          handlerRef.current(name, data);
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn("sse parse error", name, err);
        }
      };
      for (const evt of [
        "snapshot",
        "stage_update",
        "iteration_complete",
        "job_complete",
        "job_failed",
        "job_paused",
        "job_resumed",
        "budget_update",
        "remote_offline",
        "remote_online",
        "heartbeat",
      ]) {
        es.addEventListener(evt, fire(evt));
      }
      es.onopen = () => {
        backoffMs = 500;
      };
      es.onerror = () => {
        es?.close();
        es = null;
        if (cancelled) return;
        const delay = backoffMs;
        backoffMs = Math.min(backoffMs * 2, 30_000);
        setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [jobId]);
}
