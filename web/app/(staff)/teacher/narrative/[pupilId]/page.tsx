"use client";

/**
 * One pupil's narrative (§8.2).
 *
 * The page resolves which term and which pupil; `NarrativeForm` owns the
 * writing. Moving to the next pupil is a route change, so the browser's back
 * button walks back through the class the way a teacher expects.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { NarrativeForm } from "@/components/narrative-form";
import { Notice, Spinner } from "@/components/ui";
import { useTeacherApi } from "@/lib/api/use-teacher";
import { TERM_LABELS, pupilName } from "@/lib/format";
import { useResource } from "@/lib/use-async";

export default function PupilNarrativePage() {
  const api = useTeacherApi();
  const router = useRouter();
  const { pupilId } = useParams<{ pupilId: string }>();

  const workload = useResource((signal) => api!.workload(undefined, signal), [api], {
    enabled: Boolean(api),
  });
  const termId = workload.data?.term.id ?? null;

  const page = useResource(
    (signal) => api!.pupilNarrative(pupilId, termId!, signal),
    [api, pupilId, termId],
    { enabled: Boolean(api) && Boolean(termId) },
  );

  if (workload.loading || (termId && page.loading)) {
    return <Spinner label="Loading the assessment…" />;
  }
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (page.error) return <Notice>{page.error}</Notice>;
  if (!page.data || !api || !termId) return null;

  const term = workload.data?.term;

  return (
    <>
      <div>
        <Link
          href={`/teacher/class/${page.data.class_id}`}
          className="text-sm text-[var(--muted)] hover:underline"
        >
          ← {page.data.class_name}
        </Link>
        <h1 className="text-lg font-semibold">{pupilName(page.data)}</h1>
        <p className="text-sm text-[var(--muted)]">
          {page.data.admission_number}
          {term ? ` · ${TERM_LABELS[term.number] ?? term.number}, ${term.academic_session_name}` : ""}
        </p>
      </div>

      {/* Keyed on the pupil so moving to the next one rebuilds the form's
          state rather than carrying one child's draft into another's page. */}
      <NarrativeForm
        key={pupilId}
        page={page.data}
        api={api}
        termId={termId}
        onMoved={(next) => router.push(`/teacher/narrative/${next}`)}
      />
    </>
  );
}
