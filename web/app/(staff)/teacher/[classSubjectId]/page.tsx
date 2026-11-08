"use client";

/**
 * One sheet, for one class-subject and one half of the term (§8.1).
 *
 * The page loads the sheet and chooses which half; the grid itself is
 * `components/score-grid.tsx`. Keeping them apart means the half switcher
 * cannot accidentally become part of the grid's state, and reloading after a
 * save is one call.
 */

import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ScoreGrid } from "@/components/score-grid";
import { Notice, PageHeader, Skeleton, SkeletonTable } from "@/components/ui";
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

  const back = { href: "/teacher", label: "My sheets" };

  if (!api || workload.loading || (periodId && sheet.loading)) {
    return (
      <>
        <PageHeader
          breadcrumbs={[{ label: "My sheets", href: "/teacher" }]}
          back={back}
          title="Sheet"
        />
        <div className="flex gap-2" aria-hidden>
          <Skeleton className="h-8 w-32 rounded-lg" />
          <Skeleton className="h-8 w-32 rounded-lg" />
        </div>
        <SkeletonTable rows={10} columns={8} label="Loading the sheet…" />
      </>
    );
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
  if (!sheet.data) return null;

  const term = workload.data?.term;

  return (
    <>
      <PageHeader
        breadcrumbs={[
          { label: "My sheets", href: "/teacher" },
          { label: sheet.data.class_name },
          { label: sheet.data.subject_name },
        ]}
        back={back}
        title={`${sheet.data.class_name} — ${sheet.data.subject_name}`}
        description={`${HALF_LABELS[sheet.data.half]}${
          term ? `, ${TERM_LABELS[term.number] ?? term.number} ${term.academic_session_name}` : ""
        }`}
        actions={
          <nav
            aria-label="Which half"
            className="flex overflow-hidden rounded-lg border border-[var(--border)] text-sm"
          >
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
                  className={`px-3 py-2 transition ${
                    active
                      ? "bg-[var(--brand)] font-medium text-[var(--brand-contrast)]"
                      : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"
                  }`}
                >
                  {HALF_LABELS[period.half]}
                </button>
              );
            })}
          </nav>
        }
      />

      {/* Keyed on the sheet, so switching halves rebuilds the grid's state
          rather than carrying one half's dirty cells into the other. */}
      <ScoreGrid key={`${classSubjectId}:${periodId}`} sheet={sheet.data} api={api} />
    </>
  );
}
