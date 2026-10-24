"use client";

/**
 * A teacher's own list of sheets (§7 `GET /my/assignments`).
 *
 * The first screen after signing in. It exists so a teacher with eight
 * offerings does not have to open each one to find the one they have not
 * finished — the counts come from the same request.
 */

import Link from "next/link";
import { useMemo } from "react";

import { Badge, Notice, Panel, Spinner } from "@/components/ui";
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

  if (workload.loading) return <Spinner label="Loading your classes…" />;
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (!workload.data) return null;

  const { term, assignments } = workload.data;
  const myClasses = workload.data.class_teacher_of ?? [];

  return (
    <>
      <div>
        <h1 className="text-lg font-semibold">
          {TERM_LABELS[term.number] ?? term.number}, {term.academic_session_name}
        </h1>
        <p className="text-sm text-[var(--muted)]">
          {assignments?.length ?? 0} subject{assignments?.length === 1 ? "" : "s"} to enter.
          Everything is saved as you type.
        </p>
      </div>

      {myClasses.length > 0 ? (
        <Panel
          title="My classes"
          description="The written assessment, attendance, height and weight, and your comment"
        >
          <div className="flex flex-wrap gap-2">
            {myClasses.map((klass) => (
              <Link
                key={klass.class_id}
                href={`/teacher/class/${klass.class_id}`}
                className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-raised)]"
              >
                {klass.class_name}
              </Link>
            ))}
          </div>
        </Panel>
      ) : null}

      {periods.length === 0 ? (
        <Notice tone="warning">
          This term has no assessment periods set up yet, so there is no sheet to open. Ask the
          administrator to add them.
        </Notice>
      ) : null}

      {(assignments?.length ?? 0) === 0 ? (
        <Notice tone="info">
          You have no subjects assigned for this term. If that looks wrong, the administrator
          assigns teachers to classes and subjects.
        </Notice>
      ) : null}

      {(assignments ?? []).map((assignment) => (
        <Panel
          key={assignment.class_subject_id}
          title={`${assignment.class_name} — ${assignment.subject_name}`}
          description={`${assignment.pupil_count} pupil${
            assignment.pupil_count === 1 ? "" : "s"
          } on the roll`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone={STATE_TONES[assignment.state] ?? "neutral"}>
              {STATE_LABELS[assignment.state] ?? assignment.state}
            </Badge>

            {periods.map((period) => {
              const entered = assignment.entered_count?.[period.half] ?? 0;
              return (
                <Link
                  key={period.id}
                  href={`/teacher/${assignment.class_subject_id}?period=${period.id}`}
                  className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-raised)]"
                >
                  <span className="block font-medium">{HALF_LABELS[period.half]}</span>
                  <span className="block text-xs text-[var(--muted)]">
                    {entered} of {assignment.pupil_count} entered
                  </span>
                </Link>
              );
            })}
          </div>
        </Panel>
      ))}
    </>
  );
}
