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

export type ClassNarrative = Schemas["ClassNarrativeRead"];
export type PupilNarrative = Schemas["PupilNarrativeRead"];
export type Passage = Schemas["PassageRead"];
export type PassageSave = Schemas["PassageSave"];
export type NarrativeProgress = Schemas["NarrativeProgressRead"];
export type ClassAttendance = Schemas["ClassAttendanceRead"];
export type AttendanceRow = Schemas["AttendanceRead"];
export type ClassGrowth = Schemas["ClassGrowthRead"];
export type GrowthRow = Schemas["GrowthRead"];
export type ClassComments = Schemas["ClassCommentsRead"];
export type CommentRow = Schemas["PupilCommentRead"];
export type Phrase = Schemas["PhraseRead"];
export type ClassSummary = Schemas["ClassSummary"];

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

    /* --- The narrative (§8.2) ---------------------------------------- */

    classNarrative: (classId: string, termId: string, signal?: AbortSignal) =>
      request<ClassNarrative>(`/classes/${classId}/narrative`, {
        token,
        signal,
        query: { term_id: termId },
      }),

    pupilNarrative: (pupilId: string, termId: string, signal?: AbortSignal) =>
      request<PupilNarrative>(`/pupils/${pupilId}/narrative`, {
        token,
        signal,
        query: { term_id: termId },
      }),

    savePupilNarrative: (pupilId: string, termId: string, passages: PassageSave[]) =>
      request<PupilNarrative>(`/pupils/${pupilId}/narrative`, {
        method: "PUT",
        token,
        query: { term_id: termId },
        body: { passages },
      }),

    /** The phrase bank, active entries only, optionally for one section. */
    phrases: (scope?: string, signal?: AbortSignal) =>
      request<Phrase[]>("/phrases", { token, signal, query: { scope } }),

    /* --- Attendance, growth and the comment (§4.7, §1.6) ------------- */

    attendance: (classId: string, termId: string, signal?: AbortSignal) =>
      request<ClassAttendance>(`/classes/${classId}/attendance`, {
        token,
        signal,
        query: { term_id: termId },
      }),

    saveAttendance: (
      classId: string,
      termId: string,
      rows: Schemas["AttendanceSaveRow"][],
    ) =>
      request<ClassAttendance>(`/classes/${classId}/attendance`, {
        method: "PUT",
        token,
        query: { term_id: termId },
        body: { rows },
      }),

    growth: (classId: string, termId: string, signal?: AbortSignal) =>
      request<ClassGrowth>(`/classes/${classId}/growth`, {
        token,
        signal,
        query: { term_id: termId },
      }),

    saveGrowth: (classId: string, termId: string, rows: Schemas["GrowthSaveRow"][]) =>
      request<ClassGrowth>(`/classes/${classId}/growth`, {
        method: "PUT",
        token,
        query: { term_id: termId },
        body: { rows },
      }),

    comments: (classId: string, termId: string, signal?: AbortSignal) =>
      request<ClassComments>(`/classes/${classId}/comments`, {
        token,
        signal,
        query: { term_id: termId },
      }),

    saveComments: (classId: string, termId: string, rows: Schemas["CommentSaveRow"][]) =>
      request<ClassComments>(`/classes/${classId}/comments`, {
        method: "PUT",
        token,
        query: { term_id: termId },
        body: { rows },
      }),
  };
}

export type TeacherApi = ReturnType<typeof teacherApi>;
