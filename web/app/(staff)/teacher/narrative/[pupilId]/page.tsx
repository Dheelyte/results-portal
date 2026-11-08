"use client";

/**
 * One pupil's narrative (§8.2).
 *
 * The page resolves which term and which pupil; `NarrativeForm` owns the
 * writing. Moving to the next pupil is a route change, so the browser's back
 * button walks back through the class the way a teacher expects.
 */

import { useParams, useRouter } from "next/navigation";

import { NarrativeForm } from "@/components/narrative-form";
import { Avatar, Notice, PageHeader, SkeletonPanel } from "@/components/ui";
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

  if (!api || workload.loading || (termId && page.loading)) {
    return (
      <>
        <PageHeader
          breadcrumbs={[{ label: "My sheets", href: "/teacher" }]}
          back={{ href: "/teacher", label: "My sheets" }}
          title="Written assessment"
        />
        <SkeletonPanel rows={10} label="Loading the assessment…" />
      </>
    );
  }
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (page.error) return <Notice>{page.error}</Notice>;
  if (!page.data || !termId) return null;

  const term = workload.data?.term;
  const name = pupilName(page.data);
  const classHref = `/teacher/class/${page.data.class_id}/narrative`;

  return (
    <>
      <PageHeader
        breadcrumbs={[
          { label: "My sheets", href: "/teacher" },
          { label: page.data.class_name, href: classHref },
          { label: name },
        ]}
        back={{ href: classHref, label: page.data.class_name }}
        title={
          <span className="flex items-center gap-2.5">
            <Avatar name={name} />
            {name}
          </span>
        }
        description={`${page.data.admission_number}${
          term ? ` · ${TERM_LABELS[term.number] ?? term.number}, ${term.academic_session_name}` : ""
        }`}
      />

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
