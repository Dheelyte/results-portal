"use client";

/**
 * The roll (ARCHITECTURE.md §4.1, §4.2, N8).
 *
 * Typed in by hand — there is no import, by decision. That makes this the
 * slowest screen to use at go-live, roughly five hundred records, so the form
 * keeps the class and house between entries and the list is searchable and
 * paged rather than returning the whole roll.
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

  const pupils = useResource(
    () =>
      api!.pupils({
        class_id: filterClass || undefined,
        search: search || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [api, filterClass, search, offset],
    { enabled: Boolean(api) },
  );

  const action = useAction(pupils.reload);
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

  if (!api) return <Spinner />;

  const total = pupils.data?.total ?? 0;
  const classNameOf = (id: string) =>
    (classes.data ?? []).find((item) => item.id === id)?.name ?? "";

  return (
    <>
      <Panel
        title="Pupils"
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
          </div>
        }
      >
        {pupils.loading ? <Spinner /> : null}
        {pupils.error ? <Notice>{pupils.error}</Notice> : null}

        <Table
          head={["Admission no.", "Name", "Sex", "Born", "House", "Class"]}
          empty="No pupils match."
        >
          {(pupils.data?.items ?? []).map((pupil) => (
            <Row key={pupil.id}>
              <Cell>{pupil.admission_number}</Cell>
              <Cell>
                {pupilName(pupil)}
                {pupil.is_active ? null : <Badge tone="bad">Inactive</Badge>}
              </Cell>
              <Cell>{pupil.sex ?? "—"}</Cell>
              <Cell>{formatDate(pupil.date_of_birth)}</Cell>
              <Cell>
                {(houses.data ?? []).find((house) => house.id === pupil.house_id)?.name ?? "—"}
              </Cell>
              <Cell>
                <EnrollmentCell
                  pupilId={pupil.id}
                  classes={classes.data ?? []}
                  currentClassName={filterClass ? classNameOf(filterClass) : null}
                  onChanged={pupils.reload}
                />
              </Cell>
            </Row>
          ))}
        </Table>

        {total > PAGE_SIZE ? (
          <div className="mt-4 flex items-center gap-3 text-sm">
            <Button
              variant="secondary"
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
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        ) : null}
      </Panel>

      <Panel
        title="Add a pupil"
        description="The class and house stay as you set them, so a whole class can be typed in without resetting the form each time."
      >
        <form
          className="grid gap-3 sm:grid-cols-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () =>
                api.createPupil({
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
            }
          }}
        >
          <Field label="Admission number" required>
            <Input
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
          <div className="flex items-end">
            <Button type="submit" disabled={action.busy}>
              Add pupil
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
