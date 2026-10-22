"use client";

/**
 * Classes, houses, and what each class is taught by whom
 * (ARCHITECTURE.md §4.3, §5.2, D15).
 *
 * The two assignments made here decide who can do what for the rest of the
 * term. Only the assigned subject teacher may enter scores for a
 * class-subject; the class teacher owns the narrative, attendance, growth,
 * the class teacher's comment and the submission gate. Being class teacher of
 * a class does not grant score entry for its subjects, which is why they are
 * set separately.
 */

import { useState } from "react";

import {
  Badge,
  Button,
  Cell,
  Field,
  Input,
  Notice,
  Panel,
  Row,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import type { Account, SchoolClass } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { useAction, useResource } from "@/lib/use-async";

export default function ClassesPage() {
  const api = useAdminApi();
  const classes = useResource(() => api!.classes(true), [api], { enabled: Boolean(api) });
  const houses = useResource(() => api!.houses(), [api], { enabled: Boolean(api) });
  const teachers = useResource(() => api!.users("teacher"), [api], { enabled: Boolean(api) });
  const [openId, setOpenId] = useState<string | null>(null);

  const action = useAction(() => {
    classes.reload();
    houses.reload();
  });
  const [className, setClassName] = useState("");
  const [levelOrder, setLevelOrder] = useState("");
  const [houseName, setHouseName] = useState("");

  if (!api) return <Spinner />;

  const activeTeachers = (teachers.data ?? []).filter((teacher) => teacher.is_active);

  return (
    <>
      <Panel
        title="Classes"
        description="Level order sets the display order only. Pupils are never ranked (R11)."
      >
        {classes.loading ? <Spinner /> : null}
        {classes.error ? <Notice>{classes.error}</Notice> : null}

        <Table head={["Class", "Order", ""]} empty="No classes yet.">
          {(classes.data ?? []).map((item) => (
            <Row key={item.id}>
              <Cell>
                {item.name}
                {item.is_active ? null : <Badge tone="bad">Inactive</Badge>}
              </Cell>
              <Cell>{item.level_order}</Cell>
              <Cell>
                <Button
                  variant="ghost"
                  onClick={() => setOpenId(openId === item.id ? null : item.id)}
                >
                  {openId === item.id ? "Close" : "Subjects & teachers"}
                </Button>
              </Cell>
            </Row>
          ))}
        </Table>

        <form
          className="mt-4 grid gap-3 sm:grid-cols-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api.createClass({ name: className, level_order: Number(levelOrder || 0) }),
              `${className} added.`,
            );
            if (created) {
              setClassName("");
              setLevelOrder("");
            }
          }}
        >
          <Field label="Name" required>
            <Input
              required
              placeholder="Primary 4"
              value={className}
              onChange={(event) => setClassName(event.target.value)}
            />
          </Field>
          <Field label="Level order" required>
            <Input
              type="number"
              min={0}
              required
              value={levelOrder}
              onChange={(event) => setLevelOrder(event.target.value)}
            />
          </Field>
          <div className="flex items-end">
            <Button type="submit" disabled={action.busy}>
              Add class
            </Button>
          </div>
        </form>
      </Panel>

      {openId ? (
        <ClassDetail
          key={openId}
          schoolClass={(classes.data ?? []).find((item) => item.id === openId)!}
          teachers={activeTeachers}
        />
      ) : null}

      <Panel title="Houses" description="The card prints each pupil's house in its header.">
        {houses.error ? <Notice>{houses.error}</Notice> : null}
        <div className="flex flex-wrap gap-2">
          {(houses.data ?? []).map((house) => (
            <Badge key={house.id}>{house.name}</Badge>
          ))}
          {houses.data?.length ? null : (
            <p className="text-sm text-[var(--muted)]">No houses yet.</p>
          )}
        </div>

        <form
          className="mt-4 flex flex-wrap items-end gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api.createHouse({ name: houseName }),
              `${houseName} added.`,
            );
            if (created) setHouseName("");
          }}
        >
          <Field label="Name" required>
            <Input
              required
              value={houseName}
              onChange={(event) => setHouseName(event.target.value)}
            />
          </Field>
          <Button type="submit" variant="secondary" disabled={action.busy}>
            Add house
          </Button>
        </form>

        <div className="mt-3 flex flex-col gap-2">
          <Notice>{action.error}</Notice>
          <Notice tone="success">{action.success}</Notice>
        </div>
      </Panel>
    </>
  );
}

/* ------------------------------------------------------------------------- */

