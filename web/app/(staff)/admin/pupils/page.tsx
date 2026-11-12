"use client";

/**
 * The roll (ARCHITECTURE.md §4.1, §4.2, N8).
 *
 * Typed in by hand — there is no import, by decision. That makes this the
 * slowest screen to use at go-live, roughly five hundred records, so the form
 * keeps the class and house between entries and the list is searchable and
 * paged rather than returning the whole roll.
 */

import { ChevronLeft, ChevronRight, GraduationCap, Plus, UserPlus } from "lucide-react";
import { useRef, useState } from "react";

import { ConfirmDelete, RowActions, type DeleteTarget } from "@/components/manage";
import { Modal } from "@/components/modal";
import {
  Avatar,
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
import type { Pupil } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDate, pupilName } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";

const PAGE_SIZE = 25;

export default function PupilsPage() {
  const api = useAdminApi();
  const classes = useResource(() => api!.classes(), [api], { enabled: Boolean(api) });
  const houses = useResource(() => api!.houses(), [api], { enabled: Boolean(api) });

  const [filterClass, setFilterClass] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  // Off by default: a pupil who has left is deactivated, and drops out of the
  // roll until this asks for them, so they can be found and reactivated.
  const [showInactive, setShowInactive] = useState(false);

  const pupils = useResource(
    () =>
      api!.pupils({
        class_id: filterClass || undefined,
        search: search || undefined,
        include_inactive: showInactive,
        limit: PAGE_SIZE,
        offset,
      }),
    [api, filterClass, search, showInactive, offset],
    { enabled: Boolean(api) },
  );

  const action = useAction(pupils.reload);
  const [adding, setAdding] = useState(false);
  const admissionInput = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({
    admission_number: "",
    first_name: "",
    middle_name: "",
    last_name: "",
    sex: "",
    date_of_birth: "",
    house_id: "",
    class_id: "",
  });

  const update = useAction(pupils.reload);
  const [editing, setEditing] = useState<{
    id: string;
    admission_number: string;
    first_name: string;
    middle_name: string;
    last_name: string;
    sex: string;
    date_of_birth: string;
    house_id: string;
    is_active: boolean;
  } | null>(null);
  const startEditing = (pupil: Pupil) => {
    update.clear();
    setEditing({
      id: pupil.id,
      admission_number: pupil.admission_number,
      first_name: pupil.first_name,
      middle_name: pupil.middle_name ?? "",
      last_name: pupil.last_name,
      sex: pupil.sex ?? "",
      date_of_birth: pupil.date_of_birth ?? "",
      house_id: pupil.house_id ?? "",
      is_active: pupil.is_active,
    });
  };
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);

  const total = pupils.data?.total ?? 0;
  const classNameOf = (id: string) =>
    (classes.data ?? []).find((item) => item.id === id)?.name ?? "";

  return (
    <>
      <PageHeader
        title="Pupils"
        description="Typed in by hand — there is no import, by decision (N8). The form keeps the class and house between entries."
        actions={
          <Button
            icon={UserPlus}
            disabled={!api}
            onClick={() => {
              action.clear();
              setAdding(true);
            }}
          >
            Add pupil
          </Button>
        }
      />

      <Panel
        title="The roll"
        icon={GraduationCap}
        description={`${total} ${total === 1 ? "pupil" : "pupils"} matching.`}
        actions={
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Class">
              <Select
                value={filterClass}
                onChange={(event) => {
                  setFilterClass(event.target.value);
                  setOffset(0);
                }}
              >
                <option value="">All classes</option>
                {(classes.data ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Search">
              <Input
                placeholder="Name or admission number"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setOffset(0);
                }}
              />
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(event) => {
                  setShowInactive(event.target.checked);
                  setOffset(0);
                }}
              />
              Show deactivated
            </label>
          </div>
        }
      >
        {!api || pupils.loading ? (
          <SkeletonTable rows={8} columns={7} label="Loading the roll…" />
        ) : (
          <>
            {pupils.error ? <Notice>{pupils.error}</Notice> : null}

            <Table
              head={["Admission no.", "Name", "Sex", "Born", "House", "Class", ""]}
              empty="No pupils match."
            >
              {(pupils.data?.items ?? []).map((pupil) => (
                <Row key={pupil.id}>
                  <Cell className="tabular-nums text-[var(--muted)]">
                    {pupil.admission_number}
                  </Cell>
                  <Cell>
                    <span className="flex items-center gap-2.5">
                      <Avatar name={pupilName(pupil)} size="sm" />
                      <span className="min-w-0">
                        <span className="block font-medium">{pupilName(pupil)}</span>
                        {pupil.is_active ? null : <Badge tone="bad">Inactive</Badge>}
                      </span>
                    </span>
                  </Cell>
                  <Cell className="text-[var(--muted)]">{pupil.sex ?? "—"}</Cell>
                  <Cell className="text-[var(--muted)]">
                    {formatDate(pupil.date_of_birth)}
                  </Cell>
                  <Cell className="text-[var(--muted)]">
                    {(houses.data ?? []).find((house) => house.id === pupil.house_id)?.name ??
                      "—"}
                  </Cell>
                  <Cell>
                    <EnrollmentCell
                      pupilId={pupil.id}
                      classes={classes.data ?? []}
                      currentClassName={filterClass ? classNameOf(filterClass) : null}
                      onChanged={pupils.reload}
                    />
                  </Cell>
                  <Cell className="text-right">
                    <RowActions
                      label={pupilName(pupil)}
                      onEdit={() => startEditing(pupil)}
                      onDelete={() =>
                        setDeleting({
                          name: pupilName(pupil),
                          consequence:
                            "Only a pupil with no scores, passages, attendance or report cards can be deleted — a duplicate, for example. Their class enrolment and parent links go with them. A pupil who has left should be deactivated instead.",
                          run: () => api!.deletePupil(pupil.id),
                        })
                      }
                    />
                  </Cell>
                </Row>
              ))}
            </Table>
          </>
        )}

        {total > PAGE_SIZE ? (
          <div className="mt-4 flex items-center gap-3 text-sm">
            <Button
              variant="secondary"
              size="sm"
              icon={ChevronLeft}
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <span className="text-[var(--muted)]">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <Button
              variant="secondary"
              size="sm"
              icon={ChevronRight}
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        ) : null}
      </Panel>

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add a pupil"
        description="The class and house stay as you set them, so a whole class can be typed in without closing this or resetting the form each time."
        size="lg"
      >
        <form
          className="grid gap-3 sm:grid-cols-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () =>
                api!.createPupil({
                  admission_number: form.admission_number,
                  first_name: form.first_name,
                  middle_name: form.middle_name || null,
                  last_name: form.last_name,
                  sex: (form.sex || null) as "M" | "F" | null,
                  date_of_birth: form.date_of_birth || null,
                  house_id: form.house_id || null,
                  class_id: form.class_id || null,
                }),
              `${form.first_name} ${form.last_name} added.`,
            );
            if (created) {
              setForm({
                ...form,
                admission_number: "",
                first_name: "",
                middle_name: "",
                last_name: "",
                sex: "",
                date_of_birth: "",
              });
              // Open for the next one: N8's whole class, typed in a row.
              admissionInput.current?.focus();
            }
          }}
        >
          <Field label="Admission number" required>
            <Input
              ref={admissionInput}
              required
              value={form.admission_number}
              onChange={(event) =>
                setForm({ ...form, admission_number: event.target.value })
              }
            />
          </Field>
          <Field label="First name" required>
            <Input
              required
              value={form.first_name}
              onChange={(event) => setForm({ ...form, first_name: event.target.value })}
            />
          </Field>
          <Field label="Middle name">
            <Input
              value={form.middle_name}
              onChange={(event) => setForm({ ...form, middle_name: event.target.value })}
            />
          </Field>
          <Field label="Last name" required>
            <Input
              required
              value={form.last_name}
              onChange={(event) => setForm({ ...form, last_name: event.target.value })}
            />
          </Field>
          <Field label="Sex" hint="As the card records it.">
            <Select
              value={form.sex}
              onChange={(event) => setForm({ ...form, sex: event.target.value })}
            >
              <option value="">Not recorded</option>
              <option value="M">M</option>
              <option value="F">F</option>
            </Select>
          </Field>
          <Field label="Date of birth">
            <Input
              type="date"
              value={form.date_of_birth}
              onChange={(event) => setForm({ ...form, date_of_birth: event.target.value })}
            />
          </Field>
          <Field label="House">
            <Select
              value={form.house_id}
              onChange={(event) => setForm({ ...form, house_id: event.target.value })}
            >
              <option value="">Not assigned</option>
              {(houses.data ?? []).map((house) => (
                <option key={house.id} value={house.id}>
                  {house.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Class"
            hint="A pupil with no class appears in no class list and gets no report."
          >
            <Select
              value={form.class_id}
              onChange={(event) => setForm({ ...form, class_id: event.target.value })}
            >
              <option value="">Not enrolled yet</option>
              {(classes.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </Field>
          {action.error || action.success ? (
            <div className="flex flex-col gap-2 sm:col-span-3">
              <Notice>{action.error}</Notice>
              <Notice tone="success">{action.success}</Notice>
            </div>
          ) : null}
          <div className="flex justify-end gap-2 sm:col-span-3">
            <Button type="button" variant="secondary" onClick={() => setAdding(false)}>
              Done
            </Button>
            <Button type="submit" icon={Plus} loading={action.busy} disabled={!api}>
              Add pupil
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title="Edit pupil"
        description="A corrected name shows on the next card generated. Cards already published keep what they were issued with."
        size="lg"
      >
        {editing ? (
          <form
            className="grid gap-3 sm:grid-cols-3"
            onSubmit={async (event) => {
              event.preventDefault();
              const saved = await update.run(() =>
                api!.updatePupil(editing.id, {
                  admission_number: editing.admission_number,
                  first_name: editing.first_name,
                  middle_name: editing.middle_name || null,
                  last_name: editing.last_name,
                  sex: (editing.sex || null) as "M" | "F" | null,
                  date_of_birth: editing.date_of_birth || null,
                  house_id: editing.house_id || null,
                  is_active: editing.is_active,
                }),
              );
              if (saved) setEditing(null);
            }}
          >
            <Field label="Admission number" required>
              <Input
                required
                value={editing.admission_number}
                onChange={(event) =>
                  setEditing({ ...editing, admission_number: event.target.value })
                }
              />
            </Field>
            <Field label="First name" required>
              <Input
                required
                value={editing.first_name}
                onChange={(event) => setEditing({ ...editing, first_name: event.target.value })}
              />
            </Field>
            <Field label="Middle name">
              <Input
                value={editing.middle_name}
                onChange={(event) => setEditing({ ...editing, middle_name: event.target.value })}
              />
            </Field>
            <Field label="Last name" required>
              <Input
                required
                value={editing.last_name}
                onChange={(event) => setEditing({ ...editing, last_name: event.target.value })}
              />
            </Field>
            <Field label="Sex" hint="As the card records it.">
              <Select
                value={editing.sex}
                onChange={(event) => setEditing({ ...editing, sex: event.target.value })}
              >
                <option value="">Not recorded</option>
                <option value="M">M</option>
                <option value="F">F</option>
              </Select>
            </Field>
            <Field label="Date of birth">
              <Input
                type="date"
                value={editing.date_of_birth}
                onChange={(event) => setEditing({ ...editing, date_of_birth: event.target.value })}
              />
            </Field>
            <Field label="House">
              <Select
                value={editing.house_id}
                onChange={(event) => setEditing({ ...editing, house_id: event.target.value })}
              >
                <option value="">Not assigned</option>
                {(houses.data ?? []).map((house) => (
                  <option key={house.id} value={house.id}>
                    {house.name}
                  </option>
                ))}
              </Select>
            </Field>
            <label className="flex items-start gap-2 text-sm sm:col-span-2 sm:self-end">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={editing.is_active}
                onChange={(event) => setEditing({ ...editing, is_active: event.target.checked })}
              />
              <span>
                <span className="font-medium">Active</span>
                <span className="block text-[var(--muted)]">
                  Untick for a pupil who has left. Their records and past cards are kept.
                </span>
              </span>
            </label>
            {update.error ? (
              <div className="sm:col-span-3">
                <Notice>{update.error}</Notice>
              </div>
            ) : null}
            <div className="flex justify-end gap-2 sm:col-span-3">
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

      <ConfirmDelete target={deleting} onClose={() => setDeleting(null)} onDeleted={pupils.reload} />
    </>
  );
}

function EnrollmentCell({
  pupilId,
  classes,
  currentClassName,
  onChanged,
}: {
  pupilId: string;
  classes: { id: string; name: string }[];
  currentClassName: string | null;
  onChanged: () => void;
}) {
  const api = useAdminApi()!;
  const action = useAction(onChanged);

  return (
    <div className="flex flex-col gap-1">
      {currentClassName ? (
        <span className="text-xs text-[var(--muted)]">{currentClassName}</span>
      ) : null}
      <Select
        aria-label="Move to class"
        defaultValue=""
        disabled={action.busy}
        onChange={(event) => {
          const classId = event.target.value;
          if (!classId) return;
          void action.run(() => api.setEnrollment(pupilId, { class_id: classId }));
        }}
      >
        <option value="">Move to…</option>
        {classes.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </Select>
      {action.error ? (
        <span className="text-xs text-[var(--danger)]">{action.error}</span>
      ) : null}
    </div>
  );
}
