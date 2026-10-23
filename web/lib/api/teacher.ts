/**
 * The teacher surface of ARCHITECTURE.md §7, as typed functions.
 *
 * Types are the generated ones throughout; this file adds no shapes of its
 * own (CLAUDE.md, Conventions).
 */

import { request, type Schemas } from "./client";

export type Workload = Schemas["WorkloadRead"];
export type Assignment = Schemas["AssignmentRead"];
export type TermSummary = Schemas["TermSummary"];
export type PeriodSummary = Schemas["PeriodSummary"];
export type Sheet = Schemas["SheetRead"];
export type SheetRow = Schemas["EntryRead"];
export type Maxima = Schemas["MaximaRead"];
export type ScoreColumn = keyof Omit<Schemas["EntryRow"], "pupil_id">;
export type EntryRow = Schemas["EntryRow"];
export type TermHalf = PeriodSummary["half"];

export function teacherApi(token: string) {
  return {
    /** The current term by default — §5.2 gives the calendar to the admin. */
    workload: (termId?: string, signal?: AbortSignal) =>
      request<Workload>("/my/assignments", { token, signal, query: { term_id: termId } }),

    sheet: (classSubjectId: string, assessmentPeriodId: string, signal?: AbortSignal) =>
      request<Sheet>(`/class-subjects/${classSubjectId}/entries`, {
        token,
        signal,
        query: { assessment_period_id: assessmentPeriodId },
      }),

    /** The main write path. Applied all or none; per-row errors come back. */
    saveEntries: (classSubjectId: string, assessmentPeriodId: string, rows: EntryRow[]) =>
      request<Sheet>(`/class-subjects/${classSubjectId}/entries`, {
        method: "PUT",
        token,
        body: { assessment_period_id: assessmentPeriodId, rows },
      }),
  };
}

export type TeacherApi = ReturnType<typeof teacherApi>;