function ClassDetail({
  schoolClass,
  teachers,
}: {
  schoolClass: SchoolClass;
  teachers: Account[];
}) {
  const api = useAdminApi()!;
  const subjects = useResource(() => api.subjects(), [api]);
  const offerings = useResource(() => api.classSubjects(schoolClass.id), [api, schoolClass.id]);
  const assignments = useResource(
    () => api.narrativeAssignments(schoolClass.id),
    [api, schoolClass.id],
  );
  const sections = useResource(() => api.narrativeSections(), [api]);
  const classTeachers = useResource(() => api.users("teacher"), [api]);

  const action = useAction(() => {
    offerings.reload();
    assignments.reload();
    classTeachers.reload();
  });

  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const offered = new Set((offerings.data ?? []).map((row) => row.subject_id));
  const selection = chosen ?? offered;

  const scored = (subjects.data ?? []).filter((subject) => !subject.is_group);
  const headings = (subjects.data ?? []).filter((subject) => subject.is_group);

  return (
    <Panel
      title={schoolClass.name}
      description="Who teaches what, and who writes the card."
    >
      <div className="flex flex-col gap-6">
        <section>
          <h3 className="text-sm font-semibold">Class teacher</h3>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Writes the narrative sections, records attendance and growth, writes the class
            teacher&apos;s comment, and submits the class for review.
          </p>
          <form
            className="mt-3 flex flex-wrap items-end gap-3"
            onSubmit={(event) => event.preventDefault()}
          >
            <Field label="Teacher">
              <Select
                defaultValue=""
                onChange={(event) => {
                  const teacherId = event.target.value;
                  if (!teacherId) return;
                  void action.run(
                    () => api.setClassTeacher(schoolClass.id, teacherId),
                    "Class teacher set.",
                  );
                }}
              >
                <option value="">Choose a teacher…</option>
                {teachers.map((teacher) => (
                  <option key={teacher.id} value={teacher.id}>
                    {teacher.full_name}
                  </option>
                ))}
              </Select>
            </Field>
          </form>
        </section>

        <section>
          <h3 className="text-sm font-semibold">Subjects taught</h3>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Group headings are not listed: they print on the card and carry no scores (R7).
            {headings.length
              ? ` ${headings.map((heading) => heading.name).join(", ")} ${
                  headings.length === 1 ? "is a heading" : "are headings"
                }.`
              : ""}
          </p>

          {subjects.loading || offerings.loading ? <Spinner /> : null}
          {subjects.error ? <Notice>{subjects.error}</Notice> : null}

          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {scored.map((subject) => (
              <li key={subject.id}>
                <label className="flex items-center gap-2 text-sm">
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
                  {subject.name}
                  {subject.is_specialist ? <Badge tone="warn">Specialist</Badge> : null}
                </label>
              </li>
            ))}
          </ul>

          <Button
            className="mt-3"
            disabled={action.busy || chosen === null}
            onClick={async () => {
              const ordered = scored
                .filter((subject) => selection.has(subject.id))
                .map((subject) => subject.id);
              const saved = await action.run(
                () => api.setClassSubjects(schoolClass.id, ordered),
                "Subject list saved.",
              );
              if (saved) setChosen(null);
            }}
          >
            Save subject list
          </Button>
        </section>

        <section>
          <h3 className="text-sm font-semibold">Who enters the scores</h3>
          <Table head={["Subject", "Teacher"]} empty="Save a subject list first.">
            {(offerings.data ?? []).map((row) => {
              const subject = (subjects.data ?? []).find((item) => item.id === row.subject_id);
              return (
                <Row key={row.id}>
                  <Cell>{subject?.name ?? "—"}</Cell>
                  <Cell>
                    <Select
                      aria-label={`Teacher for ${subject?.name ?? "subject"}`}
                      defaultValue=""
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
                      {teachers.map((teacher) => (
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
        </section>

        <section>
          <h3 className="text-sm font-semibold">Who writes each narrative section</h3>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Leave a section unassigned and the class teacher writes it — that is the normal
            case, so most of this list stays empty. Assign one only where a specialist writes
            their own area.
          </p>

          {sections.loading || assignments.loading ? <Spinner /> : null}

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
                      {section.label}
                    </Cell>
                    <Cell>
                      <Select
                        aria-label={`Who writes ${section.label}`}
                        value={assigned?.teacher_user_id ?? ""}
                        onChange={(event) =>
                          void action.run(
                            () =>
                              api.setNarrativeAssignments(schoolClass.id, {
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
                        {teachers.map((teacher) => (
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
        </section>

        <div className="flex flex-col gap-2">
          <Notice>{action.error}</Notice>
          <Notice tone="success">{action.success}</Notice>
        </div>
      </div>
    </Panel>
  );
}
