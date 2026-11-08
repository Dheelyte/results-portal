"use client";

/**
 * What one class is taught, and by whom (ARCHITECTURE.md §4.3, §5.2, D15).
 *
 * The two assignments made here decide who can do what for the rest of the
 * term. Only the assigned subject teacher may enter scores for a
 * class-subject; the class teacher owns the narrative, attendance, growth,
 * the class teacher's comment and the submission gate. Being class teacher of
 * a class does not grant score entry for its subjects, which is why they are
 * set separately.
 *
 * Its own route since the redesign (D104): a term's worth of authorization
 * decided on a panel with no address was a page you could not send anyone
 * to, could not reload, and could not leave with the back button.
 */

import { ClipboardList, GraduationCap, UserCog, Users } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import {
  Badge,
  Button,
  Cell,
  Field,
  Notice,
  PageHeader,
  Panel,
  Row,
  Select,
  SkeletonPanel,
  SkeletonTable,
  Table,
} from "@/components/ui";
import { useAdminApi } from "@/lib/api/use-admin";
import { useAction, useResource } from "@/lib/use-async";

export default function ClassDetailPage() {
  const api = useAdminApi();
  const { classId } = useParams<{ classId: string }>();

  const classes = useResource(() => api!.classes(true), [api], { enabled: Boolean(api) });
  const subjects = useResource(() => api!.subjects(), [api], { enabled: Boolean(api) });
  const offerings = useResource(() => api!.classSubjects(classId), [api, classId], {
    enabled: Boolean(api),
  });
  const assignments = useResource(
    () => api!.narrativeAssignments(classId),
    [api, classId],
    { enabled: Boolean(api) },
  );
  const sections = useResource(() => api!.narrativeSections(), [api], {
    enabled: Boolean(api),
  });
  const teachers = useResource(() => api!.users("teacher"), [api], { enabled: Boolean(api) });

  const action = useAction(() => {
    offerings.reload();
    assignments.reload();
  });

  const [chosen, setChosen] = useState<Set<string> | null>(null);

  const schoolClass = (classes.data ?? []).find((item) => item.id === classId) ?? null;
  const activeTeachers = (teachers.data ?? []).filter((teacher) => teacher.is_active);

  const offered = new Set((offerings.data ?? []).map((row) => row.subject_id));
  const selection = chosen ?? offered;
  const scored = (subjects.data ?? []).filter((subject) => !subject.is_group);
  const headings = (subjects.data ?? []).filter((subject) => subject.is_group);

  const crumbs = [
    { label: "Classes", href: "/admin/classes" },
    { label: schoolClass?.name ?? "Class" },
  ];

  if (!api || classes.loading) {
    return (
      <>
        <PageHeader
          breadcrumbs={crumbs}
          back={{ href: "/admin/classes", label: "Classes" }}
          title="Class"
        />
        <SkeletonPanel rows={3} label="Loading the class…" />
        <SkeletonPanel rows={6} />
      </>
    );
  }

  if (classes.error) {
    return (
      <>
        <PageHeader
          breadcrumbs={crumbs}
          back={{ href: "/admin/classes", label: "Classes" }}
          title="Class"
        />
        <Notice>{classes.error}</Notice>
      </>
    );
  }

  if (!schoolClass) {
    return (
      <>
        <PageHeader
          breadcrumbs={crumbs}
          back={{ href: "/admin/classes", label: "Classes" }}
          title="Class"
        />
        <Notice tone="info">
          That class no longer exists. Pick one from the list of classes.
        </Notice>
      </>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumbs={crumbs}
        back={{ href: "/admin/classes", label: "Classes" }}
        title={schoolClass.name}
        description="Who teaches what, and who writes the card."
        badge={schoolClass.is_active ? null : <Badge tone="bad">Inactive</Badge>}
      />

      <div className="flex flex-col gap-2">
        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>

      <Panel
        title="Class teacher"
        icon={UserCog}
        description="Writes the narrative sections, records attendance and growth, writes the class teacher's comment, and submits the class for review."
      >
        {teachers.loading ? (
          <SkeletonTable rows={1} columns={2} label="Loading the teachers…" />
        ) : (
          <div className="max-w-sm">
            <Field label="Teacher">
              <Select
                defaultValue=""
                disabled={action.busy}
                onChange={(event) => {
                  const teacherId = event.target.value;
                  if (!teacherId) return;
                  void action.run(
                    () => api.setClassTeacher(classId, teacherId),
                    "Class teacher set.",
                  );
                }}
              >
                <option value="">Choose a teacher…</option>
                {activeTeachers.map((teacher) => (
                  <option key={teacher.id} value={teacher.id}>
                    {teacher.full_name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        )}
      </Panel>

      <Panel
        title="Subjects taught"
        icon={GraduationCap}
        description={
          <>
            Group headings are not listed: they print on the card and carry no scores (R7).
            {headings.length
              ? ` ${headings.map((heading) => heading.name).join(", ")} ${
                  headings.length === 1 ? "is a heading" : "are headings"
                }.`
              : ""}
          </>
        }
      >
        {subjects.loading || offerings.loading ? (
          <SkeletonTable rows={5} columns={2} label="Loading the subjects…" />
        ) : (
          <>
            {subjects.error ? <Notice>{subjects.error}</Notice> : null}

            <ul className="grid gap-2 sm:grid-cols-2">
              {scored.map((subject) => (
                <li key={subject.id}>
                  <label className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm transition hover:bg-[var(--surface-raised)]">
                    <input
                      type="checkbox"
                      checked={selection.has(subject.id)}
                      onChange={(event) => {
                        const next = new Set(selection);
                        if (event.target.checked) next.add(subject.id);
                        else next.delete(subject.id);
                        setChosen(next);
                      }}
                    />
                    <span className="flex-1">{subject.name}</span>
                    {subject.is_specialist ? <Badge tone="warn">Specialist</Badge> : null}
                  </label>
                </li>
              ))}
            </ul>

            <Button
              className="mt-4"
              loading={action.busy}
              disabled={chosen === null}
              onClick={async () => {
                const ordered = scored
                  .filter((subject) => selection.has(subject.id))
                  .map((subject) => subject.id);
                const saved = await action.run(
                  () => api.setClassSubjects(classId, ordered),
                  "Subject list saved.",
                );
                if (saved) setChosen(null);
              }}
            >
              Save subject list
            </Button>
          </>
        )}
      </Panel>

      <Panel title="Who enters the scores" icon={Users}>
        {offerings.loading ? (
          <SkeletonTable rows={5} columns={2} label="Loading the assignments…" />
        ) : (
          <Table head={["Subject", "Teacher"]} empty="Save a subject list first.">
            {(offerings.data ?? []).map((row) => {
              const subject = (subjects.data ?? []).find((item) => item.id === row.subject_id);
              return (
                <Row key={row.id}>
                  <Cell className="font-medium">{subject?.name ?? "—"}</Cell>
                  <Cell>
                    <Select
                      aria-label={`Teacher for ${subject?.name ?? "subject"}`}
                      defaultValue=""
                      disabled={action.busy}
                      onChange={(event) => {
                        const teacherId = event.target.value;
                        if (!teacherId) return;
                        void action.run(
                          () => api.setSubjectTeacher(row.id, teacherId),
                          `${subject?.name ?? "Subject"} assigned.`,
                        );
                      }}
                    >
                      <option value="">Choose a teacher…</option>
                      {activeTeachers.map((teacher) => (
                        <option key={teacher.id} value={teacher.id}>
                          {teacher.full_name}
                        </option>
                      ))}
                    </Select>
                  </Cell>
                </Row>
              );
            })}
          </Table>
        )}
      </Panel>

      <Panel
        title="Who writes each narrative section"
        icon={ClipboardList}
        description="Leave a section unassigned and the class teacher writes it — that is the normal case, so most of this list stays empty. Assign one only where a specialist writes their own area."
      >
        {sections.loading || assignments.loading ? (
          <SkeletonTable rows={6} columns={2} label="Loading the sections…" />
        ) : (
          <Table head={["Section", "Written by"]} empty="No narrative sections yet.">
            {(sections.data ?? [])
              .filter((section) => section.is_active)
              .map((section) => {
                const assigned = (assignments.data ?? []).find(
                  (row) => row.section_id === section.id,
                );
                return (
                  <Row key={section.id}>
                    <Cell>
                      {section.group_label ? (
                        <span className="text-[var(--muted)]">{section.group_label}: </span>
                      ) : null}
                      <span className="font-medium">{section.label}</span>
                    </Cell>
                    <Cell>
                      <Select
                        aria-label={`Who writes ${section.label}`}
                        value={assigned?.teacher_user_id ?? ""}
                        disabled={action.busy}
                        onChange={(event) =>
                          void action.run(
                            () =>
                              api.setNarrativeAssignments(classId, {
                                assignments: [
                                  {
                                    section_id: section.id,
                                    teacher_user_id: event.target.value || null,
                                  },
                                ],
                              }),
                            "Saved.",
                          )
                        }
                      >
                        <option value="">The class teacher</option>
                        {activeTeachers.map((teacher) => (
                          <option key={teacher.id} value={teacher.id}>
                            {teacher.full_name}
                          </option>
                        ))}
                      </Select>
                    </Cell>
                  </Row>
                );
              })}
          </Table>
        )}
      </Panel>
    </>
  );
}
