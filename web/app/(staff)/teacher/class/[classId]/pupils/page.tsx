"use client";

/**
 * A class teacher adds pupils to their own class (docs/DECISIONS.md D125).
 *
 * Each one waits for an admin. Until approved, a pupil appears here and
 * nowhere else: no register, no score sheet, no card. The house is left to
 * the admin, who approves and can correct anything at the same time.
 */

import { Hourglass, Plus, UserPlus } from "lucide-react";
import { useRef, useState } from "react";

import { Modal } from "@/components/modal";
import {
  Badge,
  Button,
  Cell,
  EmptyState,
  Field,
  Input,
  Notice,
  Panel,
  Row,
  Select,
  SkeletonTable,
  Table,
} from "@/components/ui";
import { formatDate, pupilName } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";

import { useClassContext } from "../context";

const EMPTY = {
  first_name: "",
  middle_name: "",
  last_name: "",
  sex: "",
  date_of_birth: "",
  admission_number: "",
};

export default function AddPupilsPage() {
  const { api, classId } = useClassContext();
  const waiting = useResource((signal) => api.proposedPupils(classId, signal), [api, classId]);
  const action = useAction(waiting.reload);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const firstInput = useRef<HTMLInputElement>(null);

  return (
    <>
      <Panel
        title="Pupils waiting for approval"
        icon={Hourglass}
        description="Pupils you add appear in the register, score sheets and cards once an admin approves them."
        actions={
          <Button
            icon={UserPlus}
            onClick={() => {
              action.clear();
              setAdding(true);
            }}
          >
            Add pupil
          </Button>
        }
      >
        {waiting.loading ? (
          <SkeletonTable rows={3} columns={3} label="Loading the pupils you added…" />
        ) : waiting.error ? (
          <Notice>{waiting.error}</Notice>
        ) : waiting.data?.length ? (
          <Table head={["Name", "Born", ""]}>
            {waiting.data.map((pupil) => (
              <Row key={pupil.id}>
                <Cell className="font-medium">{pupilName(pupil)}</Cell>
                <Cell className="text-[var(--muted)]">{formatDate(pupil.date_of_birth)}</Cell>
                <Cell className="text-right">
                  <Badge tone="warn">Waiting for an admin</Badge>
                </Cell>
              </Row>
            ))}
          </Table>
        ) : (
          <EmptyState
            title="Nobody waiting"
            description="Pupils you add show here until an admin approves them. Approved pupils move to the register."
          />
        )}
        {!adding && action.success ? (
          <div className="mt-3">
            <Notice tone="success">{action.success}</Notice>
          </div>
        ) : null}
      </Panel>

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add a pupil to this class"
        description="An admin approves each pupil before they join the register. You can add several in a row."
        size="lg"
      >
        <form
          className="grid gap-3 sm:grid-cols-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const added = await action.run(
              () =>
                api.proposePupil(classId, {
                  first_name: form.first_name,
                  middle_name: form.middle_name || null,
                  last_name: form.last_name,
                  sex: (form.sex || null) as "M" | "F" | null,
                  date_of_birth: form.date_of_birth || null,
                  admission_number: form.admission_number || null,
                }),
              `${form.first_name} ${form.last_name} added. An admin will approve them.`,
            );
            if (added) {
              setForm(EMPTY);
              firstInput.current?.focus();
            }
          }}
        >
          <Field label="First name" required>
            <Input
              ref={firstInput}
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
          <Field label="Admission number" hint="Optional.">
            <Input
              value={form.admission_number}
              onChange={(event) => setForm({ ...form, admission_number: event.target.value })}
            />
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
            <Button type="submit" icon={Plus} loading={action.busy}>
              Add pupil
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
