/**
 * Wire-format zod schemas mirroring backend Pydantic models.
 *
 * For M1 these are hand-maintained. M2 introduces a generator
 * (`scripts/gen_ts_schemas.py`) that emits these from Pydantic so they can't drift.
 */
import { z } from "zod";

export const JobStateSchema = z.enum([
  "queued",
  "running",
  "paused_by_user",
  "paused_remote_offline",
  "paused_crashed",
  "paused_budget",
  "succeeded",
  "failed",
  "cancelled",
]);
export type JobState = z.infer<typeof JobStateSchema>;

export const StageStatusSchema = z.enum([
  "pending",
  "running",
  "complete",
  "failed",
  "cache_hit",
]);
export type StageStatus = z.infer<typeof StageStatusSchema>;

export const BudgetSummarySchema = z.object({
  total_runtime_ms: z.number().int().nonnegative().default(0),
  call_count: z.number().int().nonnegative().default(0),
  cached_call_count: z.number().int().nonnegative().default(0),
  cache_hit_rate: z.number().min(0).max(1).default(0),
  by_provider: z.record(z.string(), z.number().int().nonnegative()).default({}),
  cap_seconds: z.number().int().nullable().default(null),
  cap_remaining_seconds: z.number().int().nullable().default(null),
});
export type BudgetSummary = z.infer<typeof BudgetSummarySchema>;

export const JobSnapshotSchema = z.object({
  id: z.string(),
  label: z.string().nullable(),
  state: JobStateSchema,
  paused_reason: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  current_iteration: z.number().int().nonnegative(),
  best_iteration: z.number().int().nullable(),
  inputs: z.unknown(),
  budget: BudgetSummarySchema.optional().default({} as BudgetSummary),
});
export type JobSnapshot = z.infer<typeof JobSnapshotSchema>;

export const CreateJobResponseSchema = z.object({
  job_id: z.string(),
});

export const StageUpdateSchema = z.object({
  iteration: z.number().int().nonnegative(),
  stage: z.string(),
  status: StageStatusSchema,
  progress: z.number().min(0).max(1),
  message: z.string().default(""),
  artifacts: z.array(z.string()).default([]),
  elapsed_ms: z.number().int().nonnegative().default(0),
});
export type StageUpdate = z.infer<typeof StageUpdateSchema>;

export const IterationCompleteSchema = z.object({
  iteration: z.number().int().nonnegative(),
  score: z.record(z.string(), z.unknown()).nullable(),
  refinement_action: z.string().nullable(),
});
export type IterationComplete = z.infer<typeof IterationCompleteSchema>;

export const JobCompleteSchema = z.object({
  state: z.literal("succeeded"),
  exports: z.record(z.string(), z.string()),
});
export type JobCompleteEvent = z.infer<typeof JobCompleteSchema>;

export const JobFailedSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
  }),
});
export type JobFailedEvent = z.infer<typeof JobFailedSchema>;

export const BudgetUpdateSchema = z.object({
  stage: z.string(),
  cached: z.boolean(),
  runtime_ms: z.number().int().nonnegative(),
  provider: z.string(),
  job_total_runtime_ms: z.number().int().nonnegative(),
});
export type BudgetUpdateEvent = z.infer<typeof BudgetUpdateSchema>;

export const HealthSchema = z.object({
  status: z.string(),
  api_version: z.string(),
  gpu_backend: z.string(),
  gpu_status: z.record(z.string(), z.unknown()).optional(),
});
export type Health = z.infer<typeof HealthSchema>;
