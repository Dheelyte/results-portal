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

import { ClipboardList, GraduationCap, UserCog } from "lucide-react";
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
  const classTeacher = useResource(() => api!.classTeacher(classId), [api, classId], {
    enabled: Boolean(api),
  });

  const action = useAction(() => {
    offerings.reload();
    assignments.reload();
    classTeacher.reload();
  });

  const [chosen, setChosen] = useState<Set<string> | null>(null);

  const schoolClass = (classes.data ?? []).find((item) => item.id === classId) ?? null;
  const activeTeachers = (teachers.data ?? []).filter((teacher) => teacher.is_active);

  const offeringBySubject = new Map((offerings.data ?? []).map((row) => [row.subject_id, row]));
  const offered = new Set(offeringBySubject.keys());

  /**
   * Active teachers, plus the assigned one if their account has since been
   * deactivated — otherwise the dropdown would silently show someone else.
   */
  const teacherOptions = (assignedId: string | null | undefined) => {
    const assigned = (teachers.data ?? []).find((teacher) => teacher.id === assignedId);
    const listed = assigned && !assigned.is_active ? [...activeTeachers, assigned] : activeTeachers;
    return listed.map((teacher) => (
      <option key={teacher.id} value={teacher.id}>
        {teacher.full_name}
        {teacher.is_active ? "" : " (deactivated)"}
      </option>
    ));
  };
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
        {teachers.loading || classTeacher.loading ? (
          <SkeletonTable rows={1} columns={2} label="Loading the teachers…" />
        ) : (
          <div className="max-w-sm">
            {classTeacher.error ? <Notice>{classTeacher.error}</Notice> : null}
            <Field label="Teacher">
              <Select
                value={classTeacher.data?.teacher_user_id ?? ""}
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
                {/* Only until someone is set: a class teacher is replaced, never cleared. */}
                {classTeacher.data ? null : <option value="">Choose a teacher…</option>}
                {teacherOptions(classTeacher.data?.teacher_user_id)}
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
            Tick what this class is taught, then choose who teaches each subject — only that
            teacher can enter its scores. Group headings are not listed: they print on the card and carry no scores (R7).
            {headings.length
              ? ` ${headings.map((heading) => heading.name).join(", ")} ${
                  headings.length === 1 ? "is a heading" : "are headings"
                }.`
              : ""}
          </>
        }
      >
        {subjects.loading || offerings.loading ? (
          <SkeletonTable rows={6} columns={3} label="Loading the subjects…" />
        ) : (
          <>
            {subjects.error ? <Notice>{subjects.error}</Notice> : null}

            <Table head={["Taught", "Subject", "Teacher"]} empty="No subjects yet.">
              {scored.map((subject) => {
                const offering = offeringBySubject.get(subject.id);
                const checked = selection.has(subject.id);
                return (
                  <Row key={subject.id}>
                    <Cell className="w-16">
                      <input
                        type="checkbox"
                        aria-label={`${subject.name} is taught`}
                        checked={checked}
                        onChange={(event) => {
                          const next = new Set(selection);
                          if (event.target.checked) next.add(subject.id);
                          else next.delete(subject.id);
                          setChosen(next);
                        }}
                      />
                    </Cell>
                    <Cell>
                      <span className="flex items-center gap-2">
                        <span className="font-medium">{subject.name}</span>
                        {subject.is_specialist ? <Badge tone="warn">Specialist</Badge> : null}
                      </span>
                    </Cell>
                    <Cell className="w-72">
                      {offering && checked ? (
                        <Select
                          aria-label={`Teacher for ${subject.name}`}
                          value={offering.teacher_user_id ?? ""}
                          disabled={action.busy}
                          onChange={(event) => {
                            const teacherId = event.target.value;
                            if (!teacherId) return;
                            void action.run(
                              () => api.setSubjectTeacher(offering.id, teacherId),
                              `${subject.name} assigned.`,
                            );
                          }}
                        >
                          {/* Offered only until someone is assigned: the API
                              replaces a teacher but never leaves it empty. */}
                          {offering.teacher_user_id ? null : (
                            <option value="">Choose a teacher…</option>
                          )}
                          {teacherOptions(offering.teacher_user_id)}
                        </Select>
                      ) : (
                        <span className="text-sm text-[var(--muted)]">
                          {checked ? "Save the subject list to choose" : "—"}
                        </span>
                      )}
                    </Cell>
                  </Row>
                );
              })}
            </Table>

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
