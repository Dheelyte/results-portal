"use client";

/**
 * The subject tree (ARCHITECTURE.md §1.5, §4.3, R7).
 *
 * English is a group heading over five scored sub-subjects. A heading prints
 * on the card and carries no scores, so it can never be offered to a class —
 * the API refuses that, and this screen says so before an admin tries.
 *
 * The card leaves blank rows for additions, so the list is editable and the
 * order is configurable. Retiring is the only kind of removal: last term's
 * cards still cite the subject.
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
import type { Subject } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { useAction, useResource } from "@/lib/use-async";

export default function SubjectsPage() {
  const api = useAdminApi();
  const [showRetired, setShowRetired] = useState(false);
  const subjects = useResource(() => api!.subjects(showRetired), [api, showRetired], {
    enabled: Boolean(api),
  });
  const action = useAction(subjects.reload);
  const [form, setForm] = useState({
    name: "",
    parent_subject_id: "",
    is_group: false,
    is_specialist: false,
  });

  if (!api) return <Spinner />;

  const groups = (subjects.data ?? []).filter((subject) => subject.is_group);
  const ordered = orderForDisplay(subjects.data ?? []);
  const nextOrder = (subjects.data ?? []).length;

  return (
    <>
      <Panel
        title="Subjects"
        description="In card order. A group heading carries no scores of its own."
        actions={
          <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <input
              type="checkbox"
              checked={showRetired}
              onChange={(event) => setShowRetired(event.target.checked)}
            />
            Show retired
          </label>
        }
      >
        {subjects.loading ? <Spinner /> : null}
        {subjects.error ? <Notice>{subjects.error}</Notice> : null}

        <Table head={["Subject", "", "Order", ""]} empty="No subjects yet.">
          {ordered.map(({ subject, depth }) => (
            <Row key={subject.id}>
              <Cell>
                <span style={{ paddingLeft: depth * 16 }}>{subject.name}</span>
              </Cell>
              <Cell className="whitespace-nowrap">
                {subject.is_group ? <Badge>Heading</Badge> : null}
                {subject.is_specialist ? <Badge tone="warn">Specialist</Badge> : null}
                {!subject.is_active ? <Badge tone="bad">Retired</Badge> : null}
              </Cell>
              <Cell>
                <OrderInput subject={subject} onSaved={subjects.reload} />
              </Cell>
              <Cell className="whitespace-nowrap">
                {!subject.is_group ? (
                  <Button
                    variant="ghost"
                    disabled={action.busy}
                    onClick={() =>
                      void action.run(
                        () =>
                          api.updateSubject(subject.id, {
                            is_specialist: !subject.is_specialist,
                          }),
                        subject.is_specialist
                          ? `${subject.name} is no longer a specialist subject.`
                          : `${subject.name} is now a specialist subject.`,
                      )
                    }
                  >
                    {subject.is_specialist ? "Not specialist" : "Specialist"}
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  disabled={action.busy}
                  onClick={() =>
                    void action.run(
                      () => api.updateSubject(subject.id, { is_active: !subject.is_active }),
                      subject.is_active
                        ? `${subject.name} retired. Past cards keep it.`
                        : `${subject.name} is active again.`,
                    )
                  }
                >
                  {subject.is_active ? "Retire" : "Restore"}
                </Button>
              </Cell>
            </Row>
          ))}
        </Table>
      </Panel>

      <Panel title="Add a subject">
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () =>
                api.createSubject({
                  name: form.name,
                  parent_subject_id: form.parent_subject_id || null,
                  is_group: form.is_group,
                  is_specialist: form.is_specialist,
                  display_order: nextOrder,
                }),
              `${form.name} added.`,
            );
            if (created) {
              setForm({
                name: "",
                parent_subject_id: "",
                is_group: false,
                is_specialist: false,
              });
            }
          }}
        >
          <Field label="Name" required>
            <Input
              required
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </Field>

          <Field
            label="Sits under"
            hint="Only a group heading can be a parent. English is the only one on the card."
          >
            <Select
              value={form.parent_subject_id}
              disabled={form.is_group}
              onChange={(event) =>
                setForm({ ...form, parent_subject_id: event.target.value })
              }
            >
              <option value="">Nothing — a subject in its own right</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </Select>
          </Field>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.is_group}
              onChange={(event) =>
                setForm({
                  ...form,
                  is_group: event.target.checked,
                  parent_subject_id: "",
                  is_specialist: event.target.checked ? false : form.is_specialist,
                })
              }
            />
            <span>
              <span className="font-medium">Group heading</span>
              <span className="block text-xs text-[var(--muted)]">
                Prints as a heading and carries no scores. Cannot be offered to a class (R7).
              </span>
            </span>
          </label>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              disabled={form.is_group}
              checked={form.is_specialist}
              onChange={(event) => setForm({ ...form, is_specialist: event.target.checked })}
            />
            <span>
              <span className="font-medium">Taught by a specialist</span>
              <span className="block text-xs text-[var(--muted)]">
                Your choice, not the software&apos;s. It can be changed at any time.
              </span>
            </span>
          </label>

          <div className="sm:col-span-2">
            <Button type="submit" disabled={action.busy}>
              Add subject
            </Button>
          </div>
        </form>

        <div className="mt-3 flex flex-col gap-2">
          <Notice>{action.error}</Notice>
          <Notice tone="success">{action.success}</Notice>
        </div>
      </Panel>
    </>
  );
}

function OrderInput({ subject, onSaved }: { subject: Subject; onSaved: () => void }) {
  const api = useAdminApi()!;
  const action = useAction(onSaved);
  const [order, setOrder] = useState(String(subject.display_order));

  return (
    <Input
      type="number"
      min={0}
      aria-label={`Display order for ${subject.name}`}
      className="w-20"
      value={order}
      disabled={action.busy}
      onChange={(event) => setOrder(event.target.value)}
      onBlur={() => {
        if (Number(order) === subject.display_order) return;
        void action.run(() => api.updateSubject(subject.id, { display_order: Number(order) }));
      }}
    />
  );
}

/** Children directly beneath their heading, each list in display order. */
function orderForDisplay(subjects: Subject[]): { subject: Subject; depth: number }[] {
  const byOrder = [...subjects].sort(
    (a, b) => a.display_order - b.display_order || a.name.localeCompare(b.name),
  );
  const children = new Map<string, Subject[]>();
  for (const subject of byOrder) {
    if (!subject.parent_subject_id) continue;
    const siblings = children.get(subject.parent_subject_id) ?? [];
    siblings.push(subject);
    children.set(subject.parent_subject_id, siblings);
  }

  const rows: { subject: Subject; depth: number }[] = [];
  for (const subject of byOrder) {
    if (subject.parent_subject_id) continue;
    rows.push({ subject, depth: 0 });
    for (const child of children.get(subject.id) ?? []) {
      rows.push({ subject: child, depth: 1 });
    }
  }

  // A child whose parent is filtered out of this list still has to appear.
  const shown = new Set(rows.map((row) => row.subject.id));
  for (const subject of byOrder) {
    if (!shown.has(subject.id)) rows.push({ subject, depth: 0 });
  }
  return rows;
}
