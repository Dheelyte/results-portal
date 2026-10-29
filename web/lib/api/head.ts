/**
 * The head teacher's review surface (§7's review block, §8.4).
 *
 * Separate from `teacher.ts` because the two roles never share a screen: §5.2
 * gives review to the head teacher alone, and a teacher calling any of these
 * gets a 403.
 */

import { request, type Schemas } from "./client";

export type ReviewQueueEntry = Schemas["QueueEntryRead"];
export type ClassReview = Schemas["ClassReviewRead"];
export type Card = Schemas["CardRead"];
export type CardSubjectRow = Schemas["SubjectRowRead"];
export type CardHalf = Schemas["CardHalf"];
export type Approval = Schemas["ApprovalRead"];
export type RemarkRow = Schemas["RemarkSaveRow"];

export function headApi(token: string) {
  return {
    /** Omit the term and the server uses the current one (D51). */
    queue: (termId?: string, signal?: AbortSignal) =>
      request<ReviewQueueEntry[]>("/review/queue", {
        token,
        signal,
        query: { term_id: termId },
      }),

    review: (classId: string, termId: string, signal?: AbortSignal) =>
      request<ClassReview>(`/classes/${classId}/review`, {
        token,
        signal,
        query: { term_id: termId },
      }),

    saveRemarks: (classId: string, termId: string, rows: RemarkRow[]) =>
      request<ClassReview>(`/classes/${classId}/remarks`, {
        method: "PUT",
        token,
        query: { term_id: termId },
        body: { rows },
      }),

    /** Irreversible: freezes every grade against the active scale (§4.5). */
    approve: (classId: string, termId: string) =>
      request<Approval>(`/classes/${classId}/approve`, {
        method: "POST",
        token,
        query: { term_id: termId },
      }),

    returnClass: (classId: string, termId: string, note: string) =>
      request<ClassReview>(`/classes/${classId}/return`, {
        method: "POST",
        token,
        query: { term_id: termId },
        body: { note },
      }),
  };
}

export type HeadApi = ReturnType<typeof headApi>;
