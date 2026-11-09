"use client";

/**
 * Classes and houses (ARCHITECTURE.md §4.3, §5.2, D15).
 *
 * The list only. What a class is taught, and by whom, is
 * `/admin/classes/[classId]` — it used to open as a panel stacked under this
 * table, which meant the two assignments that decide who can do what for a
 * whole term had no address of their own and no back button
 * (docs/DECISIONS.md D104).
 */

import { House, Layers, Plus } from "lucide-react";
import { useState } from "react";

import { Modal } from "@/components/modal";
import {
  Badge,
  Button,
  ButtonLink,
  Cell,
  EmptyState,
  Field,
  Input,
  Notice,
  PageHeader,
  Panel,
  Row,
  SkeletonTable,
  Table,
} from "@/components/ui";
import { useAdminApi } from "@/lib/api/use-admin";
import { useAction, useResource } from "@/lib/use-async";

export default function ClassesPage() {
  const api = useAdminApi();
  const classes = useResource(() => api!.classes(true), [api], { enabled: Boolean(api) });
  const houses = useResource(() => api!.houses(), [api], { enabled: Boolean(api) });

  const action = useAction(() => {
    classes.reload();
    houses.reload();
  });
  // Which create dialog is open (D117). One at a time, so one action serves
  // both: its error belongs to whichever dialog is showing.
  const [dialog, setDialog] = useState<"class" | "house" | null>(null);
  const openDialog = (which: "class" | "house") => {
    action.clear();
    setDialog(which);
  };
  const [className, setClassName] = useState("");
  const [levelOrder, setLevelOrder] = useState("");
  const [houseName, setHouseName] = useState("");

  const loading = !api || classes.loading;

  return (
    <>
      <PageHeader
        title="Classes"
        description="Level order sets the display order only. Pupils are never ranked (R11)."
        actions={
          <>
            <Button
              variant="secondary"
              icon={House}
              disabled={!api}
              onClick={() => openDialog("house")}
            >
              Add house
            </Button>
            <Button icon={Plus} disabled={!api} onClick={() => openDialog("class")}>
              Add class
            </Button>
          </>
        }
      />

      {dialog ? null : <Notice tone="success">{action.success}</Notice>}

      <Panel
        title="Every class"
        icon={Layers}
        description="Open a class to set its class teacher, its subjects and who writes the card."
      >
        {loading ? (
          <SkeletonTable rows={6} columns={3} label="Loading the classes…" />
        ) : (
          <>
            {classes.error ? <Notice>{classes.error}</Notice> : null}

            <Table head={["Class", "Order", ""]} empty="No classes yet.">
              {(classes.data ?? []).map((item) => (
                <Row key={item.id}>
                  <Cell>
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{item.name}</span>
                      {item.is_active ? null : <Badge tone="bad">Inactive</Badge>}
                    </span>
                  </Cell>
                  <Cell className="tabular-nums text-[var(--muted)]">{item.level_order}</Cell>
                  <Cell className="text-right">
                    <ButtonLink href={`/admin/classes/${item.id}`} size="sm">
                      Subjects &amp; teachers
                    </ButtonLink>
                  </Cell>
                </Row>
              ))}
            </Table>
          </>
        )}
      </Panel>

      <Panel title="Houses" description="The card prints each pupil's house in its header.">
        {houses.loading ? (
          <SkeletonTable rows={1} columns={4} label="Loading the houses…" />
        ) : (
          <>
            {houses.error ? <Notice>{houses.error}</Notice> : null}
            {houses.data?.length ? (
              <div className="flex flex-wrap gap-2">
                {houses.data.map((house) => (
                  <Badge key={house.id} tone="gold">
                    {house.name}
                  </Badge>
                ))}
              </div>
            ) : (
              <EmptyState
                title="No houses yet"
                description="A house prints in the card's header. Add the ones the school uses with “Add house” above."
              />
            )}
          </>
        )}
      </Panel>

      <Modal open={dialog === "class"} onClose={() => setDialog(null)} title="Add a class">
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api!.createClass({ name: className, level_order: Number(levelOrder || 0) }),
              `${className} added.`,
            );
            if (created) {
              setClassName("");
              setLevelOrder("");
              setDialog(null);
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
          <Field label="Level order" hint="Display order only — lower comes first." required>
            <Input
              type="number"
              min={0}
              required
              value={levelOrder}
              onChange={(event) => setLevelOrder(event.target.value)}
            />
          </Field>
          {action.error ? (
            <div className="sm:col-span-2">
              <Notice>{action.error}</Notice>
            </div>
          ) : null}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="secondary" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={action.busy} disabled={!api}>
              Add class
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={dialog === "house"}
        onClose={() => setDialog(null)}
        title="Add a house"
        description="The card prints each pupil's house in its header."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api!.createHouse({ name: houseName }),
              `${houseName} added.`,
            );
            if (created) {
              setHouseName("");
              setDialog(null);
            }
          }}
        >
          <Field label="Name" required>
            <Input
              required
              value={houseName}
              onChange={(event) => setHouseName(event.target.value)}
            />
          </Field>
          <Notice>{action.error}</Notice>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={action.busy} disabled={!api}>
              Add house
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
