"use client";

/**
 * One sheet, for one class-subject and one half of the term (§8.1).
 *
 * The page loads the sheet and chooses which half; the grid itself is
 * `components/score-grid.tsx`. Keeping them apart means the half switcher
 * cannot accidentally become part of the grid's state, and reloading after a
 * save is one call.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ScoreGrid } from "@/components/score-grid";
import { Notice, Spinner } from "@/components/ui";
import { useTeacherApi } from "@/lib/api/use-teacher";
import { HALF_LABELS, TERM_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";

export default function SheetPage() {
  const api = useTeacherApi();
  const router = useRouter();
  const params = useParams<{ classSubjectId: string }>();
  const search = useSearchParams();

  const classSubjectId = params.classSubjectId;
  const requestedPeriod = search.get("period");

  // The term and its periods come from the teacher's own endpoint: §5.2 gives
  // the calendar to the admin alone (D51).
  const workload = useResource(
    (signal) => api!.workload(undefined, signal),
    [api],
    { enabled: Boolean(api) },
  );

  const periods = workload.data?.periods ?? [];
  const periodId = requestedPeriod ?? periods[0]?.id ?? null;

  const sheet = useResource(
    (signal) => api!.sheet(classSubjectId, periodId!, signal),
    [api, classSubjectId, periodId],
    { enabled: Boolean(api) && Boolean(periodId) },
  );

  if (workload.loading || (periodId && sheet.loading)) {
    return <Spinner label="Loading the sheet…" />;
  }
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (!periodId) {
    return (
      <Notice tone="warning">
        This term has no assessment periods set up yet, so there is no sheet to open.
      </Notice>
    );
  }
  if (sheet.error) return <Notice>{sheet.error}</Notice>;
  if (!sheet.data || !api) return null;

  const term = workload.data?.term;

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href="/teacher" className="text-sm text-[var(--muted)] hover:underline">
            ← My classes
          </Link>
          <h1 className="text-lg font-semibold">
            {sheet.data.class_name} — {sheet.data.subject_name}
          </h1>
          <p className="text-sm text-[var(--muted)]">
            {HALF_LABELS[sheet.data.half]}
            {term ? `, ${TERM_LABELS[term.number] ?? term.number} ${term.academic_session_name}` : ""}
          </p>
        </div>

        <nav aria-label="Which half" className="flex gap-1 text-sm">
          {periods.map((period) => {
            const active = period.id === periodId;
            return (
              <button
                key={period.id}
                type="button"
                aria-current={active ? "page" : undefined}
                onClick={() =>
                  router.replace(`/teacher/${classSubjectId}?period=${period.id}`)
                }
                className={`rounded-md px-3 py-1.5 ${
                  active
                    ? "bg-[var(--surface-raised)] font-medium"
                    : "text-[var(--muted)] hover:text-[var(--foreground)]"
                }`}
              >
                {HALF_LABELS[period.half]}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Keyed on the sheet, so switching halves rebuilds the grid's state
          rather than carrying one half's dirty cells into the other. */}
      <ScoreGrid key={`${classSubjectId}:${periodId}`} sheet={sheet.data} api={api} />
    </>
  );
}
