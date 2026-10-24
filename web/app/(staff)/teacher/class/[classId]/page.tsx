"use client";

/**
 * The class teacher's own tasks (§8.3, partly).
 *
 * §8.3 describes one page per class: every subject with its state and owner,
 * then the class teacher's own work — narrative, attendance, growth,
 * comments — with **Send to head teacher** disabled until R10 passes and the
 * outstanding items listed beneath it. All of that is here; the Progress tab
 * holds the subjects and the button, the other three hold the work.
 *
 * Tabs rather than separate pages: these are columns of the same roll, and a
 * teacher filling them in moves between them constantly.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ClassProgress } from "@/components/class-progress";
import { ClassAttendance, ClassComments, ClassGrowth } from "@/components/class-records";
import { Badge, Notice, Panel, Spinner } from "@/components/ui";
import { useTeacherApi } from "@/lib/api/use-teacher";
import { TERM_LABELS, pupilName } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const TABS = [
  { key: "progress", label: "Progress" },
  { key: "narrative", label: "Narrative" },
  { key: "attendance", label: "Attendance" },
  { key: "growth", label: "Height & weight" },
  { key: "comments", label: "Class teacher's comment" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ClassPage() {
  const api = useTeacherApi();
  const router = useRouter();
  const { classId } = useParams<{ classId: string }>();
  const search = useSearchParams();
  // Progress first: it is the page that says what is left to do, and §8.3
  // puts the Send button on it.
  const tab = (search.get("tab") ?? "progress") as TabKey;

  const workload = useResource((signal) => api!.workload(undefined, signal), [api], {
    enabled: Boolean(api),
  });
  const termId = workload.data?.term.id ?? null;

  const narrative = useResource(
    (signal) => api!.classNarrative(classId, termId!, signal),
    [api, classId, termId],
    { enabled: Boolean(api) && Boolean(termId) },
  );

  if (workload.loading || (termId && narrative.loading)) {
    return <Spinner label="Loading the class…" />;
  }
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (narrative.error) return <Notice>{narrative.error}</Notice>;
  if (!narrative.data || !api || !termId) return null;

  const term = workload.data?.term;
  const data = narrative.data;

  return (
    <>
      <div>
        <Link href="/teacher" className="text-sm text-[var(--muted)] hover:underline">
          ← My classes
        </Link>
        <h1 className="text-lg font-semibold">{data.class_name}</h1>
        <p className="text-sm text-[var(--muted)]">
          {term ? `${TERM_LABELS[term.number] ?? term.number}, ${term.academic_session_name}` : ""}
          {` · ${data.roll_size} pupil${data.roll_size === 1 ? "" : "s"}`}
        </p>
      </div>

      <nav aria-label="Class records" className="flex flex-wrap gap-1 text-sm">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-current={item.key === tab ? "page" : undefined}
            onClick={() => router.replace(`/teacher/class/${classId}?tab=${item.key}`)}
            className={`rounded-md px-3 py-1.5 ${
              item.key === tab
                ? "bg-[var(--surface-raised)] font-medium"
                : "text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === "progress" ? (
        <ClassProgress api={api} classId={classId} termId={termId} />
      ) : null}

      {tab === "narrative" ? (
        <Panel
          title="Written assessment"
          description={`${data.complete_pupils} of ${data.roll_size} pupils complete — every section written`}
        >
          {(data.pupils ?? []).length === 0 ? (
            <Notice tone="info">No pupils are enrolled in this class for this session.</Notice>
          ) : (
            <ul className="flex flex-col divide-y divide-[var(--border)]">
              {(data.pupils ?? []).map((pupil) => (
                <li
                  key={pupil.pupil_id}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <Link
                    href={`/teacher/narrative/${pupil.pupil_id}`}
                    className="min-w-0 hover:underline"
                  >
                    <span className="block truncate text-sm font-medium">
                      {pupilName(pupil)}
                    </span>
                    <span className="block text-xs text-[var(--muted)]">
                      {pupil.admission_number}
                    </span>
                  </Link>
                  <Badge tone={pupil.is_complete ? "good" : "neutral"}>
                    {pupil.written} of {pupil.total}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      ) : null}

      {tab === "attendance" ? (
        <ClassAttendance api={api} classId={classId} termId={termId} />
      ) : null}
      {tab === "growth" ? <ClassGrowth api={api} classId={classId} termId={termId} /> : null}
      {tab === "comments" ? (
        <ClassComments api={api} classId={classId} termId={termId} />
      ) : null}
    </>
  );
}
