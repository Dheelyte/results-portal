"use client";

/**
 * The subject tree (ARCHITECTURE.md §1.5, §4.3, R7).
 *
 * English is a group heading over five scored sub-subjects. A heading prints
 * on the card and carries no scores, so it can never be offered to a class —
 * the API refuses that, and this screen says so before an admin tries.
 *
 * The card leaves blank rows for additions, so the list is editable and the
 * order is configurable. Once a class is taught a subject, retiring is the
 * only kind of removal: last term's cards still cite it. A subject no class
 * was ever given can be deleted (D121).
 */

import { BookOpen, Plus } from "lucide-react";
import { useState } from "react";

import { ConfirmDelete, RowActions, type DeleteTarget } from "@/components/manage";
import { Modal } from "@/components/modal";
import {
  Badge,
  Button,
  Cell,
  Field,
  Input,
  Notice,
  PageHeader,
  Panel,
  Row,
  Select,
  SkeletonTable,
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
  // The dialog's own, so its error stays in the dialog (D117).
  const create = useAction(subjects.reload);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    parent_subject_id: "",
    is_group: false,
    is_specialist: false,
  });

  const update = useAction(subjects.reload);
  const [editing, setEditing] = useState<{
    subject: Subject;
    name: string;
    parent_subject_id: string;
  } | null>(null);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);

  const groups = (subjects.data ?? []).filter((subject) => subject.is_group);
  const ordered = orderForDisplay(subjects.data ?? []);
  const nextOrder = (subjects.data ?? []).length;

  return (
    <>
      <PageHeader
        title="Subjects"
        description="English is a group heading over five scored sub-subjects. A heading prints on the card and carries no scores, so it can never be offered to a class (R7)."
        actions={
          <Button
            icon={Plus}
            disabled={!api}
            onClick={() => {
              // Whichever message the page shows next is this create's.
              action.clear();
              create.clear();
              setCreating(true);
            }}
          >
            Add subject
          </Button>
        }
      />

      <Notice>{action.error}</Notice>
      <Notice tone="success">{action.success ?? (creating ? null : create.success)}</Notice>

      <Panel
        title="The subject tree"
        icon={BookOpen}
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
        {!api || subjects.loading ? (
          <SkeletonTable rows={8} columns={4} label="Loading the subjects…" />
        ) : (
          <>
            {subjects.error ? <Notice>{subjects.error}</Notice> : null}

            <Table head={["Subject", "", "Order", ""]} empty="No subjects yet.">
              {ordered.map(({ subject, depth }) => (
                <Row key={subject.id}>
                  <Cell>
                    <span
                      className="font-medium"
                      style={{ paddingLeft: depth * 16 }}
                    >
                      {subject.name}
                    </span>
                  </Cell>
                  <Cell className="whitespace-nowrap">
                    <span className="flex flex-wrap gap-1">
                      {subject.is_group ? <Badge tone="brand">Heading</Badge> : null}
                      {subject.is_specialist ? <Badge tone="warn">Specialist</Badge> : null}
                      {!subject.is_active ? <Badge tone="bad">Retired</Badge> : null}
                    </span>
                  </Cell>
                  <Cell>
                    <OrderInput subject={subject} onSaved={subjects.reload} />
                  </Cell>
                  <Cell className="text-right">
                    <RowActions
                      label={subject.name}
                      disabled={action.busy}
                      onEdit={() => {
                        update.clear();
                        setEditing({
                          subject,
                          name: subject.name,
                          parent_subject_id: subject.parent_subject_id ?? "",
                        });
                      }}
                      onDelete={() =>
                        setDeleting({
                          name: subject.name,
                          consequence:
                            "Only a subject no class has been given can be deleted. Once a class is taught it, retire it instead — past cards keep it.",
                          run: () => api!.deleteSubject(subject.id),
                        })
                      }
                    >
                    {!subject.is_group ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={action.busy}
                        onClick={() =>
                          void action.run(
                            () =>
                              api!.updateSubject(subject.id, {
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
                      size="sm"
                      disabled={action.busy}
                      onClick={() =>
                        void action.run(
                          () =>
                            api!.updateSubject(subject.id, { is_active: !subject.is_active }),
                          subject.is_active
                            ? `${subject.name} retired. Past cards keep it.`
                            : `${subject.name} is active again.`,
                        )
                      }
                    >
                      {subject.is_active ? "Retire" : "Restore"}
                    </Button>
                    </RowActions>
                  </Cell>
                </Row>
              ))}
            </Table>
          </>
        )}
      </Panel>

      <Modal open={creating} onClose={() => setCreating(false)} title="Add a subject">
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await create.run(
              () =>
                api!.createSubject({
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
              setCreating(false);
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

          {create.error ? (
            <div className="sm:col-span-2">
              <Notice>{create.error}</Notice>
            </div>
          ) : null}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="secondary" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={create.busy} disabled={!api}>
              Add subject
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title="Edit subject">
        {editing ? (
          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={async (event) => {
              event.preventDefault();
              const saved = await update.run(
                () =>
                  api!.updateSubject(editing.subject.id, {
                    name: editing.name,
                    parent_subject_id: editing.parent_subject_id || null,
                  }),
                `${editing.name.trim()} saved.`,
              );
              if (saved) setEditing(null);
            }}
          >
            <Field label="Name" hint="Printed on the card." required>
              <Input
                required
                value={editing.name}
                onChange={(event) => setEditing({ ...editing, name: event.target.value })}
              />
            </Field>
            {editing.subject.is_group ? null : (
              <Field label="Sits under">
                <Select
                  value={editing.parent_subject_id}
                  onChange={(event) =>
                    setEditing({ ...editing, parent_subject_id: event.target.value })
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
            )}
            {update.error ? (
              <div className="sm:col-span-2">
                <Notice>{update.error}</Notice>
              </div>
            ) : null}
            <div className="flex justify-end gap-2 sm:col-span-2">
              <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button type="submit" loading={update.busy}>
                Save changes
              </Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <ConfirmDelete
        target={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={subjects.reload}
      />
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
