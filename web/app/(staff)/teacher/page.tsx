"use client";

/**
 * A teacher's own list of sheets (§7 `GET /my/assignments`).
 *
 * The first screen after signing in. It exists so a teacher with eight
 * offerings does not have to open each one to find the one they have not
 * finished — the counts come from the same request.
 */

import { BookOpen, ChevronRight, UsersRound } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import {
  Badge,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
  SkeletonCards,
  SkeletonPanel,
} from "@/components/ui";
import { useTeacherApi } from "@/lib/api/use-teacher";
import { HALF_LABELS, TERM_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const STATE_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  submitted: "Submitted for review",
  returned: "Returned for correction",
  approved: "Approved",
};

const STATE_TONES: Record<string, "neutral" | "good" | "warn" | "bad"> = {
  not_started: "neutral",
  in_progress: "neutral",
  submitted: "warn",
  returned: "bad",
  approved: "good",
};

export default function TeacherHomePage() {
  const api = useTeacherApi();

  const workload = useResource(
    (signal) => api!.workload(undefined, signal),
    [api],
    { enabled: Boolean(api) },
  );

  const periods = useMemo(() => workload.data?.periods ?? [], [workload.data]);

  if (!api || workload.loading) {
    return (
      <>
        <div className="flex flex-col gap-2">
          <SkeletonPanel rows={1} label="Loading your classes…" />
        </div>
        <SkeletonCards count={4} />
      </>
    );
  }
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (!workload.data) return null;

  const { term, assignments } = workload.data;
  const myClasses = workload.data.class_teacher_of ?? [];
  const count = assignments?.length ?? 0;

  return (
    <>
      <PageHeader
        title={`${TERM_LABELS[term.number] ?? term.number}, ${term.academic_session_name}`}
        description={`${count} subject${count === 1 ? "" : "s"} to enter. Everything is saved as you type.`}
      />

      {myClasses.length > 0 ? (
        <Panel
          title={myClasses.length === 1 ? "My class" : "My classes"}
          icon={UsersRound}
          description="The written assessment, attendance, height and weight, and your comment"
        >
          <ul className="grid gap-3 sm:grid-cols-2">
            {myClasses.map((klass) => (
              <li key={klass.class_id}>
                <Link
                  href={`/teacher/class/${klass.class_id}`}
                  className="flex items-center gap-3 rounded-lg border border-[var(--border)] px-3 py-2.5 text-sm transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                >
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {klass.class_name}
                  </span>
                  <ChevronRight aria-hidden className="size-4 shrink-0 text-[var(--muted)]" />
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {periods.length === 0 ? (
        <Notice tone="warning">
          This term has no assessment periods set up yet, so there is no sheet to open. Ask the
          administrator to add them.
        </Notice>
      ) : null}

      {count === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="You have no subjects assigned for this term"
          description="If that looks wrong, the administrator assigns teachers to classes and subjects."
        />
      ) : null}

      {(assignments ?? []).map((assignment) => (
        <Panel
          key={assignment.class_subject_id}
          title={`${assignment.class_name} — ${assignment.subject_name}`}
          icon={BookOpen}
          description={`${assignment.pupil_count} pupil${
            assignment.pupil_count === 1 ? "" : "s"
          } on the roll`}
          actions={
            <Badge tone={STATE_TONES[assignment.state] ?? "neutral"}>
              {STATE_LABELS[assignment.state] ?? assignment.state}
            </Badge>
          }
        >
          <ul className="grid gap-3 sm:grid-cols-2">
            {periods.map((period) => {
              const entered = assignment.entered_count?.[period.half] ?? 0;
              const full = entered >= assignment.pupil_count && assignment.pupil_count > 0;
              return (
                <li key={period.id}>
                  <Link
                    href={`/teacher/${assignment.class_subject_id}?period=${period.id}`}
                    className="flex items-center gap-3 rounded-lg border border-[var(--border)] px-3 py-2.5 transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {HALF_LABELS[period.half]}
                      </span>
                      <span className="block text-xs text-[var(--muted)]">
                        {entered} of {assignment.pupil_count} entered
                      </span>
                    </span>
                    {full ? <Badge tone="good">Complete</Badge> : null}
                    <ChevronRight aria-hidden className="size-4 shrink-0 text-[var(--muted)]" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </Panel>
      ))}
    </>
  );
}
