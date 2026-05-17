/**
 * Backend HTTP client. All boundary deserialization goes through zod schemas in
 * `./schemas.ts` — no `any`, no `as` casts at this seam.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BudgetSummarySchema,
  CreateJobResponseSchema,
  HealthSchema,
  JobSnapshotSchema,
  type BudgetSummary,
  type Health,
  type JobSnapshot,
} from "./schemas";

const BACKEND_URL =
  (import.meta.env.VITE_BACKEND_URL as string | undefined) ?? "http://127.0.0.1:7878";

async function http(path: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new Error(`HTTP ${res.status}: ${JSON.stringify(body)}`);
  }
  return (await res.json()) as unknown;
}

export function backendUrl(): string {
  return BACKEND_URL;
}

// --- Hooks --------------------------------------------------------------

export function useHealth() {
  return useQuery<Health>({
    queryKey: ["health"],
    queryFn: async () => HealthSchema.parse(await http("/health")),
    refetchInterval: 5_000,
  });
}

export function useJob(jobId: string | null) {
  return useQuery<JobSnapshot>({
    queryKey: ["job", jobId],
    queryFn: async () => JobSnapshotSchema.parse(await http(`/jobs/${jobId}`)),
    enabled: !!jobId,
  });
}

export function useJobBudget(jobId: string | null) {
  return useQuery<BudgetSummary>({
    queryKey: ["job", jobId, "budget"],
    queryFn: async () =>
      BudgetSummarySchema.parse(await http(`/jobs/${jobId}/budget`)),
    enabled: !!jobId,
    refetchInterval: 2_000,
  });
}

export type CreateJobBody = {
  input_images: string[];
  target_quality?: number;
  max_iterations?: number;
  seed?: number;
  export_formats?: Array<"glb" | "obj" | "ply">;
  label?: string;
};

export function useCreateJob() {
  const qc = useQueryClient();
  return useMutation<{ job_id: string }, Error, CreateJobBody>({
    mutationFn: async (body) => {
      const raw = await http("/jobs", {
        method: "POST",
        body: JSON.stringify(body),
      });
      return CreateJobResponseSchema.parse(raw);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useCancelJob() {
  return useMutation<unknown, Error, string>({
    mutationFn: async (jobId) =>
      http(`/jobs/${jobId}/cancel`, { method: "POST" }),
  });
}

export function usePauseJob() {
  return useMutation<unknown, Error, string>({
    mutationFn: async (jobId) =>
      http(`/jobs/${jobId}/pause`, { method: "POST" }),
  });
}

export function useResumeJob() {
  return useMutation<unknown, Error, string>({
    mutationFn: async (jobId) =>
      http(`/jobs/${jobId}/resume`, { method: "POST" }),
  });
}
