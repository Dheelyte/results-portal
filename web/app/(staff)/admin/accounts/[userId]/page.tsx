"use client";

/**
 * A parent's children (ARCHITECTURE.md §4.1, §5.2).
 *
 * This record is what §5.2's most important filter rests on: a parent signs
 * in and sees exactly the pupils named here, and no others. It is worth a
 * page — attaching the wrong child is the one mistake on these screens that
 * shows another family's results to a stranger.
 *
 * Its own route since the redesign (D104).
 */

import { Link2, UsersRound } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import {
  Avatar,
  Badge,
  Button,
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
import { pupilName, ROLE_LABELS } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";

export default function ParentChildrenPage() {
  const api = useAdminApi();
  const { userId } = useParams<{ userId: string }>();

  const accounts = useResource(() => api!.users(), [api], { enabled: Boolean(api) });
  const children = useResource(() => api!.children(userId), [api, userId], {
    enabled: Boolean(api),
  });

  const [search, setSearch] = useState("");
  const candidates = useResource(
    () => api!.pupils({ search: search || undefined, limit: 10 }),
    [api, search],
    { enabled: Boolean(api) },
  );

  const action = useAction(children.reload);
  // Which row's attach is running, so one click spins one button.
  const [attaching, setAttaching] = useState<string | null>(null);

  const parent = (accounts.data ?? []).find((item) => item.id === userId) ?? null;
  const crumbs = [
    { label: "Accounts", href: "/admin/accounts" },
    { label: parent?.full_name ?? "Account" },
  ];
  const back = { href: "/admin/accounts", label: "Accounts" };

  if (!api || accounts.loading) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Account" />
        <SkeletonTable rows={4} columns={3} label="Loading the account…" />
      </>
    );
  }

  if (accounts.error) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Account" />
        <Notice>{accounts.error}</Notice>
      </>
    );
  }

  if (!parent) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Account" />
        <Notice tone="info">
          That account no longer exists. Pick one from the list of accounts.
        </Notice>
      </>
    );
  }

  const attached = new Set((children.data ?? []).map((child) => child.id));

  return (
    <>
      <PageHeader
        breadcrumbs={crumbs}
        back={back}
        title={
          <span className="flex items-center gap-2.5">
            <Avatar name={parent.full_name} />
            {parent.full_name}
          </span>
        }
        description={`${ROLE_LABELS[parent.role] ?? parent.role} · ${
          parent.email ?? parent.phone ?? "no identifier"
        }`}
        badge={parent.is_active ? null : <Badge tone="bad">Deactivated</Badge>}
      />

      {parent.role !== "parent" ? (
        <Notice tone="info">
          Only a parent account has children attached to it. This one is a{" "}
          {(ROLE_LABELS[parent.role] ?? parent.role).toLowerCase()}.
        </Notice>
      ) : (
        <>
          <Panel
            title="Attached children"
            icon={UsersRound}
            description="This is exactly what they will see when they sign in — nothing else."
          >
            {children.loading ? (
              <SkeletonTable rows={2} columns={2} label="Loading the children…" />
            ) : children.error ? (
              <Notice>{children.error}</Notice>
            ) : children.data?.length ? (
              <ul className="flex flex-col divide-y divide-[var(--border)]">
                {children.data.map((child) => (
                  <li key={child.id} className="flex items-center gap-2.5 py-2.5">
                    <Avatar name={pupilName(child)} size="sm" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {pupilName(child)}
                      </span>
                      <span className="block text-xs text-[var(--muted)]">
                        {child.admission_number}
                      </span>
                    </span>
                    <Badge tone="good">Attached</Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={UsersRound}
                title="Nothing attached yet"
                description="This account would sign in and see an empty page. Find a pupil below and attach them."
              />
            )}
          </Panel>

          <Panel title="Attach a child" icon={Link2}>
            <div className="flex flex-col gap-4">
              <div className="max-w-sm">
                <Field label="Find a pupil" hint="Search by name or admission number.">
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Ada, or SSH/2026/001"
                  />
                </Field>
              </div>

              {candidates.loading ? (
                <SkeletonTable rows={4} columns={3} label="Searching…" />
              ) : candidates.error ? (
                <Notice>{candidates.error}</Notice>
              ) : (
                <Table
                  head={["Pupil", "Admission no.", ""]}
                  empty={
                    search
                      ? "No pupil matches that."
                      : "Start typing to find a pupil."
                  }
                >
                  {(candidates.data?.items ?? []).map((pupil) => (
                    <Row key={pupil.id}>
                      <Cell className="font-medium">{pupilName(pupil)}</Cell>
                      <Cell className="text-[var(--muted)]">{pupil.admission_number}</Cell>
                      <Cell className="text-right">
                        {attached.has(pupil.id) ? (
                          <Badge tone="good">Attached</Badge>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={Link2}
                            loading={attaching === pupil.id}
                            disabled={action.busy}
                            onClick={async () => {
                              setAttaching(pupil.id);
                              await action.run(
                                () =>
                                  api.linkChildren(userId, {
                                    children: [{ pupil_id: pupil.id, is_primary: false }],
                                  }),
                                `${pupilName(pupil)} attached.`,
                              );
                              setAttaching(null);
                            }}
                          >
                            Attach
                          </Button>
                        )}
                      </Cell>
                    </Row>
                  ))}
                </Table>
              )}

              <Notice>{action.error}</Notice>
              <Notice tone="success">{action.success}</Notice>
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
